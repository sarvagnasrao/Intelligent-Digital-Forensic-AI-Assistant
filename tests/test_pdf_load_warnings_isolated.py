"""Document-level PDF errors must be distinguishable from empty pages."""

from io import BytesIO

from reportlab.pdfgen import canvas

from worker.document_extraction import extract_pdf_text


def test_invalid_pdf_reports_load_failure():
    warnings = []
    assert extract_pdf_text(b"not a PDF", warnings=warnings) is None
    assert len(warnings) == 1
    assert "PDF could not be loaded" in warnings[0]


def test_empty_pdf_is_not_reported_as_a_failure():
    output = BytesIO()
    pdf = canvas.Canvas(output)
    pdf.showPage()
    pdf.save()
    warnings = []
    assert extract_pdf_text(output.getvalue(), warnings=warnings) is None
    assert warnings == []
