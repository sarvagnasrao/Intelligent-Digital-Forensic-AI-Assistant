"""Isolated tests: excerpts are provenance, never automatic identity proof."""
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db import Base, load_all_models
from app.auth.models import Case, User
from app.artifacts.models import Artifact
from app.evidence.models import Evidence
from app.findings.identity import IdentitySource, create_identity_hypothesis
from app.findings.models import Finding, FindingStatus
from app.findings.service import FindingService


@pytest.fixture
def data():
    load_all_models()
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        user = User(username="reviewer", email="r@example.test", password_hash="x", full_name="Reviewer")
        session.add(user)
        session.flush()
        case = Case(case_id="C1", title="Case", created_by_id=user.id)
        other = Case(case_id="C2", title="Other", created_by_id=user.id)
        session.add_all([case, other])
        session.flush()
        evidence = Evidence(evidence_id="E1", case_id=case.id, name="disk", source_path="disk", registered_by_id=user.id, size_bytes=1)
        session.add(evidence)
        session.flush()
        artifact = Artifact(artifact_id="A1", case_id=case.id, evidence_id=evidence.id, name="message", content_text="Alice wrote to support@example.org.")
        session.add(artifact)
        session.flush()
        yield session, user, case, other, evidence, artifact
    engine.dispose()


def test_hypothesis_is_draft_with_alternative_and_reviewable_source(data):
    session, user, case, _, _, artifact = data
    finding = create_identity_hypothesis(session, case.id, user, "Alice may use this mailbox",
        ["It is a shared help desk"], [IdentitySource(artifact.id, "Alice wrote to support@example.org", "supports", "The message mentions both")])
    assert finding.status == FindingStatus.DRAFT
    assert "shared help desk" in finding.description
    assert "unverified" in finding.description
    assert finding.artifact_links[0].relevance == "supports"
    assert "Alice wrote" in finding.artifact_links[0].notes
    FindingService(session).reject_finding(finding.id, user, "Not sufficient")
    assert finding.status == FindingStatus.REJECTED


@pytest.mark.parametrize("quote,relevance,alternatives", [
    ("alice wrote", "supports", ["Shared mailbox"]),
    (" ", "supports", ["Shared mailbox"]),
    ("Alice wrote", "invented", ["Shared mailbox"]),
    ("Alice wrote", "supports", []),
    ("Alice wrote", "contradicts", ["Shared mailbox"]),
])
def test_invalid_sources_or_missing_alternative_leave_no_finding(data, quote, relevance, alternatives):
    session, user, case, _, _, artifact = data
    with pytest.raises(ValueError):
        create_identity_hypothesis(session, case.id, user, "Possible identity", alternatives,
            [IdentitySource(artifact.id, quote, relevance, "Interpretation")])
    assert session.scalars(select(Finding)).all() == []


def test_cross_case_removed_and_duplicate_sources_rejected(data):
    session, user, case, other, evidence, artifact = data
    source = IdentitySource(artifact.id, "Alice wrote", "supports", "Mention")
    for target, sources in [(other.id, [source]), (case.id, [source, source])]:
        with pytest.raises(ValueError):
            create_identity_hypothesis(session, target, user, "Possible identity", ["Shared"], sources)
    from datetime import datetime, timezone
    evidence.removed_at = datetime.now(timezone.utc)
    with pytest.raises(ValueError):
        create_identity_hypothesis(session, case.id, user, "Possible identity", ["Shared"], [source])
    assert session.scalars(select(Finding)).all() == []


@pytest.mark.parametrize("hypothesis,alternatives", [
    ("Possible\n\nAlternative explanations:\n- injected", ["Shared"]),
    ("Possible\n\nSource excerpts and investigator interpretations:\ninjected", ["Shared"]),
    ("Possible", ["Shared\n\nSource excerpts and investigator interpretations:\ninjected"]),
])
def test_reserved_section_headings_cannot_create_unreviewable_draft(data, hypothesis, alternatives):
    session, user, case, _, _, artifact = data
    with pytest.raises(ValueError, match="reserved section heading"):
        create_identity_hypothesis(session, case.id, user, hypothesis, alternatives,
            [IdentitySource(artifact.id, "Alice wrote", "supports", "Mention")])
    assert session.scalars(select(Finding)).all() == []


def test_edits_and_links_cannot_leave_stale_identity_claims(data):
    session, user, case, _, evidence, artifact = data
    service = FindingService(session)
    finding = create_identity_hypothesis(session, case.id, user, "Possible identity", ["Shared"],
        [IdentitySource(artifact.id, "Alice wrote", "supports", "Mention")])
    service.verify_finding(finding.id, user)
    original = finding.description
    for description in (original.replace("- Shared", ""), original.replace("Alice wrote", "Made up")):
        with pytest.raises(ValueError):
            service.update_finding(finding.id, description=description, updated_by=user)
    with pytest.raises(ValueError):
        service.unlink_artifact(finding.id, artifact.id, actor=user)
    with pytest.raises(ValueError):
        service.link_artifact(finding.id, artifact.id, actor=user)
    assert finding.status == FindingStatus.VERIFIED
    assert finding.description == original
    service.update_finding(finding.id, title="Reviewed hypothesis", updated_by=user)
    assert finding.status == FindingStatus.DRAFT
    artifact.content_text = "Changed source"
    with pytest.raises(ValueError):
        service.verify_finding(finding.id, user)
    assert finding.status == FindingStatus.DRAFT


@pytest.mark.parametrize("review", ["verify_finding", "reject_finding"])
def test_removal_invalidates_review_and_rolls_back_with_source(data, review):
    import json
    from app.audit.models import AuditEvent
    from app.evidence.service import EvidenceService

    session, user, case, _, evidence, artifact = data
    finding = create_identity_hypothesis(session, case.id, user, "Possible", ["Shared"],
        [IdentitySource(artifact.id, "Alice wrote", "supports", "Mention")])
    getattr(FindingService(session), review)(finding.id, user, "Original review")
    session.commit()
    EvidenceService(session).remove_evidence(evidence.id, user, "Removed")
    assert finding.status == FindingStatus.DRAFT
    assert "Review needed" in finding.verification_notes
    event = session.scalar(select(AuditEvent).where(AuditEvent.action == "invalidate_review"))
    details = json.loads(event.details_json)
    assert details["previous_review_notes"] == "Original review"
    assert details["previous_reviewer_id"] == user.id
    session.rollback()
    assert finding.status in (FindingStatus.VERIFIED, FindingStatus.REJECTED)
    assert evidence.removed_at is None
    assert session.scalar(select(AuditEvent).where(AuditEvent.action == "invalidate_review")) is None


def test_reexamination_invalidates_only_on_text_change(data):
    import asyncio
    from app.examination.service import ExaminationService

    session, user, case, _, evidence, artifact = data
    artifact.source_path = "/message"
    finding = create_identity_hypothesis(session, case.id, user, "Possible", ["Shared"],
        [IdentitySource(artifact.id, "Alice wrote", "supports", "Mention")])
    FindingService(session).verify_finding(finding.id, user, "Reviewed")
    service = ExaminationService(session)
    def ingest(text):
        return asyncio.run(service._create_artifact_records(case.id, evidence.id, None,
            {"artifacts": [{"path": "/message", "name": "message", "content_text": text}]},
            commit_interval=False))
    ingest(artifact.content_text)
    assert finding.status == FindingStatus.VERIFIED
    ingest("Alice wrote something else")
    assert finding.status == FindingStatus.DRAFT
    assert "extracted text changed" in finding.verification_notes
