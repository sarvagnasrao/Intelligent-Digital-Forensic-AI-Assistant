"""The artifact detail pane makes extraction limitations visible."""
from __future__ import annotations

import json
from types import SimpleNamespace


def test_artifact_detail_shows_unsupported_extraction_status(qt_app):
    from app.ui.pages.artifacts_search_page import ArtifactDetailPane

    artifact = SimpleNamespace(
        artifact_type="file",
        name="scan.pdf",
        artifact_id="ART-0001-0001",
        evidence=None,
        source_path="/documents/scan.pdf",
        source_size=2048,
        index_status="not_indexed",
        metadata_json=json.dumps({
            "extraction_status": "unsupported_or_no_text",
            "content_truncated": False,
            "read_error": None,
        }),
        content_hash="abc123",
        created_time=None,
        content_text=None,
    )
    pane = ArtifactDetailPane()

    pane.set_artifact(artifact)

    assert "No extracted text" in pane.metadata_label.text()
    assert "scan.pdf" in pane.metadata_label.text()


def test_artifact_detail_shows_read_error_and_partial_content(qt_app):
    from app.ui.pages.artifacts_search_page import ArtifactDetailPane

    artifact = SimpleNamespace(
        artifact_type="file",
        name="broken.log",
        artifact_id="ART-0001-0002",
        evidence=None,
        source_path="/broken.log",
        source_size=12,
        index_status="not_indexed",
        metadata_json=json.dumps({
            "extraction_status": "error",
            "content_truncated": True,
            "read_error": "I/O failure",
        }),
        content_hash=None,
        created_time=None,
        content_text="partial",
    )
    pane = ArtifactDetailPane()

    pane.set_artifact(artifact)

    assert "partial content" in pane.metadata_label.text()
    assert "I/O failure" in pane.metadata_label.text()
