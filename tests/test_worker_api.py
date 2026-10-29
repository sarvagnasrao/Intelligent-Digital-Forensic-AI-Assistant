"""Worker HTTP contract: health, embeddings, examination errors, progress."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import worker.main as worker_main

VECTOR_SIZE = 384


def test_extraction_does_not_fake_pdf_or_image_content():
    assert worker_main.extract_text_content(b"%PDF-1.7", "application/pdf", ".pdf", deep=True) is None
    assert worker_main.extract_text_content(b"not an image", "image/jpeg", ".jpg", deep=True) is None


def test_text_extraction_is_not_limited_by_legacy_character_cap():
    text = "forensic evidence " * 15_000
    actual = worker_main.extract_text_content(text.encode(), "text/plain", ".txt")
    assert actual == text


@pytest.fixture
def client(monkeypatch):
    """A TestClient with the network probes replaced by inert stubs.

    No test may reach the real Ollama or Qdrant, and no test should depend on
    whether they happen to be running on the machine.
    """

    async def offline_ollama():
        return False, False

    async def offline_qdrant():
        return False

    monkeypatch.setattr(worker_main, "_probe_ollama", offline_ollama)
    monkeypatch.setattr(worker_main, "_probe_qdrant", offline_qdrant)

    with TestClient(worker_main.app) as test_client:
        yield test_client


def test_health_reports_every_dependency(client):
    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "status",
        "pytsk3",
        "pyewf",
        "ollama",
        "qdrant",
        "embeddings",
    }
    assert body["status"] in {"ok", "degraded"}
    assert body["ollama"] is False
    assert body["qdrant"] is False
    assert body["embeddings"] is False


def test_health_reports_ollama_and_embeddings_separately(client, monkeypatch):
    """Ollama can be up while the embedding model is not pulled."""

    async def running_ollama():
        return True, True

    async def running_qdrant():
        return True

    monkeypatch.setattr(worker_main, "_probe_ollama", running_ollama)
    monkeypatch.setattr(worker_main, "_probe_qdrant", running_qdrant)

    body = client.get("/health").json()

    assert body["ollama"] is True
    assert body["embeddings"] is True
    assert body["qdrant"] is True


def test_health_reports_ollama_up_without_embeddings(client, monkeypatch):
    async def running_ollama():
        return True, False

    monkeypatch.setattr(worker_main, "_probe_ollama", running_ollama)

    body = client.get("/health").json()

    assert body["ollama"] is True
    assert body["embeddings"] is False


def test_embed_returns_one_vector_per_text(client, monkeypatch):
    async def fake_embeddings(texts):
        assert texts == ["alpha", "beta"]
        return [[0.5] * VECTOR_SIZE for _ in texts]

    monkeypatch.setattr(worker_main, "get_embeddings", fake_embeddings)

    response = client.post("/embed", json={"texts": ["alpha", "beta"]})

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["dimensions"] == VECTOR_SIZE
    assert len(body["embeddings"]) == 2
    assert body["error"] is None


def test_embed_without_texts_makes_no_request(client, monkeypatch):
    async def fail(texts):
        raise AssertionError("should not embed an empty batch")

    monkeypatch.setattr(worker_main, "get_embeddings", fail)

    body = client.post("/embed", json={"texts": []}).json()

    assert body["success"] is True
    assert body["embeddings"] == []
    assert body["dimensions"] == 0


def test_embed_failure_names_the_model(client, monkeypatch):
    async def no_vectors(texts):
        return []

    monkeypatch.setattr(worker_main, "get_embeddings", no_vectors)

    body = client.post("/embed", json={"texts": ["alpha"]}).json()

    assert body["success"] is False
    assert worker_main.EMBEDDING_MODEL in body["error"]
    assert body["embeddings"] == []


def test_examine_rejects_a_missing_image(client, monkeypatch):
    monkeypatch.setattr(worker_main, "PYTSK3_AVAILABLE", True)

    response = client.post(
        "/examine",
        json={
            "case_id": 1,
            "evidence_id": 1,
            "image_path": "C:/definitely/not/here.E01",
            "operation": "partition_analysis",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is False
    assert "Image not found" in body["error"]


def test_examine_reports_missing_pytsk3(client, monkeypatch):
    monkeypatch.setattr(worker_main, "PYTSK3_AVAILABLE", False)

    body = client.post(
        "/examine",
        json={
            "case_id": 1,
            "evidence_id": 1,
            "image_path": "C:/anything.img",
            "operation": "partition_analysis",
        },
    ).json()

    assert body["success"] is False
    assert "pytsk3" in body["error"]


def test_file_extraction_probes_partitions_like_file_traversal(
    client, monkeypatch, tmp_path
):
    monkeypatch.setattr(worker_main, "PYTSK3_AVAILABLE", True)
    image = tmp_path / "partitioned.dd"
    image.write_bytes(b"image")
    monkeypatch.setattr(worker_main, "get_partitions", lambda _path: [
        {"offset": 0}, {"offset": 1_048_576}
    ])
    mounted_offsets = []

    def filesystem(_path, offset):
        mounted_offsets.append(offset)
        if offset == 0:
            worker_main._fs_info = None
            return {"error": "No filesystem at the partition table"}
        worker_main._fs_info = object()
        return {"fs_type": "NTFS"}

    monkeypatch.setattr(worker_main, "get_filesystem_info", filesystem)
    monkeypatch.setattr(
        worker_main,
        "walk_and_extract_artifacts",
        lambda *_args, **_kwargs: [{"name": "notes.txt", "path": "/notes.txt"}],
    )

    body = client.post(
        "/examine",
        json={
            "case_id": 1,
            "evidence_id": 1,
            "image_path": str(image),
            "operation": "file_extraction",
        },
    ).json()

    assert body["success"] is True
    assert mounted_offsets == [0, 1_048_576]
    assert body["results"][0]["data"]["partition_offset"] == 1_048_576


def test_progress_defaults_for_an_unknown_job(client):
    body = client.get("/examine/JOB-DOES-NOT-EXIST/progress").json()

    assert body["progress"] == 0
    assert body["message"]


def test_progress_returns_the_recorded_state(client):
    worker_main._examination_progress["JOB-TEST"] = {
        "progress": 42,
        "message": "Traversing files",
        "status": "running",
    }
    try:
        body = client.get("/examine/JOB-TEST/progress").json()
    finally:
        worker_main._examination_progress.pop("JOB-TEST", None)

    assert body["progress"] == 42
    assert body["message"] == "Traversing files"


def test_pause_and_resume_examination_worker_job(client):
    job_id = "JOB-PAUSE-TEST"
    worker_main._examination_progress[job_id] = {
        "progress": 42,
        "message": "Traversing files",
        "status": "running",
    }
    try:
        paused = client.post(f"/examine/{job_id}/pause")
        assert paused.status_code == 200
        assert job_id in worker_main._paused_jobs

        resumed = client.post(f"/examine/{job_id}/resume")
        assert resumed.status_code == 200
        assert job_id not in worker_main._paused_jobs
        assert worker_main._examination_progress[job_id]["status"] == "running"
    finally:
        with worker_main._job_control:
            worker_main._paused_jobs.discard(job_id)
            worker_main._examination_progress.pop(job_id, None)
            worker_main._job_control.notify_all()


def test_cancel_marks_only_an_active_worker_job_as_cancelling(client):
    job_id = "JOB-CANCEL-TEST"
    with worker_main._job_control:
        worker_main._active_jobs.add(job_id)
        worker_main._examination_progress[job_id] = {
            "progress": 42,
            "message": "Traversing files",
            "status": "running",
        }
    try:
        response = client.post(f"/examine/{job_id}/cancel")

        assert response.status_code == 200
        assert response.json()["status"] == "cancelling"
        assert job_id in worker_main._cancelled_jobs
        assert worker_main._examination_progress[job_id]["status"] == "cancelling"
        assert client.post("/examine/NOT-ACTIVE/cancel").status_code == 409
    finally:
        with worker_main._job_control:
            worker_main._active_jobs.discard(job_id)
            worker_main._cancelled_jobs.discard(job_id)
            worker_main._examination_progress.pop(job_id, None)
            worker_main._job_control.notify_all()


def test_extract_artifact_rejects_a_missing_image(client):
    response = client.post(
        "/extract-artifact",
        json={"image_path": "C:/definitely/not/here.E01"},
    )

    assert response.status_code == 404


def test_extract_artifact_requires_a_locator(client, tmp_path, monkeypatch):
    monkeypatch.setattr(worker_main, "PYTSK3_AVAILABLE", True)
    image = tmp_path / "disk.img"
    image.write_bytes(b"\x00" * 1024)

    response = client.post("/extract-artifact", json={"image_path": str(image)})

    assert response.status_code == 400
    assert "inode or source path" in response.json()["detail"]


def test_text_extraction_keeps_real_text_whatever_the_depth():
    body = b"meeting notes: transfer approved"

    assert worker_main.extract_text_content(body, "text/plain", ".txt", deep=False) == (
        "meeting notes: transfer approved"
    )
    assert worker_main.extract_text_content(body, "text/plain", ".txt", deep=True)


def test_unsupported_binary_is_not_faked_as_hex():
    body = b"\x00\x01\x02\x03binary payload"

    assert worker_main.extract_text_content(body, None, ".bin", deep=False) is None
    assert worker_main.extract_text_content(body, None, ".bin", deep=True) is None


def test_image_without_ocr_capability_is_not_faked_as_text():
    body = b"\xff\xd8\xff\xe0" + b"\x00" * 64

    assert worker_main.extract_text_content(body, "image/jpeg", ".jpg", deep=False) is None
    assert worker_main.extract_text_content(body, "image/jpeg", ".jpg", deep=True) is None


def test_examine_applies_deep_extraction_to_the_returned_artifact(
    client, tmp_path, monkeypatch
):
    """The Advanced switch must change the response, not only the job log.

    A plain file has no filesystem to mount, so the worker describes the file
    itself. The same bytes are examined twice and only the flag differs.
    """
    monkeypatch.setattr(worker_main, "PYTSK3_AVAILABLE", True)
    monkeypatch.setattr(worker_main, "get_partitions", lambda _path: [])
    payload = tmp_path / "payload.bin"
    payload.write_bytes(b"\x00\x01\x02\x03binary payload")

    def examined_content(deep: bool):
        response = client.post(
            "/examine",
            json={
                "case_id": 1,
                "evidence_id": 1,
                "image_path": str(payload),
                "operation": "full_examination",
                "job_id": f"J-deep-{deep}",
                "parameters": {"deep_extraction": deep},
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        artifacts = next(
            result for result in body["results"] if result["type"] == "artifacts"
        )
        return artifacts["data"]["artifacts"][0]["content_text"]

    assert examined_content(False) is None
    assert examined_content(True) is None



def test_generation_limits_clamp_an_oversized_context_window():
    """A 131072-token window asks phi3:mini for a 48 GiB KV cache."""
    num_ctx, num_predict = worker_main.resolve_generation_limits(131072, 100000)

    assert num_ctx == worker_main.MAX_CONTEXT_TOKENS
    assert num_predict == worker_main.MAX_OUTPUT_TOKENS


def test_generation_limits_keep_a_modest_reply_inside_the_window():
    num_ctx, num_predict = worker_main.resolve_generation_limits(4096, 512)

    assert num_ctx == 4096
    assert num_predict == 512


def test_generation_limits_never_go_below_the_floor():
    num_ctx, num_predict = worker_main.resolve_generation_limits(0, 0)

    assert num_ctx == worker_main.MIN_CONTEXT_TOKENS
    assert num_predict >= 256


def test_generation_limits_never_leave_no_room_for_the_prompt():
    num_ctx, num_predict = worker_main.resolve_generation_limits(2048, 999999)

    assert num_predict <= num_ctx // 2


class _FailingResponse:
    def __init__(self, status_code: int, text: str):
        self.status_code = status_code
        self.text = text
        self.json = lambda: {}


def test_call_ollama_reports_the_reason_instead_of_an_empty_answer(monkeypatch):
    """The GUI used to show a generic failure because the worker swallowed this."""

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        async def post(self, *_args, **_kwargs):
            return _FailingResponse(500, '{"error":"model requires more system memory"}')

    monkeypatch.setattr("httpx.AsyncClient", lambda **_: _Client())

    with pytest.raises(worker_main.OllamaError) as caught:
        import asyncio

        asyncio.run(worker_main.call_ollama("hello"))

    assert "model requires more system memory" in str(caught.value)


def test_call_ollama_retries_with_a_smaller_window_after_an_oom(monkeypatch):
    calls: list[int] = []

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        async def post(self, _url, json, **_kwargs):
            calls.append(json["options"]["num_ctx"])
            if len(calls) == 1:
                return _FailingResponse(500, "failed to allocate buffer for kv cache")
            return _Reply(200, "")

    class _Reply(_FailingResponse):
        def __init__(self, status_code: int, text: str):
            super().__init__(status_code, text)
            # __init__ installs a placeholder; replace it so the reply parses.
            self.json = lambda: {"response": "ready"}

    monkeypatch.setattr("httpx.AsyncClient", lambda **_: _Client())

    import asyncio

    answer = asyncio.run(worker_main.call_ollama("hello", max_tokens=64))

    assert answer == "ready"
    assert calls == [worker_main.MAX_CONTEXT_TOKENS, worker_main.MAX_CONTEXT_TOKENS // 2]
