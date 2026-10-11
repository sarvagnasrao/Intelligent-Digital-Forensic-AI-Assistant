"""
Split disk-image sets: routing, segment discovery, incomplete-set reporting and
custody hashing.

The defect this guards
----------------------
Commit `7c161fc` ("Make split disk-image sets ingestable end to end") taught the
*upload gate* to accept continuation segments (`SCHARDT.002`, `case.E02`) so a
whole set could be submitted. But the *pipeline dispatch* still decided with its
own copy of the bare extension set:

    is_disk_image = ext in FORENSIC_IMAGE_EXTENSIONS   # ingestion.py

`FORENSIC_IMAGE_EXTENSIONS` is `{.e01, .001, .dd, .raw, .img}` only. So
`SCHARDT.002` passed the gate, then `.002` was not in the set, so it went to the
**document** pipeline, was sniffed as binary, yielded no text, and the evidence
was marked **Indexed with 0 chunks** -- the silent-success shape this repo keeps
chasing, in the one place where the file was a piece of a disk image. The shared
policy function `is_forensic_image()` already knows continuation segments are
disk images; the dispatcher just was not calling it.

Three more things about split sets are checked here, and each was a separate
way the pipeline could lie about a multi-segment acquisition:

  B. the segments of a set are discovered in order, and a hole in the middle is
     distinguished from the end of the set;
  C. an incomplete set is reported as *missing segments to upload*, not as a
     *truncated acquisition to re-acquire* -- different finding, different
     remedy, and the old code reached for the wrong one whenever the set had
     more than one contiguous segment before the gap;
  D. the custody hash (`evidence.sha256_hash`) is the digest of the whole set,
     because that column is chain of custody. Verification must re-hash the same
     bytes; the walk must not overwrite it with a first-segment hash.

Everything here is pure: temp files only, no database, no network, no Qdrant.

Run: PYTHONPATH=. python tests/verify_split_images.py
"""

import atexit
import hashlib
import os
import shutil
import struct
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

from backend.modules import file_formats
from backend.modules.file_formats import (
    FORENSIC_IMAGE_EXTENSIONS,
    is_forensic_image,
    normalize_extension,
)
from backend.modules import forensic_ingestion as fi

# The dispatcher. Imported defensively so that, before the fix lands, this
# suite reports a clean FAIL rather than dying with a traceback the gate would
# have to call "unreadable".
try:
    from backend.ingestion import route_for_filename
except Exception:                                   # noqa: BLE001
    route_for_filename = None

try:
    from backend.routers.evidence import hash_evidence_set
except Exception:                                   # noqa: BLE001
    hash_evidence_set = None


PASS, FAIL = 0, 0
FAILED = []


def check(label, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"PASS  {label}")
    else:
        FAIL += 1
        FAILED.append(f"{label}  {detail}".rstrip())
        print(f"FAIL  {label}  {detail}")


def section(title):
    print(f"\n=== {title} ===")


TMP = tempfile.mkdtemp(prefix="cfi_split_")
atexit.register(shutil.rmtree, TMP, True)

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def build_set(name, segments, size=200 * 1024):
    """Writes NAME.001..len(segments) as real files; returns (dir, [paths]).

    ``segments`` is an iterable of ints -- the segment numbers to actually
    create -- so a hole can be made by omitting one.
    """
    d = os.path.join(TMP, name)
    os.makedirs(d, exist_ok=True)
    paths = []
    for n in segments:
        p = os.path.join(d, f"{name}.{n:03d}")
        with open(p, "wb") as fh:
            fh.write(bytes([n & 0xFF]) * size)
        paths.append(p)
    return d, paths


def write_mbr(path, sectors, partition_type=0x07, start_lba=63):
    """Writes a 512-byte MBR with one partition entry at ``start_lba``."""
    mbr = bytearray(512)
    e = 446
    mbr[e + 4] = partition_type
    mbr[e + 8:e + 12] = struct.pack("<I", start_lba)
    mbr[e + 12:e + 16] = struct.pack("<I", sectors)
    mbr[510] = 0x55
    mbr[511] = 0xAA
    with open(path, "r+b") as fh:
        fh.seek(0)
        fh.write(mbr)


