"""Build a deterministic, synthetic FAT12 disk image for the IDFA demo."""

import hashlib
import struct
from pathlib import Path


FILES = (
    (b"MESSAGE TXT", b"Synthetic note: contact sable-courier-47@example.test about the transfer.\r\n"),
    (b"RECEIPT TXT", b"Synthetic receipt: reply to sable-courier-47@example.test for confirmation.\r\n"),
    (b"LUNCH   TXT", b"Synthetic lunch inventory: apples, bread, and tea.\r\n"),
)


def main():
    image = bytearray(1_474_560)
    image[:3] = b"\xeb\x3c\x90"
    image[3:11] = b"IDFADEMO"
    struct.pack_into("<HBHBHHBHHHII", image, 11, 512, 1, 1, 2, 224, 2880, 0xF0, 9, 18, 2, 0, 0)
    image[510:512] = b"\x55\xaa"
    fat = bytearray(9 * 512)
    fat[:8] = b"\xf0\xff\xff\xff\xff\xff\xff\x0f"
    image[512:512 + len(fat)] = fat
    image[5120:5120 + len(fat)] = fat
    for i, (name, content) in enumerate(FILES):
        entry = 19 * 512 + i * 32
        image[entry:entry + 11] = name
        image[entry + 11] = 0x20
        struct.pack_into("<H", image, entry + 26, i + 2)
        struct.pack_into("<I", image, entry + 28, len(content))
        offset = (33 + i) * 512
        image[offset:offset + len(content)] = content
    path = Path(__file__).with_name("synthetic_demo.img")
    if path.exists() and path.read_bytes() != image:
        raise SystemExit(f"Refusing to overwrite different existing image: {path}")
    path.write_bytes(image)
    print(f"{path}\nSHA-256: {hashlib.sha256(image).hexdigest()}")


if __name__ == "__main__":
    main()
