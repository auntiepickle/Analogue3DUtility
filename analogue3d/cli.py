"""Interactive menu for the Analogue 3D Utility (the ``python a3d.py`` front-end)."""

from . import sdcard, controller, labels, saves
from .ui import bold, dim, cyan, green, yellow, magenta, gold, DOT, ask


def _sd_status_line():
    try:
        strong = [d for d in sdcard.get_potential_sd_cards() if d["score"] >= 4]
    except Exception:
        strong = []
    if len(strong) == 1:
        d = strong[0]
        label = f" [{d['label']}]" if d["label"] else ""
        return green(f"  {DOT} SD card: ") + bold(d["path"]) + dim(label)
    if strong:
        return yellow(f"  {DOT} SD card: multiple Analogue 3D cards detected")
    return dim(f"  {DOT} SD card: not detected (you can still enter a path manually)")


def main():
    title = "  ANALOGUE 3D UTILITY  "
    bar = "+" + "-" * len(title) + "+"
    print()
    print(gold(bar))
    print(gold("|") + bold(gold(title)) + gold("|"))
    print(gold(bar))

    while True:
        print()
        print(_sd_status_line())
        print()
        print(bold("  SD CARD"))
        print(f"    {cyan('1')}  Install everything (firmware + labels)")
        print(f"    {cyan('2')}  Install labels only")
        print(f"    {cyan('3')}  Update firmware only")
        print(f"    {cyan('4')}  Create backup")
        print(f"    {cyan('5')}  Restore backup")
        print(f"    {cyan('6')}  Clean backups")
        print(bold("  CARTRIDGES"))
        print(f"    {cyan('7')}  Set custom cartridge artwork")
        print(bold("  SAVES"))
        print(f"    {cyan('8')}  Back up / restore controller-pak saves")
        print(bold("  CONTROLLER"))
        print(f"    {magenta('9')}  Update 8BitDo 64 controller (USB-C)")
        print()
        print(f"    {dim('0')}  Quit")

        choice = ask("\n" + bold("Choose an option: ")).lower()

        if choice in ("0", "q", "quit"):
            print(green("\nDone. Enjoy your Analogue 3D."))
            return
        if choice not in ("1", "2", "3", "4", "5", "6", "7", "8", "9"):
            print(yellow("Please enter a number from the menu."))
            continue

        if choice == "6":
            sdcard.clean_backups()
        elif choice == "9":
            controller.run_interactive()
        else:
            target_root = sdcard.select_sd_card()
            if target_root is None:
                print(dim("Cancelled - back to menu."))
                print("\n" + dim("-" * 60))
                continue

            if choice in ("1", "2", "3"):
                if choice in ("1", "3"):
                    sdcard.install_firmware(target_root)
                if choice == "1":
                    sdcard.install_labels(target_root)
                elif choice == "2":
                    sdcard.install_labels(target_root, sdcard.choose_label_source())
                print(green("\nUpdate tasks completed!"))
                if choice in ("1", "3"):
                    print(dim("For the firmware update: hold Pairing + Power on boot."))
            elif choice == "4":
                sdcard.create_backup(target_root)
            elif choice == "5":
                sdcard.restore_backup(target_root)
            elif choice == "7":
                labels.run_interactive(target_root)
            elif choice == "8":
                saves.run_interactive(target_root)

            print(dim("\nSafely eject your SD card when ready."))

        print("\n" + dim("-" * 60))
