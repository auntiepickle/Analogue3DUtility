#!/usr/bin/env python3

"""
Analogue 3D Updater – Firmware + Labels + Backup/Restore + Clean Backups
The FINAL complete one-stop tool for your Analogue 3D (December 2025+)
Now with backup cleaning – keep your backups folder tidy!
"""

import os
import re
import sys
import shutil
import zipfile
import ctypes
import subprocess
from urllib.parse import urljoin
from datetime import datetime


def _ensure_dependencies():
    """Make this runnable with nothing but Python installed: detect any missing
    packages and offer to pip-install them automatically, so a user can just run
    the script. requests/bs4/psutil are required; hidapi is optional (controller)."""
    required = [("requests", "requests"), ("bs4", "beautifulsoup4"), ("psutil", "psutil")]
    optional = [("hid", "hidapi")]

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
              " (only needed for the controller updater) - continuing without it.")
    if missing(required):
        print("Packages still missing. Please run:  pip install " + " ".join(miss_req))
        sys.exit(1)


_ensure_dependencies()

import requests
from bs4 import BeautifulSoup
import psutil

FIRMWARE_PAGE = "https://www.analogue.co/support/3d/firmware/latest"
LABELS_DB_URL = "https://github.com/retrogamecorps/Analogue-3D-Images/releases/latest/download/labels.db"
LABELS_DB_FILENAME = "labels.db"
ANALOGUE_VOLUME_LABEL = "ANALOGUE 3D"


# --- terminal niceties ---------------------------------------------------
def _enable_color():
    if os.environ.get("NO_COLOR") or not sys.stdout.isatty():
        return False
    if os.name == "nt":
        try:
            k = ctypes.windll.kernel32
            h = k.GetStdHandle(-11)
            mode = ctypes.c_uint32()
            k.GetConsoleMode(h, ctypes.byref(mode))
            k.SetConsoleMode(h, mode.value | 0x0004)  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
        except Exception:
            return False
    return True


_COLOR = _enable_color()


def _c(text, code):
    return f"\033[{code}m{text}\033[0m" if _COLOR else text


def bold(t):    return _c(t, "1")
def dim(t):     return _c(t, "2")
def cyan(t):    return _c(t, "96")
def green(t):   return _c(t, "92")
def yellow(t):  return _c(t, "93")
def red(t):     return _c(t, "91")
def magenta(t): return _c(t, "95")

def get_latest_firmware_url():
    print("Fetching latest firmware info from Analogue...")
    resp = requests.get(FIRMWARE_PAGE)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")

    download_link = None
    for a in soup.find_all("a", href=True):
        if a.text and "Download [" in a.text and "MB" in a.text:
            download_link = a["href"]
            break

    if not download_link:
        print("Error: Could not find download link. Site layout may have changed.")
        print(f"Check manually: {FIRMWARE_PAGE}")
        return None, None

    download_url = urljoin(FIRMWARE_PAGE, download_link)

    # The link is an intermediate URL like .../firmware/1.3.0/download — not the .bin file.
    # Extract the version from the URL (or page) and build the canonical SD-card filename.
    version = None
    m = re.search(r"/firmware/(\d+)\.(\d+)\.(\d+)", download_url)
    if not m:
        m = re.search(r"Version\s+(\d+)\.(\d+)\.(\d+)", resp.text, re.IGNORECASE)
    if m:
        version = (int(m.group(1)), int(m.group(2)), int(m.group(3)))
        filename = f"a3d_os_{version[0]:02d}_{version[1]:02d}_{version[2]:02d}.bin"
    else:
        print("Error: Could not parse firmware version from page.")
        return None, None

    print(f"Latest firmware: {filename}")
    return download_url, filename

def download_file(url, dest_folder=".", filename=None):
    if not filename:
        filename = url.split("/")[-1].split("?")[0]
    filepath = os.path.join(dest_folder, filename)

    print(f"Downloading {filename}...")
    r = requests.get(url, stream=True)
    r.raise_for_status()

    with open(filepath, "wb") as f:
        for chunk in r.iter_content(chunk_size=8192):
            f.write(chunk)

    print(f"Downloaded: {filepath}")
    return filepath

def get_volume_label(mount):
    """Return the volume label for a mount point, or '' if unknown."""
    if sys.platform == "win32":
        try:
            buf = ctypes.create_unicode_buffer(1024)
            fs_buf = ctypes.create_unicode_buffer(1024)
            root = mount if mount.endswith(os.sep) else mount + os.sep
            rc = ctypes.windll.kernel32.GetVolumeInformationW(
                ctypes.c_wchar_p(root),
                buf, ctypes.sizeof(buf),
                None, None, None,
                fs_buf, ctypes.sizeof(fs_buf),
            )
            return buf.value if rc else ""
        except Exception:
            return ""
    # macOS/Linux: volume label is the last path component of the mount point.
    return os.path.basename(mount.rstrip(os.sep))

