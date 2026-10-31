"""Continuous GUI rehearsal on a disposable database, with no external services."""
import asyncio
import time

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker


def test_offscreen_case_to_finding(qt_app, tmp_path, config_home, monkeypatch):
    from PySide6.QtWidgets import QDialog, QMessageBox
    from app.analysis.runner import AnalysisRunner
    from app.analysis.service import AnalysisService
    from app.auth.models import User, UserRole
    from app.cases.service import CaseService
    from app.config import Config, save_config, set_data_dir
    from app.db import Base, load_all_models
    from app.db import session as db
    from app.evidence.service import EvidenceService
    from app.examination.models import ExaminationJob, ExaminationOperation, JobStatus
    from app.examination.service import ExaminationService
    from app.findings.models import Finding
    from app.ui.main_window import MainWindow
    from app.ui.pages.ai_analysis_page import AIAnalysisPage
    from app.ui.pages.findings_page import IdentityHypothesisDialog

    save_config(set_data_dir(Config(), tmp_path))
    load_all_models()
    engine = create_engine(f"sqlite+pysqlite:///{(tmp_path / 'demo.db').as_posix()}",
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    monkeypatch.setattr(db, "_engine", engine)
    monkeypatch.setattr(db, "_session_factory", factory)
    db.ensure_fts_index()
    monkeypatch.setattr(MainWindow, "_apply_ui_settings", lambda self: None)
    monkeypatch.setattr(AIAnalysisPage, "_refresh_status", lambda self: None)
    monkeypatch.setattr(AnalysisRunner, "start", lambda self: None)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: (_ for _ in ()).throw(AssertionError(str(a))))
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: (_ for _ in ()).throw(AssertionError(str(a))))

    source = tmp_path / "synthetic.txt"
    source.write_text("Synthetic evidence", encoding="utf-8")
    with factory() as session:
        user = User(username="demo", email="demo@example.test", password_hash="x",
                    full_name="Demo Examiner", role=UserRole.ADMIN)
        session.add(user)
        session.flush()
        case = CaseService(session).create_case("CASE-DEMO", "Synthetic case", None, None, "medium", user)
        session.flush()
        evidence = EvidenceService(session).register_evidence(
            case.id, "Synthetic evidence", str(source), registered_by=user, copy_to_store=False)
        exam = ExaminationJob(job_id="EX-DEMO", case_id=case.id, evidence_id=evidence.id,
                              operation=ExaminationOperation.FULL_EXAMINATION,
                              status=JobStatus.COMPLETED, created_by_id=user.id)
        session.add(exam)
        session.flush()
        rows = [
            {"path": "/mail.txt", "name": "mail.txt", "content_text": "Alice mentions courier@relay.test and 192.168.4.8"},
            {"path": "/notes.txt", "name": "notes.txt", "content_text": "Shared courier@relay.test and 192.168.4.8"},
        ]
        asyncio.run(ExaminationService(session)._create_artifact_records(
            case.id, evidence.id, exam.id, {"artifacts": rows}, commit_interval=False))
        session.commit()
        analysis = AnalysisService(session)
        job = analysis.enqueue_for_examination(case.id, evidence.id, exam.id,
            created_by=user, parameters={"llm_enabled": False, "build_relationships": True}, manual=True)
        session.commit()
        assert asyncio.run(analysis.run(job.id, user))["ok"]
        case_id = case.id

    window = MainWindow()
    try:
        nav = window.nav_controller
        nav.set_user(user)
        nav.open_case(case_id, "Synthetic case", "open", "medium", "Demo Examiner")
        shell = nav.case_shell
        shell.show_page_by_key("evidence")
        assert shell.evidence_page.case_context.case_id == case_id
        assert shell.evidence_page.table_model.rowCount() == 1
        shell.show_page_by_key("artifacts")
        page = shell.artifacts_page
        assert page.table_model.rowCount() == 2
        page.query_edit.setText("courier")
        page.search_btn.click()
        deadline = time.monotonic() + 10
        while not page.search_btn.isEnabled() and time.monotonic() < deadline:
            qt_app.processEvents()
            time.sleep(0.01)
        qt_app.processEvents()
        assert page.search_btn.isEnabled()
        assert page.table_model.rowCount() == 2
        shell.show_page_by_key("entities")
        shell.entities_page.refresh()
        assert shell.entities_page.rel_model.rowCount() >= 1
        shell.show_page_by_key("findings")
        def fill(dialog):
            dialog.hypothesis.setPlainText("Alice may use the mailbox")
            dialog.alternatives.setPlainText("The mailbox may be shared")
            dialog.excerpt.setPlainText("Alice mentions courier@relay.test")
            dialog.explanation.setText("Alice mentions the mailbox")
            dialog.add_source()
            return QDialog.DialogCode.Accepted
        monkeypatch.setattr(IdentityHypothesisDialog, "exec", fill)
        shell.findings_page.identity_btn.click()
        with factory() as check:
            finding = check.scalar(select(Finding).where(Finding.case_id == case_id))
            assert finding is not None and "unverified" in finding.description
    finally:
        window.close()
        qt_app.processEvents()
        engine.dispose()
