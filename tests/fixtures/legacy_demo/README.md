# Legacy synthetic regression fixture

Retained for regression tests, not the current exhibition case. The current
exhibition sample is documented in `tests/demo_case/README.md`.

All names, content and addresses are fictional. The `.test` address is reserved
for testing; the image is not real evidence. The image is a small, unpartitioned
1.44 MB FAT12 filesystem, not an E01 or a physical disk.

## Prepare and investigate

1. From the project root, run `.venv\Scripts\python.exe tests\fixtures\legacy_demo\build_image.py`.
   This creates `tests\fixtures\legacy_demo\synthetic_demo.img` deterministically. It refuses
   to overwrite a different file at that path. Keep the generated image unchanged;
   record its printed SHA-256 at intake if desired.
2. Start IDFA and its worker, create a disposable case, and register the image
   as evidence. Run a file traversal examination using the Balanced preset. Wait
   for it to finish and for background analysis to complete.
3. In Artifacts & Search, search for `"sable-courier-47@example.test"` (keyword
   search). Inspect the matching source text and the unrelated `LUNCH.TXT`.
4. In Entities & Timeline, inspect the extracted email and any related-artifact
   relationship. Review both source artifacts before recording a finding.

## Expected answers

* `MESSAGE.TXT` says to contact `sable-courier-47@example.test` about a transfer.
* `RECEIPT.TXT` says to reply to the same address for confirmation.
* `LUNCH.TXT` is an unrelated inventory and does not contain that address.
* The exact quoted search should return the first two files, not `LUNCH.TXT`.
  The shared address supports a lead linking the files; it does **not** establish
  who controls the mailbox, that a real transfer occurred, or culpability.
* A related-artifact link may be shown after analysis; inspect its evidence rather
  than assuming a graph edge is proof. AI-generated descriptions are unverified.

The raw filesystem may also expose filesystem metadata entries, so the three
named files need not be the only entries listed. No network service or model is
needed to build the image; examination requires the native worker and pytsk3.
