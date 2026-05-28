#!/usr/bin/env python3
"""
8BitDo 64 Bluetooth Controller firmware updater (the Analogue 3D pad).

Flashes the controller over its USB-C cable directly, with no 8BitDo Ultimate
Software, no browser, and no Windows driver swap. The protocol below was
reverse-engineered from 8BitDo's own WebHID updater (web.8bitdo.com) and
verified live against a real 8BitDo 64 (USB 2dc8:3019, firmware "Type 78",
shared with the "Ultimate N64" line).

Transport
---------
Plain USB HID on the game-pad interface (MI_00, usage page 0x01 / usage 0x05).
 - Output reports use reportId 0x81; 64 bytes total:
     [0x81][prefix][cmd u16][cmd_params u16][len u16][crc16 u16]
           [total_len u32][offset u32][<=46 data bytes]
   `prefix` is 5 for normal commands, 4 for StopSendKey. `crc16` covers the
   data payload only (CRC-16/MODBUS, poly 0xA001, init 0xFFFF).
 - Input/response reports arrive on reportId 0x02 (ignore 0x03/0x04 = the
   normal gamepad / keyboard input streams). Payload after the reportId byte:
     [m/prefix][status u16][cmd_params(=original cmd) u16][len u16][crc u16]
               [total_len u32][offset u32][data...]
   status == 0 means ACK; cmd_params echoes the command that was sent.

Flash sequence (the 64 flashes in app mode — there is NO bootloader jump)
-------------------------------------------------------------------------
 on open:  StopSendKey (cmd 7, prefix 4) to silence the input stream
 .dat header (28 bytes, little-endian):
     version u32, desAddress u32, desLen u32, pid u32, reserved1 u32,
     revision u32, reserved2 u32
   firmware payload = dat[28 : 28+desLen]; flashed to desAddress.
 differential flash, per 4096-byte block:
     our_crc = crc16(block)
     dev_crc = READ_CRC (cmd 0xC3, payload [address u32, 4096 u32, 4096 u32])
     if our_crc != dev_crc:
         ERASE  (cmd 4, total_len=blocklen, offset=address)
         WRITE  (cmd 3) the block in 46-byte chunks; each chunk's crc16 in header
 FLASH_INFO (cmd 0xC4, payload [file_length u32, file_version u32])
 RESET      (cmd 7, fire-and-forget) -> controller reboots into new firmware

Version encoding: integer == major*100 + minor (203 -> "2.03", 204 -> "2.04").
"""

import struct
import time

import requests

try:
    import hid  # provided by the `hidapi` pip package
except ImportError:  # pragma: no cover - surfaced to the user by the caller
    hid = None

VID = 0x2DC8
PID_APP = 0x3019
FIRMWARE_TYPE = 78

# The newest firmware release this tool's flash path has actually been verified
# against (encoded as major*100 + minor, so 204 == v2.04). Anything newer that
# 8BitDo publishes is flagged as "untested" until a maintainer validates it and
# bumps this value. See the "Supported firmware" section of the README.
MAX_TESTED_VERSION = 204  # v2.04
FIRMWARE_API = "http://dl.8bitdo.com:8080/firmware/select"
FIRMWARE_API_BASE = "http://dl.8bitdo.com:8080"

REPORT_ID_OUT = 0x81
RESP_IGNORE_IDS = {0x03, 0x04}  # normal gamepad / keyboard input reports
PREFIX_NORMAL = 5
PREFIX_STOPKEY = 4
STATUS_ACK = 0

# command opcodes (resolved from the updater's minified constants)
CMD_WRITE = 0x03        # write a flash chunk
CMD_ERASE = 0x04        # erase a flash region
CMD_RESET = 0x07        # save & reset
CMD_STOPKEY = 0x07      # stop sending input (distinguished by prefix byte 4)
CMD_READ_PID = 0x08
CMD_GET_VERSION = 0x21
CMD_READ_CRC = 0xC3     # ask the device for its CRC16 of a flash region
CMD_FLASH_INFO = 0xC4   # commit: tell the device the file length + version

