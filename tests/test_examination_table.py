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