# ---------------------------------------------------------------------------
# A. dispatch parity -- the gate and the pipeline must agree
# ---------------------------------------------------------------------------

section("A. pipeline dispatch uses the shared format policy")

if route_for_filename is None:
    check("ingestion exposes a single routing predicate "
          "(route_for_filename)", False,
          "not found -- dispatch still tests the bare extension set")
else:
    check("a continuation segment routes to the forensic pipeline",
          route_for_filename("SCHARDT.002") == "forensic",
          f"got {route_for_filename('SCHARDT.002')!r}")
    check("  and so does a later one",
          route_for_filename("SCHARDT.008") == "forensic")
    check("  EWF continuations too",
          route_for_filename("case.E02") == "forensic")
    check("first segments still route forensic",
          route_for_filename("SCHARDT.001") == "forensic"
          and route_for_filename("case.E01") == "forensic")

    for name in ("server.log", "notes.txt", "evidence.csv",
                 "report.pdf", "dump.sql", "app.log.12"):
        check(f"{name:14} routes to the document pipeline",
              route_for_filename(name) == "document",
              f"got {route_for_filename(name)!r}")

    # The rule the dispatcher must obey, stated directly: it is forensic iff
    # the shared policy says the file is a disk image. Nothing else.
    probe_names = [
        "SCHARDT.001", "SCHARDT.002", "SCHARDT.008",
        "case.E01", "case.E02", "case.E99",
        "disk.dd", "disk.raw", "disk.img", "disk.001",
        "a.log", "a.log.12", "a.txt", "a.pdf", "a.csv",
        "a.zip", "noextension", ".env", "x.100",
    ]
    for n in probe_names:
        want = "forensic" if is_forensic_image(n) else "document"
        got = route_for_filename(n)
        check(f"{n:14} -> {want:8} (agrees with is_forensic_image)",
              got == want, f"got {got!r}")

    # The bug, asserted as a fact about the format policy: these names are disk
    # images by the policy but are absent from the bare extension set the old
    # dispatcher used. If this set is ever empty the two checks above stop
    # distinguishing the fix from the bug.
    misrouted = [n for n in probe_names
                 if is_forensic_image(n)
                 and normalize_extension(n) not in FORENSIC_IMAGE_EXTENSIONS]
    check("the bare-extension test would misroute continuation segments",
          misrouted, f"expected non-empty, got {misrouted}")


# ---------------------------------------------------------------------------
# B. segment discovery and ordering
# ---------------------------------------------------------------------------

section("B. segment discovery, ordering and holes")

_d, complete = build_set("COMPLETE", range(1, 6))
segs = fi.image_segment_paths(complete[0])
check("a full set resolves to every segment in order",
      [os.path.basename(s) for s in segs]
      == [f"COMPLETE.{n:03d}" for n in range(1, 6)],
      f"got {[os.path.basename(s) for s in segs]}")
check("  and reports no missing segments",
      fi.missing_image_segments(complete[0]) == [],
      f"got {fi.missing_image_segments(complete[0])}")

_d, lone = build_set("LONE", [1])
check("a lone .001 resolves to itself",
      fi.image_segment_paths(lone[0]) == [lone[0]])
check("  and reports no successors to be missing (it cannot know)",
      fi.missing_image_segments(lone[0]) == [])

_d, holed = build_set("HOLED", [1, 2, 4])
hsegs = fi.image_segment_paths(holed[0])
check("discovery stops at the first gap",
      [os.path.basename(s) for s in hsegs] == ["HOLED.001", "HOLED.002"],
      f"got {[os.path.basename(s) for s in hsegs]}")
check("the hole is named, not assumed to be the end of the set",
      fi.missing_image_segments(holed[0]) == [".003"],
      f"got {fi.missing_image_segments(holed[0])}")

# A rotated log must never be read as a segment set.
log_dir = os.path.join(TMP, "logs")
os.makedirs(log_dir, exist_ok=True)
logp = os.path.join(log_dir, "app.log")
with open(logp, "wb") as fh:
    fh.write(b"2026-01-01 started\n")
check("a plain file is its own single 'segment'",
      fi.image_segment_paths(logp) == [logp])


