"""Embedding controls remain usable in the compact background settings."""
import os
from pathlib import Path

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QMessageBox

from app.config import Config
from app.ui.pages import settings_page
from app.ui.theme.manager import ThemeManager


def test_embedding_disclosures_and_persistence(qt_app, monkeypatch):
    config = Config()
    monkeypatch.setattr(settings_page, "get_config", lambda: config)
    monkeypatch.setattr(settings_page.SettingsPage, "_refresh_paths", lambda self: None)
    monkeypatch.setattr(settings_page.SettingsPage, "_update_services_timer", lambda self: None)
    saved = []
    monkeypatch.setattr(settings_page, "save_config", lambda value: saved.append(value))
    monkeypatch.setattr(QMessageBox, "information", lambda *args: None)
    page = settings_page.SettingsPage()
    page._switch_pane(1)
    page.show()
    qt_app.processEvents()
    assert page._embedding_advanced_content.isHidden()
    assert page._background_cloud_content.isHidden()
    page._embedding_advanced_toggle.setChecked(True)
    page.embedding_chunk_size.setValue(1500)
    page.embedding_chunk_overlap.setValue(200)
    page.embedding_batch_size.setValue(12)
    assert not page._embedding_advanced_content.isHidden()
    page._embedding_advanced_toggle.setChecked(False)
    page._background_cloud_toggle.setChecked(True)
    assert not page._background_cloud_content.isHidden()
    page._background_cloud_toggle.setChecked(False)
    page.embedding_provider.setCurrentIndex(page.embedding_provider.findData("openai"))
    assert not page._background_cloud_content.isHidden()
    assert "consent" in page.background_cloud_warning.text()
    page.embedding_provider.setCurrentIndex(page.embedding_provider.findData("ollama"))
    assert page._background_cloud_content.isHidden()
    page.analysis_provider.setCurrentIndex(page.analysis_provider.findData("openai"))
    assert not page._background_cloud_content.isHidden()
    page.analysis_provider.setCurrentIndex(page.analysis_provider.findData("ollama"))
    page._on_save()
    assert saved and (config.embeddings.chunk_size, config.embeddings.chunk_overlap,
                      config.embeddings.batch_size) == (1500, 200, 12)
    page.shutdown()
    page.close()


def test_embedding_dark_captures(qt_app, monkeypatch):
    monkeypatch.setattr(settings_page, "get_config", lambda: Config())
    monkeypatch.setattr(settings_page.SettingsPage, "_refresh_paths", lambda self: None)
    monkeypatch.setattr(settings_page.SettingsPage, "_update_services_timer", lambda self: None)
    page = settings_page.SettingsPage()
    ThemeManager().set_mode("dark")
    page._switch_pane(1)
    target = os.environ.get("IDFA_EMBEDDING_CAPTURE_DIR")
    for width in (1100, 600):
        page.resize(width, 850)
        page.show()
        qt_app.processEvents()
        scroll = page._panes[1][0]
        position = page.embedding_provider.mapTo(scroll.widget(), QPoint()).y()
        scroll.verticalScrollBar().setValue(position - 180)
        qt_app.processEvents()
        assert scroll.horizontalScrollBar().maximum() == 0
        if target:
            Path(target).mkdir(parents=True, exist_ok=True)
            assert page.grab().save(str(Path(target) / f"embedding-dark-{width}.png"))
    page.shutdown()
    page.close()
