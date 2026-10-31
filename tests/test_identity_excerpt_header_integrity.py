"""Literal evidence must not impersonate additional source records."""

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db import Base, load_all_models
from app.auth.models import Case, User
from app.artifacts.models import Artifact
from app.evidence.models import Evidence
from app.findings.identity import IdentitySource, create_identity_hypothesis, validate_identity_hypothesis
from app.findings.models import Finding


@pytest.mark.parametrize("separator", ["\n", "\r", "\u2028"])
def test_excerpt_cannot_impersonate_another_source(separator):
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
        quote = "real text" + separator + "[supports] A999: fabricated source"
        artifact = Artifact(artifact_id="A1", case_id=case.id, evidence_id=evidence.id, name="message", content_text=quote)
        session.add(artifact)
        session.flush()
        with pytest.raises(ValueError, match="reserved source header"):
            create_identity_hypothesis(session, case.id, user, "Possible identity", ["Shared"],
                                       [IdentitySource(artifact.id, quote, "supports", "Mention")])
        assert session.scalars(select(Finding)).all() == []

        finding = create_identity_hypothesis(session, case.id, user, "Possible identity", ["Shared"],
                                             [IdentitySource(artifact.id, "real text", "supports", "Mention")])
        finding.description = finding.description.replace("Excerpt: real text", "Excerpt: " + quote)
        finding.artifact_links[0].notes = "Excerpt: " + quote + "\nInterpretation: Mention"
        with pytest.raises(ValueError, match="reserved source header"):
            validate_identity_hypothesis(session, finding)
    engine.dispose()
