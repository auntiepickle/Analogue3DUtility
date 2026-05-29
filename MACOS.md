# Running on macOS

The tool itself works great on macOS. The only pain is **getting it to start**:
the pre-built `a3d-macos` binary isn't signed or notarized by Apple, so modern
macOS (Sonoma / Sequoia) throws scary "cannot be verified / malware" warnings and
makes you click through several System Settings screens to approve it.

This guide gives you the path of least resistance. There are two easy ways and a
fallback.

---

## Easiest: run from source (recommended)

On a Mac, **running from source is smoother than the binary** — there's no
Gatekeeper gauntlet to fight, because you're running your own `python`, not a
downloaded app. You just need Python 3, which most Macs can get in one command.

```bash
# 1. Get Python 3 if you don't have it (this opens Apple's installer):
xcode-select --install

# 2. Download the tool and run it:
git clone https://github.com/auntiepickle/Analogue3DUtility.git
cd Analogue3DUtility
python3 a3d.py
```

The launcher checks for the packages it needs and offers to install them for you
on first run. That's it — you land in the arrow-key menu.

> No `git`? Download the repo as a ZIP from the green **Code** button on
> [the GitHub page](https://github.com/auntiepickle/Analogue3DUtility), unzip it,
> then in Terminal `cd` into the folder and run `python3 a3d.py`.

---

## Also easy: download the binary with `curl`

If you'd rather use the standalone binary, **download it with `curl` instead of
your browser**. Files downloaded by `curl` don't get macOS's "quarantine" flag, so
Gatekeeper doesn't block them — no warnings, no System Settings trip:

```bash
cd ~/Desktop
curl -L -o a3d-macos https://github.com/auntiepickle/Analogue3DUtility/releases/latest/download/a3d-macos
chmod +x a3d-macos
./a3d-macos
```

That's the whole trick: a browser download triggers Gatekeeper; a `curl` download
doesn't.

---

## Fallback: you already downloaded the binary in a browser

If you grabbed `a3d-macos` from the Releases page in Safari/Chrome, it's now
quarantined and you'll hit the warnings. Get past them like this:

1. **Move it out of Downloads.** The Downloads folder is heavily locked down; put
   the file on your **Desktop**.
2. In Terminal, clear the quarantine flag and make it runnable:
   ```bash
   cd ~/Desktop
   xattr -cr a3d-macos
   chmod +x a3d-macos
   ./a3d-macos
   ```
   (You can also run the bundled helper:
   `bash scripts/macos-launch-helper.sh a3d-macos`.)
3. If you still get a popup, click **Done** (never "Move to Trash"), then open
   **System Settings -> Privacy & Security**, scroll to the bottom, and click
   **Open Anyway** next to the `a3d-macos` message. Authenticate, then run
   `./a3d-macos` again. Sometimes you have to run it twice.

**"Operation not permitted" on `xattr`/`chmod`?** You're probably still in
Downloads — move the file to the Desktop. If it persists, grant Terminal **Full
Disk Access** in System Settings -> Privacy & Security, or prefix the commands
with `sudo`.

---

## After it launches: two macOS gotchas

These are about the SD card, not Gatekeeper:

- **Backup says 0 MB / looks empty.** Some Mac card readers cause the tool to miss
  the `Library` / `Settings` / `Memories` folders. The tool now probes for them
  directly and reports the real backup size, warning you if it's suspiciously
  small. If you still get a tiny backup, re-seat the card or try a different reader.
- **`[Errno 30] Read-only file system`.** macOS mounted the card read-only (common
  after a filesystem hiccup or with flaky readers). The tool now catches this and
  tells you instead of crashing. Fix: safely eject and re-insert the card, run
  First Aid on it in Disk Utility, or try a different reader.

---

If something here didn't work, please
[open an issue](https://github.com/auntiepickle/Analogue3DUtility/issues) with your
macOS version and the exact error text — it helps make this smoother for the next
person.
