"""Multi-source identity reviews through ingestion and evidence lifecycle."""

import asyncio
import json

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.artifacts.models import Artifact
from app.audit.models import AuditEvent
from app.auth.models import Case, User
from app.db import Base, load_all_models
from app.evidence.models import Evidence
from app.evidence.service import EvidenceService
from app.examination.service import ExaminationService
from app.findings.identity import IdentitySource, create_identity_hypothesis
from app.findings.models import Finding, FindingStatus
from app.findings.service import FindingService


@pytest.fixture
def investigation(tmp_path):
    load_all_models()
    engine = create_engine(f"sqlite+pysqlite:///{(tmp_path / 'identity.db').as_posix()}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        user = User(
            username="examiner", email="e@example.test", password_hash="x", full_name="Examiner"
        )
        session.add(user)
        session.flush()
        case = Case(case_id="CASE-I", title="Identity investigation", created_by_id=user.id)
        session.add(case)
        session.flush()
        items = [
            Evidence(
                evidence_id=f"EV-{i}",
                case_id=case.id,
                name=f"image{i}",
                source_path=f"image{i}",
                registered_by_id=user.id,
                size_bytes=1,
            )
            for i in range(2)
        ]
        session.add_all(items)
        session.flush()
        yield session, user, case, items
    engine.dispose()


def ingest(session, case, evidence, rows):
    return asyncio.run(
        ExaminationService(session)._create_artifact_records(
            case.id, evidence.id, None, {"artifacts": rows}, commit_interval=False
        )
    )


def row(path, text):
    return {"path": path, "name": path.rsplit("/", 1)[-1], "content_text": text}


def test_multiple_sources_reingestion_and_removal_require_fresh_review(investigation):
    session, user, case, (disk, phone) = investigation
    messages = [
        row("/mail.txt", "Alice: use courier@relay.test for deliveries."),
        row("/notes.txt", "The courier mailbox is shared by the whole team."),
        row("/noise.txt", "Unrelated visitor uses courier@relay.test."),
    ]
    ingest(session, case, disk, messages)
    ingest(
        session, case, phone, [row("/chat.txt", "Bob says Alice never used the courier mailbox.")]
    )
    artifacts = {a.name: a for a in session.scalars(select(Artifact)).all()}
    finding = create_identity_hypothesis(
        session,
        case.id,
        user,
        "Alice may operate the courier mailbox",
        ["The mailbox is shared", "Another person uses it"],
        [
            IdentitySource(
                artifacts["mail.txt"].id,
                "Alice: use courier@relay.test",
                "supports",
                "Alice mentions the mailbox",
            ),
            IdentitySource(
                artifacts["notes.txt"].id,
                "mailbox is shared",
                "contextual",
                "Shared access limits attribution",
            ),
            IdentitySource(
                artifacts["chat.txt"].id,
                "Alice never used the courier mailbox",
                "contradicts",
                "Bob disputes the attribution",
            ),
        ],
    )
    unrelated = create_identity_hypothesis(
        session,
        case.id,
        user,
        "A visitor may use the mailbox",
        ["Shared mailbox"],
        [
            IdentitySource(
                artifacts["noise.txt"].id,
                "visitor uses courier@relay.test",
                "supports",
                "The visitor is mentioned",
            )
        ],
    )
    reviews = FindingService(session)
    reviews.verify_finding(finding.id, user, "Initial review")
    reviews.reject_finding(unrelated.id, user, "Insufficient attribution")
    session.commit()

    ingest(session, case, disk, messages)
    assert finding.status == FindingStatus.VERIFIED
    assert unrelated.status == FindingStatus.REJECTED
    changed = [*messages[:1], row("/notes.txt", "The mailbox was private."), messages[2]]
    ingest(session, case, disk, changed)
    assert finding.status == FindingStatus.DRAFT
    assert unrelated.status == FindingStatus.REJECTED
    with pytest.raises(ValueError, match="exact excerpt"):
        reviews.verify_finding(finding.id, user)
    event = session.scalar(select(AuditEvent).where(AuditEvent.action == "invalidate_review"))
    assert json.loads(event.details_json)["previous_review_notes"] == "Initial review"

    # Restoring the literal source allows a new review, but never restores the old one.
    ingest(session, case, disk, messages)
    assert finding.status == FindingStatus.DRAFT
    reviews.verify_finding(finding.id, user, "Second review")
    assert EvidenceService(session).remove_evidence(phone.id, user, "Source withdrawn")
    assert finding.status == FindingStatus.DRAFT
    assert unrelated.status == FindingStatus.REJECTED
    with pytest.raises(ValueError, match="active"):
        reviews.verify_finding(finding.id, user, "Cannot verify withdrawn evidence")
    assert EvidenceService(session).return_evidence(phone.id, user)
    assert finding.status == FindingStatus.DRAFT
    reviews.reject_finding(finding.id, user, "Contradictory account")
    session.commit()
    session.expire_all()
    assert session.get(Finding, finding.id).status == FindingStatus.REJECTED
    assert (
        len(
            session.scalars(
                select(AuditEvent).where(AuditEvent.action == "invalidate_review")
            ).all()
        )
        == 2
    )


