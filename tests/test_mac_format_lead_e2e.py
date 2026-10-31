"""Offline, synthetic source-backed MAC spelling regression."""

import asyncio
import json
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
from worker.main import extract_text_content


def test_mac_spelling_links_source_artifacts_without_identity_inference(
    tmp_path, config_home, monkeypatch
):
    save_config(set_data_dir(Config(), tmp_path))
    load_all_models()
    engine = create_engine(f"sqlite+pysqlite:///{(tmp_path / 'mac.db').as_posix()}")
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
            case = Case(case_id="C-MAC", title="Synthetic", created_by_id=user.id)
            session.add(case)
            session.flush()
            evidence = Evidence(
                evidence_id="E-MAC",
                case_id=case.id,
                name="Acquisition",
                source_path="synthetic",
                registered_by_id=user.id,
            )
            session.add(evidence)
            session.flush()
            exam = ExaminationJob(
                job_id="EX-MAC",
                case_id=case.id,
                evidence_id=evidence.id,
                operation=ExaminationOperation.FULL_EXAMINATION,
                status=JobStatus.COMPLETED,
                created_by_id=user.id,
            )
            session.add(exam)
            session.flush()
            sources = [
                b"adapter 02:1A:2B:3C:4D:5E",
                b"adapter 02-1a-2b-3c-4d-5e",
                b"adapter 02:1a:2b:3c:4d:5f",
                b"ordinary unrelated note",
            ]
            artifacts = []
            for i, source in enumerate(sources):
                artifact = Artifact(
                    artifact_id=f"ART-MAC-{i}",
                    case_id=case.id,
                    evidence_id=evidence.id,
                    examination_job_id=exam.id,
                    artifact_type=ArtifactType.FILE,
                    name=f"{i}.txt",
                    source_path=f"/synthetic/{i}.txt",
                    content_text=extract_text_content(source, "text/plain", ".txt"),
                )
                session.add(artifact)
                artifacts.append(artifact)
            session.commit()

            def blocked(*args, **kwargs):
                raise AssertionError("network access in isolated test")

            service = AnalysisService(session)
            job = service.enqueue_for_examination(
                case.id,
                evidence.id,
                exam.id,
                parameters={"llm_enabled": False, "build_relationships": True},
                manual=True,
            )
            session.commit()

            async def run_offline():
                with monkeypatch.context() as guard:
                    guard.setattr(socket.socket, "connect", blocked)
                    return await service.run(job.id)

            assert asyncio.run(run_offline())["ok"]
            leads = session.scalars(
                select(Entity).where(Entity.entity_type == EntityType.MAC_ADDRESS)
            ).all()
            assert len(leads) == 3
            for lead in leads:
                artifact = next(a for a in artifacts if a.id == lead.artifact_id)
                assert artifact.content_text[lead.start_offset : lead.end_offset] == lead.value
            assert {
                lead.normalized_value
                for lead in leads
                if lead.artifact_id in {artifacts[0].id, artifacts[1].id}
            } == {"02:1a:2b:3c:4d:5e"}
            links = session.scalars(
                select(EntityRelationship).where(
                    EntityRelationship.kind == RelationshipKind.RELATED_ARTIFACTS
                )
            ).all()
            assert {frozenset(json.loads(link.artifact_ids_json)) for link in links} == {
                frozenset([artifacts[0].id, artifacts[1].id])
            }
    finally:
        engine.dispose()
