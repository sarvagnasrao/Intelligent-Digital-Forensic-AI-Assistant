"""Evidence page behaviour: file state, filters, guards and actions.

The page is where an investigator actually handles evidence, so these tests
cover the things that would be dangerous to get wrong: showing a record whose
file is gone as if it were fine, deleting without typing the ID, or opening a
disk image with whatever Windows has associated with ``.dd``.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


@pytest.fixture
def session(config_home, data_dir):
    from app.config import Config, save_config, set_data_dir
    from app.db import Base, load_all_models

    save_config(set_data_dir(Config(), data_dir))
    load_all_models()
    engine = create_engine(f"sqlite+pysqlite:///{(data_dir / 'evidence.db').as_posix()}")
    Base.metadata.create_all(engine)
    with Session(engine) as db_session:
        yield db_session
    engine.dispose()


@pytest.fixture
def service(session):
    from app.evidence.service import EvidenceService

    return EvidenceService(session)


@pytest.fixture
def case_user(service, session, tmp_path):
    from app.auth.models import Case, User

    user = User(username="t", email="t@example.test", password_hash="x", full_name="T")
    session.add(user)
    session.commit()
    case = Case(case_id="C-1", title="Case", created_by_id=user.id)
    session.add(case)
    session.commit()

    source = tmp_path / "disk.dd"
    source.write_bytes(b"\xcd" * 2048)
    evidence = service.register_evidence(
        case.id, "disk.dd", str(source), registered_by=user, copy_to_store=True
    )
    session.commit()
    return case, user, evidence


class _Nav:
    """Minimal stand-in for the dashboard's nav controller."""

    def __init__(self, user):
        self._user = user

    def get_current_user(self):
        return self._user


@pytest.fixture
def page(qt_app, service, case_user):
    from app.ui.base import CaseContext
    from app.ui.pages.evidence_page import EvidencePage

    case, user, _evidence = case_user
    widget = EvidencePage(nav=_Nav(user))
    widget.set_evidence_service(service)
    widget.set_case_context(
        CaseContext(case.id, case.case_id, case.title, "open", "medium", "T")
    )
    widget.refresh()
    yield widget
    widget.deleteLater()


def row_texts(page) -> list[tuple[str, ...]]:
    model = page.table_model
    return [
        tuple(model.item(row, column).text() for column in range(model.columnCount()))
        for row in range(model.rowCount())
    ]


def evidence_row(page, evidence_id: str) -> int:
    for row in range(page.table_model.rowCount()):
        if page.table_model.item(row, 0).text() == evidence_id:
            return row
    raise AssertionError(f"{evidence_id} is not in the table")


def test_the_table_lists_the_registered_item_with_its_file_state(page, case_user):
    _case, _user, evidence = case_user

    rows = row_texts(page)
    assert len(rows) == 1
    assert rows[0][0] == evidence.evidence_id
    assert rows[0][4] == "Present"


def test_non_cancelable_progress_has_no_blank_cancel_control(page):
    from PySide6.QtWidgets import QPushButton

    progress = page._open_progress("Registering Evidence", "Preparing…")

    assert not progress.findChildren(QPushButton)
    assert progress.minimumWidth() >= 360
    page._close_progress()


def test_a_missing_stored_copy_is_flagged_in_the_table(page, service, case_user):
    case, _user, evidence = case_user
    Path(evidence.stored_path).unlink()

    page.refresh()

    row = evidence_row(page, evidence.evidence_id)
    assert page.table_model.item(row, 4).text() == "Missing"
    assert "missing" in page.summary_label.text()


def test_removed_items_are_hidden_until_the_filter_is_ticked(page, service, case_user):
    _case, user, evidence = case_user
    service.remove_evidence(evidence.id, user, "duplicate")
    service.session.commit()

    page.refresh()
    assert row_texts(page) == []

    page.show_removed_check.setChecked(True)
    assert row_texts(page)[0][0] == evidence.evidence_id
    assert "removed" in row_texts(page)[0][1]
    assert "missing" not in page.summary_label.text()


