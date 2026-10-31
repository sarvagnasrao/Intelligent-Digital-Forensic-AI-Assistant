"""Entity extraction, relationships and the analysis queue.

The pipeline is the answer to "NER is inaccurate": structured values are matched
exactly, model output is verified against the source before it is stored, and a
relationship only exists when artifacts actually support it. These tests pin
those three promises down.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.analysis.extractors import extract_entities, normalize_value
from app.analysis.llm import parse_model_answer
from app.artifacts.models import EntityType

# ----------------------------------------------------------------------
# Extraction
# ----------------------------------------------------------------------


def values(text: str) -> list[tuple[str, str]]:
    return [(item.entity_type.value, item.value) for item in extract_entities(text)]


def test_every_structured_type_is_extracted():
    text = (
        "Mail rahul.sharma@gmail.com or call +91 98765 43210. "
        "See https://drop.example.net/x and host 10.0.0.14. "
        "Wallet bc1qar0srrr7xfkvy5l643lydnw9re59gtzzwf5mdq "
        "digest e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855 "
        "mac 00:1A:2B:3C:4D:5E at C:\\Users\\alice\\Desktop\\lease.pdf "
        "login: rsharma on 2024-05-17T09:30:00Z"
    )

    found = {kind for kind, _value in values(text)}

    assert {
        "email", "phone", "url", "ip_address", "crypto_address",
        "hash", "mac_address", "file_path", "username", "timestamp",
    } <= found


def test_a_url_is_not_also_recorded_as_a_path():
    found = values("download http://10.0.0.14:8080/admin/index.html now")

    kinds = [kind for kind, _value in found]
    assert "url" in kinds
    assert kinds.count("url") == 1
    # The host part of the URL must not be reported a second time as an IP.
    assert "ip_address" not in kinds


def test_one_row_per_value_even_when_repeated():
    found = extract_entities(
        "rahul@example.org wrote to rahul@example.org about rahul@example.org"
    )

    assert len(found) == 1
    assert found[0].entity_type is EntityType.EMAIL


def test_a_date_is_not_mistaken_for_a_phone_number():
    found = values("signed 17/05/2024 and archived 2024-05-17")

    assert [kind for kind, _value in found] == ["timestamp", "timestamp"]


def test_an_iso_timestamp_keeps_its_original_text():
    found = extract_entities("logged at 2024-05-17T09:30:00Z")

    assert found[0].value == "2024-05-17T09:30:00Z"


def test_a_phone_number_is_normalised_to_digits():
    found = extract_entities("call +91 98765 43210")

    assert found[0].entity_type is EntityType.PHONE
    assert found[0].normalized == "+919876543210"


def test_a_placeholder_digest_is_ignored():
    found = values("hash 00000000000000000000000000000000")

    assert "hash" not in [kind for kind, _value in found]


def test_paths_normalise_case_and_separators():
    assert (
        normalize_value(EntityType.FILE_PATH, "C:/Users/Alice/Report.PDF")
        == "c:\\users\\alice\\report.pdf"
    )


# ----------------------------------------------------------------------
# Model output verification
# ----------------------------------------------------------------------


def test_a_name_the_model_invented_is_dropped():
    source = "Rahul Sharma met the accountant at the Bengaluru office."
    answer = (
        '[{"type": "person", "value": "Vikram Rao", '
        '"quote": "Vikram Rao signed the contract"}, '
        '{"type": "person", "value": "Rahul Sharma", '
        '"quote": "Rahul Sharma met the accountant"}]'
    )

    found = parse_model_answer(answer, source)

    assert [item.value for item in found] == ["Rahul Sharma"]
    assert found[0].extractor == "llm"


def test_a_name_without_a_supported_quote_is_dropped():
    source = "Rahul Sharma met the accountant."
    answer = '[{"type": "person", "value": "Rahul Sharma", "quote": "someone else entirely"}]'

    assert parse_model_answer(answer, source) == []


def test_a_generic_organisation_is_dropped():
    source = "The company uses Gmail for everything."
    answer = (
        '[{"type": "organization", "value": "Gmail", "quote": "uses Gmail for everything"}, '
        '{"type": "organization", "value": "the company", "quote": "The company uses Gmail"}]'
    )

    assert parse_model_answer(answer, source) == []


def test_a_fenced_answer_is_still_read():
    source = "Priya Nair works at Acme Systems in Bengaluru."
    answer = (
        "```json\n"
        '[{"type": "person", "value": "Priya Nair", "quote": "Priya Nair works at Acme"},'
        ' {"type": "organization", "value": "Acme Systems", "quote": "works at Acme Systems"},'
        ' {"type": "location", "value": "Bengaluru", "quote": "in Bengaluru"}]\n'
        "```"
    )

    found = parse_model_answer(answer, source)

    assert {item.entity_type for item in found} == {
        EntityType.PERSON, EntityType.ORGANIZATION, EntityType.LOCATION,
    }


def test_model_candidates_have_quote_provenance_and_two_review_tiers():
    source = "Rahul Sharma contacted Rahul Sharma about the account rsharma."
    answer = (
        '[{"type":"person","value":"Rahul Sharma",'
        '"quote":"Rahul Sharma contacted Rahul Sharma"},'
        '{"type":"account","value":"rsharma",'
        '"quote":"the account rsharma"}]'
    )
    entities = parse_model_answer(answer, source)
    assert [e.confidence for e in entities] == [0.85, 0.65]
    assert entities[0].metadata["confidence_tier"] == "higher"
    assert entities[1].metadata["confidence_tier"] == "candidate"
    assert all(e.metadata["quote"] in source for e in entities)
    assert entities[1].entity_type is EntityType.USERNAME


def test_a_prose_answer_is_ignored():
    assert parse_model_answer("I could not find any names.", "anything") == []


# ----------------------------------------------------------------------
# Service fixtures
# ----------------------------------------------------------------------


@pytest.fixture
def session(config_home, data_dir):
    from app.config import Config, save_config, set_data_dir
    from app.db import Base, load_all_models

    save_config(set_data_dir(Config(), data_dir))
    load_all_models()
    engine = create_engine(f"sqlite+pysqlite:///{(data_dir / 'analysis.db').as_posix()}")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db_session:
        yield db_session
    engine.dispose()


@pytest.fixture
def data(config_home, data_dir, session):
    """A case, one evidence item, a finished examination and five artifacts."""
    from app.artifacts.models import Artifact, ArtifactType, IndexStatus
    from app.auth.models import Case, User
    from app.evidence.models import Evidence
    from app.examination.models import (
        ExaminationJob, ExaminationOperation, JobStatus,
    )

    user = User(username="t", email="t@example.test", password_hash="x", full_name="T")
    session.add(user)
    session.flush()
    case = Case(case_id="C-1", title="Case", created_by_id=user.id)
    session.add(case)
    session.flush()
    evidence = Evidence(
        evidence_id="E-1", case_id=case.id, name="disk.img",
        source_path="E:/img/disk.img", registered_by_id=user.id,
        size_bytes=1,
    )
    session.add(evidence)
    session.flush()
    exam = ExaminationJob(
        job_id="EXM-1", case_id=case.id, evidence_id=evidence.id,
        operation=ExaminationOperation.FULL_EXAMINATION,
        status=JobStatus.COMPLETED, created_by_id=user.id,
        parameters_json='{"profile": "balanced"}',
    )
    session.add(exam)
    session.flush()

    rows = [
        ("chat_1.txt", "/Users/rsharma/chat_1.txt",
         "From: rahul@example.org to priya@example.net, call +91 98765 43210"),
        ("chat_1_copy.txt", "/Temp/chat_1_copy.txt",
         "From: rahul@example.org to priya@example.net, call +91 98765 43210"),
        ("notes.txt", "/Users/priya/notes.txt",
         "rahul@example.org will deliver on 2024-05-17"),
        ("image.JPG", "/DCIM/image.JPG", None),
        ("log.txt", "/Windows/log.txt", "nothing interesting here"),
    ]
    for index, (name, path, content) in enumerate(rows, start=1):
        session.add(Artifact(
            artifact_id=f"ART-{index:04d}", case_id=case.id, evidence_id=evidence.id,
            examination_job_id=exam.id, artifact_type=ArtifactType.FILE,
            name=name, source_path=path, content_text=content,
            content_hash="same" if index in (1, 2) else f"other{index}",
            source_size=10, index_status=IndexStatus.NOT_INDEXED,
            created_time=datetime(2024, 5, 17, 4, 0, tzinfo=timezone.utc),
            modified_time=datetime(2024, 5, 18, 4, 30, tzinfo=timezone.utc),
        ))
    session.commit()
    return case, user, evidence, exam


@pytest.fixture
def service(session, config_home, data_dir):
    from app.analysis.service import AnalysisService

    # Model calls are outside the scope of these tests: the deterministic pass
    # is what has to be exact.
    svc = AnalysisService(session)
    svc.config.analysis.llm_enabled = False
    return svc


def run(service, job, user):
    return asyncio.run(service.run(job.id, user))


def test_partial_model_failure_persists_verified_window_leads(session, service, data, monkeypatch):
    import json

    from sqlalchemy import select

    from app.analysis.llm import AnalysisLLM, LLMResult
    from app.artifacts.models import Artifact, Entity

    case, user, evidence, exam = data
    job = service.enqueue_for_examination(case.id, evidence.id, exam.id, created_by=user)
    from app.analysis.models import AnalysisJobStatus
    job.status = AnalysisJobStatus.RUNNING
    job.progress_message = "Running"
    artifact = session.execute(select(Artifact).where(Artifact.name == "notes.txt")).scalar_one()
    artifact.content_text = "Alice met the courier. " + "x" * 600
    session.commit()
    service.config.analysis.llm_enabled = True
    calls = 0

    async def ask(_self, _prompt):
        nonlocal calls
        calls += 1
        if calls == 1:
            return LLMResult([], answer=json.dumps([
                {"type": "person", "value": "Alice", "quote": "Alice met the courier"},
                {"type": "person", "value": "Invented", "quote": "Invented met Alice"},
            ]))
        return LLMResult([], error="simulated model failure")

    monkeypatch.setattr(AnalysisLLM, "_ask", ask)
    assert asyncio.run(service._extract_with_llm(job, [artifact], {"llm_max_chars": 500})) == 1
    entity = session.execute(select(Entity).where(Entity.artifact_id == artifact.id)).scalar_one()
    assert entity.value == "Alice"
    assert artifact.content_text[entity.start_offset:entity.end_offset] == entity.value
    assert entity.context_snippet == "Alice met the courier"
    assert calls == 2


# ----------------------------------------------------------------------
# Queue
# ----------------------------------------------------------------------


def test_one_analysis_job_per_examination(service, data):
    case, user, evidence, exam = data

    first = service.enqueue_for_examination(case.id, evidence.id, exam.id, created_by=user)
    second = service.enqueue_for_examination(case.id, evidence.id, exam.id, created_by=user)

    assert first is not None
    assert second is not None
    assert first.id == second.id
    assert first.status.value == "pending"


def test_missing_analysis_is_queued_for_every_completed_examination(service, data):
    case, user, evidence, exam = data

    created = service.enqueue_missing(case.id, created_by=user)
    again = service.enqueue_missing(case.id, created_by=user)

    assert [job.examination_job_id for job in created] == [exam.id]
    assert again == []


def test_analysis_does_not_queue_when_disabled(service, data):
    case, user, evidence, exam = data
    service.config.analysis.enabled = False

    assert service.enqueue_for_examination(case.id, evidence.id, exam.id, created_by=user) is None
    assert service.enqueue_missing(case.id, created_by=user) == []


def test_manual_queue_skips_removed_evidence(service, data):
    case, user, evidence, _exam = data
    evidence.removed_at = datetime.now(timezone.utc)
    service.session.commit()
    assert service.enqueue_missing(case.id, created_by=user, manual=True) == []


def test_queue_requires_an_explicit_active_actor(service, data):
    case, user, _, _ = data
    with pytest.raises(PermissionError):
        service.enqueue_missing(case.id, manual=True)
    with pytest.raises(PermissionError):
        service.enqueue_missing(case.id)
    user.is_active = False
    with pytest.raises(PermissionError):
        service.enqueue_missing(case.id, created_by=user)


def test_runner_reloads_actor_and_checks_case(session, service, data, monkeypatch):
    from sqlalchemy.orm import sessionmaker

    from app.analysis.models import AnalysisJobStatus
    from app.analysis.runner import AnalysisRunner
    from app.auth.models import UserRole
    import app.analysis.runner as runner_module

    case, user, evidence, exam = data
    job = service.enqueue_for_examination(case.id, evidence.id, exam.id, created_by=user)
    session.commit()
    case_id, user_id, job_id = case.id, user.id, job.id
    monkeypatch.setattr(runner_module, "get_session_factory", lambda: sessionmaker(bind=session.bind))
    runner = AnalysisRunner()
    runner.set_case(case_id, user_id)

    # Revoking access after dispatch but before the worker starts must fail.
    user.role = UserRole.READ_ONLY
    session.commit()
    runner._run_job(job_id, case_id, user_id, runner._generation)
    session.refresh(job)
    assert job.status == AnalysisJobStatus.PENDING

    user.role = UserRole.INVESTIGATOR
    session.commit()
    runner._run_job(job_id, case_id + 1, user_id, runner._generation)
    session.refresh(job)
    assert job.status == AnalysisJobStatus.PENDING

    runner._run_job(job_id, case_id, user_id, runner._generation)
    session.refresh(job)
    assert job.status == AnalysisJobStatus.COMPLETED


def test_runner_tick_autoqueues_only_for_bound_active_user(session, service, data, monkeypatch):
    from sqlalchemy.orm import sessionmaker

    import app.analysis.runner as runner_module
    from app.analysis.models import AnalysisJobStatus
    from app.analysis.runner import AnalysisRunner

    case, user, _, _ = data
    case_id, user_id = case.id, user.id
    monkeypatch.setattr(runner_module, "get_session_factory", lambda: sessionmaker(bind=session.bind))
    runner = AnalysisRunner()
    runner._tick()  # No context must never scan all cases.
    assert service.next_pending() is None

    runner.set_case(case_id, user_id)
    runner._tick()
    runner._thread.join(timeout=30)
    assert not runner.busy
    session.expire_all()
    assert service.list_jobs(case_id)[0].status == AnalysisJobStatus.COMPLETED

    runner.stop()
    assert runner._case_id is None and runner._user_id is None


# ----------------------------------------------------------------------
# Running
# ----------------------------------------------------------------------


def test_a_run_stores_entities_timeline_and_relationships(service, data):
    case, user, evidence, exam = data
    job = service.enqueue_for_examination(case.id, evidence.id, exam.id, created_by=user)

    result = run(service, job, user)

    assert result["ok"] is True
    session = service.session
    session.expire_all()

    entities = service.list_entities(case.id)
    assert any(entity.entity_type is EntityType.EMAIL for entity in entities)
    # A file's modified and created times become timeline events.
    timeline = service.list_timeline(case.id)
    assert {event.event_type for event in timeline} == {
        "file_created", "file_modified",
    }
    assert service.list_relationships(case.id)

    finished = service.get_job(job.id)
    assert finished.status.value == "completed"
    assert finished.progress_percent == 100
    assert finished.entity_count > 0


def test_a_second_run_does_not_duplicate_anything(service, data):
    case, user, evidence, exam = data
    job = service.enqueue_for_examination(case.id, evidence.id, exam.id, created_by=user)
    run(service, job, user)
    session = service.session
    session.expire_all()
    before = (
        len(service.list_entities(case.id)),
        len(service.list_timeline(case.id)),
        len(service.list_relationships(case.id)),
    )

    assert service.retry(job.id, case.id, user)
    run(service, service.get_job(job.id), user)
    session.expire_all()

    after = (
        len(service.list_entities(case.id)),
        len(service.list_timeline(case.id)),
        len(service.list_relationships(case.id)),
    )
    assert after == before


def test_a_cancelled_job_is_recorded_as_cancelled(service, data):
    case, user, evidence, exam = data
    job = service.enqueue_for_examination(case.id, evidence.id, exam.id, created_by=user)

    assert service.cancel(job.id, case.id, user) is True
    service.session.expire_all()

    assert service.get_job(job.id).status.value == "cancelled"
    # Nothing is analysed when the job never ran.
    assert service.list_entities(case.id) == []


def test_cancel_and_retry_require_active_case_writer(service, data):
    from app.auth.models import UserRole

    case, user, evidence, exam = data
    job = service.enqueue_for_examination(case.id, evidence.id, exam.id, created_by=user)
    service.session.commit()
    with pytest.raises(PermissionError):
        service.cancel(job.id, case.id + 1, user)
    user.role = UserRole.READ_ONLY
    service.session.commit()
    with pytest.raises(PermissionError):
        service.cancel(job.id, case.id, user)
    with pytest.raises(PermissionError):
        service.retry(job.id, case.id, user)
    assert service.get_job(job.id).status.value == "pending"


def test_running_cancel_blocks_retry_until_acknowledged(service, data):
    from app.analysis.models import AnalysisJobStatus
    from app.analysis.service import AnalysisCancelled

    case, user, evidence, exam = data
    job = service.enqueue_for_examination(case.id, evidence.id, exam.id, created_by=user)
    job.status = AnalysisJobStatus.RUNNING
    job.progress_message = "Running"
    service.session.commit()
    assert service.cancel(job.id, case.id, user)
    assert not service.retry(job.id, case.id, user)
    with pytest.raises(AnalysisCancelled):
        service._finish(job, entity_count=0, message="done")


def test_runner_context_switch_and_stop_cancel_owned_job(session, service, data, monkeypatch):
    from sqlalchemy.orm import sessionmaker
    import app.analysis.runner as runner_module
    from app.analysis.runner import AnalysisRunner
    from app.analysis.service import _CANCELLED

    case, user, evidence, exam = data
    job = service.enqueue_for_examination(case.id, evidence.id, exam.id, created_by=user)
    session.commit()
    monkeypatch.setattr(runner_module, "get_session_factory", lambda: sessionmaker(bind=session.bind))
    runner = AnalysisRunner()
    runner.set_case(case.id, user.id)
    runner._active_job_id = job.id
    generation = runner._generation
    try:
        runner.set_case(case.id + 1, user.id)
        session.refresh(job)
        assert job.status.value == "cancelled"
        assert runner._generation != generation
        runner.stop()
        assert runner._case_id is None and runner._user_id is None
    finally:
        _CANCELLED.discard(job.id)


def test_running_jobs_are_not_automatically_recovered(service, data):
    from app.analysis.models import AnalysisJobStatus

    case, user, evidence, exam = data
    job = service.enqueue_for_examination(case.id, evidence.id, exam.id, created_by=user)
    job.status = AnalysisJobStatus.RUNNING
    service.session.commit()

    assert service.get_job(job.id).status.value == "running"


# ----------------------------------------------------------------------
# Relationships
# ----------------------------------------------------------------------


def test_a_shared_address_links_two_artifacts(service, data):
    case, user, evidence, exam = data
    job = service.enqueue_for_examination(case.id, evidence.id, exam.id, created_by=user)
    run(service, job, user)

    rows = service.list_relationships(case.id)
    emails = [
        row for row in rows
        if "rahul@example.org" in (row.left_value, row.right_value)
    ]

    assert emails
    assert max(row.shared_count for row in emails) >= 2


def test_identical_content_is_reported_as_a_duplicate(service, data):
    case, user, evidence, exam = data
    job = service.enqueue_for_examination(case.id, evidence.id, exam.id, created_by=user)
    run(service, job, user)

    duplicates = [
        row for row in service.list_relationships(case.id)
        if row.kind.value == "duplicate_content"
    ]

    assert duplicates
    assert duplicates[0].shared_count == 2


def test_a_path_never_links_artifacts(service, data):
    case, user, evidence, exam = data
    job = service.enqueue_for_examination(case.id, evidence.id, exam.id, created_by=user)
    run(service, job, user)

    rows = service.list_relationships(case.id)

    assert all(row.left_type != "file_path" for row in rows)
    assert all(row.right_type != "file_path" for row in rows)


def test_a_single_shared_artifact_does_not_create_an_entity_pair(service, data):
    case, user, evidence, exam = data
    job = service.enqueue_for_examination(case.id, evidence.id, exam.id, created_by=user)
    run(service, job, user)

    rows = service.list_relationships(case.id)

    # An entity pair ("this address with this phone") needs at least two
    # artifacts to support it. chat_1 and its copy qualify; the address they
    # share with notes.txt does not.
    entity_pairs = [row for row in rows if row.kind.value == "shared_entity"]
    assert entity_pairs
    assert all(row.shared_count >= 2 for row in entity_pairs)

    # Those files are still connected, at artifact level, by the address they
    # both contain - one shared identifier is enough for that edge.
    artifact_links = [row for row in rows if row.kind.value == "related_artifacts"]
    assert artifact_links
    assert all(row.left_type == "artifact" for row in artifact_links)
    assert min(row.shared_count for row in artifact_links) >= 1


def test_a_common_value_does_not_link_everything(session, service, data):
    """A value in most artifacts is a hub: it must not create a complete graph."""
    from app.analysis.models import EntityRelationship
    from app.analysis.relationships import (
        RelationshipBuilder, RelationshipSettings,
    )
    from app.artifacts.models import Artifact, Entity

    case, _user, evidence, _exam = data
    artifacts = service.session.query(Artifact).all()

    # "example.com" appears in every artifact: a hub.
    for artifact in artifacts:
        service.session.add(Entity(
            entity_id=f"HUB-{artifact.id}", case_id=case.id,
            artifact_id=artifact.id, entity_type=EntityType.URL,
            value="https://example.com", normalized_value="https://example.com",
            extractor="test", confidence=1.0,
        ))
    service.session.commit()

    RelationshipBuilder(
        service.session, case.id,
        RelationshipSettings(hub_fraction=0.4, hub_min_artifacts=2),
    ).rebuild()
    service.session.commit()

    rows = service.session.query(EntityRelationship).filter_by(case_id=case.id).all()
    assert all(
        "example.com" not in (row.left_value, row.right_value) for row in rows
    )


def test_a_reviewed_relationship_survives_a_rebuild(service, data):
    case, user, evidence, exam = data
    job = service.enqueue_for_examination(case.id, evidence.id, exam.id, created_by=user)
    run(service, job, user)

    rows = service.list_relationships(case.id)
    assert rows
    target = rows[0]
    service.review_relationship(target.id, "confirmed", user.id)
    service.session.commit()
    relationship_id = target.id

    # Re-examining the evidence rebuilds the graph from scratch.
    run(service, service.get_job(job.id), user)
    service.session.expire_all()

    kept = service.session.get(type(target), relationship_id)
    assert kept is not None
    assert kept.status.value == "confirmed"
    assert kept.reviewed_by_id == user.id


def test_reviewed_lead_without_source_support_is_hidden_until_rebuilt(service, data):
    from app.analysis.models import RelationshipKind
    from app.analysis.relationships import RelationshipBuilder
    from app.artifacts.models import Entity

    case, user, evidence, exam = data
    job = service.enqueue_for_examination(case.id, evidence.id, exam.id, created_by=user)
    run(service, job, user)
    target = next(row for row in service.list_relationships(case.id)
                  if row.kind == RelationshipKind.SHARED_ENTITY)
    target_id = target.id
    service.review_relationship(target_id, "confirmed", user.id)
    original_provenance = target.artifact_ids_json

    # A later extraction no longer supports the pair. Its review is historical,
    # not an active source-backed lead; the source record remains auditable.
    entities = service.session.query(Entity).filter_by(case_id=case.id).all()
    saved_entities = [
        {column.name: getattr(entity, column.name)
         for column in Entity.__table__.columns if column.name != "id"}
        for entity in entities
    ]
    for entity in entities:
        service.session.delete(entity)
    service.session.flush()
    RelationshipBuilder(service.session, case.id).rebuild()
    service.session.commit()
    retained = service.session.get(type(target), target_id)
    assert retained.status.value == "confirmed"
    assert retained.reviewed_by_id == user.id
    assert retained.artifact_ids_json == original_provenance
    assert target_id not in {row.id for row in service.list_relationships(case.id)}
    assert service.relationship_counts(case.id)["confirmed"] == 0

    # When the original sources support it again, the reviewed edge is active.
    service.session.add_all(Entity(**values) for values in saved_entities)
    service.session.flush()
    RelationshipBuilder(service.session, case.id).rebuild()
    service.session.commit()
    assert target_id in {row.id for row in service.list_relationships(case.id)}


def test_relationship_counts_summarise_the_case(service, data):
    case, user, evidence, exam = data
    run(service, service.enqueue_for_examination(case.id, evidence.id, exam.id, created_by=user), user)

    counts = service.relationship_counts(case.id)

    assert counts["pending"] == len(service.list_relationships(case.id))
    assert counts["confirmed"] == 0
