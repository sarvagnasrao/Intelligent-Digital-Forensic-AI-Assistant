"""Time formatting helpers.

All ``datetime`` values in the database are stored in UTC. The investigator
works in a local time zone, so timestamps are converted before being shown on
screen. IDFA demo machines run on Indian Standard Time (UTC+05:30), which is
the default here; override ``IDFA_TZ`` (an IANA zone name such as
``Asia/Kolkata`` or ``UTC``) to run elsewhere.

IST is a fixed offset (India does not observe DST), so the default uses a
plain ``timezone`` offset and does not need the optional ``tzdata`` package.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# Indian Standard Time: UTC+05:30, fixed year-round (no DST).
IST = timezone(timedelta(hours=5, minutes=30))

_DEFAULT_TZ_NAME = os.environ.get("IDFA_TZ", "Asia/Kolkata")


def _tz():
    """The configured local time zone.

    Falls back to a fixed IST offset when ``tzdata`` is missing or the named
    zone can't be found, so timestamps render instead of crashing.
    """
    if _DEFAULT_TZ_NAME in {"Asia/Kolkata", "IST", "Asia/Calcutta"}:
        return IST
    if _DEFAULT_TZ_NAME == "UTC":
        return timezone.utc
    try:
        return ZoneInfo(_DEFAULT_TZ_NAME)
    except (ZoneInfoNotFoundError, KeyError, OSError):
        return IST


def to_local(dt: datetime | None) -> datetime | None:
    """Convert a UTC-aware datetime to the configured local time zone.

    Naive datetimes are treated as UTC (they are stored that way). ``None``
    passes through unchanged.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(_tz())


def format_local(dt: datetime | None, fmt: str = "%H:%M:%S") -> str:
    """Format a datetime in the local time zone, or ``""`` when ``None``."""
    local = to_local(dt)
    if local is None:
        return ""
    return local.strftime(fmt)


def format_local_date(dt: datetime | None, fmt: str = "%Y-%m-%d %H:%M") -> str:
    """Format a datetime with date and time in the local time zone."""
    local = to_local(dt)
    if local is None:
        return ""
    return local.strftime(fmt)
