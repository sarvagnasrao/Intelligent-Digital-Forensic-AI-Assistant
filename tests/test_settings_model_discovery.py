"""Model discovery never contacts a real provider or writes configuration."""
import threading
import time

import pytest

from app.config import AIConnectionConfig, AIModelConfig, Config


@pytest.fixture
def editor(qt_app, monkeypatch):
    from app.ui.pages import settings_page

    config = Config()
    config.ollama.chat_connections = [
        AIConnectionConfig(id="local", name="Local", provider="ollama",
                           base_url="http://localhost:11434",
                           models=[AIModelConfig(id="existing", enabled=True)]),
        AIConnectionConfig(id="cloud", name="Cloud", provider="openai",
                           base_url="https://example.test/v1", api_key="secret"),
    ]
    monkeypatch.setattr(settings_page, "get_config", lambda: config)
    monkeypatch.setattr(settings_page.SettingsPage, "_refresh_paths", lambda self: None)
    page = settings_page.SettingsPage()
    yield page, config, settings_page
    page.shutdown()


def finish(page, qt_app):
    deadline = time.monotonic() + 3
    while page._discovery_worker is not None and time.monotonic() < deadline:
        qt_app.processEvents()
        time.sleep(0.01)
    assert page._discovery_worker is None
    qt_app.processEvents()


@pytest.mark.parametrize("index,body,path", [
    (0, {"models": [{"name": "existing"}, {"name": "new"}]}, "/api/tags"),
    (1, {"data": [{"id": "new"}, {"id": "new"}]}, "/models"),
])
def test_discovery_is_explicit_and_adds_disabled(editor, qt_app, monkeypatch, index, body, path):
    from PySide6.QtCore import Qt

    page, config, module = editor
    calls = []
    class Response:
        status_code = 200
        def json(self):
            return body
    def get(url, **kwargs):
        calls.append((url, kwargs))
        return Response()
    monkeypatch.setattr(module.httpx, "get", get)
    page.connection_combo.setCurrentRow(index)
    if index:
        page.connection_key.setText("secret")
    assert not calls
    page.load_models_btn.click()
    finish(page, qt_app)
    assert calls[0][0].endswith(path)
    assert calls[0][1]["follow_redirects"] is False
    assert calls[0][1]["timeout"].read == 5.0
    assert calls[0][1]["headers"] == ({"Authorization": "Bearer secret"} if index else {})
    models = {page.connection_models.item(i).text(): page.connection_models.item(i).checkState()
              for i in range(page.connection_models.count())}
    assert models["new"] == Qt.CheckState.Unchecked
    if not index:
        assert models["existing"] == Qt.CheckState.Checked
    assert all(model.id != "new" for connection in config.ollama.chat_connections for model in connection.models)


def test_changed_selection_discards_inflight_result(editor, qt_app, monkeypatch):
    page, _, module = editor
    started = threading.Event()
    release = threading.Event()
    class Response:
        status_code = 200
        def json(self):
            return {"models": [{"name": "wrong"}]}
    def get(*args, **kwargs):
        started.set()
        release.wait(2)
        return Response()
    monkeypatch.setattr(module.httpx, "get", get)
    page.load_models_btn.click()
    assert started.wait(2)
    page.connection_combo.setCurrentRow(1)
    release.set()
    finish(page, qt_app)
    assert page.connection_models.count() == 0
    page.connection_combo.setCurrentRow(0)
    assert page.connection_models.count() == 1


def test_provider_error_does_not_echo_secrets(editor, qt_app, monkeypatch):
    page, _, module = editor
    page.connection_combo.setCurrentRow(1)
    page.connection_key.setText("secret")
    def get(*args, **kwargs):
        raise RuntimeError("secret provider response")
    monkeypatch.setattr(module.httpx, "get", get)
    page.load_models_btn.click()
    finish(page, qt_app)
    assert "secret" not in page.model_discovery_status.text()
    assert "Could not" in page.model_discovery_status.text()
