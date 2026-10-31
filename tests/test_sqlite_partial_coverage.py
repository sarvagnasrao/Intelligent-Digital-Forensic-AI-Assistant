"""A synthetic database with a table requiring an unavailable SQLite module."""

import hashlib
import sqlite3

from worker.main import describe_file_evidence


def test_unreadable_virtual_table_does_not_hide_other_evidence(tmp_path):
    path = tmp_path / "evidence.sqlite"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE leads (value TEXT)")
        db.execute("INSERT INTO leads VALUES ('recoverable-lead')")
        db.execute("PRAGMA writable_schema=ON")
        db.execute(
            "INSERT INTO sqlite_master (type, name, tbl_name, rootpage, sql) "
            "VALUES ('table', 'unavailable', 'unavailable', 0, "
            "'CREATE VIRTUAL TABLE unavailable USING missing_module')"
        )
    original = path.read_bytes()

    artifact = describe_file_evidence(str(path), deep=True)

    assert "recoverable-lead" in artifact["content_text"]
    assert artifact["extraction_status"] == "partial"
    assert "SQLite" in artifact["read_error"]
    assert "unavailable" in artifact["read_error"]
    assert artifact["content_hash"] == hashlib.sha256(original).hexdigest()
    assert path.read_bytes() == original
