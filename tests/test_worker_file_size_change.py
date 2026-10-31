"""Standalone evidence must not receive a digest for an incomplete read."""

import io
from unittest.mock import patch

from worker.main import describe_file_evidence


def test_standalone_short_read_is_not_reported_as_complete(tmp_path):
    evidence = tmp_path / "note.txt"
    evidence.write_bytes(b"complete evidence")

    with patch("builtins.open", return_value=io.BytesIO(b"partial")):
        artifact = describe_file_evidence(str(evidence))

    assert artifact["extraction_status"] == "error"
    assert artifact["content_truncated"] is True
    assert artifact["content_hash"] is None
    assert artifact["content_text"] is None
    assert "expected 17 bytes, read 7 bytes" in artifact["read_error"]


def test_standalone_growth_is_not_reported_as_complete(tmp_path):
    evidence = tmp_path / "note.txt"
    evidence.write_bytes(b"old")

    with patch("builtins.open", return_value=io.BytesIO(b"newer")):
        artifact = describe_file_evidence(str(evidence))

    assert artifact["extraction_status"] == "error"
    assert artifact["content_truncated"] is False
    assert artifact["content_hash"] is None
    assert artifact["content_text"] is None
