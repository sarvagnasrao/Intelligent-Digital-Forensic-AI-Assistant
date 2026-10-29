"""Batched semantic indexing: request counts, failure isolation, idempotency.

The service is exercised against a real in-memory SQLite database and a fake
Qdrant client, so the query filter, the batching loop and the status handling
are all covered without needing Qdrant or Ollama to run.
"""
from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.artifacts.models import Artifact, ArtifactType, IndexStatus
from app.artifacts.service import SearchService
from app.auth.models import Case, User
from app.evidence.models import Evidence

VECTOR_SIZE = 384
CASE_ID = 1


class FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = str(self._payload)

    def json(self) -> dict:
        return self._payload


class FakeQdrant:
    """Records upserts and can pretend the collection is missing."""

    def __init__(self, collection_exists: bool = True, upsert_status: int = 200):
        self.collection_exists = collection_exists
        self.upsert_status = upsert_status
        self.get_urls: list[str] = []
        self.put_urls: list[str] = []
        self.upserts: list[dict] = []

    async def get(self, url, **kwargs):
        self.get_urls.append(url)
        return FakeResponse(200 if self.collection_exists else 404)

    async def put(self, url, json=None, **kwargs):  # noqa: A002 - httpx signature
        self.put_urls.append(url)
        if url.endswith("/points"):
            self.upserts.append(json or {})
            return FakeResponse(self.upsert_status)
        # Collection creation.
        return FakeResponse(200)

    async def aclose(self):
        return None


@pytest.fixture
def session():
    from app.db import Base, load_all_models

    load_all_models()
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db_session:
        user = User(
            username="index-test", email="index@test.invalid",
            password_hash="x", full_name="Index Test",
        )
        db_session.add(user)
        db_session.flush()
        case = Case(case_id="CASE-1", title="Index case", created_by_id=user.id)
        db_session.add(case)
        db_session.flush()
        db_session.add(Evidence(
            evidence_id="E-1", case_id=case.id, name="Evidence disk",
            source_path="/evidence.img", registered_by_id=user.id,
        ))
        db_session.commit()
        yield db_session
    engine.dispose()


@pytest.fixture
def service(config_home, data_dir, session):
    """A SearchService wired to a fake Qdrant and a batch size of two."""
    from app.config import Config, save_config, set_data_dir

    config = set_data_dir(Config(), data_dir)
    config.embeddings.batch_size = 2
    save_config(config)

    search = SearchService(session)
    search._client = FakeQdrant()
    return search


@pytest.fixture
def fake_qdrant(service):
    return service._client


def add_artifacts(
    session, count: int, *, contents: list[str | None] | None = None
) -> list[Artifact]:
    artifacts = []
    for index in range(count):
        content = contents[index] if contents else f"content for file {index}"
        artifacts.append(
            Artifact(
                artifact_id=f"ART-{index:04d}",
                case_id=CASE_ID,
                evidence_id=1,
                artifact_type=ArtifactType.FILE,
                name=f"file-{index}.txt",
                source_path=f"/docs/file-{index}.txt",
                content_text=content,
                index_status=IndexStatus.NOT_INDEXED,
            )
        )
    session.add_all(artifacts)
    session.commit()
    return artifacts


def run_index(service) -> dict:
    return asyncio.run(service.index_artifacts(CASE_ID))


def stub_embedder(monkeypatch, function):
    """Patch the function ``index_artifacts`` imports lazily."""
    import app.ai.embeddings as embeddings

    monkeypatch.setattr(embeddings, "embed_texts", function)


def good_vectors(texts: list[str]) -> list[list[float]]:
    return [[0.01 * (index + 1)] * VECTOR_SIZE for index, _ in enumerate(texts)]


