"""Report actions reflect whether a report is selected."""

from PySide6.QtGui import QStandardItem
from types import SimpleNamespace


def test_report_actions_follow_selection(qt_app):
    from app.ui.pages.reports_page import ReportsPage

    page = ReportsPage()
    assert not page.open_btn.isEnabled()
    assert not page.export_btn.isEnabled()
    page.table_model.appendRow([QStandardItem("RPT-001") for _ in range(6)])
    page.table_view.selectRow(0)
    assert page.open_btn.isEnabled()
    assert page.export_btn.isEnabled()
    page.table_view.clearSelection()
    assert not page.open_btn.isEnabled()
    assert not page.export_btn.isEnabled()
    page.deleteLater()


def test_report_title_tooltip_preserves_full_text(qt_app):
    from app.ui.pages.reports_page import ReportTableModel

    model = ReportTableModel()
    report = SimpleNamespace(
        report_id="RPT-001", title="A long synthetic report title",
        status=SimpleNamespace(value="completed"), file_size_bytes=1024,
        generated_at=None, error_message=None, included_sections_json=None,
    )
    model.populate([report])
    assert model.item(0, 1).toolTip() == report.title