def test_the_search_box_matches_name_and_path(page, service, case_user):
    case, user, evidence = case_user
    other_source = Path(evidence.source_path).parent / "notes.txt"
    other_source.write_text("notes", encoding="utf-8")
    service.register_evidence(
        case.id, "meeting-notes", str(other_source), registered_by=user,
        copy_to_store=True,
    )
    service.session.commit()
    page.refresh()
    assert len(row_texts(page)) == 2

    page.search_edit.setText("meeting")
    assert [row[1] for row in row_texts(page)] == ["meeting-notes"]

    page.search_edit.setText("")
    page.search_edit.setText(evidence.stored_path)
    assert [row[0] for row in row_texts(page)] == [evidence.evidence_id]


def test_the_status_filter_and_archived_toggle_work_together(page, service, case_user):
    case, user, evidence = case_user
    second_source = Path(evidence.source_path).parent / "second.dd"
    second_source.write_bytes(b"\x01" * 128)
    archived = service.register_evidence(
        case.id, "second.dd", str(second_source), registered_by=user, copy_to_store=True
    )
    service.archive_evidence(archived.id, user)
    service.session.commit()
    page.refresh()

    archived_rows = [
        row for row in row_texts(page) if row[6] == "Archived"
    ]
    assert len(archived_rows) == 1

    page.show_archived_check.setChecked(False)
    assert all(row[6] != "Archived" for row in row_texts(page))

    page.show_archived_check.setChecked(True)
    page.status_filter.setCurrentIndex(
        page.status_filter.findData("archived")
    )
    assert [row[0] for row in row_texts(page)] == [archived.evidence_id]


def test_bulk_removal_asks_once_and_keeps_the_files(page, service, case_user, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from app.ui.pages import evidence_page

    case, user, evidence = case_user
    other_source = Path(evidence.source_path).parent / "second.dd"
    other_source.write_bytes(b"\x02" * 128)
    service.register_evidence(
        case.id, "second.dd", str(other_source), registered_by=user, copy_to_store=True
    )
    service.session.commit()
    page.refresh()

    asked: list[str] = []
    monkeypatch.setattr(
        evidence_page.QMessageBox, "question",
        staticmethod(lambda *args, **kwargs: (
            asked.append(args[2]), QMessageBox.StandardButton.Yes
        )[1]),
    )
    monkeypatch.setattr(
        evidence_page.QMessageBox, "information",
        staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.Ok),
    )

    page.table_view.selectAll()
    page._on_remove()

    assert len(asked) == 1
    assert service.get_evidence_by_case(case.id) == []
    assert len(service.get_evidence_by_case(case.id, include_removed=True)) == 2
    assert Path(evidence.stored_path).is_file()


def test_a_single_removal_uses_the_reason_dialog(page, service, case_user, monkeypatch):
    from PySide6.QtWidgets import QDialog, QMessageBox

    from app.ui.pages import evidence_page

    case, user, evidence = case_user
    monkeypatch.setattr(
        evidence_page.RemoveEvidenceDialog, "exec",
        lambda self: QDialog.DialogCode.Accepted,
    )
    monkeypatch.setattr(
        evidence_page.RemoveEvidenceDialog, "get_reason",
        lambda self: "registered the wrong file",
    )
    monkeypatch.setattr(
        evidence_page.QMessageBox, "information",
        staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.Ok),
    )

    page.table_view.selectRow(0)
    page._on_remove()

    removed = service.get_evidence_by_case(case.id, include_removed=True)[0]
    assert removed.is_removed
    assert removed.removal_reason == "registered the wrong file"


def test_the_delete_dialog_refuses_until_the_id_is_typed(qt_app, case_user):
    from PySide6.QtWidgets import QDialogButtonBox

    from app.ui.pages.evidence_page import DeleteEvidenceDialog

    _case, _user, evidence = case_user
    dialog = DeleteEvidenceDialog(evidence, [Path(evidence.stored_path)], [])
    ok = dialog.buttons.button(QDialogButtonBox.StandardButton.Ok)

    assert not ok.isEnabled()
    dialog.confirm_edit.setText(evidence.evidence_id[:-1])
    assert not ok.isEnabled()
    dialog.confirm_edit.setText(evidence.evidence_id)
    assert ok.isEnabled()
    dialog.deleteLater()


