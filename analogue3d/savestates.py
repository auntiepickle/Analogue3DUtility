"""Save-state ("Memories") management for the Analogue 3D.

Save states live on the SD card at:
    Memories/N64/<Title> <8hexid>/<Title> - <YYYYMMDDHHMMSS>.png

Each .png is a ~9 MB file: a 320x240 screenshot whose emulator save state is
carried *inside* the PNG (the image data ends with a normal IEND; the state
rides along in the file). That means two things:
  * backups/restores must copy the whole PNG verbatim - the state is in there;
  * thumbnails are cheap, because PIL only decodes the little screenshot.

The console caps how many states you can keep per game, so this module lets you
back them up, restore them, and trim a game down to its newest N (archiving the
rest first). Backups are copied verbatim into a folder next to the tool, matching
the controller-pak save convention in saves.py.
"""

import os
import re
import io
import shutil
import zipfile
from datetime import datetime

from . import config, ui

MEM_SUBPATH = ("Memories", "N64")
DEFAULT_KEEP = 20  # the console's per-game save-state cap

_ID_RE = re.compile(r"([0-9a-fA-F]{8})\s*$")
_TS_RE = re.compile(r"(\d{14})\.png$", re.IGNORECASE)


def _backup_dir():
    return config.backup_dir("memory_backups")


def memories_dir(sd_root):
    return os.path.join(sd_root, *MEM_SUBPATH)


def _parse_ts(filename):
    """Pull the YYYYMMDDHHMMSS stamp out of a state filename, as a datetime."""
    m = _TS_RE.search(filename)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%Y%m%d%H%M%S")
    except ValueError:
        return None


def find_game_states(sd_root):
    """Return a list of game dicts, each with its save states sorted newest-first."""
    base = memories_dir(sd_root)
    games = []
    if not os.path.isdir(base):
        return games
    for folder in sorted(os.listdir(base)):
        folder_path = os.path.join(base, folder)
        if not os.path.isdir(folder_path):
            continue
        m = _ID_RE.search(folder)
        cart_id = m.group(1).lower() if m else "????????"
        title = folder[:m.start()].strip() if m else folder
        states = []
        for f in sorted(os.listdir(folder_path)):
            if not f.lower().endswith(".png"):
                continue
            p = os.path.join(folder_path, f)
            try:
                size = os.path.getsize(p)
            except OSError:
                continue
            ts = _parse_ts(f)
            states.append({
                "name": f,
                "path": p,
                "bytes": size,
                "ts": ts.strftime("%Y%m%d%H%M%S") if ts else "",
                "when": ts.strftime("%Y-%m-%d %H:%M") if ts else "unknown",
                "_sort": ts or datetime.min,
            })
        states.sort(key=lambda s: s["_sort"], reverse=True)
        for s in states:
            s.pop("_sort", None)
        games.append({
            "title": title or folder,
            "cart_id": cart_id,
            "folder": folder,
            "path": folder_path,
            "count": len(states),
            "total_bytes": sum(s["bytes"] for s in states),
            "states": states,
        })
    return games


def find_game(sd_root, folder):
    """Look up a single game by its on-card folder name."""
    for g in find_game_states(sd_root):
        if g["folder"] == folder:
            return g
    return None


def thumbnail(png_path, max_px=260, quality=82):
    """Return JPEG bytes of a small thumbnail of the screenshot inside a state PNG."""
    from PIL import Image
    with Image.open(png_path) as im:
        im.load()
        im.thumbnail((max_px, max_px))
        buf = io.BytesIO()
        im.convert("RGB").save(buf, "JPEG", quality=quality)
        return buf.getvalue()


SNAPSHOT_PREFIX = "memories_"


def _split_folder(folder):
    """(title, cart_id) from a '<Title> <8hexid>' game folder name."""
    m = _ID_RE.search(folder)
    cart_id = m.group(1).lower() if m else "????????"
    title = folder[:m.start()].strip() if m else folder
    return title or folder, cart_id


