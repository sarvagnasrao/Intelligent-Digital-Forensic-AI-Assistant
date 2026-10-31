"""Evidence provenance in search results, without accessing investigator data."""
from types import SimpleNamespace

from app.ui.pages.artifacts_search_page import ArtifactDetailPane, ArtifactTableModel


def artifact(evidence):
    return SimpleNamespace(
        artifact_id="ART-1", artifact_type="document", name="report.txt",
        evidence=evidence, source_size=0, index_status="indexed", created_time=None,
        source_path="/report.txt", content_hash=None, metadata_json="{}", content_text="",
    )


def test_duplicate_evidence_names_are_distinguished_in_table_and_details(qt_app):
    first = artifact(SimpleNamespace(evidence_id="EVD-001", name="disk image"))
    second = artifact(SimpleNamespace(evidence_id="EVD-002", name="disk image"))
    model = ArtifactTableModel()
    model.populate([{"artifact": first}, {"artifact": second}])

    assert model.item(0, 3).text() == "EVD-001 — disk image"
    assert model.item(1, 3).text() == "EVD-002 — disk image"
    assert "Evidence: EVD-002 — disk image" in model.item(1, 0).toolTip()

    pane = ArtifactDetailPane()
    pane.set_artifact(second)
    assert "Evidence: EVD-002 — disk image" in pane.metadata_label.text()
    pane.set_artifact(None)
    assert pane.metadata_label.text() == ""


def test_missing_evidence_does_not_expose_internal_key(qt_app):
    item = artifact(None)
    item.evidence_id = 42
    model = ArtifactTableModel()
    model.populate([{"artifact": item}])
    assert model.item(0, 3).text() == "Unknown ID — Unknown evidence"
    pane = ArtifactDetailPane()
    pane.set_artifact(item)
    assert "Evidence: Unknown ID — Unknown evidence" in pane.metadata_label.text()
