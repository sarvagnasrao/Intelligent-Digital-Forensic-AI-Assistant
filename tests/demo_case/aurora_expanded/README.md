# Aurora expanded: a wider network of claims

**Entirely synthetic fiction. Not real evidence.** Every person, alias, device,
message, log line, amount and address is invented. Reserved `example.test`
mailboxes, TEST-NET addresses (`192.0.2.0/24`, `198.51.100.0/24`,
`203.0.113.0/24`) and a deliberately invalid `bc1q…` placeholder are
documentation values; do not contact, resolve or pay them. No network access is
needed to build, verify or demonstrate this dataset.

This is the larger companion to [`../aurora_fiction/`](../aurora_fiction/README.md).
It keeps the same story and trap structure but spreads many identifiers across
36 files so the entity, relationship and timeline views have real material to
reveal. Use the small Aurora sample when you want a five-minute story; use this
one when you want to show correlation.

## Prepare and verify (offline, no live database)

From the project root:

```powershell
.venv\Scripts\python.exe tests\demo_case\aurora_expanded\build_image.py
.venv\Scripts\python.exe -m pytest tests\test_aurora_expanded.py -q
```

`aurora_expanded.img` is a 1,474,560-byte unpartitioned raw FAT12 image using
Harbor's single-cluster layout, with 36 readable root files. SHA-256:

```
3334c87a283ecb44c97bb2405a02a80e36745a79ba3b87506ef36f934d3076bd
```

The builder is deterministic, leaves an identical existing image untouched and
refuses to overwrite different bytes. The tests read every file byte-for-byte
with pytsk3, compare the bundled image to a freshly rebuilt one, and assert the
identifier density stays below the graph hub threshold. The pytsk3 test skips
explicitly if that library is absent.

## What the data is designed to show

36 root files, each at most 512 bytes so the FAT12 single-cluster layout stays
trivial to audit. Every file starts with the synthetic banner and the UTC claim
warning. The identifiers are placed so that each appears in **2–5** of the 36
files — above two (so a pair exists) and well below the default hub ceiling of
`max(8, 0.5 × 36) = 18` (so no identifier is discarded as a hub).

| Identifier | Files | Files (8.3 name) |
|---|---|---|
| `prism-drop-47@example.test` | 5 | BRIEF, CHAT, STAGE, CANCEL, CONTACT |
| `aria.quill@example.test` | 4 | HANDOFF, CONTACT, ROSTER, WALLET |
| `ops-desk-12@example.test` | 3 | INTAKE, CONTACT, SMS |
| `ridge.contact@example.test` | 3 | CONTACT, INVOICE, DNS |
| `+1-202-555-0147` | 4 | INTAKE, CHAT, CONTACT, CALLS |
| `+1-202-555-0198` | 4 | HANDOFF, CONTACT, CALLS, SMS |
| `+44-20-7946-0153` | 3 | ROSTER, CALLS, SMS |
| `192.0.2.47` | 4 | BRIEF, ACCESS, BLOCK, PROXY |
| `198.51.100.23` | 3 | BLOCK, BEACON2, FIREWALL |
| `203.0.113.88` | 4 | RECEIPT, FIREWALL, PROXY, DNS |
| `DEV-AURORA-07` | 4 | DEVICE, ACCESS, USB, INVENTORY |
| `DEV-AURORA-12` | 3 | BEACON, BEACON2, INVENTORY |
| `DEV-AURORA-21` | 4 | ROSTER, INVENTORY, ISSUE, FLEET |
| `USB-AURORA-0042` | 4 | USB, STAGE, BLOCK, INVENTORY |
| `USB-AURORA-0099` | 5 | BEACON, SHIP, HANDOFF, INVENTORY, ISSUE |
| `TX-AURORA-19` | 3 | STAGE, BLOCK, CANCEL |
| `TX-AURORA-31` | 3 | BEACON, BEACON2, FIREWALL |
| `bc1qsyntheticaurora…` | 3 | WALLET, LEDGER, INVOICE |
| `SAMPLE.CSV` (filename) | 6 | BRIEF, CHAT, ACCESS, USB, STAGE, MANIFEST |
| `LEDGER.CSV` (filename) | 3 | LEDGER, INVOICE, RECEIPT |
| `MANIFEST.TXT` (filename) | 3 | CANCEL, SHIP, RECEIPT |