BLOCK = 4096            # differential-compare block size
CHUNK = 46              # max data bytes per write report
CRC_PAYLOAD_LEN = 12    # READ_CRC payload: address, len, block_size (3 x u32)
FLASH_INFO_LEN = 8      # FLASH_INFO payload: file_length, file_version (2 x u32)
HEADER_LEN = 28         # .dat header size

_CRC_TABLE = (0, 0xA001)


def crc16_modbus(data, length=None):
    """CRC-16/MODBUS, matching the updater's Z() function."""
    if length is None:
        length = len(data)
    crc = 0xFFFF
    for i in range(length):
        n = data[i]
        for _ in range(8):
            crc = (crc >> 1) ^ _CRC_TABLE[(crc ^ n) & 1]
            n >>= 1
    return crc & 0xFFFF


def format_version(v):
    return f"{v // 100}.{v % 100:02d}"


class ControllerError(Exception):
    pass


class EightBitDo64:
    """USB-HID session with an 8BitDo 64 controller in app mode."""

    def __init__(self):
        self.dev = None

    @staticmethod
    def find_path():
        """Return the HID path of the 64's game-pad interface, or None."""
        if hid is None:
            raise ControllerError("The 'hidapi' package is not installed (pip install hidapi).")
        candidates = hid.enumerate(VID, PID_APP)
        if not candidates:
            return None
        for d in candidates:  # WebHID uses usage page 0x01 / usage 0x05 (game pad)
            if d.get("usage_page") == 0x01 and d.get("usage") == 0x05:
                return d["path"]
        return candidates[0]["path"]

    def open(self):
        path = self.find_path()
        if path is None:
            raise ControllerError(
                "8BitDo 64 not found. Connect it by USB-C, power it on, and try again."
            )
        self.dev = hid.device()
        self.dev.open_path(path)
        self.stop_send_key()  # silence the input stream so responses come clean
        time.sleep(0.05)
        self._drain()
        return self

    def close(self):
        if self.dev is not None:
            try:
                self.dev.close()
            finally:
                self.dev = None

    def __enter__(self):
        return self.open()

    def __exit__(self, *exc):
        self.close()

    # --- low-level framing ------------------------------------------------
    def _build(self, cmd, cmd_params=0, length=0, crc=0, total_len=0, offset=0,
               payload=None, prefix=PREFIX_NORMAL):
        n = bytearray(63)
        n[0] = prefix
        struct.pack_into("<HHHHII", n, 1, cmd, cmd_params, length, crc, total_len, offset)
        if payload:
            if len(payload) > CHUNK:
                raise ControllerError(f"payload too large: {len(payload)} > {CHUNK}")
            n[17:17 + len(payload)] = payload
        return bytes([REPORT_ID_OUT]) + bytes(n)

    def _write(self, report):
        wrote = self.dev.write(list(report))
        if wrote < 0:
            raise ControllerError("HID write failed")

    def _drain(self):
        for _ in range(64):
            if not self.dev.read(64, 5):
                break

    def _read_response(self, timeout_ms=3000):
        """Return the response payload (bytes after the reportId), or None."""
        deadline = time.time() + timeout_ms / 1000.0
        while time.time() < deadline:
            data = self.dev.read(64, 200)
            if not data:
                continue
            if data[0] in RESP_IGNORE_IDS:
                continue
            return bytes(data[1:])  # strip reportId; matches WebHID's t.data
        return None

    def _command(self, cmd, cmd_params=0, length=0, total_len=0, offset=0,
                 payload=None, prefix=PREFIX_NORMAL, timeout_ms=3000, expect=True):
        crc = crc16_modbus(payload) if payload else 0
        report = self._build(cmd, cmd_params, length, crc, total_len, offset, payload, prefix)
        self._write(report)
        if not expect:
            return None
        resp = self._read_response(timeout_ms)
        if resp is None:
            raise ControllerError(f"no response to cmd 0x{cmd:02x}")
        status, echo = struct.unpack_from("<HH", resp, 1)
        if status != STATUS_ACK or echo != cmd:
            raise ControllerError(
                f"cmd 0x{cmd:02x} rejected (status={status}, echo=0x{echo:04x})"
            )
        return resp

    # --- read-only operations --------------------------------------------
    def stop_send_key(self):
        self._write(self._build(CMD_STOPKEY, prefix=PREFIX_STOPKEY))

    def read_pid(self):
        resp = self._command(CMD_READ_PID, length=4, total_len=4)
        return struct.unpack_from("<I", resp, 17)[0]

    def read_version(self):
        resp = self._command(CMD_GET_VERSION)
        return struct.unpack_from("<H", resp, 17)[0]

    def read_region_crc(self, address):
        payload = struct.pack("<III", address, BLOCK, BLOCK)
        resp = self._command(CMD_READ_CRC, length=CRC_PAYLOAD_LEN,
                             total_len=CRC_PAYLOAD_LEN, offset=address, payload=payload)
        return struct.unpack_from("<H", resp, 17)[0]

    # --- write operations (used only by flash()) -------------------------
    def erase(self, address, length):
        self._command(CMD_ERASE, total_len=length, offset=address, timeout_ms=10000)

    def write_region(self, data, address, total_len):
        n = 0
        end = len(data)
        while n < end:
            size = min(CHUNK, end - n)
            chunk = data[n:n + size]
            self._command(CMD_WRITE, length=size, total_len=total_len,
                          offset=address + n, payload=chunk)
            n += size

    def flash_info(self, file_length, file_version):
        payload = struct.pack("<II", file_length, file_version)
        self._command(CMD_FLASH_INFO, length=FLASH_INFO_LEN, payload=payload)

    def reset(self):
        self._write(self._build(CMD_RESET, prefix=PREFIX_NORMAL))


