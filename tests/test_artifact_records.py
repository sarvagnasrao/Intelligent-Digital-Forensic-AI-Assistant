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


def test_extraction_coverage_reports_missing_text_and_errors_separately():
    from app.examination.service import extraction_coverage

    rows = [
        {"content_text": "evidence"},
        {"deleted": True},
        {"read_error": "unreadable"},
        {"extraction_status": "error"},
        {"extraction_status": "unsupported_or_no_text"},
        {},
    ]
    assert extraction_coverage(rows) == {
        "total": 6, "text": 1, "deleted": 1, "read_errors": 2, "partial": 0,
        "unsupported_or_no_text": 1, "no_text": 1,
    }


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


def test_import_failure_reports_location_and_retains_committed_batch(session, records):
    case, evidence = records
    rows = [
        {"name": f"file-{i}.txt", "path": f"/file-{i}.txt", "content_text": "evidence"}
        for i in range(200)
    ]
    rows.append({"name": "broken", "path": "/broken", "size": object()})
    service = ExaminationService(session)
    with pytest.raises(RuntimeError, match=r"item 201/201 \(/broken\)"):
        asyncio.run(service._create_artifact_records(case.id, evidence.id, 1, {"files": rows}))
    assert len(session.execute(select(Artifact)).scalars().all()) == 200


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


def test_reingesting_bytes_path_updates_existing_blob(session, records):
    case, evidence = records
    row = {"name": "bytes path", "path": b"/bytes-path"}
    first = create(session, case, evidence, {"files": [row]})
    original_id = first[0].id
    case_id, evidence_id = case.id, evidence.id
    session.expunge_all()

    service = ExaminationService(session)
    stats = asyncio.run(service._create_artifact_records(
        case_id, evidence_id, 1, {"files": [{**row, "name": "updated"}]}
    ))
    session.commit()
    artifacts = list(session.execute(select(Artifact)).scalars())

    assert stats == {"created": 0, "updated": 1}
    assert len(artifacts) == 1
    assert artifacts[0].id == original_id
    assert artifacts[0].name == "updated"


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


def test_artifact_ingestion_reports_progress_at_the_batch_end(session, records):
    case, evidence = records
    updates = []
    service = ExaminationService(session)

    asyncio.run(service._create_artifact_records(
        case.id,
        evidence.id,
        1,
        {"artifacts": make_rows()},
        progress_callback=lambda processed, total: updates.append((processed, total)),
    ))

    assert updates == [(2, 2)]


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


def test_targeted_lookup_preserves_duplicate_and_pathless_behavior(session, records):
    case, evidence = records
    create(session, case, evidence, {"files": [{"path": "/dup", "name": "first"}]})
    duplicate = Artifact(artifact_id=f"ART-{case.id:04d}-0002", case_id=case.id,
                         evidence_id=evidence.id, name="second", source_path="/dup")
    old_null = Artifact(artifact_id=f"ART-{case.id:04d}-0003", case_id=case.id,
                        evidence_id=evidence.id, name="old null", source_path=None)
    session.add_all([duplicate, old_null])
    session.commit()
    stats = asyncio.run(ExaminationService(session)._create_artifact_records(
        case.id, evidence.id, 2, {"files": [
            {"path": "/dup", "name": "updated"},
            {"name": "new null"}, {"path": None, "name": "same null"},
            {"path": "", "name": "empty"}, {"path": "", "name": "same empty"},
        ]}))
    rows = session.execute(select(Artifact).order_by(Artifact.id)).scalars().all()
    assert stats == {"created": 2, "updated": 3}
    assert [row.name for row in rows] == ["first", "updated", "old null", "same null", "same empty"]
    assert rows[1].examination_job_id == 2


def test_targeted_lookup_large_batch_and_rollback(session, records):
    case, evidence = records
    rows = [{"path": f"/file-{i}", "name": str(i)} for i in range(1001)]
    create(session, case, evidence, {"files": rows})
    service = ExaminationService(session)
    with pytest.raises(RuntimeError, match="item 2/2"):
        asyncio.run(service._create_artifact_records(
            case.id, evidence.id, 2,
            {"files": [{"path": "/file-0", "name": "changed"},
                       {"path": "/bad", "size": object()}]},
            commit_interval=False))
    assert session.execute(select(Artifact).where(Artifact.source_path == "/file-0")).scalar_one().name == "0"
    stats = asyncio.run(service._create_artifact_records(
        case.id, evidence.id, 3, {"files": rows}, commit_interval=False))
    assert stats == {"created": 0, "updated": 1001}


@pytest.mark.parametrize("count,targeted", [(900, True), (901, False)])
def test_lookup_threshold_uses_one_snapshot(session, records, count, targeted):
    from sqlalchemy import event

    case, evidence = records
    create(session, case, evidence, {"files": [{"path": "/file-0", "name": "old"}]})
    case_id, evidence_id = case.id, evidence.id
    session.expunge_all()
    statements = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT") and "artifacts.evidence_id =" in statement:
            statements.append(statement)

    event.listen(session.bind, "before_cursor_execute", capture)
    try:
        rows = [{"path": f"/file-{i}", "name": f"new-{i}"} for i in range(count)]
        stats = asyncio.run(ExaminationService(session)._create_artifact_records(
            case_id, evidence_id, 2, {"files": rows}, commit_interval=False))
    finally:
        event.remove(session.bind, "before_cursor_execute", capture)

    assert len(statements) == 1
    assert ("artifacts.source_path IN" in statements[0]) is targeted
    assert stats == {"created": count - 1, "updated": 1}
    artifact = session.execute(select(Artifact).where(Artifact.source_path == "/file-0")).scalar_one()
    assert artifact.name == "new-0"
    assert artifact.examination_job_id == 2