def test_embeds_and_upserts_one_batch_at_a_time(session, service, monkeypatch):
    artifacts = add_artifacts(session, 5)
    calls: list[int] = []

    def embed(texts):
        calls.append(len(texts))
        return good_vectors(texts)

    stub_embedder(monkeypatch, embed)

    result = run_index(service)

    # Five artifacts with a batch size of two becomes three requests...
    assert calls == [2, 2, 1]
    # ...and three upserts, one per batch rather than one per artifact.
    assert [len(body["points"]) for body in service._client.upserts] == [2, 2, 1]
    assert result == {
        "indexed": 5, "total": 5, "chunks": 5, "failed": 0, "errors": []
    }
    assert all(a.index_status is IndexStatus.INDEXED for a in artifacts)
    assert all(a.vector_id for a in artifacts)


def test_indexing_reports_live_batch_progress(session, service, monkeypatch):
    add_artifacts(session, 3)
    stub_embedder(monkeypatch, good_vectors)
    progress = []

    result = asyncio.run(
        service.index_artifacts(
            CASE_ID,
            progress_callback=lambda *values: progress.append(values),
        )
    )

    assert result["indexed"] == 3
    assert progress[0][0] == "Preparing semantic index"
    assert progress[-1] == (
        "Semantic indexing complete", 3, 3, 3, 0
    )
    assert any("Embedding passages" in event[0] for event in progress)


def test_point_ids_are_deterministic(session, service, monkeypatch):
    artifacts = add_artifacts(session, 2)
    stub_embedder(monkeypatch, good_vectors)

    run_index(service)

    points = service._client.upserts[0]["points"]
    expected = [
        str(uuid.uuid5(uuid.NAMESPACE_URL, f"idfa:{CASE_ID}:{artifact.id}:0"))
        for artifact in artifacts
    ]
    assert [point["id"] for point in points] == expected

    # Re-indexing the same rows must reuse the ids, not add duplicates.
    for artifact in artifacts:
        artifact.index_status = IndexStatus.NOT_INDEXED
    session.commit()
    run_index(service)

    second = service._client.upserts[1]["points"]
    assert [point["id"] for point in second] == expected


def test_payload_carries_searchable_fields(session, service, monkeypatch):
    add_artifacts(session, 1, contents=["the quick brown fox " * 100])
    stub_embedder(monkeypatch, good_vectors)

    run_index(service)

    payload = service._client.upserts[0]["points"][0]["payload"]
    assert payload["artifact_id"] == "ART-0000"
    assert payload["case_id"] == CASE_ID
    assert payload["artifact_type"] == ArtifactType.FILE.value
    assert payload["name"] == "file-0.txt"
    assert payload["source_path"] == "/docs/file-0.txt"
    # The snippet is truncated so a huge document cannot bloat Qdrant.
    assert len(payload["snippet"]) == 500


def test_an_embedding_failure_only_fails_its_own_batch(session, service, monkeypatch):
    artifacts = add_artifacts(session, 4)

    def embed(texts):
        if "content for file 0" in texts:
            raise RuntimeError("ollama went away")
        return good_vectors(texts)

    stub_embedder(monkeypatch, embed)

    result = run_index(service)

    assert result["indexed"] == 2
    assert result["total"] == 4
    # Failures are counted per batch, not per artifact.
    assert result["failed"] == 1
    assert "batch of 2" in result["errors"][0]
    assert all(a.index_status is IndexStatus.INDEX_FAILED for a in artifacts[:2])
    assert all(a.index_status is IndexStatus.INDEXED for a in artifacts[2:])
    # Only the surviving batch reaches Qdrant.
    assert [len(body["points"]) for body in service._client.upserts] == [2]


def test_a_vector_count_mismatch_fails_the_batch(session, service, monkeypatch):
    artifacts = add_artifacts(session, 2)
    stub_embedder(monkeypatch, lambda texts: good_vectors(texts)[:1])

    result = run_index(service)

    assert result["indexed"] == 0
    assert result["failed"] == 1
    assert "returned 1 vectors" in result["errors"][0]
    assert all(a.index_status is IndexStatus.INDEX_FAILED for a in artifacts)
    assert service._client.upserts == []


