"""Offscreen case-dashboard tests for meaningful KPI selection and sorting."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace


def _case(identifier: str, status: str, priority: str, updated_at: datetime):
    return SimpleNamespace(
        case_id=identifier,
        title=f"Synthetic {identifier}",
        status=status,
        priority=priority,
        assignee=None,
        created_at=updated_at - timedelta(days=1),
        updated_at=updated_at,
    )


def test_kpi_filters_match_service_metrics_and_clear(qt_app):
    from app.ui.pages.case_management_page import CaseManagementPage

    page = CaseManagementPage(nav_controller=None)
    now = datetime(2026, 1, 7, tzinfo=timezone.utc)
    page.table_model.populate([
        _case("CASE-OPEN-HIGH", "open", "high", now),
        _case("CASE-OPEN-LOW", "open", "low", now),
        _case("CASE-ACTIVE", "active", "medium", now),
        _case("CASE-HOLD", "on_hold", "critical", now),
        _case("CASE-CLOSED", "closed", "medium", now),
    ])
    page._apply_filters()
    assert page.proxy_model.rowCount() == 5
    assert page.results_label.text() == "Showing 5 of 5 cases"

    page.stat_cards["needs_attention"].clicked.emit()
    assert page.proxy_model.rowCount() == 1
    assert page.proxy_model.index(0, 0).data() == "CASE-OPEN-HIGH"
    assert "Needs attention" in page.results_label.text()

    page.stat_cards["active"].clicked.emit()
    assert page.proxy_model.rowCount() == 3  # open + active
    page.stat_cards["closed"].clicked.emit()
    assert page.proxy_model.rowCount() == 1
    assert page.proxy_model.index(0, 0).data() == "CASE-CLOSED"

    page.clear_filters()
    assert page.proxy_model.rowCount() == 5
    assert not page.clear_filters_btn.isEnabled()
    page.close()


def test_filtered_empty_state_explains_recovery(qt_app):
    from app.ui.pages.case_management_page import CaseManagementPage

    page = CaseManagementPage(nav_controller=None)
    now = datetime(2026, 1, 7, tzinfo=timezone.utc)
    page.table_model.populate([_case("CASE-01", "open", "medium", now)])
    page.search_edit.setText("does not exist")
    assert page.proxy_model.rowCount() == 0
    assert page.empty_title.text() == "No matching cases"
    assert page._empty_action_clears_filters
    assert page.empty_action_btn.text() == "Clear filters"

    page._on_empty_action()
    assert page.proxy_model.rowCount() == 1
    assert page.search_edit.text() == ""
    page.close()


def test_case_dates_sort_chronologically_not_by_displayed_text(qt_app):
    from PySide6.QtCore import Qt

    from app.ui.pages.case_management_page import CaseFilterProxyModel, CaseTableModel

    model = CaseTableModel()
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    model.populate([
        _case("CASE-NOV", "open", "medium", now.replace(month=11)),
        _case("CASE-FEB", "open", "medium", now.replace(month=2)),
        _case("CASE-JUL", "open", "medium", now.replace(month=7)),
    ])
    proxy = CaseFilterProxyModel()
    proxy.setSourceModel(model)
    proxy.sort(6, Qt.SortOrder.AscendingOrder)
    assert [
        proxy.index(row, 0).data() for row in range(proxy.rowCount())
    ] == ["CASE-FEB", "CASE-JUL", "CASE-NOV"]


def test_sign_out_clears_previous_users_case_rows(qt_app):
    from app.ui.pages.case_management_page import CaseManagementPage

    page = CaseManagementPage(nav_controller=None)
    now = datetime(2026, 1, 7, tzinfo=timezone.utc)
    page.table_model.populate([_case("PRIVATE-SYNTHETIC-CASE", "open", "high", now)])
    page._apply_filters()
    assert page.proxy_model.rowCount() == 1

    page.set_user(None)
    assert page.table_model.rowCount() == 0
    assert page.proxy_model.rowCount() == 0
    assert "Sign in" in page.empty_label.text()
    assert page.new_case_btn.isHidden()
    assert page.empty_action_btn.isHidden()
    page.close()
