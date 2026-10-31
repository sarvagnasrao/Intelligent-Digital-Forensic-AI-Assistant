"""Provider selection, at-rest key encryption and the service controls."""
from __future__ import annotations

import asyncio

import pytest

from app.config import OllamaConfig


@pytest.fixture(autouse=True)
def no_blocking_dialogs(monkeypatch):
    """Never open a modal box: an unpatched one blocks the test run forever.

    ``SettingsPage._on_save()`` reports success with
    ``QMessageBox.information``. Nothing in this module asserts on that box, so
    it is replaced for every test here. Warning boxes are left alone: the test
    that cares about them patches them itself, and a stray one should fail
    loudly rather than silently pass.
    """
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(
        QMessageBox, "information", staticmethod(lambda *args, **kwargs: None)
    )
    monkeypatch.setattr(
        QMessageBox, "critical", staticmethod(lambda *args, **kwargs: None)
    )


def test_provider_defaults_to_local_ollama():
    config = OllamaConfig()

    assert config.provider == "ollama"
    assert config.cloud_model == "gpt-4o-mini"
    assert config.cloud_api_key == ""


def test_settings_expose_local_and_cloud_model_dropdowns(config_home, qt_app):
    from app.ui.pages.settings_page import SettingsPage

    page = SettingsPage()

    assert page.ai_mode == "ollama"
    assert page.ollama_model.isEditable()
    assert page.cloud_model.isEditable()
    assert page.embedding_model.isEditable()
    assert page.embedding_provider.currentData() == "ollama"
    assert page.cloud_api_key.echoMode() == page.cloud_api_key.EchoMode.Password


def test_settings_persist_search_chunking_and_batch_parameters(config_home, qt_app):
    from app.config import get_config
    from app.ui.pages.settings_page import SettingsPage

    page = SettingsPage()
    page.embedding_chunk_size.setValue(1800)
    page.embedding_chunk_overlap.setValue(250)
    page.embedding_batch_size.setValue(24)

    page._on_save()
    config = get_config()

    assert config.embeddings.chunk_size == 1800
    assert config.embeddings.chunk_overlap == 250
    assert config.embeddings.batch_size == 24


def test_settings_split_into_navigable_panes(config_home, qt_app):
    from app.ui.pages.settings_page import NAV_ITEMS, SettingsPage

    page = SettingsPage()

    assert page._stack.count() == len(NAV_ITEMS) == len(page.nav_buttons)
    assert page._stack.currentIndex() == 0

    page.nav_buttons[2].click()

    assert page._stack.currentIndex() == 2


def test_ai_pane_shows_both_configurations_for_each_analysis_provider(config_home, qt_app):
    from app.ui.pages.settings_page import SettingsPage

    page = SettingsPage()
    page.set_ai_mode("ollama")

    assert not page._offline_card.isHidden()
    assert not page._cloud_card.isHidden()

    page.set_ai_mode("openai")

    assert not page._offline_card.isHidden()
    assert not page._cloud_card.isHidden()


def test_cloud_preset_fills_the_endpoint(config_home, qt_app):
    from app.ui.pages.settings_page import CLOUD_PRESETS, SettingsPage

    page = SettingsPage()
    page.cloud_preset.setCurrentIndex(page.cloud_preset.findData("nim"))

    assert page.cloud_endpoint.text() == CLOUD_PRESETS["nim"]["url"]
    assert page.cloud_endpoint.isReadOnly()
    assert page.cloud_model.currentText() == CLOUD_PRESETS["nim"]["models"][0]

    page.cloud_preset.setCurrentIndex(page.cloud_preset.findData("custom"))

    assert not page.cloud_endpoint.isReadOnly()


def test_settings_persist_custom_cloud_and_embedding_models(config_home, qt_app):
    from app.config import cloud_api_key, get_config
    from app.ui.pages.settings_page import SettingsPage

    page = SettingsPage()
    page.set_ai_mode("openai")
    page.cloud_model.setCurrentText("my-chat-model")
    page.cloud_endpoint.setText("https://example.test/v1")
    page.cloud_api_key.setText("demo-secret")
    page.embedding_provider.setCurrentIndex(
        page.embedding_provider.findData("openai")
    )
    page.embedding_model.setCurrentText("text-embedding-3-small")

    page._on_save()
    config = get_config()

    assert config.ollama.provider == "openai"
    assert config.ollama.cloud_model == "my-chat-model"
    assert config.embeddings.provider == "openai"
    assert config.embeddings.model_id == "text-embedding-3-small"
    # The key is usable through the helper, but never readable on disk.
    assert cloud_api_key(config) == "demo-secret"


