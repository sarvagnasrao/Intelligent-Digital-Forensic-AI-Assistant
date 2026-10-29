"""Artifact records created from worker extraction results.

``full_examination`` reports its rows under ``"artifacts"`` while
``file_traversal`` reports the same fields under ``"files"``. Only the first was
read, so a traversal finished "successfully" and left nothing to search.
"""
from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.artifacts.models import Artifact
from app.auth.models import Case, User
from app.evidence.models import Evidence
from app.examination.service import ExaminationService

CASE_ID = None  # filled in by the fixture below; ids are per-database


@pytest.fixture
def session():
    from app.db import Base, load_all_models

    load_all_models()
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db_session:
        yield db_session
    engine.dispose()


@pytest.fixture
def records(session):
    """Return ``(case, evidence)`` rows to hang artifacts off."""
    user = User(username="t", email="t@example.test", password_hash="x", full_name="T")
    session.add(user)
    session.commit()

    case = Case(case_id="C-1", title="Case", created_by_id=user.id)
    session.add(case)
    session.commit()

    evidence = Evidence(
        evidence_id="E-1",
        case_id=case.id,
        name="disk.img",
        source_path="C:/evidence/disk.img",
        registered_by_id=user.id,
    )
    session.add(evidence)
    session.commit()
    return case, evidence


def make_rows() -> list[dict]:
    return [
        {
            "name": "notes.txt",
            "path": "/users/a/notes.txt",
            "artifact_type": "file",
            "mime_type": "text/plain",
            "extension": ".txt",
            "size": 11,
            "inode": 42,
            "allocated": True,
            "deleted": False,
            "content_text": "hello world",
            "content_hash": "abc",
            "mtime": 0,
        },
        {
            "name": "gone.jpg",
            "path": "/users/a/gone.jpg",
            "artifact_type": "image",
            "mime_type": "image/jpeg",
            "extension": ".jpg",
            "size": 2048,
            "inode": 43,
            "allocated": False,
            "deleted": True,
        },
    ]


def create(session, case, evidence, data):
    service = ExaminationService(session)
    asyncio.run(
        service._create_artifact_records(case.id, evidence.id, 1, data)
    )
    session.commit()
    return list(session.execute(select(Artifact).order_by(Artifact.id)).scalars())


def test_file_traversal_results_become_artifacts(session, records):
    case, evidence = records

    artifacts = create(session, case, evidence, {
        "files": make_rows(),
        "partition_offset": 32256,
    })

    assert [a.name for a in artifacts] == ["notes.txt", "gone.jpg"]
    assert artifacts[0].content_text == "hello world"
    assert artifacts[0].content_hash == "abc"
    assert artifacts[0].source_path == "/users/a/notes.txt"
    assert artifacts[0].examination_job_id == 1
    assert "32256" in artifacts[0].metadata_json
    assert artifacts[1].description.startswith("Deleted")


def test_full_examination_results_still_work(session, records):
    case, evidence = records

    artifacts = create(session, case, evidence, {"artifacts": make_rows()})

    assert len(artifacts) == 2


def test_artifact_ids_are_sequential(session, records):
    """A new path continues the sequence; a repeated path reuses its row."""
    case, evidence = records

    first = create(session, case, evidence, {"files": make_rows()[:1]})
    second = create(session, case, evidence, {"files": make_rows()[:1]})
    third = create(session, case, evidence, {"files": make_rows()[1:2]})

    assert [a.artifact_id for a in first] == [f"ART-{case.id:04d}-0001"]
    # Re-ingesting the same source path updates the existing row instead of
    # duplicating every search result, so the id is unchanged.
    assert [a.artifact_id for a in second] == [f"ART-{case.id:04d}-0001"]
    assert [a.artifact_id for a in third] == [
        f"ART-{case.id:04d}-0001",
        f"ART-{case.id:04d}-0002",
    ]


def test_reingesting_the_same_path_updates_in_place(session, records):
    case, evidence = records

    create(session, case, evidence, {"files": make_rows()[:1]})
    updated = create(session, case, evidence, {
        "files": [{**make_rows()[0], "content_text": "changed", "content_hash": "def"}],
    })

    assert len(updated) == 1
    assert updated[0].content_text == "changed"
    assert updated[0].content_hash == "def"


def test_reingesting_identical_content_keeps_the_row_untouched(session, records):
    case, evidence = records

    create(session, case, evidence, {"files": make_rows()[:1]})
    service = ExaminationService(session)
    stats = asyncio.run(
        service._create_artifact_records(case.id, evidence.id, 1, {"files": make_rows()[:1]})
    )
    session.commit()

    assert stats == {"created": 0, "updated": 1}
    assert len(list(session.execute(select(Artifact)).scalars())) == 1


def test_ids_are_unique_within_one_batch(session, records):
    """The session does not autoflush, so the counter must not be re-queried."""
    case, evidence = records

    artifacts = create(session, case, evidence, {"files": make_rows()})

    ids = [a.artifact_id for a in artifacts]
    assert ids == [f"ART-{case.id:04d}-0001", f"ART-{case.id:04d}-0002"]
    assert len(set(ids)) == len(ids)


def test_an_empty_payload_creates_nothing(session, records):
    case, evidence = records

    assert create(session, case, evidence, {}) == []
    assert create(session, case, evidence, {"files": [], "artifacts": []}) == []


def test_an_unknown_artifact_type_falls_back_to_file(session, records):
    case, evidence = records
    row = make_rows()[0]
    row["artifact_type"] = "not-a-real-type"

    artifacts = create(session, case, evidence, {"files": [row]})

    assert artifacts[0].artifact_type.value == "file"
