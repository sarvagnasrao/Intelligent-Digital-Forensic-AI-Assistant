"""Long account identifiers remain distinct and source-grounded."""

from app.analysis.extractors import extract_entities
from app.artifacts.models import EntityType


def test_long_account_values_are_not_collapsed_to_a_shared_prefix():
    prefix = "accountname" * 3
    texts = [f"account={prefix}X", f"account={prefix}Y"]
    values = []
    for text in texts:
        leads = [e for e in extract_entities(text) if e.entity_type == EntityType.USERNAME]
        assert len(leads) == 1
        lead = leads[0]
        assert text[lead.start:lead.end] == lead.value
        values.append(lead.normalized)
    assert values == [f"{prefix}x", f"{prefix}y"]


def test_account_length_boundary_does_not_invent_a_prefix():
    valid = "a" * 512
    assert any(e.value == valid for e in extract_entities(f"account={valid}"))
    assert not any(
        e.entity_type == EntityType.USERNAME
        for e in extract_entities(f"account={valid}x")
    )
