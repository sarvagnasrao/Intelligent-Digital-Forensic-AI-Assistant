"""Synthetic, offline SQLite regression corpus; labels are investigative leads, not guilt."""
import asyncio
import hashlib
import json
import socket
from itertools import combinations

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.analysis.models import EntityRelationship, RelationshipKind
from app.analysis.extractors import normalize_value
from app.analysis.service import AnalysisService
from app.artifacts.models import Artifact, ArtifactType, Entity, EntityType
from app.auth.models import Case, User
from app.config import Config, save_config, set_data_dir
from app.db import Base, load_all_models
from app.evidence.models import Evidence
from app.examination.models import ExaminationJob, ExaminationOperation, JobStatus


def test_offline_source_backed_lead_benchmark(tmp_path, config_home, monkeypatch):
    # Labels are defined independently of extraction. Generic contacts and
    # invalid lookalikes are deliberate negative controls; pairs sharing only
    # a generic mailbox are not considered investigative leads here.
    documents = {
        "dispatch": "Message to courier@relay.test, endpoint https://relay.test/drop.",
        "receipt": "Receipt from courier@relay.test; see https://relay.test/drop.",
        "dns": "Observed 10.42.8.9 in outbound connection.",
        "firewall": "Firewall blocked 10.42.8.9 on port 443.",
        "device": "device_id=ZX91-AB72 collected at loading dock.",
        "inventory": "device_id=ZX91-AB72 assigned to shipment.",
        "contact": "Callback +1 415-555-0138 regarding parcel.",
        "voicemail": "Caller +1 415-555-0138 left a message.",
        "policy": "Assistance: help@office.test.",
        "manual": "Questions: help@office.test.",
        "noise": "Invalid 999.999.999.999 and 00000000000000000000000000000000.",
        "unrelated": "Stockroom contains paper and gloves.",
        "thread_out": "From: dispatcher@freight.test\nTo: driver@freight.test\nSubject: collection\nMeet at bay three. Reference device_id=LM28-QR94.",
        "thread_reply": "From: driver@freight.test\nTo: dispatcher@freight.test\nRe: collection\nReceived; device_id=LM28-QR94 is on board.",
        "incident": "Incident note: suspicious host 172.22.9.14 contacted the gateway. Ticket closed.",
        "proxy": "Proxy log: denied 172.22.9.14; destination port 8443. No payload retained.",
        "different_host": "Proxy log: denied 172.22.9.15; destination port 8443. No payload retained.",
        "help_a": "From: helpdesk@service.test\nPlease consult the operating instructions.",
        "help_b": "Forwarded notice from helpdesk@service.test: maintenance tomorrow.",
        "invalid_a": "Header contained 999.999.999.999; placeholder digest aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.",
        "invalid_b": "Warning: 999.999.999.999 is not an address; aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa is a placeholder.",
    }
    relevant = {frozenset(pair) for pair in [
        ("dispatch", "receipt"), ("dns", "firewall"),
        ("device", "inventory"), ("contact", "voicemail"),
        ("thread_out", "thread_reply"), ("incident", "proxy"),
    ]}
    expected = {
        ("dispatch", EntityType.EMAIL, "courier@relay.test"),
        ("receipt", EntityType.EMAIL, "courier@relay.test"),
        ("dispatch", EntityType.URL, "https://relay.test/drop"),
        ("receipt", EntityType.URL, "https://relay.test/drop"),
        ("dns", EntityType.IP_ADDRESS, "10.42.8.9"),
        ("firewall", EntityType.IP_ADDRESS, "10.42.8.9"),
        ("device", EntityType.DEVICE_ID, "ZX91-AB72"),
        ("inventory", EntityType.DEVICE_ID, "ZX91-AB72"),
        ("contact", EntityType.PHONE, "+1 415-555-0138"),
        ("voicemail", EntityType.PHONE, "+1 415-555-0138"),
        ("policy", EntityType.EMAIL, "help@office.test"),
        ("manual", EntityType.EMAIL, "help@office.test"),
        ("thread_out", EntityType.EMAIL, "dispatcher@freight.test"),
        ("thread_out", EntityType.EMAIL, "driver@freight.test"),
        ("thread_reply", EntityType.EMAIL, "dispatcher@freight.test"),
        ("thread_reply", EntityType.EMAIL, "driver@freight.test"),
        ("thread_out", EntityType.DEVICE_ID, "LM28-QR94"),
        ("thread_reply", EntityType.DEVICE_ID, "LM28-QR94"),
        ("incident", EntityType.IP_ADDRESS, "172.22.9.14"),
        ("proxy", EntityType.IP_ADDRESS, "172.22.9.14"),
        ("different_host", EntityType.IP_ADDRESS, "172.22.9.15"),
        ("help_a", EntityType.EMAIL, "helpdesk@service.test"),
        ("help_b", EntityType.EMAIL, "helpdesk@service.test"),
    }
    save_config(set_data_dir(Config(), tmp_path))
    load_all_models()
    engine = create_engine(f"sqlite+pysqlite:///{(tmp_path / 'benchmark.db').as_posix()}")
    Base.metadata.create_all(engine)
    try:
        with Session(engine, expire_on_commit=False) as session:
            user = User(username="benchmark", email="bench@example.test", password_hash="x", full_name="Test")
            session.add(user)
            session.flush()
            case = Case(case_id="C-BENCH", title="Synthetic", created_by_id=user.id)
            session.add(case)
            session.flush()
            evidence = Evidence(evidence_id="E-BENCH", case_id=case.id, name="disk", source_path="synthetic", registered_by_id=user.id, size_bytes=1)
            session.add(evidence)
            session.flush()
            exam = ExaminationJob(job_id="EX-BENCH", case_id=case.id, evidence_id=evidence.id, operation=ExaminationOperation.FULL_EXAMINATION, status=JobStatus.COMPLETED, created_by_id=user.id)
            session.add(exam)
            session.flush()
            artifacts = {}
            for index, (name, text) in enumerate(documents.items()):
                artifact = Artifact(artifact_id=f"ART-BENCH-{index}", case_id=case.id, evidence_id=evidence.id, examination_job_id=exam.id, artifact_type=ArtifactType.FILE, name=name, source_path=f"/evidence/{name}", content_text=text, content_hash=hashlib.sha256(text.encode()).hexdigest())
                session.add(artifact)
                artifacts[name] = artifact
            session.commit()
            service = AnalysisService(session)
            job = service.enqueue_for_examination(case.id, evidence.id, exam.id, user, parameters={"llm_enabled": False, "build_timeline": True, "build_relationships": True}, manual=True)
            session.commit()

            async def run_offline():
                with monkeypatch.context() as guard:
                    def reject(*args, **kwargs):
                        raise AssertionError("network access in synthetic benchmark")
                    guard.setattr(socket.socket, "connect", reject)
                    return await service.run(job.id, user)

            assert asyncio.run(run_offline())["ok"]
            names = {artifact.id: name for name, artifact in artifacts.items()}
            observed = set()
            for entity in session.execute(select(Entity)).scalars():
                name = names[entity.artifact_id]
                source = documents[name]
                assert source[entity.start_offset:entity.end_offset] == entity.value
                if entity.entity_type in {EntityType.EMAIL, EntityType.URL, EntityType.IP_ADDRESS, EntityType.DEVICE_ID, EntityType.PHONE}:
                    observed.add((name, entity.entity_type, entity.value))
            assert observed == expected

            predicted = set()
            for link in session.execute(select(EntityRelationship).where(EntityRelationship.kind == RelationshipKind.RELATED_ARTIFACTS)).scalars():
                pair = frozenset(names[ident] for ident in json.loads(link.artifact_ids_json))
                assert len(pair) == 2
                predicted.add(pair)
                assert json.loads(link.evidence_ids_json) == [evidence.id]
                for item in json.loads(link.details_json)["shared"]:
                    assert all(any(n == name and kind.value == item["type"] and normalize_value(kind, value) == item["value"] for n, kind, value in observed) for name in pair)
            universe = {frozenset(pair) for pair in combinations(documents, 2)}
            tp, fp, fn = len(predicted & relevant), len(predicted - relevant), len(relevant - predicted)
            tn = len(universe - predicted - relevant)
            precision = tp / (tp + fp) if tp + fp else 0.0
            recall = tp / (tp + fn) if tp + fn else 0.0
            assert (tp, fp, fn, tn) == (6, 0, 0, 204)
            assert precision == 1.0 and recall == 1.0
    finally:
        engine.dispose()
