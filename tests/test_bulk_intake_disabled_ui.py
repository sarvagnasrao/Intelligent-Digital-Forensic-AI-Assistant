"""The intake UI must not expose bulk registration until integrity issues are fixed."""

from PySide6.QtWidgets import QDialog, QFileDialog, QLabel, QMessageBox, QPushButton

from app.ui.pages.evidence_page import RegisterEvidenceDialog, _RegisterEvidenceThread


def test_folder_disabled_and_single_file_picker(qt_app, monkeypatch, tmp_path):
    dialog = RegisterEvidenceDialog()
    folder = next(b for b in dialog.findChildren(QPushButton) if b.text() == "Browse folder")
    assert not folder.isEnabled()
    assert "integrity" in folder.toolTip()
    assert any("Bulk and folder intake" in label.text() for label in dialog.findChildren(QLabel))
    source = tmp_path / "sample.txt"
    source.write_text("synthetic")
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args: (str(source), ""))
    dialog._browse_file()
    assert dialog.source_paths == [str(source)]
    dialog._accept_if_valid()
    assert dialog.result() == QDialog.DialogCode.Accepted


def test_injected_multiple_paths_and_folder_are_blocked(qt_app, monkeypatch):
    dialog = RegisterEvidenceDialog()
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args[2]))
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *args: (_ for _ in ()).throw(AssertionError("folder picker opened")))
    dialog._browse_folder()
    dialog._set_paths(["one", "two"])
    assert dialog.source_paths == []
    dialog.source_paths = ["one", "two"]
    dialog._accept_if_valid()
    assert dialog.result() != QDialog.DialogCode.Accepted
    assert len(warnings) == 3


def test_thread_rejects_bulk_before_registration(qt_app, monkeypatch):
    from app.db import session as db_session
    from app.ui.pages import evidence_page

    class Session:
        def get(self, *args):
            return object()

        def rollback(self):
            pass

        def close(self):
            pass

    class Service:
        def __init__(self, session):
            pass

        def register_evidence(self, **kwargs):
            raise AssertionError("bulk registration was reached")

    monkeypatch.setattr(db_session, "get_session_factory", lambda: Session)
    monkeypatch.setattr(evidence_page, "EvidenceService", Service)
    thread = _RegisterEvidenceThread(1, {"source_paths": ["one", "two"]}, 1)
    failures = []
    thread.failed.connect(failures.append)
    thread.run()
    assert len(failures) == 1 and "temporarily disabled" in failures[0]
