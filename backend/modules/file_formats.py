"""
Single source of truth for which evidence file formats we accept.

Why this module exists
----------------------
The accepted-format list used to be a hand-maintained 31-entry set in
``backend/routers/evidence.py``. It was narrower than what the extraction
cascade could already read, so the upload gate rejected 20 formats that the
pipeline handled perfectly well end to end - including ``.log``, ``.csv``,
``.json`` and ``.xml``, the four an investigator asks for first. The same list
was then copied a second time into the frontend's ``accept`` attribute, so
even fixing the backend would have left the native file picker greying out the
formats the server now accepted.

Format knowledge is inherently spread across three places:

* the **mechanism** - which extensions ``forensic_ingestion`` can actually
  extract text from;
* the **policy** - which of those we choose to let an investigator upload
  directly;
* the **UI** - what the file picker offers.

The first is truth, the second is a decision, and the third should be derived
rather than restated. This module owns the decision, exposes it to the API,
and :func:`unsupported_uploads` reports any gap between the two so a mismatch
is a loud warning instead of a confusing ``400`` (and so a format can never be
advertised in the file picker but rejected by the server).

Deliberately *not* a hard import-time assert. ``forensic_ingestion`` imports
``pdfminer``, ``bs4`` and ``exifread`` at module scope, and this module sits on
the upload path: a hard failure here would take down the whole backend over a
missing optional dependency, which is bug B15 in this repo. The check is
therefore soft at run time and hard in ``tests/verify_file_formats.py``.
"""

import os
import logging

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Format groups
# ---------------------------------------------------------------------------
# Every extension listed here must also be handled by the extraction cascade
# in backend/modules/forensic_ingestion.py. tests/verify_file_formats.py
# enforces that. Adding an extension to one list and not the other is the bug
# this module was written to make impossible to ship.
#
# `icon` is the frontend's per-category icon key; `description` is user-facing
# copy that explains what actually happens to the file, so it lives next to the
# format definitions rather than being restated in the UI and left to drift.

FORMAT_GROUPS = [
    {
        "key": "disk_image",
        "label": "Forensic Disk Images",
        "icon": "Database",
        "description": (
            "Full disk image ingestion via pytsk3 - every file inside the "
            "image is walked and extracted"
        ),
        "extensions": ['.e01', '.001', '.dd', '.raw', '.img'],
    },
    {
        "key": "document",
        "label": "Documents",
        "icon": "FileText",
        "description": (
            "Text layer extracted and fully indexed for search and Q&A"
        ),
        "extensions": ['.pdf', '.rtf'],
    },
    {
        "key": "text",
        "label": "Text & Logs",
        "icon": "FileText",
        "description": (
            "Plain text and log files read directly, with encoding detected "
            "from the byte-order mark so UTF-16 exports are not garbled"
        ),
        "extensions": [
            '.txt', '.log', '.md', '.text',
            '.nfo', '.out', '.err', '.trace', '.dump',
        ],
    },
    {
        "key": "data",
        "label": "Structured Data",
        "icon": "Table",
        "description": (
            "Rows, keys and values are flattened into searchable text; "
            "property lists are parsed natively"
        ),
        "extensions": [
            '.csv', '.tsv', '.json', '.jsonl', '.ndjson',
            '.xml', '.plist', '.mobileconfig',
        ],
    },
    {
        "key": "markup",
        "label": "Web & Markup",
        "icon": "FileText",
        "description": "Tags stripped, visible text and links kept",
        "extensions": ['.html', '.htm', '.xhtml'],
    },
    {
        "key": "config",
        "label": "Configuration",
        "icon": "Settings",
        "description": (
            "Config and secrets files read as text - useful for credential "
            "scanning"
        ),
        "extensions": [
            '.yaml', '.yml', '.ini', '.cfg', '.conf',
            '.config', '.toml', '.properties',
            # Extensionless dotfiles. Listed explicitly because a leading dot
            # reads as a hidden-file marker, so splitext gives these no
            # extension at all; they are matched by name instead.
            '.env', '.envrc', '.netrc', '.pgpass', '.npmrc',
            '.bashrc', '.profile',
            '.gitconfig', '.gitignore',
            '.zsh_history', '.bash_history',
            # Password hashes. A .htpasswd is one of the most direct
            # artefacts a case can turn up.
            '.htaccess', '.htpasswd',
        ],
    },
    {
        "key": "code",
        "label": "Code & Scripts",
        "icon": "FileCode",
        "description": "Source read as text - surfaces hard-coded secrets and C2 strings",
        "extensions": [
            '.py', '.js', '.ts', '.jsx', '.tsx', '.java',
            '.c', '.h', '.cpp', '.hpp', '.cs', '.go',
            '.rb', '.php', '.pl', '.rs', '.lua', '.r',
            '.sh', '.bash', '.bat', '.ps1', '.sql', '.vb',
        ],
    },
    {
        "key": "subtitle",
        "label": "Subtitles & Transcripts",
        "icon": "MessageSquare",
        "description": (
            "Cue timings kept alongside the text, so interview and call "
            "transcripts stay readable"
        ),
        "extensions": ['.srt', '.vtt', '.ass'],
    },
    {
        "key": "office",
        "label": "Spreadsheets & Slides",
        "icon": "Table",
        "description": "Cell data and slide text extracted and indexed",
        "extensions": [
            '.docx', '.doc',
            '.xlsx', '.xls',
            '.pptx', '.ppt',
        ],
    },
    {
        "key": "email",
        "label": "Email",
        "icon": "Mail",
        "description": "Headers, body, sender, recipient and date all extracted",
        "extensions": ['.eml', '.msg'],
    },
    {
        "key": "image",
        "label": "Images",
        "icon": "Image",
        "description": "OCR (text in images) + EXIF metadata (GPS, camera, date)",
        "extensions": [
            '.jpg', '.jpeg', '.png', '.tiff', '.tif',
            '.bmp', '.gif', '.webp',
        ],
    },
    {
        "key": "audio",
        "label": "Audio",
        "icon": "Music",
        "description": "Transcribed via Whisper (local AI) - no cloud required",
        "extensions": [
            '.mp3', '.wav', '.m4a', '.flac', '.ogg',
            '.aac', '.wma', '.aiff',
        ],
    },
    {
        "key": "video",
        "label": "Video",
        "icon": "Video",
        "description": "Metadata extracted + audio track transcribed via Whisper",
        "extensions": [
            '.mp4', '.avi', '.mov', '.mkv', '.wmv',
            '.flv', '.webm', '.m4v',
        ],
    },
    {
        "key": "database",
        "label": "Databases",
        "icon": "Database",
        "description": (
            "SQLite tables read directly; recognised browser profile databases "
            "are decoded into visit history"
        ),
        "extensions": ['.db', '.sqlite', '.sqlite3'],
    },
]

