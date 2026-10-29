"""Keyword, regex and semantic search behaviour.

These tests target the accuracy bugs found in the old implementation: the FTS
MATCH only looked at ``content_text`` (so filenames and paths were
unsearchable), plain queries could not express a phrase or OR, and semantic
results could not say which passage matched.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.artifacts.models import Artifact, ArtifactType, IndexStatus
from app.auth.models import Case, User
from app.evidence.models import Evidence
from app.artifacts.service import (
    SearchError,
    SearchService,
    build_fts_query,
    chunk_text,
)


@pytest.fixture
def session(tmp_path):
    from app.db import Base, load_all_models
    from app.db.session import _FTS_TABLE_SQL, _FTS_TRIGGER_SQL

    load_all_models()
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'search.db'}")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(text(_FTS_TABLE_SQL))
        for statement in _FTS_TRIGGER_SQL:
            connection.execute(text(statement))
    with Session(engine) as db_session:
        user = User(
            username="search-test", email="search@test.invalid",
            password_hash="x", full_name="Search Test",
        )
        db_session.add(user)
        db_session.flush()
        case = Case(case_id="CASE-1", title="Search case", created_by_id=user.id)
        db_session.add(case)
        db_session.flush()
        db_session.add(Evidence(
            evidence_id="E-1", case_id=case.id, name="Evidence disk",
            source_path="/evidence.img", registered_by_id=user.id,
        ))
        db_session.commit()
        yield db_session
    engine.dispose()


def add_artifact(
    session,
    *,
    artifact_id: str,
    name: str,
    path: str,
    content: str | None = None,
    created: datetime | None = None,
) -> Artifact:
    artifact = Artifact(
        artifact_id=artifact_id,
        case_id=1,
        evidence_id=1,
        artifact_type=ArtifactType.FILE,
        name=name,
        source_path=path,
        content_text=content,
        created_time=created or datetime(2024, 5, 1, tzinfo=timezone.utc),
        index_status=IndexStatus.NOT_INDEXED,
    )
    session.add(artifact)
    session.commit()
    return artifact


def test_deleting_an_artifact_removes_it_from_the_case_inventory(session):
    artifact = add_artifact(
        session,
        artifact_id="ART-DELETE-1",
        name="delete-me.txt",
        path="/delete-me.txt",
        content="temporary extracted content",
    )
    artifact_pk = artifact.id
    investigator = session.query(User).one()

    assert SearchService(session).delete_artifact(1, artifact_pk, investigator)
    session.commit()

    assert session.get(Artifact, artifact_pk) is None
    assert not any(
        item["artifact"].id == artifact_pk
        for item in SearchService(session).list_case_artifacts(1)
    )


@pytest.fixture
def service(session, config_home, data_dir):
    from app.config import Config, save_config, set_data_dir

    save_config(set_data_dir(Config(), data_dir))
    return SearchService(session)


def run(coroutine):
    return asyncio.run(coroutine)


def test_a_filename_is_searchable(session, service):
    add_artifact(
        session, artifact_id="ART-1", name="budget-final.xlsx",
        path="/Finance/2024/budget-final.xlsx", content="quarterly numbers",
    )
    add_artifact(
        session, artifact_id="ART-2", name="notes.txt",
        path="/Users/alice/notes.txt", content="unrelated",
    )

    results = run(service.keyword_search(1, "budget"))

    assert [item["artifact"].artifact_id for item in results] == ["ART-1"]
    assert "name" in results[0]["matched_fields"]
    assert "budget-final" in results[0]["snippet"]


def test_case_inventory_lists_all_and_excludes_removed_evidence(session, service):
    active = add_artifact(
        session, artifact_id="ART-1", name="active.txt", path="/active.txt",
    )
    removed_evidence = Evidence(
        evidence_id="E-2", case_id=1, name="Removed disk",
        source_path="/removed.img", registered_by_id=1,
        removed_at=datetime.now(timezone.utc),
    )
    session.add(removed_evidence)
    session.flush()
    removed = Artifact(
        artifact_id="ART-2", case_id=1, evidence_id=removed_evidence.id,
        artifact_type=ArtifactType.FILE, name="removed.txt",
        source_path="/removed.txt", index_status=IndexStatus.NOT_INDEXED,
    )
    session.add(removed)
    session.commit()

    results = service.list_case_artifacts(1)

    assert [row["artifact"].id for row in results] == [active.id]
    assert results[0]["artifact"].evidence.name == "Evidence disk"


def test_a_directory_name_is_searchable(session, service):
    add_artifact(
        session, artifact_id="ART-1", name="log.txt",
        path="/Windows/System32/winevt/log.txt", content="nothing here",
    )

    results = run(service.keyword_search(1, "winevt"))

    assert len(results) == 1
    assert "path" in results[0]["matched_fields"]


def test_content_hit_returns_a_snippet_with_the_term(session, service):
    add_artifact(
        session, artifact_id="ART-1", name="chat.txt",
        path="/chat.txt",
        content=("filler " * 100) + "the transfer code is ALPHA-9 " + ("filler " * 100),
    )

    results = run(service.keyword_search(1, "ALPHA-9"))

    assert len(results) == 1
    assert "ALPHA-9" in results[0]["snippet"]
    assert "content" in results[0]["matched_fields"]


def test_a_quoted_phrase_only_matches_together(session, service):
    add_artifact(
        session, artifact_id="ART-1", name="a.txt", path="/a.txt",
        content="meeting at the blue house tomorrow",
    )
    add_artifact(
        session, artifact_id="ART-2", name="b.txt", path="/b.txt",
        content="blue paint and a house",
    )

    results = run(service.keyword_search(1, '"blue house"'))

    assert [item["artifact"].artifact_id for item in results] == ["ART-1"]


def test_or_expands_the_result_set(session, service):
    add_artifact(session, artifact_id="ART-1", name="a.txt", path="/a.txt", content="alpha")
    add_artifact(session, artifact_id="ART-2", name="b.txt", path="/b.txt", content="bravo")

    results = run(service.keyword_search(1, "alpha OR bravo"))

    assert {item["artifact"].artifact_id for item in results} == {"ART-1", "ART-2"}


def test_invalid_fts_syntax_is_reported(session, service):
    add_artifact(session, artifact_id="ART-1", name="a.txt", path="/a.txt", content="alpha")

    with pytest.raises(SearchError) as excinfo:
        run(service.keyword_search(1, '"unclosed'))

    assert "syntax" in str(excinfo.value).lower()


def test_plain_words_are_and_ed_prefix_matches():
    assert build_fts_query("blue house") == '"blue"* "house"*'
    assert build_fts_query('"blue house"') == '"blue house"'
    assert build_fts_query("alpha OR bravo") == "alpha OR bravo"


def test_regex_can_match_across_fields(session, service):
    add_artifact(
        session, artifact_id="ART-1", name="IMG_2041.JPG", path="/DCIM/IMG_2041.JPG",
        content="camera",
    )
    add_artifact(session, artifact_id="ART-2", name="IMG_9999.JPG", path="/other/IMG_9999.JPG")

    results = run(service.keyword_search(1, r"IMG_20\d\d", regex=True))

    assert [item["artifact"].artifact_id for item in results] == ["ART-1"]
    assert results[0]["source"] == "regex"


def test_an_invalid_regex_is_reported(session, service):
    with pytest.raises(SearchError) as excinfo:
        run(service.keyword_search(1, "([", regex=True))
    assert "regular expression" in str(excinfo.value).lower()


def test_chunks_keep_offsets_and_overlap():
    content = "x" * 3000

    chunks = chunk_text(content, size=1200, overlap=200)

    assert len(chunks) == 3
    starts = [start for start, _end, _text in chunks]
    assert starts[0] == 0
    # The next chunk starts inside the previous one, not after it.
    assert starts[1] == 1000
    assert all(len(piece) <= 1200 for _s, _e, piece in chunks)


class FakeResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)

    def json(self):
        return self._payload


def test_semantic_hits_collapse_to_one_row_per_file(session, service, monkeypatch):
    artifact = add_artifact(
        session, artifact_id="ART-1", name="contract.pdf", path="/contract.pdf",
        content="a long agreement",
    )

    class FakeClient:
        async def post(self, url, json=None, **kwargs):  # noqa: A002
            return FakeResponse(200, {"result": [
                {
                    "score": 0.72,
                    "payload": {
                        "artifact_id": "ART-1",
                        "chunk_index": 3,
                        "text": "the payment clause is due on the fifth",
                    },
                },
                {
                    "score": 0.91,
                    "payload": {
                        "artifact_id": "ART-1",
                        "chunk_index": 7,
                        "text": "termination requires thirty days notice",
                    },
                },
            ]})

        async def aclose(self):
            return None

    service._client = FakeClient()
    monkeypatch.setattr(
        "app.ai.embeddings.embed_text", lambda value: [0.1] * 384
    )

    results = run(service.semantic_search(1, "termination"))

    assert len(results) == 1
    assert results[0]["artifact"].id == artifact.id
    assert results[0]["chunk_index"] == 7
    assert "thirty days" in results[0]["snippet"]


def test_hybrid_does_not_repeat_an_artifact(session, service, monkeypatch):
    add_artifact(
        session, artifact_id="ART-1", name="budget.txt", path="/budget.txt",
        content="the budget is approved",
    )

    class FakeClient:
        async def post(self, url, json=None, **kwargs):  # noqa: A002
            return FakeResponse(200, {"result": [
                {"score": 0.9, "payload": {
                    "artifact_id": "ART-1", "chunk_index": 0, "text": "budget approved",
                }},
            ]})

        async def aclose(self):
            return None

    service._client = FakeClient()
    monkeypatch.setattr("app.ai.embeddings.embed_text", lambda value: [0.1] * 384)

    results = run(service.hybrid_search(1, "budget"))

    assert len(results) == 1
    assert results[0]["sources"] == ["keyword", "semantic"]
    assert results[0]["snippet"]