def test_the_delete_dialog_explains_why_it_is_blocked(qt_app, case_user):
    from PySide6.QtWidgets import QDialogButtonBox

    from app.ui.pages.evidence_page import DeleteEvidenceDialog

    _case, _user, evidence = case_user
    dialog = DeleteEvidenceDialog(
        evidence, [], ["1 examination job(s) reference this evidence."]
    )
    ok = dialog.buttons.button(QDialogButtonBox.StandardButton.Ok)

    dialog.confirm_edit.setText(evidence.evidence_id)
    assert not ok.isEnabled(), "a blocked item must never be deletable"
    assert not dialog.confirm_edit.isEnabled()
    dialog.deleteLater()


def test_open_file_opens_the_folder_for_a_disk_image(page, case_user, monkeypatch):
    _case, _user, evidence = case_user
    opened: list[str] = []
    monkeypatch.setattr(page, "_open_folder", lambda path: opened.append(("folder", path)))
    monkeypatch.setattr(page, "_open_path", lambda path: opened.append(("file", path)))
    page.table_view.selectRow(0)

    page._on_open_file()

    assert opened == [("folder", evidence.stored_path)]


def test_open_file_uses_the_default_app_for_a_safe_type(page, service, case_user, monkeypatch):
    case, user, evidence = case_user
    text_source = Path(evidence.source_path).parent / "notes.txt"
    text_source.write_text("plain text", encoding="utf-8")
    service.register_evidence(
        case.id, "notes.txt", str(text_source), registered_by=user, copy_to_store=True
    )
    service.session.commit()
    page.refresh()

    opened: list[tuple[str, str]] = []
    monkeypatch.setattr(page, "_open_folder", lambda path: opened.append(("folder", path)))
    monkeypatch.setattr(page, "_open_path", lambda path: opened.append(("file", path)))
    page.table_view.selectRow(evidence_row(page, "E002"))

    page._on_open_file()

    assert opened and opened[0][0] == "file"


def test_detail_pane_copy_action_reaches_the_clipboard(qt_app, page, case_user):
    from PySide6.QtWidgets import QApplication

    _case, _user, evidence = case_user
    page._on_detail_action(f"copy:{evidence.evidence_id}", evidence.id)

    assert QApplication.clipboard().text() == evidence.evidence_id


def test_manifest_export_writes_csv_and_json(page, case_user, tmp_path, monkeypatch):
    from app.ui.pages import evidence_page

    _case, _user, evidence = case_user

    class _Dialogs:
        target: Path | None = None
        filter = ""

        @staticmethod
        def getSaveFileName(*_args, **_kwargs):
            return str(_Dialogs.target), _Dialogs.filter

    monkeypatch.setattr(evidence_page, "QFileDialog", _Dialogs)
    monkeypatch.setattr(
        evidence_page.QMessageBox, "information",
        staticmethod(lambda *args, **kwargs: None),
    )

    _Dialogs.target = tmp_path / "manifest.csv"
    _Dialogs.filter = "CSV file (*.csv)"
    page._on_export_manifest()
    with _Dialogs.target.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["evidence_id"] == evidence.evidence_id
    assert rows[0]["file_state"] == "present"
    assert "sha256:" in rows[0]["hashes"]

    _Dialogs.target = tmp_path / "manifest.json"
    _Dialogs.filter = "JSON file (*.json)"
    page._on_export_manifest()
    payload = json.loads(_Dialogs.target.read_text(encoding="utf-8"))
    assert payload[0]["hashes"]["sha256"]


def test_check_files_reports_the_missing_items(page, case_user, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from app.ui.pages import evidence_page

    _case, _user, evidence = case_user
    Path(evidence.stored_path).unlink()
    captured: list[str] = []
    monkeypatch.setattr(
        evidence_page.QMessageBox, "warning",
        staticmethod(lambda _parent, _title, text, *a, **k: captured.append(text)),
    )

    page._on_check_files()

    assert captured and evidence.evidence_id in captured[0]
    assert page.table_model.item(0, 4).text() == "Missing"
    assert QMessageBox is not None
