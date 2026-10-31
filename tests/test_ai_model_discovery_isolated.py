import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app.ui.pages import ai_analysis_page as page


def test_discovery_only_requests_model_lists(monkeypatch):
    calls = []

    class Response:
        def __init__(self, data):
            self.data = data

        def raise_for_status(self):
            pass

        def json(self):
            return self.data

    def get(url, **kwargs):
        calls.append((url, kwargs))
        if url.endswith("/api/tags"):
            return Response({"models": [{"name": "one"}, {"name": "two"}]})
        return Response({"data": [{"id": "nvidia/model"}, {"id": "other"}]})

    monkeypatch.setattr(page.httpx, "get", get)
    worker = page.ModelDiscoveryWorker("http://local", "https://nim/v1", "secret")
    results = []
    worker.finished.connect(results.append)
    worker.run()
    assert results[0]["ollama"] == ["one", "two"]
    assert results[0]["openai"] == ["nvidia/model", "other"]
    assert [call[0] for call in calls] == ["http://local/api/tags", "https://nim/v1/models"]
    assert calls[1][1]["headers"] == {"Authorization": "Bearer secret"}
    assert all("json" not in kwargs for _, kwargs in calls)


def test_missing_key_and_sanitized_failure(monkeypatch):
    calls = []

    def fail(url, **kwargs):
        calls.append(url)
        raise RuntimeError("secret in exception")

    monkeypatch.setattr(page.httpx, "get", fail)
    worker = page.ModelDiscoveryWorker("http://local", "https://nim/v1", "")
    results = []
    worker.finished.connect(results.append)
    worker.run()
    assert calls == ["http://local/api/tags"]
    assert "secret" not in str(results)
    assert len(results[0]["errors"]) == 2


def test_selection_survives_refresh_and_removed_model(monkeypatch):
    from app.config import AIConnectionConfig, AIModelConfig

    app = QApplication.instance() or QApplication([])
    config = page.get_config()
    monkeypatch.setattr(page, "cloud_api_key", lambda _: "secret")
    monkeypatch.setattr(config.ollama, "chat_connections", [
        AIConnectionConfig(id="local", name="Local", provider="ollama",
                           base_url="http://127.0.0.1:11434",
                           models=[AIModelConfig(id="one"), AIModelConfig(id="two")]),
        AIConnectionConfig(id="nim", name="NVIDIA", provider="openai",
                           base_url="https://example.invalid/v1", api_key="secret",
                           models=[AIModelConfig(id="nvidia/model"), AIModelConfig(id="other")]),
    ])
    widget = page.AIAnalysisPage()
    widget._model_selection = ("nim", "nvidia/model")
    widget._refresh_models()
    assert widget.model_combo.currentData() == ("nim", "nvidia/model")
    config.ollama.chat_connections[1].models = [AIModelConfig(id="other")]
    widget._refresh_models()
    assert widget.model_combo.currentData() == ("local", "one")
    assert all(widget.model_combo.itemData(i) != ("nim", "nvidia/model")
               for i in range(widget.model_combo.count()))
    widget.shutdown()
    widget.close()
    assert app is not None
