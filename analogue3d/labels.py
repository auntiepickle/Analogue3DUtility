"""Custom cartridge artwork for the Analogue 3D, by editing labels.db in place.

labels.db format (verified against the MIT-licensed A3D-Manager):
    0x000  byte 0x07, then ASCII "Analogue-Co..."  (256-byte header)
    0x100  ID table: uint32 LE cart IDs, sorted ascending, 0xFFFFFFFF-terminated
           (16 KiB region -> up to 4096 entries)
    0x4100 image data: one 25600-byte slot per ID (same order). Each slot is
           74*86*4 = 25456 bytes of BGRA pixels (row-major, top-left) followed
           by 144 bytes of 0xFF padding.

A cartridge's ID is CRC32 (zlib/IEEE) of the first 8192 bytes of the ROM after
normalizing it to z64 (big-endian) byte order, written as 8 lowercase hex chars.
Applying a custom image overwrites that cart's slot in place (or inserts a new,
sorted entry if the cart isn't present yet).
"""

import os
import struct
import zlib
import shutil

from .ui import bold, dim, green, yellow, red, ask
from . import config

HEADER_LEN = 256
ID_TABLE_OFFSET = 0x100
ID_TABLE_BYTES = 0x4000          # 16 KiB
MAX_ENTRIES = ID_TABLE_BYTES // 4
DATA_START = 0x4100
SLOT_SIZE = 25600
IMG_W, IMG_H = 74, 86
IMG_BYTES = IMG_W * IMG_H * 4     # 25456 BGRA
PAD = SLOT_SIZE - IMG_BYTES       # 144
TERMINATOR = 0xFFFFFFFF
HASH_SIZE = 8192


def have_pillow():
    try:
        import PIL  # noqa: F401
        return True
    except ImportError:
        return False


def convert_to_z64(data):
    """Normalize a .z64/.n64/.v64 ROM image to z64 (big-endian) byte order."""
    if len(data) < 4:
        return data
    magic = data[:4]
    if magic == b"\x80\x37\x12\x40":          # z64, already big-endian
        return data
    if magic == b"\x37\x80\x40\x12":          # v64, 16-bit byteswapped
        b = bytearray(data)
        b[0::2], b[1::2] = data[1::2], data[0::2]
        return bytes(b)
    if magic == b"\x40\x12\x37\x80":          # n64, 32-bit word-swapped
        out = bytearray(len(data))
        for i in range(0, len(data) - 3, 4):
            out[i:i + 4] = data[i:i + 4][::-1]
        return bytes(out)
    return data                                # unknown - hash as-is


def compute_cart_id(rom_path):
    """Return the 8-hex Analogue 3D cart ID for a ROM file."""
    with open(rom_path, "rb") as f:
        data = f.read(HASH_SIZE * 4)  # enough to normalize + hash
    z64 = convert_to_z64(data)
    crc = zlib.crc32(z64[:HASH_SIZE]) & 0xFFFFFFFF
    return f"{crc:08x}"


def read_ids(db_path):
    """Return the list of cart IDs (ints) present in labels.db, in stored order."""
    with open(db_path, "rb") as f:
        f.seek(ID_TABLE_OFFSET)
        table = f.read(ID_TABLE_BYTES)
    ids = []
    for i in range(0, len(table), 4):
        (cid,) = struct.unpack_from("<I", table, i)
        if cid == TERMINATOR:
            break
        ids.append(cid)
    return ids


def read_label_image(db_path, cart_id_hex):
    """Return a PIL RGBA Image of the cart's stored art in labels.db, or None if
    that cart has no slot. Inverse of image_to_slot (BGRA on disk -> RGBA)."""
    from PIL import Image
    try:
        cart_id = int(cart_id_hex, 16)
    except (TypeError, ValueError):
        return None
    ids = read_ids(db_path)
    if cart_id not in ids:
        return None
    index = ids.index(cart_id)
    with open(db_path, "rb") as f:
        f.seek(DATA_START + index * SLOT_SIZE)
        slot = f.read(IMG_BYTES)
    if len(slot) < IMG_BYTES:
        return None
    rgba = bytearray(IMG_BYTES)
    rgba[0::4] = slot[2::4]  # R <- B
    rgba[1::4] = slot[1::4]  # G
    rgba[2::4] = slot[0::4]  # B <- R
    rgba[3::4] = slot[3::4]  # A
    return Image.frombytes("RGBA", (IMG_W, IMG_H), bytes(rgba))


def image_to_slot(image_path):
    """Resize an image to 74x86 and return a 25600-byte BGRA+padding slot."""
    from PIL import Image, ImageOps
    img = Image.open(image_path).convert("RGBA")
    img = ImageOps.fit(img, (IMG_W, IMG_H), method=Image.LANCZOS, centering=(0.5, 0.5))
    rgba = img.tobytes()  # RGBA, row-major
    bgra = bytearray(len(rgba))
    bgra[0::4] = rgba[2::4]  # B <- R
    bgra[1::4] = rgba[1::4]  # G
    bgra[2::4] = rgba[0::4]  # R <- B
    bgra[3::4] = rgba[3::4]  # A
    return bytes(bgra) + b"\xff" * PAD


