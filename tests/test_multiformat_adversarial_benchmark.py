"""Small offline source-backed lead benchmark; associations are not identities."""

import asyncio
import json
import socket
from itertools import combinations

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.analysis.extractors import extract_entities
from app.analysis.models import EntityRelationship, RelationshipKind
from app.analysis.service import AnalysisService
from app.artifacts.models import Artifact, ArtifactType, Entity
from app.auth.models import Case, User
from app.config import Config, save_config, set_data_dir
from app.db import Base, load_all_models
from app.evidence.models import Evidence
from app.examination.models import ExaminationJob, ExaminationOperation, JobStatus
from worker.main import extract_text_content


def test_multiformat_adversarial_leads(tmp_path, config_home, monkeypatch):
    # Labels are investigator-defined relevance, not claims about ownership.
    sources = {
        "page": (0, ".html", b"<p>Contact dispatch&#64;relay&#46;test</p>"),
        "mail": (1, ".eml", b"Subject: pickup\n\nContact dispatch@relay.test\n"),
        "warning": (1, ".txt", b"Warning: dispatch@relay.test was copied into a phishing notice."),
        "card": (0, ".vcf", b"BEGIN:VCARD\nVERSION:3.0\nTEL:+1 415-555-0138\nEND:VCARD\n"),
        "note": (1, ".rtf", b"{\\rtf1 Callback +1 415-555-0138 about pickup.}"),
        "other": (0, ".txt", b"Invalid address 999.999.999.999; ordinary inventory."),
        "alias": (1, ".txt", b"A separate alternate mailbox alternate@other.test."),
        "idn_order": (0, ".txt", b"Order contact desk@relay.xn--p1ai."),
        "idn_reply": (1, ".txt", b"Reply to desk@relay.xn--p1ai about the order."),
        "idn_warning": (0, ".txt", b"Warning: desk@relay.xn--p1ai was copied from a scam."),
        "idn_invalid": (1, ".txt", b"Malformed mailbox desk@relay.xn-- is not a contact."),
    }
    relevant = {frozenset(pair) for pair in [
        ("page", "mail"), ("card", "note"), ("mail", "alias"),
        ("idn_order", "idn_reply"),
    ]}
    save_config(set_data_dir(Config(), tmp_path))
    load_all_models()
    engine = create_engine(f"sqlite+pysqlite:///{(tmp_path / 'multiformat.db').as_posix()}")
    Base.metadata.create_all(engine)
    try:
        with Session(engine, expire_on_commit=False) as session:
            user = User(
                username="bench", email="bench@example.test", password_hash="x", full_name="Bench"
            )
            session.add(user)
            session.flush()
            case = Case(case_id="C-MULTI", title="Synthetic", created_by_id=user.id)
            session.add(case)
            session.flush()
            evidence, exams = [], []
            for i in range(2):
                item = Evidence(
                    evidence_id=f"E-MULTI-{i}",
                    case_id=case.id,
                    name=f"device-{i}",
                    source_path=f"synthetic-{i}",
                    registered_by_id=user.id,
                )
                session.add(item)
                session.flush()
                exam = ExaminationJob(
                    job_id=f"EX-MULTI-{i}",
                    case_id=case.id,
                    evidence_id=item.id,
                    operation=ExaminationOperation.FULL_EXAMINATION,
                    status=JobStatus.COMPLETED,
                    created_by_id=user.id,
                )
                session.add(exam)
                session.flush()
                evidence.append(item)
                exams.append(exam)
            artifacts = {}
            for name, (device, ext, source) in sources.items():
                text = extract_text_content(source, None, ext)
                assert text
                artifact = Artifact(
                    artifact_id=f"A-MULTI-{name}",
                    case_id=case.id,
                    evidence_id=evidence[device].id,
                    examination_job_id=exams[device].id,
                    artifact_type=ArtifactType.FILE,
                    name=name + ext,
                    source_path=f"/synthetic/{name}{ext}",
                    content_text=text,
                )
                session.add(artifact)
                artifacts[name] = artifact
            session.commit()
            assert "dispatch&#64;relay&#46;test" in artifacts["page"].content_text
            assert "[HTML character references decoded]" in artifacts["page"].content_text
            # The previous standalone HTML representation was just this raw text.
            assert not any(e.value == "dispatch@relay.test" for e in extract_entities(
                sources["page"][2].decode("utf-8")
            ))
            assert not any(e.entity_type.value == "email" for e in extract_entities(
                sources["idn_invalid"][2].decode("utf-8")
            ))

            def blocked(*args, **kwargs):
                raise AssertionError("network access in offline benchmark")

            service = AnalysisService(session)

            async def run_jobs():
                with monkeypatch.context() as guard:
                    guard.setattr(socket.socket, "connect", blocked)
                    guard.setattr(socket.socket, "connect_ex", blocked)
                    for item, exam in zip(evidence, exams, strict=True):
                        job = service.enqueue_for_examination(
                            case.id,
                            item.id,
                            exam.id,
                            parameters={"llm_enabled": False, "build_relationships": True},
                            manual=True,
                        )
                        session.commit()
                        assert (await service.run(job.id))["ok"]

            asyncio.run(run_jobs())
            names = {artifact.id: name for name, artifact in artifacts.items()}
            entities = session.scalars(select(Entity).where(Entity.case_id == case.id)).all()
            for entity in entities:
                artifact = artifacts[names[entity.artifact_id]]
                assert any(
                    (getattr(artifact, field) or "")[entity.start_offset : entity.end_offset]
                    == entity.value
                    for field in ("name", "source_path", "content_text")
                )
            predicted = set()
            for link in session.scalars(
                select(EntityRelationship).where(
                    EntityRelationship.case_id == case.id,
                    EntityRelationship.kind == RelationshipKind.RELATED_ARTIFACTS,
                )
            ):
                ids = json.loads(link.artifact_ids_json)
                pair = frozenset(names[ident] for ident in ids)
                predicted.add(pair)
                assert set(json.loads(link.evidence_ids_json)) == {
                    artifacts[name].evidence_id for name in pair
                }
                for shared in json.loads(link.details_json)["shared"]:
                    assert all(
                        any(
                            e.artifact_id == ident
                            and e.entity_type.value == shared["type"]
                            and e.normalized_value == shared["value"]
                            for e in entities
                        )
                        for ident in ids
                    )
            universe = {frozenset(pair) for pair in combinations(sources, 2)}
            # The copied address is a source-backed association, not evidence of
            # ownership or investigative relevance. Keep that false lead visible.
            assert frozenset(("idn_order", "idn_warning")) in predicted
            assert "copied from a scam" in artifacts["idn_warning"].content_text
            tp, fp, fn = (
                len(predicted & relevant),
                len(predicted - relevant),
                len(relevant - predicted),
            )
            tn = len(universe - predicted - relevant)
            assert (tp, fp, fn, tn) == (3, 4, 1, 47)
            assert tp / (tp + fp) == 3 / 7
            assert tp / (tp + fn) == 3 / 4
    finally:
        engine.dispose()
