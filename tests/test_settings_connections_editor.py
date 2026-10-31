"""The chat connection editor operates on a draft until settings are saved."""
from app.config import AIConnectionConfig, AIModelConfig, Config


def test_provider_presets_fill_endpoint_without_changing_saved_connections(qt_app, monkeypatch):
    from app.ui.pages import settings_page

    config = Config()
    config.ollama.chat_connections = [AIConnectionConfig(
        id="nim", name="My NVIDIA", provider="openai",
        base_url="https://integrate.api.nvidia.com/v1", api_key="synthetic",
    )]
    monkeypatch.setattr(settings_page, "get_config", lambda: config)
    monkeypatch.setattr(settings_page.SettingsPage, "_refresh_paths", lambda self: None)
    page = settings_page.SettingsPage()
    assert page.connection_provider.currentText() == "NVIDIA NIM"
    assert page.connection_name.text() == "My NVIDIA"
    page.connection_provider.setCurrentIndex(2)
    assert page.connection_endpoint.text() == "https://api.openai.com/v1"
    assert config.ollama.chat_connections[0].name == "My NVIDIA"
    page.shutdown()
    page.close()


def test_connection_draft_and_save(qt_app, monkeypatch):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QMessageBox
    from app.ui.pages import settings_page

    config = Config()
    config.ollama.chat_connections = [AIConnectionConfig(
        id="local", name="Local", provider="ollama", base_url="http://localhost:11434",
        models=[AIModelConfig(id="first"), AIModelConfig(id="second", enabled=False)],
    )]
    saved = []
    monkeypatch.setattr(settings_page, "get_config", lambda: config)
    monkeypatch.setattr(settings_page, "save_config", lambda value: saved.append(value))
    monkeypatch.setattr(settings_page.SettingsPage, "_refresh_paths", lambda self: None)
    monkeypatch.setattr(QMessageBox, "information", lambda *args: None)
    page = settings_page.SettingsPage()
    assert not page.remove_connection_btn.isEnabled()
    page.connection_name.setText("Edited")
    page.connection_models.item(1).setCheckState(Qt.CheckState.Checked)
    assert config.ollama.chat_connections[0].name == "Local"
    page._on_save()
    assert saved and config.ollama.chat_connections[0].name == "Edited"
    assert config.ollama.chat_connections[0].models[1].enabled
    assert config.ollama.provider == "ollama"


def test_saved_model_toggles_control_chat_selector(qt_app, monkeypatch):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QMessageBox

    from app.ui.pages import ai_analysis_page, settings_page

    config = Config()
    config.ollama.chat_connections = [AIConnectionConfig(
        id="local", name="Local", provider="ollama", base_url="http://127.0.0.1:11434",
        models=[AIModelConfig(id="first"), AIModelConfig(id="second", enabled=False)],
    )]
    monkeypatch.setattr(settings_page, "get_config", lambda: config)
    monkeypatch.setattr(ai_analysis_page, "get_config", lambda: config)
    monkeypatch.setattr(settings_page, "save_config", lambda value: None)
    monkeypatch.setattr(settings_page.SettingsPage, "_refresh_paths", lambda self: None)
    monkeypatch.setattr(QMessageBox, "information", lambda *args: None)
    settings = settings_page.SettingsPage()
    settings.connection_model_filter.setText("second")
    assert settings.connection_models.item(0).isHidden()
    assert not settings.connection_models.item(1).isHidden()
    settings.connection_models.item(0).setCheckState(Qt.CheckState.Unchecked)
    settings.connection_models.item(1).setCheckState(Qt.CheckState.Checked)
    settings._on_save()

    chat = ai_analysis_page.AIAnalysisPage()
    assert chat.model_combo.count() == 1
    assert chat.model_combo.currentData() == ("local", "second")
    settings.shutdown()
    chat.shutdown()
    settings.close()
    chat.close()


def test_chat_hides_cloud_connection_without_key(qt_app, monkeypatch):
    from app.ui.pages import ai_analysis_page

    config = Config()
    config.ollama.chat_connections = [AIConnectionConfig(
        id="cloud", name="Cloud", provider="openai", base_url="https://example.invalid/v1",
        api_key="", models=[AIModelConfig(id="configured-model")],
    )]
    monkeypatch.setattr(ai_analysis_page, "get_config", lambda: config)
    chat = ai_analysis_page.AIAnalysisPage()
    assert chat.model_combo.currentData() is None
    assert chat.model_combo.currentText() == "No configured models"
    chat.shutdown()
    chat.close()


def test_background_selector_is_visible_without_changing_saved_provider(qt_app, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from app.ui.pages import settings_page

    config = Config()
    config.ollama.provider = "openai"
    config.ollama.cloud_api_key = "synthetic-key"
    monkeypatch.setattr(settings_page, "get_config", lambda: config)
    monkeypatch.setattr(settings_page, "cloud_api_key", lambda _: "synthetic-key")
    monkeypatch.setattr(settings_page, "save_config", lambda value: None)
    monkeypatch.setattr(settings_page.SettingsPage, "_refresh_paths", lambda self: None)
    monkeypatch.setattr(QMessageBox, "information", lambda *args: None)
    page = settings_page.SettingsPage()
    assert not page.analysis_provider.isHidden()
    assert page.analysis_provider.currentData() == "openai"
    assert not page.background_cloud_warning.isHidden()
    page._on_save()
    assert config.ollama.provider == "openai"
    page.shutdown()
    page.close()
