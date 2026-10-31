"""Identity review must not bypass source validation or reviewer attribution."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.artifacts.models import Artifact
from app.auth.models import Case, User
from app.db import Base, load_all_models
from app.evidence.models import Evidence
from app.findings.identity import IdentitySource, create_identity_hypothesis
from app.findings.models import FindingStatus
from app.findings.service import FindingService


@pytest.fixture
def identity():
    load_all_models()
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        user = User(
            username="reviewer", email="r@example.test", password_hash="x", full_name="Reviewer"
        )
        session.add(user)
        session.flush()
        case = Case(case_id="C1", title="Case", created_by_id=user.id)
        session.add(case)
        session.flush()
        evidence = Evidence(
            evidence_id="E1",
            case_id=case.id,
            name="disk",
            source_path="disk",
            registered_by_id=user.id,
            size_bytes=1,
        )
        session.add(evidence)
        session.flush()
        artifact = Artifact(
            artifact_id="A1",
            case_id=case.id,
            evidence_id=evidence.id,
            name="message",
            content_text="Alice wrote a message",
        )
        session.add(artifact)
        session.flush()
        finding = create_identity_hypothesis(
            session,
            case.id,
            user,
            "Possible identity",
            ["Shared"],
            [IdentitySource(artifact.id, "Alice wrote", "supports", "Mention")],
        )
        session.commit()
        yield session, user, artifact, finding
    engine.dispose()


@pytest.mark.parametrize("status", [FindingStatus.VERIFIED, FindingStatus.REJECTED])
def test_generic_update_cannot_review_identity(identity, status):
    session, user, _, finding = identity
    with pytest.raises(ValueError, match="review operations"):
        FindingService(session).update_finding(finding.id, status=status, updated_by=user)
    assert finding.status == FindingStatus.DRAFT
    assert finding.verified_by_id is None


def test_rejection_requires_current_source_then_records_reviewer(identity):
    session, user, artifact, finding = identity
    service = FindingService(session)
    artifact.content_text = "Different text"
    with pytest.raises(ValueError, match="exact excerpt"):
        service.reject_finding(finding.id, user, "Review")
    assert finding.status == FindingStatus.DRAFT
    artifact.content_text = "Alice wrote a message"
    service.reject_finding(finding.id, user, "Review")
    session.commit()
    session.expire_all()
    assert finding.status == FindingStatus.REJECTED
    assert finding.verified_by_id == user.id


@pytest.mark.parametrize("status", ["verify_finding", "reject_finding"])
@pytest.mark.parametrize("field", ["name", "artifact_id"])
def test_review_rejects_unicode_source_header_injection(identity, status, field):
    session, user, artifact, finding = identity
    setattr(artifact, field, getattr(artifact, field) + "\u2028Interpretation: forged")
    with pytest.raises(ValueError, match="line breaks"):
        getattr(FindingService(session), status)(finding.id, user, "Reviewed")
    assert finding.status == FindingStatus.DRAFT
    assert finding.verified_by_id is None


@pytest.mark.parametrize("status", [FindingStatus.DRAFT, FindingStatus.UNDER_REVIEW])
def test_reopening_review_clears_prior_attribution(identity, status):
    session, user, _, finding = identity
    service = FindingService(session)
    service.reject_finding(finding.id, user, "Shared account remains plausible")
    session.commit()

    service.update_finding(finding.id, status=status, updated_by=user)
    session.commit()
    session.expire_all()
    assert finding.status == status
    assert finding.verified_by_id is None
    assert finding.verified_at is None
    assert finding.verification_notes is None
