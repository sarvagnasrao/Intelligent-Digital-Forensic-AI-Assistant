"""
Evidence file-format support: the gate, the extractors, and the agreement
between them.

The defect this guards: the upload gate in backend/routers/evidence.py was a
hand-maintained 31-entry list, and it was NARROWER than what the extraction
cascade could already read. Twenty formats were refused with a 400 that the
pipeline would have handled perfectly well end to end - including .log, .csv,
.json and .xml, which are the first four anyone asks for when they say "the
ingestion won't take my log files". The same list had been copied a second
time into the frontend's file input, so the picker and the server had drifted
apart too.

Three things are checked here, and the third is the one that matters:

  A. the formats an investigator actually brings now pass the gate;
  B. each one really produces text (a format that uploads and then yields
     nothing is the silent-success defect this repo keeps chasing, one
     layer earlier than the ones already fixed);
  C. the gate, the extractors and the API's advertised list cannot disagree.

Pure: no network, no database, no uploads. Run:

    PYTHONPATH=. python tests/verify_file_formats.py
"""

import sys
import atexit
import shutil
import os
import plistlib
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

from backend.modules import file_formats
from backend.modules import forensic_ingestion as fi
from backend.modules.file_formats import (
    UPLOAD_EXTENSIONS,
    accept_string,
    category_for,
    is_forensic_image,
    is_supported_upload,
    normalize_extension,
    orphan_extractables,
    unsupported_uploads,
)
from backend.modules.file_store import get_mime_type, is_browser_viewable
from backend.modules.text_parser import decode_text_bytes
from backend.routers.evidence import ALLOWED_EXTENSIONS

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


TMP = tempfile.mkdtemp(prefix="cfi_formats_")
# Registered rather than cleaned at the bottom of the file: a crash anywhere in
# the suite would otherwise leak the extraction scratch directory. That is not
# hypothetical - a bad footer line here did exactly that, and the leaked
# directories then silently accumulated in the system temp dir.
atexit.register(shutil.rmtree, TMP, True)


def extract(name, data, **kw):
    """Runs the real extraction cascade; returns (text, extraction_type).

    Asserts the 3-tuple contract rather than tolerating a 2-tuple. It used to
    have an `if len(result) == 3` / else pair whose two branches were
    identical, so a branch returning 2 values passed this suite silently - and
    `backend/ingestion.py` unpacked exactly 2, so every plain-text upload
    raised `ValueError: too many values to unpack (expected 2)`. A test helper
    that accepts both shapes will not catch a shape mismatch; that is the whole
    point of the contract.
    """
    result = fi.extract_text_from_bytes(data, name, TMP, **kw)
    if len(result) != 3:
        raise AssertionError(
            f"extract_text_from_bytes({name!r}) returned {len(result)} "
            f"values, expected 3: {result!r}")
    return result[0], result[1]


# ── A. the four that started this ────────────────────────────────────────────
# Regression-first: these are the exact extensions reported as rejected, and
# they are asserted individually so a future trim cannot quietly drop one.

section("A. the reported formats are accepted")
for name in ("server.log", "evidence.csv", "case.json",
             "system.xml", "notes.md", "page.html",
             "dump.sql", "conf.yaml", "run.sh",
             "interview.srt", "browser.sqlite", "Info.plist",
             "memo.rtf", "anim.gif", "clip.webm",
             "app.log.1", ".env"):
    ext = normalize_extension(name)
    check(f"{name:16} -> {ext or '(none)':14} accepted",
          is_supported_upload(name))

check("the reported four are all in the gate",
      {'.log', '.csv', '.json', '.xml'} <= UPLOAD_EXTENSIONS)
check("all four extract",
      all(extract(f"x{normalize_extension(n)}", b"a,b\n1,2\n")[0]
          for n in ("a.log", "a.csv", "a.json", "a.xml")))

section("B. the gate still refuses what it should")
for name in ("malware.exe", "archive.zip", "disk.iso", "bundle.dmg",
             "library.so", "driver.sys", "photo.psd", "noextension",
             "payload.7z", "script.bin"):
    check(f"{name:16} refused", not is_supported_upload(name))