# --- firmware acquisition ------------------------------------------------
def fetch_firmware_list(beta=False):
    """Return every available firmware release for the 64 (Type 78), newest
    first. Each entry gets a `version_int` (e.g. 204 for 2.04) added."""
    headers = {"Type": str(FIRMWARE_TYPE)}
    if beta:
        headers["Beta"] = "1"
    resp = requests.post(FIRMWARE_API, headers=headers, timeout=20)
    resp.raise_for_status()
    lst = resp.json().get("list") or []
    if not lst:
        raise ControllerError("8BitDo API returned no firmware for the 64 (Type 78).")
    for e in lst:
        e["version_int"] = round(float(e["version"]) * 100)
    lst.sort(key=lambda e: e["version_int"], reverse=True)
    return lst


def fetch_firmware_meta(beta=False):
    """The latest release (kept for convenience / callers that want newest)."""
    return fetch_firmware_list(beta)[0]


def download_firmware(meta):
    url = FIRMWARE_API_BASE + meta["filePathName"]
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    blob = resp.content
    expected = meta.get("fileSize")
    if expected and len(blob) != expected:
        raise ControllerError(
            f"download size mismatch: got {len(blob)}, expected {expected}"
        )
    return blob


def parse_header(blob):
    if len(blob) < HEADER_LEN:
        raise ControllerError("firmware file too small to contain a header")
    version, des_address, des_len, pid, reserved1, revision, reserved2 = \
        struct.unpack_from("<IIIIIII", blob, 0)
    if pid != PID_APP:
        raise ControllerError(
            f"firmware is for pid 0x{pid:04x}, not the 8BitDo 64 (0x{PID_APP:04x})"
        )
    if HEADER_LEN + des_len != len(blob):
        raise ControllerError(
            f"firmware header inconsistent: 28 + desLen ({des_len}) != file size ({len(blob)})"
        )
    return {
        "version": version,
        "desAddress": des_address,
        "desLen": des_len,
        "pid": pid,
        "reserved1": reserved1,
        "revision": revision,
        "payload": blob[HEADER_LEN:HEADER_LEN + des_len],
    }


