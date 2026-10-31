"""Offline query-parameter leads retain their source and can link artifacts."""

import socket

from test_synthetic_investigation import MemorySession, ingest, worker_row

from app.analysis.extractors import content_entities_for_artifact
from app.analysis.relationships import RelationshipBuilder, RelationshipStats
from app.artifacts.models import Entity, EntityType


def test_email_in_url_query_links_to_separate_source(monkeypatch):
    def reject_network(*args, **kwargs):
        raise AssertionError("unexpected network access")

    sources = [
        b"Audit URL https://portal.invalid/review?contact=courier@relay.test&ticket=42",
        b"Reply requested from courier@relay.test; context unknown.",
        b"Unrelated log entry.",
    ]
    session = MemorySession()
    rows = [worker_row(f"{i}.txt", s) for i, s in enumerate(sources)]
    assert ingest(session, rows)["created"] == 3
    # Windows asyncio creates its event-loop socketpair during ingestion.
    monkeypatch.setattr(socket.socket, "connect", reject_network)
    monkeypatch.setattr(socket.socket, "connect_ex", reject_network)
    for artifact in session.artifacts:
        for item in content_entities_for_artifact(artifact):
            field = item.metadata.get("field", "content_text")
            assert getattr(artifact, field)[item.start:item.end] == item.value
            session.entities.append(Entity(
                id=len(session.entities) + 1, case_id=1, artifact_id=artifact.id,
                entity_type=item.entity_type, value=item.value, normalized_value=item.normalized,
            ))
    first = [e for e in session.entities if e.artifact_id == 1]
    assert any(
        e.entity_type is EntityType.URL and "contact=courier@relay.test" in e.value for e in first
    )
    assert any(e.entity_type is EntityType.EMAIL and e.value == "courier@relay.test" for e in first)
    builder = RelationshipBuilder(session, 1)
    builder._evidence_ids = lambda ids: [7]
    _, pairs = builder._collect_pairs(RelationshipStats())
    assert any(set(pair["artifact_ids"]) == {1, 2} and any(
        item["value"] == "courier@relay.test" for item in pair["details"]["shared"]
    ) for pair in pairs.values())
