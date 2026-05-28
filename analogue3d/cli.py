"""Interactive menu for the Analogue 3D Utility (the ``python a3d.py`` front-end).

Uses ui.select() for an arrow-key menu when a real terminal + questionary are
available, and a numbered fallback otherwise.
"""

import os

from . import sdcard, controller, labels, saves, ui


def _status():
    """One dim line under the banner: is the Analogue 3D SD card detected?"""
    try:
        strong = [d for d in sdcard.get_potential_sd_cards() if d["score"] >= 4]
    except Exception:
        strong = []
    if len(strong) == 1:
        d = strong[0]
        label = f" [{d['label']}]" if d["label"] else ""
        ui.info(f"  {ui.DOT} SD card: {d['path']}{label}")
    elif strong:
        ui.warn(f"  {ui.DOT} SD card: multiple Analogue 3D cards detected")
    else:
        ui.info(f"  {ui.DOT} SD card: not detected (you can still enter a path)")


def _art_pack_flow(root):
    src = ui.select("Which cartridge art pack?", [
        ("RetroGameCorps community pack (download latest)", "community"),
        ("A labels.db file I already have", "file"),
        ("A custom URL", "url"),
        ("Cancel", "cancel"),
    ])
    if src in (None, "cancel"):
        return
    if src == "community":
        source = None  # install_labels defaults to the community pack URL
    elif src == "file":
        source = ui.text("Path to your labels.db file:").strip('"')
        if not source or not os.path.isfile(source):
            ui.err("File not found.")
            return
    else:  # url
        source = ui.text("Enter the labels.db URL:")
        if not source:
            return
    sdcard.install_labels(root, source)


def _auto_all():
    ui.rule("Auto - do everything")
    root = sdcard.select_sd_card()
    if root is None:
        ui.warn("Cancelled.")
        return

    controller_present = controller.is_connected()
    ui.info("This will:")
    print(f"   {ui.DOT} Back up the SD card")
    print(f"   {ui.DOT} Update the console firmware")
    print(f"   {ui.DOT} Install the community cartridge art pack")
    if controller_present:
        print(f"   {ui.DOT} Update the 8BitDo 64 controller")
    else:
        print(ui.dim("   (no 8BitDo 64 controller detected - it'll be skipped)"))

    if not ui.confirm("Proceed?", default=True):
        ui.warn("Cancelled.")
        return

    sdcard.create_backup(root)
    sdcard.install_firmware(root)
    sdcard.install_labels(root)
    if controller_present:
        ui.info("Updating 8BitDo 64 controller...")
        status = controller.update_to_latest(progress=controller._progress)
        print()
        ui.ok(f"Controller: {status}")

    ui.ok("Auto update complete.")
    ui.info("Safely eject the card. For the firmware update: hold Pairing + Power on boot.")


def _advanced():
    while True:
        action = ui.select("Advanced", [
            ("Set one cartridge's art by ID or ROM", "percart"),
            ("Clean old SD backups", "clean"),
            ("Back", "back"),
        ])
        if action in (None, "back"):
            return
        if action == "clean":
            sdcard.clean_backups()
        elif action == "percart":
            root = sdcard.select_sd_card()
            if root:
                labels.run_interactive(root)
        ui.rule()


def main():
    ui.banner()
    while True:
        _status()
        action = ui.select("What would you like to do?", [
            ("Auto - do everything (backup + updates)", "auto"),
            None,
            ("Update console firmware", "firmware"),
            ("Install cartridge art pack", "artpack"),
            ("Back up SD card", "backup"),
            ("Restore SD backup", "restore"),
            ("Back up / restore game saves", "saves"),
            ("Flash 8BitDo 64 controller", "controller"),
            None,
            ("Advanced", "advanced"),
            ("Quit", "quit"),
        ])

        if action in (None, "quit"):
            ui.info("Done. Enjoy your Analogue 3D.")
            return

        if action == "auto":
            _auto_all()
        elif action == "controller":
            controller.run_interactive()
        elif action == "advanced":
            _advanced()
        else:
            root = sdcard.select_sd_card()
            if root is None:
                ui.warn("Cancelled - back to menu.")
                ui.rule()
                continue
            if action == "firmware":
                sdcard.install_firmware(root)
                ui.info("For the firmware update: hold Pairing + Power on boot.")
            elif action == "artpack":
                _art_pack_flow(root)
            elif action == "backup":
                sdcard.create_backup(root)
            elif action == "restore":
                sdcard.restore_backup(root)
            elif action == "saves":
                saves.run_interactive(root)
            ui.info("Safely eject your SD card when ready.")

        ui.rule()
