"""Physical devices are explicit assertions, scoped to a case."""

import importlib

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, event, inspect, select
from sqlalchemy.orm import Session

from app.audit.models import AuditEvent
from app.auth.models import Case, User, UserRole
from app.db import load_all_models
from app.db.base import Base
from app.devices.models import DeviceEvidenceLink
from app.devices.service import DeviceService
from app.evidence.models import Evidence


@pytest.fixture
def db():
    load_all_models()
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        yield session
    engine.dispose()


def test_manual_devices_and_case_scoped_links(db):
    user = User(
        username="a",
        email="a@b",
        password_hash="x",
        full_name="A",
        role=UserRole.INVESTIGATOR,
        is_active=True,
    )
    db.add(user)
    db.flush()
    one = Case(case_id="one", title="One", created_by_id=user.id)
    two = Case(case_id="two", title="Two", created_by_id=user.id)
    db.add_all([one, two])
    db.flush()
    evidence = Evidence(
        case_id=one.id,
        evidence_id="E001",
        name="Image",
        source_path="image.dd",
        registered_by_id=user.id,
    )
    other = Evidence(
        case_id=two.id,
        evidence_id="E001",
        name="Other",
        source_path="other.dd",
        registered_by_id=user.id,
    )
    db.add_all([evidence, other])
    db.flush()
    service = DeviceService(db)
    device = service.create(one.id, user, " Laptop ", serial_number=" S1 ")
    assert device.label == "Laptop"
    assert device.serial_number == "S1"
    assert service.list_devices(two.id) == []
    assert service.linked_evidence(one.id, device.id) == []
    with pytest.raises(ValueError, match="active case"):
        service.link_evidence(one.id, device.id, other.id, user)
    service.link_evidence(one.id, device.id, evidence.id, user)
    service.link_evidence(one.id, device.id, evidence.id, user)
    assert service.linked_evidence(one.id, device.id) == [evidence]
    assert len(list(db.scalars(select(DeviceEvidenceLink)))) == 1
    assert len(list(db.scalars(select(AuditEvent)))) == 2
    user.role = UserRole.READ_ONLY
    with pytest.raises(ValueError, match="active investigator"):
        service.create(one.id, user, "No")


def test_device_migration_upgrade_and_downgrade():
    migration = importlib.import_module("migrations.versions.007_physical_devices")
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        operations = Operations(MigrationContext.configure(connection))
        original = migration.op
        migration.op = operations
        try:
            migration.upgrade()
            assert "physical_devices" in inspect(connection).get_table_names()
            assert "device_evidence_links" in inspect(connection).get_table_names()
            migration.downgrade()
            assert "physical_devices" not in inspect(connection).get_table_names()
        finally:
            migration.op = original
    engine.dispose()
