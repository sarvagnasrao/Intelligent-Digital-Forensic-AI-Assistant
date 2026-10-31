"""Damaged synthetic contacts must not hide later source-backed leads."""

from app.analysis.extractors import extract_entities
from app.artifacts.models import EntityType
from worker.main import extract_text_content


def test_damaged_soft_break_does_not_turn_outside_text_into_a_contact():
    source = (
        b"BEGIN:VCARD\r\nVERSION:2.1\r\n"
        b"NOTE;ENCODING=QUOTED-PRINTABLE:damaged=\r\n"
        b"END:VCARD\r\nEMAIL:outside@example.test\r\n"
        b"BEGIN:VCARD\r\nVERSION:3.0\r\n"
        b"EMAIL:analyst@example.test\r\nEND:VCARD\r\n"
    )
    text = extract_text_content(source, None, ".vcf")
    leads = [e for e in extract_entities(text) if e.entity_type == EntityType.EMAIL]
    assert [e.value for e in leads] == ["analyst@example.test"]
    assert text[leads[0].start:leads[0].end] == leads[0].value
