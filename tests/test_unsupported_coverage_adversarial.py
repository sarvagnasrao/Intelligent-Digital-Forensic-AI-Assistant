"""Coverage must reflect worker status, not inferred format support."""

from app.examination.service import extraction_coverage


def test_worker_status_takes_precedence_over_misleading_text():
    counts = extraction_coverage([
        {"name": "readable.txt", "extraction_status": "unsupported_or_no_text", "content_text": "misleading"},
        {"name": "unknown.xyz", "extraction_status": "extracted", "content_text": "actual text"},
        {"extraction_status": "unsupported_or_no_text", "read_error": "read failed"},
        {"extraction_status": "unsupported_or_no_text", "deleted": True},
        {"name": "legacy.bin"},
    ])
    assert counts == {"total": 5, "text": 1, "deleted": 1, "read_errors": 1,
                      "partial": 0, "unsupported_or_no_text": 1, "no_text": 1}


def test_worker_single_file_reports_unsupported_or_no_text(tmp_path):
    from worker.main import describe_file_evidence

    path = tmp_path / "evidence.unsupported_example"
    path.write_bytes(b"searchable-looking content")
    result = describe_file_evidence(str(path))
    assert result["extraction_status"] == "unsupported_or_no_text"
    assert result["content_text"] is None
    assert result["content_hash"]
    assert extraction_coverage([result])["unsupported_or_no_text"] == 1