# Extensionless dotfiles that are real forensic artefacts. os.path.splitext
# reports '' for these (".env" is a hidden file, not an extension), so
# normalize_extension() falls back to the basename for exactly this set.
DOTFILE_NAMES = {
    '.env', '.envrc', '.gitignore', '.gitconfig', '.npmrc',
    '.bashrc', '.bash_history', '.zsh_history', '.profile',
    '.htaccess', '.htpasswd', '.netrc', '.pgpass',
}


_EXTENSION_TO_CATEGORY = {
    ext.lower(): group["key"]
    for group in FORMAT_GROUPS
    for ext in group["extensions"]
}

# The set the upload gate checks. Lowercase, always dot-prefixed.
UPLOAD_EXTENSIONS = frozenset(_EXTENSION_TO_CATEGORY)

# Kept for callers that only care about the images; ingestion.py has its own
# copy of this set for the pipeline-dispatch check, and the two are asserted
# equal in tests/verify_file_formats.py.
FORENSIC_IMAGE_EXTENSIONS = frozenset(
    next(g["extensions"] for g in FORMAT_GROUPS
         if g["key"] == "disk_image")
)

# Suffixes appended by log rotation ("app.log.1", "app.log.2"). Dropping them
# is what lets a rotated log ingest as the .log it is, instead of being
# refused for an "extension" of ".1".
_ROTATION_SUFFIXES = {f".{i}" for i in range(0, 30)}


def normalize_extension(filename: str) -> str:
    """
    Returns the lowercase, dot-prefixed extension to classify ``filename`` by.

    Deliberately more forgiving than os.path.splitext, because the two
    filenames that matter most in a forensic timeline are the ones plain
    splitext gets wrong:

    * rotated logs - ``app.log.1`` and ``access.log.12`` have an extension of
      ``.1`` / ``.12`` and would be refused as an unknown type;
    * dotfiles - ``.env`` and ``.bash_history`` have *no* extension at all,
      because a leading dot reads as a hidden-file marker.

    Only the leading segments are considered, and the loop is bounded, so a
    name like ``a.b.c.d.e`` cannot spin.
    """
    if not filename:
        return ""

    name = os.path.basename(str(filename).strip().replace("\\", "/")).lower()
    if not name:
        return ""

    # A dotfile: the whole basename is the format.
    if name in DOTFILE_NAMES:
        return name

    ext = os.path.splitext(name)[1]

    # Peel rotation markers: app.log.1 -> .log, app.log.12 -> .log
    for _ in range(4):
        if ext and ext not in _ROTATION_SUFFIXES:
            break
        name = os.path.splitext(name)[0]
        if not name:
            return ""
        ext = os.path.splitext(name)[1]

    return ext


