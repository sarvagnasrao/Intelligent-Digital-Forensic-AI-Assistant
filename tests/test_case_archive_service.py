"""Reversible case archiving must preserve forensic provenance and permissions."""
from __future__ import annotations

import json

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.audit.models import AuditEvent
from app.auth.models import Case, User, UserRole
from app.auth.service import AuthService
from app.cases.service import CaseService
from app.db import load_all_models
from app.db.base import Base
from app.evidence.models import CustodyEvent, Evidence, EvidenceHash, HashAlgorithm


@pytest.fixture
def forensic_session():
    load_all_models()
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            admin = User(
                username="admin", email="admin@example.test", password_hash="hash",
                full_name="Admin", role=UserRole.ADMIN, is_active=True,
            )
            investigator = User(
                username="investigator", email="investigator@example.test", password_hash="hash",
                full_name="Investigator", role=UserRole.INVESTIGATOR, is_active=True,
            )
            reader = User(
                username="reader", email="reader@example.test", password_hash="hash",
                full_name="Reader", role=UserRole.READ_ONLY, is_active=True,
            )
            inactive = User(
                username="disabled", email="disabled@example.test", password_hash="hash",
                full_name="Disabled", role=UserRole.ADMIN, is_active=False,
            )
            session.add_all([admin, investigator, reader, inactive])
            session.flush()
            case = Case(
                case_id="CASE-ARCHIVE-SYNTHETIC", title="Synthetic case",
                created_by_id=admin.id, assignee_id=investigator.id, status="active",
            )
            session.add(case)
            session.flush()
            evidence = Evidence(
                evidence_id="E-001", case_id=case.id, name="Synthetic image",
                source_path="synthetic-not-a-real-file.img", stored_path=None,
                size_bytes=4, registered_by_id=admin.id,
            )
            session.add(evidence)
            session.flush()
            content_hash = EvidenceHash(
                evidence_id=evidence.id, algorithm=HashAlgorithm.SHA256,
                hash_value="ab" * 32, is_reference=True, calculated_by_id=admin.id,
            )
            custody = CustodyEvent(
                evidence_id=evidence.id, event_type="registered",
                description="Synthetic evidence registered", performed_by_id=admin.id,
            )
            session.add_all([content_hash, custody])
            session.commit()
            yield session, admin, investigator, reader, inactive, case, evidence, custody, content_hash
    finally:
        engine.dispose()


def test_archiving_preserves_evidence_hashes_custody_and_case_linked_audits(forensic_session):
    session, admin, _, _, _, case, evidence, custody, content_hash = forensic_session
    case_id = case.id
    service = CaseService(session)
    assert service.archive_case(case_id, admin, reason="Investigation completed")
    session.commit()
    session.expire_all()

    preserved_case = session.get(Case, case_id)
    assert preserved_case is not None
    assert preserved_case.archived_at is not None
    assert preserved_case.archived_by_id == admin.id
    assert preserved_case.archive_reason == "Investigation completed"
    assert session.get(Evidence, evidence.id).case_id == case_id
    assert session.get(EvidenceHash, content_hash.id).evidence_id == evidence.id
    assert session.get(CustodyEvent, custody.id).evidence_id == evidence.id

    events = session.execute(
        select(AuditEvent).where(AuditEvent.case_id == case_id, AuditEvent.action == "archive")
    ).scalars().all()
    assert len(events) == 1
    assert events[0].user_id == admin.id
    assert json.loads(events[0].details_json)["case_reference"] == "CASE-ARCHIVE-SYNTHETIC"


def test_archive_restore_and_repeated_actions_are_idempotent(forensic_session):
    session, admin, _, _, _, case, *_ = forensic_session
    service = CaseService(session)
    assert service.archive_case(case.id, admin, "synthetic reason")
    assert not service.archive_case(case.id, admin, "ignored duplicate")
    assert service.restore_case(case.id, admin)
    assert not service.restore_case(case.id, admin)
    session.commit()
    session.expire_all()
    assert session.get(Case, case.id).archived_at is None

    audit = session.execute(
        select(AuditEvent).where(AuditEvent.case_id == case.id)
        .order_by(AuditEvent.id)
    ).scalars().all()
    assert [event.action for event in audit] == ["archive", "restore"]


def test_archive_restoration_is_admin_only_and_rejects_inactive_accounts(forensic_session):
    session, admin, investigator, reader, inactive, case, *_ = forensic_session
    service = CaseService(session)
    for actor in (investigator, reader, inactive):
        with pytest.raises(PermissionError):
            service.archive_case(case.id, actor)
    assert service.archive_case(case.id, admin)
    for actor in (investigator, reader, inactive):
        with pytest.raises(PermissionError):
            service.restore_case(case.id, actor)
    session.commit()


def test_archived_case_excluded_from_normal_discovery_and_writes(forensic_session):
    session, admin, investigator, reader, _, case, *_ = forensic_session
    service = CaseService(session)
    auth = AuthService(session)
    assert service.archive_case(case.id, admin)
    session.commit()

    assert service.list_cases(admin) == []
    assert service.list_cases(investigator) == []
    assert service.list_archived_cases(admin)[0].id == case.id
    assert service.list_cases(admin, include_archived=True)[0].id == case.id
    with pytest.raises(PermissionError):
        service.list_archived_cases(investigator)
    with pytest.raises(PermissionError):
        service.list_cases(investigator, include_archived=True)
    assert auth.get_user_cases(admin) == []
    assert auth.get_user_cases(investigator) == []
    assert not auth.user_can_write_case(admin, case.id)
    assert not auth.user_can_write_case(investigator, case.id)
    assert not auth.user_can_write_case(reader, case.id)
    with pytest.raises(PermissionError, match="read-only"):
        service.update_case(case.id, title="Should not change")


def test_archival_rollback_preserves_atomicity(forensic_session):
    session, admin, _, _, _, case, *_ = forensic_session
    case_id = case.id
    assert CaseService(session).archive_case(case_id, admin)
    session.rollback()
    session.expire_all()
    assert session.get(Case, case_id).archived_at is None
    assert session.execute(
        select(AuditEvent).where(AuditEvent.case_id == case_id)
    ).scalars().all() == []


def test_permanent_delete_is_disabled(forensic_session):
    session, admin, _, _, _, case, *_ = forensic_session
    with pytest.raises(PermissionError, match="disabled"):
        CaseService(session).delete_case(case.id)
    assert session.get(Case, case.id) is not None


def test_read_only_account_cannot_create_case(forensic_session):
    session, _, _, reader, _, _, *_ = forensic_session
    with pytest.raises(PermissionError):
        CaseService(session).create_case(
            case_id="READ-ONLY-CASE", title="Should fail",
            description=None, objective=None, priority="low", created_by=reader,
        )
