from types import SimpleNamespace as NS

from app.ui.pages import ai_analysis_page as page


def test_connection_selector_filters_and_keeps_connection_identity(monkeypatch):
    connections = [
        NS(id="a", name="First", provider="openai", enabled=True, models=[NS(id="same", enabled=True), NS(id="off", enabled=False)]),
        NS(id="b", name="Second", provider="ollai", enabled=True, models=[NS(id="bad", enabled=True)]),
        NS(id="c", name="Third", provider="ollama", enabled=True, models=[NS(id="same", enabled=True)]),
        NS(id="d", name="Disabled", provider="openai", enabled=False, models=[NS(id="hidden", enabled=True)]),
    ]
    monkeypatch.setattr(page, "get_config", lambda: NS(ollama=NS(chat_connections=connections), embeddings=NS(provider="ollama")))
    monkeypatch.setattr(page, "connection_api_key", lambda connection: "secret")

    class Combo:
        def __init__(self): self.items = []; self.index = 0
        def blockSignals(self, value): pass
        def clear(self): self.items.clear()
        def addItem(self, text, data): self.items.append((text, data))
        def count(self): return len(self.items)
        def itemData(self, i): return self.items[i][1]
        def setCurrentIndex(self, i): self.index = i
        def currentData(self): return self.itemData(self.index)
        def setToolTip(self, text): pass

    combo = Combo()
    widget = NS(model_combo=combo, cloud_consent_check=NS(setVisible=lambda v: None),
                _model_shutting_down=False, _model_selection=None,
                _update_write_controls=lambda: None, nav=None)
    widget._remember_model_selection = lambda: setattr(widget, "_model_selection", combo.currentData())
    page.AIAnalysisPage._refresh_models(widget)
    assert combo.items == [("First — same", ("a", "same")), ("Third — same", ("c", "same"))]


def test_cloud_consent_and_explicit_endpoint_without_network(monkeypatch):
    config = NS(ollama=NS(provider="ollama", model="default", cloud_model="default", host="http://localhost:11434",
                          max_tokens=100, context_window_tokens=1024, timeout_seconds=10, temperature=0),
                search=NS(max_context_chunks=1, max_context_chars=1000), worker=NS(url="http://worker", timeout_seconds=10))
    monkeypatch.setattr(page, "get_config", lambda: config)
    sent = []
    class Client:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def post(self, url, json):
            sent.append(json)
            return NS(status_code=200, json=lambda: {"success": True, "answer": "ok"})
    monkeypatch.setattr(page.httpx, "Client", Client)
    worker = page.AskWorker(1, "hello", 1, conversation=True, provider="openai", model="m",
                            api_base_url="https://selected.invalid/v1", api_key="private")
    results = []
    worker.finished.connect(results.append)
    worker.run()
    assert not sent and "consent" in results[-1]["error"]
    worker.cloud_consent = True
    worker.run()
    assert sent[-1]["api_base_url"] == "https://selected.invalid/v1"
    assert sent[-1]["api_key"] == "private"
    local = page.AskWorker(1, "hello", 2, conversation=True, provider="ollama", model="m",
                           api_base_url="http://other:11434", api_key="private")
    local.finished.connect(results.append)
    local.run()
    assert len(sent) == 1 and "cannot yet route" in results[-1]["error"]