check("a name with a path is classified on its basename",
      is_supported_upload("/var/log/nginx/access.log"))
check("  a Windows path too",
      is_supported_upload(r"C:\Windows\System32\winevt\Logs\Security.evtx"
                          .replace(".evtx", ".log")))

# ── B. the normaliser ────────────────────────────────────────────────────────

section("C. extension normalisation")
cases = [
    ("app.log.1", ".log", "a rotated log is still a log"),
    ("app.log.12", ".log", "a two-digit rotation marker"),
    ("nginx.access.log.3", ".log", "rotation on a multi-dot name"),
    (".env", ".env", "a dotfile has no extension at all"),
    (".bash_history", ".bash_history", "another dotfile"),
    ("Report.PDF", ".pdf", "case is folded"),
    ("archive.tar", ".tar", "an unlisted type keeps its own extension"),
    ("noext", "", "an extensionless file classifies as nothing"),
    ("", "", "an empty name is not a format"),
    ("data.ddb", ".ddb", "a double extension is not peeled unless numeric"),
]
for name, expected, why in cases:
    got = normalize_extension(name)
    check(f"{name or '(empty)':20} -> {got or '(none)':14} {why}",
          got == expected, f"got {got!r}, wanted {expected!r}")

# Bounded: a name made of nothing but numeric segments must terminate at the
# loop's limit rather than walking off the end. The result staying a rotation
# suffix is the proof that the bound - not the string's end - stopped it.
deep_numeric = normalize_extension("a.1.2.3.4.5.6.7.8")
check("an all-numeric name terminates at the bound",
      deep_numeric in {f".{i}" for i in range(0, 30)},
      f"got {deep_numeric!r}")

# ── C. encodings ─────────────────────────────────────────────────────────────
# A UTF-16 log does not raise when read as UTF-8 with errors ignored - it
# returns mostly NULs. The file then ingests, completes, gets marked Indexed,
# and nothing useful is in the index. That is the silent-success shape, so
# the decoder has to be right rather than merely non-crashing.

section("D. encoding detection")
utf16_text = "2026-09-28 ERROR login failed for admin from 10.0.0.9"

t, enc = decode_text_bytes(b"\xff\xfe" + utf16_text.encode("utf-16-le"))
check("UTF-16LE with a BOM round-trips", t == utf16_text, f"got {t!r}")
check("  and reports its encoding", enc.startswith("utf-16"), f"got {enc}")
check("  with no NUL bytes left", "\x00" not in t)

# Big-endian is the one that cannot work by accident. Stripping the BOM and
# then decoding with the BOM-sniffing 'utf-16' codec leaves the codec with no
# BOM to read, so it falls back to native byte order - which on a
# little-endian machine turns this into CJK mojibake and raises nothing.
t, enc = decode_text_bytes(b"\xfe\xff" + utf16_text.encode("utf-16-be"))
check("UTF-16BE with a BOM round-trips", t == utf16_text, f"got {t!r}")
check("  and reports big-endian", enc == "utf-16-be", f"got {enc}")

t32, enc32 = decode_text_bytes(
    b"\x00\x00\xfe\xff" + utf16_text.encode("utf-32-be"))
check("UTF-32BE round-trips", t32 == utf16_text, f"got {t32!r}")

t, enc = decode_text_bytes(b"\xef\xbb\xbfhello")
check("a UTF-8 BOM is stripped", t == "hello", f"got {t!r}")

t, enc = decode_text_bytes(b"plain ascii")
check("plain ASCII stays utf-8", (t, enc) == ("plain ascii", "utf-8"))

# cp1252, not latin-1: 0x93/0x94 are printable curly quotes there and raw
# control characters under latin-1.
t, enc = decode_text_bytes(b"caf\xe9 \x93quoted\x94 \x97 dash")
check("cp1252 fallback decodes high bytes", t == "café “quoted” — dash",
      f"got {t!r}")
check("  and reports cp1252", enc == "cp1252", f"got {enc}")

# A file that is genuinely neither must still return text, never raise.
t, enc = decode_text_bytes(bytes([0x81, 0x8d, 0x8f, 0x90, 0x9d]) + b"tail")
check("cp1252's undefined bytes degrade, not raise", "tail" in t, f"got {t!r}")

