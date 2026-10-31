"""Evidence selection and loading feedback in the examination page."""
from types import SimpleNamespace

from app.evidence.models import EvidenceStatus
from app.ui.pages.examination_page import ExaminationPage


def test_navigation_highlights_evidence_without_exam_service(qt_app, monkeypatch):
    evidence = SimpleNamespace(
        id=7, evidence_id="E007", name="Disk", status=EvidenceStatus.REGISTERED,
        hashes=[],
    )
    page = ExaminationPage()
    page.case_context = SimpleNamespace(case_id=1)
    page.evidence_service = SimpleNamespace(get_evidence_by_case=lambda _: [evidence])
    monkeypatch.setattr(page, "_ensure_services", lambda: None)

    page.start_examination_for(7)

    assert page.evidence_combo.currentData() == 7
    assert [row.row() for row in page.evidence_table.selectionModel().selectedRows()] == [0]
    page.deleteLater()


def test_evidence_load_error_is_not_reported_as_empty_case(qt_app):
    def fail(_case_id):
        raise RuntimeError("database unavailable")

    page = ExaminationPage()
    page.case_context = SimpleNamespace(case_id=1)
    page.evidence_service = SimpleNamespace(get_evidence_by_case=fail)

    page._populate_evidence_combo()

    assert "could not be loaded" in page.selector_hint.text()
    assert "database unavailable" in page.results_log.toPlainText()
    page.evidence_service = SimpleNamespace(get_evidence_by_case=lambda _: [])
    page._populate_evidence_combo()
    assert "No active evidence" in page.selector_hint.text()
    page.deleteLater()
