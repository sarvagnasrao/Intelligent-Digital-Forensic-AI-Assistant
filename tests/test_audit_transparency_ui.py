"""Audit counts and exports describe the actual locally filtered records."""
import json
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock

from app.ui.pages.audit_page import AuditPage, QFileDialog, QMessageBox


def audit_event(event_id, username, result="success"):
    return SimpleNamespace(
        event_id=event_id, timestamp=datetime(2026, 1, 1), event_type="search",
        action="searched", result=result, user=SimpleNamespace(username=username),
        target_type=None, target_id=None, details_json=None, error_message=None,
        ip_address=None, request_id=None,
    )


def custody_event(username):
    return SimpleNamespace(
        performed_at=datetime(2026, 1, 1), event_type="viewed", evidence=None,
        performed_by=SimpleNamespace(username=username), description="Viewed",
        source_location=None, destination_location=None, tool_used=None, metadata_json=None,
    )


def test_filtered_exports_and_tab_specific_filters(qt_app, tmp_path, monkeypatch):
    page = AuditPage()
    page.case_context = SimpleNamespace(case_id=1, case_id_str="case-1")
    page._all_audit_events = [audit_event("a", "Alice"), audit_event("b", "Bob", "failure")]
    page._all_custody_events = [custody_event("Alice"), custody_event("Bob")]
    page._update_type_filter()
    page.user_filter.setText("alice")
    assert "Showing 1 of 2 loaded audit events" in page.count_label.text()
    path = tmp_path / "audit.json"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args: (str(path), "JSON files (*.json)"))
    monkeypatch.setattr(QMessageBox, "information", lambda *args: None)
    page._export_current()
    assert [row["event_id"] for row in json.loads(path.read_text(encoding="utf-8"))] == ["a"]

    page.result_filter.setCurrentText("failure")
    page.tabs.setCurrentIndex(1)
    assert "Showing 1 of 2 loaded chain-of-custody records" in page.count_label.text()
    assert "Type and result filters apply only to the audit trail" in page.count_label.text()
    path = tmp_path / "custody.json"
    page._export_current()
    assert [row["performed_by"] for row in json.loads(path.read_text(encoding="utf-8"))] == ["Alice"]
    page.close()


def test_load_limit_warning_and_empty_filtered_export(qt_app, monkeypatch):
    page = AuditPage()
    page.RECORD_LIMIT = 2
    page.case_context = SimpleNamespace(case_id=1, case_id_str="case-1")
    service = Mock()
    service.get_case_audit_events.return_value = [audit_event("a", "Alice"), audit_event("b", "Bob")]
    service.get_case_custody_events.return_value = [custody_event("Alice")]
    page.audit_service = service
    page.refresh()
    service.get_case_audit_events.assert_called_once_with(1, limit=2)
    assert "Load limit reached" in page.count_label.text()
    page.user_filter.setText("nobody")
    assert "Showing 0 of 2 loaded" in page.count_label.text()
    messages = []
    monkeypatch.setattr(QMessageBox, "information", lambda *args: messages.append(args[2]))
    page._export_current()
    assert "No records are displayed" in messages[0]
    page.tabs.setCurrentIndex(1)
    assert "Load limit reached" not in page.count_label.text()
    page.close()
