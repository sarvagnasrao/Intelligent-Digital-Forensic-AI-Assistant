"""Report controls reflow without losing selection or table data."""
from types import SimpleNamespace

from PySide6.QtWidgets import QBoxLayout


def test_reports_reflow_and_selection(qt_app):
    from app.ui.pages.reports_page import ReportsPage
    from app.ui.theme.manager import build_qss

    page = ReportsPage()
    page.setStyleSheet(build_qss(theme="dark"))
    report = SimpleNamespace(
        report_id="RPT-001", title="Synthetic report", status=SimpleNamespace(value="completed"),
        file_size_bytes=1024, generated_at=None, error_message=None,
        included_sections_json='{"template_name": "Synthetic template"}',
    )
    page.table_model.populate([report])
    page.resize(900, 700)
    page.show()
    qt_app.processEvents()
    page.table_view.selectRow(0)
    assert page.open_btn.isEnabled() and page.export_btn.isEnabled()

    for width, header_direction, action_direction in [
        (450, QBoxLayout.Direction.TopToBottom, QBoxLayout.Direction.LeftToRight),
        (320, QBoxLayout.Direction.TopToBottom, QBoxLayout.Direction.TopToBottom),
        (900, QBoxLayout.Direction.LeftToRight, QBoxLayout.Direction.LeftToRight),
    ]:
        page.resize(width, 700)
        qt_app.processEvents()
        assert page.width() == width
        assert page.header_row.direction() == header_direction
        assert page.header_actions.direction() == action_direction
        assert page.btn_row.direction() == action_direction
        for button in (page.templates_btn, page.generate_btn, page.open_btn, page.export_btn):
            assert button.isVisible()
            assert 0 <= button.mapTo(page, button.rect().topLeft()).x()
            assert button.mapTo(page, button.rect().topRight()).x() < width
        assert page.table_model.item(0, 0).text() == "RPT-001"
        assert page.open_btn.isEnabled() and page.export_btn.isEnabled()

    page.table_view.clearSelection()
    assert not page.open_btn.isEnabled() and not page.export_btn.isEnabled()
    page.close()
    page.deleteLater()
