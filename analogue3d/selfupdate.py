"""In-place self-update for the frozen CLI binary.

Downloads the latest release asset for this platform next to the running
executable, then hands off to a tiny detached helper that waits for us to exit,
swaps the new file in, and relaunches it. Only meaningful for PyInstaller
one-file builds; running from source should update via git/pip instead.

Mirrors the desktop app's proven mechanism. The one subtlety that bit us before:
the relaunch helper must run with PyInstaller's one-file markers stripped from the
environment (_MEIPASS2 etc.), or the freshly-swapped exe inherits our extraction
dir and fails with "Failed to load Python DLL".
"""

import os
import sys
import stat
import tempfile
import subprocess

from . import updates


def can_self_update():
    """True only for a frozen one-file build on a platform we know how to swap."""
    return bool(getattr(sys, "frozen", False)) and sys.platform in ("win32", "darwin", "linux")


def _asset_substring():
    """The release-asset name fragment for this platform (a3d-<this>...)."""
    if sys.platform == "win32":
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    return "linux"


def _clean_child_env():
    """Environment for the relaunch helper with PyInstaller's one-file markers
    removed, so the swapped-in exe extracts and loads its OWN Python/DLLs."""
    return {k: v for k, v in os.environ.items()
            if not (k.startswith("_MEIPASS") or k.startswith("_PYI"))}


def _download(url, dest, progress=None):
    """Stream `url` to `dest`, calling progress(pct) as it goes (if given)."""
    import requests
    with requests.get(url, stream=True, timeout=60) as r:
        r.raise_for_status()
        total = int(r.headers.get("Content-Length") or 0)
        done, last = 0, -1
        with open(dest, "wb") as f:
            for chunk in r.iter_content(65536):
                if not chunk:
                    continue
                f.write(chunk)
                done += len(chunk)
                if progress and total:
                    pct = min(100, done * 100 // total)
                    if pct != last:
                        last = pct
                        progress(pct)
    return dest


def _swap_and_restart_windows(exe, new_file):
    """Hand off to a helper .bat that swaps the exe and relaunches it. A running
    one-file .exe stays locked for a moment after we exit, so the move is retried
    until it succeeds. `ping` provides the delay (`timeout` needs console input we
    don't have); a hidden console lets start/ping/move run without a window flash."""
    fd, bat = tempfile.mkstemp(suffix=".bat")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(
            "@echo off\r\n"
            "setlocal\r\n"
            "set tries=0\r\n"
            ":retry\r\n"
            f'move /Y "{new_file}" "{exe}" >nul 2>&1\r\n'
            "if not errorlevel 1 goto launch\r\n"
            "set /a tries+=1\r\n"
            "if %tries% geq 90 goto launch\r\n"
            "ping -n 2 127.0.0.1 >nul\r\n"
            "goto retry\r\n"
            ":launch\r\n"
            "ping -n 2 127.0.0.1 >nul\r\n"
            f'start "" "{exe}"\r\n'
            'del "%~f0"\r\n'
        )
    CREATE_NO_WINDOW = 0x08000000
    subprocess.Popen(["cmd", "/c", bat], creationflags=CREATE_NO_WINDOW,
                     close_fds=True, env=_clean_child_env())


def _swap_and_restart_posix(exe, new_file):
    """macOS/Linux: the build is a single-file binary (not a .app bundle). Wait for
    this process to exit, move the new file over the old one, make it executable,
    and relaunch it detached."""
    pid = os.getpid()
    fd, sh = tempfile.mkstemp(suffix=".sh")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(
            "#!/bin/sh\n"
            f'while kill -0 {pid} 2>/dev/null; do sleep 1; done\n'
            f'mv "{new_file}" "{exe}"\n'
            f'chmod +x "{exe}"\n'
            f'"{exe}" &\n'
            'rm -f "$0"\n'
        )
    os.chmod(sh, 0o755)
    subprocess.Popen(["/bin/sh", sh], close_fds=True, env=_clean_child_env())


def self_update(progress=None):
    """Download the latest release binary for this platform and start the helper
    that swaps it in and relaunches. On success the caller should exit the process
    promptly so the file lock releases and the swap can complete.

    Returns {'ok': bool, 'tag'/'error': str}. Raises nothing - failures come back
    in the dict so the CLI can report them cleanly."""
    if not can_self_update():
        return {"ok": False, "error": "this build can't self-update (run from source: use git/pip)"}
    try:
        info = updates.latest_asset(updates.CLI_REPO, _asset_substring())
    except Exception as e:
        return {"ok": False, "error": f"couldn't reach GitHub: {e}"}
    if not info or not info.get("url"):
        return {"ok": False, "error": "no matching download in the latest release"}

    exe = sys.executable
    new_file = exe + ".new"
    try:
        _download(info["url"], new_file, progress=progress)
        if sys.platform == "win32":
            _swap_and_restart_windows(exe, new_file)
        else:
            os.chmod(new_file, os.stat(new_file).st_mode
                     | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
            _swap_and_restart_posix(exe, new_file)
    except Exception as e:
        try:
            if os.path.exists(new_file):
                os.remove(new_file)
        except OSError:
            pass
        return {"ok": False, "error": str(e)}

    return {"ok": True, "tag": info.get("tag", "")}
