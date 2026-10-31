"""Case deletion and export from the Case Management page.

Both actions used to die with ``name 'session_scope' is not defined`` because
the import only existed inside other methods, and the export timestamp used an
unimported ``timezone``. The dialogs report the exception as "Failed to ...",
so the actions silently did nothing.
"""
from __future__ import annotations

import json

import pytest
from sqlalchemy import select


@pytest.fixture
def case_page(qt_app, config_home, data_dir):
    from app.auth.models import Case, User, UserRole
    from app.cases.service import CaseService
    from app.config import Config, save_config, set_data_dir
    from app.db import load_all_models
    from app.db.session import close_db, get_session_factory, init_db
    from app.ui.pages.case_management_page import CaseManagementPage

    save_config(set_data_dir(Config(), data_dir))
    load_all_models()
    # The page runs its actions through session_scope(), so both the test and
    # the page must use the configured application database, not a side copy.
    # close_db() drops the engine cached for a previous test's data folder.
    close_db()
    init_db()
    session = get_session_factory()()

    user = User(
        username="admin", email="admin@test", password_hash="x",
        full_name="Admin", role=UserRole.ADMIN,
    )
    session.add(user)
    session.commit()
    case = Case(
        case_id="CASE-0001", title="Export me", description="d",
        objective="o", priority="medium", status="open", created_by_id=user.id,
    )
    session.add(case)
    session.commit()

    page = CaseManagementPage(nav_controller=None)
    page.set_user(user)
    page.set_case_service(CaseService(session))
    yield page, session, user, case
    session.close()
    close_db()


def test_delete_case_removes_the_record(case_page, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    page, session, _user, case = case_page
    case_id = case.id
    messages: list[tuple[str, str]] = []
    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes
    )
    monkeypatch.setattr(
        QMessageBox, "information", lambda *a, **k: messages.append(("info", a[2]))
    )
    monkeypatch.setattr(
        QMessageBox, "critical", lambda *a, **k: messages.append(("critical", a[2]))
    )

    page._delete_case(case)

    from app.auth.models import Case

    remaining = session.execute(select(Case).where(Case.id == case_id)).scalars().all()
    assert remaining == []
    assert messages and messages[0][0] == "info", messages


def test_delete_case_can_be_cancelled(case_page, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    page, session, _user, case = case_page
    case_id = case.id
    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.No
    )

    page._delete_case(case)

    from app.auth.models import Case

    assert session.get(Case, case_id) is not None


def test_edit_case_saves_every_dialog_field(case_page, monkeypatch):
    from PySide6.QtWidgets import QDialog, QMessageBox

    from app.ui.pages.case_management_page import EditCaseDialog

    page, session, _user, case = case_page
    case_id = case.id
    messages: list[tuple[str, str]] = []
    monkeypatch.setattr(
        EditCaseDialog, "exec", lambda self: QDialog.DialogCode.Accepted
    )
    monkeypatch.setattr(
        EditCaseDialog,
        "get_data",
        lambda self: {
            "title": "Renamed",
            "description": "new description",
            "objective": "new objective",
            "priority": "high",
            "status": "active",
            "assignee_id": None,
        },
    )
    monkeypatch.setattr(
        QMessageBox, "information", lambda *a, **k: messages.append(("info", a[2]))
    )
    monkeypatch.setattr(
        QMessageBox, "critical", lambda *a, **k: messages.append(("critical", a[2]))
    )

    page._edit_case(case)

    from app.auth.models import Case

    session.expire_all()
    stored = session.get(Case, case_id)
    assert stored.title == "Renamed"
    assert stored.objective == "new objective"
    assert stored.description == "new description"
    assert stored.priority == "high"
    assert stored.status == "active"
    assert messages and messages[0][0] == "info", messages


def test_export_case_writes_a_readable_json_file(case_page, monkeypatch, tmp_path):
    from PySide6.QtWidgets import QFileDialog, QMessageBox

    page, _session, _user, case = case_page
    target = tmp_path / "CASE-0001_export.json"
    messages: list[tuple[str, str]] = []
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", lambda *a, **k: (str(target), "")
    )
    monkeypatch.setattr(
        QMessageBox, "information", lambda *a, **k: messages.append(("info", a[2]))
    )
    monkeypatch.setattr(
        QMessageBox, "critical", lambda *a, **k: messages.append(("critical", a[2]))
    )

    page._export_case(case)

    assert messages and messages[0][0] == "info", messages
    assert target.exists(), "export produced no file"
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["case"]["case_id"] == "CASE-0001"
    assert payload["exported_at"]
    for key in ("evidence", "examinations", "artifacts", "findings"):
        assert isinstance(payload[key], list)
