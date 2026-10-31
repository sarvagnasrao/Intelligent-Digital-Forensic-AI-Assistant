import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLineEdit, QListWidget

from app.config import AIConnectionConfig, AIModelConfig
from app.ui.pages import ai_analysis_page as page


def test_picker_search_group_and_full_identity(monkeypatch, qt_app):
    config = page.get_config()
    long_name = "organization/" + "very-long-model-name-" * 8
    monkeypatch.setattr(config.ollama, "chat_connections", [
        AIConnectionConfig(id="a", name="Provider A", provider="openai",
                           base_url="https://example.invalid/v1", api_key="secret",
                           models=[AIModelConfig(id=long_name)]),
        AIConnectionConfig(id="b", name="Provider B", provider="openai",
                           base_url="https://example.invalid/v1", api_key="secret",
                           models=[AIModelConfig(id=long_name)]),
    ])
    widget = page.AIAnalysisPage()
    widget.model_combo.showPopup()
    popup = widget.model_combo._picker
    search = popup.findChild(QLineEdit)
    items = popup.findChild(QListWidget)
    assert items.count() == 4
    search.setText("provider b")
    assert items.count() == 2
    assert items.item(1).text() == long_name
    assert items.item(1).toolTip() == f"Provider B — {long_name}"
    items.itemClicked.emit(items.item(1))
    assert widget.model_combo.currentData() == ("b", long_name)
    assert long_name in widget.model_combo.toolTip()
    assert items.item(0).flags() == Qt.ItemFlag.NoItemFlags
    widget.close()
