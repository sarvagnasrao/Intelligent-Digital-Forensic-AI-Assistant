"""Synthetic address leads: spelling variants, provenance and false positives."""
from app.analysis.extractors import extract_entities
from app.artifacts.models import EntityType


def addresses(text):
    return [item for item in extract_entities(text) if item.entity_type == EntityType.IP_ADDRESS]


def test_ipv6_variants_have_one_key_and_literal_source_spans():
    texts = ["remote 2001:db8::1 connected", "remote 2001:0DB8:0:0:0:0:0:1 connected"]
    leads = [addresses(text)[0] for text in texts]
    assert [item.normalized for item in leads] == ["2001:db8::1"] * 2
    for text, item in zip(texts, leads):
        assert text[item.start:item.end] == item.value
        assert item.value in item.metadata["snippet"]


def test_ipv6_colons_and_invalid_candidates():
    text = "local ::1 and prefix 2001:db8::; placeholders ::; time 12:34:56; invalid 2001:db8:::1"
    leads = addresses(text)
    assert [item.value for item in leads] == ["::1", "2001:db8::"]
    assert all(text[item.start:item.end] == item.value for item in leads)