check("empty input is not an error", decode_text_bytes(b"") == ("", "empty"))

# UTF-32 first: its LE BOM is a prefix of the UTF-16LE BOM, so order matters.
t, enc = decode_text_bytes(b"\xff\xfe\x00\x00" + "abcd".encode("utf-32-le"))
check("UTF-32LE is not mistaken for UTF-16", t == "abcd", f"got {t!r}")

# Both extraction paths must agree, or a .txt behaves differently from a .log
# for no reason a reader could infer.
u16_path = os.path.join(TMP, "both_paths.txt")
with open(u16_path, "wb") as fh:
    fh.write(b"\xff\xfe" + utf16_text.encode("utf-16-le"))
from backend.modules.text_parser import extract_text
check("the .txt fast path agrees with the byte path",
      extract_text(u16_path) == extract("both.txt", open(u16_path, "rb").read())[0])

# ── D. the new extractors ────────────────────────────────────────────────────

section("E. format-specific extractors")

rtf = (rb"{\rtf1\ansi{\fonttbl{\f0 Arial;}}\ansi\deff0"
       rb"{\colortbl ;\red0\green0\blue0;}\f0\fs24"
       rb" Investigation opened.\par Suspect: John Doe\par}")
t, ty = extract("memo.rtf", rtf)
check("RTF yields prose", "Investigation opened." in t, f"got {t!r}")
check("RTF keeps the suspect line", "John Doe" in t, f"got {t!r}")
check("RTF reports its own type", ty == "rtf", f"got {ty!r}")
check("RTF drops the font table", "fonttbl" not in t and "Arial" not in t)
check("RTF drops the colour table", "colortbl" not in t and "red0" not in t)
check("RTF does not leak control words", "\\par" not in t and "\\ansi" not in t)

plist_obj = {"CFBundleIdentifier": "com.apple.mobilesafari",
             "CFBundleVersion": "1.0",
             "LastModified": __import__("datetime").datetime(2026, 9, 28),
             "Queries": [{"Id": "com.example"}, "com.other"]}
for fmt, label in ((plistlib.FMT_BINARY, "binary"), (plistlib.FMT_XML, "XML")):
    t, ty = extract("Info.plist", plistlib.dumps(plist_obj, fmt=fmt))
    check(f"plist ({label}) parses", ty == "plist", f"got {ty!r}")
    check(f"plist ({label}) keeps the key with its value",
          "CFBundleIdentifier: com.apple.mobilesafari" in t, f"got {t!r}")
    check(f"plist ({label}) flattens arrays with their index",
          "Queries[1]: com.other" in t, f"got {t!r}")

# A binary plist read as text is length-prefixed garbage, so the parse has to
# be real rather than incidental.
t_bin, _ = extract("b.plist", plistlib.dumps(plist_obj, fmt=plistlib.FMT_BINARY))
t_raw, _ = extract("b.txt", plistlib.dumps(plist_obj, fmt=plistlib.FMT_BINARY))
check("a binary plist reads better parsed than raw",
      len(t_bin) < len(t_raw), f"{len(t_bin)} vs {len(t_raw)}")

t, ty = extract("x.mobileconfig",
                b'<?xml version="1.0"?><plist version="1.0"><dict>'
                b"<key>PayloadContent</key><array><string>com.example.app"
                b"</string></array></dict></plist>")
check("a .mobileconfig is a plist", ty == "plist", f"got {ty!r}")
check("  and its payload is extracted", "com.example.app" in t, f"got {t!r}")

t, ty = extract("broken.plist", b"<plist><key>trunc")
check("a malformed plist degrades to text, not a failure",
      "trunc" in t, f"got {t!r}")

# Byte blobs must not be embedded as mojibake. b"\x00\x01\x02binary" is 9
# bytes, and the point is the count, not the value.
blob = plistlib.dumps({"Key": b"\x00\x01\x02binary"}, fmt=plistlib.FMT_BINARY)
t, _ = extract("blob.plist", blob)
check("plist byte values are labelled, not embedded",
      "Key: <9 bytes>" in t, f"got {t!r}")

# A deeply nested plist must not exhaust the stack.
deep = {"a": 1}
for _ in range(200):
    deep = {"n": deep}
