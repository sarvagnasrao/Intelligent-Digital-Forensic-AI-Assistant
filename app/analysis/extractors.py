"""Deterministic entity extraction.

Everything in here is a regular expression or a validator, so the result is the
same on every run and on every machine. That matters twice: a forensic finding
has to be reproducible, and the local model (``phi3:mini``) invents people and
organisations when asked to do free-form NER. Structured values are therefore
extracted exactly here, and the model is only ever asked about names, companies
and places, with its answer checked against the source text.

Two rules keep the output usable:

* **One match per span.** A URL contains a hostname and often a path; an email
  contains a domain. When two patterns match overlapping text the higher
  priority pattern wins, so the same characters are not reported twice as
  unrelated things.
* **One row per value per artifact.** The same address mentioned fifty times is
  one entity for that file, with the first span kept.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.artifacts.models import EntityType

# Order matters: the first extractor to claim a span owns it.
#   1. URLs and e-mail addresses contain slashes, dots and hex-looking runs.
#   2. Crypto addresses and digests are hex runs, so they must beat MAC/IP.
#   3. Files paths and names come last among the structured patterns.
EXTRACTOR_PRIORITY: tuple[str, ...] = (
    "url",
    "email",
    "crypto",
    "hash",
    "ip",
    "mac",
    "phone",
    "file_path",
    "username",
    "device_id",
    "timestamp",
)

# Confidence for a pattern that cannot be wrong about its own syntax. Values
# below mean "the shape matched but the semantics were inferred" (usernames and
# device ids come from key=value context, for example).
CONFIDENCE_EXACT = 1.0
CONFIDENCE_CONTEXT = 0.8

MAX_ENTITY_VALUE = 512
MAX_ENTITIES_PER_ARTIFACT = 200

_URL_RE = re.compile(
    r"\b(?:https?|ftp)://[^\s<>\"'\]\)\}]+"
    r"|\bwww\.[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?:/[^\s<>\"'\]\)\}]*)?",
    re.IGNORECASE,
)
_EMAIL_RE = re.compile(
    r"(?<![\w.+-])([A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,})(?![\w-])"
)
_BTC_RE = re.compile(r"\b(?:bc1[a-zA-HJ-NP-Z0-9]{25,62}|[13][a-km-zA-HJ-NP-Z1-9]{25,34})\b")
_ETH_RE = re.compile(r"\b0x[a-fA-F0-9]{40}\b")
_HASH_RE = re.compile(r"\b[a-fA-F0-9]{32}\b|\b[a-fA-F0-9]{40}\b|\b[a-fA-F0-9]{64}\b")
_IPV4_RE = re.compile(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?!\w)(?!\.\d)")
_IPV6_RE = re.compile(r"(?<![\w:])(?:[A-Fa-f0-9]{1,4}:){7}[A-Fa-f0-9]{1,4}(?![\w:])")
_MAC_RE = re.compile(r"\b(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}\b")
_PHONE_CANDIDATE_RE = re.compile(
    r"(?<![\w+])(?:\+\d{1,4}[\d\s().\-]{0,18}\d"
    r"|\(?\d{2,5}\)?[\s.\-]\d[\d\s().\-]{0,16}\d)(?![\w])"
)
_PHONE_SHAPE_DATE = re.compile(
    r"^\d{1,4}\s*[.\-/]\s*\d{1,2}\s*[.\-/]\s*\d{1,4}$"
    r"|^\d{4}\s*[.\-/]\s*\d{4}$"
    r"|^\d+(?:\.\d+){2,}$"
)
_WINDOWS_PATH_RE = re.compile(
    r"\b[A-Za-z]:\\(?:[^\\/:*?\"<>|\r\n]+\\)*[^\\/:*?\"<>|\r\n]*"
    r"|\\\\[A-Za-z0-9._-]+\\[^\\/:*?\"<>|\r\n]+"
)
_POSIX_PATH_RE = re.compile(
    r"(?<![\w:/.])/(?:[A-Za-z0-9._@+ -]+/){2,}[A-Za-z0-9._@+ -]*"
    r"|(?<![\w:/.])/(?:Users|home|etc|var|tmp|opt|usr|root|Windows|Program Files)"
    r"(?:/[^\s/<>:\"|?*\r\n]+)+"
)
_FILENAME_RE = re.compile(
    r"\b[\w][\w .\-]{0,80}\.(?:txt|log|csv|tsv|json|xml|ya?ml|ini|conf|cfg|reg|"
    r"pdf|docx?|xlsx?|pptx?|odt|ods|rtf|md|html?|"
    r"jpe?g|png|gif|bmp|tiff?|heic|webp|svg|"
    r"mp4|avi|mov|mkv|wmv|mp3|wav|flac|ogg|"
    r"zip|rar|7z|tar|gz|bz2|xz|iso|"
    r"exe|dll|sys|bat|cmd|ps1|vbs|jar|apk|"
    r"db|db3|sqlite3?|mdb|pst|ost|mbox|eml|msg|"
    r"lnk|pf|evtx|hiv|dat|bak)\b",
    re.IGNORECASE,
)
_USERNAME_CONTEXT_RE = re.compile(
    r"(?:\buser(?:name)?|\blogin(?:name)?|\baccount|\bowner|\buid|\bsam)\b"
    r"\s*[=:]\s*[\"']?([A-Za-z0-9][A-Za-z0-9._\-]{2,31})",
    re.IGNORECASE,
)
_USERNAME_PATH_RE = re.compile(
    r"(?:\bUsers|/home)[\\/]([A-Za-z0-9][A-Za-z0-9._\-]{2,31})(?:[\\/]|$)"
)
_USERNAME_HANDLE_RE = re.compile(r"(?<![\w@])@([A-Za-z0-9_]{3,30})\b")
_DEVICE_ID_RE = re.compile(
    r"\b(?:device[_\s-]?(?:id|uuid|serial)|serial(?:number|no)?|imei|udid)"
    r"\s*[=:]\s*[\"']?([A-Za-z0-9][A-Za-z0-9._:\-]{5,63})",
    re.IGNORECASE,
)
_ISO_DATE_RE = re.compile(
    r"(?<![\d-])(\d{4})-(\d{2})-(\d{2})"
    r"(?:[T ](\d{2}):(\d{2})(?::(\d{2}))?(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?)?(?![\d-])"
)
_SLASH_DATE_RE = re.compile(
    r"(?<![\d/])(\d{2})/(\d{2})/(\d{4})(?:[ T](\d{2}):(\d{2})(?::(\d{2}))?)?(?![\d/])"
)

# Domains that say nothing about a relationship. Kept short: the rarity filter
# in relationships.py removes the rest based on how common they are per case.
_COMMON_HOSTS = {
    "localhost", "example.com", "example.org", "microsoft.com", "windows.com",
    "google.com", "gstatic.com", "schema.org", "w3.org", "xmlsoap.org",
}


@dataclass
class ExtractedEntity:
    """One entity found in one artifact."""

    entity_type: EntityType
    value: str
    normalized: str
    start: int
    end: int
    extractor: str
    confidence: float = CONFIDENCE_EXACT
    metadata: dict = field(default_factory=dict)

    @property
    def key(self) -> tuple[EntityType, str]:
        return (self.entity_type, self.normalized)


def _clip(value: str) -> str:
    """Trim trailing punctuation and cap the stored length."""
    value = value.strip().strip("\"'`.,;:)]}").strip()
    return value[:MAX_ENTITY_VALUE]


def normalize_value(entity_type: EntityType, value: str) -> str:
    """A comparable form of a value, used for dedupe and relationship keys."""
    text = value.strip()
    if entity_type in (
        EntityType.EMAIL,
        EntityType.URL,
        EntityType.USERNAME,
        EntityType.FILE_PATH,
        EntityType.CRYPTO_ADDRESS,
        EntityType.HASH,
        EntityType.MAC_ADDRESS,
        EntityType.DEVICE_ID,
        EntityType.PERSON,
        EntityType.ORGANIZATION,
        EntityType.LOCATION,
    ):
        lowered = text.lower()
        if entity_type is EntityType.URL:
            lowered = lowered.rstrip("/")
        if entity_type is EntityType.FILE_PATH:
            lowered = lowered.replace("/", "\\")
        if entity_type in (EntityType.PERSON, EntityType.ORGANIZATION, EntityType.LOCATION):
            lowered = re.sub(r"\s+", " ", lowered)
        return lowered[:MAX_ENTITY_VALUE]
    if entity_type is EntityType.PHONE:
        digits = re.sub(r"\D", "", text)
        return ("+" + digits) if text.startswith("+") else digits
    if entity_type is EntityType.IP_ADDRESS:
        return text.lower()
    if entity_type is EntityType.TIMESTAMP:
        return text.replace(" ", "T").lower()
    return text.lower()[:MAX_ENTITY_VALUE]


def _valid_ipv4(value: str) -> bool:
    parts = value.split(".")
    if len(parts) != 4:
        return False
    try:
        numbers = [int(part) for part in parts]
    except ValueError:
        return False
    if any(number > 255 for number in numbers):
        return False
    # 0.0.0.0 and 255.255.255.255 are usually placeholders or masks.
    if numbers == [0, 0, 0, 0] or numbers == [255, 255, 255, 255]:
        return False
    return True


def _valid_phone(value: str) -> bool:
    digits = re.sub(r"\D", "", value)
    if not 7 <= len(digits) <= 15:
        return False
    # A run of one repeated digit is a placeholder, not a number.
    if len(set(digits)) < 4:
        return False
    if "/" in value:
        return False
    if _PHONE_SHAPE_DATE.fullmatch(value.strip()):
        return False
    # A bare run of digits is far more often an id, a size or a timestamp than
    # a telephone number; require the shape a human writes it in.
    return bool(re.search(r"[+\-(). ]", value))


def _low_entropy_hash(value: str) -> bool:
    """Reject placeholder digests such as ``0000…`` or ``aaaa…``."""
    return len(set(value.lower())) < 5


def _valid_date(year: int, month: int, day: int) -> bool:
    if not 1900 <= year <= 2100:
        return False
    try:
        datetime(year, month, day)
    except ValueError:
        return False
    return True


class _SpanSet:
    """Tracks claimed character ranges so one match cannot overlap another."""

    def __init__(self) -> None:
        self._spans: list[tuple[int, int]] = []

    def free(self, start: int, end: int) -> bool:
        return all(end <= s or start >= e for s, e in self._spans)

    def claim(self, start: int, end: int) -> None:
        self._spans.append((start, end))


def _context(text: str, start: int, end: int, width: int = 90) -> str:
    begin = max(0, start - width // 2)
    finish = min(len(text), end + width)
    snippet = text[begin:finish].replace("\r", " ").replace("\n", " ")
    return re.sub(r"\s+", " ", snippet).strip()


def extract_entities(
    text: str,
    *,
    max_entities: int = MAX_ENTITIES_PER_ARTIFACT,
) -> list[ExtractedEntity]:
    """Extract every supported structured entity from ``text``.

    Returns at most ``max_entities`` results, ordered by position so the UI can
    show them in reading order.
    """
    if not text:
        return []

    claimed = _SpanSet()
    found: list[ExtractedEntity] = []

    def add(
        entity_type: EntityType,
        raw_value: str,
        start: int,
        end: int,
        extractor: str,
        confidence: float = CONFIDENCE_EXACT,
        metadata: dict | None = None,
    ) -> None:
        value = _clip(raw_value)
        if not value or len(value) < 3:
            return
        if not claimed.free(start, end):
            return
        claimed.claim(start, end)
        found.append(
            ExtractedEntity(
                entity_type=entity_type,
                value=value,
                normalized=normalize_value(entity_type, value),
                start=start,
                end=end,
                extractor=extractor,
                confidence=confidence,
                metadata=metadata or {},
            )
        )

    # --- URLs ---------------------------------------------------------
    for match in _URL_RE.finditer(text):
        value = match.group(0)
        host = re.sub(r"^(?:https?|ftp)://", "", value, flags=re.IGNORECASE)
        host = host.split("/")[0].split(":")[0].lower()
        if host in _COMMON_HOSTS:
            continue
        add(EntityType.URL, value, match.start(), match.end(), "url")

    # --- e-mail addresses ---------------------------------------------
    for match in _EMAIL_RE.finditer(text):
        add(EntityType.EMAIL, match.group(1), match.start(1), match.end(1), "email")

    # --- wallet addresses ---------------------------------------------
    for match in _BTC_RE.finditer(text):
        add(
            EntityType.CRYPTO_ADDRESS, match.group(0),
            match.start(), match.end(), "crypto", metadata={"chain": "bitcoin"},
        )
    for match in _ETH_RE.finditer(text):
        add(
            EntityType.CRYPTO_ADDRESS, match.group(0),
            match.start(), match.end(), "crypto", metadata={"chain": "ethereum"},
        )

    # --- digests ------------------------------------------------------
    for match in _HASH_RE.finditer(text):
        value = match.group(0)
        if _low_entropy_hash(value):
            continue
        add(EntityType.HASH, value, match.start(), match.end(), "hash")

    # --- addresses ----------------------------------------------------
    for match in _IPV4_RE.finditer(text):
        if _valid_ipv4(match.group(0)):
            add(EntityType.IP_ADDRESS, match.group(0), match.start(), match.end(), "ip")
    for match in _IPV6_RE.finditer(text):
        add(EntityType.IP_ADDRESS, match.group(0), match.start(), match.end(), "ip")

    for match in _MAC_RE.finditer(text):
        add(EntityType.MAC_ADDRESS, match.group(0), match.start(), match.end(), "mac")

    # --- telephone numbers --------------------------------------------
    for match in _PHONE_CANDIDATE_RE.finditer(text):
        value = match.group(0)
        if not _valid_phone(value):
            continue
        add(EntityType.PHONE, value, match.start(), match.end(), "phone")

    # --- timestamps ---------------------------------------------------
    for match in _ISO_DATE_RE.finditer(text):
        year, month, day = int(match.group(1)), int(match.group(2)), int(match.group(3))
        if not _valid_date(year, month, day):
            continue
        add(EntityType.TIMESTAMP, match.group(0), match.start(), match.end(), "timestamp")
    for match in _SLASH_DATE_RE.finditer(text):
        day, month, year = int(match.group(1)), int(match.group(2)), int(match.group(3))
        if not _valid_date(year, month, day):
            continue
        add(EntityType.TIMESTAMP, match.group(0), match.start(), match.end(), "timestamp")

    # --- file paths and names -----------------------------------------
    for match in _WINDOWS_PATH_RE.finditer(text):
        value = match.group(0)
        if len(value) < 4:
            continue
        add(EntityType.FILE_PATH, value, match.start(), match.end(), "file_path")
    for match in _POSIX_PATH_RE.finditer(text):
        add(EntityType.FILE_PATH, match.group(0), match.start(), match.end(), "file_path")
    for match in _FILENAME_RE.finditer(text):
        add(EntityType.FILE_PATH, match.group(0), match.start(), match.end(), "file_name")

    # --- usernames and device ids -------------------------------------
    for match in _USERNAME_CONTEXT_RE.finditer(text):
        add(
            EntityType.USERNAME, match.group(1), match.start(1), match.end(1),
            "username_context", CONFIDENCE_CONTEXT,
        )
    for match in _USERNAME_PATH_RE.finditer(text):
        add(
            EntityType.USERNAME, match.group(1), match.start(1), match.end(1),
            "username_path", CONFIDENCE_CONTEXT,
        )
    for match in _USERNAME_HANDLE_RE.finditer(text):
        add(
            EntityType.USERNAME, "@" + match.group(1), match.start(), match.end(),
            "handle", CONFIDENCE_CONTEXT,
        )
    for match in _DEVICE_ID_RE.finditer(text):
        add(
            EntityType.DEVICE_ID, match.group(1), match.start(1), match.end(1),
            "device_id", CONFIDENCE_CONTEXT,
        )

    # De-duplicate: one row per (type, normalized) with the first span kept.
    unique: dict[tuple[EntityType, str], ExtractedEntity] = {}
    for entity in found:
        unique.setdefault(entity.key, entity)

    results = sorted(unique.values(), key=lambda item: item.start)
    for entity in results:
        entity.metadata.setdefault("snippet", _context(text, entity.start, entity.end))
    return results[:max_entities]


def parse_timestamp(value: str) -> datetime | None:
    """Best-effort parse of an extracted timestamp, in UTC when no zone is given."""
    text = value.strip().replace("Z", "+00:00")
    for candidate in (text, text.replace(" ", "T")):
        try:
            parsed = datetime.fromisoformat(candidate)
        except ValueError:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    for fmt in ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%d/%m/%Y", "%m/%d/%Y"):
        try:
            parsed = datetime.strptime(value.strip(), fmt)
        except ValueError:
            continue
        return parsed.replace(tzinfo=timezone.utc)
    return None


def content_entities_for_artifact(artifact) -> list[ExtractedEntity]:
    """Entities from an artifact's stored text, name and path.

    The name and path are analysed as well as the body: a filename such as
    ``invoice_rahul.sharma@gmail.com.pdf`` is itself evidence, and the path is
    what reveals the account a file was stored under.
    """
    entities: list[ExtractedEntity] = []
    seen: set[tuple[EntityType, str]] = set()

    for field_name in ("name", "source_path", "content_text"):
        text = getattr(artifact, field_name, None) or ""
        if not text:
            continue
        for entity in extract_entities(text, max_entities=MAX_ENTITIES_PER_ARTIFACT):
            if entity.key in seen:
                continue
            seen.add(entity.key)
            # Offsets only make sense relative to the content that was analysed.
            if field_name != "content_text":
                entity.metadata["field"] = field_name
            entities.append(entity)
    return entities
