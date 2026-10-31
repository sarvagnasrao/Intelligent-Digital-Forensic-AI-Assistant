"""Duplicate leads retain their actual endpoints beyond the sample cap."""

import json

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.analysis.models import EntityRelationship, RelationshipKind
from app.analysis.relationships import RelationshipBuilder, RelationshipSettings
from app.artifacts.models import Artifact, ArtifactType
from app.auth.models import Case, User
from app.db import Base, load_all_models
from app.evidence.models import Evidence


def test_duplicate_edges_include_both_source_artifacts(tmp_path):
    load_all_models()
    engine = create_engine(f"sqlite+pysqlite:///{(tmp_path / 'case.db').as_posix()}")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            user = User(username="examiner", email="examiner@example.test",
                        password_hash="x", full_name="Examiner")
            session.add(user)
            session.flush()
            case = Case(case_id="C-DUP", title="Synthetic", created_by_id=user.id)
            session.add(case)
            session.flush()
            evidence = Evidence(evidence_id="E-DUP", case_id=case.id, name="Synthetic",
                                source_path="synthetic", registered_by_id=user.id)
            session.add(evidence)
            session.flush()
            artifacts = [Artifact(
                artifact_id=f"ART-DUP-{i:03d}", case_id=case.id,
                evidence_id=evidence.id, artifact_type=ArtifactType.FILE,
                name=f"{i}.txt", source_path=f"/synthetic/{i}.txt",
                content_hash="a" * 64, content_text="same synthetic content",
            ) for i in range(45)]
            session.add_all(artifacts)
            session.commit()
            builder = RelationshipBuilder(session, case.id, RelationshipSettings())
            builder.rebuild()
            session.commit()
            links = session.scalars(select(EntityRelationship).where(
                EntityRelationship.kind == RelationshipKind.DUPLICATE_CONTENT
            )).all()
            assert len(links) == 44
            by_name = {artifact.artifact_id.lower(): artifact.id for artifact in artifacts}
            for link in links:
                supporting = json.loads(link.artifact_ids_json)
                assert len(supporting) <= 40
                assert {by_name[link.left_value], by_name[link.right_value]} <= set(supporting)
                assert json.loads(link.evidence_ids_json) == [evidence.id]
            builder.rebuild()
            session.commit()
            assert len(session.scalars(select(EntityRelationship)).all()) == 44
    finally:
        engine.dispose()
