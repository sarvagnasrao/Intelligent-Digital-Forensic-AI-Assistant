from types import SimpleNamespace

from app.analysis.extractors import extract_entities, normalize_value
from app.analysis.relationships import _key, _relationship_value
from app.artifacts.models import EntityType


def test_bitcoin_case_variants_remain_distinct_source_backed_leads():
    first = "1BoatSLRHtKNngkdXEeobR76b53LETtpyT"
    second = "1boatSLRHtKNngkdXEeobR76b53LETtpyT"
    text = f"{first} and {second} and {first}"
    leads = [e for e in extract_entities(text) if e.entity_type is EntityType.CRYPTO_ADDRESS]
    assert [e.value for e in leads] == [first, second]
    assert len({e.normalized for e in leads}) == 2
    assert all(text[e.start:e.end] == e.value for e in leads)
    keys = {
        _key(SimpleNamespace(entity_type=e.entity_type, value=e.value, normalized_value=e.normalized))
        for e in leads
    }
    assert len(keys) == 2
    assert all(_relationship_value(kind, value) == value for kind, value in keys)


def test_ethereum_hex_case_variants_still_compare_equal():
    first = "0xAbCdEf1234567890AbCdEf1234567890AbCdEf12"
    second = "0xabcdef1234567890abcdef1234567890abcdef12"
    assert normalize_value(EntityType.CRYPTO_ADDRESS, first) == normalize_value(
        EntityType.CRYPTO_ADDRESS, second
    )
