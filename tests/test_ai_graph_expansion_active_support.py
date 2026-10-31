"""Graph expansion rejects historical or inactive supporting provenance."""
import json
from types import SimpleNamespace

import pytest

from app.ui.pages.ai_analysis_page import AskWorker


class Result:
    def __init__(self, rows):
        self.rows = rows

    def scalars(self):
        return iter(self.rows)


class GraphSession:
    def __init__(self, details, support, active):
        self.edge = SimpleNamespace(
            details_json=details, artifact_ids_json=json.dumps(support),
        )
        self.active = active
        self.statements = []

    def execute(self, statement):
        self.statements.append(str(statement))
        if len(self.statements) == 1:
            return Result([self.edge])
        if len(self.statements) == 2:
            return Result(self.active)
        return Result([SimpleNamespace(id=2)])


@pytest.mark.parametrize("details", [
    '{"unsupported_after_rebuild": true}', '[]', 'null', '{bad json',
])
def test_historical_or_malformed_details_do_not_expand(details, config_home):
    worker = AskWorker(1, "needle", 1)
    session = GraphSession(details, [1, 2], [1, 2])
    seeds = [{"citation": {"db_id": 1}}]
    assert worker._expand_graph(session, seeds) == seeds
    assert len(session.statements) == 1


@pytest.mark.parametrize("support,active", [
    ([1, 2], [1]), ([1, 2, 3], [1, 2]), ([1, "2"], [1, 2]),
])
def test_all_support_must_resolve_to_active_case_artifacts(support, active, config_home):
    worker = AskWorker(1, "needle", 1)
    session = GraphSession("{}", support, active)
    seeds = [{"citation": {"db_id": 1}}]
    assert worker._expand_graph(session, seeds) == seeds
    assert len(session.statements) <= 2
    if len(session.statements) == 2:
        statement = session.statements[1]
        assert "artifacts.case_id =" in statement
        assert "evidence.case_id =" in statement
        assert "evidence.removed_at IS NULL" in statement


def test_supported_current_edge_still_expands(monkeypatch, config_home):
    worker = AskWorker(1, "needle", 1)
    session = GraphSession("{}", [1, 2], [1, 2])
    monkeypatch.setattr(worker, "_as_item", lambda *args, **kwargs: {
        "citation": {"db_id": 2, "provenance": "artifact text"},
    })
    result = worker._expand_graph(session, [{"citation": {"db_id": 1}}])
    assert [item["citation"]["db_id"] for item in result] == [1, 2]
    assert len(session.statements) == 3
