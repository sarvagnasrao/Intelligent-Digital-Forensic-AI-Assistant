"""Visual state regressions that affect investigation workflows."""
from __future__ import annotations

from app.ui.theme.manager import ThemeManager
from app.ui.theme.tokens import Color


def test_workflow_status_follows_live_theme_switch(qt_app):
    from app.ui.pages.overview_page import WorkflowCard

    manager = ThemeManager()
    original = manager.mode
    card = WorkflowCard("Examination", "examination")
    try:
        manager.set_mode("dark")
        card.set_state("not_started", "0/1", "Awaiting examination")
        dark_style = card.status_label.styleSheet()
        manager.set_mode("light")
        assert Color.TEXT_SECONDARY.name() in card.status_label.styleSheet()
        assert card.status_label.styleSheet() != dark_style
        assert card.value_label.text() == "0/1"
    finally:
        card.deleteLater()
        manager.set_mode(original)


def test_artifact_actions_only_appear_with_a_selected_record(qt_app):
    from app.artifacts.models import Artifact, ArtifactType, IndexStatus
    from app.ui.pages.artifacts_search_page import ArtifactDetailPane

    pane = ArtifactDetailPane()
    assert pane.delete_button.isHidden()
    assert pane.expand_button.isHidden()
    artifact = Artifact(
        artifact_id="ART-TEST", name="notes.txt", artifact_type=ArtifactType.DOCUMENT,
        source_path="/notes.txt", content_text="Investigation notes",
        index_status=IndexStatus.NOT_INDEXED,
    )
    pane.set_artifact(artifact)
    assert not pane.delete_button.isHidden()
    assert pane.delete_button.isEnabled()
    assert pane.content_text.toPlainText() == "Investigation notes"
    pane.set_artifact(None)
    assert pane.delete_button.isHidden()
    assert pane.content_text.toPlainText() == ""
    pane.deleteLater()


def test_case_header_keeps_long_identity_within_available_width(qt_app):
    from app.ui.base import CaseHeaderBar

    header = CaseHeaderBar()
    title = "Evidence review for a long investigation title " * 8
    header.set_case_context("CASE-2026-001", title, "on_hold", "high", "Investigator name " * 8)
    header.resize(760, 80)
    header.show()
    qt_app.processEvents()
    assert header.width() == 760
    assert title.strip() in header.case_id_label.text()
    assert title.strip() in header.case_id_label.toolTip()
    assert header.case_id_label.fontMetrics().horizontalAdvance(
        header.case_id_label.text()
    ) > header.case_id_label.width()
    assert header.case_id_label.geometry().right() <= header.case_id_label.parent().width()
    assert "On Hold" in header.case_meta_label.text()
    header.close()
    header.deleteLater()
