"""Search completion must not overwrite a newer case or leave threads running."""
import threading
import time

from app.ui.base import CaseContext
from app.ui.pages.artifacts_search_page import ArtifactsSearchPage


class BlockingSearch:
    def __init__(self, fail=False):
        self.started = threading.Event()
        self.release = threading.Event()
        self.calls = []
        self.fail = fail

    def list_case_evidence(self, case_id):
        return []

    def list_case_artifacts(self, case_id, *args, **kwargs):
        return []

    async def keyword_search(self, case_id, query, *args, **kwargs):
        self.calls.append((case_id, query))
        self.started.set()
        if not self.release.wait(5):
            raise RuntimeError("test timed out")
        if self.fail:
            raise RuntimeError("search failed")
        return []


def wait_for(qt_app, predicate):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        qt_app.processEvents()
        if predicate():
            return
        time.sleep(0.005)
    assert predicate()


def context(case_id):
    return CaseContext(case_id, f"CASE-{case_id}", "Case", "open", "normal", "Tester")


def test_case_switch_and_enter_do_not_accept_stale_result(qt_app):
    page = ArtifactsSearchPage()
    service = BlockingSearch()
    page.set_search_service(service)
    page.set_case_context(context(1))
    page.query_edit.setText("first")
    page._on_search()
    try:
        assert service.started.wait(2)
        page.set_case_context(context(2))
        page.query_edit.setText("second")
        page._on_search()
        assert service.calls == [(1, "first")]
        service.release.set()
        wait_for(qt_app, lambda: not page._search_active)
        assert page.result_summary.text() == "0 artifact(s) in this case"
        assert page.search_btn.isEnabled()
    finally:
        service.release.set()
        page.shutdown()
        page.close()


def test_error_stops_thread_and_allows_retry(qt_app, monkeypatch):
    page = ArtifactsSearchPage()
    service = BlockingSearch(fail=True)
    errors = []
    monkeypatch.setattr("app.ui.pages.artifacts_search_page.QMessageBox.critical",
                        lambda *args: errors.append(args[-1]))
    page.set_search_service(service)
    page.set_case_context(context(1))
    page.query_edit.setText("first")
    page._on_search()
    try:
        assert service.started.wait(2)
        service.release.set()
        wait_for(qt_app, lambda: not page._search_active)
        assert errors == ["search failed"]
        assert page.search_btn.isEnabled()
        page._on_search()
        wait_for(qt_app, lambda: not page._search_active)
        assert len(service.calls) == 2
    finally:
        service.release.set()
        page.shutdown()
        page.close()


def test_stale_error_is_not_shown_after_switch(qt_app, monkeypatch):
    page = ArtifactsSearchPage()
    service = BlockingSearch(fail=True)
    errors = []
    monkeypatch.setattr("app.ui.pages.artifacts_search_page.QMessageBox.critical",
                        lambda *args: errors.append(args[-1]))
    page.set_search_service(service)
    page.set_case_context(context(1))
    page.query_edit.setText("first")
    page._on_search()
    try:
        assert service.started.wait(2)
        page.set_case_context(context(2))
        service.release.set()
        wait_for(qt_app, lambda: not page._search_active)
        assert errors == []
        assert page.search_btn.isEnabled()
    finally:
        service.release.set()
        page.shutdown()
        page.close()