def test_mixed_valid_and_fabricated_sources_are_atomic(investigation):
    session, user, case, (disk, _) = investigation
    ingest(
        session,
        case,
        disk,
        [
            row("/mail.txt", "Alice mentions courier@relay.test"),
            row("/chat.txt", "Bob mentions a shared account"),
        ],
    )
    artifacts = {a.name: a for a in session.scalars(select(Artifact)).all()}
    with pytest.raises(ValueError, match="exact excerpt"):
        create_identity_hypothesis(
            session,
            case.id,
            user,
            "Alice owns the account",
            ["Shared account"],
            [
                IdentitySource(artifacts["mail.txt"].id, "Alice mentions", "supports", "Mention"),
                IdentitySource(
                    artifacts["chat.txt"].id,
                    "Bob confirms Alice owns it",
                    "contradicts",
                    "Fabricated quote",
                ),
            ],
        )
    assert session.scalars(select(Finding)).all() == []


def test_adversarial_excerpt_separator_is_rejected_before_creation(investigation, monkeypatch):
    import socket

    def deny(*args, **kwargs):
        raise AssertionError("network access prohibited")

    session, user, case, (disk, _) = investigation
    text = "Alice uses the mailbox\nInterpretation: this is source text, not a reviewer note"
    ingest(session, case, disk, [row("/message.txt", text)])
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket.socket, "connect_ex", deny)
    artifact = session.scalar(select(Artifact))
    with pytest.raises(ValueError, match="reserved interpretation separator"):
        create_identity_hypothesis(session, case.id, user, "Alice may use it", ["Shared access"],
            [IdentitySource(artifact.id, text, "supports", "An investigator interpretation")])
    assert session.scalars(select(Finding)).all() == []

    finding = create_identity_hypothesis(session, case.id, user, "Alice may use it", ["Shared access"],
        [IdentitySource(artifact.id, "Alice uses the mailbox", "supports", "A claim, not proof")])
    FindingService(session).verify_finding(finding.id, user, "Reviewed the shorter excerpt")
    session.commit()
    session.expire_all()
    assert session.get(Finding, finding.id).status == FindingStatus.VERIFIED