def is_supported_upload(filename: str) -> bool:
    """True when this filename's format is accepted by the upload gate."""
    return normalize_extension(filename) in UPLOAD_EXTENSIONS


def category_for(filename: str) -> str:
    """
    Returns the group key for a filename, or '' when the format is not
    accepted. Callers that need to know how a file will be *processed* should
    use this rather than testing against the groups themselves.
    """
    return _EXTENSION_TO_CATEGORY.get(normalize_extension(filename), "")


def is_forensic_image(filename: str) -> bool:
    """True for the disk-image extensions, which take the pytsk3 walk path."""
    return normalize_extension(filename) in FORENSIC_IMAGE_EXTENSIONS


def accept_string() -> str:
    """
    Value for an <input type="file" accept="..."> attribute.

    The frontend used to hardcode this list, which is how a format could be
    accepted by the server but hidden by the native file picker. It is now
    served from GET /api/evidence/formats.
    """
    return ",".join(sorted(UPLOAD_EXTENSIONS))


def describe_groups() -> list:
    """
    The group list as the API serves it: sorted, with a normalised
    `extensions` string for display. Used to render the file picker's format
    guide so the guide cannot claim a format the gate would reject.
    """
    described = []
    for group in FORMAT_GROUPS:
        described.append({
            "key": group["key"],
            "label": group["label"],
            "icon": group["icon"],
            "description": group["description"],
            "extensions": group["extensions"],
            "extensions_label": " ".join(group["extensions"]),
        })
    return described


def unsupported_uploads() -> list:
    """
    Extensions the policy accepts that the extraction cascade cannot read.

    Non-empty means a format is advertised in the file picker and accepted by
    the gate, but yields no text - the same silent-success shape as the bugs
    this repo keeps hitting, one level earlier. Empty is the healthy state.
    """
    try:
        from backend.modules import forensic_ingestion as fi
    except Exception as exc:  # pragma: no cover - optional deps missing
        return []

    extractable = (
        fi.TEXT_EXTENSIONS
        | fi.PDF_EXTENSIONS
        | fi.DB_EXTENSIONS
        | fi.IMAGE_EXTENSIONS
        | fi.HTML_EXTENSIONS
        | fi.OFFICE_EXTENSIONS
        | fi.AUDIO_EXTENSIONS
        | fi.VIDEO_EXTENSIONS
        | fi.EMAIL_EXTENSIONS
        | fi.RTF_EXTENSIONS
        | fi.PLIST_EXTENSIONS
        | fi.SUBTITLE_EXTENSIONS
        # Disk images are handled by the pytsk3 walk rather than by
        # extract_text_from_bytes, so they have to be added back here or the
        # five most obviously-supported formats in the product read as
        # unsupported.
        | FORENSIC_IMAGE_EXTENSIONS
    )
    return sorted(UPLOAD_EXTENSIONS - extractable)


def orphan_extractables() -> list:
    """
    Extensions the extraction cascade can read that the policy does not list.

    Not automatically a bug: the in-image walk is allowed to be broader than
    direct upload. Surfaced so a newly added extractor is a deliberate choice
    rather than an accident nobody notices.
    """
    try:
        from backend.modules import forensic_ingestion as fi
    except Exception:  # pragma: no cover - optional deps missing
        return []

    extractable = (
        fi.TEXT_EXTENSIONS
        | fi.PDF_EXTENSIONS
        | fi.DB_EXTENSIONS
        | fi.IMAGE_EXTENSIONS
        | fi.HTML_EXTENSIONS
        | fi.OFFICE_EXTENSIONS
        | fi.AUDIO_EXTENSIONS
        | fi.VIDEO_EXTENSIONS
        | fi.EMAIL_EXTENSIONS
        | fi.RTF_EXTENSIONS
        | fi.PLIST_EXTENSIONS
        | fi.SUBTITLE_EXTENSIONS
        | FORENSIC_IMAGE_EXTENSIONS
    )
    return sorted(extractable - UPLOAD_EXTENSIONS)


def warn_on_mismatch() -> None:
    """
    Logs, once per process, any drift between the accepted formats and what
    the extractor can actually read. Cheap to call on the upload path.
    """
    global _WARNED
    if _WARNED:
        return
    _WARNED = True
    gaps = unsupported_uploads()
    if gaps:
        logger.warning(
            "Accepted evidence formats with no extractor: %s - these upload "
            "but yield no text.", ", ".join(gaps)
        )


_WARNED = False
