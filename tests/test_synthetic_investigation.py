"""Synthetic, service-free investigation; the session is an in-memory test double."""
import asyncio
import hashlib
from types import SimpleNamespace

from app.analysis.extractors import content_entities_for_artifact
from app.analysis.relationships import RelationshipBuilder, RelationshipStats
from app.artifacts.models import Artifact, Entity, EntityType, IndexStatus
from app.db import load_all_models
from app.examination.service import ExaminationService
from worker.main import extract_text_content

load_all_models()


class Result:
    def __init__(self, rows):
        self.rows = rows

    def scalars(self):
        return self

    def all(self):
        return self.rows

    def __iter__(self):
        return iter(self.rows)


class MemorySession:
    def __init__(self):
        self.artifacts = []
        self.entities = []
        self.deleted = []
        self.new = set()
        self._snapshots = {}

    @property
    def dirty(self):
        # Track scalar changes to flushed artifacts, as Session.dirty does.
        return {
            item for item in self.artifacts
            if item in self._snapshots and self._artifact_values(item) != self._snapshots[item]
        }

    @staticmethod
    def _artifact_values(item):
        return tuple(getattr(item, column.key) for column in Artifact.__table__.columns)

    def execute(self, statement):
        self.flush()  # Session.execute() autoflushes pending changes.
        if statement.is_delete:
            self.deleted.append(statement.table.name)
            # The test re-examines one artifact at a time.
            if statement.table.name == Entity.__tablename__:
                self.entities.clear()
            else:
                for artifact in self.artifacts:
                    artifact.chunks.clear()
            return Result([])
        if statement.column_descriptions[0].get("entity") is Entity:
            return Result(self.entities)
        if (len(statement.column_descriptions) == 1
                and statement.column_descriptions[0].get("entity") is Artifact):
            rows = self.artifacts
            for criterion in statement._where_criteria:
                key = getattr(criterion.left, "key", None)
                value = criterion.right.value
                if key == "evidence_id":
                    rows = [row for row in rows if row.evidence_id == value]
                elif key == "source_path":
                    rows = [row for row in rows if row.source_path in value]
                else:
                    raise AssertionError(f"Unsupported artifact filter: {criterion}")
            return Result(rows)
        if (
            len(statement.column_descriptions) == 2
            and statement.column_descriptions[1].get("name") == "content_text"
        ):
            return Result([(artifact.id, artifact.content_text) for artifact in self.artifacts])
        if len(statement.column_descriptions) > 1:
            return Result(self.artifacts)
        return Result(self.artifacts)

    def scalars(self, statement):
        # This test double contains no findings to invalidate on re-extraction.
        return Result([])

    def add(self, item):
        if isinstance(item, Artifact):
            item.id = len(self.artifacts) + 1
            self.artifacts.append(item)
            self.new.add(item)

    def flush(self):
        self.new.clear()
        self._snapshots = {item: self._artifact_values(item) for item in self.artifacts}

    def commit(self):
        self.flush()

    def rollback(self):
        pass


def ingest(session, rows):
    service = ExaminationService.__new__(ExaminationService)
    service.session = session
    service.config = SimpleNamespace(embeddings=SimpleNamespace(chunk_size=32))
    service._next_artifact_number = lambda _: len(session.artifacts) + 1
    return asyncio.run(service._create_artifact_records(1, 7, 9, {"artifacts": rows}))


def worker_row(name, data):
    return {
        "name": name, "path": "/evidence/" + name, "size": len(data),
        "content_hash": hashlib.sha256(data).hexdigest(),
        "content_text": extract_text_content(data, "text/plain", ".txt"),
    }


