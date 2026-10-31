from email.message import EmailMessage

from worker.main import extract_text_content


def test_email_decodes_headers_and_body_without_attachment():
    message = EmailMessage()
    message["Subject"] = "Café investigation"
    message["From"] = "analyst@example.org"
    message.set_content("Evidence: naïve résumé", cte="base64")
    message.add_alternative("<p>Duplicate HTML</p>", subtype="html")
    message.add_attachment(b"secret attachment", maintype="text", subtype="plain", filename="secret.txt")

    text = extract_text_content(message.as_bytes(), "message/rfc822", ".eml")

    assert "Café investigation" in text
    assert "analyst@example.org" in text
    assert "Evidence: naïve résumé" in text
    assert "Duplicate HTML" in text
    assert "[Alternative 2: text/html]" in text
    assert "secret attachment" not in text


def test_email_html_only_and_unknown_charset():
    content = (b"Subject: test\r\nContent-Type: text/html; charset=x-unknown\r\n"
               b"Content-Transfer-Encoding: base64\r\n\r\nPHA+RXZpZGVuY2U8L3A+")
    assert "<p>Evidence</p>" in extract_text_content(content, None, ".eml")
