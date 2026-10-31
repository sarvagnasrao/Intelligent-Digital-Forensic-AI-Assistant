"""Overlong source identifiers must not create fabricated shared leads."""

import asyncio
import re
import socket

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.analysis.models import EntityRelationship, RelationshipKind
from app.analysis.service import AnalysisService
from app.artifacts.models import Artifact, ArtifactType, Entity, EntityType
from app.auth.models import Case, User
from app.config import Config, save_config, set_data_dir
from app.db import Base, load_all_models
from app.evidence.models import Evidence
from app.examination.models import ExaminationJob, ExaminationOperation, JobStatus


def test_previous_pattern_truncated_distinct_identifiers():
    previous = re.compile(
        r"\b(?:device[_\s-]?(?:id|uuid|serial)|serial(?:number|no)?|imei|udid)"
        r"\s*[=:]\s*[\"']?([A-Za-z0-9][A-Za-z0-9._:\-]{5,63})",
        re.IGNORECASE,
    )
    prefix = "ab12" * 16
    assert [previous.search(f"device_id={prefix}{suffix}").group(1)
            for suffix in "XY"] == [prefix, prefix]


def test_overlong_device_ids_do_not_produce_shared_prefix(tmp_path, config_home, monkeypatch):
    save_config(set_data_dir(Config(), tmp_path))
    load_all_models()
    engine = create_engine(f"sqlite+pysqlite:///{(tmp_path / 'device.db').as_posix()}")
    Base.metadata.create_all(engine)
    try:
        with Session(engine, expire_on_commit=False) as session:
            user = User(username="examiner", email="examiner@example.test",
                        password_hash="x", full_name="Examiner")
            session.add(user)
            session.flush()
            case = Case(case_id="C-DEVICE", title="Synthetic", created_by_id=user.id)
            session.add(case)
            session.flush()
            evidence = Evidence(evidence_id="E-DEVICE", case_id=case.id, name="Synthetic",
                                source_path="synthetic", registered_by_id=user.id)
            session.add(evidence)
            session.flush()
            exam = ExaminationJob(job_id="EX-DEVICE", case_id=case.id,
                                  evidence_id=evidence.id,
                                  operation=ExaminationOperation.FULL_EXAMINATION,
                                  status=JobStatus.COMPLETED, created_by_id=user.id)
            session.add(exam)
            session.flush()
            prefix = "ab12" * 16
            texts = [f"device_id={prefix}X", f"device_id={prefix}Y",
                     f"device_id={prefix}", "device_id=short-123"]
            artifacts = [Artifact(artifact_id=f"ART-DEVICE-{i}", case_id=case.id,
                                  evidence_id=evidence.id, examination_job_id=exam.id,
                                  artifact_type=ArtifactType.FILE, name=f"record{i}",
                                  source_path=f"/synthetic/record{i}", content_text=text)
                         for i, text in enumerate(texts)]
            session.add_all(artifacts)
            session.commit()
            service = AnalysisService(session)
            job = service.enqueue_for_examination(
                case.id, evidence.id, exam.id,
                created_by=user,
                parameters={"llm_enabled": False, "build_relationships": True}, manual=True,
            )
            session.commit()

            def reject(*args, **kwargs):
                raise AssertionError("network access in offline test")

            async def run_offline():
                with monkeypatch.context() as guard:
                    guard.setattr(socket.socket, "connect", reject)
                    guard.setattr(socket.socket, "connect_ex", reject)
                    return await service.run(job.id, user)

            assert asyncio.run(run_offline())["ok"]
            leads = session.scalars(select(Entity).where(
                Entity.case_id == case.id, Entity.entity_type == EntityType.DEVICE_ID
            )).all()
            assert {lead.artifact_id for lead in leads} == {artifacts[2].id, artifacts[3].id}
            for lead in leads:
                text = next(a.content_text for a in artifacts if a.id == lead.artifact_id)
                assert text[lead.start_offset:lead.end_offset] == lead.value
            links = session.scalars(select(EntityRelationship).where(
                EntityRelationship.case_id == case.id,
                EntityRelationship.kind == RelationshipKind.RELATED_ARTIFACTS,
            )).all()
            assert not links
    finally:
        engine.dispose()