Each strong identifier contributes pairwise links: **92 pair-instances** and
**79 unique file pairs** from strong identifiers alone; adding the shared
filenames gives **113 pair-instances** and **93 unique pairs**. Filtering to what
the IDFA extractors actually recognise leaves about **72 graph-eligible pairs**
across 28 artifacts. `GARDEN.TXT` and `LUNCH.TXT` are deliberate decoys and share
none of these values, so they should stay isolated in the graph.

**Extraction coverage is not the same as the table above.** The deterministic
extractors recognise e-mail, IP, phone, device and USB identifiers, hashes,
paths, timestamps, usernames and wallet-like strings. Whether a given identifier
becomes an entity depends on the extractor's patterns and on the analysis
parameters used (`max_entities_per_artifact`). Always confirm what was actually
extracted in the Entities & Timeline page rather than assuming this table.

## Expected source claims

All printed times claim **UTC (+00:00), 2026-10-28** and are not independently
verified. FAT metadata on the image is a fixed construction marker
(2026-10-28 00:00) and must not be read as an event time.

| Source | Claimed time | What the text supports (not proof) |
|---|---|---|
| `BRIEF.TXT` | 08:00 | Liora Vale reports a suspected pricing-data leak; names contact and source host. |
| `INTAKE.TXT` | 08:05 | Case contact and phone recorded; no device seized. |
| `CONTACT.TXT` | 08:10 | Directory of all four mailboxes and two phones (invented). |
| `ROSTER.TXT` | 08:15 | `aria.quill`, a phone and `DEV-AURORA-21` for a drill. |
| `SCHEDULE.LOG` | 08:30 | Room schedule; does not place anyone at a device. |
| `ISSUE.LOG` | 08:45 | `DEV-AURORA-21` issued, `USB-AURORA-0099` returned; unsigned. |
| `FLEET.TXT` | 08:47 | Routine battery check on `DEV-AURORA-21`; unrelated. |
| `DEVICE.TXT` | 08:50 | Asset register names `DEV-AURORA-07`; no operator attribution. |
| `CHAT.TXT` | 09:10 | Aliases Finch/Wren discuss preparing `SAMPLE.CSV`; approval pending. |
| `ACCESS.LOG` | 09:12 | Application claims a local read from `192.0.2.47`; not an upload. |
| `USB.TXT` | 09:14 | `USB-AURORA-0042` attached to `DEV-AURORA-07`; no copy proof. |
| `STAGE.TXT` | 09:16 | Checklist marks `SAMPLE.CSV` PREPARED; delivery unconfirmed. |
| `MANIFEST.TXT` | 09:17 | Names `SAMPLE.CSV` and its actual SHA-256; identifies bytes only. |
| `BLOCK.LOG` | 09:20 | Gateway denies `TX-AURORA-19` to `198.51.100.23:443`, `bytes_sent=0`. |
| `CANCEL.TXT` | 09:25 | Supervisor cancels `TX-AURORA-19`; no acknowledgement. |
| `CALLS.LOG` | 09:40 | Call-detail extract between two numbers; no audio. |
| `SMS.TXT` | 09:45 | Message extract; sender not authenticated. |
| `BEACON.TXT` | 10:02 | Second staging: `DEV-AURORA-12`, `USB-AURORA-0099`, `TX-AURORA-31`. |
| `BEACON2.LOG` | 10:05 | Sync log queues `TX-AURORA-31`; `bytes_sent=0`. |
| `FIREWALL.LOG` | 10:06 | Queue action from `203.0.113.88`; queued, not sent. |
| `PROXY.LOG` | 10:08 | Connection attempt via `203.0.113.88`; zero bytes. |
| `DNS.TXT` | 10:09 | Resolver cache entry for a reserved name. |
| `SHIP.TXT` | 10:20 | `USB-AURORA-0099` moved between desks; not an external transfer. |
| `HANDOFF.TXT` | 10:40 | Handover to `aria.quill`; courier identity unverified. |
| `WALLET.TXT` | 11:00 | Payment **request** naming a placeholder wallet; not a payment. |
| `INVOICE.TXT` | 11:10 | Draft invoice for LEDGER row 1; not proof of payment. |
| `RECEIPT.TXT` | 11:20 | Receipt stub labelling a ledger row; no bank record. |
| `WITNESS.TXT` | 13:00 | Conflicting witness statement; resolves nothing alone. |
| `REBUTTAL.LOG` | 13:30 | Rehearsal lead says the queue and denial were the drill. |
| `SAMPLE.CSV` | none | Pricing rows, invented customers and amounts. |
| `LEDGER.CSV` | none | Invented ledger rows naming the placeholder wallet. |
| `INVENTORY.CSV` | none | Three devices and their serials. |
| `GARDEN.TXT` | 12:00 | Unrelated gardening note; no shared identifier. |
| `LUNCH.TXT` | 12:30 | Canteen menu; no shared identifier. |
| `WEATHER.TXT` | 07:00 | Weather log; no operational meaning. |
| `COMMUTE.TXT` | 07:30 | Commute note; no operational meaning. |

