from app.ui.pages.tools_page import _read_log_tail


def test_log_filter_keeps_tracebacks_with_matching_record(tmp_path):
    path = tmp_path / "idfa.log"
    contents = (
        "2026-01-01 | INFO     | app | ERROR in message\n"
        "2026-01-01 | ERROR    | app | failure\n"
        "Traceback (most recent call last):\n"
        "  failure detail\n"
        "2026-01-01 | CRITICAL | app | stopped\n"
    )
    path.write_text(contents, encoding="utf-8")
    assert _read_log_tail(path, "All") == contents
    assert _read_log_tail(path, "ERROR") == (
        "2026-01-01 | ERROR    | app | failure\n"
        "Traceback (most recent call last):\n"
        "  failure detail\n"
    )
    assert "stopped" in _read_log_tail(path, "CRITICAL")


def test_log_tail_is_limited_and_decodes_damaged_bytes(tmp_path):
    path = tmp_path / "idfa.log"
    path.write_bytes(b"old\n" * 1000 + b"new\xff\n")
    tail = _read_log_tail(path, "All")
    assert len(tail.splitlines()) == 1000
    assert tail.endswith("new\ufffd\n")
