import os
import re
import hashlib
import json
import sqlite3
import tempfile
from datetime import datetime
from typing import Generator
from backend.modules.entropy_analyzer import (
    calculate_shannon_entropy,
    HIGH_ENTROPY_THRESHOLD)
from backend.modules.file_store import (
    should_save_file,
    is_browser_viewable,
    save_file,
    get_stored_path,
    get_mime_type)
from backend.modules.text_parser import decode_text_bytes
from backend.modules.file_formats import normalize_extension

# These imports are conditional —
# wrap in try/except for graceful failure
try:
    import pyewf
    PYEWF_AVAILABLE = True
except ImportError:
    PYEWF_AVAILABLE = False
    print("WARNING: pyewf not available. "
          ".E01 support disabled.")

try:
    import pytsk3
    PYTSK3_AVAILABLE = True
except ImportError:
    PYTSK3_AVAILABLE = False
    print("WARNING: pytsk3 not available. "
          "Forensic disk images disabled.")

try:
    import exifread
    EXIFREAD_AVAILABLE = True
except ImportError:
    EXIFREAD_AVAILABLE = False

from pdfminer.high_level import (
    extract_text as pdf_extract)
from bs4 import BeautifulSoup

# File types we extract text from
# The upload gate in file_formats.py advertises a subset of these; the two are
# reconciled by tests/verify_file_formats.py. A format that is extractable
# here but not listed in file_formats is intentional (the in-image walk is
# deliberately broader than direct upload), the reverse is a bug.
TEXT_EXTENSIONS = {
    '.txt', '.log', '.csv', '.tsv', '.xml',
    '.json', '.jsonl', '.ndjson', '.md', '.py', '.js',
    '.html', '.htm',
    # Config and secrets. Credential scanning needs these far more than the
    # original list allowed for - a .env or a .properties file is one of the
    # highest-yield artefacts in a real case.
    '.yaml', '.yml', '.ini', '.cfg', '.conf',
    '.config', '.toml', '.properties',
    # Log/exec output, the shapes that carry crash and stack traces.
    '.text', '.nfo', '.out', '.err', '.trace', '.dump',
    # Source and shell. Opened read as text, so this is a superset of
    # "languages we analyse" - it is a decoding decision, not a parser claim.
    '.ts', '.jsx', '.tsx', '.java', '.c', '.h',
    '.cpp', '.hpp', '.cs', '.go', '.rb', '.php',
    '.pl', '.rs', '.lua', '.r', '.sh', '.bash',
    '.bat', '.ps1', '.sql', '.vb',
    # Extensionless dotfiles, which normalize_extension reports by name
    # because splitext sees a leading dot as a hidden-file marker. A .env is
    # one of the highest-yield artefacts in a case - live API keys, database
    # URLs, internal hostnames - and the credential scanner needs it.
    '.env', '.envrc', '.gitignore', '.gitconfig', '.npmrc',
    '.bashrc', '.bash_history', '.zsh_history', '.profile',
    '.htaccess', '.htpasswd', '.netrc', '.pgpass',
    # NOTE: .eml and .msg are now handled
    # by media_extractor (email extractor)
    # which parses headers + body properly.
    # NOTE: .rtf, .plist and .srt/.vtt/.ass are handled by dedicated
    # extractors below rather than a plain UTF-8 read, because each of them
    # stores its payload in a way that a raw decode garbles.
}
PDF_EXTENSIONS = {'.pdf'}
DB_EXTENSIONS = {'.db', '.sqlite', '.sqlite3'}
IMAGE_EXTENSIONS = {
    '.jpg', '.jpeg', '.png',
    '.tiff', '.tif', '.bmp',
    '.gif', '.webp'
}
HTML_EXTENSIONS = {'.html', '.htm', '.xhtml'}

# Rich Text Format: a Word export that still appears in older case material.
# The payload is wrapped in control words, so it gets a real stripper.
RTF_EXTENSIONS = {'.rtf'}

# Apple property lists - the backbone of iOS/macOS artefacts (Info.plist,
# .mobileconfig, preference payloads).
PLIST_EXTENSIONS = {'.plist', '.mobileconfig'}

# Subtitle / transcript formats. Interview and call recordings are routinely
# exported alongside their subtitles, and a transcript is evidence.
SUBTITLE_EXTENSIONS = {'.srt', '.vtt', '.ass'}

# New multimedia extension sets
OFFICE_EXTENSIONS = {
    '.docx', '.doc',
    '.xlsx', '.xls',
    '.pptx', '.ppt'
}
AUDIO_EXTENSIONS = {
    '.mp3', '.wav', '.m4a',
    '.flac', '.ogg', '.aac',
    '.wma', '.aiff'
}
VIDEO_EXTENSIONS = {
    '.mp4', '.avi', '.mov',
    '.mkv', '.wmv', '.flv',
    '.webm', '.m4v'
}
EMAIL_EXTENSIONS = {'.eml', '.msg'}

# Skip system/binary/archive files
# Audio and video are NO LONGER skipped —
# they are processed by media_extractor.
SKIP_EXTENSIONS = {
    '.exe', '.dll', '.sys', '.bin',
    '.so', '.dylib', '.o', '.a',
    '.zip', '.tar', '.gz', '.7z',
    '.rar', '.pkg', '.dmg', '.iso',
    '.psd', '.ai'
}

# Max file size for text/office/email (50 MB)
# Video files have a separate 2 GB limit.
MAX_FILE_SIZE = 50 * 1024 * 1024
VIDEO_MAX_FILE_SIZE = 2 * 1024 * 1024 * 1024


# Read size for hashing. Was 8 KB, which is a syscall every 8 KB across a
# multi-gigabyte image. 1 MB cuts that by 128x and still gives the stop check
# below a fine-grained place to fire. The digest is identical either way.
_HASH_CHUNK = 1024 * 1024


def compute_sha256(file_path: str, stop_check=None) -> str:
    """
    Computes SHA-256 of a file on disk.

    stop_check is consulted between read chunks and raises to abort.

    Hashing a disk image is the single longest uninterruptible step in the
    whole product - it runs before anything is reported, over every byte of
    the evidence. With no check in the loop, an operator who pressed Stop
    watched the job sit on "Verifying image SHA-256" with no way out, and
    concluded the Stop button was broken rather than slow.

    The StopIteration re-raise is load-bearing: StopIteration is a subclass
    of Exception, so the generic handler below would otherwise swallow it and
    return "" - writing an empty hash to evidence.sha256_hash and carrying on
    as if verification had succeeded. That is the same silent-success defect
    as a truncated image reported as processed.
    """
    sha256 = hashlib.sha256()
    try:
        with open(file_path, "rb") as f:
            for chunk in iter(
                    lambda: f.read(_HASH_CHUNK), b""):
                if stop_check is not None and stop_check():
                    raise StopIteration("Ingestion stopped by user")
                sha256.update(chunk)
        return sha256.hexdigest()
    except StopIteration:
        raise
    except Exception as e:
        print(f"[FORENSIC] SHA256 error: {e}")
        return ""


