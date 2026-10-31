"""Forwarded message headers are source-backed leads, not attachment contents."""

from app.analysis.extractors import extract_entities
from app.artifacts.models import EntityType
from worker.main import extract_text_content


def test_inline_forwarded_message_header_lead_is_discoverable():
    source = (
        b'MIME-Version: 1.0\r\nContent-Type: multipart/mixed; boundary="x"\r\n\r\n'
        b'--x\r\nContent-Type: text/plain\r\n\r\nSee forwarded message.\r\n'
        b'--x\r\nContent-Type: message/rfc822\r\n\r\n'
        b'From: lead@example.test\r\nSubject: Forwarded\r\n\r\nOrdinary body.\r\n'
        b'--x--\r\n'
    )
    text = extract_text_content(source, None, ".eml")
    leads = [e for e in extract_entities(text) if e.entity_type == EntityType.EMAIL]
    assert [e.value for e in leads] == ["lead@example.test"]
    assert text[leads[0].start:leads[0].end] == leads[0].value