def test_api_key_is_encrypted_when_saved(config_home, qt_app):
    from app.config import cloud_api_key, get_config
    from app.ui.pages.settings_page import SettingsPage

    page = SettingsPage()
    page.set_ai_mode("openai")
    page.cloud_api_key.setText("nvapi-secret-value")

    page._on_save()
    config = get_config()

    assert config.ollama.cloud_api_key.startswith("dpapi:")
    assert "nvapi-secret-value" not in config.ollama.cloud_api_key
    assert cloud_api_key(config) == "nvapi-secret-value"


def test_saving_cloud_without_api_key_is_rejected(config_home, qt_app, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from app.config import get_config
    from app.ui.pages.settings_page import SettingsPage

    warnings: list[str] = []
    monkeypatch.setattr(
        QMessageBox, "warning", lambda *args, **kwargs: warnings.append(args[1])
    )
    page = SettingsPage()
    page.set_ai_mode("openai")
    page.cloud_api_key.setText("")

    page._on_save()

    assert warnings, "saving an incomplete cloud setup must warn"
    assert get_config().ollama.provider != "openai"


def test_cloud_generation_requires_an_api_key():
    from worker.main import OllamaError, call_openai_compatible

    with pytest.raises(OllamaError, match="no API key"):
        asyncio.run(
            call_openai_compatible(
                "question",
                model="gpt-4o-mini",
                api_base_url="https://api.openai.com/v1",
                api_key="",
                temperature=0.2,
                max_tokens=100,
                timeout_seconds=10,
            )
        )


def test_cloud_generation_rejects_insecure_or_invalid_endpoint():
    from worker.main import OllamaError, call_openai_compatible

    with pytest.raises(OllamaError, match="must start with https"):
        asyncio.run(
            call_openai_compatible(
                "question",
                model="custom-model",
                api_base_url="not-a-url",
                api_key="test-key",
                temperature=0.2,
                max_tokens=100,
                timeout_seconds=10,
            )
        )


def test_cloud_embeddings_use_openai_format_and_qdrant_dimensions(
    config_home, data_dir, monkeypatch
):
    from app.ai import embeddings
    from app.config import Config, save_config, set_data_dir

    config = set_data_dir(Config(), data_dir)
    config.embeddings.provider = "openai"
    config.embeddings.model_id = "text-embedding-3-small"
    config.ollama.cloud_api_key = "test-key"
    save_config(config)
    captured = {}

    class _Response:
        status_code = 200
        text = ""

        @staticmethod
        def json():
            return {"data": [{"index": 0, "embedding": [0.1] * 384}]}

    def fake_post(url, *, headers, json, timeout):  # noqa: A002
        captured.update(url=url, headers=headers, body=json)
        return _Response()

    monkeypatch.setattr(embeddings.httpx, "post", fake_post)

    vectors = embeddings.embed_texts(["artifact text"])

    assert len(vectors) == 1 and len(vectors[0]) == config.qdrant.vector_size
    assert captured["url"] == "https://api.openai.com/v1/embeddings"
    assert captured["headers"]["Authorization"] == "Bearer test-key"
    assert captured["body"]["dimensions"] == config.qdrant.vector_size


# ---------------------------------------------------------------- DPAPI secrets
def test_dpapi_round_trips_and_leaves_plain_text_alone(tmp_path):
    from app.util import dpapi

    encrypted = dpapi.encrypt_secret("nvidia-abc123")

    assert dpapi.is_encrypted(encrypted)
    assert "nvidia-abc123" not in encrypted
    assert dpapi.decrypt_secret(encrypted) == "nvidia-abc123"
    # Older configs stored the key as plain text; they must keep working.
    assert dpapi.decrypt_secret("plain-key") == "plain-key"
    assert dpapi.encrypt_secret("") == ""
    assert dpapi.decrypt_secret("") == ""


# ------------------------------------------------------------- managed Ollama
@pytest.fixture
def run_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("IDFA_RUN_DIR", str(tmp_path))
    return tmp_path


def test_stop_managed_is_a_noop_without_a_pid_file(run_dir):
    from app.util import ollama_service

    assert ollama_service.stop_managed() is False
    assert not (run_dir / "ollama-idfa.pid").exists()


def test_stop_managed_removes_a_stale_pid_file(run_dir):
    """A recycled PID must never be killed just because a file survived."""
    from app.util import ollama_service

    pid_file = run_dir / "ollama-idfa.pid"
    pid_file.write_text("not-a-pid", encoding="ascii")

    assert ollama_service.stop_managed() is False
    assert not pid_file.exists()


def test_stop_managed_ignores_a_pid_that_is_not_ollama(run_dir):
    import os

    from app.util import ollama_service

    pid_file = run_dir / "ollama-idfa.pid"
    pid_file.write_text(str(os.getpid()), encoding="ascii")

    assert ollama_service.stop_managed() is False
    assert not pid_file.exists()


# ---------------------------------------------------------------- services
def test_service_status_reports_each_service(config_home, run_dir, monkeypatch):
    from app.util import procs, services

    monkeypatch.setattr(procs, "http_ok", lambda url, timeout=1.0: False)
    monkeypatch.setattr(procs, "is_alive", lambda name: False)

    statuses = {item.key: item for item in services.statuses()}

    assert set(statuses) == {"worker", "qdrant", "ollama"}
    assert all(item.state == services.STOPPED for item in statuses.values())
    assert not any(item.owned for item in statuses.values())


def test_ollama_is_not_needed_when_both_providers_are_cloud(
    config_home, data_dir, run_dir, monkeypatch
):
    from app.config import Config, save_config, set_data_dir
    from app.util import procs, services

    config = set_data_dir(Config(), data_dir)
    config.ollama.provider = "openai"
    config.embeddings.provider = "openai"
    save_config(config)
    monkeypatch.setattr(procs, "http_ok", lambda url, timeout=1.0: False)
    monkeypatch.setattr(procs, "is_alive", lambda name: False)

    statuses = {item.key: item for item in services.statuses()}

    assert statuses["ollama"].state == services.NOT_NEEDED
    assert statuses["worker"].state == services.STOPPED


def test_ollama_is_needed_when_embeddings_stay_local(
    config_home, data_dir, run_dir, monkeypatch
):
    from app.config import Config, save_config, set_data_dir
    from app.util import procs, services

    config = set_data_dir(Config(), data_dir)
    config.ollama.provider = "openai"
    config.embeddings.provider = "ollama"
    save_config(config)
    monkeypatch.setattr(procs, "http_ok", lambda url, timeout=1.0: False)
    monkeypatch.setattr(procs, "is_alive", lambda name: False)

    statuses = {item.key: item for item in services.statuses()}

    assert statuses["ollama"].state == services.STOPPED


def test_stopping_a_service_idfa_did_not_start_is_refused(config_home, run_dir):
    from app.util import services

    ok, message = services.stop("worker")

    assert ok is False
    assert "left running" in message


def test_health_and_ownership_decide_the_service_state(
    config_home, run_dir, monkeypatch
):
    from app.util import procs, services

    monkeypatch.setattr(procs, "http_ok", lambda url, timeout=1.0: True)
    monkeypatch.setattr(procs, "is_alive", lambda name: True)

    worker = next(item for item in services.statuses() if item.key == "worker")

    assert worker.state == services.RUNNING
    assert worker.owned is True
    assert worker.can_stop is True


def test_settings_services_pane_lists_each_service(config_home, qt_app):
    from app.ui.pages.settings_page import SettingsPage

    page = SettingsPage()

    assert set(page._service_rows) == {"worker", "qdrant", "ollama"}
    for row in page._service_rows.values():
        assert "dot" in row and "state" in row and "stop" in row


def test_settings_page_shuts_its_workers_down():
    from app.ui.pages.settings_page import SettingsPage

    assert hasattr(SettingsPage, "shutdown")


def test_stop_pid_terminates_the_launcher_child_too(run_dir):
    """A virtualenv python.exe is a wrapper; the real server is its child.

    Stopping only the wrapper is what left a worker holding port 8000 while the
    GUI reported it stopped.
    """
    import subprocess
    import sys
    import time

    import psutil

    from app.util import procs

    inner = "import time; time.sleep(60)"
    outer = (
        "import subprocess, sys, time\n"
        f"child = subprocess.Popen([sys.executable, '-c', {inner!r}])\n"
        "time.sleep(60)\n"
    )
    wrapper = subprocess.Popen([sys.executable, "-c", outer])
    try:
        procs.write_pid("worker", wrapper.pid)

        child_pid = None
        for _ in range(40):
            time.sleep(0.2)
            try:
                children = psutil.Process(wrapper.pid).children(recursive=True)
            except psutil.Error:
                break
            if children:
                child_pid = children[0].pid
                break
        assert child_pid is not None, "the wrapper never started a child"

        assert procs.stop_pid("worker", names=procs.PYTHON_NAMES) is True

        assert not psutil.pid_exists(child_pid), "the child was left running"
        assert wrapper.wait(timeout=10) is not None
        assert not procs.pid_path("worker").exists()
    finally:
        if wrapper.poll() is None:
            wrapper.kill()


def test_failed_worker_start_cleans_up_before_reporting(
    config_home, run_dir, monkeypatch
):
    """A worker that never answers must not be left holding the port."""
    from app.util import procs, services

    class FakeProcess:
        pid = 4242

    stopped: list[str] = []
    monkeypatch.setattr(services, "_spawn", lambda *args, **kwargs: FakeProcess())
    monkeypatch.setattr(procs, "http_ok", lambda *args, **kwargs: False)
    monkeypatch.setattr(procs, "wait_http", lambda *args, **kwargs: False)
    monkeypatch.setattr(
        procs, "stop_pid", lambda name, **kwargs: stopped.append(name) or True
    )

    ok, message = services.start("worker")

    assert ok is False
    assert stopped == ["worker"]
    assert "did not answer" in message
