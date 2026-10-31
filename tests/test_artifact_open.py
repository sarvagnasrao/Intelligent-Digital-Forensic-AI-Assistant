"""Opening an artifact from the search results.

An artifact stored inside an evidence image is materialised through the worker,
and that branch used ``get_config`` without importing it, so every attempt ended
with the message "name 'get_config' is not defined".
"""
from __future__ import annotations


class _FakeResponse:
    status_code = 200
    content = b"%PDF-1.4 extracted by the worker"
    text = ""


def test_artifact_inside_an_image_is_fetched_from_the_worker(qt_app, monkeypatch):
    from app.ui.pages import artifacts_search_page as page_module
    from app.ui.pages.artifacts_search_page import OpenArtifactWorker

    calls: list[dict] = []

    def fake_post(url, json=None, timeout=None):
        calls.append({"url": url, "json": json, "timeout": timeout})
        return _FakeResponse()

    monkeypatch.setattr(page_module.httpx, "post", fake_post)

    worker = OpenArtifactWorker({
        "name": "report.pdf",
        "extension": ".pdf",
        "evidence_path": "C:/case/disk.dd",
        "inode": 42,
        "source_path": "/docs/report.pdf",
        "partition_offset": 1048576,
    })
    seen: list[dict] = []
    worker.finished.connect(seen.append)

    worker.run()

    assert seen and seen[0]["error"] is None, seen
    assert calls and calls[0]["url"].endswith("/extract-artifact")
    assert calls[0]["json"]["inode"] == 42
    assert calls[0]["json"]["partition_offset"] == 1048576

    from pathlib import Path

    extracted = Path(seen[0]["path"])
    assert extracted.suffix == ".pdf"
    assert extracted.read_bytes() == _FakeResponse.content
    extracted.unlink(missing_ok=True)


def test_unsupported_extension_is_refused_before_any_request(qt_app, monkeypatch):
    from app.ui.pages import artifacts_search_page as page_module
    from app.ui.pages.artifacts_search_page import OpenArtifactWorker

    def fail(*args, **kwargs):  # pragma: no cover - must not be reached
        raise AssertionError("the worker must not be asked to extract a .exe")

    monkeypatch.setattr(page_module.httpx, "post", fail)

    worker = OpenArtifactWorker({
        "name": "payload.exe", "extension": ".exe",
        "evidence_path": "C:/case/disk.dd", "inode": 7,
    })
    seen: list[dict] = []
    worker.finished.connect(seen.append)

    worker.run()

    assert seen and "disabled" in seen[0]["error"]
