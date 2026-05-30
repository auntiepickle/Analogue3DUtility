# Running on macOS

> ## Most Mac users should use the desktop app instead
> The CLI works on macOS but the install path is fiddly — Gatekeeper warnings,
> right-click → Open, the `curl` trick to skip quarantine, etc. The companion
> **[Analogue 3D Desktop](https://github.com/auntiepickle/Analogue3DDesktop)** ships
> as a signed `.app` in a drag-to-Applications `.dmg` — no terminal, and (until
> we notarize it) only a one-time right-click → Open on first launch instead of
> the CLI's wider Gatekeeper gauntlet. Unless you specifically want a CLI
> (scripting, terminal habits), grab the desktop and skip the rest of this guide.

The CLI works great on macOS once it's running. The only friction is the
pre-built `a3d-macos` binary: it's unsigned and not notarized, so downloading it
in a **browser** trips Apple's Gatekeeper warnings.

There are two good ways to run it, plus a recovery route if you already grabbed the
binary in a browser:

- **Run from source** — often the smoothest experience overall.
- **Download the binary with `curl`** — the easiest way to use the standalone
  binary; in testing it launched with no Gatekeeper prompts at all.

---

## Easiest for many: run from source

On a Mac, running from source sidesteps Gatekeeper entirely — you're running your
own `python`, not a downloaded app. You just need Python 3, which most Macs can get
in one command.

```bash
# 1. Get Apple's command-line tools (includes python3) if you don't have them:
xcode-select --install

# 2. Download the tool and run it:
git clone https://github.com/auntiepickle/Analogue3DUtility.git
cd Analogue3DUtility
python3 a3d.py
```

The launcher checks for the packages it needs and offers to install them on first
run. That's it — you land in the arrow-key menu.

> No `git`? Download the repo as a ZIP from the green **Code** button on
> [the GitHub page](https://github.com/auntiepickle/Analogue3DUtility), unzip it,
> then in Terminal `cd` into the folder and run `python3 a3d.py`.

---

## Recommended for the binary: download with `curl`

If you'd rather use the standalone binary, **download it with `curl` instead of
your browser**:

```bash
cd ~/Desktop
curl -L -o a3d-macos https://github.com/auntiepickle/Analogue3DUtility/releases/latest/download/a3d-macos
chmod +x a3d-macos
./a3d-macos
```

**Why this works:** files downloaded with `curl` don't get macOS's
`com.apple.quarantine` flag (unlike downloads from Safari, Chrome, or Firefox). No
quarantine flag means Gatekeeper doesn't put up its warning-and-approval wall.

In macOS testing, a fresh `curl` download launched with **no Gatekeeper dialogs and
no System Settings steps** at all.

> The binary is only ad-hoc signed, so on some machines or macOS versions you might
> still get a one-time prompt the first time you run it. It wasn't needed in
> testing, but if you see one: open **System Settings -> Privacy & Security**,
> scroll to the bottom, click **Open Anyway** next to the `a3d-macos` message, then
> run the command again.

---

## Already downloaded it in a browser? (recovery)

A browser download gets quarantined, so you'll hit the warnings. The simplest fix
is to just re-download it with the `curl` command above. To use the file you
already have:

1. Move it out of **Downloads** (heavily locked down) onto your **Desktop**.
2. Clear the quarantine flag and make it runnable:
   ```bash
   cd ~/Desktop
   xattr -cr a3d-macos
   chmod +x a3d-macos
   ./a3d-macos
   ```
   (Or run the bundled helper, which does this for you:
   `bash scripts/macos-launch-helper.sh a3d-macos`.)
3. If a popup still appears, click **Done** (never "Move to Trash"), open
   **System Settings -> Privacy & Security**, scroll to the bottom, click **Open
   Anyway** next to the `a3d-macos` message, authenticate, and run `./a3d-macos`
   again. Sometimes it takes two tries.

**"Operation not permitted" on `xattr`/`chmod`?** You're probably still in
Downloads — move the file to the Desktop. If it persists, grant Terminal **Full
Disk Access** in System Settings -> Privacy & Security, or prefix the commands with
`sudo`.

---

## After it launches: two macOS SD-card gotchas

These are about the SD card, not Gatekeeper:

- **Backup says 0 MB / looks empty.** Some Mac card readers cause the tool to miss
  the `Library` / `Settings` / `Memories` folders. The tool now probes for them
  directly and reports the real backup size, warning you if it's suspiciously
  small. If you still get a tiny backup, re-seat the card or try a different reader.
- **`[Errno 30] Read-only file system`.** macOS mounted the card read-only (common
  after a filesystem hiccup or with flaky readers). The tool now catches this and
  tells you instead of crashing. Fix: safely eject and re-insert the card, run First
  Aid on it in Disk Utility, or try a different reader.

---

If something here didn't work, please
[open an issue](https://github.com/auntiepickle/Analogue3DUtility/issues) with your
macOS version and the exact error text — it helps make this smoother for the next
person.
