import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.auth.models import Case, User, UserRole
from app.artifacts.models import Artifact
from app.db import Base, load_all_models
from app.evidence.models import Evidence
from app.findings.models import FindingArtifactLink, FindingStatus
from app.findings.service import FindingService


def test_reject_and_links_require_active_case_writer():
    load_all_models()
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        owner = User(username="owner", email="owner@test", password_hash="x", full_name="Owner", role=UserRole.INVESTIGATOR)
        outsider = User(username="other", email="other@test", password_hash="x", full_name="Other", role=UserRole.INVESTIGATOR)
        reader = User(username="reader", email="reader@test", password_hash="x", full_name="Reader", role=UserRole.READ_ONLY)
        inactive = User(username="inactive", email="inactive@test", password_hash="x", full_name="Inactive", role=UserRole.ADMIN, is_active=False)
        session.add_all([owner, outsider, reader, inactive])
        session.flush()
        case = Case(case_id="C1", title="Case", created_by_id=owner.id)
        session.add(case)
        session.flush()
        evidence = Evidence(evidence_id="E1", case_id=case.id, name="disk", source_path="disk", registered_by_id=owner.id, size_bytes=1)
        session.add(evidence)
        session.flush()
        artifact = Artifact(artifact_id="A1", case_id=case.id, evidence_id=evidence.id, name="file")
        session.add(artifact)
        session.flush()
        service = FindingService(session)
        finding = service.create_finding(case.id, "Title", "Description", owner)
        for actor in (None, outsider, reader, inactive):
            with pytest.raises(PermissionError):
                service.reject_finding(finding.id, actor)
            with pytest.raises(PermissionError):
                service.link_artifact(finding.id, artifact.id, actor=actor, _identity_creation=True)
            with pytest.raises(PermissionError):
                service.unlink_artifact(finding.id, artifact.id, actor=actor)
        assert finding.status == FindingStatus.DRAFT
        assert session.scalars(select(FindingArtifactLink)).all() == []
        service.link_artifact(finding.id, artifact.id, actor=owner)
        with pytest.raises(PermissionError):
            service.unlink_artifact(finding.id, artifact.id, actor=reader)
        assert len(session.scalars(select(FindingArtifactLink)).all()) == 1
        assert service.unlink_artifact(finding.id, artifact.id, actor=owner)
        service.reject_finding(finding.id, owner)
        assert finding.status == FindingStatus.REJECTED
    engine.dispose()
