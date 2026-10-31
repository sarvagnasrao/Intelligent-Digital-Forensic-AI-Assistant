"""Source text stays literal and can be selected for review."""

from PySide6.QtCore import Qt

from app.ui.pages.ai_analysis_page import CitationPanel
from app.ui.pages.findings_page import IdentityHypothesisDialog


def test_citation_panel_displays_html_like_source_text_literally(qt_app):
    panel = CitationPanel()
    panel.set_citations([{
        "name": "<b>evidence</b>",
        "artifact_id": "ART-1",
        "path": "<file://source>",
        "snippet": "<img src=x> literal excerpt",
        "source_number": 2,
    }])
    text = panel.citation_list.toPlainText()
    assert "<b>evidence</b>" in text
    assert "<file://source>" in text
    assert "<img src=x> literal excerpt" in text
    assert "[Source 2]" in text
    panel.deleteLater()


def test_identity_source_summary_is_selectable(qt_app):
    dialog = IdentityHypothesisDialog([])
    assert dialog.source_list.textInteractionFlags() & Qt.TextInteractionFlag.TextSelectableByMouse
    dialog.deleteLater()
