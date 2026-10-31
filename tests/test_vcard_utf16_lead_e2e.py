"""UTF-16 contact evidence must remain searchable without identity inference."""

import pytest

from app.analysis.extractors import extract_entities
from app.artifacts.models import EntityType
from worker.main import extract_text_content


@pytest.mark.parametrize("encoding", ["utf-16-le", "utf-16-be"])
def test_utf16_contacts_keep_leads_and_quoted_printable(encoding):
    bom = b"\xff\xfe" if encoding == "utf-16-le" else b"\xfe\xff"
    source = bom + (
        "BEGIN:VCARD\r\nVERSION:2.1\r\nFN:Élodie\r\n"
        "EMAIL;ENCODING=QUOTED-PRINTABLE:contact=40example.test\r\n"
        "END:VCARD\r\nBEGIN:VCARD\r\nVERSION:3.0\r\n"
        "EMAIL:other@investigation.test\r\nEND:VCARD\r\n"
    ).encode(encoding)
    text = extract_text_content(source, None, ".vcf")
    assert text is not None
    assert "FN: Élodie" in text
    leads = [e for e in extract_entities(text) if e.entity_type == EntityType.EMAIL]
    assert [e.value for e in leads] == ["contact@example.test", "other@investigation.test"]
    assert all(text[e.start:e.end] == e.value for e in leads)
