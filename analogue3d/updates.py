"""Is there a newer release of this tool itself?

A lightweight check against the GitHub Releases API. It is cached for a day and
fails silently (offline, rate-limited, no releases yet), so it never slows down
or blocks a launch. Used by both the CLI banner and the desktop app's header.
"""

import os
import re
import json
import time

from . import config

# Public repos that ship released builds.
CLI_REPO = "auntiepickle/Analogue3DUtility"
GUI_REPO = "auntiepickle/Analogue3DDesktop"  # keep in sync if the repo is renamed

_CACHE_PATH = os.path.join(os.path.dirname(config.config_path()), "update_check.json")
_CACHE_TTL = 24 * 3600  # one network check per day is plenty
_NUM_RE = re.compile(r"\d+")


def parse_version(s):
    """'v0.6.1' / '0.6.1' -> (0, 6, 1). Non-numeric chunks are ignored."""
    if not s:
        return ()
    return tuple(int(x) for x in _NUM_RE.findall(s))


def _fetch_release_json(repo):
    import requests
    url = f"https://api.github.com/repos/{repo}/releases/latest"
    r = requests.get(url, timeout=6, headers={"Accept": "application/vnd.github+json"})
    r.raise_for_status()
    return r.json()


def _fetch_latest(repo):
    data = _fetch_release_json(repo)
    return {
        "tag": data.get("tag_name") or "",
        "url": data.get("html_url") or f"https://github.com/{repo}/releases/latest",
    }


def latest_asset(repo, contains):
    """Download info for the latest-release asset whose name contains `contains`
    (case-insensitive), e.g. 'windows' or 'macos'. Returns {name, url, tag} or
    None. Not cached - only called when the user actually triggers an update."""
    try:
        data = _fetch_release_json(repo)
    except Exception:
        return None
    sub = (contains or "").lower()
    for a in data.get("assets", []):
        name = a.get("name", "")
        if sub in name.lower():
            return {
                "name": name,
                "url": a.get("browser_download_url", ""),
                "tag": data.get("tag_name", ""),
            }
    return None


def _load_cache():
    try:
        with open(_CACHE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save_cache(cache):
    try:
        os.makedirs(os.path.dirname(_CACHE_PATH), exist_ok=True)
        with open(_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(cache, f)
    except OSError:
        pass


def latest_tag(repo, use_cache=True):
    """{'tag', 'url'} for the repo's latest release, or None. Cached daily; on any
    failure falls back to a stale cache entry if present, else returns None."""
    cache = _load_cache() if use_cache else {}
    entry = cache.get(repo)
    if use_cache and entry and (time.time() - entry.get("at", 0)) < _CACHE_TTL:
        return {"tag": entry.get("tag", ""), "url": entry.get("url", "")}
    try:
        info = _fetch_latest(repo)
    except Exception:
        if entry:
            return {"tag": entry.get("tag", ""), "url": entry.get("url", "")}
        return None
    cache[repo] = {"tag": info["tag"], "url": info["url"], "at": time.time()}
    _save_cache(cache)
    return info


def check(current, repo, use_cache=True):
    """Compare `current` (e.g. '0.6.1') with the repo's latest release tag.
    Returns {'current', 'latest', 'url', 'update_available'} or None if unknown."""
    info = latest_tag(repo, use_cache=use_cache)
    if not info or not info.get("tag"):
        return None
    latest = info["tag"]
    return {
        "current": current,
        "latest": latest.lstrip("vV"),
        "url": info["url"],
        "update_available": parse_version(latest) > parse_version(current),
    }
