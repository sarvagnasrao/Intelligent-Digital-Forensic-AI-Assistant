"""Synthetic JSON coverage and cross-evidence associations, entirely offline."""

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


def test_escaped_json_leads_remain_traceable_across_evidence(tmp_path, config_home, monkeypatch):
    sources = [
        b'{"records":[{"contact":"dispatch\\u0040relay\\u002etest"},'
        b'{"note":"copied from a public warning"}]}',
        b'{"reply":"dispatch@relay.test", "other":"different@relay.test"}',
        b'{"bad":"dispatch\\u0040relay\\u002etest"',  # incomplete JSON
    ]
    texts = [extract_text_content(source, None, ".json") for source in sources]
    assert all(texts)
    assert sources[0].decode() in texts[0]
    assert "dispatch@relay.test" in texts[0]
    assert texts[2] == sources[2].decode()
    save_config(set_data_dir(Config(), tmp_path))
    load_all_models()
    engine = create_engine(f"sqlite+pysqlite:///{(tmp_path / 'json.db').as_posix()}")
    Base.metadata.create_all(engine)
    try:
        with Session(engine, expire_on_commit=False) as session:
            user = User(
                username="tester", email="tester@example.test", password_hash="x", full_name="Test"
            )
            session.add(user)
            session.flush()
            case = Case(case_id="C-JSON", title="Synthetic", created_by_id=user.id)
            session.add(case)
            session.flush()
            artifacts, jobs = [], []
            for i, text in enumerate(texts):
                evidence = Evidence(
                    evidence_id=f"E-JSON-{i}",
                    case_id=case.id,
                    name=f"source{i}",
                    source_path=f"source{i}",
                    registered_by_id=user.id,
                )
                session.add(evidence)
                session.flush()
                exam = ExaminationJob(
                    job_id=f"EX-JSON-{i}",
                    case_id=case.id,
                    evidence_id=evidence.id,
                    operation=ExaminationOperation.FULL_EXAMINATION,
                    status=JobStatus.COMPLETED,
                    created_by_id=user.id,
                )
                session.add(exam)
                session.flush()
                artifact = Artifact(
                    artifact_id=f"A-JSON-{i}",
                    case_id=case.id,
                    evidence_id=evidence.id,
                    examination_job_id=exam.id,
                    artifact_type=ArtifactType.FILE,
                    name=f"record{i}.json",
                    source_path=f"/synthetic/record{i}.json",
                    content_text=text,
                )
                session.add(artifact)
                artifacts.append(artifact)
                jobs.append((evidence, exam))
            session.commit()
            service = AnalysisService(session)

            def reject(*args, **kwargs):
                raise AssertionError("network access in offline test")

            async def run():
                with monkeypatch.context() as guard:
                    guard.setattr(socket.socket, "connect", reject)
                    guard.setattr(socket.socket, "connect_ex", reject)
                    for evidence, exam in jobs:
                        job = service.enqueue_for_examination(
                            case.id,
                            evidence.id,
                            exam.id,
                            created_by=user,
                            parameters={"llm_enabled": False, "build_relationships": True},
                            manual=True,
                        )
                        session.commit()
                        assert (await service.run(job.id, user))["ok"]

            asyncio.run(run())
            entities = session.scalars(
                select(Entity).where(
                    Entity.case_id == case.id,
                    Entity.entity_type == EntityType.EMAIL,
                    Entity.normalized_value == "dispatch@relay.test",
                )
            ).all()
            assert {entity.artifact_id for entity in entities} == {artifacts[0].id, artifacts[1].id}
            for entity in entities:
                artifact = next(a for a in artifacts if a.id == entity.artifact_id)
                assert (
                    artifact.content_text[entity.start_offset : entity.end_offset] == entity.value
                )
            links = session.scalars(
                select(EntityRelationship).where(
                    EntityRelationship.case_id == case.id,
                    EntityRelationship.kind == RelationshipKind.RELATED_ARTIFACTS,
                )
            ).all()
            assert any(
                set(json.loads(link.artifact_ids_json)) == {artifacts[0].id, artifacts[1].id}
                and set(json.loads(link.evidence_ids_json))
                == {artifacts[0].evidence_id, artifacts[1].evidence_id}
                for link in links
            )
    finally:
        engine.dispose()
