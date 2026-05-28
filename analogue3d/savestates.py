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
from datetime import datetime

MEM_SUBPATH = ("Memories", "N64")
DEFAULT_KEEP = 20  # the console's per-game save-state cap

_ID_RE = re.compile(r"([0-9a-fA-F]{8})\s*$")
_TS_RE = re.compile(r"(\d{14})\.png$", re.IGNORECASE)


def _backup_dir():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "memory_backups")


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


def backup_state(state_path, cart_id, name=None):
    """Copy one save-state PNG (verbatim) into the local backup folder."""
    dest_dir = os.path.join(_backup_dir(), cart_id)
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, name or os.path.basename(state_path))
    shutil.copy2(state_path, dest)
    return dest


def backup_game(game):
    """Back up every state of one game. Returns the number copied."""
    for s in game["states"]:
        backup_state(s["path"], game["cart_id"], s["name"])
    return len(game["states"])


def list_backups():
    """Return {cart_id: [backup_path, ...]} of locally stored state backups."""
    root = _backup_dir()
    out = {}
    if not os.path.isdir(root):
        return out
    for cart_id in sorted(os.listdir(root)):
        d = os.path.join(root, cart_id)
        if os.path.isdir(d):
            pngs = sorted((os.path.join(d, f) for f in os.listdir(d)
                           if f.lower().endswith(".png")), reverse=True)
            if pngs:
                out[cart_id] = pngs
    return out


def trim_to_latest(game, keep=DEFAULT_KEEP, backup_first=True):
    """Delete all but the newest `keep` states for a game, archiving the removed
    ones to the local backup folder first (unless backup_first is False).
    Returns (removed_count, kept_count)."""
    keep = max(0, keep)
    states = game["states"]  # newest-first
    to_remove = states[keep:]
    for s in to_remove:
        if backup_first:
            backup_state(s["path"], game["cart_id"], s["name"])
        try:
            os.remove(s["path"])
        except OSError:
            pass
    return len(to_remove), min(keep, len(states))


def restore_state(backup_path, game_folder_path):
    """Copy a backed-up state PNG back into a game's Memories folder."""
    os.makedirs(game_folder_path, exist_ok=True)
    dest = os.path.join(game_folder_path, os.path.basename(backup_path))
    shutil.copy2(backup_path, dest)
    return dest


__all__ = [
    "find_game_states", "find_game", "memories_dir", "thumbnail",
    "backup_state", "backup_game", "list_backups", "trim_to_latest",
    "restore_state", "DEFAULT_KEEP",
]