# --- high-level flows ----------------------------------------------------
def flash(dev, header, progress=None):
    """Flash the firmware, then commit and reset.

    The per-block CRC read is the device-side differential check the official
    updater uses to decide whether to (re)write a block. The 64's firmware is
    written through the device's *encrypted* write path, so the device computes
    its CRC over the decrypted flash while we hold the encrypted .dat -- the two
    never match, so in practice every block is (re)written. That's expected and
    matches the official tool; success is confirmed afterwards by re-reading the
    firmware version once the controller reboots (see run_interactive)."""
    payload = header["payload"]
    des_len = header["desLen"]
    base = header["desAddress"]
    nblocks = (len(payload) + BLOCK - 1) // BLOCK

    written = 0
    for i in range(nblocks):
        block = payload[i * BLOCK:(i + 1) * BLOCK]
        address = base + i * BLOCK
        if crc16_modbus(block) != dev.read_region_crc(address):
            dev.erase(address, len(block))
            dev.write_region(block, address, des_len)
        written += len(block)
        if progress:
            progress(written, des_len, i + 1, nblocks)

    dev.flash_info(des_len, header["version"])
    dev.reset()


def reopen_and_read_version(retries=20, delay=1.5):
    """After a flash+reset the controller reboots and re-enumerates. Poll for it
    and return the firmware version it now reports, or None if it doesn't return."""
    for _ in range(retries):
        time.sleep(delay)
        try:
            dev = EightBitDo64().open()
        except ControllerError:
            continue
        try:
            return dev.read_version()
        except ControllerError:
            continue
        finally:
            dev.close()
    return None


def is_connected():
    """True if an 8BitDo 64 is plugged in and reachable over HID."""
    if hid is None:
        return False
    try:
        return EightBitDo64.find_path() is not None
    except ControllerError:
        return False


def update_to_latest(progress=None):
    """Non-interactive: flash the latest firmware if the connected 64 is behind.
    Returns a short human-readable status string (used by the 'auto' flow)."""
    if hid is None:
        return "skipped (hidapi not installed)"
    if not is_connected():
        return "skipped (controller not connected)"
    try:
        latest = fetch_firmware_list()[0]
        dev = EightBitDo64().open()
        try:
            current = dev.read_version()
            if current >= latest["version_int"]:
                return f"already on {format_version(current)}"
            header = parse_header(download_firmware(latest))  # only download if behind
            flash(dev, header, progress=progress)
        finally:
            dev.close()
    except (ControllerError, OSError, ValueError, struct.error,
            requests.RequestException) as e:
        return f"failed ({e})"
    new_ver = reopen_and_read_version()
    return f"updated to {format_version(new_ver)}" if new_ver else "flashed (verify pending)"