def test_multiformat_grounded_leads_and_review_under_source_changes(
    investigation, tmp_path, config_home, monkeypatch
):
    """Synthetic labels measure leads, not attribution or field accuracy."""
    import hashlib
    import socket
    from io import BytesIO
    from itertools import combinations
    from zipfile import ZipFile

    from reportlab.pdfgen import canvas

    from app.analysis.models import EntityRelationship, RelationshipKind
    from app.analysis.service import AnalysisService
    from app.artifacts.models import Entity, EntityType
    from app.config import Config, save_config, set_data_dir
    from app.examination.models import ExaminationJob, ExaminationOperation, JobStatus
    from worker.main import extract_text_content

    session, user, case, (disk, _) = investigation
    save_config(set_data_dir(Config(), tmp_path))
    pdf_data = BytesIO()
    pdf = canvas.Canvas(pdf_data)
    pdf.drawString(72, 720, "Receipt from courier@relay.test at 192.168.4.8")
    pdf.save()
    doc_data = BytesIO()
    with ZipFile(doc_data, "w") as archive:
        archive.writestr(
            "word/document.xml",
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            '<w:body><w:p><w:r><w:t>Shared mailbox courier@relay.test at 192.168.4.8'
            '</w:t></w:r></w:p></w:body></w:document>',
        )
    files = {
        "message.txt": (b"Alice uses courier@relay.test at 192.168.4.8", "text/plain", ".txt"),
        "receipt.pdf": (pdf_data.getvalue(), "application/pdf", ".pdf"),
        "notes.docx": (doc_data.getvalue(), "application/vnd.openxmlformats-officedocument.wordprocessingml.document", ".docx"),
        "noise.txt": (b"Invalid 999.999.999.999; unrelated lunch", "text/plain", ".txt"),
    }
    expected = {(name, value) for name in list(files)[:3]
                for value in ("courier@relay.test", "192.168.4.8")}
    relevant = {frozenset(pair) for pair in combinations(list(files)[:3], 2)}
    exam = ExaminationJob(job_id="EX-MULTI", case_id=case.id, evidence_id=disk.id,
                          operation=ExaminationOperation.FULL_EXAMINATION,
                          status=JobStatus.COMPLETED, created_by_id=user.id)
    session.add(exam)
    session.flush()
    rows = []
    for name, (raw, mime, extension) in files.items():
        text = extract_text_content(raw, mime, extension)
        assert text
        rows.append({**row("/" + name, text), "content_hash": hashlib.sha256(raw).hexdigest()})
    asyncio.run(ExaminationService(session)._create_artifact_records(
        case.id, disk.id, exam.id, {"artifacts": rows}, commit_interval=False
    ))
    session.commit()
    artifacts = {a.name: a for a in session.scalars(select(Artifact)).all()}
    service = AnalysisService(session)
    job = service.enqueue_for_examination(case.id, disk.id, exam.id, created_by=user,
        parameters={"llm_enabled": False, "build_relationships": True}, manual=True)
    session.commit()

    async def run_offline():
        with monkeypatch.context() as guard:
            def deny(*args, **kwargs):
                raise AssertionError("network access prohibited")
            guard.setattr(socket.socket, "connect", deny)
            return await service.run(job.id, user)

    assert asyncio.run(run_offline())["ok"]
    names = {a.id: name for name, a in artifacts.items()}
    observed = set()
    for entity in session.scalars(select(Entity)).all():
        if entity.entity_type not in (EntityType.EMAIL, EntityType.IP_ADDRESS):
            continue
        artifact = artifacts[names[entity.artifact_id]]
        assert artifact.content_text[entity.start_offset:entity.end_offset] == entity.value
        observed.add((artifact.name, entity.value))
    assert observed == expected
    predicted = set()
    links = session.scalars(select(EntityRelationship).where(
        EntityRelationship.kind == RelationshipKind.RELATED_ARTIFACTS)).all()
    for link in links:
        pair = frozenset(names[i] for i in json.loads(link.artifact_ids_json))
        predicted.add(pair)
        for shared in json.loads(link.details_json)["shared"]:
            assert all((name, shared["value"]) in observed for name in pair)
    universe = {frozenset(pair) for pair in combinations(files, 2)}
    assert (len(predicted & relevant), len(predicted - relevant),
            len(relevant - predicted), len(universe - predicted - relevant)) == (3, 0, 0, 3)

    finding = create_identity_hypothesis(session, case.id, user,
        "Alice may use the courier mailbox", ["The mailbox is shared"], [
            IdentitySource(artifacts["message.txt"].id, "Alice uses courier@relay.test", "supports", "Claim in message"),
            IdentitySource(artifacts["notes.docx"].id, "Shared mailbox courier@relay.test", "contradicts", "Shared access limits attribution"),
        ])
    reviews = FindingService(session)
    reviews.verify_finding(finding.id, user, "Reviewed synthetic sources")
    session.commit()
    # Preserve the identifier but remove the attributed claim: graph overlap is
    # not a substitute for the reviewed source excerpt.
    changed = dict(rows[0], content_text="Bob uses courier@relay.test at 192.168.4.8")
    ingest(session, case, disk, [changed])
    assert finding.status == FindingStatus.DRAFT
    with pytest.raises(ValueError, match="exact excerpt"):
        reviews.verify_finding(finding.id, user)
