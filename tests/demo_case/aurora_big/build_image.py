"""Deterministic synthetic HDD + mobile device storage images.

Builds two unpartitioned FAT16 raw disk images for an IDFA exhibition demo:

* ``computer_hdd.img``  (~300 MB) - a fictional workstation hard drive
* ``mobile_storage.img`` (~300 MB) - a fictional mobile device (phone/SD) storage

Both are wholly synthetic fiction. People, addresses, devices, messages and
events are invented. Reserved ``example.test`` mailboxes, TEST-NET addresses
and a deliberately invalid ``bc1q…`` placeholder are documentation values.

Design goals
------------
* ~330 MB total so the demo visibly scales beyond the small Aurora samples.
* Deterministic: fixed seed, fixed timestamps, identical bytes on rebuild.
* Dense hidden relationships: the same e-mail addresses, phone numbers, device
  IDs, transfer IDs and shared filenames occur in files on BOTH devices, so the
  IDFA entity/relationship graph produces real cross-device edges.
* Rich natural-language text (emails, messages, reports, logs) so the content is
  suitable for semantic embedding / RAG extraction. A few multi-megabyte files
  make the images genuinely "big data" while the small files carry the links.
* FAT16 single-filesystem layout readable by pytsk3 at offset 0 (no partition
  table), matching the existing Aurora/Harbor pattern.

The builder refuses to overwrite a different existing image and leaves an
identical one untouched. It does not import the application, start services or
call any model.
"""

from __future__ import annotations

import hashlib
import struct
from pathlib import Path

SECTOR = 512
SECTORS_PER_CLUSTER = 8           # 4 KiB clusters -> ~76,800 clusters for 300 MB, above the
                                  # 65,525 threshold so pytsk3 auto-detects FAT32.
CLUSTER = SECTOR * SECTORS_PER_CLUSTER
RESERVED_SECTORS = 32             # boot + FS info + backup boot
FAT_COUNT = 2
END_OF_CHAIN = 0x0FFFFFFF         # FAT32 end-of-chain marker

# Fixed construction timestamp (FAT has no TZ; treated as a marker, not evidence).
FAT_DATE = (46 << 9) | (10 << 5) | 28      # 2026-10-28
FAT_TIME = (12 << 11)                      # 12:00:00

# Identifiers intentionally shared across the two devices so the graph links
# computer and mobile evidence together. Each appears in multiple files.
SHARED_EMAILS = (
    "alice.mercer@corp.example.test",
    "bob.renn@corp.example.test",
    "dana.cross@example.test",
    "contractor@example.test",
)
SHARED_PHONES = ("+1-555-0100", "+1-555-0200", "+44-20-7946-0300")
SHARED_DEVICES = ("HDD-ASSET-07", "MOBILE-IMEI-0099")
SHARED_TRANSFERS = ("TX-FILE-19", "TX-FILE-31")
SHARED_WALLET = "bc1qbigsyntheticplaceholder00000000000000000000"
SHARED_NAMES = ("Alice Mercer", "Bob Renn", "Dana Cross")
SHARED_FILENAMES = ("LEDGER.CSV", "MANIFEST.TXT")

BANNER = (
    "SYNTHETIC FICTION - NOT REAL EVIDENCE\r\n"
    "Times below are source claims in UTC (+00:00), not verified.\r\n"
)


def _dir_entry(name: str, attr: int, cluster_hi: int, cluster_lo: int, size: int) -> bytes:
    entry = bytearray(32)
    name_bytes = name.encode("ascii").upper().ljust(11)[:11]
    entry[0:11] = name_bytes
    entry[11] = attr
    entry[20:22] = struct.pack("<H", cluster_hi)
    entry[22:24] = struct.pack("<H", FAT_TIME)
    entry[24:26] = struct.pack("<H", FAT_DATE)
    entry[26:28] = struct.pack("<H", cluster_lo)
    entry[28:32] = struct.pack("<I", size)
    return bytes(entry)


def _boot_sector(total_sectors: int, sectors_per_fat: int, oem: bytes) -> bytes:
    boot = bytearray(SECTOR)
    boot[0:3] = b"\xeb\x3c\x90"
    boot[3:11] = oem.ljust(8)[:8]
    struct.pack_into("<H", boot, 11, SECTOR)
    boot[13] = SECTORS_PER_CLUSTER
    struct.pack_into("<H", boot, 14, RESERVED_SECTORS)
    boot[16] = FAT_COUNT
    struct.pack_into("<H", boot, 17, 0)           # FAT32: root entry count = 0
    struct.pack_into("<I", boot, 32, total_sectors)
    boot[21] = 0xF8                               # media descriptor (fixed disk)
    struct.pack_into("<H", boot, 22, 0)           # FAT32: FAT16 spfat = 0
    struct.pack_into("<H", boot, 24, 63)          # sectors per track
    struct.pack_into("<H", boot, 26, 255)         # heads
    struct.pack_into("<I", boot, 28, 0)           # hidden sectors
    struct.pack_into("<I", boot, 36, sectors_per_fat)  # FAT32 sectors per FAT
    struct.pack_into("<I", boot, 44, 2)           # FAT32 root directory cluster
    struct.pack_into("<H", boot, 48, 1)           # FS info sector
    struct.pack_into("<H", boot, 50, 6)           # backup boot sector
    boot[510:512] = b"\x55\xaa"
    return bytes(boot)


