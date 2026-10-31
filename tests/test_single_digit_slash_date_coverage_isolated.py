"""Synthetic source-backed coverage for non-zero-padded calendar dates."""

from app.analysis.extractors import extract_entities, parse_timestamp
from app.artifacts.models import EntityType
from worker.main import extract_text_content


def test_single_digit_dates_are_source_backed_timeline_candidates():
    raw = b"Events: 1/31/2024 12:34:56; 31/1/2024; invalid 13/32/2024."
    text = extract_text_content(raw, "text/plain", ".txt")
    dates = [e for e in extract_entities(text) if e.entity_type == EntityType.TIMESTAMP]
    assert [e.value for e in dates] == ["1/31/2024 12:34:56", "31/1/2024"]
    assert all(text[e.start:e.end] == e.value for e in dates)
    assert parse_timestamp(dates[0].value).isoformat() == "2024-01-31T12:34:56+00:00"
    assert parse_timestamp(dates[1].value).isoformat() == "2024-01-31T00:00:00+00:00"


def test_single_digit_dates_do_not_match_inside_longer_numeric_tokens():
    text = "111/31/2024 and 1/31/20245 and 1/31/2024/5"
    assert not [e for e in extract_entities(text) if e.entity_type == EntityType.TIMESTAMP]