t, ty = extract("deep.plist", plistlib.dumps(deep, fmt=plistlib.FMT_XML))
check("a deeply nested plist is truncated, not fatal",
      "nesting limit" in t, f"got {t[:200]!r}")

srt = (b"1\n00:00:01,000 --> 00:00:04,000\n"
       b"Where were you last night?\n\n"
       b"2\n00:00:05,000 --> 00:00:07,500\nAt the warehouse.\n")
t, ty = extract("interview.srt", srt)
check("SRT yields the transcript", "Where were you last night?" in t)
check("SRT joins a multi-line cue into one line",
      "At the warehouse." in t and "\nAt the" not in t, f"got {t!r}")
check("SRT keeps the cue timing", "00:00:01,000" in t, f"got {t!r}")
check("SRT drops the cue numbers", "\n1\n" not in t, f"got {t!r}")

t, ty = extract("c.vtt", b"WEBVTT\n\n00:00:01.000 --> 00:00:04.000\nhello\n")
check("WebVTT yields its text", "hello" in t, f"got {t!r}")
check("  and does not treat the WEBVTT header as a cue", "WEBVTT" not in t)

# The point of the field-order handling: text is NOT always field 9.
ass_reordered = (b"[Script Info]\nTitle: x\n\n[Events]\n"
                 b"Format: Layer, Start, End, Style, Text\n"
                 b"Dialogue: 0,0:00:01.00,0:00:04.00,Default,Where were you?\n")
t, ty = extract("x.ass", ass_reordered)
check("ASS honours its declared field order", t == "Where were you?", f"got {t!r}")

ass_default = (b"[Events]\n"
               b"Format: Layer, Start, End, Style, Name, MarginL, MarginR, "
               b"MarginV, Effect, Text\n"
               b"Dialogue: 0,0:00:01.00,0:00:04.00,Default,Speaker,0,0,0,,Hi\n")
t, ty = extract("y.ass", ass_default)
check("ASS default order still reads the text", "Hi" in t, f"got {t!r}")
check("ASS does not index the style name",
      "Default" not in t, f"got {t!r}")

ass_tagged = (b"[Events]\nFormat: Text\n"
              b"Dialogue: {\\i1}tagged{\\i0} line\n")
t, ty = extract("z.ass", ass_tagged)
check("ASS override tags are stripped", t == "tagged line", f"got {t!r}")

# ── E. the four families that used to be ungated ─────────────────────────────

section("F. the ungated families extract")
families = [
    (".gif", b"GIF89a" + b"\x00" * 40, "gif"),
    (".webp", b"RIFF" + b"\x00" * 40, "webp"),
    (".tif", b"II*\x00" + b"\x00" * 40, "tiff"),
    (".aiff", b"FORM" + b"\x00" * 40, "aiff"),
    (".wma", b"\x30\x26\xb2\x75" + b"\x00" * 40, "wma"),
    (".flv", b"FLV\x01" + b"\x00" * 40, "flv"),
    (".m4v", b"\x00\x00\x00\x20ftypM4V " + b"\x00" * 40, "m4v"),
    (".sqlite", b"SQLite format 3\x00" + b"\x00" * 40, "sqlite"),
]
for ext, blob, label in families:
    # run_ocr=False so this asserts routing, not whether Tesseract is present.
    text, ty = extract("f" + ext, blob, run_ocr=False)
    check(f"{ext:8} is routed to an extractor, not 'unsupported'",
          ty != "unsupported", f"got {ty!r}")

check("a .log is not mistaken for a disk image", not is_forensic_image("a.log"))
check("a .E01 is", is_forensic_image("disk.E01"))
check("a .001 is (the EWF split segment)", is_forensic_image("disk.001"))
check("a .dd is", is_forensic_image("raw.dd"))

# ── F. the agreement checks ──────────────────────────────────────────────────
# This is the section that stops the bug from coming back. Each of these fails
# the moment someone adds a format to one list and not the other.

section("G. the three lists cannot disagree")
check("nothing is advertised that the extractor cannot read",
      unsupported_uploads() == [],
      f"unsupported: {unsupported_uploads()}")