def compute_sha256_bytes(data: bytes) -> str:
    """Computes SHA-256 of bytes in memory."""
    return hashlib.sha256(data).hexdigest()


def format_timestamp(ts_value) -> str:
    """Converts pytsk3 timestamp to string."""
    try:
        if ts_value and ts_value > 0:
            return datetime.utcfromtimestamp(
                ts_value
            ).strftime('%Y-%m-%d %H:%M:%S UTC')
    except Exception:
        pass
    return "Unknown"


def is_supported_file(filename: str,
                      size: int) -> bool:
    """
    Returns True if the file should be
    processed. Skips system files, empty
    files, and oversized files.
    Video files have a higher size limit
    (2 GB) since only the audio track
    is transcribed.
    Registry hive files (NTUSER.DAT, SYSTEM,
    SOFTWARE, SAM, etc.) have no extension
    but are explicitly allowed by name.
    """
    if not filename or filename.startswith('$'):
        return False  # Skip NTFS system files
    if size <= 0:
        return False
    ext = os.path.splitext(filename.lower())[1]
    if ext in SKIP_EXTENSIONS:
        return False
    # Video files: allow up to 2 GB
    if ext in VIDEO_EXTENSIONS:
        if size > VIDEO_MAX_FILE_SIZE:
            print(f"[FORENSIC] Skipping "
                  f"{filename}: "
                  f"{size / 1e9:.1f} GB "
                  f"exceeds 2 GB video limit")
            return False
        return True
    # Registry hives: no extension but matched by name
    if not ext:
        try:
            from backend.modules.registry_parser import REGISTRY_HIVES
            if filename.lower() in REGISTRY_HIVES:
                return True
        except ImportError:
            pass
        return False  # Unknown extensionless file — skip
    # All other files: max 50 MB
    if size > MAX_FILE_SIZE:
        return False
    return True


# ---------------------------------------------------------------------------
# Format-specific text extractors
# ---------------------------------------------------------------------------

# Destinations whose contents are markup, not prose. Skipping them is what
# keeps font names and colour tables out of an extracted "document".
_RTF_SKIP_DESTINATIONS = {
    'fonttbl', 'colortbl', 'stylesheet', 'info', 'pict', 'object',
    'filetbl', 'listtable', 'listoverridetable', 'rsidtbl', 'generator',
    'themedata', 'colorschememapping', 'latentstyles', 'datastore',
    'xmlnstbl', 'panose', 'falt', 'listtext', 'pn', 'shppict',
    'nonshppict', 'field', 'shp', 'shpinst', 'do', 'objclass',
    'objdata', 'result', 'atnid', 'atnauthor', 'atndate',
    'bkmkstart', 'bkmkend', 'comment', 'annotation', 'footnote',
}

# Control words that contribute a literal character.
_RTF_LITERALS = {
    'emdash': '\u2014', 'endash': '\u2013',
    'bullet': '\u2022', 'lquote': '\u2018', 'rquote': '\u2019',
    'ldblquote': '\u201c', 'rdblquote': '\u201d',
}

_RTF_TOKEN_RE = re.compile(
    r"""
      \\(?P<hex>'[0-9a-fA-F]{2})
    | \\(?P<word>[a-zA-Z]+)(?P<param>-?[0-9]+)?[ ]?
    | \\(?P<symbol>.)
    | (?P<open>\{)
    | (?P<close>\})
    | (?P<text>[^\\{}]+)
    """,
    re.VERBOSE | re.DOTALL,
)


def _extract_rtf(data: bytes) -> tuple:
    """
    Pulls the readable text out of an RTF document.

    RTF wraps its prose in control words (`\\b`, `\\fs24`, `\\par`) and hides
    its tables inside `{\\*...}` destinations, so reading it as UTF-8 indexes
    control words and font tables instead of the document. This is a text
    stripper, not a layout-preserving RTF parser - it yields the words in
    order, which is what the index and the entity extractor need.
    """
    raw, encoding = decode_text_bytes(data)
    if not raw:
        return "", 'rtf', {}

    out = []
    depth = 0
    skip_from = None

    for m in _RTF_TOKEN_RE.finditer(raw):
        if m.group('open') is not None:
            depth += 1
            continue
        if m.group('close') is not None:
            if skip_from is not None and depth <= skip_from:
                skip_from = None
            depth = max(0, depth - 1)
            continue
        if skip_from is not None:
            continue
        if m.group('text') is not None:
            out.append(m.group('text'))
            continue
        if m.group('hex') is not None:
            out.append(bytes(
                [int(m.group('hex')[1:], 16)]
            ).decode('cp1252', 'replace'))
            continue

        word = m.group('word')
        param = m.group('param')
        if word is not None:
            if word == 'u' and param:
                # \uN? - a signed 16-bit code point
                try:
                    cp = int(param)
                    if cp < 0:
                        cp += 65536
                    out.append(chr(cp))
                except (ValueError, OverflowError):
                    pass
                continue
            if word in _RTF_LITERALS:
                out.append(_RTF_LITERALS[word])
                continue
            if word in ('par', 'line', 'sect', 'page'):
                out.append('\n')
                continue
            if word in _RTF_SKIP_DESTINATIONS:
                skip_from = depth
            continue

        symbol = m.group('symbol')
        if symbol in ('\\', '{', '}'):
            out.append(symbol)
        elif symbol in ('~', '_'):
            out.append(' ' if symbol == '~' else '-')
        elif symbol in ('\r', '\n'):
            out.append('\n')
        elif symbol == '*':
            skip_from = depth

    text = ''.join(out)
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n\s*\n+', '\n', text)
    return text.strip()[:50000], 'rtf', {'_encoding': encoding}


