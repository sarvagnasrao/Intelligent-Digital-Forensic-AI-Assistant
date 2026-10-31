"""Source inspection and filtering without a running worker or model."""
from datetime import datetime
from types import SimpleNamespace

from app.ui.pages.entities_timeline_page import EntitiesTimelinePage


def test_entity_selection_exposes_copyable_source_and_clears(qt_app):
    page = EntitiesTimelinePage()
    page._entities = [SimpleNamespace(
        artifact=SimpleNamespace(name="chat.txt", artifact_id="ART-1", source_path="/disk/chat.txt"),
        context_snippet="contact alice@example.test",
    )]
    from PySide6.QtGui import QStandardItem

    page.entity_model.appendRow([QStandardItem("email")])
    page.entity_table.selectRow(0)
    text = page.entity_source.toPlainText()
    assert "ART-1" in text and "/disk/chat.txt" in text
    assert "contact alice@example.test" in text
    page.entity_table.clearSelection()
    assert not page.entity_source.toPlainText()
    page.deleteLater()


def test_timeline_filter_finds_source_artifact_id(qt_app):
    page = EntitiesTimelinePage()
    event = SimpleNamespace(
        event_type="created", title="Created", description="/disk/file.txt",
        timestamp=datetime(2024, 1, 1), certainty="high",
        artifact=SimpleNamespace(name="file.txt", artifact_id="ART-123", source_path="/disk/file.txt"),
    )
    page.case_context = SimpleNamespace(case_id=1)
    page.analysis_service = SimpleNamespace(list_timeline=lambda *args, **kwargs: [event])
    page.tl_search.setText("art-123")
    assert page.timeline_model.rowCount() == 1
    page.tl_search.setText("art-999")
    assert page.timeline_model.rowCount() == 0
    page.deleteLater()
