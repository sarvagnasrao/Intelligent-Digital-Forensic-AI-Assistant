"""Finding creation, review and provenance through the case page."""
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session


@pytest.fixture
def finding_page(qt_app, config_home, data_dir, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from app.artifacts.models import Artifact, ArtifactType
    from app.auth.models import Case, User, UserRole
    from app.config import Config, save_config, set_data_dir
    from app.db import Base, load_all_models
    from app.evidence.models import Evidence
    from app.findings.service import FindingService
    from app.ui.base import CaseContext
    from app.ui.pages.findings_page import FindingsPage

    save_config(set_data_dir(Config(), data_dir))
    load_all_models()
    engine = create_engine(f"sqlite+pysqlite:///{(data_dir / 'findings.db').as_posix()}")
    Base.metadata.create_all(engine)
    session = Session(engine, expire_on_commit=False)
    session.add(User(username="admin", email="admin@test", password_hash="x", full_name="Admin", role=UserRole.ADMIN))
    user = User(username="investigator", email="i@test", password_hash="x", full_name="Investigator", role=UserRole.INVESTIGATOR)
    session.add(user)
    session.flush()
    case = Case(case_id="CASE-1", title="Case", created_by_id=user.id)
    session.add(case)
    session.flush()
    evidence = Evidence(evidence_id="E-1", case_id=case.id, name="disk", source_path="disk", registered_by_id=user.id)
    session.add(evidence)
    session.flush()
    artifact = Artifact(artifact_id="ART-0001-1", case_id=case.id, evidence_id=evidence.id,
                        name="log.txt", artifact_type=ArtifactType.FILE, content_text="source")
    session.add(artifact)
    session.commit()
    destinations = []
    nav = SimpleNamespace(get_current_user=lambda: user, show_page_by_key=destinations.append)
    page = FindingsPage(nav=nav)
    page.set_finding_service(FindingService(session))
    page.set_case_context(CaseContext(case.id, case.case_id, case.title, "open", "medium", user.full_name))
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: None)
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: pytest.fail(str(args[2])))
    monkeypatch.setattr(QMessageBox, "critical", lambda *args, **kwargs: pytest.fail(str(args[2])))
    yield page, session, case, user, artifact, destinations
    page.deleteLater()
    session.close()
    engine.dispose()


def test_detail_pane_scroll_area_carries_the_responsive_bounds(finding_page):
    from app.ui.layouts import DETAIL_PANE_MAX_WIDTH, DETAIL_PANE_MIN_WIDTH

    page, *_ = finding_page

    assert page.detail_pane.minimumWidth() == DETAIL_PANE_MIN_WIDTH
    assert page.detail_scroll.minimumWidth() == DETAIL_PANE_MIN_WIDTH
    assert page.detail_scroll.maximumWidth() == DETAIL_PANE_MAX_WIDTH


def test_create_filter_and_review_uses_signed_in_user(finding_page, monkeypatch):
    from PySide6.QtWidgets import QDialog, QInputDialog

    from app.audit.models import AuditEvent
    from app.findings.models import Finding, FindingStatus
    from app.ui.pages.findings_page import NewFindingDialog

    page, session, case, user, _artifact, destinations = finding_page
    monkeypatch.setattr(NewFindingDialog, "exec", lambda self: QDialog.DialogCode.Accepted)
    monkeypatch.setattr(NewFindingDialog, "get_data", lambda self: {
        "title": "Review log", "description": "Relevant content", "conclusion": None,
    })
    page._on_new_finding()
    finding = session.scalar(select(Finding).where(Finding.case_id == case.id))
    assert finding.created_by_id == user.id
    page.table_view.selectRow(0)
    monkeypatch.setattr(QInputDialog, "getMultiLineText", lambda *args, **kwargs: ("Checked source", True))
    page.detail_pane.verify_btn.click()
    assert finding.status == FindingStatus.VERIFIED
    assert finding.verified_by_id == user.id
    assert finding.verification_notes == "Checked source"
    assert session.scalar(select(AuditEvent).where(AuditEvent.action == "review")).user_id == user.id
    page.status_filter.setCurrentText("Draft")
    assert page.table_model.rowCount() == 0
    page.status_filter.setCurrentText("Verified")
    assert page.table_model.rowCount() == 1
    page._on_ai_suggested()
    assert destinations == ["ai"]


def test_linking_and_unlinking_artifact_returns_reviewed_finding_to_draft(finding_page, monkeypatch):
    from PySide6.QtWidgets import QInputDialog

    from app.findings.models import FindingStatus

    page, session, case, user, artifact, _ = finding_page
    finding = page.finding_service.create_finding(case.id, "Test", "Description", user)
    page.finding_service.verify_finding(finding.id, user, "Reviewed")
    session.commit()
    page.refresh()
    page.table_view.selectRow(0)
    monkeypatch.setattr(QInputDialog, "getText", lambda *args, **kwargs: (artifact.artifact_id, True))
    page.detail_pane.link_btn.click()
    assert finding.status == FindingStatus.DRAFT
    assert finding.verified_at is None
    assert len(page.finding_service.get_finding_artifacts(finding.id)) == 1
    page.finding_service.verify_finding(finding.id, user, "Reviewed again")
    session.commit()
    monkeypatch.setattr(QInputDialog, "getItem", lambda *args, **kwargs: (args[3][0], True))
    page.detail_pane.unlink_btn.click()
    assert finding.status == FindingStatus.DRAFT
    assert finding.verified_at is None
    assert page.finding_service.get_finding_artifacts(finding.id) == []