def _flatten_plist(obj, prefix='', out=None, depth=0) -> list:
    """
    Flattens a parsed plist into `dotted.key: value` lines.

    Dotted keys rather than indented lines, because a line of text carrying a
    bare value is what gets chunked and embedded - the key has to travel with
    the value or "Last Modified" cannot be connected to a date.
    """
    if out is None:
        out = []
    if depth > 12:
        # A hostile or malformed plist can nest deeply enough to exhaust the
        # stack; truncating is recoverable, a RecursionError is not.
        out.append(f"{prefix}: <nesting limit reached>")
        return out
    if isinstance(obj, dict):
        for key, value in obj.items():
            child = f"{prefix}.{key}" if prefix else str(key)
            _flatten_plist(value, child, out, depth + 1)
    elif isinstance(obj, (list, tuple)):
        if not obj:
            out.append(f"{prefix}:")
        for index, value in enumerate(obj):
            _flatten_plist(
                value, f"{prefix}[{index}]", out, depth + 1)
    elif isinstance(obj, (bytes, bytearray)):
        out.append(f"{prefix}: <{len(obj)} bytes>")
    else:
        out.append(f"{prefix}: {obj}")
    return out


def _extract_plist(data: bytes) -> tuple:
    """
    Parses an Apple property list with plistlib (stdlib) and flattens it.

    Binary plists are the norm in iOS artefacts, and their strings are
    length-prefixed binary - a plain read yields fragments interleaved with
    binary noise, so the text would embed but be full of garbage tokens.
    """
    try:
        import plistlib
        parsed = plistlib.loads(data)
    except Exception:
        # Not a well-formed plist. Read it as text anyway: plenty of files
        # called .plist are hand-written or truncated XML, and a partial
        # read beats refusing the file.
        text, encoding = decode_text_bytes(data)
        return text[:50000], 'text', {'_encoding': encoding}

    lines = _flatten_plist(parsed)
    return '\n'.join(lines)[:50000], 'plist', {}


def _strip_ass_tags(text: str) -> str:
    """Removes ASS/SSA override blocks ({...}) and \\N line breaks."""
    text = re.sub(r'\{[^}]*\}', '', text)
    return text.replace('\\N', ' ').replace('\\n', ' ').replace('\\h', ' ')


def _extract_ass(raw: str) -> str:
    """
    Reads an Advanced SubStation file, honouring its declared field order.

    The field order is not fixed: an ASS file declares it in
    `[Events]`/`Format:`, and the text is wherever that line puts it. Reading
    a Dialogue record positionally instead indexes the font name, the layer
    and the effect string - plausible-looking text that means nothing.
    """
    out = []
    fields = None
    text_index = 9  # the spec's default position
    in_events = False

    for line in raw.replace('\r\n', '\n').replace('\r', '\n').split('\n'):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith('['):
            in_events = stripped.lower().startswith('[events')
            continue
        if not in_events:
            continue
        head, _, rest = stripped.partition(':')
        key = head.strip().lower()
        if key == 'format':
            fields = [f.strip().lower() for f in rest.split(',')]
            if 'text' in fields:
                text_index = fields.index('text')
        elif key == 'dialogue' and fields:
            # Text is the last field and may itself contain commas, so the
            # split is bounded to len(fields) - 1 pieces.
            parts = rest.split(',', len(fields) - 1)
            if text_index < len(parts):
                cue = _strip_ass_tags(parts[text_index].strip())
                if cue:
                    out.append(cue)

    return '\n'.join(out)


def _extract_cues(raw: str) -> str:
    """
    Reads SRT / WebVTT cues, keeping the start time with each line.

    Cue text can span several lines, so the body is collected until the blank
    line that ends the block rather than one line at a time - reading a cue
    as a single line keeps one fragment per line and splits sentences.
    """
    lines = raw.replace('\r\n', '\n').replace('\r', '\n').split('\n')
    out = []
    index = 0

    while index < len(lines):
        stripped = lines[index].strip()
        if '-->' in stripped:
            start = stripped.split('-->')[0].strip()
            body = []
            index += 1
            while index < len(lines) and lines[index].strip():
                body.append(lines[index].strip())
                index += 1
            cue = ' '.join(body)
            if cue:
                out.append(f"[{start}] {cue}")
            continue

        # Bare integers are SRT cue numbers, and the remaining bare keywords
        # are VTT block headers. Neither carries evidence text.
        if (stripped.isdigit()
                or stripped.upper() in _SUBTITLE_HEADER_LINES
                or stripped.split(':')[0].lower() in _SUBTITLE_META_KEYS):
            index += 1
            continue

        if stripped:
            out.append(stripped)
        index += 1

    return '\n'.join(out)


_SUBTITLE_HEADER_LINES = {
    'WEBVTT', 'NOTE', 'STYLE', 'REGION', 'END',
}

_SUBTITLE_META_KEYS = {'kind', 'language', 'voice'}


def _extract_subtitle(data: bytes) -> tuple:
    """
    Extracts text from SRT / WebVTT / ASS subtitle and transcript files.

    Interview and call recordings are routinely accompanied by a subtitle
    file, and that transcript is evidence in its own right - often the only
    searchable form of a recording whose audio transcribes poorly.
    """
    raw, encoding = decode_text_bytes(data)
    if not raw:
        return "", 'subtitle', {}

    if re.search(r'^\s*\[events\]', raw, re.IGNORECASE | re.MULTILINE):
        text = _extract_ass(raw)
        extraction_type = 'subtitle_ass'
    else:
        text = _extract_cues(raw)
        extraction_type = 'subtitle'

    return text.strip()[:50000], extraction_type, {'_encoding': encoding}


