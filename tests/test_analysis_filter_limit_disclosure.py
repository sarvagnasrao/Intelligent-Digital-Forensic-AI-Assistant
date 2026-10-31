"""The displayed filters must not imply that capped results cover the case."""
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.analysis.models import RelationshipStatus
from app.ui.pages import entities_timeline_page as module


@pytest.fixture
def page(qt_app, monkeypatch):
    monkeypatch.setattr(module, "RELATIONSHIP_TAB_LIMIT", 2)
    monkeypatch.setattr(module, "TIMELINE_TAB_LIMIT", 2)
    widget = module.EntitiesTimelinePage()
    widget.case_context = SimpleNamespace(case_id=1)
    widget._artifact_label_map = lambda: {}
    yield widget
    widget.deleteLater()


def relationship(value):
    return SimpleNamespace(
        left_value=value, right_value="other", details_json="{}",
        left_type="email", right_type="email", kind=SimpleNamespace(value="shared_entity"),
        shared_count=1, score=0.9, status=RelationshipStatus.PENDING,
    )


def event(title, event_type="file"):
    return SimpleNamespace(
        timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc), event_type=event_type,
        title=title, description="", artifact=None, certainty="known",
    )


class Service:
    def __init__(self, relationships=(), events=()):
        self.relationships = relationships
        self.events = events

    def list_relationships(self, case_id, *, status, kind, limit):
        return list(self.relationships[:limit])

    def relationship_counts(self, case_id):
        return {"pending": len(self.relationships)}

    def list_timeline(self, case_id, *, limit):
        return list(self.events[:limit])


def test_relationship_search_warns_even_when_no_loaded_rows_match(page):
    page.analysis_service = Service(relationships=[relationship("a"), relationship("b"), relationship("needle")])
    page.rel_search.setText("needle")
    assert page.rel_model.rowCount() == 0
    assert "only the top 2 by score" in page.rel_summary.text()
    assert "status and kind" in page.rel_summary.text()


def test_timeline_filters_disclose_limited_source_and_types(page):
    page.analysis_service = Service(events=[event("a"), event("b"), event("needle", "older")])
    page.tl_search.setText("needle")
    assert page.timeline_model.rowCount() == 0
    assert "only the most recent 2 events" in page.tl_summary.text()
    assert "older events are not included" in page.tl_summary.text()
    assert page.tl_type_filter.findData("older") == -1


def test_exact_limit_does_not_claim_results_are_missing(page):
    page.analysis_service = Service(relationships=[relationship("a"), relationship("b")], events=[event("a"), event("b")])
    page._refresh_relationships()
    page._refresh_timeline()
    assert "only the top" not in page.rel_summary.text()
    assert "older events are not included" not in page.tl_summary.text()
    assert page.rel_model.rowCount() == page.timeline_model.rowCount() == 2
