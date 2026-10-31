"""Extract embedded text from documents without changing evidence files."""


def extract_pdf_text(content: bytes, max_chars: int | None = None, warnings: list[str] | None = None) -> str | None:
    """Return embedded PDF text in page order, or None when unavailable.

    Qt PDF is included in the standard IDFA installation, but is optional in a
    standalone worker. Image-only, encrypted and invalid PDFs yield no text;
    this function does not perform OCR or attempt to bypass passwords.
    """
    if max_chars is not None and max_chars <= 0:
        return None
    try:
        from PySide6.QtCore import QByteArray, QBuffer, QIODevice
        from PySide6.QtPdf import QPdfDocument

        buffer = QBuffer()
        buffer.setData(QByteArray(content))
        if not buffer.open(QIODevice.OpenModeFlag.ReadOnly):
            if warnings is not None:
                warnings.append("PDF buffer could not be opened")
            return None
        try:
            document = QPdfDocument()
            try:
                document.load(buffer)
                if document.status() != QPdfDocument.Status.Ready:
                    if warnings is not None:
                        warnings.append(f"PDF could not be loaded: {document.error()}")
                    return None
                pages: list[str] = []
                length = 0
                for page in range(document.pageCount()):
                    try:
                        text = document.getAllText(page).text().strip()
                    except (RuntimeError, ValueError) as exc:
                        if warnings is not None:
                            warnings.append(f"page {page + 1}: {exc}")
                        continue
                    if not text:
                        continue
                    if max_chars is not None:
                        remaining = max_chars - length - (1 if pages else 0)
                        if remaining <= 0:
                            break
                        text = text[:remaining]
                    pages.append(text)
                    length += len(text) + (1 if len(pages) > 1 else 0)
                    if max_chars is not None and length >= max_chars:
                        break
                return "\n".join(pages) or None
            finally:
                document.close()
        finally:
            buffer.close()
    except (ImportError, RuntimeError, ValueError) as exc:
        if warnings is not None:
            warnings.append(f"PDF extraction failed: {exc}")
        return None
