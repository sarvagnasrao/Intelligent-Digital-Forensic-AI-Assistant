"""Exercise the GUI service and worker concurrently without external services."""
import asyncio
import uuid
from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.artifacts.models import Artifact
from app.auth.models import Case, User
from app.db import Base, load_all_models
from app.evidence.models import Evidence
from app.examination.models import ExaminationJob, ExaminationOperation, JobStatus
from app.examination.service import ExaminationService
import worker.main as worker


@pytest.fixture
def setup_scan(tmp_path, monkeypatch):
    load_all_models()
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    image = tmp_path / "evidence.img"
    image.write_bytes(b"test image")
    with Session(engine) as session:
        user = User(username="examiner", email="e@example.test", password_hash="x", full_name="Examiner")
        session.add(user)
        session.flush()
        case = Case(case_id="CASE-TEST", title="Test", created_by_id=user.id)
        session.add(case)
        session.flush()
        evidence = Evidence(evidence_id="E-TEST", case_id=case.id, name="image", source_path=str(image), registered_by_id=user.id)
        session.add(evidence)
        session.flush()
        job = ExaminationJob(job_id=f"JOB-{uuid.uuid4().hex}", case_id=case.id, evidence_id=evidence.id,
                             operation=ExaminationOperation.FILE_TRAVERSAL, status=JobStatus.PENDING, created_by_id=user.id)
        session.add(job)
        session.commit()
        monkeypatch.setattr(worker, "PYTSK3_AVAILABLE", True)
        monkeypatch.setattr(worker, "get_partitions", lambda path: [{"offset": 4096}])
        monkeypatch.setattr(worker, "get_filesystem_info", lambda *args: {"fs_type": "test"})
        yield session, job
    worker._artifact_batches.pop(job.job_id, None)
    worker._examination_progress.pop(job.job_id, None)
    engine.dispose()


def row(name, **values):
    return {"name": name, "path": "/" + name, "size": 1, **values}


def test_progressive_ack_and_coverage(setup_scan, monkeypatch):
    session, job = setup_scan
    def walk(path, offset, **kwargs):
        deliver = kwargs["batch_callback"]
        deliver(offset, [row("text", content_text="evidence"), row("empty")])
        deliver(offset, [row("deleted", deleted=True), row("error", read_error="unreadable")])
        return []
    monkeypatch.setattr(worker, "walk_and_extract_artifacts", walk)

    async def run():
        service = ExaminationService(session)
        service._client = httpx.AsyncClient(transport=httpx.ASGITransport(app=worker.app), base_url="http://worker")
        try:
            assert await asyncio.wait_for(service.start_job(job.id), 10)
        finally:
            await service.close()
    asyncio.run(run())
    assert job.status == JobStatus.COMPLETED
    assert len(session.scalars(select(Artifact)).all()) == 4
    assert "1 with text, 1 without text, 0 unsupported or no text" in job.progress_message
    assert "1 deleted metadata-only, 1 read errors" in job.progress_message
    assert job.job_id not in worker._artifact_batches


def test_streaming_partial_partition_coverage_is_persisted(setup_scan, monkeypatch):
    session, job = setup_scan
    monkeypatch.setattr(worker, "get_partitions", lambda _: [{"offset": 4096}, {"offset": 8192}])
    monkeypatch.setattr(worker, "get_filesystem_info", lambda _, offset: (
        {"fs_type": "test"} if offset == 4096 else {"error": "unsupported filesystem"}
    ))
    def walk(path, offset, **kwargs):
        kwargs["batch_callback"](offset, [row("saved", content_text="evidence")])
        return []
    monkeypatch.setattr(worker, "walk_and_extract_artifacts", walk)

    async def run():
        service = ExaminationService(session)
        service._client = httpx.AsyncClient(transport=httpx.ASGITransport(app=worker.app), base_url="http://worker")
        try:
            assert await asyncio.wait_for(service.start_job(job.id), 10)
        finally:
            await service.close()
    asyncio.run(run())
    assert job.status == JobStatus.COMPLETED
    assert "incomplete coverage" in job.progress_message
    warnings = [result for result in job.results if result.result_type == "partition_warning"]
    assert len(warnings) == 1
    assert "8192" in warnings[0].summary
    assert "unsupported filesystem" in warnings[0].summary
    assert [artifact.name for artifact in session.scalars(select(Artifact)).all()] == ["saved"]


