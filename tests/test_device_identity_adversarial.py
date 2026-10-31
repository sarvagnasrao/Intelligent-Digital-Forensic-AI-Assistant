"""Offline, source-backed identity review across explicitly recorded devices."""

import asyncio
import socket

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.artifacts.models import Artifact
from app.auth.models import Case, User, UserRole
from app.db import Base, load_all_models
from app.devices.service import DeviceService
from app.evidence.models import Evidence
from app.evidence.service import EvidenceService
from app.examination.service import ExaminationService
from app.findings.identity import IdentitySource, create_identity_hypothesis
from app.findings.models import Finding, FindingStatus
from app.findings.service import FindingService


def test_device_sources_are_case_scoped_and_review_tracks_withdrawal(tmp_path, monkeypatch):
    loop = asyncio.new_event_loop()  # Windows creates an internal socket pair here.
    def deny(*args, **kwargs):
        raise AssertionError("network access prohibited")

    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket.socket, "connect_ex", deny)
    load_all_models()
    engine = create_engine(f"sqlite+pysqlite:///{(tmp_path / 'devices.db').as_posix()}")
    Base.metadata.create_all(engine)
    try:
        with Session(engine, expire_on_commit=False) as session:
            user = User(username="investigator", email="i@example.test", password_hash="x",
                        full_name="Investigator", role=UserRole.INVESTIGATOR, is_active=True)
            session.add(user)
            session.flush()
            cases = [Case(case_id=f"C{i}", title=f"Case {i}", created_by_id=user.id)
                     for i in range(2)]
            session.add_all(cases)
            session.flush()
            evidence = [Evidence(case_id=cases[0 if i < 2 else 1].id,
                                 evidence_id=f"E{i}", name=f"Image {i}",
                                 source_path=f"image{i}", registered_by_id=user.id)
                        for i in range(3)]
            session.add_all(evidence)
            session.flush()
            devices = DeviceService(session)
            laptop = devices.create(cases[0].id, user, "Laptop")
            phone = devices.create(cases[0].id, user, "Phone")
            devices.link_evidence(cases[0].id, laptop.id, evidence[0].id, user)
            devices.link_evidence(cases[0].id, phone.id, evidence[1].id, user)
            with pytest.raises(ValueError, match="active case"):
                devices.link_evidence(cases[0].id, phone.id, evidence[2].id, user)

            texts = ["Alice mentions shared@relay.test", "Bob denies Alice controls shared@relay.test",
                     "Alice controls shared@relay.test"]
            for item, text in zip(evidence, texts, strict=True):
                loop.run_until_complete(ExaminationService(session)._create_artifact_records(
                    item.case_id, item.id, None,
                    {"artifacts": [{"name": "same.txt", "path": "/same.txt", "content_text": text}]},
                    commit_interval=False,
                ))
            artifacts = {a.evidence_id: a for a in session.scalars(select(Artifact)).all()}
            assert len(artifacts) == 3
            sources = [IdentitySource(artifacts[evidence[0].id].id, "Alice mentions shared@relay.test",
                                      "supports", "A mention is not proof of control"),
                       IdentitySource(artifacts[evidence[1].id].id, "Bob denies Alice controls",
                                      "contradicts", "A conflicting account")]
            with pytest.raises(ValueError, match="active, in this case"):
                create_identity_hypothesis(session, cases[0].id, user, "Alice controls the account",
                    ["Shared access"], sources + [IdentitySource(artifacts[evidence[2].id].id,
                    texts[2], "supports", "Other case")])
            assert session.scalars(select(Finding)).all() == []
            finding = create_identity_hypothesis(session, cases[0].id, user,
                "Alice may use the account", ["Shared access", "An impersonator"], sources)
            reviews = FindingService(session)
            reviews.verify_finding(finding.id, user, "Contradictory account reviewed")
            session.commit()
            assert EvidenceService(session).remove_evidence(evidence[1].id, user, "Withdrawn")
            assert finding.status == FindingStatus.DRAFT
            with pytest.raises(ValueError, match="active"):
                reviews.verify_finding(finding.id, user)
            assert EvidenceService(session).return_evidence(evidence[1].id, user)
            assert finding.status == FindingStatus.DRAFT
            reviews.reject_finding(finding.id, user, "Attribution disputed")
            session.commit()
            session.expire_all()
            assert session.get(Finding, finding.id).status == FindingStatus.REJECTED
            assert {link.artifact.evidence_id for link in finding.artifact_links} == {
                evidence[0].id, evidence[1].id}
    finally:
        loop.close()
        engine.dispose()
