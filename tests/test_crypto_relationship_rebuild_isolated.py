"""Exercise crypto relationship identity through a real SQLite rebuild."""

import json

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.analysis.extractors import extract_entities
from app.analysis.models import EntityRelationship, RelationshipKind, RelationshipStatus
from app.analysis.relationships import RelationshipBuilder
from app.artifacts.models import Artifact, Entity, EntityType
from app.auth.models import Case, User
from app.db import Base, load_all_models
from app.evidence.models import Evidence


def test_case_distinct_bitcoin_addresses_and_review_survive_rebuild():
    first = "1BoatSLRHtKNngkdXEeobR76b53LETtpyT"
    second = "1boatSLRHtKNngkdXEeobR76b53LETtpyT"
    load_all_models()
    engine = create_engine("sqlite+pysqlite:///:memory:")
    try:
        Base.metadata.create_all(engine)
        with Session(engine) as session:
            user = User(
                username="reviewer", email="r@example.test", password_hash="x", full_name="R"
            )
            session.add(user)
            session.flush()
            case = Case(case_id="C-1", title="Case", created_by_id=user.id)
            session.add(case)
            session.flush()
            evidence = Evidence(evidence_id="E-1", case_id=case.id, name="disk",
                                source_path="disk", registered_by_id=user.id, size_bytes=1)
            session.add(evidence)
            session.flush()
            artifacts = []
            for index, address in enumerate((first, second, first), 1):
                artifact = Artifact(artifact_id=f"ART-{index}", case_id=case.id,
                                    evidence_id=evidence.id, name=f"{index}.txt",
                                    content_text=address)
                session.add(artifact)
                session.flush()
                leads = [lead for lead in extract_entities(address)
                         if lead.entity_type is EntityType.CRYPTO_ADDRESS]
                assert len(leads) == 1
                lead = leads[0]
                session.add(Entity(entity_id=f"ENT-{index}", case_id=case.id,
                                   artifact_id=artifact.id, entity_type=lead.entity_type,
                                   value=lead.value, normalized_value=lead.normalized,
                                   start_offset=lead.start, end_offset=lead.end,
                                   extractor="regex"))
                artifacts.append(artifact)
            session.commit()

            builder = RelationshipBuilder(session, case.id)
            builder.rebuild()
            session.commit()
            rows = session.scalars(select(EntityRelationship)).all()
            assert len(rows) == 1
            edge = rows[0]
            assert edge.kind is RelationshipKind.RELATED_ARTIFACTS
            assert set(json.loads(edge.artifact_ids_json)) == {artifacts[0].id, artifacts[2].id}
            assert json.loads(edge.details_json)["shared"][0]["value"] == first
            edge.status = RelationshipStatus.CONFIRMED
            edge_id = edge.id
            session.commit()

            builder.rebuild()
            session.commit()
            rows = session.scalars(select(EntityRelationship)).all()
            assert len(rows) == 1
            assert rows[0].id == edge_id
            assert rows[0].status is RelationshipStatus.CONFIRMED
            assert set(json.loads(rows[0].artifact_ids_json)) == {artifacts[0].id, artifacts[2].id}
    finally:
        engine.dispose()