def archive_all(sd_root):
    """Zip every save state on the card into one timestamped snapshot, preserving
    the per-game folder structure inside (so a single game can be restored later).
    Returns (zip_path, n_states); (None, 0) if there are no save states."""
    games = find_game_states(sd_root)
    total = sum(g["count"] for g in games)
    if total == 0:
        return (None, 0)
    os.makedirs(_backup_dir(), exist_ok=True)
    base = memories_dir(sd_root)
    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    zip_path = os.path.join(_backup_dir(), f"{SNAPSHOT_PREFIX}{stamp}.zip")
    # PNGs are already compressed, so store (don't re-deflate) for speed.
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_STORED) as z:
        for g in games:
            for s in g["states"]:
                arc = os.path.relpath(s["path"], base).replace(os.sep, "/")
                z.write(s["path"], arc)
    return (zip_path, total)


def _snapshot_path(name):
    return os.path.join(_backup_dir(), os.path.basename(name))


def list_snapshots():
    """All snapshot zips, newest first, each with the per-game breakdown it holds."""
    d = _backup_dir()
    out = []
    if not os.path.isdir(d):
        return out
    for name in os.listdir(d):
        if not (name.startswith(SNAPSHOT_PREFIX) and name.lower().endswith(".zip")):
            continue
        path = os.path.join(d, name)
        out.append({
            "name": name,
            "bytes": os.path.getsize(path),
            "games": snapshot_games(name),
        })
    out.sort(key=lambda s: s["name"], reverse=True)
    return out


def snapshot_games(name):
    """Per-game breakdown of a snapshot: [{cart_id, title, count}], by title."""
    path = _snapshot_path(name)
    games = {}
    if not os.path.isfile(path):
        return []
    with zipfile.ZipFile(path) as z:
        for n in z.namelist():
            if n.endswith("/"):
                continue
            parts = n.split("/")
            folder = parts[-2] if len(parts) >= 2 else ""
            title, cart_id = _split_folder(folder)
            g = games.setdefault(cart_id, {"cart_id": cart_id, "title": title, "count": 0})
            g["count"] += 1
    return sorted(games.values(), key=lambda g: g["title"].lower())


def restore_snapshot(sd_root, name, cart_id=None):
    """Restore a snapshot back onto the card. If cart_id is given, only that game's
    states are restored; otherwise the whole snapshot. Returns how many were written."""
    path = _snapshot_path(name)
    if not os.path.isfile(path):
        raise FileNotFoundError(name)
    base = memories_dir(sd_root)
    os.makedirs(base, exist_ok=True)
    n = 0
    with zipfile.ZipFile(path) as z:
        for info in z.infolist():
            if info.is_dir():
                continue
            parts = info.filename.split("/")
            folder = parts[-2] if len(parts) >= 2 else ""
            if cart_id and _split_folder(folder)[1] != cart_id:
                continue
            dest = os.path.join(base, *parts)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with z.open(info) as src, open(dest, "wb") as out:
                shutil.copyfileobj(src, out)
            n += 1
    return n


def delete_snapshot(name):
    path = _snapshot_path(name)
    if os.path.isfile(path):
        os.remove(path)
        return True
    return False


def trim_to_latest(game, keep=DEFAULT_KEEP):
    """Delete all but the newest `keep` states for a game (newest-first already).
    Returns (removed_count, kept_count). Caller is responsible for archiving first."""
    keep = max(0, keep)
    to_remove = game["states"][keep:]
    for s in to_remove:
        try:
            os.remove(s["path"])
        except OSError:
            pass
    return len(to_remove), min(keep, game["count"])


def delete_state(state_path):
    """Delete a single save-state file from the card."""
    if os.path.isfile(state_path):
        os.remove(state_path)
        return True
    return False


