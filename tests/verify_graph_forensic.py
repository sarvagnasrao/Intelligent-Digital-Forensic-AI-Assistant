"""
Registry-hive routing (A7) and bounded/streamed entry hashing (A9) in
backend/modules/forensic_ingestion.py.

A7: ``is_supported_file`` admits registry hives (SYSTEM, SOFTWARE, SAM, ...) by
    name on the in-image walk, but ``extract_text_from_bytes`` had no registry
    branch, so every hive fell through to the content sniffer and was reported
    ``unsupported`` - the format was accepted and then never extracted.

A9: ``extract_file_content`` read a whole TSK directory entry into RAM in one
    ``entry.read_random(0, size)`` call and only then hashed it. The hash is
    now streamed over bounded reads.

Pure: temp dirs, fake TSK entries, no DB, no network, no real disk image. Run:
    PYTHONPATH=. python tests/verify_graph_forensic.py
"""

import atexit
import hashlib
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

from backend.modules import forensic_ingestion as fi

PASS, FAIL = 0, 0
FAILED = []


def check(label, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"PASS  {label}")
    else:
        FAIL += 1
        FAILED.append(label)
        print(f"FAIL  {label}  -- {detail}")


TMP = tempfile.mkdtemp(prefix="idfa_graph_forensic_")
atexit.register(shutil.rmtree, TMP, True)


class _FakeEntry:
    """A stand-in for a pytsk3 directory entry.

    Records every ``read_random`` request so the suite can assert the read was
    *streamed* (several bounded calls) rather than one whole-entry call.
    """

    def __init__(self, data):
        self.data = data
        self.requests = []

    def read_random(self, offset, length):
        self.requests.append((offset, length))
        return self.data[offset:offset + length]


# ── A7: registry hives reach a real extractor ────────────────────────────────

for name in ("SYSTEM", "SOFTWARE", "SAM", "SECURITY", "NTUSER.DAT",
             "UsrClass.dat"):
    result = fi.extract_text_from_bytes(b"\x00" * 128, name, TMP)
    check(f"{name:14} extracts as a registry hive",
          isinstance(result, tuple) and len(result) == 3
          and result[1] == "registry",
          f"got {result[1] if isinstance(result, tuple) else result!r}")
    check(f"{name:14} yields a truthy summary mentioning Registry",
          isinstance(result, tuple) and bool((result[0] or "").strip())
          and "registry" in (result[0] or "").lower(),
          f"got {(result[0] if isinstance(result, tuple) else '')!r}")

# An ordinary extensionless file must NOT be mistaken for a hive.
_r = fi.extract_text_from_bytes(b"\x00" * 128, "noextension", TMP)
check("an unknown extensionless file is still not a registry hive",
      _r[1] != "registry", f"got {_r[1]!r}")

# extract_file_content routes a hive the same way.
entry = _FakeEntry(b"\x00" * 128)
enriched = fi.extract_file_content({
    "filename": "SYSTEM", "internal_path": "/Windows/System32/config/SYSTEM",
    "size": 128, "modified": "x", "accessed": "x",
    "created": "x", "born": "x", "entry": entry, "is_deleted": False,
}, TMP)
check("extract_file_content reports a hive as extraction_type=registry",
      enriched.get("extraction_type") == "registry",
      f"got {enriched.get('extraction_type')!r}")

# ── A9: the entry hash is streamed over bounded reads ────────────────────────

hasher = getattr(fi, "hash_entry_sha256", None)
check("hash_entry_sha256 exists", callable(hasher),
      "no streaming hash helper on forensic_ingestion")

if callable(hasher):
    payload = (b"abc123" * 400_000)          # ~2.4 MB, > one 1 MB chunk
    entry = _FakeEntry(payload)
    digest, read_back = hasher(entry, len(payload))
    check("the streamed digest matches sha256 of the whole entry",
          digest == hashlib.sha256(payload).hexdigest(),
          f"got {digest!r}")
    check("  and the bytes are returned intact",
          read_back == payload, f"got {len(read_back)} bytes")
    check("  the read is streamed in more than one request",
          len(entry.requests) > 1, f"{len(entry.requests)} request(s)")
    check("  no request exceeds the chunk size",
          all(length <= fi._HASH_CHUNK for _, length in entry.requests),
          f"max {max((l for _, l in entry.requests), default=0)}")

    # An explicit small chunk size proves the bound is the parameter, not luck.
    entry = _FakeEntry(payload)
    hasher(entry, len(payload), chunk_size=64 * 1024)
    check("a caller-chosen chunk size is honoured",
          all(length <= 64 * 1024 for _, length in entry.requests)
          and len(entry.requests) > 1,
          f"{len(entry.requests)} requests")

    # Offsets must advance monotonically across the whole entry.
    entry = _FakeEntry(payload)
    hasher(entry, len(payload))
    offsets = [o for o, _ in entry.requests]
    check("the streamed reads advance without gaps or overlap",
          offsets == sorted(offsets) and len(set(offsets)) == len(offsets)
          and offsets[0] == 0,
          f"offsets {offsets[:4]}...")

# extract_file_content must use the streamed hash, not hash a monolithic read.
entry = _FakeEntry(b"hello world\n")
enriched = fi.extract_file_content({
    "filename": "notes.txt", "internal_path": "/notes.txt",
    "size": len(b"hello world\n"), "modified": "x", "accessed": "x",
    "created": "x", "born": "x", "entry": entry, "is_deleted": False,
}, TMP)
check("extract_file_content hashes the entry it read",
      enriched.get("sha256_hash")
      == hashlib.sha256(b"hello world\n").hexdigest(),
      f"got {enriched.get('sha256_hash')!r}")
check("extract_file_content still extracts the text",
      "hello world" in (enriched.get("extracted_text") or ""),
      f"got {enriched.get('extracted_text')!r}")

print("\n" + "=" * 66)
for label in FAILED:
    print(f"  FAILED: {label}")
print(f"PASSED: {PASS}    FAILED: {FAIL}")
print("=" * 66)

sys.exit(1 if FAIL else 0)
