"""A query parameter can contain a source-backed network-address lead."""

import socket

from test_synthetic_investigation import MemorySession, ingest, worker_row

from app.analysis.extractors import content_entities_for_artifact
from app.analysis.relationships import RelationshipBuilder, RelationshipStats
from app.artifacts.models import Entity, EntityType


def test_query_address_links_to_separate_artifact_without_inventing_host(monkeypatch):
    sources = [
        b"Review https://portal.invalid/search?peer=192.0.2.42&ticket=9",
        b"Gateway observed 192.0.2.42; ownership unknown.",
        b"Unrelated entry.",
    ]
    session = MemorySession()
    rows = [worker_row(f"{i}.txt", s) for i, s in enumerate(sources)]
    assert ingest(session, rows)["created"] == 3

    def reject_network(*args, **kwargs):
        raise AssertionError("unexpected network access")

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
    assert any(e.entity_type is EntityType.URL for e in first)
    assert any(e.entity_type is EntityType.IP_ADDRESS and e.value == "192.0.2.42" for e in first)
    builder = RelationshipBuilder(session, 1)
    builder._evidence_ids = lambda ids: [7]
    _, pairs = builder._collect_pairs(RelationshipStats())
    assert any(set(pair["artifact_ids"]) == {1, 2} and any(
        item["value"] == "192.0.2.42" for item in pair["details"]["shared"]
    ) for pair in pairs.values())