def test_reject_edit_and_mark_under_review(finding_page, monkeypatch):
    from PySide6.QtWidgets import QDialog, QInputDialog

    from app.findings.models import FindingStatus
    from app.ui.pages.findings_page import NewFindingDialog

    page, session, case, user, _artifact, _ = finding_page
    finding = page.finding_service.create_finding(case.id, "Original", "Description", user)
    session.commit()
    page.refresh()
    page.table_view.selectRow(0)
    monkeypatch.setattr(QInputDialog, "getMultiLineText", lambda *args, **kwargs: ("Not supported", True))
    page.detail_pane.reject_btn.click()
    assert finding.status == FindingStatus.REJECTED
    assert finding.verification_notes == "Not supported"
    monkeypatch.setattr(NewFindingDialog, "exec", lambda self: QDialog.DialogCode.Accepted)
    monkeypatch.setattr(NewFindingDialog, "get_data", lambda self: {
        "title": "Updated", "description": "Revised description", "conclusion": None,
    })
    page.detail_pane.edit_btn.click()
    assert finding.status == FindingStatus.DRAFT
    assert finding.title == "Updated"
    assert finding.verification_notes is None
    page.detail_pane.review_btn.click()
    assert finding.status == FindingStatus.UNDER_REVIEW


def test_source_labels_show_evidence_and_historical_state(finding_page):
    from datetime import datetime, timezone

    from app.ui.pages.findings_page import IdentityHypothesisDialog, _source_label

    page, session, case, user, artifact, _ = finding_page
    finding = page.finding_service.create_finding(case.id, "Test", "Description", user)
    page.finding_service.link_artifact(finding.id, artifact.id, actor=user)
    session.commit()
    page.refresh()
    page.table_view.selectRow(0)
    assert "Evidence E-1 — disk" in page.detail_pane.artifacts_list.text()
    dialog = IdentityHypothesisDialog([artifact])
    assert "Evidence E-1 — disk" in dialog.artifact.itemText(0)
    artifact.evidence.removed_at = datetime.now(timezone.utc)
    page.detail_pane.set_finding(finding, [artifact])
    assert "Evidence E-1 — disk (removed from case)" in page.detail_pane.artifacts_list.text()
    unavailable = SimpleNamespace(artifact_id="A-missing", name="orphan", evidence=None)
    assert "Evidence unavailable" in _source_label(unavailable)
    dialog.deleteLater()


def test_explicit_device_associations_in_finding_and_identity_picker(finding_page):
    from app.devices.service import DeviceService
    from app.ui.pages.findings_page import IdentityHypothesisDialog

    page, session, case, user, artifact, _ = finding_page
    finding = page.finding_service.create_finding(case.id, "Test", "Description", user)
    page.finding_service.link_artifact(finding.id, artifact.id, actor=user)
    page.detail_pane.set_finding(finding, [artifact])
    assert "No associated physical device" in page.detail_pane.artifacts_list.text()

    service = DeviceService(session)
    for label in ("Laptop", "External drive"):
        device = service.create(case.id, user, label)
        service.link_evidence(case.id, device.id, artifact.evidence_id, user)
    page.detail_pane.set_finding(finding, [artifact])
    label = page.detail_pane.artifacts_list.text()
    assert "Investigator-associated device(s): Laptop, External drive" in label
    dialog = IdentityHypothesisDialog([artifact])
    assert "Investigator-associated device(s): Laptop, External drive" in dialog.artifact.itemText(0)
    dialog.deleteLater()


def test_identity_picker_excludes_removed_and_other_case_evidence(finding_page, monkeypatch):
    from datetime import datetime, timezone

    from PySide6.QtWidgets import QDialog
    from app.artifacts.models import Artifact
    from app.auth.models import Case
    from app.evidence.models import Evidence
    from app.ui.pages.findings_page import IdentityHypothesisDialog

    page, session, case, user, artifact, _ = finding_page
    other = Case(case_id="CASE-2", title="Other", created_by_id=user.id)
    session.add(other)
    session.flush()
    removed = Evidence(evidence_id="E-removed", case_id=case.id, name="removed", source_path="x",
                       registered_by_id=user.id, removed_at=datetime.now(timezone.utc))
    foreign = Evidence(evidence_id="E-other", case_id=other.id, name="other", source_path="x",
                       registered_by_id=user.id)
    session.add_all([removed, foreign])
    session.flush()
    session.add_all([
        Artifact(artifact_id="A-removed", case_id=case.id, evidence_id=removed.id, name="removed", content_text="text"),
        Artifact(artifact_id="A-foreign", case_id=case.id, evidence_id=foreign.id, name="foreign", content_text="text"),
    ])
    session.commit()
    seen = []
    def inspect(dialog):
        seen.extend(dialog.artifact.itemText(i) for i in range(dialog.artifact.count()))
        return QDialog.DialogCode.Rejected
    monkeypatch.setattr(IdentityHypothesisDialog, "exec", inspect)
    page._on_new_identity()
    assert len(seen) == 1
    assert artifact.artifact_id in seen[0] and "Evidence E-1 — disk" in seen[0]
