"""Regression coverage for examination job table row construction."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from app.examination.models import ExaminationOperation, JobStatus
from app.ui.pages.examination_page import JobTableModel


def test_job_without_timestamps_populates_valid_items(qt_app):
    job = SimpleNamespace(
        job_id="job-1",
        evidence_id=7,
        evidence=None,
        operation=ExaminationOperation.FULL_EXAMINATION,
        status=JobStatus.PENDING,
        progress_percent=0,
        started_at=None,
        completed_at=None,
    )
    model = JobTableModel()

    model.populate([job])

    assert model.rowCount() == 1
    assert model.item(0, 7).text() == ""
    assert model.item(0, 8).text() == ""
    assert all(model.item(0, column) is not None for column in range(model.columnCount()))


def test_running_paused_job_is_labeled_in_the_table(qt_app):
    job = SimpleNamespace(
        job_id="job-paused",
        evidence_id=7,
        evidence=None,
        operation=ExaminationOperation.FULL_EXAMINATION,
        status=JobStatus.RUNNING,
        progress_percent=31,
        progress_message="Paused — waiting to resume",
        started_at=None,
        completed_at=None,
    )
    model = JobTableModel()

    model.populate([job])

    assert model.item(0, 3).text() == "paused"
    assert model.item(0, 4).text() == "~31%"


def test_running_cancellation_request_is_visible_in_the_table(qt_app):
    job = SimpleNamespace(
        job_id="job-cancelling",
        evidence_id=7,
        evidence=None,
        operation=ExaminationOperation.FILE_TRAVERSAL,
        status=JobStatus.RUNNING,
        progress_percent=65,
        progress_message="Cancelling — stopping at the next safe checkpoint",
        started_at=None,
        completed_at=None,
    )
    model = JobTableModel()

    model.populate([job])

    assert model.item(0, 3).text() == "cancelling"


def test_running_job_shows_elapsed_time_and_progress_based_eta(qt_app):
    from app.ui.pages.examination_page import _job_time_text

    now = datetime.now(UTC)
    job = SimpleNamespace(
        started_at=now - timedelta(minutes=2),
        completed_at=None,
        status=JobStatus.RUNNING,
        progress_percent=25,
        progress_message="Traversing files",
    )

    assert _job_time_text(job, now) == ("00:02:00", "~00:06:00")


def test_completed_job_shows_final_elapsed_time_without_eta(qt_app):
    from app.ui.pages.examination_page import _job_time_text

    now = datetime.now(UTC)
    job = SimpleNamespace(
        started_at=now - timedelta(seconds=95),
        completed_at=now - timedelta(seconds=5),
        status=JobStatus.COMPLETED,
        progress_percent=100,
        progress_message="Complete",
    )

    assert _job_time_text(job, now) == ("00:01:30", "—")


def test_new_examination_is_attributed_to_the_signed_in_user(qt_app, monkeypatch):
    from PySide6.QtWidgets import QDialog

    from app.evidence.models import EvidenceStatus
    from app.ui.pages.examination_page import ExaminationPage

    signed_in = SimpleNamespace(id=42, username="signed-in")
    verified_hash = SimpleNamespace(
        is_reference=True, verified_at=datetime.now(UTC), match_result=True
    )
    evidence = SimpleNamespace(
        id=7,
        evidence_id="E007",
        name="disk",
        status=EvidenceStatus.EXAMINED,
        hashes=[verified_hash],
    )
    captured = {}
    fake_job = SimpleNamespace(job_id="JOB-1")
    session = SimpleNamespace(commit=lambda: None, rollback=lambda: None)

    def create_job(**kwargs):
        captured.update(kwargs)
        return fake_job

    page = ExaminationPage(nav=SimpleNamespace(get_current_user=lambda: signed_in))
    page.case_context = SimpleNamespace(case_id=1)
    page.evidence_service = SimpleNamespace(
        get_evidence_by_case=lambda _case_id: [evidence]
    )
    page.exam_service = SimpleNamespace(session=session, create_job=create_job)
    page._populate_evidence_combo()
    page.evidence_combo.setCurrentIndex(1)

    monkeypatch.setattr(
        "app.ui.pages.examination_page.NewExamJobDialog.exec",
        lambda self: QDialog.DialogCode.Accepted,
    )
    monkeypatch.setattr(
        "app.ui.pages.examination_page.NewExamJobDialog.get_data",
        lambda self: {
            "evidence_id": 7,
            "operation": ExaminationOperation.FULL_EXAMINATION,
            "parameters": {},
        },
    )
    monkeypatch.setattr(page, "refresh", lambda: None)
    monkeypatch.setattr(page, "_select_job", lambda _job_id: True)
    monkeypatch.setattr(page, "_on_start", lambda: None)

    page._on_new_job()

    assert captured["created_by"] is signed_in
    assert captured["created_by"].id == 42
    page.deleteLater()


def test_multiple_selected_jobs_allow_bulk_delete_but_disable_single_job_actions(qt_app):
    from PySide6.QtCore import QItemSelectionModel

    from app.ui.pages.examination_page import ExaminationPage

    page = ExaminationPage()
    page._jobs = [
        SimpleNamespace(
            id=i, job_id=f"job-{i}", evidence_id=1, evidence=None,
            operation=ExaminationOperation.FULL_EXAMINATION,
            status=JobStatus.COMPLETED, progress_percent=100,
            started_at=None, completed_at=None,
        ) for i in (1, 2)
    ]
    page.jobs_model.populate(page._jobs)
    selection = page.jobs_table.selectionModel()
    selection.blockSignals(True)
    for row in (0, 1):
        selection.select(page.jobs_model.index(row, 0),
                         QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)
    selection.blockSignals(False)
    page._on_job_selected()

    assert len(page._selected_jobs()) == 2
    assert page.delete_job_btn.isEnabled()
    assert not page.start_btn.isEnabled()
    assert not page.pause_btn.isEnabled()
    assert not page.cancel_btn.isEnabled()
    assert "2 jobs selected" in page.results_log.toPlainText()
    page.deleteLater()


def test_evidence_list_shows_verification_state_and_requires_verification(qt_app):
    from app.evidence.models import EvidenceStatus
    from app.ui.pages.examination_page import ExaminationPage

    verified_hash = SimpleNamespace(is_reference=True, verified_at=datetime.now(UTC), match_result=True)
    failed_hash = SimpleNamespace(is_reference=True, verified_at=datetime.now(UTC), match_result=False)
    evidence = [
        SimpleNamespace(id=1, evidence_id="E001", name="Verified disk", status=EvidenceStatus.EXAMINED, hashes=[verified_hash]),
        SimpleNamespace(id=2, evidence_id="E002", name="Failed disk", status=EvidenceStatus.INTEGRITY_FAILED, hashes=[failed_hash]),
        SimpleNamespace(id=3, evidence_id="E003", name="Unverified disk", status=EvidenceStatus.REGISTERED, hashes=[]),
    ]
    page = ExaminationPage()
    page.case_context = SimpleNamespace(case_id=1)
    page.evidence_service = SimpleNamespace(get_evidence_by_case=lambda case_id: evidence)
    page._populate_evidence_combo()

    assert page.evidence_model.rowCount() == 3
    assert page.evidence_model.item(0, 0).text() == "E001"
    assert page.evidence_model.item(0, 2).text() == "Verified"
    assert page.evidence_model.item(1, 2).text() == "Verification failed"
    assert page.evidence_model.item(2, 2).text() == "Verification required"
    page.evidence_table.selectRow(0)
    assert page.evidence_combo.currentData() == 1
    page._update_buttons()
    assert page.new_job_btn.isEnabled()
    page.evidence_table.selectRow(2)
    page._update_buttons()
    assert not page.new_job_btn.isEnabled()
    assert "Verify integrity" in page.selector_hint.text()
    page.deleteLater()


def test_examination_dialog_advanced_controls_fit(qt_app):
    from types import SimpleNamespace

    from app.ui.pages.examination_page import NewExamJobDialog

    evidence = SimpleNamespace(id=1, evidence_id="E007", name="SCHARDT")
    dialog = NewExamJobDialog([evidence], selected_evidence=evidence)
    dialog.resize(620, 640)
    dialog.advanced_toggle.setChecked(True)
    dialog.show()
    qt_app.processEvents()
    assert dialog.form_scroll.horizontalScrollBar().maximum() == 0
    assert dialog.get_data()["evidence_id"] == 1
    assert "max_files" not in dialog.get_data()["parameters"]
    assert not hasattr(dialog, "max_files_spin")
    assert "max_file_size" not in dialog.get_data()["parameters"]
    assert "max_text_chars" not in dialog.get_data()["parameters"]
    dialog.close()