def test_planted_leads_are_ingested_source_backed_and_linked():
    sources = [
        b"Contact courier@relay.test at 2024-05-17T09:30:00Z; transfer 192.168.4.8.",
        b"Receipt from courier@relay.test; transfer 192.168.4.8.",
        b"Routine note: address 999.999.999.999 and hash 00000000000000000000000000000000.",
    ]
    session = MemorySession()
    rows = [worker_row(f"item{i}.txt", source) for i, source in enumerate(sources)]
    assert ingest(session, rows) == {"created": 3, "updated": 0}
    for artifact, source in zip(session.artifacts, sources, strict=True):
        assert artifact.content_text == source.decode()
        assert "".join(chunk.text for chunk in artifact.chunks) == artifact.content_text
        for extracted in content_entities_for_artifact(artifact):
            field = extracted.metadata.get("field", "content_text")
            assert extracted.value in getattr(artifact, field)[extracted.start:extracted.end]
            session.entities.append(Entity(
                id=len(session.entities) + 1, case_id=1, artifact_id=artifact.id,
                entity_type=extracted.entity_type, value=extracted.value,
                normalized_value=extracted.normalized,
            ))
    by_artifact = {a.id: {e.value for e in session.entities if e.artifact_id == a.id}
                   for a in session.artifacts}
    assert {"courier@relay.test", "192.168.4.8"} <= by_artifact[1] & by_artifact[2]
    assert "2024-05-17T09:30:00Z" in by_artifact[1]
    assert "999.999.999.999" not in by_artifact[3]
    assert not any(e.entity_type is EntityType.HASH for e in session.entities)
    builder = RelationshipBuilder(session, 1)
    builder._evidence_ids = lambda ids: [7]
    entity_pairs, artifact_pairs = builder._collect_pairs(RelationshipStats())
    assert any(set(p["artifact_ids"]) == {1, 2} for p in entity_pairs.values())
    related = [p for p in artifact_pairs.values() if set(p["artifact_ids"]) == {1, 2}]
    assert len(related) == 1
    assert {v["value"] for v in related[0]["details"]["shared"]} >= {
        "courier@relay.test", "192.168.4.8"
    }
    assert not any(3 in p["artifact_ids"] for p in artifact_pairs.values())


def test_reextraction_same_bytes_invalidates_old_derived_text():
    session = MemorySession()
    row = worker_row("lead.txt", b"courier@relay.test")
    row["content_text"] = None
    ingest(session, [row])
    artifact = session.artifacts[0]
    artifact.index_status = IndexStatus.INDEXED
    artifact.vector_id = "stale"
    row["content_text"] = "courier@relay.test"
    assert ingest(session, [row]) == {"created": 0, "updated": 1}
    assert artifact.index_status is IndexStatus.NOT_INDEXED
    assert artifact.vector_id is None
    assert "".join(chunk.text for chunk in artifact.chunks) == row["content_text"]
    assert Entity.__tablename__ in session.deleted