def set_label(db_path, cart_id_hex, image_path):
    """Write a custom image for cart_id into labels.db (overwrite or sorted insert)."""
    cart_id = int(cart_id_hex, 16)
    slot = image_to_slot(image_path)
    ids = read_ids(db_path)

    if cart_id in ids:
        index = ids.index(cart_id)
        with open(db_path, "r+b") as f:
            f.seek(DATA_START + index * SLOT_SIZE)
            f.write(slot)
        return "updated"

    # Insert, keeping the ID table sorted ascending.
    if len(ids) >= MAX_ENTRIES:
        raise ValueError("labels.db is full (4096 entries)")
    pos = 0
    while pos < len(ids) and ids[pos] < cart_id:
        pos += 1
    new_ids = ids[:pos] + [cart_id] + ids[pos:]

    with open(db_path, "rb") as f:
        header = f.read(HEADER_LEN)
        f.seek(DATA_START)
        slots = f.read(len(ids) * SLOT_SIZE)

    table = bytearray(b"\xff" * ID_TABLE_BYTES)  # 0xFFFFFFFF terminator padding
    struct.pack_into("<" + "I" * len(new_ids), table, 0, *new_ids)

    new_data = (slots[:pos * SLOT_SIZE] + slot + slots[pos * SLOT_SIZE:])
    tmp = db_path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(header)
        f.write(table)
        f.write(new_data)
    os.replace(tmp, db_path)
    return "inserted"


# --- custom-art overrides (so your art survives a base-pack re-install) ---
def overrides_dir():
    return config.backup_dir("art_overrides")


def _is_hex8(s):
    return len(s) == 8 and all(c in "0123456789abcdef" for c in s.lower())


def list_overrides():
    """{cart_id: image_path} of the user's stored custom-art overrides."""
    d = overrides_dir()
    out = {}
    if not os.path.isdir(d):
        return out
    for f in os.listdir(d):
        stem = os.path.splitext(f)[0].lower()
        if _is_hex8(stem):
            out[stem] = os.path.join(d, f)
    return out


def save_override(cart_id_hex, image_path):
    """Store the original image for a cart so it can be re-applied after any
    base-pack install (re-downscaled fresh each time)."""
    cart_id_hex = cart_id_hex.lower()
    d = overrides_dir()
    os.makedirs(d, exist_ok=True)
    for cid, p in list_overrides().items():   # replace any prior override for this cart
        if cid == cart_id_hex:
            try:
                os.remove(p)
            except OSError:
                pass
    ext = os.path.splitext(image_path)[1].lower() or ".png"
    dest = os.path.join(d, cart_id_hex + ext)
    shutil.copy2(image_path, dest)
    return dest


def apply_overrides(db_path):
    """Re-apply every stored override into labels.db. Returns how many applied."""
    n = 0
    for cart_id, image_path in list_overrides().items():
        try:
            set_label(db_path, cart_id, image_path)
            n += 1
        except (ValueError, OSError):
            pass
    return n


def run_interactive(sd_root):
    print("\n=== Custom Cartridge Artwork ===")
    if not have_pillow():
        print(yellow("This feature needs Pillow. Run: pip install pillow"))
        return

    db_path = os.path.join(sd_root, "Library", "N64", "Images", "labels.db")
    if not os.path.isfile(db_path):
        print(yellow("No labels.db on the card yet."))
        print(dim("Install a cartridge art pack first, then come back."))
        return

    image_path = ask("Path to your image (PNG/JPG, will be resized to 74x86): ").strip('"')
    if not image_path or not os.path.isfile(image_path):
        print(red("Image not found. Cancelled."))
        return

    print("\nWhich cartridge is this art for?")
    print(f"  {bold('1')})  Point me at the game's ROM file (I'll compute its ID)")
    print(f"  {bold('2')})  I know the 8-character cart ID")
    print(f"  {bold('0')})  Cancel")
    how = ask("Choose: ").lower()
    if how == "1":
        rom = ask("Path to the ROM (.z64/.n64/.v64): ").strip('"')
        if not rom or not os.path.isfile(rom):
            print(red("ROM not found. Cancelled."))
            return
        cart_id = compute_cart_id(rom)
        print(dim(f"Computed cart ID: {cart_id}"))
    elif how == "2":
        cart_id = ask("Enter the 8-character cart ID: ").strip().lower()
        if len(cart_id) != 8 or any(c not in "0123456789abcdef" for c in cart_id):
            print(red("That isn't a valid 8-character hex ID. Cancelled."))
            return
    else:
        print("Cancelled.")
        return

    try:
        result = set_label(db_path, cart_id, image_path)
        save_override(cart_id, image_path)  # keep it across future art-pack installs
    except (ValueError, OSError) as e:
        print(red(f"Failed: {e}"))
        return
    verb = "Updated" if result == "updated" else "Added"
    print(green(f"{verb} artwork for cart {cart_id}. It'll show on the console next boot."))
    print(dim("Saved as a custom override - it'll be re-applied if you reinstall an art pack."))


__all__ = ["compute_cart_id", "read_ids", "read_label_image", "image_to_slot",
           "set_label", "convert_to_z64", "have_pillow", "run_interactive",
           "overrides_dir", "list_overrides", "save_override", "apply_overrides"]
