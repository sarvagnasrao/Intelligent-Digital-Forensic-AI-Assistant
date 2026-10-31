"""Offline source-backed review survives failed lifecycle transactions correctly."""

import socket

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.artifacts.models import Artifact
from app.audit.models import AuditEvent
from app.auth.models import Case, User
from app.db import Base, load_all_models
from app.evidence.models import Evidence
from app.evidence.service import EvidenceService
from app.findings.identity import IdentitySource, create_identity_hypothesis
from app.findings.models import Finding, FindingStatus
from app.findings.service import FindingService


@pytest.mark.parametrize("review", ["verify_finding", "reject_finding"])
def test_withdrawal_rollback_preserves_review_and_audit(tmp_path, monkeypatch, review):
    def deny(*args, **kwargs):
        raise AssertionError("network access prohibited")

    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket.socket, "connect_ex", deny)
    load_all_models()
    engine = create_engine(f"sqlite+pysqlite:///{(tmp_path / 'case.db').as_posix()}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        user = User(username="reviewer", email="reviewer@example.test", password_hash="x", full_name="Reviewer")
        session.add(user)
        session.flush()
        case = Case(case_id="CASE", title="Synthetic", created_by_id=user.id)
        session.add(case)
        session.flush()
        evidence = Evidence(evidence_id="EV", case_id=case.id, name="disk", source_path="synthetic", registered_by_id=user.id, size_bytes=1)
        session.add(evidence)
        session.flush()
        artifact = Artifact(artifact_id="A", case_id=case.id, evidence_id=evidence.id, name="message.txt", content_text="A mailbox is shared by several people.")
        session.add(artifact)
        session.flush()
        finding = create_identity_hypothesis(session, case.id, user, "Someone may use the mailbox", ["Shared access"], [IdentitySource(artifact.id, "mailbox is shared", "supports", "A source statement")])
        getattr(FindingService(session), review)(finding.id, user, "Original review")
        session.commit()
        finding_id, evidence_id = finding.id, evidence.id
        original_status = finding.status

        assert EvidenceService(session).remove_evidence(evidence_id, user, "Withdrawn")
        assert finding.status == FindingStatus.DRAFT
        assert session.scalar(select(AuditEvent).where(AuditEvent.action == "invalidate_review"))
        session.rollback()

    with Session(engine) as session:
        finding = session.get(Finding, finding_id)
        assert finding.status == original_status
        assert finding.verification_notes == "Original review"
        assert session.get(Evidence, evidence_id).removed_at is None
        assert session.scalar(select(AuditEvent).where(AuditEvent.action == "invalidate_review")) is None
    engine.dispose()
