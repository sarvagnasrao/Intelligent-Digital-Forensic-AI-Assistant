"""End-to-end check of the analysis pipeline against a throwaway database.

Run from the project root::

    .venv\\Scripts\\python.exe tests\\manual\\analysis_smoke.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(WORKSPACE))

os.environ["IDFA_CONFIG_DIR"] = str(
    Path(tempfile.mkdtemp(prefix="idfa_analysis_")) / "config"
)

from app import config as config_module  # noqa: E402
from app.config import Config, save_config, set_data_dir  # noqa: E402
from app.db import load_all_models  # noqa: E402
from app.db.base import Base  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402


def main() -> int:
    data_dir = Path(tempfile.mkdtemp(prefix="idfa_analysis_data_"))
    save_config(set_data_dir(Config(), data_dir))
    config_module.clear_config_cache()
    # Analysis must not reach for a model in this check.
    cfg = config_module.get_config()
    cfg.analysis.llm_enabled = False
    cfg.analysis.defer_llm_while_examining = False

    load_all_models()
    engine = create_engine(f"sqlite:///{data_dir / 'idfa.db'}")
    Base.metadata.create_all(engine)

    from app.artifacts.models import Artifact, ArtifactType, IndexStatus
    from app.auth.models import Case, User
    from app.evidence.models import Evidence
    from app.examination.models import ExaminationJob, ExaminationOperation, JobStatus

    with Session(engine, expire_on_commit=False) as session:
        user = User(username="admin", email="a@b.c", password_hash="x", full_name="Admin")
        session.add(user)
        session.flush()
        case = Case(case_id="C-1", title="Smoke", created_by_id=user.id)
        session.add(case)
        session.flush()
        evidence = Evidence(
            evidence_id="E-1", case_id=case.id, name="disk.img",
            source_path="E:/x/disk.img", evidence_type="image", registered_by_id=user.id,
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
             "From: rahul.sharma@gmail.com\nTo: priya@example.org\nCall +91 98765 43210. "
             "Transfer to bc1qar0srrr7xfkvy5l643lydnw9re59gtzzwf5mdq on 2024-05-17T09:30:00Z"),
            ("chat_2.txt", "/Users/rsharma/chat_2.txt",
             "rahul.sharma@gmail.com again, sha256 "
             "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"),
            ("notes.txt", "/Users/priya/notes.txt",
             "Priya and Rahul met at Bengaluru office. Contact priya@example.org."),
            ("copy_of_chat_1.txt", "/Temp/copy_of_chat_1.txt",
             "From: rahul.sharma@gmail.com\nTo: priya@example.org\nCall +91 98765 43210. "
             "Transfer to bc1qar0srrr7xfkvy5l643lydnw9re59gtzzwf5mdq on 2024-05-17T09:30:00Z"),
            ("IMG_2041.JPG", "/DCIM/IMG_2041.JPG", None),
        ]
        from datetime import datetime, timezone
        for index, (name, path, content) in enumerate(rows, start=1):
            session.add(Artifact(
                artifact_id=f"ART-0001-{index:04d}", case_id=case.id,
                evidence_id=evidence.id, examination_job_id=exam.id,
                artifact_type=ArtifactType.FILE, name=name, source_path=path,
                content_text=content,
                content_hash="abc123" if index in (1, 4) else f"hash{index}",
                source_size=100, index_status=IndexStatus.NOT_INDEXED,
                created_time=datetime(2024, 5, 17, 9, 30, tzinfo=timezone.utc),
                modified_time=datetime(2024, 5, 18, 10, 0, tzinfo=timezone.utc),
            ))
        session.commit()

        import asyncio

        from app.analysis.service import AnalysisService

        service = AnalysisService(session)
        job = service.enqueue_for_examination(case.id, evidence.id, exam.id)
        session.commit()
        print(f"queued analysis job {job.job_id} status={job.status.value}")

        result = asyncio.run(service.run(job.id))
        print("run result:", result)

        session.expire_all()
        from sqlalchemy import select
        from app.artifacts.models import Entity, TimelineEvent

        entities = list(session.execute(select(Entity)).scalars())
        print(f"\n{len(entities)} entities:")
        for entity in entities[:40]:
            print(f"  {entity.entity_type.value:15} {entity.value[:52]:54} {entity.extractor}")

        events = list(session.execute(select(TimelineEvent)).scalars())
        print(f"\n{len(events)} timeline events; first: {events[0].title if events else None}")

        relationships = service.list_relationships(case.id)
        print(f"\n{len(relationships)} relationships:")
        for row in relationships[:20]:
            print(f"  {row.kind.value:16} {row.left_value[:26]:28} <-> "
                  f"{row.right_value[:26]:28} shared={row.shared_count} score={row.score}")

        print("\nentity counts:", service.entity_type_counts(case.id))
        print("relationship counts:", service.relationship_counts(case.id))
        print("queue counts:", service.counts(case.id))

        # Re-run must not duplicate anything.
        before = (len(entities), len(events), len(relationships))
        job2 = service.enqueue_for_examination(case.id, evidence.id, exam.id)
        print(f"\nsecond enqueue returned same job: {job2.id == job.id}")
        result = asyncio.run(service.run(job.id))
        session.expire_all()
        after = (
            len(list(session.execute(select(Entity)).scalars())),
            len(list(session.execute(select(TimelineEvent)).scalars())),
            len(service.list_relationships(case.id)),
        )
        print(f"counts before={before} after={after}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
