"""Failed services use the offline indicator without changing their status."""
from app.config import Config
from app.ui.pages import settings_page
from app.util.services import ServiceStatus


def test_failed_service_indicator_and_detail(qt_app, monkeypatch):
    monkeypatch.setattr(settings_page, "get_config", lambda: Config())
    monkeypatch.setattr(settings_page.SettingsPage, "_refresh_paths", lambda self: None)
    monkeypatch.setattr(settings_page.SettingsPage, "_update_services_timer", lambda self: None)
    page = settings_page.SettingsPage()
    status = ServiceStatus("qdrant", "Qdrant", "http://127.0.0.1:6333", "error", "Health check failed")
    page._apply_statuses([status])
    row = page._service_rows["qdrant"]
    assert row["dot"].property("serviceDot") == "stopped"
    assert row["state"].text() == "Health check failed"
    assert "error" in row["state"].toolTip()
    assert row["start"].isEnabled()
    assert not row["stop"].isEnabled()
    page.shutdown()
    page.close()
