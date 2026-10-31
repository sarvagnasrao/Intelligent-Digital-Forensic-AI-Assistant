"""Offline, synthetic mapped-address leads are not identity assertions."""

import asyncio
import json
import socket

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.analysis.extractors import extract_entities
from app.analysis.models import EntityRelationship, RelationshipKind
from app.analysis.service import AnalysisService
from app.artifacts.models import Artifact, ArtifactType, Entity, EntityType
from app.auth.models import Case, User
from app.config import Config, save_config, set_data_dir
from app.db import Base, load_all_models
from app.evidence.models import Evidence
from app.examination.models import ExaminationJob, ExaminationOperation, JobStatus


def test_mapped_address_lead_is_source_backed_offline(tmp_path, config_home, monkeypatch):
    docs = [
        "Shared gateway observed ::ffff:192.0.2.42 on a public terminal.",
        "Another shift recorded 0:0:0:0:0:ffff:c000:22a; ownership unknown.",
        "A separate IPv4 peer 192.0.2.42 is not the same address representation.",
    ]
    save_config(set_data_dir(Config(), tmp_path))
    load_all_models()
    engine = create_engine(f"sqlite+pysqlite:///{(tmp_path / 'mapped.db').as_posix()}")
    Base.metadata.create_all(engine)
    try:
        with Session(engine, expire_on_commit=False) as session:
            user = User(
                username="test", email="test@example.test", password_hash="x", full_name="Test"
            )
            session.add(user)
            session.flush()
            case = Case(case_id="C-MAPPED", title="Synthetic", created_by_id=user.id)
            session.add(case)
            session.flush()
            evidence = Evidence(
                evidence_id="E-MAPPED",
                case_id=case.id,
                name="synthetic",
                source_path="synthetic",
                registered_by_id=user.id,
                size_bytes=1,
            )
            session.add(evidence)
            session.flush()
            exam = ExaminationJob(
                job_id="EX-MAPPED",
                case_id=case.id,
                evidence_id=evidence.id,
                operation=ExaminationOperation.FULL_EXAMINATION,
                status=JobStatus.COMPLETED,
                created_by_id=user.id,
            )
            session.add(exam)
            session.flush()
            artifacts = [
                Artifact(
                    artifact_id=f"ART-MAPPED-{i}",
                    case_id=case.id,
                    evidence_id=evidence.id,
                    examination_job_id=exam.id,
                    artifact_type=ArtifactType.FILE,
                    name=f"record{i}",
                    source_path=f"/synthetic/record{i}",
                    content_text=text,
                )
                for i, text in enumerate(docs)
            ]
            session.add_all(artifacts)
            session.commit()
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

                    def reject(*args, **kwargs):
                        raise AssertionError("network access in offline test")

                    guard.setattr(socket.socket, "connect", reject)
                    guard.setattr(socket.socket, "connect_ex", reject)
                    return await service.run(job.id)

            assert asyncio.run(run_offline())["ok"]

            entities = (
                session.execute(
                    select(Entity).where(
                        Entity.case_id == case.id, Entity.entity_type == EntityType.IP_ADDRESS
                    )
                )
                .scalars()
                .all()
            )
            by_artifact = {entity.artifact_id: entity for entity in entities}
            assert len(entities) == 3
            assert (
                by_artifact[artifacts[0].id].normalized_value
                == by_artifact[artifacts[1].id].normalized_value
            )
            assert (
                by_artifact[artifacts[0].id].normalized_value
                != by_artifact[artifacts[2].id].normalized_value
            )
            for artifact, text in zip(artifacts, docs, strict=True):
                entity = by_artifact[artifact.id]
                assert text[entity.start_offset : entity.end_offset] == entity.value
            links = (
                session.execute(
                    select(EntityRelationship).where(
                        EntityRelationship.case_id == case.id,
                        EntityRelationship.kind == RelationshipKind.RELATED_ARTIFACTS,
                    )
                )
                .scalars()
                .all()
            )
            assert [set(json.loads(link.artifact_ids_json)) for link in links] == [
                {artifacts[0].id, artifacts[1].id}
            ]
    finally:
        engine.dispose()


def test_mapped_address_not_truncated_or_invented():
    text = "[::ffff:192.0.2.42] versus ::ffff:999.0.2.42"
    entities = [
        item for item in extract_entities(text) if item.entity_type == EntityType.IP_ADDRESS
    ]
    assert entities[0].value == "::ffff:192.0.2.42"
    assert all(text[item.start : item.end] == item.value for item in entities)
    assert not any(item.value == "::ffff:999.0.2.42" for item in entities)
