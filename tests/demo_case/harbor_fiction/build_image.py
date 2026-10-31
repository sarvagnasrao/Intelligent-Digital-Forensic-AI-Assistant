"""Build the fictional Harbor lead as an unpartitioned FAT12 image."""
import hashlib
import struct
from pathlib import Path

FILES = (
    (b"NOTE    TXT", b"2026-10-29 09:15\r\nMira: use lantern-bridge-73@example.test to request the Harbor package.\r\n"),
    (b"REPLY   TXT", b"2026-10-29 10:40\r\nTo: lantern-bridge-73@example.test\r\nThe Harbor package is ready for collection. Signed: Rowan.\r\n"),
    (b"STATUS  TXT", b"2026-10-30 08:00\r\nHarbor package status: collection cancelled; package remains in storage.\r\n"),
    (b"GARDEN  TXT", b"2026-10-30 12:00\r\nGarden club list: mint, beans, and watering cans.\r\n"),
)


def main():
    image = bytearray(1_474_560)
    image[:3] = b"\xeb\x3c\x90"
    image[3:11] = b"IDFADEMO"
    struct.pack_into("<HBHBHHBHHHII", image, 11, 512, 1, 1, 2, 224, 2880, 0xF0, 9, 18, 2, 0, 0)
    image[510:512] = b"\x55\xaa"
    fat = bytearray(9 * 512)
    fat[:3] = b"\xf0\xff\xff"
    for i, (name, content) in enumerate(FILES):
        assert len(name) == 11 and len(content) <= 512
        cluster = i + 2
        pos = cluster + cluster // 2
        if cluster % 2:
            fat[pos] = (fat[pos] & 0x0F) | 0xF0
            fat[pos + 1] = 0xFF
        else:
            fat[pos] = 0xFF
            fat[pos + 1] = (fat[pos + 1] & 0xF0) | 0x0F
        entry = 19 * 512 + i * 32
        image[entry:entry + 11] = name
        image[entry + 11] = 0x20
        struct.pack_into("<H", image, entry + 26, cluster)
        struct.pack_into("<I", image, entry + 28, len(content))
        offset = (33 + i) * 512
        image[offset:offset + len(content)] = content
    image[512:512 + len(fat)] = fat
    image[5120:5120 + len(fat)] = fat
    path = Path(__file__).with_name("harbor_fiction.img")
    if path.exists() and path.read_bytes() != image:
        raise SystemExit(f"Refusing to overwrite different existing image: {path}")
    path.write_bytes(image)
    print(f"{path}\nSHA-256: {hashlib.sha256(image).hexdigest()}")


if __name__ == "__main__":
    main()
