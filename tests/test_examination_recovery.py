"""Jobs that were running when the application exited.

Nothing survives a GUI exit, so a ``RUNNING`` row found at startup belongs to a
process that no longer exists. It must not stay running: the UI would show a
frozen progress bar and retries would be refused.
"""
from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.evidence.models import EvidenceStatus
from app.examination.models import ExaminationJob, ExaminationOperation, JobStatus
from app.examination.service import ExaminationService

CASE_ID = 1
EVIDENCE_ID = 1
USER_ID = 1


@pytest.fixture
def session():
    from app.db import Base, load_all_models

    load_all_models()
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db_session:
        yield db_session
    engine.dispose()


def add_job(session, job_id: str, status: JobStatus) -> ExaminationJob:
    job = ExaminationJob(
        job_id=job_id,
        case_id=CASE_ID,
        evidence_id=EVIDENCE_ID,
        operation=ExaminationOperation.FILE_TRAVERSAL,
        status=status,
        created_by_id=USER_ID,
    )
    session.add(job)
    session.commit()
    return job


def test_a_running_job_becomes_interrupted(session):
    job = add_job(session, "JOB-RUNNING", JobStatus.RUNNING)

    count = ExaminationService(session).mark_interrupted_jobs()

    assert count == 1
    assert job.status is JobStatus.INTERRUPTED
    assert job.completed_at is not None
    assert "closed while this job was running" in job.progress_message


def test_finished_jobs_are_untouched(session):
    pending = add_job(session, "JOB-PENDING", JobStatus.PENDING)
    completed = add_job(session, "JOB-DONE", JobStatus.COMPLETED)
    failed = add_job(session, "JOB-FAILED", JobStatus.FAILED)

    assert ExaminationService(session).mark_interrupted_jobs() == 0

    assert pending.status is JobStatus.PENDING
    assert completed.status is JobStatus.COMPLETED
    assert failed.status is JobStatus.FAILED


def test_nothing_to_recover_is_not_an_error(session):
    assert ExaminationService(session).mark_interrupted_jobs() == 0


def test_recovery_is_idempotent(session):
    add_job(session, "JOB-RUNNING", JobStatus.RUNNING)
    service = ExaminationService(session)

    assert service.mark_interrupted_jobs() == 1
    assert service.mark_interrupted_jobs() == 0


def test_an_interrupted_job_can_be_started_again(session, monkeypatch):
    """The retry must be allowed past the status gate.

    The evidence is stubbed as archived, so an accepted start ends in a known
    failure the test can observe. Before recovery the gate rejects the call and
    the job keeps its status.
    """
    from app.evidence.models import Evidence

    class ArchivedEvidence:
        status = EvidenceStatus.ARCHIVED

    original_get = session.get

    def fake_get(model, ident, **kwargs):
        if model is Evidence:
            return ArchivedEvidence()
        return original_get(model, ident, **kwargs)

    monkeypatch.setattr(session, "get", fake_get)

    job = add_job(session, "JOB-RUNNING", JobStatus.RUNNING)
    service = ExaminationService(session)

    assert asyncio.run(service.start_job(job.id)) is False
    assert job.status is JobStatus.RUNNING
    assert job.error_message is None

    service.mark_interrupted_jobs()

    assert asyncio.run(service.start_job(job.id)) is False
    # Past the gate: the archived evidence is what stopped it.
    assert job.status is JobStatus.FAILED
    assert "Archived evidence" in job.error_message


def test_a_missing_job_cannot_be_started(session):
    assert asyncio.run(ExaminationService(session).start_job(999)) is False


def test_startup_recovery_uses_the_configured_database(config_home, data_dir):
    """The entry point must close stale jobs in the real database, not a copy.

    ``app.__main__`` calls this before the window opens; here the engine is
    pointed at a temporary data root so the developer's own cases are untouched.
    """
    from app import db as db_package
    from app.auth.models import Case, User
    from app.config import Config, save_config, set_data_dir
    from app.db import session as session_module
    from app.evidence.models import Evidence

    save_config(set_data_dir(Config(), data_dir))
    db_package.load_all_models()
    session_module._engine = None
    session_module._session_factory = None
    session_module.init_db()

    from app.__main__ import recover_interrupted_jobs

    factory = session_module.get_session_factory()
    try:
        with factory() as db:
            user = User(
                username="stale", email="stale@example.test",
                password_hash="x", full_name="Stale",
            )
            db.add(user)
            db.commit()

            case = Case(case_id="C-STARTUP", title="Startup", created_by_id=user.id)
            db.add(case)
            db.commit()

            evidence = Evidence(
                evidence_id="E-STARTUP", case_id=case.id, name="disk.img",
                source_path="C:/evidence/disk.img", registered_by_id=user.id,
            )
            db.add(evidence)
            db.commit()

            db.add(ExaminationJob(
                job_id="JOB-STALE", case_id=case.id, evidence_id=evidence.id,
                operation=ExaminationOperation.FILE_TRAVERSAL,
                status=JobStatus.RUNNING, created_by_id=user.id,
            ))
            db.commit()

        assert recover_interrupted_jobs() == 1
        assert recover_interrupted_jobs() == 0

        with factory() as db:
            job = db.execute(select(ExaminationJob)).scalars().one()
            assert job.status is JobStatus.INTERRUPTED
            assert job.progress_message
    finally:
        if session_module._engine is not None:
            session_module._engine.dispose()
        session_module._engine = None
        session_module._session_factory = None