check("nothing is extractable but unlisted",
      orphan_extractables() == [],
      f"orphans: {orphan_extractables()}")
check("the router imports the shared gate, not a private copy",
      ALLOWED_EXTENSIONS is UPLOAD_EXTENSIONS)

section("H. the API's advertised list")
advertised = accept_string().split(",")
check("the accept string is non-empty and well formed",
      advertised and all(e.startswith(".") for e in advertised))
check("it has no duplicates", len(advertised) == len(set(advertised)))
check("it is sorted", advertised == sorted(advertised))
check("everything it advertises passes the gate",
      all(is_supported_upload("f" + e) for e in advertised))
check("every gate extension is advertised",
      set(advertised) == set(UPLOAD_EXTENSIONS))
check("the reported four are advertised",
      {".log", ".csv", ".json", ".xml"} <= set(advertised))

groups = file_formats.describe_groups()
grouped = {e for g in groups for e in g["extensions"]}
check("the described groups cover the gate exactly",
      grouped == set(UPLOAD_EXTENSIONS),
      f"diff: {grouped ^ set(UPLOAD_EXTENSIONS)}")
check("every group has a label, an icon and a description",
      all(g.get("label") and g.get("icon") and g.get("description")
          for g in groups))
check("no extension is claimed by two groups",
      sum(len(g["extensions"]) for g in groups) == len(grouped))

check("every advertised extension has a category",
      all(category_for("f" + e) for e in advertised))
check("an unknown format has no category", category_for("f.zzz") == "")
check("category_for agrees with the group it came from",
      all(category_for("f" + e) == g["key"]
          for g in groups for e in g["extensions"]))

section("I. every accepted format reaches a real extractor")
# Not "is it in a set" - does the cascade actually handle it. A format that
# routes to 'unsupported' uploads fine and indexes nothing.
plain_text_formats = sorted(
    e for e in UPLOAD_EXTENSIONS
    if category_for("f" + e) in
    {'text', 'data', 'markup', 'config', 'code', 'subtitle'})
unrouted = []
for ext in plain_text_formats:
    text, ty = extract("probe" + ext, b"probe body 12345")
    if not text.strip() or ty == "unsupported":
        unrouted.append((ext, ty, text[:40]))
check(f"all {len(plain_text_formats)} text-like formats yield text",
      not unrouted, f"unrouted: {unrouted}")

section("J. viewing and MIME")
for ext in (".log", ".csv", ".json", ".xml", ".yaml", ".sql", ".srt",
            ".plist", ".rtf", ".sh"):
    check(f"{ext:8} is viewable in the browser",
          is_browser_viewable("evidence" + ext))
    check(f"{ext:8} is not served as octet-stream",
          get_mime_type("evidence" + ext) != "application/octet-stream",
          f"got {get_mime_type('evidence' + ext)}")

check("a .plist is served as XML",
      get_mime_type("Info.plist") == "application/xml")
check("an unknown type is still octet-stream",
      get_mime_type("f.zzz") == "application/octet-stream")

section("K. estimates are not fabricated")
# The estimator drove media and image off two hardcoded sets that omitted
# .gif/.webp/.tif/.wma/.aiff/.flv/.webm/.m4v, so those were quoted as
# documents - an 80 MB webm estimated to produce 64 MB of transcript.
from backend.modules.time_estimator import estimate_ingestion_time
MB = 1024 * 1024

for name, expected in (("clip.webm", "media"), ("clip.flv", "media"),
                       ("voice.wma", "media"), ("voice.aiff", "media"),
                       ("clip.m4v", "media"),
                       ("anim.gif", "image"), ("shot.webp", "image"),
                       ("shot.tif", "image"),
                       ("image.E01", "disk_image"),
                       ("server.log", "document"),
                       ("dump.sql", "document")):
    got = estimate_ingestion_time(name, 8 * MB)["category"]
    check(f"{name:14} is categorised as {expected:11}", got == expected,
          f"got {got!r}")

log_est = estimate_ingestion_time("app.log", 80 * MB)["total_seconds"]
sql_est = estimate_ingestion_time("dump.sql", 80 * MB)["total_seconds"]
check("a .sql is not quoted 20x the .txt beside it",
      sql_est < log_est * 2, f"sql={sql_est:.0f} log={log_est:.0f}")
