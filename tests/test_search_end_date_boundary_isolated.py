"""Inclusive end-date filtering across case inventory and search modes."""

import asyncio
from datetime import UTC, date, datetime

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.artifacts.models import Artifact, ArtifactType
from app.artifacts.service import SearchService
from app.auth.models import Case, User
from app.evidence.models import Evidence


def test_end_date_includes_last_microsecond_but_not_next_day(tmp_path, config_home, data_dir):
    from app.config import Config, save_config, set_data_dir
    from app.db import Base, load_all_models
    from app.db.session import _FTS_TABLE_SQL, _FTS_TRIGGER_SQL

    save_config(set_data_dir(Config(), data_dir))
    load_all_models()
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'boundary.db'}")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(text(_FTS_TABLE_SQL))
        for statement in _FTS_TRIGGER_SQL:
            connection.execute(text(statement))
    with Session(engine) as session:
        user = User(
            username="boundary",
            email="boundary@example.invalid",
            password_hash="x",
            full_name="Boundary",
        )
        session.add(user)
        session.flush()
        case = Case(case_id="CASE-BOUNDARY", title="Boundary", created_by_id=user.id)
        session.add(case)
        session.flush()
        evidence = Evidence(
            evidence_id="E-BOUNDARY",
            case_id=case.id,
            name="Disk",
            source_path="/disk",
            registered_by_id=user.id,
        )
        session.add(evidence)
        session.flush()
        for suffix, created in [
            ("last", datetime(2024, 5, 1, 23, 59, 59, 999999, tzinfo=UTC)),
            ("next", datetime(2024, 5, 2, tzinfo=UTC)),
        ]:
            session.add(
                Artifact(
                    artifact_id=f"ART-{suffix}",
                    case_id=case.id,
                    evidence_id=evidence.id,
                    artifact_type=ArtifactType.FILE,
                    name=f"{suffix}.txt",
                    source_path=f"/{suffix}",
                    content_text="needle",
                    created_time=created,
                )
            )
        session.commit()
        service = SearchService(session)
        end = date(2024, 5, 1)
        results = [service.list_case_artifacts(case.id, date_to=end, evidence_id=evidence.id)]
        for regex in (False, True):
            results.append(
                asyncio.run(
                    service.keyword_search(
                        case.id, "needle", date_to=end, evidence_id=evidence.id, regex=regex
                    )
                )
            )
        for rows in results:
            assert [row["artifact"].artifact_id for row in rows] == ["ART-last"]
    engine.dispose()
