#!/usr/bin/env python3
"""
Analogue 3D Utility - one tool for the Analogue 3D console and its 8BitDo 64 pad.

This is the launcher: run `python a3d.py`. It bootstraps any missing Python
packages (so you can run it with nothing but Python installed), then hands off to
the `analogue3d` package, which is organized as:

    analogue3d/ui.py          shared terminal helpers (colors, prompts)
    analogue3d/cli.py         the interactive menu
    analogue3d/sdcard.py      console firmware, cartridge labels, backups
    analogue3d/labels.py      custom cartridge artwork
    analogue3d/saves.py       controller-pak save backup/restore
    analogue3d/controller.py  8BitDo 64 controller firmware flashing (USB-C)
"""

import sys
import subprocess


def _ensure_dependencies():
    """Detect missing packages and offer to pip-install them, so a user can just
    run the script. requests/bs4/psutil are required; hidapi (controller) and
    pillow (custom artwork) are optional."""
    required = [("requests", "requests"), ("bs4", "beautifulsoup4"), ("psutil", "psutil")]
    optional = [("hid", "hidapi"), ("PIL", "pillow"),
                ("rich", "rich"), ("questionary", "questionary")]

    def missing(items):
        out = []
        for mod, pkg in items:
            try:
                __import__(mod)
            except ImportError:
                out.append(pkg)
        return out

    miss_req, miss_opt = missing(required), missing(optional)
    if not miss_req and not miss_opt:
        return

    print("This tool needs a few Python packages that aren't installed yet:")
    print("   " + ", ".join(miss_req + miss_opt))
    try:
        answer = input("Install them now with pip? [Y/n]: ").strip().lower()
    except EOFError:
        answer = "y"
    if answer not in ("", "y", "yes"):
        if miss_req:
            print("Can't continue without: " + ", ".join(miss_req))
            print("Install manually:  pip install " + " ".join(miss_req))
            sys.exit(1)
        return

    def pip_install(pkgs):
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", *pkgs])
            return True
        except (subprocess.CalledProcessError, OSError):
            return False

    if miss_req and not pip_install(miss_req):
        print("Auto-install failed. Please run:  pip install " + " ".join(miss_req))
        sys.exit(1)
    if miss_opt and not pip_install(miss_opt):
        print("Note: couldn't install " + ", ".join(miss_opt) +
              " (only needed for some features) - continuing without them.")
    if missing(required):
        print("Packages still missing. Please run:  pip install " + " ".join(miss_req))
        sys.exit(1)


if __name__ == "__main__":
    _ensure_dependencies()          # must run before importing the package (it needs requests/etc.)
    from analogue3d.cli import main
    main()
