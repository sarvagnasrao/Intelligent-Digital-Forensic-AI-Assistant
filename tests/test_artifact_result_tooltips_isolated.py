"""Truncated artifact result values remain accessible with provenance."""

from types import SimpleNamespace


def test_result_tooltip_contains_excerpt_and_source(qt_app):
    from app.ui.pages.artifacts_search_page import ArtifactTableModel

    artifact = SimpleNamespace(
        artifact_id="ART-001", artifact_type="file", name="message.txt",
        source_size=10, evidence=None, evidence_id=1, index_status="indexed",
        created_time=None, source_path="/message.txt", content_hash="abc123",
    )
    model = ArtifactTableModel()
    model.populate([{"artifact": artifact, "snippet": "Distinctive excerpt"}])
    tooltip = model.item(0, 6).toolTip()
    assert "Distinctive excerpt" in tooltip
    assert "ART-001" in tooltip
    assert "/message.txt" in tooltip