# ---------------------------------------------------------------------------
# C. an incomplete set is reported as missing segments, not as truncation
# ---------------------------------------------------------------------------

section("C. incomplete sets name the missing segments")

# .001/.002 present, .003 missing, .004 present -- the shape where the old
# `len(segments) == 1` guard suppressed the actionable message.
_d, holed = build_set("PARTIAL", [1, 2, 4], size=200 * 1024)
# Declare a volume far larger than the contiguous prefix, so the image is
# genuinely short of bytes (the `bad` path) AND has a reportable hole.
write_mbr(holed[0], sectors=2000)          # 2000 * 512 = 1 MB > 400 KB present

info = fi.inspect_raw_image(holed[0])
check("an image with an interior hole is reported incomplete",
      info.get("missing_segments") == [".003"],
      f"missing={info.get('missing_segments')!r}")
check("  the missing segment is named in the summary",
      ".003" in (info.get("summary") or ""),
      f"summary={info.get('summary')!r}")
check("  the remedy is 'upload the missing segment', not 're-acquire'",
      "re-acquire" not in (info.get("summary") or "").lower(),
      f"summary={info.get('summary')!r}")

# A complete set whose partition fits must read as OK, and say it was split.
_d, full = build_set("WHOLE", range(1, 5), size=200 * 1024)   # 800 KB
write_mbr(full[0], sectors=1000)           # declares 512 KB < 800 KB present
whole = fi.inspect_raw_image(full[0])
check("a complete set is not reported as incomplete",
      whole.get("missing_segments") == [],
      f"got {whole.get('missing_segments')!r}")
check("  and its summary is not a truncation warning",
      whole.get("truncated") is False,
      f"truncated={whole.get('truncated')!r} summary={whole.get('summary')!r}")
check("  and it says how many segments it spans",
      "4 split segments" in (whole.get("summary") or ""),
      f"summary={whole.get('summary')!r}")


# ---------------------------------------------------------------------------
# D. the custody hash covers the whole set
# ---------------------------------------------------------------------------

section("D. custody hashing follows the whole set")

_d, dset = build_set("DIGEST", range(1, 4), size=64 * 1024)
expected = hashlib.sha256()
for p in dset:
    with open(p, "rb") as fh:
        expected.update(fh.read())
expected_hex = expected.hexdigest()

first_only = hashlib.sha256()
with open(dset[0], "rb") as fh:
    first_only.update(fh.read())
first_hex = first_only.hexdigest()

check("the three segments hash differently from the first alone",
      expected_hex != first_hex)

if hash_evidence_set is None:
    check("evidence exposes whole-set hashing (hash_evidence_set)", False,
          "not found -- /verify still hashes only the first segment")
else:
    got = hash_evidence_set(dset[0])
    check("hashing the evidence reproduces the upload-time digest",
          got == expected_hex, f"got {got[:16]}... wanted {expected_hex[:16]}...")
    check("  it is not the first-segment digest",
          got != first_hex)
    # A non-split file is its own set, and must still hash as one file.
    plain = os.path.join(TMP, "plain.txt")
    with open(plain, "wb") as fh:
        fh.write(b"plain evidence body\n")
    check("an unsplit file hashes as itself",
          hash_evidence_set(plain)
          == hashlib.sha256(b"plain evidence body\n").hexdigest())


# The walk must not rewrite the custody hash. A source scan, like the arity
# scan in verify_file_formats: the rule is a single statement, and stating it as
# a regex is clearer than any behavioural proxy that needs a disk image.
_ing = os.path.join(REPO, "backend", "ingestion.py")
with open(_ing, encoding="utf-8") as fh:
    src = fh.read()
import re as _re
clobber = _re.search(r"^\s*evidence\.sha256_hash\s*=\s*\w+\s*$", src, _re.M)
check("the forensic walk does not overwrite the custody hash",
      clobber is None,
      f"line still present: {clobber.group(0).strip() if clobber else ''}")


print("\n" + "=" * 66)
for label in FAILED:
    print(f"  FAILED: {label}")
print(f"PASSED: {PASS}    FAILED: {FAIL}")
print("=" * 66)

sys.exit(1 if FAIL else 0)
