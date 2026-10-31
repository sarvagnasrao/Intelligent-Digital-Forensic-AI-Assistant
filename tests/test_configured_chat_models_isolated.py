"""Configured chat models, without provider requests or real settings."""
from PySide6.QtWidgets import QMessageBox


def test_legacy_model_migration():
    from app.config import OllamaConfig

    config = OllamaConfig(model="old-local", cloud_model="old-cloud")
    assert config.chat_local_models == ["old-local"]
    assert config.chat_cloud_models == ["old-cloud"]
    assert OllamaConfig(chat_local_models=[], chat_cloud_models=[]).chat_local_models == []


def test_settings_and_selector_roundtrip(config_home, qt_app, monkeypatch):
    from PySide6.QtCore import Qt
    from app.config import clear_config_cache, get_config
    from app.ui.pages import ai_analysis_page
    from app.ui.pages.settings_page import SettingsPage

    monkeypatch.setattr(QMessageBox, "information", lambda *args: None)
    settings = SettingsPage()
    settings.connection_models.clear()
    settings._append_model("local-one")
    settings._append_model("local-two")
    settings._append_model("local-three")
    settings.connection_combo.setCurrentRow(1)
    settings.connection_models.clear()
    settings._append_model("cloud-one")
    settings._append_model("cloud-two")
    settings.connection_key.setText("synthetic-key")
    settings._on_save()
    clear_config_cache()
    config = get_config()
    local, cloud = config.ollama.chat_connections
    assert [m.id for m in local.models] == ["local-one", "local-two", "local-three"]
    assert [m.id for m in cloud.models] == ["cloud-one", "cloud-two"]
    assert cloud.provider == "openai"
    assert cloud.api_key != "synthetic-key"

    widget = ai_analysis_page.AIAnalysisPage()
    widget._refresh_models()
    values = [widget.model_combo.itemData(i) for i in range(widget.model_combo.count())]
    assert values == [("local", "local-one"), ("local", "local-two"),
                      ("local", "local-three"), ("cloud", "cloud-one"),
                      ("cloud", "cloud-two")]
    assert not widget.cloud_consent_check.isChecked()
    settings = SettingsPage()
    settings.connection_models.item(1).setCheckState(Qt.CheckState.Unchecked)
    settings.connection_combo.setCurrentRow(1)
    settings.connection_models.item(1).setCheckState(Qt.CheckState.Unchecked)
    settings._on_save()
    clear_config_cache()
    widget._refresh_models()
    values = [widget.model_combo.itemData(i) for i in range(widget.model_combo.count())]
    assert ("local", "local-two") not in values
    assert ("cloud", "cloud-two") not in values
    assert ("cloud", "cloud-one") in values
    assert not get_config().ollama.chat_connections[1].models[1].enabled
    widget.shutdown()
    widget.close()
