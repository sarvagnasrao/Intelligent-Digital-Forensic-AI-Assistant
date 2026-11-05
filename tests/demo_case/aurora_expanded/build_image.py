"""Deterministic, wholly synthetic Aurora expanded FAT12 teaching image."""

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
    "Harbor Finch,Signal,118\n"
)
SAMPLE_SHA256 = hashlib.sha256(SAMPLE).hexdigest()

# Shared values the demonstration relies on. Every one lies in 2-6 of the 36
# files, so none reaches the 18-file hub threshold (0.5 of 36) or the minimum
# hub rule of 8. Filenames are capped at 6 because a name is weaker evidence.
STRONG_IDENTIFIERS = (
    b"prism-drop-47@example.test",
    b"aria.quill@example.test",
    b"ops-desk-12@example.test",
    b"ridge.contact@example.test",
    b"+1-202-555-0147",
    b"+1-202-555-0198",
    b"+44-20-7946-0153",
    b"192.0.2.47",
    b"198.51.100.23",
    b"203.0.113.88",
    b"DEV-AURORA-07",
    b"DEV-AURORA-12",
    b"DEV-AURORA-21",
    b"USB-AURORA-0042",
    b"USB-AURORA-0099",
    b"TX-AURORA-19",
    b"TX-AURORA-31",
    b"bc1qsyntheticaurora0000000000000000000000",
)
SHARED_FILENAMES = (b"SAMPLE.CSV", b"LEDGER.CSV", b"MANIFEST.TXT")