def _analogue_signature(mount, label):
    """Score how likely a drive is the Analogue 3D card, by label + contents."""
    score = 0
    reasons = []
    if label.strip().upper() == ANALOGUE_VOLUME_LABEL:
        score += 5
        reasons.append("volume label")
    try:
        entries = os.listdir(mount)
    except OSError:
        entries = []
    if any(re.match(r"a3d_os_.*\.bin$", e, re.IGNORECASE) for e in entries):
        score += 4
        reasons.append("firmware file")
    lower = {e.lower() for e in entries}
    if "library" in lower and "settings" in lower:
        score += 3
        reasons.append("Library + Settings")
    return score, reasons


def get_potential_sd_cards():
    """Return drive dicts, best Analogue-3D candidate first."""
    candidates = []
    seen = set()
    for part in psutil.disk_partitions():
        mount = part.mountpoint
        if not os.access(mount, os.W_OK):
            continue
        opts = part.opts.lower()
        fstype = part.fstype.lower()
        is_removable = "removable" in opts
        is_sd_like = fstype in ("fat", "fat32", "exfat", "vfat", "ntfs")
        is_external_path = mount.startswith(("/media/", "/Volumes/", "/mnt/"))
        if not (is_removable or is_external_path or is_sd_like):
            continue
        display_path = mount.rstrip(os.sep) + os.sep
        if display_path in seen:
            continue
        seen.add(display_path)
        try:
            free_gb = shutil.disk_usage(mount).free // (1024 ** 3)
        except OSError:
            free_gb = 0
        label = get_volume_label(mount)
        score, reasons = _analogue_signature(mount, label)
        candidates.append({
            "path": display_path, "free_gb": free_gb, "label": label,
            "removable": is_removable, "score": score, "reasons": reasons,
        })
    # Strongest signature first; then removable; then smaller drives (SD cards are small).
    candidates.sort(key=lambda d: (d["score"], d["removable"], -d["free_gb"]), reverse=True)
    return candidates


def _validate_root(path):
    if not os.path.exists(path):
        print(red("Error: that path doesn't exist."))
        sys.exit(1)
    if not os.access(path, os.W_OK):
        print(red("Error: can't write to that path."))
        sys.exit(1)
    return path


def select_sd_card():
    print(dim("Scanning for the Analogue 3D SD card..."))
    drives = get_potential_sd_cards()

    # Auto-pick when exactly one drive has a strong Analogue 3D signature.
    strong = [d for d in drives if d["score"] >= 4]
    if len(strong) == 1:
        d = strong[0]
        label_str = f" [{d['label']}]" if d["label"] else ""
        detail = f"{d['free_gb']} GB free - matched: {', '.join(d['reasons'])}"
        print(green("Found your Analogue 3D card: ") + bold(d["path"]) + label_str +
              " " + dim(f"({detail})"))
        try:
            confirm = input("Use this drive? [Y/n]: ").strip().lower()
        except EOFError:
            confirm = "y"
        if confirm in ("", "y", "yes"):
            return _validate_root(d["path"])
        print("OK, choose manually instead.")

    # Show removable drives and anything with an Analogue signature; hide plain
    # internal fixed drives (score 0) to keep the list uncluttered.
    shown = [d for d in drives if d["removable"] or d["score"] > 0]
    if shown:
        print("\nDetected drives:")
        for i, d in enumerate(shown, 1):
            label_str = f" [{d['label']}]" if d["label"] else ""
            free_str = dim(f"({d['free_gb']} GB free)")
            internal = "" if d["removable"] else dim(" - internal")
            tag = green("  <- looks like Analogue 3D") if d["score"] >= 4 else ""
            print(f"  {bold(str(i))}) {d['path']}{label_str} {free_str}{internal}{tag}")
        print(f"  {bold('0')}) Enter a path manually")

        default_hint = " " + dim("[Enter = 1]") if strong else ""
        choice = input(f"\nSelect your SD card{default_hint}: ").strip()
        if choice == "" and strong:
            return _validate_root(shown[0]["path"])
        if choice == "0":
            target_root = input(r"Enter full path to SD card root (e.g. E:\ or /Volumes/NO_NAME/): ").strip()
        else:
            try:
                target_root = shown[int(choice) - 1]["path"]
            except (ValueError, IndexError):
                print(red("Invalid selection."))
                sys.exit(1)
    else:
        print(yellow("No removable drives detected automatically."))
        target_root = input(r"Enter full path to SD card root (e.g. E:\ or /Volumes/NO_NAME/): ").strip()

    return _validate_root(target_root)

