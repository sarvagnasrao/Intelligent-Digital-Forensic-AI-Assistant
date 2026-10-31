"""Synthetic SQLite evidence, including Windows temporary-file semantics."""

import sqlite3
import tempfile

from worker.main import extract_text_content


def test_sqlite_extraction_uses_closed_copy_and_escapes_uri(tmp_path, monkeypatch):
    source = tmp_path / "source.sqlite"
    with sqlite3.connect(source) as db:
        db.execute('CREATE TABLE "leads" (value TEXT)')
        db.execute('INSERT INTO leads VALUES (?)', ("unique-investigation-lead",))
    evidence = source.read_bytes()

    # URI metacharacters in the temporary parent must not change the filename.
    parent = tmp_path / "temp # percent%"
    parent.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(parent))

    def forbidden(*args, **kwargs):
        raise AssertionError("an open NamedTemporaryFile cannot be reopened on Windows")

    monkeypatch.setattr(tempfile, "NamedTemporaryFile", forbidden)
    result = extract_text_content(evidence, None, ".sqlite", deep=True)
    assert result is not None
    assert "unique-investigation-lead" in result
    assert source.read_bytes() == evidence
    assert list(parent.iterdir()) == []


def test_corrupt_sqlite_is_not_reported_as_extracted():
    assert extract_text_content(b"not a database", None, ".db", deep=True) is None
