"""Device leads are source-backed occurrences, not device assertions."""
from datetime import datetime

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.artifacts.models import Artifact, Entity, EntityType
from app.auth.models import Case, User, UserRole
from app.db import load_all_models
from app.db.base import Base
from app.devices.models import DeviceEvidenceLink, PhysicalDevice
from app.devices.service import DeviceService
from app.evidence.models import Evidence


def test_candidates_are_scoped_exact_and_never_create_devices():
    load_all_models()
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = User(username="u", email="u@example.com", password_hash="x", full_name="U",
                    role=UserRole.INVESTIGATOR, is_active=True)
        db.add(user)
        db.flush()
        case = Case(case_id="C", title="Case", created_by_id=user.id)
        db.add(case)
        db.flush()
        evidence = Evidence(case_id=case.id, evidence_id="E", name="Image", source_path="x",
                            registered_by_id=user.id)
        db.add(evidence)
        db.flush()
        artifact = Artifact(case_id=case.id, evidence_id=evidence.id, artifact_id="A", name="log",
                            source_path="/log", content_text="MAC aa:bb:cc:dd:ee:ff seen")
        db.add(artifact)
        db.flush()
        for number, start in enumerate((4, 0)):
            db.add(Entity(case_id=case.id, artifact_id=artifact.id, entity_id=f"N{number}",
                          entity_type=EntityType.MAC_ADDRESS, value="aa:bb:cc:dd:ee:ff",
                          start_offset=start, end_offset=start + 17, extractor="regex"))
        db.flush()
        service = DeviceService(db)
        leads = service.identification_candidates(case.id, evidence.id)
        assert len(leads) == 1
        assert leads[0].source_path == "/log"
        assert leads[0].context == artifact.content_text
        assert service.identification_candidates(case.id + 1, evidence.id) == []
        assert list(db.scalars(select(PhysicalDevice))) == []
        assert list(db.scalars(select(DeviceEvidenceLink))) == []
        evidence.removed_at = datetime.now()
        db.flush()
        assert service.identification_candidates(case.id, evidence.id) == []
    engine.dispose()
