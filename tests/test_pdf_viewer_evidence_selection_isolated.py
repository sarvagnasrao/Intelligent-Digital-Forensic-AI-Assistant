"""The PDF viewer must not mistake an evidence container for its artifact."""
from types import SimpleNamespace

import pytest


@pytest.mark.parametrize("container_name,inode", [("image.dd", 42), ("image.pdf", 42)])
def test_embedded_pdf_shows_artifact_text_not_container(tmp_path, monkeypatch, container_name, inode):
    from app.ui.pages import artifacts_search_page as page

    container = tmp_path / container_name
    container.write_bytes(b"evidence container")
    artifact = SimpleNamespace(
        name="selected.pdf", extension=".pdf", source_offset=inode,
        content_text="selected artifact text",
        evidence=SimpleNamespace(stored_path=str(container), source_path=None),
    )
    text = SimpleNamespace(setPlainText=lambda value: shown.append(value))
    shown = []
    widgets = []
    dialog = SimpleNamespace(
        _artifact=artifact, _query="", text_view=text,
        viewer_stack=SimpleNamespace(addWidget=widgets.append),
    )
    monkeypatch.setattr(page, "QPdfView", lambda *_: pytest.fail("container opened as PDF"))

    page.ArtifactDocumentDialog._load_document(dialog)

    assert widgets == [text]
    assert "selected artifact text" in shown[0]
    assert container.read_bytes() == b"evidence container"
