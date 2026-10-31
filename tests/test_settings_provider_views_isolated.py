"""Provider selection and model views operate only on the settings draft."""
from PySide6.QtCore import Qt

from app.config import AIConnectionConfig, AIModelConfig, Config


def test_cloud_selection_and_grouped_model_toggles(qt_app, monkeypatch):
    from app.ui.pages import settings_page

    config = Config()
    config.ollama.chat_connections = [
        AIConnectionConfig(id="local", name="Local", provider="ollama",
                           base_url="http://localhost:11434",
                           models=[AIModelConfig(id="local-model")]),
        AIConnectionConfig(id="cloud", name="Cloud", provider="openai",
                           base_url="https://example.invalid/v1", api_key="key",
                           models=[AIModelConfig(id="cloud-model")]),
    ]
    monkeypatch.setattr(settings_page, "get_config", lambda: config)
    monkeypatch.setattr(settings_page.SettingsPage, "_refresh_paths", lambda self: None)
    page = settings_page.SettingsPage()
    page.connection_combo.setCurrentRow(1)
    assert page.connection_provider.currentData() == "openai"
    page.connection_combo.setCurrentRow(0)
    assert page._connections[1].provider == "openai"
    page._rebuild_model_tree()
    cloud_model = page.model_tree.topLevelItem(1).child(0)
    cloud_model.setCheckState(0, Qt.CheckState.Unchecked)
    assert not page._connections[1].models[0].enabled
    assert config.ollama.chat_connections[1].models[0].enabled
    page.connection_model_filter.setText("cloud")
    assert page.model_tree.topLevelItem(0).isHidden()
    assert not page.model_tree.topLevelItem(1).isHidden()
    page.shutdown()
    page.close()


def test_background_cloud_warning_names_selected_providers(qt_app, monkeypatch):
    from app.ui.pages import settings_page

    monkeypatch.setattr(settings_page, "get_config", lambda: Config())
    monkeypatch.setattr(settings_page.SettingsPage, "_refresh_paths", lambda self: None)
    page = settings_page.SettingsPage()
    for analysis, embedding in ((False, False), (True, False), (False, True), (True, True)):
        page.analysis_provider.setCurrentIndex(page.analysis_provider.findData("openai" if analysis else "ollama"))
        page.embedding_provider.setCurrentIndex(page.embedding_provider.findData("openai" if embedding else "ollama"))
        warning = page.background_cloud_warning
        assert warning.isHidden() == (not analysis and not embedding)
        if analysis or embedding:
            assert ("Background analysis" in warning.text()) == analysis
            assert ("embeddings" in warning.text()) == embedding
            assert "consent" in warning.text()
    page.shutdown()
    page.close()
