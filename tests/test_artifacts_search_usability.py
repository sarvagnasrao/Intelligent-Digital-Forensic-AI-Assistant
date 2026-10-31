"""Search controls should accurately describe the case inventory and dates."""

from datetime import date

from PySide6.QtCore import QDate

from app.ui.base import CaseContext
from app.ui.pages.artifacts_search_page import ArtifactsSearchPage


class EmptySearchService:
    def list_case_evidence(self, case_id):
        return []

    def list_case_artifacts(self, *args, **kwargs):
        return []


def test_custom_dates_allow_old_and_future_evidence(qt_app):
    page = ArtifactsSearchPage()
    page.date_preset.setCurrentIndex(page.date_preset.findData("custom"))
    page.date_from.setDate(QDate(1985, 1, 2))
    page.date_to.setDate(QDate(2100, 3, 4))
    assert page._date_range() == (date(1985, 1, 2), date(2100, 3, 4))
    assert "creation date" in page.date_preset.toolTip()
    page.close()


def test_inventory_summary_identifies_filtered_results(qt_app):
    page = ArtifactsSearchPage()
    page.set_search_service(EmptySearchService())
    page.set_case_context(CaseContext(1, "CASE-1", "Case", "open", "normal", "Tester"))
    assert page.result_summary.text() == "0 artifact(s) in this case"
    page.type_filter.setCurrentIndex(1)
    page._load_case_artifacts()
    assert page.result_summary.text() == "0 artifact(s) matching filters"
    page._show_all_artifacts()
    assert page.result_summary.text() == "0 artifact(s) in this case"
    page.close()