def extract_text_from_bytes(
        data: bytes,
        filename: str,
        temp_dir: str,
        run_ocr: bool = True,
        whisper_model: str = None,
        whisper_gpu: bool = True) -> tuple:
    """
    Extracts text from file bytes.

    ALWAYS returns exactly 3 values:
        (extracted_text, extraction_type, metadata_dict)

    The third element is the EXIF/metadata dict; it is an empty dict for every
    branch that has none.

    **The arity is deliberately uniform.** It used to vary by branch - the PDF,
    SQLite, HTML and RTF/plist/subtitle paths returned 2-tuples while the text
    and image paths returned 3 - so a caller's unpack had to be written to
    tolerate both. `ingestion.py` was not written that way, and the result was
    `ValueError: too many values to unpack (expected 2)` on every plain-text
    upload. It went unnoticed because the only branches reachable through the
    document pipeline's multimedia path were images and archives, which
    returned 3; the moment `.json`/`.log`/`.csv` became uploadable they did too.

    A return value whose *shape* depends on which branch handled the file is a
    defect waiting for a caller. Every branch below returns 3, and the
    regression test asserts the arity is 3 for every advertised format.

    Writes to temp file for libraries that need a file path.

    run_ocr / whisper_model / whisper_gpu come from the ingestion mode.
    They are keyword-only-with-defaults so every existing caller keeps
    working unchanged, but the 'fastest' profile now genuinely skips OCR
    instead of paying for it and throwing the text away.
    """
    # normalize_extension rather than os.path.splitext, so the extractor
    # classifies a file the same way the upload gate and the time estimator
    # do. The difference is not cosmetic: splitext reports '' for a dotfile
    # (".env" is a hidden file, not an extension) and ".1" for a rotated log
    # ("app.log.1"), so a .env routed here as unrecognised and a rotated log
    # routed here as an unknown type. Both then returned 'unsupported' and
    # indexed nothing.
    ext = normalize_extension(filename)

    # A FAT volume truncates every name to 8.3, so REPORT.DOCX arrives here as
    # REPORT.DOC and the extension points a zip file at a reader that cannot
    # open it. Correct the extension from the archive's own contents BEFORE
    # anything is dispatched on it, so every downstream branch sees the truth.
    real_office = _sniff_zip_office(data)
    if real_office:
        ext = "." + real_office

    # PDF files — check before text
    if ext in PDF_EXTENSIONS:
        try:
            tmp_path = os.path.join(
                temp_dir, f"tmp_{filename}")
            with open(tmp_path, 'wb') as f:
                f.write(data)
            text = pdf_extract(tmp_path)
            try:
                os.remove(tmp_path)
            except Exception:
                pass
            return (text[:50000] if text else ""), 'pdf', {}
        except Exception:
            return "", 'pdf', {}

    # SQLite databases — check before text
    if ext in DB_EXTENSIONS:
        try:
            from backend.modules.media_extractor import extract_browser_history
            browser_history = extract_browser_history(
                data, filename, temp_dir)
            if browser_history:
                return (browser_history,
                        'browser_history', {})

            tmp_path = os.path.join(
                temp_dir, f"tmp_{filename}")
            with open(tmp_path, 'wb') as f:
                f.write(data)
            text_parts = []
            conn = sqlite3.connect(tmp_path)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table'")
            tables = cursor.fetchall()
            for (table_name,) in tables[:10]:
                try:
                    cursor.execute(
                        f'SELECT * FROM "{table_name}" '
                        f"LIMIT 100")
                    rows = cursor.fetchall()
                    text_parts.append(
                        f"Table: {table_name}")
                    for row in rows:
                        text_parts.append(
                            ' | '.join(
                                str(c) for c in row
                                if c is not None
                            )
                        )
                except Exception:
                    continue
            conn.close()
            try:
                os.remove(tmp_path)
            except Exception:
                pass
            return (
                '\n'.join(text_parts)[:50000],
                'sqlite',
                {}
            )
        except Exception:
            return "", 'sqlite', {}

    # HTML files — check before text (.html is in both sets)
    if ext in HTML_EXTENSIONS:
        try:
            soup = BeautifulSoup(data, 'lxml')
            text = soup.get_text(
                separator=' ', strip=True)
            return text[:50000], 'html', {}
        except Exception:
            return "", 'html', {}

    # Image files — try OCR first,
    # then fall through to EXIF below
    if ext in IMAGE_EXTENSIONS:
        if not run_ocr:
            # 'fastest' profile: skip Tesseract entirely. EXIF/GPS below
            # still runs, so the image is not lost - it just has no text.
            print(
                "[EXTRACT] OCR disabled by ingestion mode - "
                "extracting EXIF only."
            )
        else:
            from backend.modules.media_extractor \
                import extract_image_ocr
            ocr_text = extract_image_ocr(data)
            if ocr_text and len(
                    ocr_text.strip()) > 20:
                return ocr_text[:20000], 'ocr', {}
        # Fall through to EXIF + GPS extraction
        if EXIFREAD_AVAILABLE:
            try:
                import io
                tags = exifread.process_file(
                    io.BytesIO(data),
                    details=False
                )

                # Extract GPS coordinates
                gps_lat     = tags.get('GPS GPSLatitude')
                gps_lat_ref = tags.get('GPS GPSLatitudeRef')
                gps_lon     = tags.get('GPS GPSLongitude')
                gps_lon_ref = tags.get('GPS GPSLongitudeRef')

                lat = lon = None
                if gps_lat and gps_lat_ref:
                    lat = _convert_gps(
                        gps_lat, str(gps_lat_ref))
                if gps_lon and gps_lon_ref:
                    lon = _convert_gps(
                        gps_lon, str(gps_lon_ref))

                exif_dict = {
                    str(k): str(v)
                    for k, v in tags.items()
                    if not k.startswith('Thumbnail')
                }

                # Embed GPS in exif_dict for caller
                if lat is not None and lon is not None:
                    exif_dict['_gps_lat'] = lat
                    exif_dict['_gps_lon'] = lon

                # Build text output
                text_parts = []
                if lat is not None and lon is not None:
                    text_parts.append(
                        f"GPS Location: {lat:.6f}, {lon:.6f}")
                for k, v in list(exif_dict.items())[:20]:
                    if not k.startswith('_'):
                        text_parts.append(f"{k}: {v}")

                return (
                    '\n'.join(text_parts)[:10000],
                    'exif',
                    exif_dict
                )
            except Exception:
                pass
        return "", 'exif', {}

    # RTF — a Word export that decodes to control-word noise,
    # so it gets a real stripper rather than a raw read.
    if ext in RTF_EXTENSIONS:
        return _extract_rtf(data)

    # Apple property lists — binary or XML, parsed with plistlib
    # (stdlib) and flattened to searchable key/value text.
    if ext in PLIST_EXTENSIONS:
        return _extract_plist(data)

    # Subtitles / transcripts. Cue timings are kept because a transcript's
    # value is very often in the timing.
    if ext in SUBTITLE_EXTENSIONS:
        return _extract_subtitle(data)

    # Plain text files
    # (txt, log, csv, json, py, js, md, yaml, sql…)
    if ext in TEXT_EXTENSIONS:
        text, encoding = decode_text_bytes(data)
        if not text.strip():
            return "", 'text', {}
        return text[:50000], 'text', {'_encoding': encoding}

    # Office documents, audio, video, email
    # Route to media_extractor module
    if ext in (
        OFFICE_EXTENSIONS |
        AUDIO_EXTENSIONS |
        VIDEO_EXTENSIONS |
        EMAIL_EXTENSIONS
    ):
        from backend.modules.media_extractor \
            import extract_media
        result = extract_media(
            data, filename, temp_dir,
            run_ocr=run_ocr,
            whisper_model=whisper_model,
            whisper_gpu=whisper_gpu)
        # extract_media returns (text, type)
        #
        # A failed extractor returns "" and the caller above has ALREADY been
        # told the type, so the pair ('', 'docx') says "this is a Word document
        # and it yielded nothing" -- a true-shaped label attached to content
        # that was never extracted. Measured before this guard, on a FAT image
        # where REPORT.DOCX arrives as REPORT.DOC:
        #     [MEDIA] docx extraction error: no item named '[Content_Types].xml'
        #     -> extraction_type='docx', extracted_text=''
        # and the error went to a log nobody reads while the artifact list
        # reported the file as a processed Word document.
        #
        # So an empty result is NOT allowed to keep the claimed type. Fall
        # through to the content sniffer, which will identify the file from its
        # bytes if it is recoverable that way, and otherwise says 'unsupported'
        # -- which is the truth.
        if not (result[0] or "").strip():
            sniffed = _sniff_unknown_text(data)
            if sniffed[0]:
                return sniffed
            return "", 'unsupported', {
                '_claimed_extension': ext,
                '_reason': f"{ext} reader produced no text from this file",
            }
        return result[0], result[1], {}

    # The extension is not in any allowlist. Before discarding the content,
    # decide from the bytes -- see the long note on _looks_like_text for why an
    # extension allowlist is the wrong model for a FAT volume.
    return _sniff_unknown_text(data)


