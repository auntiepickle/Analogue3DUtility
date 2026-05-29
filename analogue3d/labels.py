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
import json
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


def _insert_or_update_slot(db_path, cart_id, slot):
    """Write a 25600-byte slot for cart_id: overwrite if present, else sorted insert.
    Returns 'updated' or 'inserted'."""
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


def _read_slot(db_path, cart_id):
    """Raw 25600-byte slot for cart_id from a labels.db, or None if absent."""
    ids = read_ids(db_path)
    if cart_id not in ids:
        return None
    index = ids.index(cart_id)
    with open(db_path, "rb") as f:
        f.seek(DATA_START + index * SLOT_SIZE)
        slot = f.read(SLOT_SIZE)
    return slot if len(slot) == SLOT_SIZE else None


def label_matches(db_a, db_b, cart_id_hex):
    """True if both labels.db files hold the identical image slot for a cart -
    used to tell whether a cart's custom art is actually live on the card."""
    try:
        cid = int(cart_id_hex, 16)
    except (TypeError, ValueError):
        return False
    try:
        a = _read_slot(db_a, cid)
    except OSError:
        return False
    if a is None:
        return False
    try:
        b = _read_slot(db_b, cid)
    except OSError:
        return False
    return a == b


def set_label(db_path, cart_id_hex, image_path):
    """Write a custom image for cart_id into labels.db (overwrite or sorted insert)."""
    cart_id = int(cart_id_hex, 16)
    return _insert_or_update_slot(db_path, cart_id, image_to_slot(image_path))


def remove_label(db_path, cart_id_hex):
    """Remove a cart's entry + image slot from labels.db. True if it was present."""
    cart_id = int(cart_id_hex, 16)
    ids = read_ids(db_path)
    if cart_id not in ids:
        return False
    index = ids.index(cart_id)
    new_ids = ids[:index] + ids[index + 1:]
    with open(db_path, "rb") as f:
        header = f.read(HEADER_LEN)
        f.seek(DATA_START)
        slots = f.read(len(ids) * SLOT_SIZE)
    table = bytearray(b"\xff" * ID_TABLE_BYTES)
    if new_ids:
        struct.pack_into("<" + "I" * len(new_ids), table, 0, *new_ids)
    new_data = slots[:index * SLOT_SIZE] + slots[(index + 1) * SLOT_SIZE:]
    tmp = db_path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(header)
        f.write(table)
        f.write(new_data)
    os.replace(tmp, db_path)
    return True


def _community_cache_path():
    return os.path.join(os.path.dirname(config.config_path()), "community_labels.db")


def community_cache():
    """Path to the cached community pack if already downloaded, else None. Never
    downloads - safe for cheap preview reads."""
    p = _community_cache_path()
    return p if os.path.isfile(p) else None


def community_db():
    """Local cached copy of the community (RetroGameCorps) labels.db, downloading
    it once into the app dir. Returns the path, or None if the download fails."""
    from . import sdcard
    dest = _community_cache_path()
    if not os.path.isfile(dest):
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        try:
            sdcard.download_file(sdcard.LABELS_DB_URL,
                                 dest_folder=os.path.dirname(dest),
                                 filename=os.path.basename(dest))
        except Exception:
            return None
    return dest if os.path.isfile(dest) else None


def reset_label(db_path, cart_id_hex):
    """Drop a cart's custom override: restore the community art for it if the
    community pack has it, else remove the slot entirely. Returns 'reverted',
    'removed', or None if the cart had no entry to begin with."""
    cart_id = int(cart_id_hex, 16)
    if cart_id not in read_ids(db_path):
        return None
    comm = community_db()
    slot = _read_slot(comm, cart_id) if comm else None
    if slot is not None:
        _insert_or_update_slot(db_path, cart_id, slot)
        return "reverted"
    remove_label(db_path, cart_id_hex)
    return "removed"


# --- the user's own "My custom labels" pack -------------------------------
# Setting custom art edits the card's labels.db and snapshots it here, so it's
# selectable as its own source and used as Auto's default. Installing the plain
# The RetroGameCorps pack stays clean (no overrides forced on) so reverting works.
def custom_pack_path():
    """Local path of the user's own labels.db (their pack with custom art)."""
    return config.backup_dir("custom_labels.db")


def has_custom_pack():
    return os.path.isfile(custom_pack_path())


def save_custom_pack(src_db_path):
    """Snapshot the just-customized labels.db as the user's own selectable pack
    (becomes the 'My custom labels' source + Auto's default)."""
    if not os.path.isfile(src_db_path):
        return None
    dest = custom_pack_path()
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    shutil.copy2(src_db_path, dest)
    return dest


# Which carts the user has personally overridden. Tracked explicitly (recorded on
# set, removed on revert) so the UI can show a "Revert" only on carts you changed,
# not on every stock cart.
def _overrides_path():
    return custom_pack_path() + ".overrides.json"


def overridden_carts():
    """Set of 8-hex cart IDs the user has applied custom art to."""
    try:
        with open(_overrides_path(), encoding="utf-8") as f:
            return {str(c).lower() for c in json.load(f)}
    except (OSError, ValueError):
        return set()


def _save_overrides(ids):
    p = _overrides_path()
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(sorted(ids), f)
    except OSError:
        pass


def mark_override(cart_id_hex):
    ids = overridden_carts()
    ids.add(str(cart_id_hex).lower())
    _save_overrides(ids)


def unmark_override(cart_id_hex):
    ids = overridden_carts()
    ids.discard(str(cart_id_hex).lower())
    _save_overrides(ids)


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
        save_custom_pack(db_path)
        mark_override(cart_id)
    except (ValueError, OSError) as e:
        print(red(f"Failed: {e}"))
        return
    verb = "Updated" if result == "updated" else "Added"
    print(green(f"{verb} artwork for cart {cart_id}. It'll show on the console next boot."))
    print(dim("Saved into your 'My custom labels' pack (selectable when installing art)."))


__all__ = ["compute_cart_id", "read_ids", "read_label_image", "image_to_slot",
           "set_label", "remove_label", "reset_label", "community_db",
           "community_cache", "label_matches",
           "convert_to_z64", "have_pillow", "run_interactive",
           "custom_pack_path", "has_custom_pack", "save_custom_pack",
           "overridden_carts", "mark_override", "unmark_override"]
