"""Content filtering is a UI-only subset, never a change to search semantics."""
from datetime import date, datetime

import pytest

from app.artifacts.models import Artifact, ArtifactType, IndexStatus
from app.ui.base import CaseContext
from app.ui.pages.artifacts_search_page import (
    ArtifactsSearchPage,
    SearchWorker,
    _has_extracted_text,
)


def result(content, kind=ArtifactType.FILE, number=1):
    return {
        "artifact": Artifact(
            id=number, artifact_id=f"ART-{number}", name=f"file-{number}",
            artifact_type=kind, content_text=content,
            index_status=IndexStatus.NOT_INDEXED,
            created_time=datetime(2020, 1, 2),
        ),
        "source": "keyword", "snippet": "a filename match, not content",
        "matched_fields": ["name"], "score": 0.5,
    }


@pytest.mark.parametrize(("content", "expected"), [
    (None, False), ("", False), (" \t\n\u2003", False),
    ("[Image - 12 bytes]", False),
    ("[Office Document - 12 bytes]", False),
    ("[SQLite Database - 12 bytes]", False),
    ("hello", True), ("0", True), ("日本語", True),
    ("[Image - 12 bytes]\nActual extracted note", True),
])
def test_presence_uses_content_not_type_or_index(content, expected):
    for kind in (ArtifactType.FILE, ArtifactType.DOCUMENT, ArtifactType.IMAGE):
        artifact = result(content, kind)["artifact"]
        for status in IndexStatus:
            artifact.index_status = status
            assert _has_extracted_text(artifact) is expected


def test_inventory_filter_and_show_all_reset(qt_app):
    rows = [result(None, number=1), result("actual text", number=2)]

    class Inventory:
        def list_case_evidence(self, case_id):
            return []

        def list_case_artifacts(self, *args, **kwargs):
            return rows

    page = ArtifactsSearchPage()
    try:
        page.set_search_service(Inventory())
        page.set_case_context(CaseContext(1, "CASE-1", "Case", "open", "normal", "Tester"))
        assert page.content_filter.currentText() == "All"
        assert page.table_model.rowCount() == 2
        for key, expected in (("with_text", rows[1:]), ("without_text", rows[:1])):
            page.content_filter.setCurrentIndex(page.content_filter.findData(key))
            page._load_case_artifacts()
            assert page.table_model._search_results == expected
            assert page.result_summary.text() == "1 artifact(s) matching filters"
        page._show_all_artifacts()
        assert page.content_filter.currentData() == "all"
        assert page.table_model._search_results == rows
    finally:
        page.close()


@pytest.mark.parametrize("mode", ["Keyword", "Semantic", "Hybrid"])
def test_search_keeps_query_ranking_metadata_and_discloses_limits(qt_app, mode):
    rows = [result("text", number=1), result(None, number=2), result("more", number=3)]
    calls = []

    class Search:
        async def keyword_search(self, *args, **kwargs):
            calls.append((args, kwargs))
            return rows

        semantic_search = keyword_search
        hybrid_search = keyword_search

    page = ArtifactsSearchPage()
    try:
        page.content_filter.setCurrentIndex(page.content_filter.findData("with_text"))
        worker = SearchWorker(
            Search(), 7, '"exact phrase" OR prefix*', mode, ArtifactType.FILE,
            date(2020, 1, 1), date(2020, 1, 3), regex=True, evidence_id=9,
        )
        worker.finished.connect(page._on_search_finished)
        worker.run()
        args, kwargs = calls[0]
        assert args == (7, '"exact phrase" OR prefix*', ArtifactType.FILE)
        assert kwargs["evidence_id"] == 9
        assert kwargs["date_from"] == date(2020, 1, 1)
        assert kwargs["date_to"] == date(2020, 1, 3)
        assert ("regex" in kwargs) is (mode != "Semantic")
        assert page.table_model._search_results == [rows[0], rows[2]]
        assert page.table_model._search_results[0]["artifact"] is rows[0]["artifact"]
        assert "2 of 3 returned" in page.result_summary.text()
        assert "after search limits" in page.result_summary.text()
        assert "Semantic search only retrieves indexed text" in page.content_filter.toolTip()
        page.content_filter.setCurrentIndex(page.content_filter.findData("without_text"))
        page._on_search_finished(rows)
        assert page.table_model._search_results == [rows[1]]
        page._on_search_finished([rows[0]])
        assert page.table_model.rowCount() == 0
        assert "0 of 1 returned" in page.result_summary.text()
        page.content_filter.setCurrentIndex(0)
        page._on_search_finished(rows)
        assert page.table_model._search_results == rows
    finally:
        page.close()
