"""Synthetic status checks: no network or models are required."""
import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

from PySide6.QtWidgets import QApplication

from app.ui.pages.ai_analysis_page import AIAnalysisPage, StatusCheckWorker, StatusStrip


def config(embedding="ollama", chat="ollama"):
    return SimpleNamespace(
        worker=SimpleNamespace(url="http://worker"),
        ollama=SimpleNamespace(host="http://ollama", provider=chat, model="chat",
                               cloud_model="cloud", cloud_base_url="https://example.test"),
        embeddings=SimpleNamespace(provider=embedding, model_id="embed"),
        qdrant=SimpleNamespace(url="http://qdrant"),
    )


class Response:
    status_code = 200

    def __init__(self, value):
        self.value = value

    def json(self):
        if isinstance(self.value, Exception):
            raise self.value
        return self.value


def check(monkeypatch, health, tags=None, embedding="ollama", chat="ollama"):
    monkeypatch.setattr("app.ui.pages.ai_analysis_page.cloud_api_key", lambda _: "")
    responses = {"http://worker/health": Response(health),
                 "http://ollama/api/tags": Response(tags if tags is not None else {"models": []}),
                 "http://qdrant/collections": Response({"result": {"collections": []}})}
    monkeypatch.setattr(StatusCheckWorker, "_get", staticmethod(lambda _, url: responses.get(url)))
    return StatusCheckWorker(1)._service_status(config(embedding, chat), None)


def test_worker_health_contract(monkeypatch):
    good = dict(status="ok", pytsk3=True, pyewf=True, ollama=True, qdrant=True, embeddings=True)
    assert check(monkeypatch, good)["Worker"]["state"] == "ok"
    for invalid in (ValueError(), [], {}, {**good, "pyewf": 1}, {**good, "status": "bad"}):
        assert check(monkeypatch, invalid)["Worker"]["state"] == "unknown"
    for field in ("pytsk3", "pyewf", "ollama", "qdrant", "embeddings"):
        assert check(monkeypatch, {**good, field: False})["Worker"]["state"] == "partial"
    assert check(monkeypatch, {**good, "status": "degraded"})["Worker"]["state"] == "partial"


def test_embedding_action_only_for_confirmed_missing_local(monkeypatch):
    missing = check(monkeypatch, {}, {"models": []})["Embedding"]
    assert missing["pull_available"] is True
    assert check(monkeypatch, {}, {"models": [{"name": "embed:latest"}]})["Embedding"]["state"] == "ok"
    assert check(monkeypatch, {}, {"bad": []})["Embedding"]["state"] == "unknown"
    cloud = check(monkeypatch, {}, embedding="openai", chat="openai")
    assert cloud["Ollama"]["detail"] == "not needed"
    assert cloud["Embedding"]["detail"] == "API key missing"
    assert not cloud["Embedding"].get("pull_available")

    app = QApplication.instance() or QApplication([])
    strip = StatusStrip()
    owner = SimpleNamespace(_case_id=1, status_strip=strip,
                            status_hint=SimpleNamespace(setText=lambda _: None),
                            _status_summary=lambda _: "")
    AIAnalysisPage._on_status_checked(owner, {"case_id": 1, "Embedding": missing})
    assert not strip.download_embedding_btn.isHidden()
    AIAnalysisPage._on_status_checked(owner, {"case_id": 1, "Embedding": cloud["Embedding"]})
    assert strip.download_embedding_btn.isHidden()
    strip.set_status("Ollama", "ok", "not needed")
    strip.set_status("Model", "error", "missing")
    assert "not needed" in strip.services["Ollama"].accessibleName()
    assert "missing" in strip.services["Model"].text()
    strip.close()
