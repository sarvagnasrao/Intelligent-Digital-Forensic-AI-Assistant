"""Synthetic vCard evidence must retain leads across combined line folding."""

from app.analysis.extractors import extract_entities
from app.artifacts.models import EntityType
from worker.main import extract_text_content


def test_folded_quoted_printable_email_remains_source_backed():
    source = (
        b"BEGIN:VCARD\r\nVERSION:2.1\r\n"
        b"EMAIL;ENCODING=QUOTED-PRINTABLE:alice=40exa=\r\n"
        b" mple.test\r\nNOTE:unrelated\r\nEND:VCARD\r\n"
    )
    text = extract_text_content(source, None, ".vcf")
    leads = [e for e in extract_entities(text) if e.entity_type == EntityType.EMAIL]
    assert [e.value for e in leads] == ["alice@example.test"]
    assert text[leads[0].start:leads[0].end] == leads[0].value