def test_disposable_sqlite_multiformat_investigation(tmp_path, config_home):
    """Three planted document leads, distractors, and a persisted graph rebuild."""
    import json
    from io import BytesIO
    from zipfile import ZipFile

    from reportlab.pdfgen import canvas
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session

    from app.analysis.models import EntityRelationship, RelationshipKind, RelationshipStatus
    from app.analysis.service import AnalysisService
    from app.artifacts.models import ArtifactType
    from app.auth.models import Case, User
    from app.config import Config, save_config, set_data_dir
    from app.db import Base
    from app.evidence.models import Evidence
    from app.examination.models import ExaminationJob, ExaminationOperation, JobStatus

    save_config(set_data_dir(Config(), tmp_path))
    engine = create_engine(f"sqlite+pysqlite:///{(tmp_path / 'investigation.db').as_posix()}")
    Base.metadata.create_all(engine)
    pdf_bytes = BytesIO()
    pdf = canvas.Canvas(pdf_bytes)
    pdf.drawString(72, 720, "Contact courier@relay.test for delivery")
    pdf.save()
    doc_bytes = BytesIO()
    with ZipFile(doc_bytes, "w") as archive:
        archive.writestr("word/document.xml", '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Contact courier@relay.test for delivery</w:t></w:r></w:p></w:body></w:document>')
    files = [
        ("lead.txt", b"Contact courier@relay.test and dispatch@relay.test", "text/plain", ".txt"),
        ("lead.pdf", pdf_bytes.getvalue(), "application/pdf", ".pdf"),
        ("lead.docx", doc_bytes.getvalue(), "application/vnd.openxmlformats-officedocument.wordprocessingml.document", ".docx"),
        ("noise.txt", b"Invalid 999.999.999.999 hash 00000000000000000000000000000000", "text/plain", ".txt"),
    ]
    try:
        with Session(engine, expire_on_commit=False) as session:
            user = User(username="synthetic", email="test@example.test", password_hash="x", full_name="Test")
            session.add(user)
            session.flush()
            case = Case(case_id="C-SYN", title="Synthetic", created_by_id=user.id)
            session.add(case)
            session.flush()
            evidence = Evidence(evidence_id="E-SYN", case_id=case.id, name="disk", source_path="synthetic", registered_by_id=user.id, size_bytes=1)
            session.add(evidence)
            session.flush()
            exam = ExaminationJob(job_id="EX-SYN", case_id=case.id, evidence_id=evidence.id, operation=ExaminationOperation.FULL_EXAMINATION, status=JobStatus.COMPLETED, created_by_id=user.id)
            session.add(exam)
            session.flush()
            artifacts = []
            for index, (name, raw, mime, extension) in enumerate(files):
                text = extract_text_content(raw, mime, extension)
                assert text is not None
                artifact = Artifact(artifact_id=f"ART-{index}", case_id=case.id, evidence_id=evidence.id, examination_job_id=exam.id, artifact_type=ArtifactType.FILE, name=name, source_path=f"/evidence/{name}", content_text=text, content_hash=hashlib.sha256(raw).hexdigest())
                session.add(artifact)
                artifacts.append(artifact)
            session.commit()
            service = AnalysisService(session)
            job = service.enqueue_for_examination(case.id, evidence.id, exam.id, created_by=user, parameters={"llm_enabled": False, "build_relationships": True}, manual=True)
            session.commit()
            assert asyncio.run(service.run(job.id, user))["ok"]
            entities = session.execute(select(Entity)).scalars().all()
            for artifact in artifacts[:3]:
                assert any(e.artifact_id == artifact.id and e.value == "courier@relay.test" and artifact.content_text[e.start_offset:e.end_offset] == e.value for e in entities)
            assert not any(e.value in {"999.999.999.999", "00000000000000000000000000000000"} for e in entities)
            relationships = session.execute(select(EntityRelationship)).scalars().all()
            links = [r for r in relationships if r.kind == RelationshipKind.RELATED_ARTIFACTS]
            assert len(links) == 3
            assert all(artifacts[3].id not in json.loads(r.artifact_ids_json) for r in links)
            strong = next(r for r in relationships if r.kind == RelationshipKind.SHARED_ENTITY and {r.left_value, r.right_value} == {"courier@relay.test", "dispatch@relay.test"})
            assert json.loads(strong.artifact_ids_json) == [artifacts[0].id]
            strong.status = RelationshipStatus.CONFIRMED
            session.commit()
            RelationshipBuilder(session, case.id).rebuild()
            session.commit()
            assert session.get(EntityRelationship, strong.id).status == RelationshipStatus.CONFIRMED
            assert len(session.execute(select(EntityRelationship)).scalars().all()) == len(relationships)
    finally:
        engine.dispose()


