"""Settings guidance and provider actions remain reachable at narrow widths."""
from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QMessageBox

from app.config import Config
from app.ui.pages import settings_page


def test_narrow_guidance_and_provider_actions(qt_app, monkeypatch):
    monkeypatch.setattr(settings_page, "get_config", lambda: Config())
    monkeypatch.setattr(settings_page.SettingsPage, "_refresh_paths", lambda self: None)
    monkeypatch.setattr(settings_page.SettingsPage, "_update_services_timer", lambda self: None)
    messages = []
    monkeypatch.setattr(QMessageBox, "information", lambda *args: messages.append(args))
    page = settings_page.SettingsPage()
    page.resize(600, 700)
    page.show()
    page._switch_pane(1)
    qt_app.processEvents()
    assert page.width() == 600
    assert page._footer_help.isVisible()
    page._footer_help.click()
    assert all(word in messages[0][2] for word in ("Save", "immediately", "restart"))
    for button in (page._footer_help, page.reset_btn, page.save_btn):
        pos = button.mapTo(page, QPoint(0, 0))
        assert 0 <= pos.x() and pos.x() + button.width() <= page.width()
        assert button.width() >= button.fontMetrics().horizontalAdvance(button.text()) + 16
    button = page.remove_connection_btn
    parent = button.parentWidget()
    pos = button.mapTo(parent, QPoint(0, 0))
    assert button.isVisible()
    assert pos.x() >= 0 and pos.x() + button.width() <= parent.width()
    page.resize(1100, 700)
    qt_app.processEvents()
    assert page._footer_hint.isVisible()
    assert not page._footer_help.isVisible()
    page.shutdown()
    page.close()
