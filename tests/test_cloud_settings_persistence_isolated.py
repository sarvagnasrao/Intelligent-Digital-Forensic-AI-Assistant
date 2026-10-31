"""Cloud settings persistence without real credentials or network access."""
import os
import subprocess
import sys

from PySide6.QtWidgets import QLabel, QMessageBox


def test_cloud_settings_survive_restart_and_mode_switch(config_home, qt_app, monkeypatch):
    from app.config import clear_config_cache
    from app.ui.pages.settings_page import SettingsPage

    monkeypatch.setattr(QMessageBox, "information", lambda *args: None)
    page = SettingsPage()
    page.set_ai_mode("openai")
    page.cloud_preset.setCurrentIndex(page.cloud_preset.findData("nim"))
    page.cloud_model.setCurrentText("synthetic/model")
    page.cloud_api_key.setText("synthetic-key-only")
    page._on_save()

    env = os.environ.copy()
    env["IDFA_CONFIG_DIR"] = str(config_home)
    code = (
        "from app.config import get_config, cloud_api_key; "
        "c=get_config(); "
        "assert c.ollama.provider == 'openai'; "
        "assert c.ollama.cloud_model == 'synthetic/model'; "
        "assert cloud_api_key(c) == 'synthetic-key-only'"
    )
    subprocess.run([sys.executable, "-c", code], env=env, check=True)
    clear_config_cache()
    reloaded = SettingsPage()
    assert reloaded.cloud_model.currentText() == "synthetic/model"
    assert reloaded.cloud_api_key.text() == "synthetic-key-only"
    reloaded.set_ai_mode("ollama")
    reloaded._on_save()
    clear_config_cache()
    offline = SettingsPage()
    offline.set_ai_mode("openai")
    assert offline.cloud_model.currentText() == "synthetic/model"
    assert offline.cloud_api_key.text() == "synthetic-key-only"
    offline._on_save()
    subprocess.run([sys.executable, "-c", code], env=env, check=True)
    assert any("Testing does not save" in label.text() for label in page.findChildren(QLabel))


def test_offline_save_preserves_unreadable_protected_key(config_home, qt_app, monkeypatch):
    from app.config import clear_config_cache, get_config, save_config
    from app.ui.pages.settings_page import SettingsPage

    monkeypatch.setattr(QMessageBox, "information", lambda *args: None)
    config = get_config()
    config.ollama.cloud_api_key = "dpapi:invalid-synthetic-value"
    save_config(config)
    page = SettingsPage()
    assert page.cloud_api_key.text() == ""
    page._on_save()
    clear_config_cache()
    assert get_config().ollama.cloud_api_key == "dpapi:invalid-synthetic-value"
    page.cloud_api_key.setText("synthetic-replacement")
    page._on_save()
    clear_config_cache()
    from app.config import cloud_api_key
    assert cloud_api_key(get_config()) == "synthetic-replacement"


def test_cloud_configuration_does_not_enable_background_providers(config_home, qt_app, monkeypatch):
    from app.config import clear_config_cache, get_config
    from app.ui.pages.settings_page import SettingsPage

    monkeypatch.setattr(QMessageBox, "information", lambda *args: None)
    page = SettingsPage()
    page.cloud_preset.setCurrentIndex(page.cloud_preset.findData("nim"))
    page.cloud_model.setCurrentText("synthetic/model")
    page.cloud_api_key.setText("synthetic-key-only")
    page._on_save()
    clear_config_cache()
    config = get_config()
    assert config.ollama.provider == "ollama"
    assert config.embeddings.provider == "ollama"
    assert config.ollama.cloud_model == "synthetic/model"