def test_role_mailbox_link_benchmark(monkeypatch):
    """Labeled candidate pairs from synthetic text; no external services or data.

    Relevance is a planted investigative lead, not proof of wrongdoing. This
    small, deliberately challenging corpus is not a population accuracy claim.
    """
    import app.analysis.relationships as rules

    documents = {
        "dispatch": "Send courier@relay.test. Contact help@office.test.",
        "receipt": "Received from courier@relay.test; help@office.test.",
        "policy": "For assistance use help@office.test.",
        "manual": "Support: help@office.test.",
        "invoice": "Pay accounts@vendor.test.",
        "payment": "Paid accounts@vendor.test.",
        "ticket": "Assigned to help.person@office.test.",
        "reply": "Reply from help.person@office.test.",
        "other": "Contact support@office.test.",
        "faq": "Contact support@office.test.",
    }
    relevant = {frozenset(pair) for pair in [
        ("dispatch", "receipt"), ("invoice", "payment"), ("ticket", "reply"),
    ]}
    session = MemorySession()
    names = {}
    for number, (name, text) in enumerate(documents.items(), 1):
        artifact = Artifact(id=number, artifact_id=f"ART-{number}", case_id=1,
                            name=name, source_path=f"/synthetic/{name}",
                            content_text=text, evidence_id=7)
        session.artifacts.append(artifact)
        names[number] = name
        for item in content_entities_for_artifact(artifact):
            field = item.metadata.get("field", "content_text")
            assert getattr(artifact, field)[item.start:item.end] == item.value
            session.entities.append(Entity(id=len(session.entities) + 1, case_id=1,
                artifact_id=number, entity_type=item.entity_type, value=item.value,
                normalized_value=item.normalized))

    builder = RelationshipBuilder(session, 1)
    builder._evidence_ids = lambda ids: [7]

    def predictions():
        _, links = builder._collect_pairs(RelationshipStats())
        result = {}
        for link in links.values():
            pair = frozenset(names[ident] for ident in link["artifact_ids"])
            for value in link["details"]["shared"]:
                assert all(value["value"] in documents[name].lower() for name in pair)
            result[pair] = link
        return result

    with monkeypatch.context() as baseline:
        baseline.setattr(rules, "_generic_role_mailbox", lambda key: False)
        before = predictions()
    after = predictions()

    def counts(predicted):
        pairs = set(predicted)
        return len(pairs & relevant), len(pairs - relevant), len(relevant - pairs)

    assert counts(before) == (3, 6, 0)  # precision 3/9, recall 3/3
    assert counts(after) == (3, 0, 0)   # precision 3/3, recall 3/3
    corroborated = after[frozenset(("dispatch", "receipt"))]["details"]["shared"]
    assert {item["value"] for item in corroborated} == {
        "courier@relay.test", "help@office.test"
    }


