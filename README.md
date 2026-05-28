# Analogue 3D Firmware Updater

A dead-simple, cross-platform Python script that automatically downloads the **latest** Analogue 3D firmware from the official site and copies it to your SD card — while cleaning up any old firmware files.

Think of it as the spiritual successor to PocketSync… but for the Analogue 3D (until someone makes a proper GUI).

## Features

- Always grabs the absolute latest firmware directly from `https://www.analogue.co/support/3d/firmware/latest`
- Detects removable drives / SD cards automatically (Windows, macOS, Linux)
- Lets you pick the correct drive or enter the path manually
- Copies the new `.bin` file to the root of the card
- Deletes any previous `a3d_os_*.bin` files (Analogue recommends only one firmware file present)
- No dependencies beyond standard Python packages + three tiny pip installs

## 8BitDo 64 Controller updater (menu option 7)

Updates the **8BitDo 64 Bluetooth Controller** (the Analogue 3D pad) over its
USB-C cable — no 8BitDo Ultimate Software, no browser, no Windows driver swap.

- Downloads the latest controller firmware straight from 8BitDo's API
  (`dl.8bitdo.com`, firmware "Type 78")
- Talks the controller's HID flashing protocol directly (reverse-engineered
  from 8BitDo's WebHID updater and verified live against a real 8BitDo 64)
- Differential flash: only the 4KB blocks that actually changed are written,
  each verified by CRC. If interrupted, just run it again — the controller's
  bootloader stays intact, so it's recoverable.

Usage: connect the controller with a USB-C **data** cable, power it on, run the
tool, and pick option 7. Requires the extra `hidapi` package (see below).

## Requirements

Python 3.7+ and the following packages:

```bash
pip install requests beautifulsoup4 psutil hidapi