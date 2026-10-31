"""Damaged text in one database row must not conceal later evidence."""

import hashlib
import sqlite3

from app.analysis.extractors import extract_entities
from app.artifacts.models import EntityType
from worker.main import describe_file_evidence


def test_invalid_text_cell_preserves_later_source_backed_leads(tmp_path):
    path = tmp_path / "contacts.sqlite"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE contacts (note TEXT)")
        db.execute("INSERT INTO contacts VALUES ('first@example.test')")
        db.execute("INSERT INTO contacts VALUES (CAST(x'80' AS TEXT))")
        db.execute("INSERT INTO contacts VALUES ('later@example.test')")
    original = path.read_bytes()

    artifact = describe_file_evidence(str(path), deep=True)
    text = artifact["content_text"]
    leads = [item for item in extract_entities(text) if item.entity_type == EntityType.EMAIL]
    assert {item.value for item in leads} == {"first@example.test", "later@example.test"}
    assert all(text[item.start:item.end] == item.value for item in leads)
    assert artifact["extraction_status"] == "partial"
    assert "invalid UTF-8" in artifact["read_error"]
    assert artifact["content_hash"] == hashlib.sha256(original).hexdigest()
    assert path.read_bytes() == original