def test_a_blank_vector_fails_only_that_artifact(session, service, monkeypatch):
    artifacts = add_artifacts(session, 2)

    def embed(texts):
        return [good_vectors(texts)[0], []]

    stub_embedder(monkeypatch, embed)

    result = run_index(service)

    assert result["indexed"] == 1
    assert result["failed"] == 1
    assert "ART-0001" in result["errors"][0]
    assert artifacts[0].index_status is IndexStatus.INDEXED
    assert artifacts[1].index_status is IndexStatus.INDEX_FAILED
    # The rejected artifact must not appear in the upsert body.
    assert len(service._client.upserts[0]["points"]) == 1


def test_a_qdrant_rejection_marks_the_batch_failed(session, service, monkeypatch):
    artifacts = add_artifacts(session, 3)
    service._client.upsert_status = 500
    stub_embedder(monkeypatch, good_vectors)

    result = run_index(service)

    assert result["indexed"] == 0
    # Two batches were attempted, so two failures are reported.
    assert result["failed"] == 2
    assert all("HTTP 500" in error for error in result["errors"])
    assert all(a.index_status is IndexStatus.INDEX_FAILED for a in artifacts)
    assert all(a.vector_id is None for a in artifacts)


def test_qdrant_being_unreachable_is_reported_per_batch(session, service, monkeypatch):
    add_artifacts(session, 2)
    stub_embedder(monkeypatch, good_vectors)

    async def explode(*args, **kwargs):
        raise OSError("connection refused")

    service._client.put = explode

    result = run_index(service)

    assert result["indexed"] == 0
    assert result["failed"] == 1
    assert "Qdrant upsert failed" in result["errors"][0]


def test_only_new_and_failed_artifacts_are_retried(session, service, monkeypatch):
    artifacts = add_artifacts(session, 3)
    artifacts[0].index_status = IndexStatus.INDEXED
    artifacts[1].index_status = IndexStatus.INDEX_FAILED
    artifacts[2].index_status = IndexStatus.NOT_INDEXED
    session.commit()
    stub_embedder(monkeypatch, good_vectors)

    result = run_index(service)

    assert result["total"] == 2
    assert result["indexed"] == 2
    assert artifacts[0].vector_id is None  # untouched, already indexed


def test_artifacts_without_text_are_not_sent_for_embedding(session, service, monkeypatch):
    add_artifacts(session, 2, contents=["", None])
    stub_embedder(monkeypatch, good_vectors)

    result = run_index(service)

    # The query filters missing and empty text, so there is nothing to embed.
    assert result == {"indexed": 0, "message": "No artifacts to index"}
    assert service._client.upserts == []


def test_nothing_to_index_is_not_an_error(session, service, monkeypatch):
    stub_embedder(monkeypatch, good_vectors)

    result = run_index(service)

    assert result == {"indexed": 0, "message": "No artifacts to index"}


def test_collection_is_created_when_missing(session, service, monkeypatch):
    """A first index run on a new case must create the Qdrant collection."""
    add_artifacts(session, 1)
    service._client.collection_exists = False
    stub_embedder(monkeypatch, good_vectors)

    run_index(service)

    collection_urls = [url for url in service._client.put_urls if not url.endswith("/points")]
    assert collection_urls == [f"http://127.0.0.1:6333/collections/idfa_case_{CASE_ID}"]
    assert service._client.get_urls[0].endswith(f"/collections/idfa_case_{CASE_ID}")


def test_existing_collection_is_not_recreated(session, service, monkeypatch):
    add_artifacts(session, 1)
    stub_embedder(monkeypatch, good_vectors)

    run_index(service)

    collection_urls = [url for url in service._client.put_urls if not url.endswith("/points")]
    assert collection_urls == []
