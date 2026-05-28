"""Interactive menu for the Analogue 3D Utility (the ``python a3d.py`` front-end).

Uses ui.select() for an arrow-key menu when a real terminal + questionary are
available, and a numbered fallback otherwise.
"""

import os

import requests

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

    n_controllers = controller.connected_count()
    ui.info("This will, for every part that applies:")
    print(f"   {ui.DOT} Back up the SD card")
    print(f"   {ui.DOT} Update the console firmware")
    print(f"   {ui.DOT} Install the community cartridge art pack")
    if n_controllers == 1:
        print(f"   {ui.DOT} Update the 8BitDo 64 controller " + ui.green("(detected)"))
    elif n_controllers > 1:
        print(f"   {ui.DOT} Update all {n_controllers} 8BitDo 64 controllers " + ui.green("(detected)"))
    else:
        print(f"   {ui.DOT} Update the 8BitDo 64 controller " + ui.dim("(not detected - will skip)"))

    if not ui.confirm("Proceed?", default=True):
        ui.warn("Cancelled.")
        return

    try:
        sdcard.create_backup(root)
        if not sdcard.install_firmware(root):
            ui.warn("Firmware step didn't complete - check your connection.")
        sdcard.install_labels(root)
    except (requests.RequestException, OSError) as e:
        ui.err(f"Auto update stopped during SD tasks: {e}")
        return

    if n_controllers >= 1:
        ui.info(f"Updating 8BitDo 64 controller{'s' if n_controllers > 1 else ''}...")
        s = controller.update_all(progress=controller._progress)
        print()
        if s.get("note") and not s.get("updated"):
            ui.warn(f"Controller: {s['note']}")
        else:
            msg = f"Controllers: {s.get('updated', 0)} updated, {s.get('already', 0)} already current"
            if s.get("failed"):
                msg += f", {s['failed']} failed"
            (ui.warn if s.get("failed") else ui.ok)(msg)

    ui.ok("SD tasks complete.")
    ui.info("Safely eject the card. For the firmware update: hold Pairing + Power on boot.")


def run_auto():
    """One-shot, non-interactive run (the --auto flag): the full Auto flow with
    defaults. Requires ui.ASSUME_YES so the prompts auto-answer."""
    ui.banner()
    _auto_all()


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
            ("Auto - do everything (backup, firmware, art pack, controller)", "auto"),
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
