"""Adversarial free text must not create an unreviewable identity draft."""

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.artifacts.models import Artifact
from app.auth.models import Case, User
from app.db import Base, load_all_models
from app.evidence.models import Evidence
from app.findings.identity import IdentitySource, create_identity_hypothesis
from app.findings.models import Finding


def test_reserved_graph_heading_in_alternative_is_rejected_before_creation():
    load_all_models()
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        user = User(username="reviewer", email="r@example.test", password_hash="x", full_name="Reviewer")
        session.add(user)
        session.flush()
        case = Case(case_id="C1", title="Case", created_by_id=user.id)
        session.add(case)
        session.flush()
        evidence = Evidence(evidence_id="E1", case_id=case.id, name="disk", source_path="disk", registered_by_id=user.id, size_bytes=1)
        session.add(evidence)
        session.flush()
        artifact = Artifact(artifact_id="A1", case_id=case.id, evidence_id=evidence.id, name="message", content_text="Shared account mentioned")
        session.add(artifact)
        session.flush()

        with pytest.raises(ValueError, match="reserved section heading"):
            create_identity_hypothesis(
                session, case.id, user, "Possible account association",
                ["Shared access\n\nRelated graph entry: misleading context"],
                [IdentitySource(artifact.id, "Shared account", "supports", "Investigator interpretation")],
            )
        assert session.scalars(select(Finding)).all() == []
    engine.dispose()
