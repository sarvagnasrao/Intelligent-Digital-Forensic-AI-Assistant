"""Offline MIME calendar evidence remains available for lead discovery."""

from app.analysis.extractors import extract_entities
from app.artifacts.models import EntityType
from worker.main import extract_text_content


def test_inline_calendar_leads_are_source_backed_and_attachments_stay_excluded():
    message = (
        b"From: coordinator@example.test\r\n"
        b"Subject: Appointment\r\n"
        b"MIME-Version: 1.0\r\n"
        b'Content-Type: multipart/mixed; boundary="outer"\r\n\r\n'
        b"--outer\r\n"
        b"Content-Type: text/calendar; charset=utf-8; method=REQUEST\r\n"
        b"Content-Transfer-Encoding: quoted-printable\r\n\r\n"
        b"BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\n"
        b"ATTENDEE:mailto:dispatch=40relay.test\r\n"
        b"LOCATION:Call +1 415-555-0138\r\n"
        b"END:VEVENT\r\nEND:VCALENDAR\r\n"
        b"--outer\r\n"
        b"Content-Type: text/calendar\r\n"
        b'Content-Disposition: attachment; filename="private.ics"\r\n\r\n'
        b"ATTENDEE:mailto:excluded@attachment.test\r\n"
        b"--outer--\r\n"
    )
    text = extract_text_content(message, None, ".eml")
    assert "ATTENDEE:mailto:dispatch@relay.test" in text
    assert "excluded@attachment.test" not in text
    leads = extract_entities(text)
    for kind, value in ((EntityType.EMAIL, "dispatch@relay.test"),
                        (EntityType.PHONE, "+1 415-555-0138")):
        match = next(e for e in leads if e.entity_type == kind and e.value == value)
        assert text[match.start:match.end] == value
