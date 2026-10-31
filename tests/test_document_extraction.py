"""Tests for standalone evidence document extraction."""

from io import BytesIO

from reportlab.pdfgen import canvas

from worker.document_extraction import extract_pdf_text


def make_pdf(*pages: str) -> bytes:
    output = BytesIO()
    pdf = canvas.Canvas(output)
    for text in pages:
        if text:
            pdf.drawString(72, 720, text)
        pdf.showPage()
    pdf.save()
    return output.getvalue()


def test_pdf_text_in_page_order_and_limit():
    data = make_pdf("First evidence page", "Second evidence page")
    text = extract_pdf_text(data)
    assert text is not None
    assert text.index("First evidence page") < text.index("Second evidence page")
    assert extract_pdf_text(data, 10) == text[:10]
    assert extract_pdf_text(data, 0) is None


def test_invalid_and_empty_pdf_have_no_text():
    assert extract_pdf_text(b"not a pdf") is None
    assert extract_pdf_text(make_pdf("")) is None


def test_password_protected_pdf_has_no_text():
    from reportlab.lib.pdfencrypt import StandardEncryption

    output = BytesIO()
    pdf = canvas.Canvas(output, encrypt=StandardEncryption("secret"))
    pdf.drawString(72, 720, "Private evidence")
    pdf.save()
    assert extract_pdf_text(output.getvalue()) is None