## Five-minute investigator script

Use a disposable case, not a real investigation. The GUI and background
analysis need the normal application runtime; the offline verification above
does not.

1. **0:00–1:00 — Intake.** Register the image as disk-image evidence and examine
   with **Fast**. Confirm `llm_enabled=false` before dispatch. There is no
   partition table, so scan the filesystem at offset zero. Read `BRIEF.TXT` and
   point out the synthetic banner.
2. **1:00–2:00 — Lead.** Keyword-search `prism-drop-47@example.test`, then
   `192.0.2.47`. Note every hit is unauthenticated text, not a mail or network
   capture.
3. **2:00–3:00 — Correlate.** Search `USB-AURORA-0042`, `DEV-AURORA-07` and
   `TX-AURORA-19`, then open **Entities & Timeline**. Show that the same values
   repeat across independent-looking files and that the graph groups them.
4. **3:00–4:00 — Counterevidence.** Read `BLOCK.LOG`, `CANCEL.TXT`,
   `WITNESS.TXT` and `REBUTTAL.LOG`. Search `TX-AURORA-31` and note the second
   attempt is also `bytes_sent=0`.
5. **4:00–5:00 — Defensible finding.** Show that `GARDEN.TXT` and `LUNCH.TXT`
   do not join the graph. Save a source-cited finding: “Sources describe
   preparation, local access and two blocked or queued attempts. Successful
   external delivery and operator identity are not established.”

## Relationship and timeline expectations

- **Entities** come from deterministic extraction (no model). Expect many
  e-mail, phone, IP, device/serial, hash, path and timestamp rows. Exact counts
  depend on extractor patterns and on `max_entities_per_artifact`.
- **Relationships** are rebuilt from shared rare identifiers and identical
  bytes. This dataset is designed so that each strong identifier stays under the
  hub ceiling, which is what allows real `shared_entity` and
  `related_artifacts` edges to survive.
- **Timeline** events are built from FAT file metadata (`file_created`,
  `file_modified`, `file_accessed`) only. The UTC times printed inside the files
  are *source claims* and are not promoted to events by the deterministic
  pipeline. Do not present the image's fixed metadata timestamp as a real event.

## Limits and traps

- Two staging attempts, one cancellation and one contradictory witness statement
  are all compatible with the story. None proves a completed leak, and a blocked
  attempt cannot exclude another route.
- Plain-text "messages", inventory and logs have no authenticated sender,
  trustworthy clock, real handset, signature or network capture.
- A matching SHA-256 identifies sample bytes only. It proves no USB copy, no
  external recipient, no mailbox control and no culpability.
- FAT metadata is a construction marker. This is not a forensic acquisition.
- No real secrets, deleted-file recovery, partitions, E01, large files, actual
  USB behaviour or live mail are demonstrated.
- The authoritative source bytes and the computed sample hash live in
  `build_image.py`; there is no separately maintained transcript to drift.
