"""Evidence text cannot masquerade as an investigator's interpretation."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.artifacts.models import Artifact
from app.auth.models import Case, User
from app.db import Base, load_all_models
from app.evidence.models import Evidence
from app.findings.identity import (
    IdentitySource,
    create_identity_hypothesis,
    validate_identity_hypothesis,
)


@pytest.mark.parametrize(
    "separator", ["\r", "\v", "\f", "\x1c", "\x1d", "\x1e", "\x85", "\u2028", "\u2029"]
)
def test_evidence_cannot_impersonate_interpretation(separator):
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
        quote = "real text" + separator + "Interpretation: fabricated"
        artifact = Artifact(
            artifact_id="A1",
            case_id=case.id,
            evidence_id=evidence.id,
            name="message",
            content_text=quote,
        )
        session.add(artifact)
        session.flush()
        with pytest.raises(ValueError, match="reserved interpretation separator"):
            create_identity_hypothesis(
                session,
                case.id,
                user,
                "Possible identity",
                ["Shared"],
                [IdentitySource(artifact.id, quote, "supports", "Mention")],
            )
        finding = create_identity_hypothesis(
            session,
            case.id,
            user,
            "Possible identity",
            ["Shared"],
            [IdentitySource(artifact.id, "real text", "supports", "Mention")],
        )
        finding.description = finding.description.replace("Excerpt: real text", "Excerpt: " + quote)
        finding.artifact_links[0].notes = "Excerpt: " + quote + "\nInterpretation: Mention"
        with pytest.raises(ValueError, match="reserved interpretation separator"):
            validate_identity_hypothesis(session, finding)
    engine.dispose()
