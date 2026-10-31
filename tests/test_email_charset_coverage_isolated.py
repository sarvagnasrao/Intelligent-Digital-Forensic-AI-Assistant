"""Damaged MIME text must not masquerade as complete evidence coverage."""

from app.analysis.extractors import extract_entities
from app.artifacts.models import EntityType
from app.examination.service import extraction_coverage
from worker.main import describe_file_evidence


def test_invalid_mime_body_reports_partial_and_preserves_other_leads(tmp_path):
    source = tmp_path / "message.eml"
    source.write_bytes(
        b"MIME-Version: 1.0\r\n"
        b'Content-Type: multipart/mixed; boundary="case"\r\n\r\n'
        b"--case\r\nContent-Type: text/plain; charset=utf-8\r\n\r\n"
        b"Damaged contact: \xff\xfe\r\n"
        b"--case\r\nContent-Type: text/plain; charset=utf-8\r\n\r\n"
        b"Reply to reliable@relay.test\r\n"
        b"--case--\r\n"
    )

    artifact = describe_file_evidence(str(source))
    assert artifact["extraction_status"] == "partial"
    assert "charset utf-8" in artifact["read_error"]
    text = artifact["content_text"]
    lead = next(e for e in extract_entities(text) if e.entity_type == EntityType.EMAIL)
    assert lead.value == "reliable@relay.test"
    assert text[lead.start:lead.end] == lead.value
    assert extraction_coverage([artifact])["partial"] == 1
