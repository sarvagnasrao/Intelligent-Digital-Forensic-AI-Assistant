"""Inline MIME text is evidence even when the sender supplies a filename."""

from app.analysis.extractors import extract_entities
from app.artifacts.models import EntityType
from worker.main import describe_file_evidence


def test_named_inline_body_is_discoverable_but_attachment_is_not(tmp_path):
    evidence = tmp_path / "message.eml"
    evidence.write_bytes(
        b'MIME-Version: 1.0\r\nContent-Type: multipart/mixed; boundary="x"\r\n\r\n'
        b'--x\r\nContent-Type: text/plain; name="body.txt"\r\n'
        b'Content-Disposition: inline; filename="body.txt"\r\n\r\n'
        b'Contact inline-lead@example.test for the account.\r\n'
        b'--x\r\nContent-Type: text/plain\r\n'
        b'Content-Disposition: attachment; filename="attachment.txt"\r\n\r\n'
        b'attachment-only@example.test\r\n--x--\r\n'
    )

    artifact = describe_file_evidence(str(evidence))
    assert artifact["extraction_status"] == "extracted"
    text = artifact["content_text"]
    leads = [e for e in extract_entities(text) if e.entity_type == EntityType.EMAIL]
    assert [e.value for e in leads] == ["inline-lead@example.test"]
    assert text[leads[0].start:leads[0].end] == leads[0].value