def _sniff_unknown_text(data: bytes) -> tuple:
    """Fallback for files whose extension is not in any allowlist.

    Kept separate from _looks_like_text so the dispatch is readable at the call
    site, and so the fallback can be exercised on its own.

    The extraction_type is 'text_sniffed', NOT 'text'. The distinction is the
    whole point: an analyst looking at the artifact list needs to know this was
    identified by content because the name said nothing, and a file truncated to
    8.3 on a FAT volume is exactly the case where that distinction carries
    information. Reporting it as plain 'text' would be a confident true-shaped
    label that hides how the format was decided.
    """
    is_text, decoded = _looks_like_text(data)
    if not is_text or not decoded.strip():
        return "", 'unsupported', {}
    return decoded[:50000], 'text_sniffed', {'_identified_by': 'content'}


# ── content sniffing: the fallback that makes disk images usable ─────────────
#
# WHY THIS EXISTS
# Extension dispatch is the wrong model for forensic disk images, and not by a
# small margin. A FAT filesystem -- which is what `.001` raw images of older
# laptops and most USB sticks actually are -- truncates every filename to 8.3.
# So the evidence loses its extension:
#
#     MALCFG.JSON   -> MALCFG.JSO   (3 of 4 letters; not in any allowlist)
#     EMPLOYEE.DAT  -> EMPLOYEE.DAT  (.dat is not a listed text extension)
#     CONTACTS.VCF  -> CONTACTS.VCF  (nor is .vcf)
#     LEDGER_DLL.REC-> _EDGERDL.REC
#     REPORT.DOCX   -> REPORT.DOC    (then routed to the .doc reader, which
#                                    cannot open a docx zip)
#
# Measured on a 32 MB FAT16 test image before this change: 12 files walked,
# 12 readable, 4 of them -- including the employee record that names the
# suspect and the malware config whose operator_handles field reads
# ["nightowl", "m.webb"] -- silently indexed as ZERO bytes.
#
# That is B1/B10's defect class again, and the worst direction: the evidence
# that ties the chat handle to a named employee was present, readable, and
# discarded, so the investigator is told the disk contains nothing connecting
# the two.
#
# So: when the extension says nothing, decide from the BYTES. This does not
# weaken any existing branch -- it only runs where the function was about to
# return 'unsupported', i.e. where the alternative was to throw the content away.
#
# WHAT IT WILL NOT DO
# It requires the bytes to actually BE text. A binary blob, an image, an
# archive or an encrypted payload fails the test and still returns
# 'unsupported'. Nothing here invents text out of a file that has none.
_NOISE = b'\x00'


def _sniff_zip_office(data: bytes):
    """Identify an OOXML document by what is inside the archive, not its name.

    A docx, xlsx and pptx are all zip files, and each puts its parts under a
    distinct top-level directory. That makes the format self-describing, which
    matters because a FAT volume truncates the extension that would otherwise
    tell us:

        REPORT.DOCX -> REPORT.DOC    (routed to the .doc reader, which hands a
                                     zip to python-docx; it raises, the error
                                     goes to a log nobody reads, and the file
                                     is indexed as ZERO bytes while still
                                     labelled extraction_type='docx')

    That last part is the defect worth naming: the label is true-shaped and
    false, which is the failure mode this whole file is about. Measured on a
    FAT image before this fix: "[MEDIA] docx extraction error: no item named
    '[Content_Types].xml' in the archive", and the artifact contributed nothing.

    Returns 'docx' | 'xlsx' | 'pptx' | None. None means "not an OOXML archive",
    which is a real answer -- plenty of zips are not Office documents.
    """
    if not data.startswith(b"PK\x03\x04"):
        return None
    try:
        import io
        import zipfile
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            names = z.namelist()
    except Exception:
        # A truncated or corrupt zip is not an OOXML document. Say so rather
        # than guessing -- a zip that cannot be opened is exactly the case where
        # a fallback would otherwise hand it to the wrong reader.
        return None
    for kind, marker in (("docx", "word/"), ("xlsx", "xl/"), ("pptx", "ppt/")):
        if any(n.startswith(marker) for n in names):
            return kind
    return None


def _looks_like_text(data: bytes) -> tuple:
    """Decide whether `data` is readable text, by content alone.

    Returns (is_text, decoded_text). The test is deliberately conservative:

      * a NUL byte means binary -- true of every real binary format, and no
        encoding of text produces one;
      * the bytes must decode under UTF-8 or cp1252/latin-1;
      * a high proportion must be printable or ordinary whitespace.

    The cp1252 fallback is what catches a Windows-authored file with a stray
    CP-1252 byte in it, which is extremely common in old log and .dat files
    lifted off a FAT drive.
    """
    if not data:
        return False, ""
    if _NOISE in data[:4096]:
        return False, ""
    # A 4 KB sample is enough to judge and keeps this O(1) on a 64 MB file.
    sample = data[:4096]

    for encoding in ("utf-8", "cp1252"):
        try:
            text = sample.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
        if not text:
            continue
        printable = sum(
            1 for ch in text
            if ch.isprintable() or ch in "\r\n\t\f\v"
        )
        ratio = printable / len(text)
        # 0.85 is the same threshold class used for "is this a text file"
        # elsewhere; below it the content is mostly control bytes, which is
        # what a binary looks like once decoded with a permissive codec.
        if ratio >= 0.85:
            # Re-decode the WHOLE payload with whichever codec judged the
            # sample, so the caller gets the whole file and not a 4 KB slice.
            try:
                return True, data.decode(encoding)
            except (UnicodeDecodeError, LookupError):
                return True, text
    return False, ""


