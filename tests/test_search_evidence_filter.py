"""Evidence filtering uses isolated SQLite and a fake vector service."""
import asyncio
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.artifacts.models import Artifact, ArtifactType, IndexStatus
from app.artifacts.service import SearchService
from app.auth.models import Case, User
from app.evidence.models import Evidence


@pytest.fixture
def setup_search(tmp_path, config_home, data_dir):
    from app.config import Config, save_config, set_data_dir
    from app.db import Base, load_all_models
    from app.db.session import _FTS_TABLE_SQL, _FTS_TRIGGER_SQL

    save_config(set_data_dir(Config(), data_dir))
    load_all_models()
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'filter.db'}")
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(text(_FTS_TABLE_SQL))
        for statement in _FTS_TRIGGER_SQL:
            conn.execute(text(statement))
    with Session(engine) as session:
        user = User(username="filter", email="filter@example.invalid", password_hash="x", full_name="Filter")
        session.add(user)
        session.flush()
        cases = [Case(case_id=f"CASE-{i}", title="Case", created_by_id=user.id) for i in (1, 2)]
        session.add_all(cases)
        session.flush()
        evidence = [Evidence(evidence_id=f"E-{i}", case_id=cases[0 if i < 3 else 1].id,
                             name=f"Disk {i}", source_path=f"/{i}", registered_by_id=user.id,
                             removed_at=datetime.now(timezone.utc) if i == 2 else None)
                    for i in range(4)]
        session.add_all(evidence)
        session.flush()
        for i, ev in enumerate(evidence):
            session.add(Artifact(artifact_id=f"ART-{i}", case_id=ev.case_id, evidence_id=ev.id,
                                 artifact_type=ArtifactType.FILE, name=f"file{i}.txt",
                                 source_path=f"/{i}.txt", content_text="needle",
                                 index_status=IndexStatus.INDEXED))
        session.commit()
        yield SearchService(session), cases[0].id, [ev.id for ev in evidence]
    engine.dispose()


def test_filter_before_keyword_and_regex_limits(setup_search):
    service, case, ids = setup_search
    assert [e.id for e in service.list_case_evidence(case)] == ids[:2]
    assert [x["artifact"].evidence_id for x in service.list_case_artifacts(case, evidence_id=ids[1])] == [ids[1]]
    for regex in (False, True):
        results = asyncio.run(service.keyword_search(case, "needle", limit=1, regex=regex, evidence_id=ids[1]))
        assert [x["artifact"].evidence_id for x in results] == [ids[1]]
        for invalid in ids[2:]:
            assert not asyncio.run(service.keyword_search(case, "needle", regex=regex, evidence_id=invalid))


def test_semantic_and_hybrid_filter_vector_candidates_and_validate_database(setup_search, monkeypatch):
    service, case, ids = setup_search
    payloads = []

    class Response:
        status_code = 200
        def json(self):
            return {"result": [{"score": 0.9, "payload": {"artifact_id": f"ART-{i}", "text": "needle"}}
                               for i in range(4)]}

    class Client:
        async def post(self, url, json, **kwargs):
            payloads.append(json)
            return Response()

    async def embedding(query):
        return [0.1]

    monkeypatch.setattr(service, "_get_embedding", embedding)
    service._client = Client()
    for method in (service.semantic_search, service.hybrid_search):
        results = asyncio.run(method(case, "needle", evidence_id=ids[1]))
        assert [x["artifact"].evidence_id for x in results] == [ids[1]]
        assert {"key": "evidence_id", "match": {"value": ids[1]}} in payloads[-1]["filter"]["must"]
        for invalid in ids[2:]:
            assert not asyncio.run(method(case, "needle", evidence_id=invalid))


def test_evidence_picker_lists_active_case_items_and_resets(setup_search, qt_app):
    from app.ui.base import CaseContext
    from app.ui.pages.artifacts_search_page import ArtifactsSearchPage

    service, case, ids = setup_search
    page = ArtifactsSearchPage()
    page.set_search_service(service)
    page.set_case_context(CaseContext(case, "CASE-1", "Case", "open", "normal", "Tester"))
    assert page.evidence_filter.count() == 3
    page.evidence_filter.setCurrentIndex(2)
    page._load_case_artifacts()
    assert page.table_model.rowCount() == 1
    assert page.table_model.get_artifact_at_row(0).evidence_id == ids[1]
    page._show_all_artifacts()
    assert page.evidence_filter.currentData() is None
    page.close()
