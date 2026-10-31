"""Device writes must authorize the persisted user, not a caller-supplied role."""

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.audit.models import AuditEvent
from app.auth.models import Case, User, UserRole
from app.db import Base, load_all_models
from app.devices.models import DeviceEvidenceLink, PhysicalDevice
from app.devices.service import DeviceService
from app.evidence.models import Evidence


def test_fabricated_privileges_cannot_create_or_link():
    load_all_models()
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            admin = User(
                username="admin",
                email="admin@example.test",
                password_hash="x",
                full_name="Admin",
                role=UserRole.INVESTIGATOR,
                is_active=True,
            )
            reader = User(
                username="reader",
                email="reader@example.test",
                password_hash="x",
                full_name="Reader",
                role=UserRole.READ_ONLY,
                is_active=True,
            )
            session.add_all([admin, reader])
            session.flush()
            case = Case(case_id="C1", title="Case", created_by_id=admin.id)
            session.add(case)
            session.flush()
            evidence = Evidence(
                case_id=case.id,
                evidence_id="E1",
                name="Image",
                source_path="image",
                registered_by_id=admin.id,
            )
            session.add(evidence)
            session.flush()
            service = DeviceService(session)
            device = service.create(case.id, admin, "Laptop")
            forged = User(id=reader.id, role=UserRole.INVESTIGATOR, is_active=True)
            with pytest.raises(ValueError, match="active investigator"):
                service.create(case.id, forged, "Forged")
            with pytest.raises(ValueError, match="active investigator"):
                service.link_evidence(case.id, device.id, evidence.id, forged)
            assert len(session.scalars(select(PhysicalDevice)).all()) == 1
            assert session.scalars(select(DeviceEvidenceLink)).all() == []
            assert len(session.scalars(select(AuditEvent)).all()) == 1
            reader.is_active = False
            reader.role = UserRole.INVESTIGATOR
            with pytest.raises(ValueError, match="active investigator"):
                service.create(case.id, forged, "Inactive")
    finally:
        engine.dispose()