def test_labeled_investigative_leads_precision_recall(tmp_path, config_home, monkeypatch):
    """Score candidate links, not just extraction: common contacts are distractors.

    Ground truth is an investigator-defined connection between documents, not a
    claim that every shared identifier proves criminal activity. All documents
    and labels are synthetic; this is a small regression corpus, not a field
    accuracy estimate.
    """
    import json
    import socket
    from itertools import combinations

    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session

    from app.analysis.models import EntityRelationship, RelationshipKind
    from app.analysis.service import AnalysisService
    from app.artifacts.models import ArtifactType
    from app.auth.models import Case, User
    from app.config import Config, save_config, set_data_dir
    from app.db import Base
    from app.evidence.models import Evidence
    from app.examination.models import ExaminationJob, ExaminationOperation, JobStatus

    def no_network(*args, **kwargs):
        raise AssertionError("synthetic evaluation must not contact a service")

    save_config(set_data_dir(Config(), tmp_path))
    # Each expected identifier occurrence is independently labeled by source.
    documents = {
        "message.txt": ("Dispatch courier@relay.test via 192.168.4.8. Help desk help@office.test.",
                        {"courier@relay.test", "192.168.4.8", "help@office.test"}),
        "receipt.txt": ("Received by courier@relay.test from 192.168.4.8.",
                        {"courier@relay.test", "192.168.4.8"}),
        "log.txt": ("Connection to 192.168.4.8 recorded.", {"192.168.4.8"}),
        "invoice.txt": ("Billing contact accounts@vendor.test.", {"accounts@vendor.test"}),
        "payment.txt": ("Paid accounts@vendor.test for materials.", {"accounts@vendor.test"}),
        "policy.txt": ("For assistance email help@office.test.", {"help@office.test"}),
        "noise.txt": ("Invalid address 999.999.999.999 and digest 00000000000000000000000000000000.", set()),
        "unrelated.txt": ("Lunch inventory: tea and biscuits.", set()),
    }
    relevant = {
        frozenset(pair) for pair in [
            ("message.txt", "receipt.txt"), ("message.txt", "log.txt"),
            ("receipt.txt", "log.txt"), ("invoice.txt", "payment.txt"),
        ]
    }
    engine = create_engine(f"sqlite+pysqlite:///{(tmp_path / 'leads.db').as_posix()}")
    Base.metadata.create_all(engine)
    try:
        with Session(engine, expire_on_commit=False) as session:
            user = User(username="lead-test", email="lead@example.test", password_hash="x", full_name="Test")
            session.add(user)
            session.flush()
            case = Case(case_id="C-LEADS", title="Synthetic leads", created_by_id=user.id)
            session.add(case)
            session.flush()
            evidence = Evidence(evidence_id="E-LEADS", case_id=case.id, name="disk", source_path="synthetic", registered_by_id=user.id, size_bytes=1)
            session.add(evidence)
            session.flush()
            exam = ExaminationJob(job_id="EX-LEADS", case_id=case.id, evidence_id=evidence.id, operation=ExaminationOperation.FULL_EXAMINATION, status=JobStatus.COMPLETED, created_by_id=user.id)
            session.add(exam)
            session.flush()
            artifacts = {}
            for index, (name, (text, _)) in enumerate(documents.items()):
                raw = text.encode()
                extracted = extract_text_content(raw, "text/plain", ".txt")
                assert extracted == text
                artifact = Artifact(artifact_id=f"ART-LEAD-{index}", case_id=case.id, evidence_id=evidence.id, examination_job_id=exam.id, artifact_type=ArtifactType.FILE, name=name, source_path=f"/evidence/{name}", content_text=extracted, content_hash=hashlib.sha256(raw).hexdigest())
                session.add(artifact)
                artifacts[name] = artifact
            session.commit()
            service = AnalysisService(session)
            job = service.enqueue_for_examination(case.id, evidence.id, exam.id, created_by=user, parameters={"llm_enabled": False, "build_timeline": True, "build_relationships": True}, manual=True)
            session.commit()
            async def run_offline():
                # Windows asyncio constructs its own loopback socket pair first.
                with monkeypatch.context() as guard:
                    guard.setattr(socket.socket, "connect", no_network)
                    return await service.run(job.id, user)

            assert asyncio.run(run_offline())["ok"]

            entities = session.execute(select(Entity)).scalars().all()
            ids_to_names = {artifact.id: name for name, artifact in artifacts.items()}
            observed = set()
            for entity in entities:
                if entity.entity_type not in (EntityType.EMAIL, EntityType.IP_ADDRESS):
                    continue
                name = ids_to_names[entity.artifact_id]
                text = documents[name][0]
                assert entity.start_offset is not None and entity.end_offset is not None
                assert text[entity.start_offset:entity.end_offset] == entity.value
                observed.add((name, entity.value))
            expected = {(name, value) for name, (_, values) in documents.items() for value in values}
            assert observed == expected

            links = session.execute(select(EntityRelationship).where(EntityRelationship.kind == RelationshipKind.RELATED_ARTIFACTS)).scalars().all()
            predicted = set()
            for link in links:
                ids = json.loads(link.artifact_ids_json)
                assert len(ids) == 2
                names = frozenset(ids_to_names[item] for item in ids)
                predicted.add(names)
                shared = json.loads(link.details_json)["shared"]
                assert shared
                for item in shared:
                    assert all((name, item["value"]) in observed for name in names)
            universe = {frozenset(pair) for pair in combinations(documents, 2)}
            tp, fp, fn = len(predicted & relevant), len(predicted - relevant), len(relevant - predicted)
            tn = len(universe - predicted - relevant)
            assert (tp, fp, fn, tn) == (4, 0, 0, 24)
            assert tp / (tp + fp) == 1.0
            assert tp / (tp + fn) == 1.0
    finally:
        engine.dispose()
