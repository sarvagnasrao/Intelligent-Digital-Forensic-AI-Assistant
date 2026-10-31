"""AI layout responds to a single resize without contacting AI services."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QSplitter, QWidget

from app.ui.pages.ai_analysis_page import AIAnalysisPage


def test_wide_to_narrow_in_one_resize(qt_app, monkeypatch):
    monkeypatch.setattr(AIAnalysisPage, "_refresh_models", lambda self: None)
    page = AIAnalysisPage()
    page.resize(1400, 900)
    page.show()
    qt_app.processEvents()
    assert page._chat_splitter.orientation() == Qt.Orientation.Horizontal

    page.resize(650, 900)
    qt_app.processEvents()
    assert page.width() == 650
    assert page._chat_splitter.orientation() == Qt.Orientation.Vertical
    for control in (page.input_edit, page.model_combo, page.mode_combo, page.send_btn,
                    page.clear_context_btn, page.save_finding_btn, page.citation_panel):
        assert control.isVisible()
        assert control.width() > 0
    page.close()


def test_page_inside_desktop_splitter_resizes_both_directions(qt_app, monkeypatch):
    monkeypatch.setattr(AIAnalysisPage, "_refresh_models", lambda self: None)
    desktop = QSplitter(Qt.Orientation.Horizontal)
    desktop.setHandleWidth(6)
    sidebar = QWidget()
    sidebar.setFixedWidth(200)
    page = AIAnalysisPage()
    desktop.addWidget(sidebar)
    desktop.addWidget(page)
    desktop.resize(1606, 900)
    desktop.show()
    qt_app.processEvents()
    assert page._chat_splitter.orientation() == Qt.Orientation.Horizontal

    desktop.resize(856, 900)
    qt_app.processEvents()
    assert page.width() == 650
    assert page._chat_splitter.orientation() == Qt.Orientation.Vertical
    for control in (page.input_edit, page.model_combo, page.mode_combo, page.send_btn,
                    page.clear_context_btn, page.save_finding_btn, page.citation_panel,
                    page.status_strip.refresh_btn):
        assert control.isVisible()
        top_left = control.mapTo(page, control.rect().topLeft())
        bottom_right = control.mapTo(page, control.rect().bottomRight())
        assert page.rect().contains(top_left)
        assert page.rect().contains(bottom_right)

    desktop.resize(1606, 900)
    qt_app.processEvents()
    assert page._chat_splitter.orientation() == Qt.Orientation.Horizontal
    desktop.close()
