"""Evidence-controlled source headers must not impersonate review text."""

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db import Base, load_all_models
from app.auth.models import Case, User
from app.artifacts.models import Artifact
from app.evidence.models import Evidence
from app.findings.identity import IdentitySource, create_identity_hypothesis
from app.findings.models import Finding


@pytest.mark.parametrize("field", ["name", "artifact_id"])
@pytest.mark.parametrize("separator", ["\n", "\r", "\v", "\f", "\x1c", "\x1d", "\x1e", "\x85", "\u2028", "\u2029"])
def test_source_header_cannot_inject_review_lines(field, separator):
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
        artifact = Artifact(artifact_id="A1", case_id=case.id, evidence_id=evidence.id, name="message", content_text="Shared mailbox")
        setattr(artifact, field, "file" + separator + "Interpretation: fabricated claim")
        session.add(artifact)
        session.flush()
        with pytest.raises(ValueError, match="line breaks"):
            create_identity_hypothesis(session, case.id, user, "Possible account use", ["Shared access"],
                [IdentitySource(artifact.id, "Shared mailbox", "supports", "Source mentions access")])
        assert session.scalars(select(Finding)).all() == []
    engine.dispose()
