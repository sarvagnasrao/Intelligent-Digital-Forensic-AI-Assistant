# Aurora: a staged transfer is not a proven leak

**Entirely synthetic fiction. Not real evidence.** All people, aliases, assets,
messages and events are invented. The reserved `example.test` mailbox and
TEST-NET addresses `192.0.2.47` / `198.51.100.23` are documentation identifiers;
do not contact them. No network activity is needed to build or verify this demo.

## Prepare and verify (offline, no live database)

From the project root:

```powershell
.venv\Scripts\python.exe tests\demo_case\aurora_fiction\build_image.py
.venv\Scripts\python.exe -m pytest tests\test_aurora_fiction.py -q
```

`aurora_fiction.img` is a 1,474,560-byte unpartitioned raw FAT12 image, using
Harbor's single-cluster file layout, with 11 readable root files. SHA-256:
`1c9952928f4c7c322b6e21732a7d5ed742cf90e83c347f0f8c995e586faf3310`.
The builder is deterministic, leaves an identical existing image untouched, and
refuses to overwrite different bytes. It does not import the application.
Tests read every file byte-for-byte with pytsk3 and check the bundled image;
the pytsk3 test skips explicitly if that library is absent. This dataset was
generated and all four tests passed with pytsk3 present, without AI, services
or a live database. Harbor is preserved for its existing regressions.

## Five-minute investigator script (optional GUI demonstration)

### Optional service-based case preparation (writes only when explicitly run)

The agent has **not run this importer or modified the live database**. To create
the actual labelled case yourself, keep the GUI closed or in another case
(for example Harbor) until this command completes:

```powershell
.venv\Scripts\python.exe scripts\prepare_aurora_demo.py --create --confirm-gui-not-in-aurora --username admin
```

It prompts for the existing user's password and creates only
`SYNTHETIC-AURORA-DEMO-2026`, refusing an existing case with that identifier.
It never deletes/replaces cases or changes provider configuration. Evidence is
reference-only (keep this image in place). It uses the local worker's examination
HTTP endpoint, persists the **Fast** profile and explicit `llm_enabled=false`
analysis job **before** dispatch, then manually runs deterministic analysis.
It performs no indexing, embeddings or model calls. No GUI switches or services
are started. Failure retains a partially prepared labelled case for inspection;
reruns refuse it rather than deleting/retrying. Only offline tests and `--help`
were exercised, not a live import. Do not open Aurora concurrently: this script
does not control another process's analysis runner or later investigator actions.

Use a **new disposable case**, not a real investigation. GUI examination and
background analysis require the normal application runtime; they are not part
of the offline verification above. Do not expect identical AI/graph output.

1. **0:00–1:00 — Intake.** Register the image as disk-image evidence; examine
   using file traversal and Fast to keep background LLM extraction disabled.
   Verify the effective analysis parameters before dispatch; do not start indexing
   or live AI on the crash-affected laptop. It has no partition table: use filesystem
   scanning at offset zero. Read `BRIEF.TXT`; explain the synthetic banner.
2. **1:00–2:00 — Lead.** Keyword-search `"prism-drop-47@example.test"`.
   Inspect `BRIEF.TXT`, `CHAT.TXT` and `STAGE.TXT`. Ask: “Is this a recipient,
   or only an intended contact named in unauthenticated text?”
3. **2:00–3:00 — Correlate, don't attribute.** Search `"192.0.2.47"` to
   connect local access and the blocked attempt. Search `"USB-AURORA-0042"`
   and `"DEV-AURORA-07"` to connect staging, attachment and inventory.
   Inspect `SAMPLE.CSV` and `MANIFEST.TXT`; compare the sample's computed
   SHA-256 with the manifest, not the whole-image digest above.
4. **3:00–4:00 — Counterevidence.** Read `BLOCK.LOG` and `CANCEL.TXT` in
   that order. Search `"TX-AURORA-19"`. The attempted transfer is described
   as denied with zero bytes sent, then cancelled five minutes later.
5. **4:00–5:00 — Defensible finding.** Inspect the unrelated `GARDEN.TXT`.
   Save a source-cited finding: “Sources describe preparation and local access;
   the recorded attempt was blocked and later cancelled. Successful external
   delivery and operator identity are not established.” An optional AI prompt
   is: “Separate preparation, access, attempted transfer and confirmed delivery;
   cite sources and include later counterevidence.” Verify every assertion.

## Expected source claims

All printed times explicitly claim **UTC (+00:00), 2026-10-28**, and are not
independently verified event times. Each file repeats that warning.

| Source | Claimed time | What the text supports (not independent proof) |
|---|---|---|
| `BRIEF.TXT` | 08:00 | Fictional Liora Vale reports suspected pricing-data leak; names contact. |
| `DEVICE.TXT` | 08:50 | Asset register names `DEV-AURORA-07`; no reliable operator attribution. |
| `CHAT.TXT` | 09:10 | Aliases Finch/Wren discuss preparing `SAMPLE.CSV`; approval pending. |
| `ACCESS.LOG` | 09:12 | Application claims a successful local read from `192.0.2.47`, not upload. |
| `USB.TXT` | 09:14 | Inventory claims `USB-AURORA-0042` attached to the named device; no copy proof. |
| `STAGE.TXT` | 09:16 | Checklist says PREPARED for that USB and intended contact; delivery unconfirmed. |
| `MANIFEST.TXT` | 09:17 | Names `SAMPLE.CSV` and its actual SHA-256; identifies bytes, not transmission. |
| `BLOCK.LOG` | 09:20 | Gateway claims `TX-AURORA-19` to `198.51.100.23:443` denied, bytes_sent=0. |
| `CANCEL.TXT` | 09:25 | Supervisor note claims same transfer cancelled, material retained, no receipt. |
| `SAMPLE.CSV` | No event time | Readable fictional pricing rows; digest covers banner and CRLF too. |
| `GARDEN.TXT` | 12:00 | Unrelated gardening note; no case-specific shared identifiers. |

The intended contact occurs in 3/11 files; source IP, USB serial, device ID
and transfer ID each occur in 2/11. These stay below the default 0.5 hub
fraction (threshold 5 for 11 artifacts). The filename occurs in four files.
Extractor recognition of device/transfer tokens and graph presentation can vary;
exact keyword searches and source bytes are the reliable demonstration route.

## Limits and traps

- Staging and later cancellation are compatible, not a fabricated contradiction.
  Neither proves a completed leak. A denied attempt cannot exclude other routes.
- Plain text “messages”, inventory and logs have no authenticated sender,
  trustworthy clock, real handset, signature, network capture or provenance.
- Matching a SHA-256 identifies sample bytes only. It proves neither a USB copy,
  an external recipient, mailbox control, human identity nor culpability.
- FAT modification dates are fixed construction markers (2026-10-28 00:00,
  timezone unspecified by FAT). Do not substitute them for the printed UTC claims.
  Creation/access metadata is not modeled. This is not a forensic acquisition.
- No real secrets, deleted files, partition recovery, E01, large files, actual
  USB device behavior or live mail are demonstrated. pytsk3 verification is not
  an end-to-end GUI/AI test; synthetic banners may themselves become common hubs.
- The authoritative exact source bytes and computed sample hash are in
  `build_image.py`; there is no separately maintained transcript to drift.
