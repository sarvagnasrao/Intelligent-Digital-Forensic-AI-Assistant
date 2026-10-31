"""A damaged contact property must not hide the next source-backed lead."""

from app.analysis.extractors import extract_entities
from app.artifacts.models import EntityType
from worker.main import extract_text_content


def test_damaged_quoted_printable_does_not_consume_next_property():
    source = (
        b"BEGIN:VCARD\r\nVERSION:2.1\r\n"
        b"NOTE;ENCODING=QUOTED-PRINTABLE:damaged=\r\n"
        b"EMAIL:alice@example.test\r\nEND:VCARD\r\n"
    )
    text = extract_text_content(source, None, ".vcf")
    assert "EMAIL: alice@example.test" in text
    leads = [e for e in extract_entities(text) if e.entity_type == EntityType.EMAIL]
    assert [e.value for e in leads] == ["alice@example.test"]
    assert text[leads[0].start:leads[0].end] == leads[0].value
