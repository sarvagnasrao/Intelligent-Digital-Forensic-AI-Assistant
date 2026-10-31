"""HTML character references should not hide source-backed email leads."""

from email.message import EmailMessage

from app.analysis.extractors import extract_entities
from app.artifacts.models import EntityType
from worker.main import extract_text_content


def test_encoded_html_leads_survive_mime_extraction_without_reading_attachment():
    message = EmailMessage()
    message.set_content("Ordinary plain alternative")
    message.add_alternative(
        '<p>Contact analyst&#64;example&#46;test</p>'
        '<a href="https://leads&#46;test/case">case</a>', subtype="html"
    )
    message.add_attachment(
        b"hidden&#64;example.test", maintype="text", subtype="html", filename="secret.html"
    )
    text = extract_text_content(message.as_bytes(), None, ".eml")
    leads = extract_entities(text)
    assert any(
        e.entity_type == EntityType.EMAIL and e.value == "analyst@example.test" for e in leads
    )
    assert any(
        e.entity_type == EntityType.URL and e.value == "https://leads.test/case" for e in leads
    )
    assert all(text[e.start:e.end] == e.value for e in leads)
    assert "analyst&#64;example&#46;test" in text
    assert "hidden" not in text
