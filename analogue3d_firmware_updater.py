#!/usr/bin/env python3

"""
Analogue 3D Updater – Firmware + Cartridge Labels (labels.db)
Fixed for December 2025+: labels.db is now hosted as a GitHub Release asset
(so raw/main 404s – we now use /releases/latest/download/ which always gets the newest)
"""

import os
import sys
import shutil
import requests
from bs4 import BeautifulSoup
import psutil
from urllib.parse import urljoin

FIRMWARE_PAGE = "https://www.analogue.co/support/3d/firmware/latest"
# Fixed URL – always downloads the absolute latest labels.db from RetroGameCorps
LABELS_DB_URL = "https://github.com/retrogamecorps/Analogue-3D-Images/releases/latest/download/labels.db"
LABELS_DB_FILENAME = "labels.db"
LABELS_DB_PATH_ON_CARD = os.path.join("Library", "N64", "Images", LABELS_DB_FILENAME)

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
    filename = url.split("/")[-1].split("?")[0]  # Clean any redirects/query params
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
    print("\n=== Updating Analogue 3D OS ===")
    fw_url, fw_filename = get_latest_firmware_url()
    if not fw_url:
        return False
        
    local_fw_path = download_file(fw_url)
    dest_path = os.path.join(target_root, fw_filename)
    
    print(f"Copying {fw_filename} to SD card root...")
    shutil.copy(local_fw_path, dest_path)
    
    # Clean up old firmware files
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
    print("\n=== Installing/Updating Cartridge Labels Database ===")
    local_labels_path = download_file(LABELS_DB_URL, dest_folder=".")
    
    labels_dir = os.path.join(target_root, "Library", "N64", "Images")
    os.makedirs(labels_dir, exist_ok=True)
    
    dest_path = os.path.join(labels_dir, LABELS_DB_FILENAME)
    print(f"Copying {LABELS_DB_FILENAME} to {labels_dir}/")
    shutil.copy(local_labels_path, dest_path)
    
    print("Cartridge labels installed/updated! Beautiful stock cartridge art will now appear when you insert games.")

def main():
    print("=====================================")
    print("   Analogue 3D Updater Tool")
    print("   Firmware + Cartridge Labels (Dec 2025+)")
    print("=====================================\n")
    
    while True:
        print("What do you want to do?")
        print("1) Install ALL (OS + Cartridge Labels)")
        print("2) Install Cartridge Labels only")
        print("3) Update OS (Firmware) only")
        print("0) Quit")
        
        choice = input("\nEnter choice (0-3): ").strip()
        
        if choice not in ["0", "1", "2", "3"]:
            print("Invalid choice, try again.\n")
            continue
        
        if choice == "0":
            print("Goodbye!")
            sys.exit(0)
        
        do_firmware = choice in ["1", "3"]
        do_labels   = choice in ["1", "2"]
        
        if not (do_firmware or do_labels):
            continue
        
        target_root = select_sd_card()
        
        success = True
        if do_firmware:
            success &= install_firmware(target_root)
        
        if do_labels:
            install_labels(target_root)
        
        print("\n🎉 All selected tasks completed!")
        print("Safely eject your SD card and enjoy your fully updated Analogue 3D!")
        print("Firmware update → hold Pairing + Power on boot\n")
        
        again = input("Do another operation? (y/n): ").strip().lower()
        if again != "y":
            print("All done! 🚀")
            break
        print("")

if __name__ == "__main__":
    try:
        import requests, bs4, psutil
    except ImportError:
        print("Missing required packages!")
        print("Run: pip install requests beautifulsoup4 psutil")
        sys.exit(1)
    
    main()