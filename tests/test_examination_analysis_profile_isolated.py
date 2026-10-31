"""Completion-time analysis queueing must preserve examination depth."""
from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.analysis.models import AnalysisJob
from app.analysis.service import AnalysisService
from app.auth.models import Case, User
from app.config import Config
from app.db import Base, load_all_models
from app.evidence.models import Evidence
from app.examination.models import ExaminationOperation, JobStatus
from app.examination.profiles import profile_parameters
from app.examination.service import ExaminationService


@pytest.mark.parametrize(
    ("profile", "llm_enabled", "entity_limit"),
    [("fast", False, 60), ("balanced", True, 60), ("deep", True, 120)],
)
def test_completion_enqueue_preserves_analysis_profile(
    monkeypatch, profile, llm_enabled, entity_limit
):
    config = Config()
    config.analysis.llm_enabled = True
    monkeypatch.setattr("app.examination.service.get_config", lambda: config)
    monkeypatch.setattr("app.analysis.service.get_config", lambda: config)
    requests = []

    def respond(request):
        requests.append(request)
        if request.method == "POST" and request.url.path == "/examine":
            return httpx.Response(200, json={"success": True, "results": []})
        return httpx.Response(200, json={})

    load_all_models()
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            user = User(
                username="profile", email="profile@example.test",
                password_hash="unused", full_name="Profile Test",
            )
            session.add(user)
            session.flush()
            case = Case(case_id="C-PROFILE", title="Profile", created_by_id=user.id)
            session.add(case)
            session.flush()
            evidence = Evidence(
                evidence_id="E-PROFILE", case_id=case.id, name="disk.img",
                source_path="C:/synthetic/disk.img", registered_by_id=user.id,
            )
            session.add(evidence)
            session.flush()
            service = ExaminationService(session)
            job = service.create_job(
                case.id, evidence.id, ExaminationOperation.FILE_TRAVERSAL,
                parameters=profile_parameters(profile), created_by=user,
            )
            session.commit()

            async def complete():
                async with httpx.AsyncClient(
                    transport=httpx.MockTransport(respond)
                ) as client:
                    service._client = client
                    return await service.start_job(job.id)

            assert asyncio.run(complete()) is True
            assert job.status == JobStatus.COMPLETED
            analysis_job = session.execute(select(AnalysisJob)).scalar_one()
            stored = json.loads(analysis_job.parameters_json)
            assert stored["profile"] == profile
            assert stored["llm_enabled"] is llm_enabled
            assert stored["max_entities_per_artifact"] == entity_limit
            assert stored == AnalysisService(session)._parameters_from_examination(job)
            effective = AnalysisService(session)._job_parameters(analysis_job)
            assert effective["llm_enabled"] is llm_enabled
            assert any(request.url.path == "/examine" for request in requests)
            assert all("/generate" not in request.url.path for request in requests)
    finally:
        engine.dispose()
