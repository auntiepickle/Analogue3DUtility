"""User settings for the Analogue 3D tools - currently just where backups go.

Stored as JSON in the user's home so the CLI and the GUI share one setting.

Backups are large, user-facing files (SD-card zips, save-state snapshots, save
images) that someone will want to find, copy to another drive, or restore - so
the default lives in the user's *Documents* folder, not a hidden app-data dir.
Resolution honors OneDrive-redirected Documents on Windows and XDG user-dirs on
Linux. Earlier versions defaulted to the package directory; legacy_backup_root()
surfaces that so old backups aren't silently lost.
"""

import os
import sys
import json

APP_NAME = "Analogue3D"

_CONFIG_PATH = os.path.join(os.path.expanduser("~"), ".analogue3d", "config.json")
_LEGACY_ROOT = os.path.dirname(os.path.abspath(__file__))  # the old (pre-Documents) default
_BACKUP_SUBDIRS = ("backups", "memory_backups", "save_backups")


def _documents_dir():
    home = os.path.expanduser("~")
    if sys.platform == "win32":
        try:
            import ctypes
            import ctypes.wintypes as wt
            buf = ctypes.create_unicode_buffer(wt.MAX_PATH)
            # CSIDL_PERSONAL = 5, SHGFP_TYPE_CURRENT = 0 (honors OneDrive redirection)
            if ctypes.windll.shell32.SHGetFolderPathW(0, 5, 0, 0, buf) == 0:
                return buf.value
        except Exception:
            pass
        return os.path.join(home, "Documents")
    if sys.platform == "darwin":
        return os.path.join(home, "Documents")
    # Linux: respect XDG user-dirs (Documents may be localized/relocated)
    xdg = os.path.join(os.environ.get("XDG_CONFIG_HOME", os.path.join(home, ".config")),
                       "user-dirs.dirs")
    try:
        with open(xdg, encoding="utf-8") as f:
            for line in f:
                if line.startswith("XDG_DOCUMENTS_DIR"):
                    p = line.split("=", 1)[1].strip().strip('"')
                    return os.path.expandvars(p.replace("$HOME", home))
    except OSError:
        pass
    return os.path.join(home, "Documents")


def default_backup_root():
    return os.path.join(_documents_dir(), APP_NAME)


def _load():
    try:
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save(cfg):
    os.makedirs(os.path.dirname(_CONFIG_PATH), exist_ok=True)
    with open(_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)


def config_path():
    return _CONFIG_PATH


def get_backup_root():
    root = _load().get("backup_root")
    return root if root else default_backup_root()


def is_custom_backup_root():
    return bool(_load().get("backup_root"))


def set_backup_root(path):
    cfg = _load()
    if path:
        cfg["backup_root"] = path
    else:
        cfg.pop("backup_root", None)  # empty resets to default
    _save(cfg)
    return get_backup_root()


def backup_dir(sub):
    """Absolute path of a backup subfolder under the configured backup root."""
    return os.path.join(get_backup_root(), sub)


def legacy_backup_root():
    """The old package-dir default, but only if it still holds backups - so the
    GUI/CLI can point users at backups made before the default moved. Else None."""
    for sub in _BACKUP_SUBDIRS:
        d = os.path.join(_LEGACY_ROOT, sub)
        try:
            if os.path.isdir(d) and any(os.scandir(d)):
                return _LEGACY_ROOT
        except OSError:
            pass
    return None
