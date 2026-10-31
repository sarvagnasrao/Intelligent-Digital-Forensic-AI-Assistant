"""Offline regression for quoted vCard encoding parameters."""

import asyncio
import socket

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.analysis.service import AnalysisService
from app.artifacts.models import Artifact, ArtifactType, Entity, EntityType
from app.auth.models import Case, User
from app.config import Config, save_config, set_data_dir
from app.db import Base, load_all_models
from app.evidence.models import Evidence
from app.examination.models import ExaminationJob, ExaminationOperation, JobStatus
from worker.main import extract_text_content


def test_vcard_quoted_encoding_source_backed_lead(tmp_path, config_home, monkeypatch):
    source = (
        b"BEGIN:VCARD\r\nVERSION:2.1\r\n"
        b'NOTE;ENCODING="QUOTED-PRINTABLE":contact alice=40sample.=\r\n'
        b'test\r\nEND:VCARD\r\n'
    )
    text = extract_text_content(source, "text/vcard", ".vcf")
    assert "contact alice@sample.test" in text

    save_config(set_data_dir(Config(), tmp_path))
    load_all_models()
    engine = create_engine(f"sqlite+pysqlite:///{(tmp_path / 'vcard.db').as_posix()}")
    Base.metadata.create_all(engine)
    try:
        with Session(engine, expire_on_commit=False) as session:
            user = User(
                username="examiner",
                email="examiner@example.test",
                password_hash="x",
                full_name="Examiner",
            )
            session.add(user)
            session.flush()
            case = Case(case_id="C-CHARSET", title="Synthetic", created_by_id=user.id)
            session.add(case)
            session.flush()
            evidence = Evidence(
                evidence_id="E-CHARSET",
                case_id=case.id,
                name="Synthetic",
                source_path="synthetic",
                registered_by_id=user.id,
            )
            session.add(evidence)
            session.flush()
            exam = ExaminationJob(
                job_id="EX-CHARSET",
                case_id=case.id,
                evidence_id=evidence.id,
                operation=ExaminationOperation.FULL_EXAMINATION,
                status=JobStatus.COMPLETED,
                created_by_id=user.id,
            )
            session.add(exam)
            session.flush()
            artifact = Artifact(
                artifact_id="A-CHARSET",
                case_id=case.id,
                evidence_id=evidence.id,
                examination_job_id=exam.id,
                artifact_type=ArtifactType.FILE,
                name="contact.vcf",
                source_path="/synthetic/contact.vcf",
                content_text=text,
            )
            session.add(artifact)
            session.commit()
            service = AnalysisService(session)
            job = service.enqueue_for_examination(
                case.id,
                evidence.id,
                exam.id,
                created_by=user,
                parameters={"llm_enabled": False, "build_relationships": True},
                manual=True,
            )
            session.commit()

            def blocked(*args, **kwargs):
                raise AssertionError("network access in offline test")

            async def run():
                with monkeypatch.context() as guard:
                    guard.setattr(socket.socket, "connect", blocked)
                    guard.setattr(socket.socket, "connect_ex", blocked)
                    return await service.run(job.id, user)

            assert asyncio.run(run())["ok"]
            leads = session.scalars(
                select(Entity).where(
                    Entity.artifact_id == artifact.id, Entity.entity_type == EntityType.EMAIL
                )
            ).all()
            assert len(leads) == 1
            assert leads[0].value == "alice@sample.test"
            assert text[leads[0].start_offset : leads[0].end_offset] == leads[0].value
    finally:
        engine.dispose()
