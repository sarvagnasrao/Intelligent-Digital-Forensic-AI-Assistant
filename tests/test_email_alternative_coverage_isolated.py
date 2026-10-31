"""Synthetic messages exercise alternative coverage through worker and analysis."""

from email.message import EmailMessage

from app.analysis.extractors import extract_entities
from app.artifacts.models import EntityType
from worker.main import extract_text_content


def test_distinct_html_lead_is_source_backed_and_attachment_stays_excluded():
    message = EmailMessage()
    message.set_content("Contact plain@example.test")
    message.add_alternative(
        '<p>Contact html@example.test</p><a href="https://lead.test/path">link</a>',
        subtype="html",
    )
    message.add_attachment(
        b"hidden@example.test", maintype="text", subtype="plain", filename="hidden.txt"
    )
    text = extract_text_content(message.as_bytes(), None, ".eml")
    leads = [e for e in extract_entities(text) if e.entity_type == EntityType.EMAIL]
    assert {e.value for e in leads} == {"plain@example.test", "html@example.test"}
    assert all(text[e.start:e.end] == e.value for e in leads)
    assert '[Alternative 2: text/html]' in text
    assert 'href="https://lead.test/path"' in text
    assert 'hidden@example.test' not in text


def test_simple_duplicate_html_is_suppressed_but_attributes_are_not():
    message = EmailMessage()
    message.set_content("Same evidence")
    message.add_alternative("<p>Same evidence</p>", subtype="html")
    message.add_alternative('<p title="extra lead">Same evidence</p>', subtype="html")
    text = extract_text_content(message.as_bytes(), None, ".eml")
    assert "[Alternative 2:" not in text
    assert '[Alternative 3: text/html]' in text
    assert 'title="extra lead"' in text