FILES = (
    (b"BRIEF   TXT", text(
        "2026-10-28T08:00:00+00:00 Internal exercise briefing.\n"
        "Analyst Liora Vale reports a suspected pricing-data leak.\n"
        "Contact prism-drop-47@example.test (identity unverified).\n"
        "Source host 192.0.2.47; staging file SAMPLE.CSV.\n"
        "Treat every line below as a source assertion only.\n")),
    (b"INTAKE  TXT", text(
        "2026-10-28T08:05:00+00:00 Fictional evidence intake note.\n"
        "Case contact ops-desk-12@example.test; phone +1-202-555-0147.\n"
        "Reference-only register entry; no device was seized.\n"
        "Chain of custody is not modelled in this exercise.\n")),
    (b"DEVICE  TXT", text(
        "2026-10-28T08:50:00+00:00 Fictional asset register extract.\n"
        "device_id=DEV-AURORA-07 assigned to West rehearsal room.\n"
        "No reliable operator attribution is recorded here.\n")),
    (b"CHAT    TXT", text(
        "2026-10-28T09:10:00+00:00 Exported fictional chat transcript.\n"
        "Alias Finch: prepare SAMPLE.CSV for prism-drop-47@example.test.\n"
        "Alias Wren: approval pending; call +1-202-555-0147 first.\n"
        "Handles and numbers are claimed, not authenticated.\n")),
    (b"ACCESS  LOG", text(
        "2026-10-28T09:12:00+00:00 Fictional application access log.\n"
        "source_ip=192.0.2.47 device_id=DEV-AURORA-07 file=SAMPLE.CSV result=OK\n"
        "A local read is not an upload or a receipt record.\n")),
    (b"USB     TXT", text(
        "2026-10-28T09:14:00+00:00 Fictional device inventory snapshot.\n"
        "serial=USB-AURORA-0042 attached_to=DEV-AURORA-07 file=SAMPLE.CSV\n"
        "Attachment does not prove that any file was copied.\n")),
    (b"SAMPLE  CSV", SAMPLE),
    (b"STAGE   TXT", text(
        "2026-10-28T09:16:00+00:00 Fictional staging checklist.\n"
        "SAMPLE.CSV queued for serial=USB-AURORA-0042, transfer_id=TX-AURORA-19.\n"
        "Intended contact: prism-drop-47@example.test\n"
        "State=PREPARED; external delivery NOT confirmed.\n")),
    (b"MANIFESTTXT", text(
        "2026-10-28T09:17:00+00:00 Fictional local staging manifest.\n"
        f"filename=SAMPLE.CSV\nsha256={SAMPLE_SHA256}\n"
        "A digest identifies bytes, not transmission or a person.\n")),
    (b"BLOCK   LOG", text(
        "2026-10-28T09:20:00+00:00 Fictional gateway policy log.\n"
        "source_ip=192.0.2.47 target=198.51.100.23:443 action=DENY\n"
        "transfer_id=TX-AURORA-19 serial=USB-AURORA-0042 bytes_sent=0\n"
        "reason=approval_missing; this record covers one route only.\n")),
    (b"CANCEL  TXT", text(
        "2026-10-28T09:25:00+00:00 Fictional supervisor closure note.\n"
        "transfer_id=TX-AURORA-19 CANCELLED. Approval withheld.\n"
        "prism-drop-47@example.test never acknowledged; MANIFEST.TXT retained.\n"
        "Later cancellation cannot exclude other routes.\n")),
    (b"BEACON  TXT", text(
        "2026-10-28T10:02:00+00:00 Fictional second-staging note.\n"
        "device_id=DEV-AURORA-12 queued serial=USB-AURORA-0099.\n"
        "transfer_id=TX-AURORA-31 created for a rehearsal upload.\n"
        "No recipient, receipt or delivery record is supplied.\n")),
    (b"BEACON2 LOG", text(
        "2026-10-28T10:05:00+00:00 Fictional sync service log.\n"
        "device_id=DEV-AURORA-12 target=198.51.100.23 transfer_id=TX-AURORA-31\n"
        "state=QUEUED bytes_sent=0; queueing is not delivery.\n")),
    (b"SHIP    TXT", text(
        "2026-10-28T10:20:00+00:00 Fictional courier handover note.\n"
        "serial=USB-AURORA-0099 placed in pouch 14; MANIFEST.TXT not included.\n"
        "A move between desks is not an external transfer.\n")),
    (b"HANDOFF TXT", text(
        "2026-10-28T10:40:00+00:00 Fictional shift handover message.\n"
        "serial=USB-AURORA-0099 handed to aria.quill@example.test.\n"
        "Callback number +1-202-555-0198. Courier identity unverified.\n")),
    (b"CONTACT TXT", text(
        "2026-10-28T08:10:00+00:00 Fictional contact directory (invented).\n"
        "prism-drop-47@example.test; aria.quill@example.test\n"
        "ops-desk-12@example.test; ridge.contact@example.test\n"
        "Phones +1-202-555-0147 and +1-202-555-0198.\n"
        "Only reserved example.test identifiers appear here.\n")),
    (b"ROSTER  TXT", text(
        "2026-10-28T08:15:00+00:00 Fictional rehearsal roster.\n"
        "aria.quill@example.test; phone +44-20-7946-0153.\n"
        "Device DEV-AURORA-21 issued for the drill.\n")),
    (b"CALLS   LOG", text(
        "2026-10-28T09:40:00+00:00 Fictional call-detail extract.\n"
        "+1-202-555-0147 to +1-202-555-0198 duration=00:02:14\n"
        "+44-20-7946-0153 dialled once; no audio or recording provided.\n")),
    (b"SMS     TXT", text(
        "2026-10-28T09:45:00+00:00 Fictional text-message extract.\n"
        "From +1-202-555-0198 to +44-20-7946-0153: approval still pending.\n"
        "Copy to ops-desk-12@example.test. Sender not authenticated.\n")),
    (b"WALLET  TXT", text(
        "2026-10-28T11:00:00+00:00 Fictional payment instruction.\n"
        "wallet bc1qsyntheticaurora0000000000000000000000\n"
        "Requested by aria.quill@example.test; a request is not a payment.\n")),
    (b"LEDGER  CSV", text(
        "Fictional LEDGER.CSV excerpt; every row and address is invented.\n"
        "entry,wallet,amount\n"
        "1,bc1qsyntheticaurora0000000000000000000000,42\n"
        "2,reserved,0\n")),
    (b"INVOICE TXT", text(
        "2026-10-28T11:10:00+00:00 Fictional invoice draft.\n"
        "Bill to ridge.contact@example.test for LEDGER.CSV row 1.\n"
        "Payment address bc1qsyntheticaurora0000000000000000000000\n"
        "A draft invoice is not proof of payment.\n")),
    (b"RECEIPT TXT", text(
        "2026-10-28T11:20:00+00:00 Fictional receipt stub.\n"
        "LEDGER.CSV reference 1; node 203.0.113.88.\n"
        "MANIFEST.TXT mention is a label only; no bank record exists.\n")),
    (b"FIREWALLLOG", text(
        "2026-10-28T10:06:00+00:00 Fictional firewall log.\n"
        "203.0.113.88 -> 198.51.100.23:443 transfer_id=TX-AURORA-31 action=QUEUE\n"
        "Queued, not sent; no payload is captured.\n")),
    (b"PROXY   LOG", text(
        "2026-10-28T10:08:00+00:00 Fictional proxy connection log.\n"
        "192.0.2.47 via 203.0.113.88 to example.test:443 bytes=0\n"
        "A connection attempt is not content delivery.\n")),
    (b"DNS     TXT", text(
        "2026-10-28T10:09:00+00:00 Fictional resolver cache extract.\n"
        "203.0.113.88 resolved for mail.example.test; query by ridge.contact@example.test\n"
        "Names and addresses are reserved documentation values.\n")),
    (b"INVENTORCSV", text(
        "device_id=DEV-AURORA-07,serial=USB-AURORA-0042,room=West\n"
        "device_id=DEV-AURORA-12,serial=USB-AURORA-0099,room=East\n"
        "device_id=DEV-AURORA-21,serial=none,room=Store\n")),
    (b"ISSUE   LOG", text(
        "2026-10-28T08:45:00+00:00 Fictional equipment issue log.\n"
        "device_id=DEV-AURORA-21 issued; serial=USB-AURORA-0099 returned.\n"
        "Signatures are not present in this export.\n")),
    (b"FLEET   TXT", text(
        "2026-10-28T08:47:00+00:00 Fictional fleet summary.\n"
        "device_id=DEV-AURORA-21 flagged for a routine battery check.\n"
        "Unrelated to any transfer claim.\n")),
    (b"GARDEN  TXT", text(
        "2026-10-28T12:00:00+00:00 Fictional unrelated garden-club note.\n"
        "Water the mint; order compost and three terracotta pots.\n"
        "No case identifier occurs in this note.\n")),
    (b"LUNCH   TXT", text(
        "2026-10-28T12:30:00+00:00 Fictional canteen menu.\n"
        "Today: lentil soup, cheese rolls, apple crumble.\n"
        "Table four is reserved for the garden club.\n"
        "No case identifier occurs here.\n")),
    (b"WEATHER TXT", text(
        "2026-10-28T07:00:00+00:00 Fictional weather log.\n"
        "Overcast with light rain; no operational meaning.\n")),
    (b"COMMUTE TXT", text(
        "2026-10-28T07:30:00+00:00 Fictional commute note.\n"
        "The bus was delayed by ten minutes; arrival at 07:52.\n")),
    (b"SCHEDULELOG", text(
        "2026-10-28T08:30:00+00:00 Fictional room schedule.\n"
        "09:00 rehearsal, 10:00 review, 11:00 debrief in the West room.\n"
        "A schedule does not place any named person at a device.\n")),
    (b"WITNESS TXT", text(
        "2026-10-28T13:00:00+00:00 Fictional witness statement (conflicting).\n"
        "Alias Heron says the media stayed in the drawer all morning.\n"
        "This contradicts the staging checklist and the USB inventory.\n"
        "One unauthenticated statement resolves nothing.\n")),
    (b"REBUTTALLOG", text(
        "2026-10-28T13:30:00+00:00 Fictional response from the rehearsal lead.\n"
        "The queue and the denial were the drill itself, approved for training.\n"
        "Logs show bytes_sent=0 for both recorded attempts.\n"
        "Any negligence claim still needs the approval record, which is absent.\n")),
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
    destination = Path(__file__).with_name("aurora_expanded.img")
    print(f"{destination}\nSHA-256: {write_image(destination)}")