def install_firmware(target_root):
    print("\n=== Updating Analogue 3D Firmware ===")
    fw_url, fw_filename = get_latest_firmware_url()
    if not fw_url:
        return False
        
    local_fw_path = download_file(fw_url, filename=fw_filename)
    dest_path = os.path.join(target_root, fw_filename)
    
    print(f"Copying {fw_filename} to SD card root...")
    shutil.copy(local_fw_path, dest_path)
    
    print("Removing old firmware files...")
    removed = 0
    for entry in os.listdir(target_root):
        if entry.startswith("a3d_os_") and entry.endswith(".bin") and entry != fw_filename:
            old_path = os.path.join(target_root, entry)
            try:
                os.remove(old_path)
                print(f"  Removed {entry}")
                removed += 1
            except:
                pass
    if removed == 0:
        print("  No old firmware files found.")
    
    return True

def install_labels(target_root):
    print("\n=== Installing/Updating Cartridge Labels ===")
    local_labels_path = download_file(LABELS_DB_URL, dest_folder=".")
    
    labels_dir = os.path.join(target_root, "Library", "N64", "Images")
    os.makedirs(labels_dir, exist_ok=True)
    
    dest_path = os.path.join(labels_dir, LABELS_DB_FILENAME)
    print(f"Copying {LABELS_DB_FILENAME} to {labels_dir}/")
    shutil.copy(local_labels_path, dest_path)
    
    print("Cartridge labels updated → beautiful cartridge art will now show!")

