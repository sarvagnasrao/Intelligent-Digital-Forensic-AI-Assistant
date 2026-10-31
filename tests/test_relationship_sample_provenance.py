from types import SimpleNamespace

from app.analysis.relationships import RelationshipBuilder, RelationshipStats
from app.artifacts.models import EntityType


def test_relationship_sample_comes_from_current_supporting_artifact():
    def entity(artifact_id, value, offset, snippet):
        return SimpleNamespace(
            artifact_id=artifact_id, entity_type=EntityType.EMAIL, value=value,
            normalized_value=value, start_offset=offset, end_offset=offset + len(value),
            context_snippet=snippet,
        )

    first = "first@example.test"
    second = "second@example.test"
    rows = [entity(1, first, 0, "unrelated cached snippet"),
            entity(2, first, 0, "stale cached snippet"),
            entity(2, second, len(first) + 1, "stale")]
    texts = [(1, first), (2, first + " " + second)]

    class Result:
        def __init__(self, data):
            self.data = data

        def scalars(self):
            return self.data

        def all(self):
            return self.data

    class Session:
        calls = 0

        def execute(self, statement):
            self.calls += 1
            return Result(rows if self.calls % 2 else texts)

    builder = RelationshipBuilder(Session(), 1)
    builder._evidence_ids = lambda ids: []
    builder._collect_artifact_links = lambda *args: {}
    pairs, _ = builder._collect_pairs(RelationshipStats())
    payload = next(iter(pairs.values()))
    assert payload["artifact_ids"] == [2]
    assert payload["details"]["sample"] == texts[1][1]

    rows[1].start_offset = 999
    pairs, _ = builder._collect_pairs(RelationshipStats())
    assert next(iter(pairs.values()))["details"]["sample"] == ""
