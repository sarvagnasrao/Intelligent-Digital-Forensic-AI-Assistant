"""Examination deletion must use the signed-in investigator, not an admin."""
from types import SimpleNamespace
from unittest.mock import Mock

from PySide6.QtWidgets import QMessageBox

from app.auth.models import UserRole
from app.examination.models import JobStatus
from app.ui.pages.examination_page import ExaminationPage


def test_batch_deletion_passes_signed_in_actor_to_worker(qt_app, monkeypatch):
    from app.ui import deletion_worker, qt_threads
    from app.ui.pages import examination_page

    user = SimpleNamespace(id=42, role=UserRole.ADMIN)
    page = ExaminationPage(nav=SimpleNamespace(get_current_user=lambda: user))
    page.exam_service = object()
    page._selected_jobs = lambda: [
        SimpleNamespace(id=7, status=JobStatus.COMPLETED),
        SimpleNamespace(id=8, status=JobStatus.COMPLETED),
    ]
    worker = Mock()
    factory = Mock(return_value=worker)
    monkeypatch.setattr(deletion_worker, "DeletionWorker", factory)
    monkeypatch.setattr(qt_threads, "track", lambda _worker: None)
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    progress = Mock()
    monkeypatch.setattr(examination_page, "QProgressDialog", lambda *args: progress)

    page._on_delete_job()

    factory.assert_called_once_with("examination_batch", [7, 8], 42)
    worker.start.assert_called_once()
    page._delete_thread = None
    page.close()


def test_deletion_rejects_read_only_actor(qt_app, monkeypatch):
    from app.ui import deletion_worker

    user = SimpleNamespace(id=42, role=UserRole.READ_ONLY)
    page = ExaminationPage(nav=SimpleNamespace(get_current_user=lambda: user))
    page.exam_service = object()
    page._selected_jobs = lambda: [SimpleNamespace(id=7, status=JobStatus.COMPLETED)]
    warning = Mock()
    factory = Mock()
    monkeypatch.setattr(QMessageBox, "warning", warning)
    monkeypatch.setattr(deletion_worker, "DeletionWorker", factory)

    page._on_delete_job()

    warning.assert_called_once()
    factory.assert_not_called()
    page.close()


def test_batch_worker_loads_and_uses_requested_actor(monkeypatch):
    from app.auth.models import User
    from app.db import session as db_session
    from app.examination.service import ExaminationService
    from app.ui.deletion_worker import DeletionWorker

    actor = SimpleNamespace(id=42)
    session = Mock()
    session.get_bind.return_value.dialect.name = "other"
    session.get.return_value = actor
    monkeypatch.setattr(db_session, "get_session_factory", lambda: lambda: session)
    delete = Mock(return_value=True)
    monkeypatch.setattr(ExaminationService, "delete_job", delete)

    worker = DeletionWorker("examination_batch", [7, 8], 42)
    worker.run()

    session.get.assert_called_once_with(User, 42)
    assert delete.call_args_list == [((7, actor),), ((8, actor),)]
    session.close.assert_called_once()
