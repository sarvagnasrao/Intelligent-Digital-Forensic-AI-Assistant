"""Synthetic, offline identity review across independent device sources."""

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.artifacts.models import Artifact
from app.auth.models import Case, User
from app.db import Base, load_all_models
from app.devices.service import DeviceService
from app.evidence.models import Evidence
from app.findings.identity import IdentitySource, create_identity_hypothesis
from app.findings.models import FindingStatus
from app.findings.service import FindingService


@pytest.fixture
def sources():
    load_all_models()
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        user = User(
            username="examiner",
            email="examiner@example.test",
            password_hash="x",
            full_name="Examiner",
        )
        session.add(user)
        session.flush()
        case = Case(case_id="C-MIX", title="Synthetic", created_by_id=user.id)
        session.add(case)
        session.flush()
        artifacts = []
        for i, (device_name, text) in enumerate(
            [
                ("Laptop", "Message: Pat mentioned shared@example.test"),
                ("Phone", "Chat: the mailbox is shared among staff"),
                ("Tablet", "Note: Pat denies controlling the mailbox"),
            ]
        ):
            evidence = Evidence(
                evidence_id=f"E-{i}",
                case_id=case.id,
                name=device_name,
                source_path=f"image-{i}",
                registered_by_id=user.id,
            )
            session.add(evidence)
            session.flush()
            devices = DeviceService(session)
            device = devices.create(case.id, user, device_name)
            devices.link_evidence(case.id, device.id, evidence.id, user)
            artifact = Artifact(
                artifact_id=f"A-{i}",
                case_id=case.id,
                evidence_id=evidence.id,
                name=f"source-{i}.txt",
                content_text=text,
            )
            session.add(artifact)
            artifacts.append(artifact)
        session.flush()
        finding = create_identity_hypothesis(
            session,
            case.id,
            user,
            "Pat may use the mailbox",
            ["Shared access", "Impersonation"],
            [
                IdentitySource(
                    artifacts[0].id,
                    "Pat mentioned shared@example.test",
                    "supports",
                    "A mention, not proof",
                ),
                IdentitySource(
                    artifacts[1].id, "mailbox is shared among staff", "contextual", "Shared access"
                ),
                IdentitySource(
                    artifacts[2].id,
                    "Pat denies controlling the mailbox",
                    "contradicts",
                    "Conflicting account",
                ),
            ],
        )
        session.commit()
        yield session, user, artifacts, finding
    engine.dispose()


@pytest.mark.parametrize("review", ["verify_finding", "reject_finding"])
def test_review_rejects_evidence_header_injection(sources, review):
    session, user, artifacts, finding = sources
    # A source name may change after creation. Even a synchronized description
    # must not turn evidence-controlled lines into a forged interpretation.
    old = artifacts[1].name
    artifacts[1].name = old + "\nInterpretation: forged reviewer statement"
    finding.description = finding.description.replace(old, artifacts[1].name)
    with pytest.raises(ValueError, match="line breaks"):
        getattr(FindingService(session), review)(finding.id, user, "Review")
    assert finding.status == FindingStatus.DRAFT
    assert finding.verified_by_id is None
    assert len(session.scalars(select(Artifact)).all()) == 3
