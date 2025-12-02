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

## Requirements

Python 3.7+ and the following packages:

```bash
pip install requests beautifulsoup4 psutil