check("a rotated log is estimated as the log it is",
      abs(estimate_ingestion_time("app.log.1", 80 * MB)["total_seconds"]
          - log_est) < 1e-6)
check("a .webm is not quoted as though it were all transcript",
      estimate_ingestion_time("clip.webm", 80 * MB)["total_seconds"]
      < log_est * 30,
      f"{estimate_ingestion_time('clip.webm', 80 * MB)['total_seconds']:.0f}"
      f" vs log {log_est:.0f}")

# ── L. the gate as the endpoint applies it ───────────────────────────────────

section("L. the endpoint's own gate")
from backend.modules.file_formats import is_supported_upload as _gate
check("the gate the router calls is the shared one", _gate is is_supported_upload)
check("a trailing space in a filename does not defeat the gate",
      not is_supported_upload("malware.exe "))
check("uppercase is accepted, as it always was",
      is_supported_upload("SERVER.LOG"))

# ── M. the return shape every caller unpacks ─────────────────────────────────

section("M. extract_text_from_bytes always returns 3 values")

# This is the bug that made a .json file fail to ingest. The function returned
# a 3-tuple on the text/image paths and a 2-tuple on the PDF/SQLite/HTML
# paths; backend/ingestion.py unpacked exactly 2. Asserting "some format
# extracts" is not enough - the shape has to be uniform, because a caller
# cannot unpack a value whose arity depends on which branch ran.
ARITY_SAMPLES = {
    ".txt": b"plain text probe 12345\n",
    ".log": b"2026-01-01 INFO started\n",
    ".csv": b"a,b\n1,2\n",
    ".json": b'{"k": "v"}',
    ".xml": b"<a><b>c</b></a>",
    ".yaml": b"k: v\n",
    ".md": b"# heading\n",
    ".sql": b"SELECT 1;",
    ".html": b"<html><body><p>hi</p></body></html>",
    ".htm": b"<html><body><p>hi</p></body></html>",
    ".rtf": rb"{\rtf1\ansi probe}",
    ".plist": plistlib.dumps({"k": "v"}),
    ".srt": b"1\n00:00:01,000 --> 00:00:02,000\nprobe\n",
    ".pdf": b"%PDF-1.4\n",
    ".db": b"SQLite format 3\x00",
    ".jpg": b"\xff\xd8\xff\xe0" + b"\x00" * 32,
    ".png": b"\x89PNG\r\n\x1a\n" + b"\x00" * 32,
    ".gif": b"GIF89a" + b"\x00" * 32,
    ".weird": b"extension nobody claims\n",
}
bad_arity = []
for ext, payload in ARITY_SAMPLES.items():
    r = fi.extract_text_from_bytes(payload, f"probe{ext}", TMP, run_ocr=False)
    if not isinstance(r, tuple) or len(r) != 3:
        bad_arity.append((ext, len(r) if isinstance(r, tuple) else type(r).__name__))
check(f"all {len(ARITY_SAMPLES)} branches return a 3-tuple",
      not bad_arity, f"offenders: {bad_arity}")

# And the call site must agree with the contract. Source scan rather than AST:
# the pattern is a single tuple target naming both variables, and a readable
# line-by-line check states the rule more plainly than a comprehension over
# parse() output does.
_ing_path = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "backend", "ingestion.py")
_mismatch = []
with open(_ing_path, encoding="utf-8") as fh:
    for lineno, line in enumerate(fh, 1):
        stripped = line.strip()
        if not stripped.startswith("text, extraction_type"):
            continue
        # count the names bound by this tuple target
        tail = stripped.split("=", 1)[0]
        arity = len([p for p in tail.split(",") if p.strip()])
        if arity != 3:
            _mismatch.append(f"line {lineno}: binds {arity}")
check("every (text, extraction_type, ...) unpack in ingestion.py binds 3",
      not _mismatch, "; ".join(_mismatch))

print("\n" + "=" * 66)
for label in FAILED:
    print(f"  FAILED: {label}")
print(f"PASSED: {PASS}    FAILED: {FAIL}")
print("=" * 66)

sys.exit(1 if FAIL else 0)
