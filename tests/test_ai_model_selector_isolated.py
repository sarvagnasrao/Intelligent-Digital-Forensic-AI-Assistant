import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app.ui.pages import ai_analysis_page as page


def test_selector_configured_models_and_refresh(monkeypatch):
    from app.config import AIConnectionConfig, AIModelConfig

    app = QApplication.instance() or QApplication([])
    config = page.get_config()
    monkeypatch.setattr(page, "cloud_api_key", lambda _: "secret")
    monkeypatch.setattr(config.ollama, "model", "local-test")
    monkeypatch.setattr(config.ollama, "cloud_model", "cloud-test")
    monkeypatch.setattr(config.ollama, "provider", "openai")
    monkeypatch.setattr(config.ollama, "chat_connections", [
        AIConnectionConfig(id="local", name="Local", provider="ollama",
                           base_url="http://127.0.0.1:11434",
                           models=[AIModelConfig(id="local-test"), AIModelConfig(id="local-two")]),
        AIConnectionConfig(id="cloud", name="Cloud", provider="openai",
                           base_url="https://example.invalid", api_key="secret",
                           models=[AIModelConfig(id="cloud-test")]),
    ])
    widget = page.AIAnalysisPage()
    widget.model_combo.setCurrentIndex(2)
    assert widget.model_combo.currentData() == ("cloud", "cloud-test")
    widget._refresh_models()
    assert widget.model_combo.currentData() == ("cloud", "cloud-test")
    config.ollama.chat_connections[1].enabled = False
    widget._refresh_models()
    assert widget.model_combo.count() == 2
    assert all(widget.model_combo.itemData(i)[0] == "local" for i in range(2))
    widget.close()
    assert app is not None


def test_model_selector_is_compact_below_prompt_and_before_send(qt_app):
    widget = page.AIAnalysisPage()
    widget.resize(1200, 800)
    widget.show()
    qt_app.processEvents()

    assert widget.model_combo.width() == 180
    prompt = widget.input_edit.mapTo(widget, widget.input_edit.rect().center())
    model = widget.model_combo.mapTo(widget, widget.model_combo.rect().center())
    send = widget.send_btn.mapTo(widget, widget.send_btn.rect().center())
    assert prompt.y() < model.y()
    assert model.x() < send.x()
    assert abs(send.y() - model.y()) <= 2
    widget.close()


def test_configured_cloud_model_is_selectable_without_discovery(monkeypatch, qt_app):
    from app.config import AIConnectionConfig, AIModelConfig

    config = page.get_config()
    monkeypatch.setattr(config.ollama, "cloud_model", "nim/custom-model")
    monkeypatch.setattr(config.ollama, "cloud_base_url", "https://example.invalid/v1")
    monkeypatch.setattr(config.ollama, "chat_connections", [
        AIConnectionConfig(id="nim", name="NVIDIA", provider="openai",
                           base_url="https://example.invalid/v1", api_key="secret",
                           models=[AIModelConfig(id="nim/custom-model")])
    ])
    monkeypatch.setattr(page, "cloud_api_key", lambda _: "secret")
    widget = page.AIAnalysisPage()
    widget._model_selection = ("nim", "nim/custom-model")
    widget._refresh_models()
    assert widget.model_combo.currentData() == ("nim", "nim/custom-model")
    assert "configured in Settings" in widget.model_combo.toolTip()
    widget.close()


def test_selected_provider_payload_and_consent(monkeypatch):
    config = page.get_config()
    monkeypatch.setattr(page, "cloud_api_key", lambda _: "secret")
    sent = []

    class Client:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def post(self, url, json):
            sent.append(json)
            return SimpleNamespace(status_code=200, json=lambda: {"success": True, "answer": "ok"})

    monkeypatch.setattr(page.httpx, "Client", Client)
    local = page.AskWorker(1, "hello", 1, provider="ollama", model="local-test")
    local._generate([], mode="conversation")
    assert (sent[-1]["provider"], sent[-1]["model"], sent[-1]["api_key"]) == ("ollama", "local-test", "")
    cloud = page.AskWorker(1, "hello", 2, conversation=True, provider="openai", model="cloud-test")
    results = []
    cloud.finished.connect(results.append)
    cloud.run()
    assert "consent" in results[0]["error"]
    assert len(sent) == 1
    cloud.cloud_consent = True
    cloud.run()
    assert sent[-1]["model"] == "cloud-test"
    assert sent[-1]["provider"] == "openai"
    assert sent[-1]["api_key"] == "secret"