def _restore_flow(sd_root, snaps):
    snap = ui.select("Restore from which snapshot?",
                     [(s["name"], s["name"]) for s in snaps] + [("Cancel", "cancel")])
    if snap in (None, "cancel"):
        return
    sgames = snapshot_games(snap)
    scope = ui.select("Restore what?",
                      [("Everything in this snapshot", "all")] +
                      [(f"Just {g['title']} [{g['cart_id']}] ({g['count']})", g["cart_id"]) for g in sgames] +
                      [("Cancel", "cancel")])
    if scope in (None, "cancel"):
        return
    if not ui.confirm("Restore onto the card? Files with the same name are overwritten.", default=False):
        return
    try:
        n = restore_snapshot(sd_root, snap, cart_id=None if scope == "all" else scope)
    except FileNotFoundError:
        ui.err("Snapshot not found.")
        return
    ui.ok(f"Restored {n} save state(s) from {snap}.")


def _trim_flow(sd_root, games):
    folder = ui.select("Trim which game to its newest N?",
                       [(f"{g['title']} [{g['cart_id']}] ({g['count']})", g["folder"]) for g in games] +
                       [("Cancel", "cancel")])
    if folder in (None, "cancel"):
        return
    g = find_game(sd_root, folder)
    if not g:
        ui.err("Game not found on the card.")
        return
    raw = ui.text(f"Keep how many newest? (default {DEFAULT_KEEP})") or str(DEFAULT_KEEP)
    try:
        keep = max(0, int(raw))
    except ValueError:
        ui.err("Not a number.")
        return
    if not ui.confirm(f"Snapshot everything first, then keep the newest {keep} of {g['title']}?", default=True):
        return
    archive_all(sd_root)  # safety snapshot before deleting
    removed, kept = trim_to_latest(g, keep=keep)
    ui.ok(f"{g['title']}: removed {removed} older state(s); kept the newest {kept}.")


def _delete_snapshot_flow(snaps):
    snap = ui.select("Delete which snapshot?",
                     [(s["name"], s["name"]) for s in snaps] + [("Cancel", "cancel")])
    if snap in (None, "cancel"):
        return
    if not ui.confirm(f"Delete {snap}? This can't be undone.", default=False):
        return
    delete_snapshot(snap)
    ui.ok("Snapshot deleted.")


def run_interactive(sd_root):
    print("\n=== Save States (Memories) ===")
    while True:
        games = find_game_states(sd_root)
        snaps = list_snapshots()
        total = sum(g["count"] for g in games)
        ui.info(f"  {ui.DOT} {total} save state(s) across {len(games)} game(s) on the card; "
                f"{len(snaps)} local snapshot(s).")
        action = ui.select("Save states", [
            ("Archive all save states now (snapshot)", "archive"),
            ("Restore from a snapshot (all or one game)", "restore"),
            ("Trim a game to its newest N", "trim"),
            ("Delete a snapshot", "delsnap"),
            ("List games and states", "list"),
            ("Back", "back"),
        ])
        if action in (None, "back"):
            return
        if action == "archive":
            path, n = archive_all(sd_root)
            if path:
                ui.ok(f"Archived {n} save state(s) -> {os.path.basename(path)}")
            else:
                ui.warn("No save states on the card to archive.")
        elif action == "list":
            if not games:
                ui.warn("No save states on the card.")
            for g in games:
                ui.info(f"  {g['title']} [{g['cart_id']}] - {g['count']} state(s), "
                        f"{g['total_bytes'] // (1024 * 1024)} MB")
        elif action == "restore":
            if not snaps:
                ui.warn("No snapshots yet - archive first.")
            else:
                _restore_flow(sd_root, snaps)
        elif action == "trim":
            if not games:
                ui.warn("No save states on the card.")
            else:
                _trim_flow(sd_root, games)
        elif action == "delsnap":
            if not snaps:
                ui.warn("No snapshots to delete.")
            else:
                _delete_snapshot_flow(snaps)
        ui.rule()


__all__ = [
    "find_game_states", "find_game", "memories_dir", "thumbnail",
    "archive_all", "list_snapshots", "snapshot_games", "restore_snapshot",
    "delete_snapshot", "trim_to_latest", "delete_state", "run_interactive",
    "DEFAULT_KEEP",
]
