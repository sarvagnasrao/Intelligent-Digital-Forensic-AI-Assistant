"""PDF page failures must not hide text recovered from other pages."""

from types import SimpleNamespace

from PySide6 import QtPdf

from worker.main import describe_file_evidence


def test_pdf_failed_page_preserves_other_pages_and_reports_partial(tmp_path, monkeypatch):
    class Document:
        Status = QtPdf.QPdfDocument.Status

        def load(self, buffer):
            pass

        def status(self):
            return self.Status.Ready

        def pageCount(self):
            return 3

        def getAllText(self, page):
            if page == 1:
                raise RuntimeError("damaged page")
            return SimpleNamespace(text=lambda: ("first lead", "", "last lead")[page])

        def close(self):
            pass

    monkeypatch.setattr(QtPdf, "QPdfDocument", Document)
    evidence = tmp_path / "evidence.pdf"
    evidence.write_bytes(b"isolated synthetic evidence")

    artifact = describe_file_evidence(str(evidence))

    assert artifact["content_text"] == "first lead\nlast lead"
    assert artifact["extraction_status"] == "partial"
    assert "page 2: damaged page" in artifact["read_error"]
    assert artifact["content_hash"] is not None
