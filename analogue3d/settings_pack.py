"""Apply community-curated per-game settings to an Analogue 3D SD card.

The Analogue 3D stores per-game settings at:

    [SD]/Library/N64/Games/<title> <cartId>/settings.json

The cartId is a CRC32 of the first 8 KiB of the Z64 ROM, lowercased hex.
(See https://github.com/TheLeggett/A3D-Manager/blob/main/docs/CART_ID_ALGORITHM.md
for the reverse-engineered spec — same module's schema mirrored in
schema/game-settings.v1.json over at auntiepickle/Analogue3DSettings.)

This module fetches a community-curated collection from the
Analogue3DSettings repo, walks every cart folder on the user's SD card,
deep-merges the recommended settings into the cart's existing settings.json,
and writes back valid JSON. The Analogue 3D console writes JSON with
trailing commas; we read tolerantly and write strict so both tools agree.

Public API:

    list_collections(use_cache=True)         → [{id, name, description, ...}]
    fetch_collection(cid, use_cache=True)    → {games: {cartId: entry}, ...}
    card_carts(root)                         → [{cart_id, title, ...}]
    preview_apply(root, [cid1, cid2, ...])   → [{cart_id, current, after, diff}]
    apply_collections(root, [cid1, ...], snapshot=True, force=False) → summary

Multiple collections are applied in the order given; later collections'
fields override earlier ones (deep-merge).  Existing settings the user
customised are PRESERVED at every key the collections don't touch
(per-key overlay, not whole-object replace) unless force=True.
"""

import gc
import json
import os
import re
import stat
import time
import urllib.parse
import urllib.request

from . import config


def _robust_unlink(path, attempts=32, delay=0.25):
    """Delete a file, working around two Windows gotchas:

      * a read-only attribute (cleared before retrying), and
      * "the process cannot access the file because it is being used by another
        process" (WinError 32) — on an SD card, antivirus/Defender scans a file
        on-access for a few SECONDS after it's read (e.g. by the pre-delete
        backup), and the Search indexer or a not-yet-finalised reader can hold a
        handle too. Windows refuses the delete until every handle without
        share-delete is gone.

    Retries with a backoff long enough (~8s) to outlast a multi-second scan, and
    runs gc.collect() each round so any unreferenced file object still pinning a
    handle in this process is finalised. Raises the last error only if every
    attempt fails; treats an already-absent file as success."""
    last = None
    for i in range(attempts):
        try:
            os.unlink(path)
            return
        except FileNotFoundError:
            return
        except PermissionError as e:
            last = e
            if i == 0:
                try:
                    os.chmod(path, stat.S_IWRITE)   # clear read-only once
                except OSError:
                    pass
            gc.collect()                            # finalise any stray handle in-process
            time.sleep(delay)
        except OSError as e:
            last = e
            time.sleep(delay)
    if last:
        raise last

# Defaults; can be overridden by the caller passing repo=… (e.g. for a fork).
SETTINGS_REPO = "auntiepickle/Analogue3DSettings"
SETTINGS_BRANCH = "main"

# Per-collection on-disk cache. Lives next to update_check.json and the rest
# of the ~/.analogue3d/ state so it can be wiped with one command.
_CACHE_DIR  = os.path.join(os.path.dirname(config.config_path()), "settings_pack")
_CACHE_TTL  = 24 * 3600         # 24h is fine — these update on the order of weeks
_USER_AGENT = "Analogue3D-Utility-settings-pack/0.1"

# Cart folder pattern. The Analogue 3D firmware coins these as
# "Game Title aabbccdd" — title can contain spaces/punct; cartId is a fixed
# 8-char lowercase hex suffix at the end.
_FOLDER_RE = re.compile(r"^(.+?)\s+([0-9a-f]{8})$")

# Games root, relative to the SD card root. Used both for walking and for
# constructing settings.json paths.
GAMES_REL = os.path.join("Library", "N64", "Games")

