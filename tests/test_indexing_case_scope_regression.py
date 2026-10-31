"""Indexing must not embed artifacts linked to a different case's evidence."""
import asyncio

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.artifacts.models import Artifact, ArtifactType, IndexStatus
from app.artifacts.service import SearchService
from app.auth.models import Case, User
from app.evidence.models import Evidence


def test_indexing_excludes_evidence_from_another_case(config_home, data_dir, monkeypatch):
    from app.config import Config, save_config, set_data_dir
    from app.db import Base, load_all_models

    save_config(set_data_dir(Config(), data_dir))
    load_all_models()
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        user = User(username="scope", email="scope@example.invalid", password_hash="x", full_name="Scope")
        session.add(user)
        session.flush()
        cases = [Case(case_id=f"CASE-{i}", title="Case", created_by_id=user.id) for i in (1, 2)]
        session.add_all(cases)
        session.flush()
        evidence = [Evidence(evidence_id=f"EV-{i}", case_id=case.id, name="Disk",
                             source_path="/disk", registered_by_id=user.id)
                    for i, case in enumerate(cases)]
        session.add_all(evidence)
        session.flush()
        artifact = Artifact(artifact_id="ART-mismatch", case_id=cases[0].id,
                            evidence_id=evidence[1].id, artifact_type=ArtifactType.FILE,
                            name="secret.txt", source_path="/secret.txt", content_text="secret",
                            index_status=IndexStatus.NOT_INDEXED)
        session.add(artifact)
        session.commit()
        service = SearchService(session)
        calls = []

        async def ensure_collection(name):
            calls.append(name)

        monkeypatch.setattr(service, "_ensure_collection", ensure_collection)
        result = asyncio.run(service.index_artifacts(cases[0].id, artifact_ids=[artifact.id]))
        assert result == {"indexed": 0, "message": "No artifacts to index"}
        assert calls == []
        assert artifact.index_status == IndexStatus.NOT_INDEXED
    engine.dispose()
