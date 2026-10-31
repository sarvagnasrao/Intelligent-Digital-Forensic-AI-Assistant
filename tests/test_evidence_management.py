"""Evidence transparency and control: files, removal, deletion, hashes, export.

These cover the operations an investigator needs when a registration is wrong
or a file moves: seeing what is actually on disk, taking an item out of the
case, deleting it for good, recording a hash from the evidence bag, exporting a
verified copy, and producing a case manifest.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


@pytest.fixture
def session(config_home, data_dir):
    from app.config import Config, save_config, set_data_dir
    from app.db import Base, load_all_models

    save_config(set_data_dir(Config(), data_dir))
    load_all_models()
    engine = create_engine(f"sqlite+pysqlite:///{(data_dir / 'evidence.db').as_posix()}")
    Base.metadata.create_all(engine)
    with Session(engine) as db_session:
        yield db_session
    engine.dispose()


@pytest.fixture
def service(session):
    from app.evidence.service import EvidenceService

    return EvidenceService(session)


@pytest.fixture
def registered(service, session, tmp_path):
    """A case, a user and one registered evidence item with a stored copy."""
    from app.auth.models import Case, User

    user = User(username="t", email="t@example.test", password_hash="x", full_name="T")
    session.add(user)
    session.commit()
    case = Case(case_id="C-1", title="Case", created_by_id=user.id)
    session.add(case)
    session.commit()

    source = tmp_path / "disk.dd"
    source.write_bytes(b"\xab" * 4096)
    evidence = service.register_evidence(
        case.id, "disk.dd", str(source), registered_by=user, copy_to_store=True
    )
    session.commit()
    return case, user, evidence, source


def test_registering_copies_the_file_into_the_case_store(registered):
    _case, _user, evidence, source = registered
    from app.evidence.service import EvidenceService

    assert evidence.stored_path is not None
    assert Path(evidence.stored_path).is_file()
    assert Path(evidence.stored_path) != source
    assert evidence.status.value == "registered"
    assert EvidenceService.STORED_PRESENT == "present"


def test_ewf_segments_are_one_hashed_item(service, session, registered, tmp_path):
    import hashlib
    from app.evidence.models import HashAlgorithm

    case, user, _, _ = registered
    first, second = tmp_path / "image.E01", tmp_path / "image.E02"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    item = service.register_evidence(case.id, "image", str(second), registered_by=user)
    assert item.source_path == str(first)
    assert Path(item.stored_path).with_suffix(".E02").read_bytes() == b"second"
    assert service._calculate_hashes(item.stored_path, [HashAlgorithm.SHA256])[HashAlgorithm.SHA256] == hashlib.sha256(b"firstsecond").hexdigest()


def test_hash_failure_removes_only_new_copy_and_never_overwrites(service, registered, tmp_path, monkeypatch):
    case, user, _, source = registered
    new_source = tmp_path / "new.txt"
    new_source.write_bytes(b"new")
    monkeypatch.setattr(service, "_calculate_hashes", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("hash failed")))
    with pytest.raises(OSError, match="hash failed"):
        service.register_evidence(case.id, "new", str(new_source), registered_by=user)
    destination = Path(service.config.worker.evidence_root_windows) / str(case.id) / "E002.txt"
    assert not destination.exists()
    destination.write_bytes(b"existing")
    with pytest.raises(FileExistsError):
        service.register_evidence(case.id, "new", str(new_source), registered_by=user)
    assert destination.read_bytes() == b"existing"
    assert source.exists() and new_source.read_bytes() == b"new"


def test_reference_algorithm_not_in_configuration_is_checked(service, registered, tmp_path):
    from app.evidence.models import HashAlgorithm

    case, user, _, _ = registered
    source = tmp_path / "reference.txt"
    source.write_bytes(b"synthetic")
    service.config.forensics.hash_algorithms = ["sha256"]
    item = service.register_evidence(case.id, "reference", str(source), registered_by=user,
                                     reference_hashes={HashAlgorithm.MD5: "0" * 32})
    hashes = [h for h in item.hashes if h.algorithm == HashAlgorithm.MD5]
    assert len(hashes) == 2
    assert next(h for h in hashes if h.is_reference).match_result is False
    assert item.status.value == "integrity_failed"


def test_invalid_reference_is_rejected_before_copy(service, registered, tmp_path):
    from app.evidence.models import HashAlgorithm

    case, user, _, _ = registered
    source = tmp_path / "invalid.txt"
    source.write_bytes(b"synthetic")
    with pytest.raises(ValueError, match="Invalid MD5"):
        service.register_evidence(case.id, "invalid", str(source), registered_by=user,
                                  reference_hashes={HashAlgorithm.MD5: "not a hash"})
    assert not (Path(service.config.worker.evidence_root_windows) / str(case.id) / "E002.txt").exists()


def test_record_creation_failure_cleans_only_new_copy(service, registered, tmp_path, monkeypatch):
    import app.evidence.service as module

    case, user, existing, _ = registered
    source = tmp_path / "new.txt"
    source.write_bytes(b"synthetic")
    def fail(**kwargs):
        raise RuntimeError("hash record failed")
    monkeypatch.setattr(module, "EvidenceHash", fail)
    with pytest.raises(RuntimeError, match="hash record failed"):
        service.register_evidence(case.id, "new", str(source), registered_by=user)
    assert source.read_bytes() == b"synthetic"
    assert Path(existing.stored_path).exists()
    assert not (Path(service.config.worker.evidence_root_windows) / str(case.id) / "E002.txt").exists()


def test_copy_failure_cleans_partial_segments(service, registered, tmp_path):
    case, user, _, _ = registered
    first, second = tmp_path / "split.E01", tmp_path / "split.E02"
    first.write_bytes(b"one")
    second.write_bytes(b"two")

    def fail_on_second(message, current, total):
        if "segment 2/2" in message:
            raise OSError("copy interrupted")

    with pytest.raises(OSError, match="copy interrupted"):
        service.register_evidence(case.id, "split", str(first), registered_by=user, progress_callback=fail_on_second)
    dest = Path(service.config.worker.evidence_root_windows) / str(case.id)
    assert not (dest / "E002.E01").exists()
    assert not (dest / "E002.E02").exists()
    assert first.read_bytes() == b"one" and second.read_bytes() == b"two"


def test_file_state_reports_a_missing_stored_copy(service, session, registered):
    case, _user, evidence, _source = registered
    Path(evidence.stored_path).unlink()
    session.commit()

    assert service.file_state(evidence) == service.STORED_MISSING
    assert service.check_files(case.id)[evidence.id] == service.STORED_MISSING


def test_removing_hides_without_deleting(service, session, registered):
    case, user, evidence, _source = registered
    stored = Path(evidence.stored_path)

    assert service.remove_evidence(evidence.id, user, "duplicate registration") is True
    session.commit()

    assert evidence.is_removed
    assert evidence.removal_reason == "duplicate registration"
    assert stored.is_file(), "removal must never touch the files"
    assert service.get_evidence_by_case(case.id) == []
    assert len(service.get_evidence_by_case(case.id, include_removed=True)) == 1
    assert any(event.event_type == "removed" for event in evidence.custody_events)


def test_returning_a_removed_item_restores_it(service, session, registered):
    case, user, evidence, _source = registered

    service.remove_evidence(evidence.id, user, "wrong file")
    session.commit()
    assert service.return_evidence(evidence.id, user) is True
    session.commit()

    assert not evidence.is_removed
    assert evidence.removal_reason is None
    assert len(service.get_evidence_by_case(case.id)) == 1


def test_deleting_removes_the_record_and_the_case_copy(service, session, registered):
    _case, user, evidence, source = registered
    stored = Path(evidence.stored_path)
    evidence_pk = evidence.id

    result = service.delete_evidence(evidence_pk, user, "bad registration")
    session.commit()

    assert result["files"] == 1
    assert result["bytes"] > 0
    assert not stored.exists(), "the case-store copy must be deleted"
    assert source.is_file(), "the original acquisition is never touched"
    assert service.get_evidence_by_id(evidence_pk) is None


def test_deleting_a_reference_only_item_keeps_the_source(service, session, registered, tmp_path):
    case, user, _evidence, _source = registered
    reference = tmp_path / "reference.dd"
    reference.write_bytes(b"\x01" * 64)
    evidence = service.register_evidence(
        case.id, "reference.dd", str(reference), registered_by=user, copy_to_store=False
    )
    session.commit()

    assert service.file_state(evidence) == service.STORED_REFERENCE
    result = service.delete_evidence(evidence.id, user)
    session.commit()

    assert result["files"] == 0
    assert reference.is_file()


def test_deleting_missing_evidence_with_many_artifacts(service, session, registered):
    import sqlite3
    from app.artifacts.models import Artifact, ArtifactType

    case, user, evidence, source = registered
    evidence_id = evidence.id
    Path(evidence.stored_path).unlink()
    session.add_all([
        Artifact(artifact_id=f"ART-{i}", case_id=case.id, evidence_id=evidence_id,
                 artifact_type=ArtifactType.FILE, name=f"item-{i}")
        for i in range(850)
    ])
    session.commit()
    raw = session.connection().connection.driver_connection
    previous_limit = raw.setlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, 900)
    try:
        result = service.delete_evidence(evidence_id, user)
        session.commit()
    finally:
        raw.setlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, previous_limit)

    assert result["files"] == 0
    assert result["artifacts"] == 850
    assert source.exists()
    assert service.get_evidence_by_id(evidence_id) is None
    assert session.query(Artifact).filter_by(evidence_id=evidence_id).count() == 0


def test_delete_worker_reserves_write_before_reading_evidence(session, registered, monkeypatch, qt_app):
    from sqlalchemy.exc import OperationalError
    from sqlalchemy.orm import Session
    from app.db import session as session_module
    from app.evidence.service import EvidenceService
    from app.ui.deletion_worker import DeletionWorker

    _case, user, evidence, _source = registered
    user_id, evidence_id = user.id, evidence.id
    engine = session.get_bind()
    session.commit()
    monkeypatch.setattr(session_module, "get_session_factory", lambda: lambda: Session(engine))

    def simulate_cleanup(self, record_id, performed_by, reason):
        with engine.connect() as competing:
            competing.exec_driver_sql("PRAGMA busy_timeout=1")
            with pytest.raises(OperationalError, match="locked"):
                competing.exec_driver_sql("BEGIN IMMEDIATE")
        return {"files": 0, "bytes": 0, "jobs": 0, "artifacts": 0}

    monkeypatch.setattr(EvidenceService, "delete_evidence", simulate_cleanup)
    worker = DeletionWorker("evidence", evidence_id, user_id)
    results, errors = [], []
    worker.succeeded.connect(results.append)
    worker.failed.connect(errors.append)
    worker.run()
    assert results and not errors


def test_deleting_cascades_completed_examinations_and_artifacts(
    service, session, registered
):
    from app.artifacts.models import Artifact, ArtifactType
    from app.examination.models import ExaminationJob, ExaminationOperation, JobStatus
    from app.examination.models import ExaminationResult

    case, user, evidence, _source = registered
    session.add(ExaminationJob(
        job_id="J-1",
        case_id=case.id,
        evidence_id=evidence.id,
        operation=ExaminationOperation.FULL_EXAMINATION,
        status=JobStatus.COMPLETED,
        created_by_id=user.id,
    ))
    session.flush()
    job = session.query(ExaminationJob).filter_by(job_id="J-1").one()
    session.add(Artifact(
        artifact_id="ART-TEST-1",
        case_id=case.id,
        evidence_id=evidence.id,
        examination_job_id=job.id,
        artifact_type=ArtifactType.FILE,
        name="derived.txt",
        content_text="derived text",
    ))
    session.add(ExaminationResult(
        job_id=job.id,
        result_type="artifacts",
        content_json="[]",
    ))
    session.commit()

    result = service.delete_evidence(evidence.id, user)
    session.commit()

    assert result["jobs"] == 1
    assert result["artifacts"] == 1
    assert session.query(ExaminationJob).filter_by(job_id="J-1").count() == 0
    assert session.query(Artifact).filter_by(artifact_id="ART-TEST-1").count() == 0
    assert service.get_evidence_by_id(evidence.id) is None


def test_deleting_an_examination_job_deletes_its_artifacts(
    session, registered
):
    from app.artifacts.models import Artifact, ArtifactType
    from app.examination.models import ExaminationJob, ExaminationOperation, JobStatus
    from app.examination.service import ExaminationService

    case, user, evidence, _source = registered
    job = ExaminationJob(
        job_id="J-DELETE-ARTIFACTS",
        case_id=case.id,
        evidence_id=evidence.id,
        operation=ExaminationOperation.FULL_EXAMINATION,
        status=JobStatus.COMPLETED,
        created_by_id=user.id,
    )
    session.add(job)
    session.flush()
    artifact = Artifact(
        artifact_id="ART-JOB-DELETE",
        case_id=case.id,
        evidence_id=evidence.id,
        examination_job_id=job.id,
        artifact_type=ArtifactType.FILE,
        name="derived.txt",
        content_text="extracted",
    )
    session.add(artifact)
    session.commit()
    artifact_pk = artifact.id

    assert ExaminationService(session).delete_job(job.id, user)
    session.commit()

    assert session.get(Artifact, artifact_pk) is None
    assert session.query(ExaminationJob).filter_by(job_id="J-DELETE-ARTIFACTS").count() == 0


def test_a_tampered_stored_path_cannot_delete_outside_the_store(
    service, session, registered, tmp_path
):
    _case, user, evidence, _source = registered
    outsider = tmp_path / "important.txt"
    outsider.write_text("keep me", encoding="utf-8")
    evidence.stored_path = str(outsider)
    session.commit()

    assert service.case_store_files(evidence) == []

    service.delete_evidence(evidence.id, user)
    session.commit()

    assert outsider.is_file(), "only files inside the case store may be deleted"


def test_reference_hash_is_recorded_and_verified(service, session, registered):
    from app.evidence.models import EvidenceStatus, HashAlgorithm

    _case, user, evidence, _source = registered
    correct = next(
        item.hash_value for item in evidence.hashes
        if item.algorithm == HashAlgorithm.SHA256
    )

    results = service.set_reference_hash(
        evidence.id, HashAlgorithm.SHA256, correct, user, note="evidence bag"
    )
    session.commit()

    assert results[HashAlgorithm.SHA256] is True
    assert evidence.status == EvidenceStatus.INTEGRITY_VERIFIED
    assert any(
        event.event_type == "hash_reference_set" for event in evidence.custody_events
    )


def test_a_wrong_reference_hash_fails_verification(service, session, registered):
    from app.evidence.models import EvidenceStatus, HashAlgorithm

    _case, user, evidence, _source = registered

    results = service.set_reference_hash(
        evidence.id, HashAlgorithm.SHA256, "0" * 64, user
    )
    session.commit()

    assert results[HashAlgorithm.SHA256] is False
    assert evidence.status == EvidenceStatus.INTEGRITY_FAILED


def test_a_malformed_reference_hash_is_rejected(service, registered):
    from app.evidence.models import HashAlgorithm

    _case, user, evidence, _source = registered

    with pytest.raises(ValueError, match="64 hexadecimal"):
        service.set_reference_hash(evidence.id, HashAlgorithm.SHA256, "abc", user)


def test_export_copies_and_confirms_the_hash(service, session, registered, tmp_path):
    _case, user, evidence, _source = registered
    destination = tmp_path / "handover"

    result = service.export_copy(evidence.id, destination, user)
    session.commit()

    assert result["verified"] is True
    exported = Path(result["files"][0])
    assert exported.is_file()
    assert exported.read_bytes() == Path(evidence.stored_path).read_bytes()
    assert any(event.event_type == "exported" for event in evidence.custody_events)


def test_editing_details_is_recorded(service, session, registered):
    _case, user, evidence, _source = registered

    assert service.update_details(
        evidence.id, "Renamed disk", "Found in office", user
    ) is True
    session.commit()

    assert evidence.name == "Renamed disk"
    assert evidence.description == "Found in office"
    with pytest.raises(ValueError):
        service.update_details(evidence.id, "   ", "", user)
    assert any(
        event.event_type == "details_edited" for event in evidence.custody_events
    )


def test_case_storage_summary_counts_items_and_removed(service, session, registered):
    case, user, evidence, _source = registered
    service.remove_evidence(evidence.id, user, "duplicate")
    session.commit()

    summary = service.case_storage(case.id)

    assert summary["items"] == 0
    assert summary["removed"] == 1


def test_manifest_covers_every_item_including_removed(service, session, registered):
    case, user, evidence, _source = registered
    service.remove_evidence(evidence.id, user, "duplicate")
    session.commit()

    rows = service.case_manifest(case.id)

    assert len(rows) == 1
    row = rows[0]
    assert row["evidence_id"] == evidence.evidence_id
    assert row["removed"] is True
    assert row["removal_reason"] == "duplicate"
    assert row["hashes"], "the manifest must carry the reference hashes"
    assert json.dumps(rows)  # serialisable for a JSON export


def test_a_removed_item_is_hidden_from_examination(service, session, registered):
    case, user, evidence, _source = registered
    service.remove_evidence(evidence.id, user, "wrong file")
    session.commit()

    assert service.get_evidence_by_case(case.id) == []


def test_case_overview_does_not_count_removed_evidence(service, session, registered):
    from app.cases.service import CaseService

    case, user, evidence, _source = registered
    assert CaseService(session).get_case_overview(case.id)["stats"]["evidence"] == 1

    service.remove_evidence(evidence.id, user, "duplicate registration")
    session.commit()

    assert CaseService(session).get_case_overview(case.id)["stats"]["evidence"] == 0


def test_case_overview_uses_active_evidence_scope_for_derived_counts(
    service, session, registered
):
    from app.artifacts.models import Artifact, ArtifactType, IndexStatus
    from app.cases.service import CaseService
    from app.examination.models import ExaminationJob, ExaminationOperation, JobStatus

    case, user, evidence, _source = registered
    job = ExaminationJob(
        job_id="OVERVIEW-EXAM",
        case_id=case.id,
        evidence_id=evidence.id,
        operation=ExaminationOperation.FULL_EXAMINATION,
        status=JobStatus.COMPLETED,
        created_by_id=user.id,
    )
    session.add(job)
    session.flush()
    session.add(Artifact(
        artifact_id="OVERVIEW-ART",
        case_id=case.id,
        evidence_id=evidence.id,
        examination_job_id=job.id,
        artifact_type=ArtifactType.FILE,
        name="notes.txt",
        content_text="case notes",
        index_status=IndexStatus.INDEXED,
    ))
    session.commit()

    overview = CaseService(session).get_case_overview(case.id)
    assert overview["stats"]["evidence"] == 1
    assert overview["stats"]["examinations"] == 1
    assert overview["stats"]["artifacts"] == 1
    assert overview["stats"]["indexed"] == 1

    service.remove_evidence(evidence.id, user, "removed from active case")
    session.commit()
    overview = CaseService(session).get_case_overview(case.id)
    assert overview["stats"]["evidence"] == 0
    assert overview["stats"]["examinations"] == 0
    assert overview["stats"]["artifacts"] == 0
    assert overview["stats"]["removed_artifacts"] == 1
    assert overview["next_action"]["key"] == "evidence"


def test_a_bag_hash_becomes_the_reference_and_is_checked_at_intake(
    service, session, registered, tmp_path
):
    from app.evidence.models import EvidenceStatus, HashAlgorithm

    case, user, _evidence, _source = registered
    source = tmp_path / "bag-image.dd"
    source.write_bytes(b"\x11" * 512)

    evidence = service.register_evidence(
        case.id,
        "bag-image.dd",
        str(source),
        registered_by=user,
        copy_to_store=True,
        reference_hashes={HashAlgorithm.SHA256: "0" * 64},
    )
    session.commit()

    reference = next(
        item for item in evidence.hashes
        if item.is_reference and item.algorithm == HashAlgorithm.SHA256
    )
    calculated = [
        item for item in evidence.hashes
        if not item.is_reference and item.algorithm == HashAlgorithm.SHA256
    ]

    assert reference.hash_value == "0" * 64, "the bag hash must stay the reference"
    assert reference.match_result is False
    assert reference.verified_at is not None
    assert len(calculated) == 1, "the value IDFA computed is kept as a normal record"
    assert evidence.status == EvidenceStatus.INTEGRITY_FAILED

    # A later verification must still compare against the bag, otherwise the
    # mismatch would silently disappear after one run.
    results = service.verify_integrity(evidence.id, user)
    session.commit()
    assert results[HashAlgorithm.SHA256] is False
    assert evidence.status == EvidenceStatus.INTEGRITY_FAILED


def test_a_matching_bag_hash_registers_as_verified(service, session, registered, tmp_path):
    from app.evidence.models import EvidenceStatus, HashAlgorithm

    case, user, _evidence, _source = registered
    source = tmp_path / "bag-image-good.dd"
    source.write_bytes(b"\x22" * 512)
    import hashlib

    digest = hashlib.sha256(source.read_bytes()).hexdigest()

    evidence = service.register_evidence(
        case.id,
        "bag-image-good.dd",
        str(source),
        registered_by=user,
        copy_to_store=True,
        reference_hashes={HashAlgorithm.SHA256: digest.upper()},
    )
    session.commit()

    assert evidence.status == EvidenceStatus.INTEGRITY_VERIFIED
    assert service.verify_integrity(evidence.id, user)[HashAlgorithm.SHA256] is True
    session.commit()
