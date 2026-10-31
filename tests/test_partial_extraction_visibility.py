"""Partial extraction is distinct from a complete read failure."""
import json
from types import SimpleNamespace


def test_coverage_classifies_partial_before_warning():
    from app.examination.service import extraction_coverage

    counts = extraction_coverage([
        {"extraction_status": "partial", "read_error": "damaged part", "content_text": "recovered"},
        {"extraction_status": "partial"},
        {"extraction_status": "error", "read_error": "unreadable"},
        {"content_text": "complete"},
    ])
    assert counts == {"total": 4, "text": 1, "deleted": 0, "read_errors": 1, "partial": 2, "unsupported_or_no_text": 0, "no_text": 0}


def test_detail_labels_partial_warning(qt_app):
    from app.ui.pages.artifacts_search_page import ArtifactDetailPane

    artifact = SimpleNamespace(
        artifact_type="file", name="damaged.docx", artifact_id="ART-1", evidence=None,
        source_path="/damaged.docx", source_size=100, index_status="not_indexed",
        metadata_json=json.dumps({"extraction_status": "partial", "read_error": "damaged part"}),
        content_hash=None, created_time=None, content_text="recovered",
    )
    pane = ArtifactDetailPane()
    pane.set_artifact(artifact)
    text = pane.metadata_label.text()
    assert "Partial extraction" in text
    assert "Extraction warning: damaged part" in text
    assert "Read error:" not in text
