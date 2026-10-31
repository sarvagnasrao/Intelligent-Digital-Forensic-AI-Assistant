"""Encoded contact properties must yield grounded leads, not binary data."""

from app.analysis.extractors import extract_entities
from app.artifacts.models import EntityType
from worker.main import extract_text_content


def test_base64_contact_lead_survives_folding_and_bad_neighbours():
    source = (
        b"BEGIN:VCARD\r\nVERSION:3.0\r\n"
        b"EMAIL;ENCODING=b:Y29udGFjdEBleGFt\r\n cGxlLnRlc3Q=\r\n"
        b"NOTE;ENCODING=BASE64:!!!\r\n"
        b"PHOTO;ENCODING=b:aGlkZGVuQGV4YW1wbGUudGVzdA==\r\n"
        b"X-BINARY;ENCODING=b:aGlkZGVuQGV4YW1wbGUudGVzdA==\r\n"
        b"EMAIL:second@example.test\r\nEND:VCARD\r\n"
    )
    text = extract_text_content(source, None, ".vcf")
    leads = [e for e in extract_entities(text) if e.entity_type == EntityType.EMAIL]
    assert [e.value for e in leads] == ["contact@example.test", "second@example.test"]
    assert all(text[e.start:e.end] == e.value for e in leads)
    assert "hidden@example.test" not in text