def _convert_gps(coord, ref) -> float:
    """
    Converts an exifread GPS coordinate
    value to decimal degrees.
    Returns None on failure.
    """
    try:
        from fractions import Fraction

        def to_float(val):
            if hasattr(val, 'num'):
                return float(
                    Fraction(val.num, val.den))
            return float(val)

        vals = coord.values
        degrees = to_float(vals[0])
        minutes = to_float(vals[1])
        seconds = to_float(vals[2])
        decimal = (degrees +
                   minutes / 60 +
                   seconds / 3600)
        if ref in ('S', 'W'):
            decimal = -decimal
        return round(decimal, 6)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# EWFImageInfo — bridge between pyewf and pytsk3
# ---------------------------------------------------------------------------

if PYTSK3_AVAILABLE:
    class EWFImageInfo(pytsk3.Img_Info):
        """
        Bridge class between pyewf and pytsk3.
        Allows pytsk3 to read from an open
        pyewf handle.
        """
        def __init__(self, ewf_handle):
            self._ewf_handle = ewf_handle
            super().__init__(
                url="",
                type=pytsk3.TSK_IMG_TYPE_EXTERNAL
            )

        def get_size(self):
            return self._ewf_handle.get_media_size()

        def read(self, offset, length):
            self._ewf_handle.seek(offset)
            return self._ewf_handle.read(length)

else:
    class EWFImageInfo:
        """Stub when pytsk3 is not installed."""
        def __init__(self, ewf_handle):
            raise RuntimeError(
                "pytsk3 is not installed.")


# ---------------------------------------------------------------------------
# Filesystem walker
# ---------------------------------------------------------------------------

def walk_filesystem(
        img_info,
        fs_info,
        directory=None,
        path="/",
        include_deleted: bool = False) -> Generator:
    """
    Recursively walks the filesystem.
    Yields dict for each regular file found.
    When include_deleted=True, also yields
    files marked as unallocated/deleted.
    """
    if not PYTSK3_AVAILABLE:
        return

    if directory is None:
        directory = fs_info.open_dir(path="/")

    for entry in directory:
        try:
            # Skip . and .. entries
            name = entry.info.name.name
            if isinstance(name, bytes):
                name = name.decode(
                    'utf-8', errors='replace')
            if name in ('.', '..'):
                continue

            # Skip if no metadata
            if (not entry.info.meta or
                    entry.info.meta.type is None):
                continue

            full_path = os.path.join(path, name)

            # If directory, recurse
            if (entry.info.meta.type ==
                    pytsk3.TSK_FS_META_TYPE_DIR):
                try:
                    sub_dir = entry.as_directory()
                    yield from walk_filesystem(
                        img_info, fs_info,
                        sub_dir, full_path,
                        include_deleted=include_deleted)
                except Exception:
                    continue

            # If regular file
            elif (entry.info.meta.type ==
                  pytsk3.TSK_FS_META_TYPE_REG):
                size = entry.info.meta.size

                # Detect if deleted/unallocated
                is_deleted = bool(
                    entry.info.meta.flags &
                    pytsk3.TSK_FS_META_FLAG_UNALLOC
                )

                # Skip deleted files unless explicitly requested
                if is_deleted and not include_deleted:
                    continue

                if not is_supported_file(name, size):
                    if not (is_deleted and include_deleted):
                        continue

                # Get MACB timestamps
                meta = entry.info.meta
                yield {
                    "filename": name,
                    "internal_path": full_path,
                    "size": size,
                    "modified": format_timestamp(
                        meta.mtime),
                    "accessed": format_timestamp(
                        meta.atime),
                    "created": format_timestamp(
                        meta.crtime),
                    "born": format_timestamp(
                        meta.ctime),
                    "entry": entry,
                    "is_deleted": is_deleted
                }

        except Exception as e:
            print(f"[FORENSIC] Walk error "
                  f"at {path}: {e}")
            continue


# ---------------------------------------------------------------------------
# Image container detection
#
# The file EXTENSION is not trusted. '.001' is the
# standard split-EWF segment extension but is also
# routinely used for plain raw images, while '.e01'
# is EWF and '.dd'/'.img' are raw. Routing on
# extension alone sends genuine multi-segment EWF
# sets to pytsk3, which cannot read EWF-compressed
# segments and yields 0 files with no error.
# Content decides.
# ---------------------------------------------------------------------------

EWF_SIGNATURES = (
    b"EVF\x09\x0d\x0a\xff\x00",   # EnCase EWF
    b"EVF\x09\x0d\x0a\xff\x01",   # FTK EWF
    b"LVF\x09\x0d\x0a\xff\x00",   # Logical EWF
    b"EVF\x09\x0d\x0a\xff\xc0",   # EnCase EWF (ex04)
)


def detect_image_format(image_path: str) -> str:
    """
    Sniffs the container format from the file header.

    Returns 'ewf', 'raw', or 'unknown'.
    """
    try:
        with open(image_path, "rb") as f:
            head = f.read(8)
    except OSError:
        return "unknown"

    for sig in EWF_SIGNATURES:
        if head.startswith(sig):
            return "ewf"
    return "raw"


def _sniff_filesystem(boot: bytes) -> str:
    """Identifies a filesystem from its boot sector."""
    if len(boot) < 512:
        return "unknown"
    oem = boot[3:11]
    if oem == b"NTFS    ":
        return "NTFS"
    if oem == b"EXFAT   ":
        return "exFAT"
    if oem in (b"MSDOS5.0", b"MSDOS4.0", b"MSWIN4.0", b"MSWIN4.1"):
        # The OEM string does NOT distinguish FAT12/16/32 - MSDOS5.0 is
        # used by all of them. Classify by data-cluster count the same
        # way TSK does, so the label and the declared size are honest.
        return "FAT32" if boot[16] == 0x00 and \
            int.from_bytes(boot[17:19], "little") == 0 else "FAT12/16"
    if boot[510:512] == b"\x55\xaa":
        return "FAT"
    return "unknown"


def _declared_volume_bytes(boot: bytes,
                           fs_type: str,
                           part_sectors: int) -> int:
    """
    Returns the volume size the boot sector claims,
    so truncation can be detected without mounting.
    Falls back to the partition length when the
    boot sector does not state a usable size.
    """
    bps = int.from_bytes(boot[11:13], "little") or 512

    if fs_type == "NTFS":
        total = int.from_bytes(boot[40:48], "little")
        if total:
            return total * bps

    if fs_type.startswith("FAT"):
        # FAT32 uses the 32-bit total-sectors field; FAT12/16 use the
        # 16-bit field unless it is zero, in which case 32-bit is used.
        total = int.from_bytes(boot[19:21], "little")
        if not total:
            total = int.from_bytes(boot[32:36], "little")
        if total:
            return total * bps

    return part_sectors * 512


