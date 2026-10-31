"""Progress persistence failures must stop the worker, not be ignored."""
import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx

from app.audit.service import AuditService
from app.auth.models import UserRole
from app.evidence.models import EvidenceStatus
from app.examination.models import ExaminationOperation, JobStatus
from app.examination.service import ExaminationService


def test_progress_commit_failure_cancels_scan_and_marks_failed(monkeypatch):
    actor = SimpleNamespace(id=3, role=UserRole.ADMIN)
    job = SimpleNamespace(
        id=1, job_id="JOB-TEST", case_id=1, evidence_id=2,
        status=JobStatus.PENDING, operation=ExaminationOperation.FILE_TRAVERSAL,
        parameters_json=None, created_by_id=actor.id, created_by=actor, progress_percent=0,
    )
    evidence = SimpleNamespace(status=EvidenceStatus.REGISTERED, stored_path=None, source_path="missing.img")
    session = MagicMock()
    session.get.side_effect = [job, evidence, actor]
    commit_progress = []

    def commit():
        commit_progress.append((job.status, job.progress_percent))
        if len(commit_progress) == 2:
            raise RuntimeError("progress write failed")

    session.commit.side_effect = commit
    monkeypatch.setattr(AuditService, "log_examination_start", lambda *args: None)
    monkeypatch.setattr(AuditService, "log_examination_complete", lambda *args, **kwargs: None)
    calls = []

    async def handle(request):
        calls.append(request.url.path)
        if request.url.path == "/examine":
            await asyncio.Event().wait()
        if request.url.path.endswith("/progress"):
            return httpx.Response(200, json={"status": "running", "progress": 10})
        return httpx.Response(200, json={})

    async def run():
        service = ExaminationService(session)
        service._client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
        try:
            assert not await asyncio.wait_for(service.start_job(1), 5)
        finally:
            await service.close()

    asyncio.run(run())
    assert commit_progress == [
        (JobStatus.RUNNING, 0),
        (JobStatus.RUNNING, 10),
        (JobStatus.FAILED, 0),
    ]
    assert "/examine/JOB-TEST/progress" in calls
    assert job.status == JobStatus.FAILED
    assert "progress write failed" in job.error_message
    assert "/examine/JOB-TEST/cancel" in calls
    session.rollback.assert_called_once()
