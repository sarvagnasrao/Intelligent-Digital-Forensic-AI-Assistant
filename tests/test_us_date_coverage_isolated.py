"""Offline coverage of unambiguous US dates through ingestion and analysis."""

import asyncio
import socket

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.analysis.extractors import parse_timestamp
from app.analysis.service import AnalysisService
from app.artifacts.models import Artifact, ArtifactType, Entity, EntityType
from app.auth.models import Case, User
from app.config import Config, save_config, set_data_dir
from app.db import Base, load_all_models
from app.evidence.models import Evidence
from app.examination.models import ExaminationJob, ExaminationOperation, JobStatus
from worker.main import extract_text_content


def test_us_date_and_phone_remain_separate_source_backed_leads(
    tmp_path, config_home, monkeypatch
):
    save_config(set_data_dir(Config(), tmp_path))
    load_all_models()
    engine = create_engine(f"sqlite+pysqlite:///{(tmp_path / 'coverage.db').as_posix()}")
    Base.metadata.create_all(engine)
    try:
        with Session(engine, expire_on_commit=False) as session:
            user = User(
                username="examiner", email="test@example.test", password_hash="x",
                full_name="Examiner",
            )
            session.add(user)
            session.flush()
            case = Case(case_id="C-TIME", title="Synthetic", created_by_id=user.id)
            session.add(case)
            session.flush()
            evidence = Evidence(
                evidence_id="E-TIME", case_id=case.id, name="synthetic",
                source_path="synthetic", registered_by_id=user.id,
            )
            session.add(evidence)
            session.flush()
            exam = ExaminationJob(
                job_id="EX-TIME", case_id=case.id, evidence_id=evidence.id,
                operation=ExaminationOperation.FULL_EXAMINATION,
                status=JobStatus.COMPLETED, created_by_id=user.id,
            )
            session.add(exam)
            session.flush()
            raw = b"On 12/31/2024 12:34:56 event. Callback +1 212-555-0198."
            artifact = Artifact(
                artifact_id="ART-TIME", case_id=case.id, evidence_id=evidence.id,
                examination_job_id=exam.id, artifact_type=ArtifactType.FILE,
                name="record.txt", source_path="/synthetic/record.txt",
                content_text=extract_text_content(raw, "text/plain", ".txt"),
            )
            session.add(artifact)
            session.commit()
            service = AnalysisService(session)
            job = service.enqueue_for_examination(
                case.id, evidence.id, exam.id,
                created_by=user,
                parameters={"llm_enabled": False, "build_relationships": False}, manual=True,
            )
            session.commit()

            def reject(*args, **kwargs):
                raise AssertionError("network access in isolated test")

            async def run_offline():
                with monkeypatch.context() as guard:
                    guard.setattr(socket.socket, "connect", reject)
                    guard.setattr(socket.socket, "connect_ex", reject)
                    return await service.run(job.id, user)

            assert asyncio.run(run_offline())["ok"]
            entities = session.scalars(
                select(Entity).where(Entity.artifact_id == artifact.id)
            ).all()
            selected = [
                e for e in entities if e.entity_type in (EntityType.TIMESTAMP, EntityType.PHONE)
            ]
            assert {(e.entity_type, e.value) for e in selected} == {
                (EntityType.TIMESTAMP, "12/31/2024 12:34:56"),
                (EntityType.PHONE, "+1 212-555-0198"),
            }
            for entity in selected:
                assert artifact.content_text[entity.start_offset:entity.end_offset] == entity.value
            assert parse_timestamp("12/31/2024 12:34:56").isoformat() == (
                "2024-12-31T12:34:56+00:00"
            )
            assert parse_timestamp("03/04/2024").day == 3
    finally:
        engine.dispose()