def test_failed_batch_rolls_back_and_cancels_worker(setup_scan, monkeypatch):
    session, job = setup_scan
    def walk(path, offset, **kwargs):
        deliver = kwargs["batch_callback"]
        deliver(offset, [row("retained", content_text="first")])
        deliver(offset, [row("partial"), row("broken", inode={"invalid": True})])
        return []
    monkeypatch.setattr(worker, "walk_and_extract_artifacts", walk)

    async def run():
        service = ExaminationService(session)
        service._client = httpx.AsyncClient(transport=httpx.ASGITransport(app=worker.app), base_url="http://worker")
        try:
            assert not await asyncio.wait_for(service.start_job(job.id), 10)
        finally:
            await service.close()
    asyncio.run(run())
    assert job.status == JobStatus.FAILED
    assert [artifact.name for artifact in session.scalars(select(Artifact)).all()] == ["retained"]


def test_worker_interruption_preserves_acknowledged_batch(setup_scan, monkeypatch):
    session, job = setup_scan
    def walk(path, offset, **kwargs):
        kwargs["batch_callback"](offset, [row("saved", content_text="evidence")])
        raise RuntimeError("simulated scan interruption")
    monkeypatch.setattr(worker, "walk_and_extract_artifacts", walk)

    async def run():
        service = ExaminationService(session)
        service._client = httpx.AsyncClient(transport=httpx.ASGITransport(app=worker.app), base_url="http://worker")
        try:
            assert not await asyncio.wait_for(service.start_job(job.id), 10)
        finally:
            await service.close()
    asyncio.run(run())
    assert job.status == JobStatus.FAILED
    assert "simulated scan interruption" in job.error_message
    assert [artifact.name for artifact in session.scalars(select(Artifact)).all()] == ["saved"]
    assert job.job_id not in worker._artifact_batches


def test_early_client_interruption_persists_running_and_requests_worker_cancel(setup_scan):
    session, job = setup_scan
    job.completed_at = datetime.now(UTC)
    session.commit()
    calls = []

    async def run():
        started = asyncio.Event()

        async def handle(request):
            calls.append(request.url.path)
            if request.url.path == "/examine":
                started.set()
                await asyncio.Event().wait()
            return httpx.Response(200, json={})

        service = ExaminationService(session)
        service._client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
        try:
            task = asyncio.create_task(service.start_job(job.id))
            await asyncio.wait_for(started.wait(), 3)
            with Session(session.bind) as observer:
                persisted = observer.get(ExaminationJob, job.id)
                assert persisted.status == JobStatus.RUNNING
                assert persisted.completed_at is None
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        finally:
            await service.close()

    asyncio.run(run())
    assert f"/examine/{job.job_id}/cancel" in calls
    assert job.status == JobStatus.INTERRUPTED
    assert job.completed_at is not None


def test_transport_timeout_requests_worker_cancel(setup_scan):
    session, job = setup_scan
    calls = []

    async def handle(request):
        calls.append(request.url.path)
        if request.url.path == "/examine":
            raise httpx.ReadTimeout("timed out", request=request)
        return httpx.Response(200, json={})

    async def run():
        service = ExaminationService(session)
        service._client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
        try:
            assert not await service.start_job(job.id)
        finally:
            await service.close()

    asyncio.run(run())
    assert f"/examine/{job.job_id}/cancel" in calls
    assert job.status == JobStatus.FAILED
