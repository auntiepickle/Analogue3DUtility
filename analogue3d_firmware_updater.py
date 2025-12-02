#!/usr/bin/env python3

"""
Analogue 3D Firmware Updater Script
A simple cross-platform Python script to automatically download the latest
Analogue 3D firmware and copy it to your SD card (with old firmware cleanup).

Requirements:
pip install requests beautifulsoup4 psutil

Tested on Windows / macOS / Linux – it should work everywhere Python runs.
"""

import os
import sys
import shutil
import requests
from bs4 import BeautifulSoup
import psutil
from urllib.parse import urljoin

FIRMWARE_PAGE = "https://www.analogue.co/support/3d/firmware/latest"

def get_latest_firmware_url():
    print("Fetching latest firmware info from Analogue...")
    resp = requests.get(FIRMWARE_PAGE)
    resp.raise_for_status()
    
    soup = BeautifulSoup(resp.text, "html.parser")
    
    # Find the "Download [xx.xMB]" link – this is the only one with that pattern
    download_link = None
    for a in soup.find_all("a", href=True):
        if a.text and "Download [" in a.text and "MB" in a.text:
            download_link = a["href"]
            break
    
    if not download_link:
        print("Error: Could not find download link on the page.")
        print("The site layout may have changed – check manually at:")
        print(FIRMWARE_PAGE)
        sys.exit(1)
    
    # Make sure it's absolute
    download_url = urljoin(FIRMWARE_PAGE, download_link)
    filename = download_url.split("/")[-1]
    print(f"Latest firmware: {filename}")
    return download_url, filename

def download_firmware(url, dest_folder="."):
    filename = url.split("/")[-1]
    filepath = os.path.join(dest_folder, filename)
    
    print(f"Downloading {filename}...")
    r = requests.get(url, stream=True)
    r.raise_for_status()
    
    with open(filepath, "wb") as f:
        for chunk in r.iter_content(chunk_size=8192):
            f.write(chunk)
    
    print(f"Downloaded to {filepath}")
    return filepath

def get_potential_sd_cards():
    candidates = []
    
    for part in psutil.disk_partitions():
        mount = part.mountpoint
        
        # Skip if not writable
        if not os.access(mount, os.W_OK):
            continue
            
        # Common indicators for SD cards / USB drives
        is_removable = ("removable" in part.opts.lower() or 
                       "cdrom" not in part.opts.lower())
        is_sd_like = part.fstype.lower() in ["fat", "fat32", "exfat", "vfat", "ntfs"]
        is_external_path = mount.startswith(("/media/", "/Volumes/", "/mnt/"))
        
        if (is_removable or is_sd_like or is_external_path):
            # Add trailing separator for nice display
            display_path = mount.rstrip(os.sep) + os.sep
            if display_path not in candidates:
                try:
                    free_gb = shutil.disk_usage(mount).free // (1024**3)
                    candidates.append((display_path, free_gb))
                except:
                    candidates.append((display_path, 0))
    
    return candidates

def main():
    # Step 1: Get latest firmware
    try:
        fw_url, fw_filename = get_latest_firmware_url()
    except Exception as e:
        print(f"Failed to get firmware URL: {e}")
        sys.exit(1)
    
    # Step 2: Download it
    local_fw_path = download_firmware(fw_url)
    
    # Step 3: Find SD card
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
    
    # Validate path
    if not os.path.exists(target_root):
        print("Error: That path doesn't exist.")
        sys.exit(1)
    if not os.access(target_root, os.W_OK):
        print("Error: Cannot write to that path.")
        sys.exit(1)
    
    # Step 4: Copy firmware
    dest_path = os.path.join(target_root, fw_filename)
    print(f"\nCopying {fw_filename} to {target_root} ...")
    shutil.copy(local_fw_path, dest_path)
    
    # Step 5: Clean up old firmware files (Analogue recommends only one present)
    print("Removing any old Analogue 3D firmware files...")
    removed_count = 0
    for entry in os.listdir(target_root):
        if entry.startswith("a3d_os_") and entry.endswith(".bin") and entry != fw_filename:
            old_file = os.path.join(target_root, entry)
            try:
                os.remove(old_file)
                print(f"  Removed {entry}")
                removed_count += 1
            except:
                pass
    if removed_count == 0:
        print("  No old firmware files found.")
    
    print("\nAll done!")
    print("You can now safely eject the SD card and update your Analogue 3D.")
    print("(Hold Pairing button + Power to install the update.)")

if __name__ == "__main__":
    main()