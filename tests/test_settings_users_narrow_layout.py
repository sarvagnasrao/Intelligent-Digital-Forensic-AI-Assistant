"""Narrow-window regressions without starting services or accessing accounts."""
from pathlib import Path

from PySide6.QtGui import QFont

from app.auth.models import UserRole
from app.config import Config
from app.ui.pages import settings_page, user_management_page


def test_settings_can_shrink_after_being_wide(qt_app, monkeypatch):
    monkeypatch.setattr(settings_page, "get_config", lambda: Config())
    monkeypatch.setattr(settings_page.SettingsPage, "_refresh_paths", lambda self: None)
    monkeypatch.setattr(settings_page.SettingsPage, "_update_services_timer", lambda self: None)
    page = settings_page.SettingsPage()
    page.resize(1100, 700)
    page.show()
    qt_app.processEvents()
    page.resize(600, 700)
    qt_app.processEvents()
    assert page.width() == 600
    for index in (0, 1, 3, 4):
        page._switch_pane(index)
        qt_app.processEvents()
        scroll, column = page._panes[index]
        assert column.width() <= scroll.viewport().width()
    page.close()


def test_user_management_narrow_filters_and_actions(qt_app):
    page = user_management_page.UserManagementPage()
    page._rows = [user_management_page.UserRow(
        1, "analyst", "Example Analyst", "analyst@example.invalid", UserRole.ADMIN, True
    )]
    page._apply_filters()
    page.resize(600, 700)
    page.show()
    qt_app.processEvents()
    assert page.width() == 600
    page.search_edit.setText("analyst")
    page.table.selectRow(0)
    assert page._selected_row().username == "analyst"
    assert page.edit_btn.isEnabled()
    assert page.reset_password_btn.isEnabled()
    assert page.toggle_active_btn.isEnabled()
    page.close()


def test_user_management_narrow_with_theme_and_larger_font(qt_app):
    old_font, old_style = qt_app.font(), qt_app.styleSheet()
    page = None
    try:
        qt_app.setFont(QFont("Segoe UI", 11))
        qt_app.setStyleSheet(
            (Path(__file__).resolve().parents[1] / "app/ui/theme/professional.qss")
            .read_text(encoding="utf-8")
        )
        page = user_management_page.UserManagementPage()
        page._rows = [user_management_page.UserRow(
            1, "analyst", "Example Analyst", "analyst@example.invalid", UserRole.ADMIN, True
        )]
        page._apply_filters()
        page.resize(1100, 700)
        page.show()
        qt_app.processEvents()
        page.resize(600, 700)
        qt_app.processEvents()
        assert page.width() == 600
        page.role_filter.setCurrentIndex(1)
        page.status_filter.setCurrentIndex(1)
        page.table.selectRow(0)
        assert page._selected_row().username == "analyst"
        assert page.edit_btn.isEnabled()
        assert page.reset_password_btn.isEnabled()
        assert page.toggle_active_btn.isEnabled()
    finally:
        if page is not None:
            page.close()
        qt_app.setStyleSheet(old_style)
        qt_app.setFont(old_font)
