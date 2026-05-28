"""Controller-Pak (N64 memory pak) save backup & restore for the Analogue 3D.

Saves live on the SD card at:
    Library/N64/Games/<Title> <8hexid>/controller_pak.img
Each is a standard N64 Controller-Pak image: exactly 32768 bytes, 128 pages of
256 bytes. The page-usage (INODE) table starts at 0x100, two bytes per page,
big-endian; 0x0003 means a free page. Pages 0-4 are system; pages 5-127 (123
pages) hold the actual save data. Backups are copied verbatim (md5-tracked) to a
local folder next to this tool.
"""

import os
import re
import struct
import shutil
import hashlib
from datetime import datetime

from ui import bold, dim, green, yellow, red, ask

PAK_SIZE = 32768
PAGE_SIZE = 256
PAGE_COUNT = 128
FIRST_DATA_PAGE = 5          # pages 0-4 are system
USER_PAGES = PAGE_COUNT - FIRST_DATA_PAGE   # 123
INODE_TABLE = 0x100
PAGE_FREE = 0x0003
PAK_FILENAME = "controller_pak.img"
GAMES_SUBPATH = ("Library", "N64", "Games")
_ID_RE = re.compile(r"([0-9a-fA-F]{8})\s*$")


def _backup_dir():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "save_backups")


def used_pages(data):
    """Count occupied user pages (5..127) in a 32KB pak image."""
    if len(data) < PAK_SIZE:
        return 0
    used = 0
    for page in range(FIRST_DATA_PAGE, PAGE_COUNT):
        (val,) = struct.unpack_from(">H", data, INODE_TABLE + page * 2)
        if val != PAGE_FREE:
            used += 1
    return used


def find_game_saves(sd_root):
    """Return a list of dicts for every game folder that has a controller_pak.img."""
    games_dir = os.path.join(sd_root, *GAMES_SUBPATH)
    saves = []
    if not os.path.isdir(games_dir):
        return saves
    for folder in sorted(os.listdir(games_dir)):
        folder_path = os.path.join(games_dir, folder)
        pak = os.path.join(folder_path, PAK_FILENAME)
        if not os.path.isfile(pak):
            continue
        m = _ID_RE.search(folder)
        cart_id = m.group(1).lower() if m else "????????"
        name = folder[:m.start()].strip() if m else folder
        try:
            data = open(pak, "rb").read()
        except OSError:
            continue
        saves.append({
            "name": name or folder,
            "cart_id": cart_id,
            "path": pak,
            "size": len(data),
            "used": used_pages(data),
        })
    return saves


def backup_save(save):
    """Copy a save into the local backup folder. Returns the backup path."""
    dest_dir = os.path.join(_backup_dir(), save["cart_id"])
    os.makedirs(dest_dir, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    dest = os.path.join(dest_dir, f"{stamp}.img")
    shutil.copy2(save["path"], dest)
    return dest


def list_backups():
    """Return {cart_id: [backup_path, ...]} of locally stored save backups."""
    root = _backup_dir()
    out = {}
    if not os.path.isdir(root):
        return out
    for cart_id in sorted(os.listdir(root)):
        d = os.path.join(root, cart_id)
        if os.path.isdir(d):
            imgs = sorted((os.path.join(d, f) for f in os.listdir(d) if f.endswith(".img")),
                          reverse=True)
            if imgs:
                out[cart_id] = imgs
    return out


def restore_save(backup_path, dest_path):
    data = open(backup_path, "rb").read()
    if len(data) != PAK_SIZE:
        raise ValueError(f"backup is {len(data)} bytes, expected {PAK_SIZE}")
    shutil.copy2(backup_path, dest_path)


def run_interactive(sd_root):
    print("\n=== Controller-Pak Saves ===")
    saves = find_game_saves(sd_root)
    if not saves:
        print(yellow("No game saves found on the SD card."))
        print(dim(f"(looked in {os.path.join(sd_root, *GAMES_SUBPATH)})"))
        return

    print("Games with save data:")
    for i, s in enumerate(saves, 1):
        meter = f"{s['used']}/{USER_PAGES} pages"
        flag = dim("  (empty)") if s["used"] == 0 else ""
        print(f"  {bold(str(i))})  {s['name']} {dim('[' + s['cart_id'] + ']')}  {dim(meter)}{flag}")
    print(f"\n  {bold('a')})  Back up ALL")
    print(f"  {bold('r')})  Restore a backup")
    print(f"  {bold('0')})  Cancel (back to menu)")

    choice = ask("\nBack up which game? (number / a / r / 0): ").lower()
    if choice in ("", "0", "q", "quit"):
        print("Cancelled.")
        return

    if choice == "r":
        _restore_flow(saves)
        return

    if choice == "a":
        targets = saves
    else:
        try:
            targets = [saves[int(choice) - 1]]
        except (ValueError, IndexError):
            print(red("Invalid selection."))
            return

    for s in targets:
        dest = backup_save(s)
        print(green(f"Backed up {s['name']} -> ") + dim(dest))
    print(green(f"\nDone - {len(targets)} save(s) backed up."))


def _restore_flow(saves):
    backups = list_backups()
    if not backups:
        print(yellow("No save backups found yet."))
        return
    by_id = {s["cart_id"]: s for s in saves}
    items = []
    print("\nAvailable backups:")
    for cart_id, paths in backups.items():
        target = by_id.get(cart_id)
        name = target["name"] if target else dim("(no matching game on card)")
        for p in paths:
            items.append((p, target))
            stamp = os.path.basename(p)[:-4]
            print(f"  {bold(str(len(items)))})  {name} {dim('[' + cart_id + ']')}  {dim(stamp)}")
    print(f"  {bold('0')})  Cancel")

    choice = ask("\nRestore which backup? (number / 0): ").lower()
    if choice in ("", "0", "q", "quit"):
        print("Cancelled.")
        return
    try:
        backup_path, target = items[int(choice) - 1]
    except (ValueError, IndexError):
        print(red("Invalid selection."))
        return
    if target is None:
        print(red("That game isn't on the card right now, so there's nowhere to restore it."))
        return

    confirm = ask(f"Overwrite {target['name']}'s save on the card? Type YES: ")
    if confirm != "YES":
        print("Cancelled.")
        return
    try:
        restore_save(backup_path, target["path"])
    except (OSError, ValueError) as e:
        print(red(f"Restore failed: {e}"))
        return
    print(green(f"Restored {target['name']}'s save."))


__all__ = ["find_game_saves", "used_pages", "backup_save", "list_backups",
           "restore_save", "run_interactive"]
