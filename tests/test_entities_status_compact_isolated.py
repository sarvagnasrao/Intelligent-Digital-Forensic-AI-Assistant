"""Compact analysis history and queue controls, with no database or services."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PySide6.QtGui import QFont, QFontDatabase, QStandardItem
from PySide6.QtWidgets import QMessageBox, QWidget

from app.analysis.models import AnalysisJobStatus
from app.ui.pages.entities_timeline_page import EntitiesTimelinePage


@pytest.fixture
def page(qt_app):
    widget = EntitiesTimelinePage()
    yield widget
    widget.close()
    widget.deleteLater()


@pytest.mark.parametrize(("counts", "expected"), [
    ({}, "No analysis jobs"),
    ({"completed": 3}, "Analysis complete · 3 completed"),
    ({"completed": 3, "pending": 2}, "0 running · 2 queued"),
    ({"running": 1}, "1 running · 0 queued"),
    ({"failed": 1}, "Analysis stopped"),
    ({"completed": 3, "interrupted": 1}, "1 stopped"),
])
def test_status_distinguishes_completed_from_pending_queue(page, counts, expected):
    page._queue_counts = counts
    page._on_runner_status("Analysis queue empty")
    assert expected in page.status_label.text()
    assert page.status_detail.isHidden()


def test_paused_and_disabled_remain_visible(page):
    page.runner = SimpleNamespace(paused=True)
    page._queue_counts = {"completed": 2}
    page._on_runner_status("Analysis disabled in settings")
    assert page.status_label.text().startswith("Queue paused")
    assert "2 completed" in page.status_label.text()
    assert page.status_detail.text() == "Analysis disabled in settings"
    assert not page.status_detail.isHidden()


def test_status_includes_existing_result_totals(page):
    page._queue_counts = {"completed": 3}
    page._result_counts = {"entities": 120, "relationships": 8}
    page._sync_analysis_status()
    assert "120 entities · 8 relationships" in page.status_label.text()


@pytest.mark.parametrize("status", [AnalysisJobStatus.PENDING, AnalysisJobStatus.RUNNING])
def test_active_jobs_cannot_be_rerun(page, status):
    page._jobs = [SimpleNamespace(status=status)]
    page.queue_model.appendRow([QStandardItem("ANL-1")])
    page.queue_table.selectRow(0)
    assert not page.retry_btn.isEnabled()
    assert page.cancel_btn.isEnabled()


def test_status_and_filters_leave_space_for_results(page, qt_app):
    from app.ui.theme.manager import build_qss

    for name in ("segoeui.ttf", "segoeuib.ttf"):
        font_path = Path("C:/Windows/Fonts") / name
        if font_path.exists():
            QFontDatabase.addApplicationFont(str(font_path))
    page.setFont(QFont("Segoe UI", 10))
    page.setStyleSheet(build_qss())
    page._queue_counts = {"completed": 3}
    page._sync_analysis_status()
    page.resize(1200, 850)
    page.show()
    qt_app.processEvents()
    status = page.status_label.parentWidget()
    assert status.height() < 160
    assert page.rel_status_filter.y() == page.rel_kind_filter.y() == page.rel_search.y()
    assert page.relationship_stack.height() > 400
    page.resize(640, 850)
    qt_app.processEvents()
    assert page.rel_status_filter.y() == page.rel_kind_filter.y()
    assert page.rel_search.y() > page.rel_kind_filter.y()
    assert page.rel_search.geometry().right() < page.tabs.width()


def test_review_jobs_opens_queue_and_selects_completed(page):
    page._jobs = [SimpleNamespace(status=AnalysisJobStatus.COMPLETED)]
    page.queue_model.appendRow([QStandardItem("ANL-1")])
    page._show_analysis_queue()
    assert page.tabs.currentIndex() == 3
    assert page.retry_btn.isEnabled()
    assert page.retry_btn.text() == "Re-run"


def test_rerun_confirmation_and_actor_permission_are_preserved(page, monkeypatch):
    shell = QWidget()
    actor = SimpleNamespace(id=7)
    shell.get_current_user = lambda: actor
    page.setParent(shell)
    page.case_context = SimpleNamespace(case_id=42)
    job = SimpleNamespace(id=19, job_id="ANL-19", status=AnalysisJobStatus.COMPLETED)
    page._jobs = [job]
    page.queue_model.appendRow([QStandardItem(job.job_id)])
    page.queue_table.selectRow(0)
    session = Mock()
    session.get.return_value = actor
    service = Mock(session=session)
    service.retry.side_effect = PermissionError("Case write access required")
    page.analysis_service = service
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.No)
    page._on_retry()
    service.retry.assert_not_called()
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.Yes)
    warning = Mock()
    monkeypatch.setattr(QMessageBox, "warning", warning)
    page._on_retry()
    session.refresh.assert_called_once_with(actor)
    service.retry.assert_called_once_with(19, 42, actor)
    assert warning.call_args.args[2] == "Case write access required"
    page.setParent(None)
