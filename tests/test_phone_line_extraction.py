import pytest

from app.analysis.extractors import extract_entities
from app.artifacts.models import EntityType


@pytest.mark.parametrize("separator", ["\n", "\r\n", "\r"])
def test_phone_numbers_on_separate_lines_keep_source_spans(separator):
    text = f"Call +1 415 555 2671{separator}212 555 1234"
    phones = [item for item in extract_entities(text) if item.entity_type == EntityType.PHONE]

    assert [item.value for item in phones] == ["+1 415 555 2671", "212 555 1234"]
    assert all(text[item.start:item.end] == item.value for item in phones)


def test_repeated_phone_on_separate_lines_is_deduplicated():
    text = "+1 415 555 2671\n+1 415 555 2671"
    phones = [item for item in extract_entities(text) if item.entity_type == EntityType.PHONE]

    assert len(phones) == 1
    assert phones[0].value == "+1 415 555 2671"
    assert phones[0].start == 0