def _strip_trailing_commas(raw):
    """Strip JSON trailing commas (before `}` or `]`) while leaving string
    contents alone. A regex like `,(\\s*[}\\]])` would also clobber a comma
    inside a string value of the form `"foo,]"`. Cheap state machine instead."""
    out = []
    i, n = 0, len(raw)
    in_str = False
    escape = False
    while i < n:
        c = raw[i]
        if in_str:
            out.append(c)
            if escape:
                escape = False
            elif c == "\\":
                escape = True
            elif c == '"':
                in_str = False
            i += 1
            continue
        if c == '"':
            in_str = True
            out.append(c); i += 1; continue
        if c == ",":
            # Lookahead past whitespace; drop the comma if next non-ws is ] or }.
            j = i + 1
            while j < n and raw[j] in " \t\r\n":
                j += 1
            if j < n and raw[j] in "}]":
                i += 1   # skip the comma
                continue
        out.append(c)
        i += 1
    return "".join(out)


# ----------------------------------------------------------------------
# network helpers (stdlib so the engine stays dep-light)
# ----------------------------------------------------------------------

def _http_get_json(url, timeout=20):
    req = urllib.request.Request(url, headers={
        "Accept": "application/json",
        "User-Agent": _USER_AGENT,
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _raw_url(path, repo=None, branch=None):
    return (f"https://raw.githubusercontent.com/"
            f"{repo or SETTINGS_REPO}/{branch or SETTINGS_BRANCH}/{path}")


def _api_url(path, repo=None):
    return f"https://api.github.com/repos/{repo or SETTINGS_REPO}/contents/{path}"


def _cache_file(name):
    os.makedirs(_CACHE_DIR, exist_ok=True)
    return os.path.join(_CACHE_DIR, name)


def _cache_fresh(path):
    try:
        return (time.time() - os.path.getmtime(path)) < _CACHE_TTL
    except OSError:
        return False


# ----------------------------------------------------------------------
# Collection discovery + fetch
# ----------------------------------------------------------------------

def list_collections(use_cache=True, repo=None):
    """Return [{id, name, description, version, updated, games_count}] for
    every collection the Analogue3DSettings repo ships. Walks the repo's
    `collections/` directory via the GitHub Contents API and pulls each
    collection's `collection.json` for the human-readable bits."""
    cache_path = _cache_file("collections_index.json")
    if use_cache and _cache_fresh(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            pass
    try:
        listing = _http_get_json(_api_url("collections", repo=repo))
    except Exception:
        if os.path.exists(cache_path):
            with open(cache_path, "r", encoding="utf-8") as f:
                return json.load(f)
        return []
    out = []
    for entry in listing:
        if entry.get("type") != "dir":
            continue
        cid = entry.get("name")
        if not cid:
            continue
        try:
            meta = _http_get_json(_raw_url(f"collections/{cid}/collection.json", repo=repo))
        except Exception:
            meta = {}
        # Pull games count cheaply via the games.json sitting next to meta —
        # one extra fetch per collection, fine since this is on-demand.
        games_count = None
        try:
            g = _http_get_json(_raw_url(f"collections/{cid}/games.json", repo=repo))
            games_count = len(g.get("games") or {})
        except Exception:
            pass
        out.append({
            "id":           cid,
            "name":         meta.get("name") or cid,
            "description":  meta.get("description") or "",
            "version":      meta.get("version"),
            "updated":      meta.get("updated"),
            "maintainers":  meta.get("maintainers") or [],
            "license":      meta.get("license"),
            "depends_on":   meta.get("depends_on") or [],
            "games_count":  games_count,
        })
    try:
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=2, ensure_ascii=False)
    except OSError:
        pass
    return out


def fetch_collection(collection_id, use_cache=True, repo=None):
    """Pull a collection's games.json. Cached per-collection 24h."""
    cache_path = _cache_file(f"{collection_id}.json")
    if use_cache and _cache_fresh(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            pass
    try:
        data = _http_get_json(_raw_url(
            f"collections/{collection_id}/games.json", repo=repo))
    except Exception:
        # Offline / 404: serve a stale cache if any. Saves a user's "apply"
        # action from blowing up just because their wifi blipped.
        if os.path.exists(cache_path):
            with open(cache_path, "r", encoding="utf-8") as f:
                return json.load(f)
        raise
    try:
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    except OSError:
        pass
    return data


# ----------------------------------------------------------------------
# SD card walking
# ----------------------------------------------------------------------

def card_carts(root):
    """Walk the SD card's game library and return an entry per cart folder:

        [{cart_id, title, folder_path, settings_path, has_existing_settings}, ...]

    `cart_id` is the lowercased 8-hex suffix extracted from the folder name.
    Folders that don't match the expected pattern are silently skipped —
    the console keeps a few special directories in there."""
    games_dir = os.path.join(root, GAMES_REL)
    if not os.path.isdir(games_dir):
        return []
    out = []
    games_dir_real = os.path.realpath(games_dir)
    for name in sorted(os.listdir(games_dir)):
        folder = os.path.join(games_dir, name)
        if not os.path.isdir(folder):
            continue
        # Skip symlinks that point outside the card — we don't want
        # apply_collections following a user-placed symlink and writing
        # settings.json files into unrelated parts of their filesystem.
        if os.path.islink(folder) and not os.path.realpath(folder).startswith(games_dir_real):
            continue
        m = _FOLDER_RE.match(name)
        if not m:
            continue
        title, cart_id = m.group(1), m.group(2).lower()
        settings_path = os.path.join(folder, "settings.json")
        out.append({
            "cart_id":               cart_id,
            "title":                 title,
            "folder_path":           folder,
            "settings_path":         settings_path,
            "has_existing_settings": os.path.isfile(settings_path),
        })
    return out


# ----------------------------------------------------------------------
# Read / merge / write
# ----------------------------------------------------------------------

def _read_existing(path):
    """Tolerantly read an Analogue-3D-written settings.json.

    The console writes JSON with trailing commas, which strict json.loads
    rejects. We strip those (string-aware) before parsing so a round-trip
    via this module preserves console-set fields the user wants to keep."""
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = f.read()
    except OSError:
        return {}
    if not raw.strip():
        return {}
    try:
        return json.loads(raw)
    except ValueError:
        try:
            return json.loads(_strip_trailing_commas(raw))
        except ValueError:
            return {}


def _deep_merge(base, overlay):
    """Per-key overlay: dicts merge recursively; everything else overwrites.
    `overlay` wins where both have the same key. Returns a new dict; inputs
    are not mutated.

    Semantic notes for future contributors:
    - Lists REPLACE wholesale (no append). The N64 settings schema has no
      list fields today; if one is added, decide whether the desired
      semantic is replace, append, or set-union and update this function.
    - An explicit `None` in overlay WIPES the corresponding base key
      (writes null over a subtree). Collections should omit a key to
      preserve the base, not set it to null."""
    if not isinstance(base, dict):
        return overlay
    out = dict(base)
    for k, v in (overlay or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _write_atomic(path, data):
    """Settings files live on the SD card — power loss mid-write would
    corrupt a single game's config. Write to a sibling tempfile and rename
    so the on-disk file is always a complete document or untouched.

    Caveat: `os.replace` is atomic on POSIX and NTFS, but the SD card is
    usually FAT32/exFAT, where rename is a metadata update without a
    journal guarantee. A power loss during the rename can leave EITHER
    the old or new file, but not a half-written hybrid (the prior write
    is what would be lost). The on-disk corruption window we're guarding
    against — partial JSON — is fully covered."""
    tmp = path + ".tmp"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
        # Same Windows lock as deletes: if the existing settings.json is briefly
        # held open (antivirus/indexer), os.replace raises WinError 32. Retry.
        last = None
        for _ in range(10):
            try:
                os.replace(tmp, path)
                last = None
                break
            except PermissionError as e:
                last = e
                try: os.chmod(path, stat.S_IWRITE)
                except OSError: pass
                time.sleep(0.15)
        if last:
            raise last
    except Exception:
        # Don't leave a stray .tmp lying around if dump or replace failed.
        try: os.unlink(tmp)
        except OSError: pass
        raise


# ----------------------------------------------------------------------
# Preview + apply
# ----------------------------------------------------------------------

def _resolve_recommended(collections_data, cart_id):
    """Walk `collections_data` (a list of {collection_id, games}) in order;
    deep-merge each matching entry's settings on top of the running total.
    Returns (merged_settings, [collection_ids_that_contributed])."""
    merged = {}
    sources = []
    for col in collections_data:
        entry = (col.get("games") or {}).get(cart_id)
        if not entry:
            continue
        settings = entry.get("settings") or {}
        if not settings:
            continue
        merged = _deep_merge(merged, settings)
        sources.append(col.get("collection_id") or col.get("_id"))
    return merged, sources


def preview_apply(root, collection_ids, repo=None):
    """Per-cart preview of what `apply_collections` would change.

        [{
          "cart_id":     "ac631da0",
          "title":       "Super Mario 64",
          "current":     {...},                       # current settings.json on card
          "after":       {...},                       # what it would become
          "diff":        [(dotted.key, current, after), ...],
          "sources":     ["community-best"],          # which collections wrote something
          "skipped":     "no_recommendation" | None,  # why this cart wouldn't change
        }, ...]
    """
    collections_data = []
    for cid in collection_ids:
        data = fetch_collection(cid, repo=repo)
        data["_id"] = cid
        collections_data.append(data)
    out = []
    for cart in card_carts(root):
        cart_id = cart["cart_id"]
        current = _read_existing(cart["settings_path"])
        recommended, sources = _resolve_recommended(collections_data, cart_id)
        if not recommended:
            out.append({**cart, "current": current, "after": current,
                        "diff": [], "sources": [], "skipped": "no_recommendation"})
            continue
        after = _deep_merge(current, recommended)
        out.append({**cart, "current": current, "after": after,
                    "diff": _diff(current, after), "sources": sources,
                    "skipped": None})
    return out


def _diff(a, b, prefix=""):
    """Flat-dotted-key diff between two nested dicts.
    Returns [(key.path, before, after), ...] where before/after differ."""
    out = []
    keys = set((a or {}).keys()) | set((b or {}).keys())
    for k in sorted(keys):
        av, bv = (a or {}).get(k), (b or {}).get(k)
        full = k if not prefix else f"{prefix}.{k}"
        if isinstance(av, dict) or isinstance(bv, dict):
            out.extend(_diff(av if isinstance(av, dict) else {},
                             bv if isinstance(bv, dict) else {},
                             prefix=full))
            continue
        if av != bv:
            out.append((full, av, bv))
    return out


def backup_settings_json(root):
    """Zip every existing settings.json on the card into one timestamped backup
    in the app's backup folder before we modify any of them. Returns
    (zip_path, count), or (None, 0) when the card has no settings files yet
    (nothing to lose). Unlike a save-state snapshot, this actually contains the
    files apply/revert change, so it's a real recovery point."""
    import zipfile
    from datetime import datetime
    from . import savestates
    paths = [c["settings_path"] for c in card_carts(root)
             if c["has_existing_settings"]]
    if not paths:
        return (None, 0)
    backup_dir = savestates._backup_dir()
    os.makedirs(backup_dir, exist_ok=True)
    base = os.path.join(root, GAMES_REL)
    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    zip_path = os.path.join(backup_dir, f"settings_{stamp}.zip")
    written = 0
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for p in paths:
            arc = os.path.relpath(p, base).replace(os.sep, "/")
            try:
                with open(p, "rb") as fh:
                    data = fh.read()
            except OSError:
                continue
            # Build the entry by hand rather than z.write(): ZipInfo.from_file
            # calls time.localtime(st_mtime), which raises [Errno 22] when the
            # Analogue 3D wrote the file with an out-of-range RTC timestamp
            # (e.g. the 1601 epoch when the console clock was never set). A fixed,
            # valid date_time sidesteps that so one bad file can't abort the backup.
            zi = zipfile.ZipInfo(arc)            # date_time defaults to 1980-01-01
            zi.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(zi, data)
            written += 1
    if not written:
        try:
            os.unlink(zip_path)
        except OSError:
            pass
        return (None, 0)
    return (zip_path, written)


def apply_collections(root, collection_ids, snapshot=True, force=False,
                      progress=None, repo=None):
    """Apply the chosen collections (in the given order) to every cart on
    the card that has a matching recommendation.

    `snapshot=True` (default) zips every existing settings.json on the card
    first (backup_settings_json), so the user can recover their pre-apply
    settings — the real files being changed, not save states. A card with no
    settings files yet returns (None, 0); apply continues and
    summary["settings_backup"] stays None (nothing to back up).

    `force=True` IGNORES the cart's existing settings.json entirely.
    The written file is the recommended dict alone (merged across
    `collection_ids` in order). Use sparingly — UI should label this as
    "replace ALL settings", not just "override collection-touched keys",
    because EVERY key not in the recommendation is wiped.

    `force=False` (default) preserves any user-set keys the collections
    don't touch — collection settings overlay on top of what's there
    via per-key deep-merge.

    Returns:

        {
          "applied":  [{cart_id, title, sources, settings_path}, ...],
          "skipped":  [{cart_id, title, reason}, ...],
          "errors":   [{cart_id, title, error}, ...],
          "settings_backup": {"path": "...", "count": N} | None,
        }
    """
    summary = {"applied": [], "skipped": [], "errors": [], "settings_backup": None}

    if snapshot:
        try:
            bpath, bcount = backup_settings_json(root)
            if bpath:
                summary["settings_backup"] = {"path": bpath, "count": bcount}
        except Exception as e:
            return {**summary, "errors": [
                {"cart_id": None, "title": None,
                 "error": f"Pre-apply settings backup failed: {e}. "
                          "Refusing to write without a backup. "
                          "Pass snapshot=False to override."}]}

    collections_data = []
    for cid in collection_ids:
        try:
            data = fetch_collection(cid, repo=repo)
            data["_id"] = cid
            collections_data.append(data)
        except Exception as e:
            summary["errors"].append({"cart_id": None, "title": None,
                                      "error": f"Couldn't fetch collection {cid!r}: {e}"})
    if not collections_data:
        return summary

    carts = card_carts(root)
    total = len(carts)
    for i, cart in enumerate(carts):
        if progress:
            try:
                progress(i, total, cart["title"])
            except Exception:
                pass
        cart_id = cart["cart_id"]
        recommended, sources = _resolve_recommended(collections_data, cart_id)
        if not recommended:
            summary["skipped"].append({"cart_id": cart_id, "title": cart["title"],
                                       "reason": "no_recommendation"})
            continue
        base = {} if force else _read_existing(cart["settings_path"])
        merged = _deep_merge(base, recommended)
        # Don't touch the SD card if the cart already has these exact settings —
        # rewriting an identical file is a pointless write (and a needless mtime
        # bump on flash). Only force-mode, which replaces wholesale, always writes.
        if not force and merged == base:
            summary["skipped"].append({"cart_id": cart_id, "title": cart["title"],
                                       "reason": "already_applied"})
            continue
        try:
            _write_atomic(cart["settings_path"], merged)
            summary["applied"].append({
                "cart_id": cart_id, "title": cart["title"],
                "sources": sources, "settings_path": cart["settings_path"],
            })
        except OSError as e:
            summary["errors"].append({"cart_id": cart_id, "title": cart["title"],
                                      "error": str(e)})
    if progress:
        try:
            progress(total, total, None)
        except Exception:
            pass
    return summary


# ----------------------------------------------------------------------
# Revert
# ----------------------------------------------------------------------

def _strip_recommended(current, recommended):
    """Remove from `current` every leaf that `recommended` set AND that still
    holds the recommended value, so a revert undoes exactly what a collection
    applied without clobbering values the user changed afterwards. Empty dicts
    are pruned. Returns (new_current, removed_count); inputs aren't mutated."""
    removed = 0

    def walk(cur, rec):
        nonlocal removed
        out = {}
        for k, v in cur.items():
            if k in rec:
                rv = rec[k]
                if isinstance(v, dict) and isinstance(rv, dict):
                    sub = walk(v, rv)
                    if sub:
                        out[k] = sub          # keep whatever didn't match
                    continue                  # else prune the now-empty subtree
                if v == rv:                   # same equality apply/_diff use
                    removed += 1
                    continue                  # this leaf was our applied value — drop it
            out[k] = v                        # untouched key, or user-changed value
        return out

    return walk(current or {}, recommended or {}), removed


def revert_collections(root, collection_ids, snapshot=True, progress=None, repo=None):
    """Undo a previous apply: for every cart, remove the values the given
    collections wrote (where the cart still holds them). A cart whose
    settings.json ends up empty has the file deleted, reverting it to the
    console's defaults. User-set keys the collections never touched, and values
    the user changed after applying, are preserved.

    Returns:
        {
          "reverted": [{cart_id, title, removed, settings_path}, ...],
          "skipped":  [{cart_id, title, reason}, ...],   # no_recommendation | not_applied
          "errors":   [{cart_id, title, error}, ...],
          "settings_backup": {"path": "...", "count": N} | None,
        }
    """
    summary = {"reverted": [], "skipped": [], "errors": [], "settings_backup": None}

    if snapshot:
        try:
            bpath, bcount = backup_settings_json(root)
            if bpath:
                summary["settings_backup"] = {"path": bpath, "count": bcount}
        except Exception as e:
            return {**summary, "errors": [
                {"cart_id": None, "title": None,
                 "error": f"Pre-revert settings backup failed: {e}. "
                          "Refusing to write without a backup. "
                          "Pass snapshot=False to override."}]}

    collections_data = []
    for cid in collection_ids:
        try:
            data = fetch_collection(cid, repo=repo)
            data["_id"] = cid
            collections_data.append(data)
        except Exception as e:
            summary["errors"].append({"cart_id": None, "title": None,
                                      "error": f"Couldn't fetch collection {cid!r}: {e}"})
    if not collections_data:
        return summary

    carts = card_carts(root)
    total = len(carts)
    for i, cart in enumerate(carts):
        if progress:
            try:
                progress(i, total, cart["title"])
            except Exception:
                pass
        cart_id = cart["cart_id"]
        recommended, _sources = _resolve_recommended(collections_data, cart_id)
        if not recommended:
            summary["skipped"].append({"cart_id": cart_id, "title": cart["title"],
                                       "reason": "no_recommendation"})
            continue
        current = _read_existing(cart["settings_path"])
        new_current, removed = _strip_recommended(current, recommended)
        if removed == 0:
            summary["skipped"].append({"cart_id": cart_id, "title": cart["title"],
                                       "reason": "not_applied"})
            continue
        try:
            if new_current:
                _write_atomic(cart["settings_path"], new_current)
            else:
                _robust_unlink(cart["settings_path"])
            summary["reverted"].append({"cart_id": cart_id, "title": cart["title"],
                                        "removed": removed,
                                        "settings_path": cart["settings_path"]})
        except OSError as e:
            summary["errors"].append({"cart_id": cart_id, "title": cart["title"],
                                      "error": str(e)})
    if progress:
        try:
            progress(total, total, None)
        except Exception:
            pass
    return summary


def reset_all(root, snapshot=True):
    """Remove every settings.json on the card, returning all carts to the
    console's defaults — a full "unapply", regardless of which collection (if
    any) wrote them. This also clears settings the user set by hand, so callers
    must warn clearly. Backs up existing settings first.

    Returns:
        {
          "reset":    [{cart_id, title, settings_path}, ...],
          "skipped":  [{cart_id, title, reason}, ...],   # "no_settings"
          "errors":   [{cart_id, title, error}, ...],
          "settings_backup": {"path": "...", "count": N} | None,
        }
    """
    summary = {"reset": [], "skipped": [], "errors": [], "settings_backup": None}

    if snapshot:
        try:
            bpath, bcount = backup_settings_json(root)
            if bpath:
                summary["settings_backup"] = {"path": bpath, "count": bcount}
        except Exception as e:
            return {**summary, "errors": [
                {"cart_id": None, "title": None,
                 "error": f"Pre-reset settings backup failed: {e}. "
                          "Refusing to delete without a backup. "
                          "Pass snapshot=False to override."}]}

    for cart in card_carts(root):
        if not cart["has_existing_settings"]:
            summary["skipped"].append({"cart_id": cart["cart_id"],
                                       "title": cart["title"], "reason": "no_settings"})
            continue
        try:
            _robust_unlink(cart["settings_path"])
            summary["reset"].append({"cart_id": cart["cart_id"], "title": cart["title"],
                                     "settings_path": cart["settings_path"]})
        except FileNotFoundError:
            summary["skipped"].append({"cart_id": cart["cart_id"],
                                       "title": cart["title"], "reason": "no_settings"})
        except OSError as e:
            summary["errors"].append({"cart_id": cart["cart_id"],
                                      "title": cart["title"], "error": str(e)})
    return summary