def inspect_raw_image(image_path: str) -> dict:
    """
    Parses the MBR and per-partition boot sectors of a
    raw image WITHOUT mounting it.

    Purpose: detect truncated / partial images before
    ingestion starts. A truncated image cannot be walked
    (for NTFS the $MFT usually sits past EOF), and the
    resulting TSK error is actively misleading.

    Returns a dict:
      {
        'file_size': int,
        'has_mbr': bool,
        'partitions': [ {index, offset, sectors, type,
                         fs_type, declared_bytes,
                         present_bytes, truncated}, ... ],
        'truncated': bool,
        'summary': str
      }
    """
    result = {
        "file_size": 0,
        "has_mbr": False,
        "partitions": [],
        "truncated": False,
        "summary": "",
    }

    try:
        file_size = os.path.getsize(image_path)
    except OSError as e:
        result["summary"] = f"Cannot stat image: {e}"
        return result

    result["file_size"] = file_size
    SECTOR = 512

    try:
        with open(image_path, "rb") as f:
            mbr = f.read(SECTOR)
            if len(mbr) < SECTOR or mbr[510:512] != b"\x55\xaa":
                result["summary"] = (
                    "No MBR boot signature - image may be a bare "
                    "filesystem or unsupported layout."
                )
                return result

            result["has_mbr"] = True

            for i in range(4):
                entry = mbr[446 + i * 16: 446 + (i + 1) * 16]
                if len(entry) < 16:
                    break

                ptype = entry[4]
                start_lba = int.from_bytes(entry[8:12], "little")
                sectors = int.from_bytes(entry[12:16], "little")

                if ptype == 0 or sectors == 0:
                    continue

                offset = start_lba * SECTOR

                boot = b""
                if offset + SECTOR <= file_size:
                    f.seek(offset)
                    boot = f.read(SECTOR)

                fs_type = _sniff_filesystem(boot) if boot else "unreadable"
                declared = _declared_volume_bytes(boot, fs_type, sectors)
                present = max(0, min(declared, file_size - offset))
                truncated = present < declared

                result["partitions"].append({
                    "index": i,
                    "offset": offset,
                    "sectors": sectors,
                    "type": ptype,
                    "fs_type": fs_type,
                    "declared_bytes": declared,
                    "present_bytes": present,
                    "truncated": truncated,
                })

    except Exception as e:
        result["summary"] = f"Failed to parse image layout: {e}"
        return result

    if not result["partitions"]:
        result["summary"] = "MBR present but no partition entries found."
        return result

    bad = [p for p in result["partitions"] if p["truncated"]]
    if bad:
        result["truncated"] = True
        p = bad[0]
        pct = (100.0 * p["present_bytes"] / p["declared_bytes"]) \
            if p["declared_bytes"] else 0.0
        result["summary"] = (
            f"IMAGE IS TRUNCATED - partition {p['index']} ({p['fs_type']}) "
            f"declares {_human_bytes(p['declared_bytes'])} but only "
            f"{_human_bytes(p['present_bytes'])} "
            f"({pct:.1f}%) is present in the "
            f"{_human_bytes(file_size)} file. A partial copy cannot be "
            f"fully walked - re-acquire the complete image."
        )
    else:
        result["summary"] = (
            f"Layout OK - {len(result['partitions'])} partition(s), "
            f"all fully contained in {_human_bytes(file_size)}."
        )

    return result


def _human_bytes(n: int) -> str:
    """Formats a byte count for human-readable errors."""
    step = 1024.0
    value = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < step:
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= step
    return f"{value:.1f} PB"


# ---------------------------------------------------------------------------
# Filesystem mounting with real error reporting
# ---------------------------------------------------------------------------

def _walk_all_filesystems(img_info,
                          include_deleted: bool,
                          source: str) -> Generator:
    """
    Opens every allocated partition on img_info and
    walks it, falling back to a whole-disk filesystem.

    Unlike the previous implementation this does NOT
    swallow mount failures. Failures are collected and,
    if no filesystem could be opened at all, raised as
    a RuntimeError carrying the real TSK diagnostics.

    A partition that opens but yields no files is a
    legitimate empty volume and is not an error.
    """
    errors = []
    mounted = 0

    # Pass 1 - allocated partitions
    try:
        volume = pytsk3.Volume_Info(img_info)
        for part in volume:
            if part.flags != pytsk3.TSK_VS_PART_FLAG_ALLOC:
                continue
            offset = part.start * 512
            try:
                fs = pytsk3.FS_Info(img_info, offset=offset)
            except Exception as e:
                errors.append(
                    f"partition {part.addr} at offset {offset} "
                    f"({part.desc}): {e}")
                continue

            mounted += 1
            print(f"[FORENSIC] Mounted {part.desc} at offset {offset}")
            try:
                yield from walk_filesystem(
                    img_info, fs,
                    include_deleted=include_deleted)
            finally:
                try:
                    fs.close()
                except Exception:
                    pass
    except Exception as e:
        errors.append(f"volume enumeration: {e}")

    # Pass 2 - whole-disk filesystem (no partition table)
    if mounted == 0:
        try:
            fs = pytsk3.FS_Info(img_info)
            mounted += 1
            print("[FORENSIC] Mounted whole-disk filesystem "
                  f"({fs.info.ftype})")
            try:
                yield from walk_filesystem(
                    img_info, fs,
                    include_deleted=include_deleted)
            finally:
                try:
                    fs.close()
                except Exception:
                    pass
        except Exception as e:
            errors.append(f"whole-disk filesystem: {e}")

    if mounted == 0:
        detail = "\n  - ".join(errors) if errors else "no partitions found"
        raise RuntimeError(
            f"Could not open any filesystem in this {source} image. "
            f"The image was readable but contains no mountable "
            f"volume. TSK reported:\n  - {detail}\n"
            f"If the source was a partial copy of a larger disk, "
            f"it must be re-acquired in full - a truncated image "
            f"cannot be walked."
        )


# ---------------------------------------------------------------------------
# E01 ingestion
# ---------------------------------------------------------------------------

