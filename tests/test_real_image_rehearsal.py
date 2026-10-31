"""Offline FAT12 image rehearsal; no mounted volume or external services."""
import asyncio
import socket
import struct
from types import SimpleNamespace

import httpx
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session


def make_image(path):
    # Standard 1.44 MB FAT12 floppy, with three one-cluster files.
    image = bytearray(1474560)
    image[:3] = b"\xeb\x3c\x90"
    image[3:11] = b"IDFATEST"
    struct.pack_into("<HBHBHHBHHHII", image, 11, 512, 1, 1, 2, 224, 2880, 0xf0, 9, 18, 2, 0, 0)
    image[510:512] = b"\x55\xaa"
    fat = bytearray(9 * 512)
    fat[:8] = b"\xf0\xff\xff\xff\xff\xff\xff\x0f"
    image[512:512 + len(fat)] = fat
    image[5120:5120 + len(fat)] = fat
    files = [
        (b"MESSAGE TXT", b"Alice uses courier@relay.test at 192.168.4.8"),
        (b"RECEIPT TXT", b"Receipt from courier@relay.test at 192.168.4.8"),
        (b"NOISE   TXT", b"Unrelated lunch inventory"),
    ]
    for i, (name, content) in enumerate(files):
        entry = 19 * 512 + i * 32
        image[entry:entry + 11] = name
        image[entry + 11] = 0x20
        struct.pack_into("<H", image, entry + 26, i + 2)
        struct.pack_into("<I", image, entry + 28, len(content))
        offset = (33 + i) * 512
        image[offset:offset + len(content)] = content
    path.write_bytes(image)


def test_real_disk_to_review(tmp_path, config_home, qt_app, monkeypatch):
    import worker.main as worker
    from app.analysis.models import RelationshipKind, RelationshipStatus
    from app.analysis.service import AnalysisService
    from app.artifacts.models import Artifact
    from app.artifacts.service import SearchService
    from app.auth.models import Case, User
    from app.config import Config, save_config, set_data_dir
    from app.db import Base, load_all_models
    from app.db.session import _FTS_TABLE_SQL, _FTS_TRIGGER_SQL
    from app.evidence.models import Evidence
    from app.examination.models import ExaminationJob, ExaminationOperation, JobStatus
    from app.examination.service import ExaminationService
    from app.findings.identity import IdentitySource, create_identity_hypothesis
    from app.findings.models import FindingStatus
    from app.findings.service import FindingService
    from app.ui.base import CaseContext
    from app.ui.pages.entities_timeline_page import EntitiesTimelinePage
    from app.ui.pages.findings_page import FindingsPage

    save_config(set_data_dir(Config(), tmp_path))
    image = tmp_path / "synthetic.img"
    make_image(image)
    load_all_models()
    engine = create_engine(f"sqlite+pysqlite:///{(tmp_path / 'rehearsal.db').as_posix()}")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(text(_FTS_TABLE_SQL))
        for statement in _FTS_TRIGGER_SQL:
            connection.execute(text(statement))
    try:
        with Session(engine, expire_on_commit=False) as session:
            user = User(username="examiner", email="e@example.test", password_hash="x", full_name="Examiner")
            session.add(user)
            session.flush()
            case = Case(case_id="CASE-IMAGE", title="Image rehearsal", created_by_id=user.id)
            session.add(case)
            session.flush()
            evidence = Evidence(evidence_id="E-IMAGE", case_id=case.id, name="synthetic.img", source_path=str(image), registered_by_id=user.id, size_bytes=image.stat().st_size)
            session.add(evidence)
            session.flush()
            exam = ExaminationJob(job_id="EX-IMAGE", case_id=case.id, evidence_id=evidence.id, operation=ExaminationOperation.FILE_TRAVERSAL, status=JobStatus.PENDING, created_by_id=user.id)
            session.add(exam)
            session.commit()

            async def scan():
                service = ExaminationService(session)
                service._client = httpx.AsyncClient(transport=httpx.ASGITransport(app=worker.app), base_url="http://isolated-worker")
                try:
                    with monkeypatch.context() as guard:
                        guard.setattr(socket.socket, "connect", deny_network)
                        guard.setattr(socket.socket, "connect_ex", deny_network)
                        return await asyncio.wait_for(service.start_job(exam.id), 30)
                finally:
                    await service.close()

            def deny_network(*args, **kwargs):
                raise AssertionError("External network access forbidden during rehearsal")

            assert asyncio.run(scan()), exam.error_message
            assert exam.status == JobStatus.COMPLETED
            artifacts = {a.name.lower(): a for a in session.scalars(select(Artifact)).all()}
            assert artifacts["message.txt"].content_text == "Alice uses courier@relay.test at 192.168.4.8"
            assert "courier@relay.test" in artifacts["receipt.txt"].content_text
            results = asyncio.run(SearchService(session).keyword_search(case.id, '"courier@relay.test"'))
            assert {r["artifact"].name.lower() for r in results} == {"message.txt", "receipt.txt"}
            analysis = AnalysisService(session)
            job = analysis.enqueue_for_examination(case.id, evidence.id, exam.id, created_by=user, parameters={"llm_enabled": False, "build_relationships": True}, manual=True)
            session.commit()
            async def analyse():
                with monkeypatch.context() as guard:
                    guard.setattr(socket.socket, "connect", deny_network)
                    guard.setattr(socket.socket, "connect_ex", deny_network)
                    return await analysis.run(job.id, user)

            assert asyncio.run(analyse())["ok"]
            context = CaseContext(case.id, case.case_id, case.title, "open", "medium", user.full_name)
            page = EntitiesTimelinePage()
            page.set_analysis_service(analysis)
            page.set_case_context(context)
            page.refresh()
            assert page.rel_model.rowCount() > 0
            target = next(r for r in analysis.list_relationships(case.id) if r.kind == RelationshipKind.RELATED_ARTIFACTS)
            row = next(i for i, item in enumerate(page._relationships) if item.id == target.id)
            page.rel_table.selectRow(row)
            page._on_relationship_selected()
            assert "courier@relay.test" in page.rel_evidence.toPlainText()
            page._review_relationship(RelationshipStatus.CONFIRMED)
            assert any(r.status == RelationshipStatus.CONFIRMED for r in analysis.list_relationships(case.id, status=None))
            finding = create_identity_hypothesis(session, case.id, user, "Alice may use the mailbox", ["Shared access"], [IdentitySource(artifacts["message.txt"].id, "Alice uses courier@relay.test", "supports", "Source claim")])
            FindingService(session).verify_finding(finding.id, user, "Reviewed source")
            session.commit()
            assert finding.status == FindingStatus.VERIFIED
            findings = FindingsPage(nav=SimpleNamespace(get_current_user=lambda: user))
            findings.set_finding_service(FindingService(session))
            findings.set_case_context(context)
            findings.refresh()
            assert findings.table_model.rowCount() == 1
            page.deleteLater()
            findings.deleteLater()
    finally:
        engine.dispose()
