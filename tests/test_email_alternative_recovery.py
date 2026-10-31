from email.message import EmailMessage

from worker.email_extraction import extract_email_text


def test_empty_plain_alternative_does_not_hide_html():
    message = EmailMessage()
    message.set_content("   ")
    message.add_alternative("<p>Important evidence</p>", subtype="html")

    assert "Important evidence" in extract_email_text(message.as_bytes())


def test_attached_plain_alternative_does_not_hide_html():
    message = EmailMessage()
    message.make_alternative()
    attachment = EmailMessage()
    attachment.set_content("secret attachment")
    attachment.add_header("Content-Disposition", "attachment", filename="secret.txt")
    html = EmailMessage()
    html.set_content("<p>Actual body</p>", subtype="html")
    message.attach(attachment)
    message.attach(html)

    text = extract_email_text(message.as_bytes())
    assert "Actual body" in text
    assert "secret attachment" not in text


def test_distinct_plain_and_html_alternatives_are_retained():
    message = EmailMessage()
    message.set_content("Plain evidence")
    message.add_alternative("<p>HTML duplicate</p>", subtype="html")

    text = extract_email_text(message.as_bytes())
    assert "Plain evidence" in text
    assert "HTML duplicate" in text
    assert "[Alternative 1: text/plain]" in text
    assert "[Alternative 2: text/html]" in text
