"""Examination presets and parameter validation.

The New Job dialog offers three presets so the common case is one click, plus
an Advanced expander for the exact numbers. Both write the same flat parameter
dictionary, which is what gets stored on the job (``parameters_json``) and sent
to the worker, so a job can always be reproduced exactly.

The worker is a standalone process and does not import this module; it reads the
same keys with the same defaults. Keep the two in step.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

MB = 1024 * 1024

# Compatibility bounds for old clients. Worker treats these as hints only:
# inventory and readable text are never silently stopped by a preset cap.
MAX_FILES_LIMIT = 2_000_000
MAX_FILE_SIZE_MB_LIMIT = 4096
MAX_TEXT_CHARS_LIMIT = 2_000_000
MAX_TIMEOUT_LIMIT = 86_400

HASH_ALGORITHMS = ("sha256", "md5", "sha1")


@dataclass(frozen=True)
class ExaminationProfile:
    """One named bundle of examination parameters."""

    key: str
    name: str
    description: str
    max_files: int
    max_file_size_mb: int
    max_text_chars: int
    include_deleted: bool
    skip_media: bool
    hash_large_files: bool
    deep_extraction: bool

    @property
    def max_file_size_bytes(self) -> int:
        return self.max_file_size_mb * MB


# The legacy caps remain in the request shape for saved-job compatibility but
# are not enforced: every discovered entry is inventoried and readable text is
# retained. The only current profile difference is optional SQLite row text.
PROFILES: dict[str, ExaminationProfile] = {
    "fast": ExaminationProfile(
        key="fast",
        name="Fast (triage)",
        description=(
            "Standard extraction: all discovered entries are inventoried and readable "
            "text is retained. Legacy caps are not enforced."
        ),
        max_files=2_000,
        max_file_size_mb=2,
        max_text_chars=4_000,
        include_deleted=False,
        skip_media=True,
        hash_large_files=False,
        deep_extraction=False,
    ),
    "balanced": ExaminationProfile(
        key="balanced",
        name="Balanced (default)",
        description=(
            "Standard extraction, with the same coverage as Fast. All discovered "
            "entries and readable text are retained."
        ),
        max_files=20_000,
        max_file_size_mb=10,
        max_text_chars=20_000,
        include_deleted=True,
        skip_media=False,
        hash_large_files=True,
        deep_extraction=False,
    ),
    "deep": ExaminationProfile(
        key="deep",
        name="Deep (full pass)",
        description=(
            "Adds SQLite table and row text to standard extraction. Unsupported formats "
            "such as PDFs, scans, and media are inventoried without fabricated text."
        ),
        max_files=200_000,
        max_file_size_mb=50,
        max_text_chars=100_000,
        include_deleted=True,
        skip_media=False,
        hash_large_files=True,
        deep_extraction=True,
    ),
}

DEFAULT_PROFILE = "balanced"


def get_profile(key: str | None) -> ExaminationProfile:
    """Return a profile, falling back to Balanced for an unknown name."""
    return PROFILES.get((key or "").strip().lower(), PROFILES[DEFAULT_PROFILE])


def profile_parameters(key: str | None) -> dict[str, Any]:
    """Return the worker parameter dictionary for a preset."""
    profile = get_profile(key)
    return {
        "profile": profile.key,
        "max_files": profile.max_files,
        "max_file_size": profile.max_file_size_bytes,
        "max_text_chars": profile.max_text_chars,
        "include_deleted": profile.include_deleted,
        "skip_media": profile.skip_media,
        "hash_large_files": profile.hash_large_files,
        "deep_extraction": profile.deep_extraction,
        "partition_offset": 0,
        "hash_algorithms": ["sha256"],
        "timeout_seconds": 3600,
    }


def _as_int(value: Any, name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a number, not true/false")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a whole number") from exc


def _as_bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


def validate_parameters(raw: dict[str, Any] | None) -> dict[str, Any]:
    """Return a complete, bounded parameter dictionary.

    Unknown keys are preserved so a newer caller is not silently stripped by an
    older build, but every known key is coerced to a usable value. Missing keys
    fall back to the Balanced preset.
    """
    base = profile_parameters(DEFAULT_PROFILE)
    if not raw:
        return base

    data = dict(raw)
    profile_key = str(data.get("profile") or "").strip().lower()
    if profile_key in PROFILES:
        # A preset fills anything the caller did not override.
        base = profile_parameters(profile_key)

    params = {**base, **data}
    params["profile"] = profile_key if profile_key in PROFILES else base["profile"]

    max_files = _as_int(params["max_files"], "max_files")
    if not 1 <= max_files <= MAX_FILES_LIMIT:
        raise ValueError(f"max_files must be between 1 and {MAX_FILES_LIMIT:,}")
    params["max_files"] = max_files

    # Older callers send bytes; the dialog sends MB. Accept either: a value
    # below the MB limit is ambiguous, so treat anything under 4096 as MB.
    size = _as_int(params["max_file_size"], "max_file_size")
    if size < MAX_FILE_SIZE_MB_LIMIT:
        size *= MB
    if not MB <= size <= MAX_FILE_SIZE_MB_LIMIT * MB:
        raise ValueError(
            f"max_file_size must be between 1 MB and {MAX_FILE_SIZE_MB_LIMIT} MB"
        )
    params["max_file_size"] = size

    text_chars = _as_int(params["max_text_chars"], "max_text_chars")
    if not 0 <= text_chars <= MAX_TEXT_CHARS_LIMIT:
        raise ValueError(
            f"max_text_chars must be between 0 and {MAX_TEXT_CHARS_LIMIT:,}"
        )
    params["max_text_chars"] = text_chars

    offset = _as_int(params.get("partition_offset", 0), "partition_offset")
    if offset < 0:
        raise ValueError("partition_offset cannot be negative")
    params["partition_offset"] = offset

    timeout = _as_int(params.get("timeout_seconds", 3600), "timeout_seconds")
    if not 30 <= timeout <= MAX_TIMEOUT_LIMIT:
        raise ValueError(f"timeout_seconds must be between 30 and {MAX_TIMEOUT_LIMIT}")
    params["timeout_seconds"] = timeout

    for flag in (
        "include_deleted",
        "skip_media",
        "hash_large_files",
        "deep_extraction",
    ):
        params[flag] = _as_bool(params.get(flag))

    algorithms = params.get("hash_algorithms") or ["sha256"]
    if isinstance(algorithms, str):
        algorithms = [algorithms]
    cleaned = [
        str(name).strip().lower() for name in algorithms
        if str(name).strip().lower() in HASH_ALGORITHMS
    ]
    # SHA-256 is the evidence digest; it is never optional.
    if "sha256" not in cleaned:
        cleaned.insert(0, "sha256")
    params["hash_algorithms"] = cleaned

    return params


def parameter_summary(params: dict[str, Any] | None) -> str:
    """One-line human summary, used in the job log and audit details."""
    params = params or {}
    size_mb = int(params.get("max_file_size", 10 * MB)) / MB
    parts = [
        f"up to {int(params.get('max_files', 20_000)):,} files",
        f"files <= {size_mb:g} MB",
        f"text <= {int(params.get('max_text_chars', 20_000)):,} chars",
    ]
    if params.get("include_deleted"):
        parts.append("deleted included")
    if params.get("skip_media"):
        parts.append("media skipped")
    if params.get("hash_large_files"):
        parts.append("large files hashed")
    if params.get("deep_extraction"):
        parts.append("deep extraction")
    if int(params.get("partition_offset") or 0):
        parts.append(f"partition offset {int(params['partition_offset'])}")
    profile = str(params.get("profile") or "").strip()
    prefix = f"{get_profile(profile).name}: " if profile in PROFILES else ""
    return prefix + ", ".join(parts)
