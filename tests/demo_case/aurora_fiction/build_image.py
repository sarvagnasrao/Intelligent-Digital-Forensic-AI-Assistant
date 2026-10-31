"""Deterministic, wholly synthetic Aurora FAT12 teaching image (no services)."""

import hashlib
import struct
from pathlib import Path


def text(body: str) -> bytes:
    return ("SYNTHETIC FICTION - NOT REAL EVIDENCE\r\n"
            "Times below are source claims in UTC (+00:00), not verified.\r\n"
            + body.replace("\n", "\r\n")).encode("ascii")


SAMPLE = text(
    "Aurora fictional pricing sample; invented customers and amounts.\n"
    "customer,product,credits\n"
    "Cloud Otter,Prism,420\n"
    "Paper Comet,Beacon,735\n"
)
SAMPLE_SHA256 = hashlib.sha256(SAMPLE).hexdigest()
FILES = (
    (b"BRIEF   TXT", text(
        "2026-10-28T08:00:00+00:00 Internal exercise briefing.\n"
        "Analyst Liora Vale reports a suspected pricing-data leak.\n"
        "Review contact prism-drop-47@example.test; identity unverified.\n"
        "Staging, access and delivery are different claims. Seek counterevidence.\n")),
    (b"CHAT    TXT", text(
        "2026-10-28T09:10:00+00:00 Exported fictional text-message transcript.\n"
        "Alias Finch: Prepare SAMPLE.CSV for prism-drop-47@example.test.\n"
        "Alias Wren: Staging only; approval is still pending.\n"
        "No authenticated sender, handset or delivery metadata is supplied.\n")),
    (b"ACCESS  LOG", text(
        "2026-10-28T09:12:00+00:00 Fictional application access log.\n"
        "source_ip=192.0.2.47 action=READ file=SAMPLE.CSV result=OK\n"
        "Local read recorded; this is not an upload or receipt record.\n")),
    (b"USB     TXT", text(
        "2026-10-28T09:14:00+00:00 Fictional device inventory snapshot.\n"
        "USB serial=USB-AURORA-0042 attached_to=DEV-AURORA-07\n"
        "Mount label: rehearsal-media. Attachment does not prove a file copy.\n")),
    (b"DEVICE  TXT", text(
        "2026-10-28T08:50:00+00:00 Fictional asset register.\n"
        "device_id=DEV-AURORA-07; assigned desk=West rehearsal room.\n"
        "No reliable operator attribution or physical acquisition is provided.\n")),
    (b"SAMPLE  CSV", SAMPLE),
    (b"STAGE   TXT", text(
        "2026-10-28T09:16:00+00:00 Fictional staging checklist.\n"
        "File SAMPLE.CSV queued for USB-AURORA-0042.\n"
        "Intended contact: prism-drop-47@example.test\n"
        "State=PREPARED; destination copy and external delivery NOT confirmed.\n")),
    (b"MANIFESTTXT", text(
        "2026-10-28T09:17:00+00:00 Fictional local staging manifest.\n"
        f"filename=SAMPLE.CSV\nsha256={SAMPLE_SHA256}\n"
        "Digest matches the exact sample bytes in this image, including labels/CRLF.\n"
        "A content match identifies bytes, not transmission or an operator.\n")),
    (b"BLOCK   LOG", text(
        "2026-10-28T09:20:00+00:00 Fictional gateway policy log.\n"
        "source_ip=192.0.2.47 target=198.51.100.23:443 action=DENY\n"
        "transfer_id=TX-AURORA-19 bytes_sent=0 reason=approval_missing\n"
        "This record claims this attempt was blocked; it covers no other route.\n")),
    (b"CANCEL  TXT", text(
        "2026-10-28T09:25:00+00:00 Fictional supervisor closure note.\n"
        "transfer_id=TX-AURORA-19 CANCELLED. Approval withheld.\n"
        "Staged material retained locally; no receipt confirmed.\n"
        "Later cancellation qualifies intent, but cannot exclude other attempts.\n")),
    (b"GARDEN  TXT", text(
        "2026-10-28T12:00:00+00:00 Fictional unrelated garden-club note.\n"
        "Water the mint; order compost and three terracotta pots.\n"
        "No pricing, transfer or device identifiers occur in this note.\n")),
)


def build_image() -> bytes:
    """Use Harbor's single-cluster, unpartitioned 1.44 MB FAT12 layout."""
    image = bytearray(1_474_560)
    image[:3] = b"\xeb\x3c\x90"
    image[3:11] = b"IDFADEMO"
    struct.pack_into("<HBHBHHBHHHII", image, 11, 512, 1, 1, 2, 224, 2880,
                     0xF0, 9, 18, 2, 0, 0)
    image[510:512] = b"\x55\xaa"
    fat = bytearray(9 * 512)
    fat[:3] = b"\xf0\xff\xff"
    for i, (name, content) in enumerate(FILES):
        if len(name) != 11 or not 0 < len(content) <= 512:
            raise ValueError("Each FAT 8.3 name needs 11 bytes and one data cluster")
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
        # Fixed FAT metadata: 2026-10-28 00:00, timezone unspecified by FAT.
        # It is a construction marker, never an event timestamp.
        struct.pack_into("<HH", image, entry + 22, 0, (46 << 9) | (10 << 5) | 28)
        struct.pack_into("<H", image, entry + 26, cluster)
        struct.pack_into("<I", image, entry + 28, len(content))
        offset = (33 + i) * 512
        image[offset:offset + len(content)] = content
    image[512:512 + len(fat)] = fat
    image[5120:5120 + len(fat)] = fat
    return bytes(image)


def write_image(path: Path) -> str:
    image = build_image()
    try:
        with path.open("xb") as stream:
            stream.write(image)
    except FileExistsError:
        if path.read_bytes() != image:
            raise FileExistsError(
                f"Refusing to overwrite different existing image: {path}"
            ) from None
        # Identical images are left untouched, including their filesystem mtime.
    return hashlib.sha256(image).hexdigest()


if __name__ == "__main__":
    destination = Path(__file__).with_name("aurora_fiction.img")
    print(f"{destination}\nSHA-256: {write_image(destination)}")