def create_backup(target_root):
    print("\n=== Creating Backup ===")
    
    script_dir = os.path.dirname(os.path.abspath(__file__))
    backup_dir = os.path.join(script_dir, "backups")
    os.makedirs(backup_dir, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    backup_filename = f"analogue3d_backup_{timestamp}.zip"
    backup_path = os.path.join(backup_dir, backup_filename)
    
    folders_to_backup = []
    for entry in os.listdir(target_root):
        entry_lower = entry.lower()
        entry_path = os.path.join(target_root, entry)
        if os.path.isdir(entry_path) and entry_lower in {"library", "settings"}:
            folders_to_backup.append(entry)
    
    if not folders_to_backup:
        print("Warning: No Library or Settings folder found. Creating empty backup anyway.")
    else:
        print(f"Backing up folders (exact casing preserved): {', '.join(folders_to_backup)}")
    
    with zipfile.ZipFile(backup_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for folder in folders_to_backup:
            folder_path = os.path.join(target_root, folder)
            zip_arcname = folder.replace(os.sep, '/') + '/'
            zipf.writestr(zip_arcname, b'')
            
            for root, dirs, files in os.walk(folder_path):
                for d in dirs:
                    subdir_path = os.path.join(root, d)
                    if not os.listdir(subdir_path):
                        rel = os.path.relpath(subdir_path, target_root).replace(os.sep, '/') + '/'
                        zipf.writestr(rel, b'')
                
                for file in files:
                    full_path = os.path.join(root, file)
                    arcname = os.path.relpath(full_path, target_root).replace(os.sep, '/')
                    zipf.write(full_path, arcname)
    
    print(f"Backup created successfully!")
    print(f"Location: {backup_path}")

def restore_backup(target_root):
    print("\n=== Restore Backup ===")
    
    script_dir = os.path.dirname(os.path.abspath(__file__))
    backup_dir = os.path.join(script_dir, "backups")
    
    if not os.path.exists(backup_dir) or not os.listdir(backup_dir):
        print("No backups found!")
        print(f"Backups are stored in: {backup_dir}")
        return
    
    backups = sorted([f for f in os.listdir(backup_dir) 
                     if f.startswith("analogue3d_backup_") and f.endswith(".zip")], reverse=True)
    
    print("Available backups (newest first):")
    for i, backup in enumerate(backups):
        path = os.path.join(backup_dir, backup)
        size_mb = os.path.getsize(path) // (1024**1024)
        print(f"  {i+1}) {backup} ({size_mb} MB)")
    
    choice = input("\nSelect backup to restore (number): ").strip()
    try:
        selected_backup = backups[int(choice) - 1]
    except:
        print("Invalid selection.")
        return
    
    backup_path = os.path.join(backup_dir, selected_backup)
    
    confirm = input(f"\nWARNING: This will OVERWRITE all files in Library/Settings folders!\nType YES to continue: ").strip()
    if confirm != "YES":
        print("Restore cancelled.")
        return
    
    print(f"Restoring {selected_backup}...")
    with zipfile.ZipFile(backup_path, 'r') as zipf:
        zipf.extractall(target_root)
    
    print("Restore completed successfully!")

def clean_backups():
    print("\n=== Clean Backups ===")
    
    script_dir = os.path.dirname(os.path.abspath(__file__))
    backup_dir = os.path.join(script_dir, "backups")
    
    if not os.path.exists(backup_dir):
        print("No backups folder found (nothing to clean).")
        return
        
    backups = sorted([f for f in os.listdir(backup_dir) 
                     if f.startswith("analogue3d_backup_") and f.endswith(".zip")], reverse=True)
    
    if not backups:
        print("No backups found.")
        return
    
    print("Current backups (newest first):")
    total_size = 0
    for i, backup in enumerate(backups):
        path = os.path.join(backup_dir, backup)
        size_mb = os.path.getsize(path) // (1024**1024)
        total_size += size_mb
        print(f"  {i+1}) {backup} ({size_mb} MB)")
    print(f"\nTotal backups: {len(backups)} | Total size: {total_size} MB")
    
    choice = input("\nEnter numbers to delete (e.g. 2,4,5), 'all', or 0 to cancel: ").strip().lower()
    
    if choice == "0" or choice == "":
        print("Cancelled.")
        return
    
    to_delete = []
    if choice == "all":
        confirm = input("Delete ALL backups? Type YES to confirm: ").strip()
        if confirm == "YES":
            to_delete = backups
        else:
            print("Cancelled.")
            return
    else:
        try:
            indices = [int(x.strip()) - 1 for x in choice.split(",") if x.strip()]
            to_delete = [backups[i] for i in indices if 0 <= i < len(backups)]
        except:
            print("Invalid input.")
            return
    
    if not to_delete:
        print("Nothing selected.")
        return
    
    confirm = input(f"\nDelete {len(to_delete)} backup(s)? Type YES to confirm: ").strip()
    if confirm != "YES":
        print("Cancelled.")
        return
    
    deleted = 0
    for backup in to_delete:
        path = os.path.join(backup_dir, backup)
        try:
            os.remove(path)
            print(f"  Deleted {backup}")
            deleted += 1
        except:
            print(f"  Failed to delete {backup}")
    
    print(f"\nClean complete! {deleted} backup(s) deleted.")

def main():
    title = "  ANALOGUE 3D UTILITY  "
    line = "+" + "-" * len(title) + "+"
    print()
    print(cyan(line))
    print(cyan("|") + bold(title) + cyan("|"))
    print(cyan(line))
    print(dim("  Firmware  -  Labels  -  Backup  -  Restore  -  Controller") + "\n")

    while True:
        print(bold("What do you want to do?"))
        print(f"  {cyan('1')})  Install ALL (Firmware + Labels)")
        print(f"  {cyan('2')})  Install Labels only")
        print(f"  {cyan('3')})  Update Firmware only")
        print(f"  {cyan('4')})  Create Backup (Library + Settings)")
        print(f"  {cyan('5')})  Restore Backup")
        print(f"  {cyan('6')})  Clean Backups")
        print(f"  {magenta('7')})  Update 8BitDo 64 Controller firmware (USB-C)")
        print(f"  {dim('0')})  Quit")

        choice = input("\n" + bold("Enter choice (0-7): ")).strip()

        if choice not in ["0", "1", "2", "3", "4", "5", "6", "7"]:
            print(yellow("Invalid choice, try again.") + "\n")
            continue

        if choice == "0":
            print(green("Goodbye! Enjoy your perfectly maintained Analogue 3D."))
            sys.exit(0)

        if choice == "6":
            clean_backups()
        elif choice == "7":
            import eightbitdo_64_updater
            eightbitdo_64_updater.run_interactive()
        else:
            # All other options need the SD card
            target_root = select_sd_card()
            
            if choice in ["1", "2", "3"]:
                if choice in ["1", "3"]:
                    install_firmware(target_root)
                if choice in ["1", "2"]:
                    install_labels(target_root)
                print(green("\nUpdate tasks completed!"))

            elif choice == "4":
                create_backup(target_root)

            elif choice == "5":
                restore_backup(target_root)

            print(dim("\nSafely eject your SD card when ready."))
            if choice in ["1", "3"]:
                print(dim("For firmware update: hold Pairing + Power on boot."))
        
        print()
        again = input("\nDo another operation? (y/n): ").strip().lower()
        if again != "y":
            print(green("All done! Your Analogue 3D is in perfect shape."))
            break
        print("\n" + dim("=" * 60) + "\n")


if __name__ == "__main__":
    main()