def ingest_e01(image_path: str,
               temp_dir: str,
               include_deleted: bool = False) -> Generator:
    """
    Opens an EWF (.E01 and split-segment) image and
    yields file info dicts for all extractable files.
    Requires pyewf and pytsk3.
    """
    if not PYEWF_AVAILABLE:
        raise RuntimeError(
            "pyewf not installed. "
            "Run: pip install pyewf")
    if not PYTSK3_AVAILABLE:
        raise RuntimeError(
            "pytsk3 not installed. "
            "Run: pip install pytsk3")

    # Normalize path to prevent pyewf \./ unnormalized path crashes on Windows
    image_path = os.path.abspath(image_path).replace("\\./", "\\").replace("/./", "/").replace("\\.\\", "\\")
    filenames = pyewf.glob(image_path)
    if not filenames:
        raise RuntimeError(
            f"No EWF segments found for {os.path.basename(image_path)}. "
            f"A split EWF image needs all its segments "
            f"(.E01/.E02 or .001/.002) uploaded together."
        )
    ewf_handle = pyewf.handle()
    ewf_handle.open(filenames)

    try:
        img_info = EWFImageInfo(ewf_handle)
        yield from _walk_all_filesystems(
            img_info, include_deleted, "EWF")
    finally:
        ewf_handle.close()


# ---------------------------------------------------------------------------
# Raw image ingestion (.dd / .img / .raw / .001)
# ---------------------------------------------------------------------------

def ingest_raw(image_path: str,
               temp_dir: str,
               include_deleted: bool = False) -> Generator:
    """
    Opens a raw (.dd / .img / .raw / .001) image.
    Yields file info dicts.
    """
    if not PYTSK3_AVAILABLE:
        raise RuntimeError(
            "pytsk3 not installed.")

    # Pre-flight: refuse to pretend a partial image is fine.
    report = inspect_raw_image(image_path)
    if report["truncated"]:
        print(f"[FORENSIC] WARNING: {report['summary']}")
        print("[FORENSIC] Attempting partial recovery anyway - "
              "results will be incomplete.")

    img_info = pytsk3.Img_Info(image_path)

    try:
        yield from _walk_all_filesystems(
            img_info, include_deleted, "raw")
    finally:
        try:
            img_info.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Per-file content extraction
# ---------------------------------------------------------------------------

def extract_file_content(
        file_entry: dict,
        temp_dir: str,
        extracted_base_dir: str = None) -> dict:
    """
    Reads file bytes from disk image entry
    and extracts text, metadata, GPS coords,
    Shannon entropy, and optionally saves
    the raw file to disk for browser viewing.
    Returns enriched dict.
    """
    try:
        entry = file_entry["entry"]
        size = file_entry["size"]

        # Read file bytes.
        #
        # The entry the walker yields is ALREADY a pytsk3.File -- it exposes
        # read_random() directly. This called entry.as_file(), which does not
        # exist on the object pytsk3 hands back, so EVERY file raised
        # AttributeError, the handler below turned it into empty text, and the
        # job finished "Completed - 0 artifacts" with the evidence marked
        # Indexed. The investigator would have concluded the drive was clean.
        #
        # Verified against pytsk3 20260715: dir() on the yielded entry is
        # ['as_directory', 'current_attr', 'info', 'max_attr', 'read_random'].
        # No as_file(). There is nothing to unwrap.
        data = entry.read_random(0, size)

        # A short read means the declared size does not match what the
        # filesystem returned -- a truncated image, or a cluster chain that runs
        # past the end of the volume. Truncating silently would store a file
        # whose bytes are not the file, and the SHA-256 would be computed over
        # the short read, so the artifact would verify against a hash of
        # itself while containing evidence that was never recovered.
        if len(data) < size:
            raise IOError(
                f"short read: filesystem declared {size:,} B for "
                f"{file_entry.get('internal_path') or file_entry.get('filename')}"
                f" but only {len(data):,} B could be read -- the image is "
                f"truncated or the cluster chain runs past the end of the "
                f"volume. Refusing to store partial evidence as if it were "
                f"complete."
            )

        # Compute artifact hash
        artifact_hash = compute_sha256_bytes(data)

        # Calculate Shannon entropy before text extraction
        entropy = calculate_shannon_entropy(data)
        is_high = entropy >= HIGH_ENTROPY_THRESHOLD

        # Save file to disk if appropriate
        stored_path = None
        stored_size = 0
        viewable = is_browser_viewable(file_entry["filename"])

        if (extracted_base_dir and
                should_save_file(
                    file_entry["filename"],
                    file_entry["size"])):
            stored_path = get_stored_path(
                extracted_base_dir,
                file_entry["internal_path"]
            )
            success = save_file(data, stored_path)
            if success:
                stored_size = len(data)
            else:
                stored_path = None

        # Extract text. Uniform 3-tuple: (text, extraction_type, metadata).
        text, extraction_type, exif_dict = extract_text_from_bytes(
            data,
            file_entry["filename"],
            temp_dir
        )

        # If very high entropy and no text extracted,
        # mark the type clearly so analysts know.
        if is_high and not text:
            extraction_type = "high_entropy_binary"

        # Extract GPS from exif_dict if present
        gps_lat = exif_dict.get('_gps_lat')
        gps_lon = exif_dict.get('_gps_lon')

        return {
            **file_entry,
            "sha256_hash": artifact_hash,
            "extracted_text": text,
            "extraction_type": extraction_type,
            "data_size": len(data),
            "shannon_entropy": entropy,
            "is_high_entropy": is_high,
            "gps_latitude": gps_lat,
            "gps_longitude": gps_lon,
            "stored_file_path": stored_path,
            "stored_file_size": stored_size,
            "is_viewable": viewable
        }
    except Exception as e:
        # A per-file I/O failure must NOT be laundered into "no text".
        #
        # Returning {"extracted_text": ""} here is B10's exact shape in the
        # forensic path: the caller does `if not enriched.get("extracted_text"):
        # continue`, so a failure is indistinguishable from a genuinely empty
        # file. When every file failed, the job reported "Completed - 0
        # artifacts" and the evidence was marked Indexed -- which reads to an
        # investigator as "the drive was clean". That is the exculpatory
        # direction, and it is the one that matters most.
        #
        # I/O problems (short read, unreadable cluster, volume damage) raise so
        # the per-file handler in _run_forensic_with_progress can count them and
        # the pipeline can refuse to report success. Genuine content problems --
        # a binary with no extractable text -- are NOT errors and still return
        # empty text.
        if isinstance(e, (IOError, OSError)):
            raise
        return {
            **file_entry,
            "sha256_hash": "",
            "extracted_text": "",
            "extraction_type": "error",
            "shannon_entropy": None,
            "is_high_entropy": False,
            "gps_latitude": None,
            "gps_longitude": None,
            "stored_file_path": None,
            "stored_file_size": 0,
            "is_viewable": False,
            "error": str(e)
        }
