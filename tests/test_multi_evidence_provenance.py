"""Disposable multi-evidence provenance regression, without external services.

Evidence records represent acquisitions; labels suggesting devices do not imply
the application has a separate device model or prove physical-device identity.
"""
import asyncio
import json

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from app.analysis.models import EntityRelationship, RelationshipKind
from app.analysis.service import AnalysisService
from app.artifacts.models import Artifact
from app.artifacts.service import SearchService
from app.auth.models import Case, User
from app.config import Config, save_config, set_data_dir
from app.db import Base, load_all_models
from app.db.session import _FTS_TABLE_SQL, _FTS_TRIGGER_SQL
from app.evidence.models import Evidence
from app.examination.models import ExaminationJob, ExaminationOperation, JobStatus
from app.examination.service import ExaminationService
from app.findings.service import FindingService


def test_provenance_survives_same_path_ingest_search_analysis_and_finding(
    tmp_path, config_home, monkeypatch
):
    import socket

    save_config(set_data_dir(Config(), tmp_path))
    load_all_models()
    engine = create_engine(f"sqlite+pysqlite:///{(tmp_path / 'provenance.db').as_posix()}")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(text(_FTS_TABLE_SQL))
        for statement in _FTS_TRIGGER_SQL:
            connection.execute(text(statement))
    try:
        with Session(engine, expire_on_commit=False) as session:
            user = User(username="examiner", email="examiner@example.test", password_hash="x", full_name="Examiner")
            session.add(user)
            session.flush()
            cases = [Case(case_id=f"CASE-{i}", title=f"Case {i}", created_by_id=user.id) for i in range(2)]
            session.add_all(cases)
            session.flush()
            evidence = [Evidence(evidence_id=f"EV-{i}", case_id=cases[0 if i < 3 else 1].id,
                                 name=f"Acquisition {i}", source_path=f"synthetic-{i}",
                                 registered_by_id=user.id) for i in range(4)]
            session.add_all(evidence)
            session.flush()
            jobs = [ExaminationJob(job_id=f"EX-{i}", case_id=item.case_id, evidence_id=item.id,
                                   operation=ExaminationOperation.FULL_EXAMINATION,
                                   status=JobStatus.COMPLETED, created_by_id=user.id)
                    for i, item in enumerate(evidence)]
            session.add_all(jobs)
            session.commit()
            ingest = ExaminationService(session)
            contents = ["courier@relay.test alpha", "courier@relay.test beta", "unrelated gamma", "courier@relay.test othercase"]
            for item, job, content in zip(evidence, jobs, contents, strict=True):
                row = {"name": "same.txt", "path": "/same.txt", "size": len(content), "content_text": content}
                assert asyncio.run(ingest._create_artifact_records(item.case_id, item.id, job.id, {"artifacts": [row]})) == {"created": 1, "updated": 0}
            session.commit()
            artifacts = {a.evidence_id: a for a in session.scalars(select(Artifact)).all()}
            assert len(artifacts) == 4
            for item, job, content in zip(evidence, jobs, contents, strict=True):
                artifact = artifacts[item.id]
                assert (artifact.case_id, artifact.examination_job_id, artifact.content_text) == (item.case_id, job.id, content)

            results = asyncio.run(SearchService(session).keyword_search(cases[0].id, '"courier@relay.test"'))
            assert {r["artifact"].id for r in results} == {artifacts[evidence[0].id].id, artifacts[evidence[1].id].id}

            async def analyse_offline():
                def blocked(*args, **kwargs):
                    raise AssertionError("network access in isolated regression")
                with monkeypatch.context() as guard:
                    guard.setattr(socket.socket, "connect", blocked)
                    service = AnalysisService(session)
                    for item, job in zip(evidence[:3], jobs[:3], strict=True):
                        analysis = service.enqueue_for_examination(item.case_id, item.id, job.id, created_by=user, parameters={"llm_enabled": False, "build_relationships": True}, manual=True)
                        session.commit()
                        assert (await service.run(analysis.id, user))["ok"]
            asyncio.run(analyse_offline())
            links = session.scalars(select(EntityRelationship).where(EntityRelationship.case_id == cases[0].id, EntityRelationship.kind == RelationshipKind.RELATED_ARTIFACTS)).all()
            link = next(r for r in links if set(json.loads(r.artifact_ids_json)) == {artifacts[evidence[0].id].id, artifacts[evidence[1].id].id})
            assert set(json.loads(link.evidence_ids_json)) == {evidence[0].id, evidence[1].id}

            findings = FindingService(session)
            finding = findings.create_finding(cases[0].id, "Shared contact", "A lead for review", user)
            for item in evidence[:2]:
                findings.link_artifact(finding.id, artifacts[item.id].id, actor=user)
            with pytest.raises(ValueError):
                findings.link_artifact(finding.id, artifacts[evidence[3].id].id, actor=user)
            session.commit()
            session.expire_all()
            saved = findings.get_finding(finding.id)
            assert {link.artifact.evidence_id for link in saved.artifact_links} == {evidence[0].id, evidence[1].id}
    finally:
        engine.dispose()