def _progress(written, total, block, nblocks):
    pct = min(100, written * 100 // total)
    bar = "#" * (pct // 4) + "-" * (25 - pct // 4)
    print(f"\r  flashing [{bar}] {pct:3d}%  block {block}/{nblocks}", end="", flush=True)


def _select_version(versions, current):
    """Show the available releases and let the user pick one (default: latest)."""
    print("\nAvailable firmware (newest first):")
    for i, e in enumerate(versions, 1):
        tags = []
        if i == 1:
            tags.append("latest")
        if e["version_int"] == current:
            tags.append("installed")
        if e["version_int"] > MAX_TESTED_VERSION:
            tags.append("untested")
        suffix = "   <- " + ", ".join(tags) if tags else ""
        print(f"  {i}) {format_version(e['version_int'])}{suffix}")
    raw = input("\nSelect a version to flash [Enter = latest, 0 = cancel]: ").strip()
    if raw == "":
        return versions[0]
    if raw == "0":
        return None
    try:
        idx = int(raw) - 1
    except ValueError:
        idx = -1
    if 0 <= idx < len(versions):
        return versions[idx]
    print("Invalid selection.")
    return None


def run_interactive():
    """Menu-callable entry point: detect, pick a version, confirm, flash, verify."""
    print("\n=== Update 8BitDo 64 Controller Firmware ===")
    if hid is None:
        print("The 'hidapi' package is required. Run: pip install hidapi")
        return

    try:
        dev = EightBitDo64().open()
    except ControllerError as e:
        print(e)
        print("Tip: connect the 8BitDo 64 with a USB-C *data* cable and power it on.")
        return

    expected = None
    try:
        try:
            current = dev.read_version()
            pid = dev.read_pid()
        except ControllerError as e:
            print(f"Could not read the controller: {e}")
            return
        print(f"Controller detected (pid 0x{pid:04x}). "
              f"Current firmware: {format_version(current)}")

        try:
            versions = fetch_firmware_list()
        except (requests.RequestException, ControllerError, ValueError) as e:
            print(f"Could not fetch the firmware list: {e}")
            return

        latest = versions[0]["version_int"]
        print(f"This tool is tested up to firmware {format_version(MAX_TESTED_VERSION)}.")
        if latest > MAX_TESTED_VERSION:
            print(f"Heads up: 8BitDo has published {format_version(latest)}, which is newer "
                  f"than that.\nYou can flash it, but it hasn't been verified with this tool yet.")

        sel = _select_version(versions, current)
        if sel is None:
            print("Cancelled.")
            return
        target = sel["version_int"]

        try:
            blob = download_firmware(sel)
            header = parse_header(blob)
        except (requests.RequestException, ControllerError, ValueError) as e:
            print(f"Could not download/verify firmware {format_version(target)}: {e}")
            return
        expected = header["version"]

        if target == current:
            action = f"re-flash the same version ({format_version(target)})"
        elif target < current:
            action = f"DOWNGRADE {format_version(current)} -> {format_version(target)}"
        else:
            action = f"update {format_version(current)} -> {format_version(target)}"

        print("\nFlashing writes the firmware in CRC-checked blocks. The controller")
        print("stays in its bootloader if interrupted, so a failed flash is recoverable")
        print("by simply running this again. Do NOT unplug the controller while flashing.")
        if target < current:
            print("NOTE: this is a downgrade to an older official firmware - supported by")
            print("8BitDo's own updater, but less common than a normal update.")
        if target > MAX_TESTED_VERSION:
            print(f"WARNING: {format_version(target)} is NEWER than the version this tool has")
            print(f"been tested with ({format_version(MAX_TESTED_VERSION)}). It may work, but is "
                  f"not officially supported.")
        confirm = input(f"\nProceed to {action}? Type YES to continue: ").strip()
        if confirm != "YES":
            print("Cancelled.")
            return

        try:
            flash(dev, header, progress=_progress)
            print()  # newline after progress bar
        except ControllerError as e:
            print(f"\nFlash failed: {e}")
            print("The controller is recoverable: reconnect it and run this again,")
            print("or use 8BitDo's official updater as a fallback.")
            return
    finally:
        dev.close()

    print("Controller is rebooting; verifying new firmware...")
    new_ver = reopen_and_read_version()
    if new_ver == expected:
        print(f"Success! Controller is now running firmware {format_version(new_ver)}.")
    elif new_ver is not None:
        print(f"Flashed, but controller reports {format_version(new_ver)} "
              f"(expected {format_version(expected)}). Try power-cycling it.")
    else:
        print(f"Flash sent. Couldn't re-read the controller yet; power-cycle it and "
              f"it should be on {format_version(expected)}.")


__all__ = [
    "EightBitDo64", "ControllerError", "crc16_modbus", "format_version",
    "fetch_firmware_list", "fetch_firmware_meta", "download_firmware",
    "parse_header", "flash", "reopen_and_read_version", "run_interactive",
    "is_connected", "update_to_latest",
]


if __name__ == "__main__":
    run_interactive()
