"""Entities & Timeline page: entities, relationships, timeline and the queue.

The page is the only place an investigator sees the analysis results, so these
tests cover what would otherwise be invisible: that an empty case explains
itself, that a relationship shows its supporting artifacts, and that reviewing
one actually persists.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


@pytest.fixture
def session(config_home, data_dir):
    from app.config import Config, save_config, set_data_dir
    from app.db import Base, load_all_models

    save_config(set_data_dir(Config(), data_dir))
    load_all_models()
    engine = create_engine(f"sqlite+pysqlite:///{(data_dir / 'entities_ui.db').as_posix()}")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db_session:
        yield db_session
    engine.dispose()


@pytest.fixture
def seeded(session):
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
        source_path="E:/img/disk.img", registered_by_id=user.id, size_bytes=1,
    )
    session.add(evidence)
    session.flush()
    exam = ExaminationJob(
        job_id="EXM-1", case_id=case.id, evidence_id=evidence.id,
        operation=ExaminationOperation.FULL_EXAMINATION,
        status=JobStatus.COMPLETED, created_by_id=user.id,
    )
    session.add(exam)
    session.flush()
    for index, (name, path, content) in enumerate(
        [
            ("chat_1.txt", "/Users/a/chat_1.txt", "mail rahul@example.org"),
            ("chat_2.txt", "/Users/a/chat_2.txt", "mail rahul@example.org"),
        ],
        start=1,
    ):
        session.add(Artifact(
            artifact_id=f"ART-0001-000{index}", case_id=case.id,
            evidence_id=evidence.id, examination_job_id=exam.id,
            artifact_type=ArtifactType.FILE, name=name, source_path=path,
            content_text=content, source_size=10,
            index_status=IndexStatus.NOT_INDEXED,
            created_time=datetime(2024, 5, 17, 4, 0, tzinfo=timezone.utc),
        ))
    session.commit()
    return case, user, evidence, exam


@pytest.fixture
def service(session, config_home, data_dir):
    from app.analysis.service import AnalysisService

    svc = AnalysisService(session)
    svc.config.analysis.llm_enabled = False
    return svc


@pytest.fixture
def page(qt_app, service, seeded, monkeypatch):
    from PySide6.QtWidgets import QMessageBox, QWidget

    from app.ui.base import CaseContext
    from app.ui.pages.entities_timeline_page import EntitiesTimelinePage

    case, user, _evidence, _exam = seeded
    shell = QWidget()
    shell.get_current_user = lambda: user
    widget = EntitiesTimelinePage(shell)

    def unexpected_error(_parent, title, message):
        pytest.fail(f"Unexpected dialog: {title}: {message}")

    monkeypatch.setattr(QMessageBox, "critical", unexpected_error)
    widget.set_analysis_service(service)
    widget.set_case_context(
        CaseContext(case.id, case.case_id, case.title, "open", "medium", "T")
    )
    yield widget
    widget.deleteLater()
    shell.deleteLater()


def analyse(service, seeded) -> None:
    case, user, evidence, exam = seeded
    job = service.enqueue_for_examination(case.id, evidence.id, exam.id, created_by=user)
    asyncio.run(service.run(job.id, user))


def row_texts(model) -> list[tuple[str, ...]]:
    return [
        tuple(model.item(row, column).text() for column in range(model.columnCount()))
        for row in range(model.rowCount())
    ]


def test_an_empty_case_explains_what_will_happen(page):
    assert "No entities yet" in page.entity_summary.text()
    assert "No relationships yet" in page.rel_detail.text()
    assert page.rel_detail_panel.isHidden()


def test_entities_appear_after_analysis(page, service, seeded):
    analyse(service, seeded)

    page.refresh()

    rows = row_texts(page.entity_model)
    assert rows
    assert any("rahul@example.org" in row[1] for row in rows)
    assert "shown of" in page.entity_summary.text()


def test_llm_candidate_tier_and_source_quote_are_visible(page, session, seeded):
    from app.artifacts.models import Artifact, Entity, EntityType

    case, _user, _evidence, _exam = seeded
    artifact = session.query(Artifact).first()
    session.add(Entity(
        entity_id="ENT-UI-HIGH",
        case_id=case.id,
        artifact_id=artifact.id,
        entity_type=EntityType.PERSON,
        value="Rita Example",
        normalized_value="rita example",
        context_snippet="Message sent by Rita Example.",
        confidence=0.85,
        extractor="llm",
    ))
    session.commit()

    page.refresh()

    rows = row_texts(page.entity_model)
    row_index = next(i for i, row in enumerate(rows) if row[1] == "Rita Example")
    assert rows[row_index][3] == "Higher confidence"
    assert "Message sent by Rita Example." in page.entity_model.item(row_index, 1).toolTip()


def test_the_entity_type_filter_narrows_the_table(page, service, seeded):
    analyse(service, seeded)
    page.refresh()
    total = page.entity_model.rowCount()

    index = page.entity_type_filter.findData("email")
    page.entity_type_filter.setCurrentIndex(index)

    assert 0 < page.entity_model.rowCount() < total
    assert all(row[0] == "email" for row in row_texts(page.entity_model))


def test_a_relationship_lists_its_supporting_artifacts(page, service, seeded):
    analyse(service, seeded)
    page.refresh()

    assert page.rel_model.rowCount() >= 1
    page.rel_table.selectRow(0)
    page._on_relationship_selected()

    detail = page.rel_evidence.toPlainText()
    # Two files share one address, so this is an artifact↔artifact link and the
    # pane names both files plus the identifier that ties them together.
    assert "ART-0001-0001" in detail
    assert "ART-0001-0002" in detail
    assert "rahul@example.org" in detail
    assert detail.count("rahul@example.org") >= 3  # identifier and both source excerpts
    assert "/Users/a/chat_1.txt" in detail
    assert "/Users/a/chat_2.txt" in detail
    assert "E-1 — disk.img" in detail
    assert "Evidence ids:" not in detail
    assert "does not establish identity or ownership" in page.rel_detail.text()
    assert "confirmation records your review, not identity proof" in page.rel_hint.text()


def test_provenance_labels_identify_removed_and_unavailable_sources(page, session, seeded):
    from app.artifacts.models import Artifact

    _case, _user, evidence, _exam = seeded
    artifact = session.query(Artifact).first()
    evidence.removed_at = datetime.now(timezone.utc)
    session.flush()

    assert page._evidence_labels([evidence.id, 987654, "invalid"]) == [
        "E-1 — disk.img (removed from case)",
        "Evidence unavailable in this case",
        "Evidence unavailable in this case",
    ]
    labels = page._artifact_labels([artifact.id, 987654])
    assert artifact.artifact_id in labels[0]
    assert labels[1] == "Artifact unavailable in this case"


def test_confirming_a_relationship_persists(page, service, seeded):
    analyse(service, seeded)
    page.refresh()
    page.rel_table.selectRow(0)

    page._review_relationship(__import__(
        "app.analysis.models", fromlist=["RelationshipStatus"]
    ).RelationshipStatus.CONFIRMED)

    service.session.expire_all()
    confirmed = service.list_relationships(seeded[0].id, status=None)
    assert any(row.status.value == "confirmed" for row in confirmed)


def test_rejecting_a_relationship_persists(page, service, seeded):
    from app.analysis.models import RelationshipStatus

    analyse(service, seeded)
    page.refresh()
    page.rel_table.selectRow(0)
    relationship_id = page._selected_relationship().id

    page.reject_btn.click()

    service.session.expire_all()
    rejected = service.list_relationships(seeded[0].id, status=RelationshipStatus.REJECTED)
    assert any(row.id == relationship_id for row in rejected)


def test_the_timeline_shows_local_time(page, service, seeded):
    analyse(service, seeded)
    page.refresh()

    rows = row_texts(page.timeline_model)
    assert rows
    # 04:00 UTC is 09:30 IST; the page must not show the raw UTC value.
    assert rows[0][0].startswith("2024-05-17 09:30")


def test_the_queue_lists_the_analysis_job_after_a_run(page, service, seeded):
    analyse(service, seeded)

    page.refresh()

    rows = row_texts(page.queue_model)
    assert rows
    assert rows[0][2] == "completed"
    assert "queued" in page.queue_summary.text()


def test_run_analysis_now_queues_a_missing_job(page, service, seeded):
    assert service.list_jobs(seeded[0].id) == []

    page._on_run_now()

    assert len(service.list_jobs(seeded[0].id)) == 1
    assert "Queued 1" in page.status_detail.text()


def test_manual_analysis_works_when_automatic_queue_is_disabled(page, service, seeded):
    service.config.analysis.auto_queue = False
    page._on_run_now()
    assert len(service.list_jobs(seeded[0].id)) == 1
    assert "Queued 1" in page.status_detail.text()


def test_run_analysis_denies_read_only_user(page, service, seeded, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from app.auth.models import UserRole

    user = seeded[1]
    user.role = UserRole.READ_ONLY
    service.session.commit()
    errors = []
    monkeypatch.setattr(
        QMessageBox, "critical", lambda _parent, title, message: errors.append((title, message))
    )

    page._on_run_now()

    assert service.list_jobs(seeded[0].id) == []
    assert errors
    assert errors[0][0] == "Could not queue analysis"


def test_removed_evidence_is_not_queued_or_shown_in_analysis(page, service, seeded):
    case, user, evidence, _exam = seeded
    analyse(service, seeded)
    evidence.removed_at = datetime.now(timezone.utc)
    service.session.commit()
    page.refresh()
    assert page.entity_model.rowCount() == 0
    assert page.timeline_model.rowCount() == 0
    assert page.rel_model.rowCount() == 0
    assert sum(service.relationship_counts(case.id).values()) == 0
    assert service.enqueue_missing(case.id, created_by=user, manual=True) == []
