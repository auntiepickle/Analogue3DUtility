"""User settings for the Analogue 3D tools - currently just where backups go.

Stored as JSON in the user's home so the CLI and the GUI share one setting. The
default backup root is this package's own directory (where backups have always
lived), so existing backups keep working until the user picks a new location.
"""

import os
import json

_CONFIG_PATH = os.path.join(os.path.expanduser("~"), ".analogue3d", "config.json")
_DEFAULT_BACKUP_ROOT = os.path.dirname(os.path.abspath(__file__))


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
    return root if root else _DEFAULT_BACKUP_ROOT


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