def build_image(
    label: bytes,
    target_bytes: int,
    files: list[tuple[str, bytes]],
) -> bytes:
    """Build one FAT32 image with all ``files`` in the root directory (cluster 2).

    FAT32 with 4 KiB clusters gives ~76,800 clusters for 300 MB -- above the
    65,525 threshold so pytsk3 auto-detects FAT32 and walks the root directory
    cluster (cluster 2) reliably. The root directory is a regular cluster chain
    starting at cluster 2, matching the standard FAT32 layout.

    Every file lives in root. Names are short 8.3 and prefixed to hint at their
    logical origin (e.g. ``HDD-RPT1.TXT`` vs ``MOB-SMS1.TXT``). The shared
    identifiers embedded in the file *content* are what create the cross-device
    graph edges.
    """
    total_sectors = max(target_bytes // SECTOR, RESERVED_SECTORS + 2 * 128)
    # FAT32 entries are 4 bytes; sectors per FAT covers cluster count + 2 reserved.
    data_clusters = (total_sectors - RESERVED_SECTORS) // SECTORS_PER_CLUSTER
    sectors_per_fat = max(
        256, (data_clusters * 4 + SECTOR - 1) // SECTOR
    )
    fat_sectors = FAT_COUNT * sectors_per_fat
    # Data area starts immediately after both FATs (no fixed root dir area).
    data_offset = (RESERVED_SECTORS + fat_sectors) * SECTOR
    # Recompute total so the layout fits exactly.
    total_sectors = (data_offset + data_clusters * SECTORS_PER_CLUSTER * SECTOR) // SECTOR
    image_size = total_sectors * SECTOR

    image = bytearray(image_size)

    boot = _boot_sector(total_sectors, sectors_per_fat, label)
    image[0:SECTOR] = boot
    image[SECTOR * 6:SECTOR * 7] = boot  # backup boot sector

    fat_offset = RESERVED_SECTORS * SECTOR
    fat_size = sectors_per_fat * SECTOR
    cluster_bytes = SECTORS_PER_CLUSTER * SECTOR

    # FAT32: 4-byte entries. cluster 0 = media, 1 = reserved, 2 = root dir.
    fat = [0x0FFFFFF8, 0x0FFFFFFFF, END_OF_CHAIN] + [0] * (data_clusters - 2)

    def cluster_offset(cluster: int) -> int:
        return data_offset + (cluster - 2) * cluster_bytes

    def write_cluster(cluster: int, payload: bytes) -> None:
        base = cluster_offset(cluster)
        image[base:base + len(payload)] = payload

    def set_fat(cluster: int, value: int) -> None:
        fat[cluster] = value

    next_cluster = 3  # 0,1 reserved; 2 = root dir

    def allocate_chain(count: int) -> list[int]:
        nonlocal next_cluster
        clusters = []
        for _ in range(count):
            clusters.append(next_cluster)
            next_cluster += 1
        return clusters

    # ---- root directory (cluster 2, may span multiple clusters) ----
    root_entries = bytearray()
    root_entries += _dir_entry(".", 0x10, 0, 2, 0)
    root_entries += _dir_entry("..", 0x10, 0, 2, 0)
    root_cluster = 2
    root_clusters = [2]
    set_fat(2, END_OF_CHAIN)

    def flush_root() -> None:
        nonlocal root_entries, root_cluster
        root_entries = root_entries.ljust(cluster_bytes, b"\x00")[:cluster_bytes]
        write_cluster(root_cluster, root_entries)

    def add_root_entry(entry: bytes) -> None:
        nonlocal root_entries, root_cluster
        root_entries += entry
        if len(root_entries) >= cluster_bytes:
            flush_root()
            root_cluster = next_cluster
            next_cluster += 1
            set_fat(root_clusters[-1], root_cluster)
            set_fat(root_cluster, END_OF_CHAIN)
            root_clusters.append(root_cluster)
            root_entries = bytearray()

    for name, content in files:
        short = name.upper()
        if len(short) > 11:
            base = short[:6]
            ext = short[-3:]
            short = f"{base}~1.{ext}"
        short_name = short.upper().ljust(11)[:11]
        clusters_needed = (len(content) + cluster_bytes - 1) // cluster_bytes
        clusters = allocate_chain(clusters_needed)
        for i, c in enumerate(clusters):
            nxt = clusters[i + 1] if i + 1 < len(clusters) else END_OF_CHAIN
            set_fat(c, nxt)
            chunk = content[i * cluster_bytes:(i + 1) * cluster_bytes]
            write_cluster(c, chunk.ljust(cluster_bytes, b"\x00")[:cluster_bytes])
        fc = clusters[0]
        add_root_entry(
            _dir_entry(short_name, 0x20, fc >> 16, fc & 0xFFFF, len(content)),
        )
    flush_root()
    # Ensure last root cluster is EOC.
    set_fat(root_clusters[-1], END_OF_CHAIN)

    # Write both FATs (4-byte entries).
    fat_bytes = struct.pack("<" + "I" * len(fat), *fat)
    fat_padded = fat_bytes.ljust(fat_size, b"\x00")[:fat_size]
    image[fat_offset:fat_offset + fat_size] = fat_padded
    image[fat_offset + fat_size:fat_offset + 2 * fat_size] = fat_padded

    return bytes(image)

# ---- fixed root directory ----
    root_entries = bytearray()
    root_entries += _dir_entry(".", 0x10, 0, 2, 0)
    root_entries += _dir_entry("..", 0x10, 0, 2, 0)

    for name, content in files:
        short = name.upper()
        if len(short) > 11:
            base = short[:6]
            ext = short[-3:]
            short = f"{base}~1.{ext}"
        short_name = short.upper().ljust(11)[:11]
        clusters_needed = (len(content) + cluster_bytes - 1) // cluster_bytes
        clusters = allocate_chain(clusters_needed)
        for i, c in enumerate(clusters):
            nxt = clusters[i + 1] if i + 1 < len(clusters) else END16
            set_fat(c, nxt)
            chunk = content[i * cluster_bytes:(i + 1) * cluster_bytes]
            write_cluster(c, chunk.ljust(cluster_bytes, b"\x00")[:cluster_bytes])
        fc = clusters[0]
        root_entries += _dir_entry(short_name, 0x20, fc >> 16, fc & 0xFFFF, len(content))

    root_entries = root_entries.ljust(root_dir_bytes, b"\x00")[:root_dir_bytes]
    image[root_offset:root_offset + len(root_entries)] = root_entries

    # Write both FATs (2-byte entries).
    fat_bytes = struct.pack("<" + "H" * len(fat), *fat)
    fat_padded = fat_bytes.ljust(fat_size, b"\x00")[:fat_size]
    image[fat_offset:fat_offset + fat_size] = fat_padded
    image[fat_offset + fat_size:fat_offset + 2 * fat_size] = fat_padded

    return bytes(image)


# ---------------------------------------------------------------------------
# Content generators (deterministic, synthetic, rich text for RAG)
# ---------------------------------------------------------------------------

def _block(index: int, kind: str) -> str:
    """One deterministic block of synthetic text, roughly 1 KiB."""
    lines = []
    for k in range(16):
        lines.append(
            f"{kind.upper()} block {index}-{k}: "
            f"{SHARED_NAMES[(index + k) % 3]} "
            f"({SHARED_EMAILS[(index + k) % 4]}) "
            f"phone {SHARED_PHONES[(index + k) % 3]} "
            f"device {SHARED_DEVICES[(index + k) % 2]} "
            f"transfer {SHARED_TRANSFERS[(index + k) % 2]} "
            f"file {SHARED_FILENAMES[(index + k) % 2]} "
            f"wallet {SHARED_WALLET}. "
            f"Invented narrative detail {index * 1000 + k} for training scenarios. "
        )
    return "\r\n".join(lines) + "\r\n"


def sized_text(target_bytes: int, index: int, kind: str) -> str:
    """Deterministic text of approximately ``target_bytes`` bytes."""
    block = _block(index, kind)
    repeats = max(1, target_bytes // len(block) + 1)
    text = block * repeats
    return text[:target_bytes]


def email_text(index: int) -> str:
    sender = SHARED_EMAILS[index % len(SHARED_EMAILS)]
    recipient = SHARED_EMAILS[(index + 1) % len(SHARED_EMAILS)]
    return (
        f"From: {sender}\r\n"
        f"To: {recipient}\r\n"
        f"Subject: Fictional project update {index}\r\n"
        f"Date: 2026-10-28T09:{index % 60:02d}:00+00:00\r\n\r\n"
        f"This is a fictional email from {SHARED_NAMES[index % len(SHARED_NAMES)]} "
        f"discussing project plans. Contact {sender} or phone "
        f"{SHARED_PHONES[index % len(SHARED_PHONES)]}. "
        f"Device reference {SHARED_DEVICES[index % len(SHARED_DEVICES)]}. "
        f"Related transfer {SHARED_TRANSFERS[index % len(SHARED_TRANSFERS)]}. "
        f"See the attached {SHARED_FILENAMES[index % len(SHARED_FILENAMES)]} for figures. "
        f"All names and addresses are reserved documentation values.\r\n\r\n"
    )


def manifest_text(index: int) -> str:
    return (
        "FICTIONAL STAGING MANIFEST\r\n"
        f"compiled by {SHARED_NAMES[index % 3]}\r\n"
        f"contact {SHARED_EMAILS[index % 4]} phone {SHARED_PHONES[index % 3]}\r\n"
        f"device {SHARED_DEVICES[index % 2]} transfer {SHARED_TRANSFERS[index % 2]}\r\n"
        f"wallet {SHARED_WALLET}\r\n"
        "files: LEDGER.CSV, MANIFEST.TXT (shared across devices)\r\n"
        + "\r\n".join(f"entry {k}: synthetic inventory row." for k in range(50))
        + "\r\n"
    )


FILE_SPECS = (
    # (device, flat_8.3_name, size_bytes, kind, index_base)
    # --- computer HDD ---
    ("hdd", "RPT1.TXT", 300_000, "report", 1),
    ("hdd", "RPT2.TXT", 300_000, "report", 2),
    ("hdd", "LEDGER.CSV", 40_000, "ledger", 1),
    ("hdd", "INVOIC1.TXT", 300_000, "report", 3),
    ("hdd", "BIGLOG.LOG", 40_000_000, "systemlog", 1),
    ("hdd", "INBOX.TXT", 80_000, "email", 1),
    ("hdd", "SENT.TXT", 80_000, "email", 2),
    ("hdd", "DRAFT.TXT", 80_000, "email", 3),
    ("hdd", "SYS.LOG", 200_000, "syslog", 1),
    ("hdd", "AUTH.LOG", 200_000, "authlog", 1),
    ("hdd", "ALICE.TXT", 60_000, "notes", 1),
    ("hdd", "BOB.TXT", 60_000, "notes", 2),
    ("hdd", "MANIFEST.TXT", 10_000, "manifest", 1),
    # --- mobile device storage ---
    ("mobile", "SMS1.TXT", 100_000, "message", 1),
    ("mobile", "CHAT1.TXT", 100_000, "message", 2),
    ("mobile", "SMS2.TXT", 100_000, "message", 3),
    ("mobile", "VCARD1.TXT", 60_000, "contact", 1),
    ("mobile", "VCARD2.TXT", 60_000, "contact", 2),
    ("mobile", "LEDGER.CSV", 40_000, "ledger", 1),
    ("mobile", "MANIFEST.TXT", 10_000, "manifest", 1),
    ("mobile", "PHOTO.TXT", 200_000, "photometadata", 1),
    ("mobile", "PERSON.TXT", 60_000, "notes", 3),
    ("mobile", "BIGARC.TXT", 30_000_000, "archive", 1),
)


def _content_for(kind: str, index: int, size_bytes: int) -> bytes:
    if kind == "email":
        text = email_text(index)
    elif kind == "manifest":
        text = manifest_text(index)
    else:
        text = sized_text(size_bytes, index, kind)
    return (BANNER + text).encode("ascii")


IMAGES = {
    "computer_hdd.img": (b"IDFAHDD ", 300 * 1024 * 1024),
    "mobile_storage.img": (b"IDFAMOB ", 300 * 1024 * 1024),
}


def write_image(path: Path, image: bytes) -> str:
    try:
        with path.open("xb") as stream:
            stream.write(image)
    except FileExistsError:
        if path.read_bytes() != image:
            raise FileExistsError(f"Refusing to overwrite different existing image: {path}") from None
    return hashlib.sha256(image).hexdigest()


def build_all(destination: Path) -> dict[str, str]:
    destination.mkdir(parents=True, exist_ok=True)
    digests: dict[str, str] = {}
    for img_name, (label, target) in IMAGES.items():
        device_key = "hdd" if "hdd" in img_name else "mobile"
        specs = [s for s in FILE_SPECS if s[0] == device_key]
        image_files = [
            (name, _content_for(kind, idx, size))
            for (dev, name, size, kind, idx) in specs
        ]
        image = build_image(label, target, image_files)
        digest = write_image(destination / img_name, image)
        digests[img_name] = digest
        print(f"{img_name}: {len(image):,} bytes, SHA-256: {digest}")
    return digests


if __name__ == "__main__":
    here = Path(__file__).resolve().parent
    build_all(here)
