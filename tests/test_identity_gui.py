"""Identity hypotheses through the findings GUI with a throwaway database."""
from types import SimpleNamespace

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session


def test_identity_dialog_keeps_input_after_invalid_source(qt_app, monkeypatch):
    from PySide6.QtWidgets import QDialog, QMessageBox
    from app.ui.pages.findings_page import IdentityHypothesisDialog

    artifact = SimpleNamespace(id=1, artifact_id="A1", name="message", content_text="Exact source text")
    dialog = IdentityHypothesisDialog([artifact])
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args[-1]))
    dialog.hypothesis.setPlainText("Possible identity")
    dialog.alternatives.setPlainText("Shared account")
    dialog.excerpt.setPlainText("inexact text")
    dialog.explanation.setText("Possible connection")
    dialog.add_source()
    dialog.accept()
    assert dialog.result() != QDialog.DialogCode.Accepted
    assert "exact excerpt" in warnings[-1]
    assert dialog.hypothesis.toPlainText() == "Possible identity"
    dialog.remove_source()
    dialog.excerpt.setPlainText("Exact source text")
    dialog.explanation.setText("Possible connection")
    dialog.add_source()
    dialog.accept()
    assert dialog.result() == QDialog.DialogCode.Accepted
    dialog.deleteLater()


def test_identity_creation_and_review(qt_app, monkeypatch):
    from PySide6.QtWidgets import QDialog, QInputDialog
    from app.db import Base, load_all_models
    from app.auth.models import Case, User, UserRole
    from app.artifacts.models import Artifact
    from app.evidence.models import Evidence
    from app.findings.models import Finding, FindingStatus
    from app.findings.service import FindingService
    from app.ui.base import CaseContext
    from app.ui.pages.findings_page import FindingsPage, IdentityHypothesisDialog

    load_all_models()
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        user = User(username="investigator", email="i@example.test", password_hash="x",
                    full_name="Investigator", role=UserRole.INVESTIGATOR)
        session.add(user)
        session.flush()
        case = Case(case_id="C1", title="Case", created_by_id=user.id)
        session.add(case)
        session.flush()
        evidence = Evidence(evidence_id="E1", case_id=case.id, name="disk", source_path="disk", registered_by_id=user.id)
        session.add(evidence)
        session.flush()
        session.add_all([Artifact(artifact_id="A1", case_id=case.id, evidence_id=evidence.id, name="one", content_text="Alice uses mailbox"),
                         Artifact(artifact_id="A2", case_id=case.id, evidence_id=evidence.id, name="two", content_text="Mailbox is shared")])
        session.commit()
        page = FindingsPage(nav=SimpleNamespace(get_current_user=lambda: user))
        page.set_finding_service(FindingService(session))
        page.set_case_context(CaseContext(case.id, case.case_id, case.title, "open", "medium", user.full_name))

        def fill(dialog):
            dialog.hypothesis.setPlainText("Alice may use the mailbox")
            dialog.alternatives.setPlainText("Another person uses it")
            dialog.excerpt.setPlainText("Alice uses mailbox")
            dialog.explanation.setText("The message mentions Alice")
            dialog.add_source()
            dialog.artifact.setCurrentIndex(1)
            dialog.role.setCurrentIndex(1)
            dialog.excerpt.setPlainText("Mailbox is shared")
            dialog.explanation.setText("Others may use it")
            dialog.add_source()
            return QDialog.DialogCode.Accepted

        monkeypatch.setattr(IdentityHypothesisDialog, "exec", fill)
        page.identity_btn.click()
        finding = session.scalar(select(Finding))
        assert finding.status == FindingStatus.DRAFT
        assert "Another person uses it" in finding.description
        assert {link.relevance for link in finding.artifact_links} == {"supports", "contradicts"}
        assert "unverified" in finding.description
        from app.ui.pages.findings_page import NewFindingDialog
        from PySide6.QtWidgets import QMessageBox
        errors = []
        monkeypatch.setattr(QMessageBox, "critical", lambda *args: errors.append(args[-1]))
        def invalid_edit(dialog):
            dialog.desc_edit.setPlainText(finding.description.replace("- Another person uses it", ""))
            return QDialog.DialogCode.Accepted
        monkeypatch.setattr(NewFindingDialog, "exec", invalid_edit)
        page.detail_pane.edit_btn.click()
        assert errors and "alternative" in errors[-1].lower()
        assert "- Another person uses it" in finding.description
        warnings = []
        monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args[-1]))
        monkeypatch.setattr(QInputDialog, "getItem", lambda *args, **kwargs: (args[3][0], True))
        page.detail_pane.unlink_btn.click()
        assert warnings and "cannot be changed" in warnings[-1]
        assert len(service_links := FindingService(session).get_finding_artifacts(finding.id)) == 2
        monkeypatch.setattr(QInputDialog, "getMultiLineText", lambda *args, **kwargs: ("Insufficient", True))
        page.detail_pane.reject_btn.click()
        assert finding.status == FindingStatus.REJECTED
        assert finding.verification_notes == "Insufficient"
        from app.evidence.service import EvidenceService
        EvidenceService(session).remove_evidence(evidence.id, user, "No longer in case")
        page.detail_pane.set_finding(finding, FindingService(session).get_finding_artifacts(finding.id))
        assert page.detail_pane.status_badge.text() == "Draft"
        assert "Review needed" in page.detail_pane.review_note.text()
        page.deleteLater()
    engine.dispose()
