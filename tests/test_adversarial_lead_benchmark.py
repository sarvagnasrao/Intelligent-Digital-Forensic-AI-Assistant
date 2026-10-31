"""Offline lead evaluation: shared identifiers are not proof of identity.

Labels describe a fictional investigation, not whether two texts share a token.
This small hand-authored corpus is a regression fixture, not a population estimate.
"""
import asyncio
import hashlib
import json
import socket
from itertools import combinations

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.analysis.extractors import normalize_value
from app.analysis.models import EntityRelationship, RelationshipKind
from app.analysis.service import AnalysisService
from app.artifacts.models import Artifact, ArtifactType, Entity
from app.auth.models import Case, User
from app.config import Config, save_config, set_data_dir
from app.db import Base, load_all_models
from app.evidence.models import Evidence
from app.examination.models import ExaminationJob, ExaminationOperation, JobStatus


def test_adversarial_identity_leads_offline(tmp_path, config_home, monkeypatch):
    # Alice's own messages are relevant. The shared terminal IP and a copied
    # address in a warning create plausible, source-backed but misleading leads.
    docs = {
        "alice_order": "Alice ordered a parcel; reply to alice@courier.test. Terminal 10.8.4.7.",
        "alice_reply": "Alice confirmed collection from alice@courier.test. Terminal 10.8.4.7.",
        "bob_shift": "Bob used terminal 10.8.4.7 during the next shift.",
        "warning": "Do not contact alice@courier.test: address copied from a phishing warning.",
        "carol_order": "Carol requested pickup via carol@freight.test.",
        "carol_receipt": "Carol received pickup confirmation at carol@freight.test.",
        "help_one": "Instructions from helpdesk@service.test for warehouse A.",
        "help_two": "Instructions from helpdesk@service.test for warehouse B.",
        # Same person but no exact shared identifier: a deliberately missed lead.
        "alice_alias": "Alice used an alternate mailbox alice.alt@other.test for delivery.",
        "unrelated": "Warehouse stock consists of gloves and labels.",
        "shared_note": "The account dock@relay.test is shared by all staff, not owned by Dana.",
        "shared_log": "Evan used dock@relay.test on the shared desk.",
        "dana_order": "Dana ordered supplies using dana@relay.test.",
        "dana_receipt": "Dana received supplies using dana@relay.test.",
    }
    relevant = {frozenset(pair) for pair in [
        ("alice_order", "alice_reply"), ("alice_order", "alice_alias"),
        ("alice_reply", "alice_alias"), ("carol_order", "carol_receipt"),
        ("dana_order", "dana_receipt"),
    ]}
    save_config(set_data_dir(Config(), tmp_path))
    load_all_models()
    engine = create_engine(f"sqlite+pysqlite:///{(tmp_path / 'adversarial.db').as_posix()}")
    Base.metadata.create_all(engine)
    try:
        with Session(engine, expire_on_commit=False) as session:
            user = User(username="bench", email="bench@example.test", password_hash="x", full_name="Bench")
            session.add(user)
            session.flush()
            case = Case(case_id="C-ADV", title="Synthetic", created_by_id=user.id)
            session.add(case)
            session.flush()
            evidence = Evidence(evidence_id="E-ADV", case_id=case.id, name="synthetic", source_path="synthetic", registered_by_id=user.id, size_bytes=1)
            session.add(evidence)
            session.flush()
            exam = ExaminationJob(job_id="EX-ADV", case_id=case.id, evidence_id=evidence.id, operation=ExaminationOperation.FULL_EXAMINATION, status=JobStatus.COMPLETED, created_by_id=user.id)
            session.add(exam)
            session.flush()
            artifacts = {}
            for index, (name, text) in enumerate(docs.items()):
                artifact = Artifact(artifact_id=f"ART-ADV-{index}", case_id=case.id, evidence_id=evidence.id, examination_job_id=exam.id, artifact_type=ArtifactType.FILE, name=name, source_path=f"/synthetic/{name}", content_text=text, content_hash=hashlib.sha256(text.encode()).hexdigest())
                session.add(artifact)
                artifacts[name] = artifact
            session.commit()
            service = AnalysisService(session)
            job = service.enqueue_for_examination(case.id, evidence.id, exam.id, created_by=user, parameters={"llm_enabled": False, "build_timeline": True, "build_relationships": True}, manual=True)
            session.commit()
            async def run_offline():
                with monkeypatch.context() as guard:
                    def reject(*args, **kwargs):
                        raise AssertionError("network access in offline benchmark")
                    guard.setattr(socket.socket, "connect", reject)
                    guard.setattr(socket.socket, "connect_ex", reject)
                    return await service.run(job.id, user)

            assert asyncio.run(run_offline())["ok"]

            names = {artifact.id: name for name, artifact in artifacts.items()}
            entities = list(session.execute(select(Entity).where(Entity.case_id == case.id)).scalars())
            for entity in entities:
                assert docs[names[entity.artifact_id]][entity.start_offset:entity.end_offset] == entity.value
            predicted = set()
            contextualized = {}
            for link in session.execute(select(EntityRelationship).where(EntityRelationship.case_id == case.id, EntityRelationship.kind == RelationshipKind.RELATED_ARTIFACTS)).scalars():
                ids = json.loads(link.artifact_ids_json)
                pair = frozenset(names[ident] for ident in ids)
                contextualized[pair] = json.loads(link.details_json)["shared"]
                assert len(pair) == 2
                assert json.loads(link.evidence_ids_json) == [evidence.id]
                for item in json.loads(link.details_json)["shared"]:
                    assert all(any(entity.artifact_id == ident and entity.entity_type.value == item["type"] and normalize_value(entity.entity_type, entity.value) == item["value"] for entity in entities) for ident in ids)
                    matching = {
                        entity.artifact_id for entity in entities
                        if entity.entity_type.value == item["type"]
                        and normalize_value(entity.entity_type, entity.value) == item["value"]
                    }
                    assert item["case_artifact_count"] == len(matching)
                    excerpts = item["excerpts"]
                    assert {excerpt["artifact_id"] for excerpt in excerpts} == set(ids)
                    for excerpt in excerpts:
                        assert excerpt["text"] in docs[names[excerpt["artifact_id"]]]
                        assert item["value"] in excerpt["text"].lower()
                    if item["value"] in {"alice@courier.test", "10.8.4.7"}:
                        assert item["case_artifact_count"] == 3
                predicted.add(pair)

            # These false leads remain visible, but their source contexts expose
            # the copied-warning and shared-account competing explanations.
            warning = contextualized[frozenset(("alice_order", "warning"))]
            assert any("phishing warning" in excerpt["text"]
                       for item in warning for excerpt in item["excerpts"])
            shared = contextualized[frozenset(("shared_note", "shared_log"))]
            assert any("shared by all staff" in excerpt["text"]
                       for item in shared for excerpt in item["excerpts"])

            universe = {frozenset(pair) for pair in combinations(docs, 2)}
            tp = len(predicted & relevant)
            fp = len(predicted - relevant)
            fn = len(relevant - predicted)
            tn = len(universe - predicted - relevant)
            assert (tp, fp, fn, tn) == (3, 5, 2, 81)
            assert tp / (tp + fp) == 3 / 8  # precision
            assert tp / (tp + fn) == 3 / 5  # recall
    finally:
        engine.dispose()
