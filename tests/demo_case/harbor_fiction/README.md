# Fictional Harbor investigation

Retained Harbor demonstration and regression fixture. See `tests/demo_case/` for
the newer Aurora exhibition sample.

Everything here is invented, including names, events and the reserved `.test`
address. This is a teaching scenario, not real evidence. It contains no actual
mail, sender metadata, or proof of a real transaction.

## Evidence and preparation

`harbor_fiction.img` is a 1,474,560-byte raw, unpartitioned FAT12 filesystem.
Its SHA-256 is `1eb86b58edfc966c49dce4637daa659e990a351d4f016e09a5abaee50ee2da8e`.
To rebuild it, run `.venv\Scripts\python.exe tests\demo_case\harbor_fiction\build_image.py`
from the project root. The builder refuses to overwrite a different image at
that path. The image was opened with pytsk3 and all four files and their bytes
were read successfully. No actual IDFA database was accessed in preparation.

For a demonstration, register the image in a **disposable** case as disk image
evidence; examine with file traversal and the Balanced preset. Wait for the
examination and background analysis. Search the exact quoted address in keyword
mode, inspect both sources, then examine `STATUS.TXT` and `GARDEN.TXT`. The
filesystem may expose additional metadata entries. The graph or AI may vary;
verify any result against the files rather than assuming it will be generated.

## Exact source content

The four root files use CRLF line endings and contain the following text:

`NOTE.TXT`:
```text
2026-10-29 09:15
Mira: use lantern-bridge-73@example.test to request the Harbor package.
```
`REPLY.TXT`:
```text
2026-10-29 10:40
To: lantern-bridge-73@example.test
The Harbor package is ready for collection. Signed: Rowan.
```
`STATUS.TXT`:
```text
2026-10-30 08:00
Harbor package status: collection cancelled; package remains in storage.
```
`GARDEN.TXT`:
```text
2026-10-30 12:00
Garden club list: mint, beans, and watering cans.
```

## Questions and expected answers

1. **What connects the request and the reply?** Both `NOTE.TXT` and
   `REPLY.TXT` contain `lantern-bridge-73@example.test` and refer to a Harbor
   package. This is a source-backed investigative lead, not evidence that Mira
   or Rowan owns or controls the mailbox. An exact-address search should find
   these two files, not the other two.
2. **Was the package collected?** The reply says it was ready, not collected.
   The later `STATUS.TXT` says collection was cancelled and it remained in
   storage. These statements can both be true; the status is a counterpoint to
   an unsupported assumption that collection occurred, not a direct contradiction.
3. **Which item is unrelated?** `GARDEN.TXT` describes gardening supplies; it
   has no shared address or stated Harbor connection.
4. **Who sent a real email, and when?** The image contains plain text notes,
   not authenticated emails. The printed timestamps have no timezone and are
   claims within the files, not independently verified event times. Identity,
   ownership, delivery and culpability cannot be established from this dataset.

This image does not demonstrate deleted-file recovery, partitions, E01, or
actual physical-device provenance. Search, analysis, and UI behavior depend on
the installed application and services; pytsk3 verification alone is not an
end-to-end GUI test.
