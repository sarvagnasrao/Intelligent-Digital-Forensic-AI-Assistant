"""Row architecture regression and optional reproducible offscreen captures.

Set IDFA_SETTINGS_CAPTURE_DIR to save synthetic dark/light captures. No HTTP,
model discovery, real configuration writes or process operations are performed.
"""
import os
from pathlib import Path

import pytest
from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QFrame, QMessageBox, QTabWidget

from app.config import AIConnectionConfig, AIModelConfig, Config
from app.ui.pages import settings_page
from app.ui.theme.manager import ThemeManager


@pytest.fixture
def page(qt_app, monkeypatch):
    config = Config()
    config.ollama.chat_connections = [AIConnectionConfig(
        id="local", name="This computer", provider="ollama",
        base_url="http://127.0.0.1:11434", models=[AIModelConfig(id="phi3:mini")]),
        AIConnectionConfig(id="demo", name="Review provider", provider="openai",
            base_url="https://example.invalid/v1", api_key="synthetic",
            models=[AIModelConfig(id="review-model", enabled=False)])]
    monkeypatch.setattr(settings_page, "get_config", lambda: config)
    monkeypatch.setattr(settings_page.SettingsPage, "_refresh_paths", lambda self: None)
    monkeypatch.setattr(settings_page.SettingsPage, "_update_services_timer", lambda self: None)
    monkeypatch.setattr(settings_page.httpx, "get", lambda *a, **k: pytest.fail("Unexpected HTTP"))
    widget = settings_page.SettingsPage()
    widget._apply_statuses([
        settings_page.services.ServiceStatus("worker", "Forensic worker", "http://127.0.0.1:8000",
            "running", "Running · managed by IDFA", owned=True),
        settings_page.services.ServiceStatus("qdrant", "Qdrant", "http://127.0.0.1:6333",
            "running", "Started outside IDFA", owned=False),
        settings_page.services.ServiceStatus("ollama", "Ollama", "http://127.0.0.1:11434",
            "stopped", "Stopped", owned=False),
    ])
    widget.data_dir_display.setText(r"C:\Synthetic IDFA\Data")
    for key, label in widget.path_labels.items():
        label.setText(f"C:/Synthetic IDFA/Data/{key}")
    widget.free_space_label.setText("Synthetic storage preview · no case data loaded")
    widget.resize(1200, 850)
    widget.show()
    yield widget, config
    widget.shutdown()
    widget.close()


def test_flat_content_sized_ai_and_drafts(page, qt_app):
    widget, config = page
    widget._switch_pane(1)
    qt_app.processEvents()
    assert widget._stack.count() == 5
    assert not widget.findChildren(QTabWidget)
    sections = [f for f in widget.findChildren(QFrame) if f.objectName() == "SettingsSection"]
    assert sections
    assert all(not s.property("card") for s in sections)
    assert widget.connection_combo.height() < 160
    assert widget.model_tree.height() < 220
    assert "127.0.0.1" in widget.connection_combo.item(0).text()
    assert "models enabled" in widget.connection_combo.item(1).text()
    assert not widget.remove_connection_btn.isEnabled()
    widget.connection_combo.setCurrentRow(1)
    assert widget.remove_connection_btn.isEnabled()
    widget.connection_name.setText("Draft only")
    assert config.ollama.chat_connections[1].name == "Review provider"
    assert not widget.analysis_provider.isHidden()
    widget.analysis_provider.setCurrentIndex(1)
    assert not widget._cloud_card.isHidden()
    assert not widget.background_cloud_warning.isHidden()


def test_save_preserves_separate_background_and_index_settings(page, monkeypatch):
    widget, config = page
    saved = []
    monkeypatch.setattr(settings_page, "save_config", lambda config: saved.append(config))
    monkeypatch.setattr(QMessageBox, "information", lambda *a: None)
    widget.embedding_chunk_size.setValue(1500)
    widget.embedding_chunk_overlap.setValue(150)
    widget.embedding_batch_size.setValue(12)
    widget._on_save()
    assert saved
    assert config.embeddings.chunk_size == 1500
    assert config.embeddings.chunk_overlap == 150
    assert config.embeddings.batch_size == 12
    assert config.ollama.provider == "ollama"
    assert len(config.ollama.chat_connections) == 2


def test_service_rows_preserve_ownership_and_compact_geometry(page, qt_app):
    widget, _ = page
    widget._switch_pane(2)
    qt_app.processEvents()
    rows = widget._service_rows
    assert rows["worker"]["stop"].isEnabled()
    assert not rows["qdrant"]["stop"].isEnabled()
    assert rows["ollama"]["start"].isEnabled()
    for row in rows.values():
        assert row["start"].parentWidget().height() < 140


def test_connection_add_remove_updates_always_visible_model_groups(page):
    widget, _ = page
    widget._add_connection()
    assert widget.model_tree.topLevelItemCount() == 3
    widget._remove_connection()
    assert widget.model_tree.topLevelItemCount() == 2
    widget.connection_combo.setCurrentRow(0)
    widget._remove_connection()
    assert widget.connection_combo.count() == 2


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_readable_offscreen_layout_and_captures(page, qt_app, theme):
    widget, _ = page
    ThemeManager().set_mode(theme)
    target = os.environ.get("IDFA_SETTINGS_CAPTURE_DIR")
    for index, (key, _) in enumerate(settings_page.NAV_ITEMS):
        widget._switch_pane(index)
        qt_app.processEvents()
        qt_app.processEvents()
        assert widget._panes[index][1].width() <= settings_page.CONTENT_MAX_WIDTH
        assert widget._panes[index][0].horizontalScrollBar().maximum() == 0
        if target:
            Path(target).mkdir(parents=True, exist_ok=True)
            assert widget.grab().save(str(Path(target) / f"settings-{key}-{theme}.png"))
    widget._switch_pane(1)
    widget._advanced_toggle.setChecked(True)
    qt_app.processEvents()
    scroll = widget._panes[1][0]
    scroll.verticalScrollBar().setValue(scroll.verticalScrollBar().maximum())
    qt_app.processEvents()
    if target:
        assert widget.grab().save(str(Path(target) / f"settings-ai-advanced-{theme}.png"))
    scroll.verticalScrollBar().setValue(0)
    widget.resize(600, 700)
    widget._switch_pane(1)
    qt_app.processEvents()
    for button in (widget.save_btn, widget.reset_btn, widget.remove_connection_btn):
        x = button.mapTo(widget, QPoint()).x()
        assert x >= 0
        assert x + button.width() <= widget.width()
    if target:
        assert widget.grab().save(str(Path(target) / f"settings-ai-{theme}-narrow.png"))
