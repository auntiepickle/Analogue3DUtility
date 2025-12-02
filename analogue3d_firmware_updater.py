#!/usr/bin/env python3

"""
Analogue 3D Updater – Firmware + Labels + Backup/Restore
- Always uses forward slashes in zip paths (bulletproof on Windows)
- Explicitly adds directory entries for everything that needs it
- Uses b'' for directory entries (no zero-byte files ever created)
- Tested logic on Windows: empty folders restore as folders, never as files
"""

import os
import sys
import shutil
import zipfile
import requests
from bs4 import BeautifulSoup
import psutil
from urllib.parse import urljoin
from datetime import datetime

FIRMWARE_PAGE = "https://www.analogue.co/support/3d/firmware/latest"
LABELS_DB_URL = "https://github.com/retrogamecorps/Analogue-3D-Images/releases/latest/download/labels.db"
LABELS_DB_FILENAME = "labels.db"

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
    filename = download_url.split("/")[-1]
    print(f"Latest firmware: {filename}")
    return download_url, filename

def download_file(url, dest_folder="."):
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

def get_potential_sd_cards():
    candidates = []
    
    for part in psutil.disk_partitions():
        mount = part.mountpoint
        
        if not os.access(mount, os.W_OK):
            continue
            
        is_removable = ("removable" in part.opts.lower() or "cdrom" not in part.opts.lower())
        is_sd_like = part.fstype.lower() in ["fat", "fat32", "exfat", "vfat", "ntfs"]
        is_external_path = mount.startswith(("/media/", "/Volumes/", "/mnt/"))
        
        if (is_removable or is_sd_like or is_external_path):
            display_path = mount.rstrip(os.sep) + os.sep
            if display_path not in [c[0] for c in candidates]:
                try:
                    free_gb = shutil.disk_usage(mount).free // (1024**3)
                    candidates.append((display_path, free_gb))
                except:
                    candidates.append((display_path, 0))
    
    return candidates

def select_sd_card():
    print("\nLooking for SD cards / removable drives...")
    drives = get_potential_sd_cards()
    
    if drives:
        print("Found possible SD cards:")
        for i, (path, free_gb) in enumerate(drives):
            print(f"  {i+1}) {path} ({free_gb} GB free)")
        print("  0) Enter path manually")
        
        choice = input("\nSelect your SD card (number): ").strip()
        if choice == "0":
            target_root = input("Enter full path to SD card root (e.g. E:\\ or /Volumes/NO_NAME/): ").strip()
        else:
            try:
                target_root = drives[int(choice)-1][0]
            except:
                print("Invalid selection.")
                sys.exit(1)
    else:
        print("No removable drives detected automatically.")
        target_root = input("Enter full path to SD card root (e.g. E:\\ or /Volumes/NO_NAME/): ").strip()
    
    if not os.path.exists(target_root):
        print("Error: Path doesn't exist.")
        sys.exit(1)
    if not os.access(target_root, os.W_OK):
        print("Error: Cannot write to that path.")
        sys.exit(1)
    
    return target_root

def install_firmware(target_root):
    print("\n=== Updating Analogue 3D Firmware ===")
    fw_url, fw_filename = get_latest_firmware_url()
    if not fw_url:
        return False
        
    local_fw_path = download_file(fw_url)
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
    
    # Case-insensitive detection, exact casing preserved
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
            
            # Always add top-level directory entry
            zip_arcname = folder.replace(os.sep, '/') + '/'
            zipf.writestr(zip_arcname, b'')
            
            for root, dirs, files in os.walk(folder_path):
                # Add empty subdirectories
                for d in dirs:
                    subdir_path = os.path.join(root, d)
                    if not os.listdir(subdir_path):  # truly empty
                        rel = os.path.relpath(subdir_path, target_root).replace(os.sep, '/') + '/'
                        zipf.writestr(rel, b'')
                
                # Add files
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
        print(f"  {i+1}) {backup}")
    
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
    
    print("Restore completed successfully! Empty folders (like Settings/Global) are now properly restored as folders.")

def main():
    print("=============================================")
    print("   Analogue 3D Complete Updater Tool")
    print("   Firmware ▪ Labels ▪ Backup ▪ Restore")
    print("   Empty folders 100% fixed (Dec 2025)")
    print("=============================================\n")
    
    while True:
        print("What do you want to do?")
        print("1) Install ALL (Firmware + Labels)")
        print("2) Install Labels only")
        print("3) Update Firmware only")
        print("4) Create Backup (Library + Settings)")
        print("5) Restore Backup")
        print("0) Quit")
        
        choice = input("\nEnter choice (0-5): ").strip()
        
        if choice not in ["0","1","2","3","4","5"]:
            print("Invalid choice, try again.\n")
            continue
        
        if choice == "0":
            print("Goodbye! Enjoy your Analogue 3D 🚀")
            sys.exit(0)
        
        target_root = select_sd_card()
        
        if choice in ["1", "2", "3"]:
            if choice in ["1", "3"]:
                install_firmware(target_root)
            if choice in ["1", "2"]:
                install_labels(target_root)
            print("\n🎉 Update tasks completed!")
        
        elif choice == "4":
            create_backup(target_root)
        
        elif choice == "5":
            restore_backup(target_root)
        
        print("\nSafely eject your SD card when ready.")
        if choice in ["1", "3"]:
            print("For firmware update: hold Pairing + Power on boot.")
        print()
        
        again = input("Do another operation? (y/n): ").strip().lower()
        if again != "y":
            print("All done! See you next time 🚀")
            break
        print("\n" + "="*50 + "\n")

if __name__ == "__main__":
    try:
        import requests, bs4, psutil
    except ImportError:
        print("Missing required packages!")
        print("Run: pip install requests beautifulsoup4 psutil")
        sys.exit(1)
    
    main()