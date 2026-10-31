from pathlib import Path


def test_folder_selection_skips_reparse_points(qt_app, tmp_path, monkeypatch):
    import stat
    from types import SimpleNamespace
    from app.ui.pages import evidence_page

    safe = tmp_path / "safe.txt"
    safe.write_text("synthetic")
    junction = tmp_path / "junction"
    junction.mkdir()
    (junction / "hidden.txt").write_text("not selected")
    original = Path.lstat
    def lstat(path):
        info = original(path)
        if path == junction:
            return SimpleNamespace(st_mode=info.st_mode,
                                   st_file_attributes=stat.FILE_ATTRIBUTE_REPARSE_POINT)
        return info
    monkeypatch.setattr(Path, "lstat", lstat)
    monkeypatch.setattr(evidence_page.QFileDialog, "getExistingDirectory", lambda *args: str(tmp_path))
    dialog = evidence_page.RegisterEvidenceDialog()
    dialog._browse_folder()
    assert dialog.source_paths == [str(safe)]
    dialog.deleteLater()


def test_bulk_selection_groups_segments_and_keeps_distinct_paths(qt_app, tmp_path):
    from app.ui.pages.evidence_page import RegisterEvidenceDialog

    first = tmp_path / "disk.001"
    second = tmp_path / "disk.002"
    other = tmp_path / "note.txt"
    for path in (first, second, other):
        path.write_bytes(b"evidence")
    dialog = RegisterEvidenceDialog()
    dialog._set_paths([str(second), str(first), str(other), str(other)])
    assert dialog.source_paths == [str(first), str(other)]
    assert dialog.get_data()["source_paths"] == [str(first), str(other)]
    dialog.deleteLater()


def test_bulk_selection_groups_ewf_and_rejects_gaps(qt_app, tmp_path):
    import pytest
    from app.evidence.service import EvidenceService
    from app.ui.pages.evidence_page import RegisterEvidenceDialog

    first, second = tmp_path / "disk.E01", tmp_path / "disk.E02"
    first.write_bytes(b"one")
    second.write_bytes(b"two")
    dialog = RegisterEvidenceDialog()
    dialog._set_paths([str(second), str(first)])
    assert dialog.source_paths == [str(first)]
    second.rename(tmp_path / "disk.E03")
    with pytest.raises(FileNotFoundError):
        EvidenceService._split_image_parts(first)
    dialog.deleteLater()


def test_bulk_thread_commits_each_and_reports_failures(monkeypatch, tmp_path, qt_app):
    from app.db import session as db_session
    from app.ui.pages import evidence_page

    class Session:
        def __init__(self):
            self.commits = 0
            self.rollbacks = 0

        def get(self, *args):
            return object()

        def commit(self):
            self.commits += 1

        def rollback(self):
            self.rollbacks += 1

        def close(self):
            pass

    session = Session()
    calls = []

    class Service:
        def __init__(self, _session):
            pass

        def register_evidence(self, **kwargs):
            calls.append(kwargs)
            if len(calls) == 2:
                raise ValueError("unreadable")
            return type("Item", (), {"evidence_id": "E001"})()

    monkeypatch.setattr(db_session, "get_session_factory", lambda: lambda: session)
    monkeypatch.setattr(evidence_page, "EvidenceService", Service)
    paths = [str(tmp_path / "a.txt"), str(tmp_path / "b.txt")]
    data = {"source_paths": paths, "source_path": paths[0], "name": "ignored",
            "description": "source description", "copy_to_store": False,
            "reference_hash": "", "reference_algorithm": "sha256"}
    thread = evidence_page._RegisterEvidenceThread(1, data, 2)
    results = []
    thread.registered.connect(results.append)
    thread.run()
    assert session.commits == 1 and session.rollbacks == 1
    assert [call["name"] for call in calls] == [Path(p).name for p in paths]
    assert all(not call["copy_to_store"] and call["reference_hashes"] is None for call in calls)
    assert results[0][0][1] == "E001" and results[0][1][2] == "unreadable"
