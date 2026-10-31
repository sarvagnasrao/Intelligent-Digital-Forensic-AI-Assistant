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

MAX_TIMEOUT_LIMIT = 86_400


@dataclass(frozen=True)
class ExaminationProfile:
    """One named bundle of examination parameters."""

    key: str
    name: str
    description: str
    deep_extraction: bool


# Every profile inventories all discovered entries, hashes every readable file,
# and retains supported text. The Deep profile adds SQLite cell-value extraction.
PROFILES: dict[str, ExaminationProfile] = {
    "fast": ExaminationProfile(
        key="fast",
        name="Fast (triage)",
        description=(
            "Standard extraction: all discovered entries are inventoried and readable "
            "text is retained. Legacy caps are not enforced."
        ),
        deep_extraction=False,
    ),
    "balanced": ExaminationProfile(
        key="balanced",
        name="Balanced (default)",
        description=(
            "Standard extraction, with the same coverage as Fast. All discovered "
            "entries and readable text are retained."
        ),
        deep_extraction=False,
    ),
    "deep": ExaminationProfile(
        key="deep",
        name="Deep (full pass)",
        description=(
            "Adds SQLite table and row text to standard extraction. Unsupported formats "
            "such as PDFs, scans, and media are inventoried without fabricated text."
        ),
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
        "deep_extraction": profile.deep_extraction,
        "partition_offset": 0,
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
    # Old saved jobs contain throughput knobs which no longer affect evidence
    # coverage. Strip them so future job payloads express the invariant policy.
    for obsolete in (
        "max_files", "max_file_size", "max_text_chars", "include_deleted",
        "skip_media", "hash_large_files",
    ):
        params.pop(obsolete, None)
    params["profile"] = profile_key if profile_key in PROFILES else base["profile"]

    offset = _as_int(params.get("partition_offset", 0), "partition_offset")
    if offset < 0:
        raise ValueError("partition_offset cannot be negative")
    params["partition_offset"] = offset

    timeout = _as_int(params.get("timeout_seconds", 3600), "timeout_seconds")
    if not 30 <= timeout <= MAX_TIMEOUT_LIMIT:
        raise ValueError(f"timeout_seconds must be between 30 and {MAX_TIMEOUT_LIMIT}")
    params["timeout_seconds"] = timeout

    params["deep_extraction"] = _as_bool(params.get("deep_extraction"))

    return params


def parameter_summary(params: dict[str, Any] | None) -> str:
    """One-line human summary, used in the job log and audit details."""
    params = params or {}
    parts = [
        "all discovered entries",
        "full-file hash",
        "all readable text retained",
    ]
    if params.get("deep_extraction"):
        parts.append("deep extraction")
    if int(params.get("partition_offset") or 0):
        parts.append(f"partition offset {int(params['partition_offset'])}")
    profile = str(params.get("profile") or "").strip()
    prefix = f"{get_profile(profile).name}: " if profile in PROFILES else ""
    return prefix + ", ".join(parts)
