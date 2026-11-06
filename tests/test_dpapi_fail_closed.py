"""Secrets must never be written in plaintext when Windows DPAPI fails."""
from __future__ import annotations

import pytest

from app.util import dpapi


def test_dpapi_failure_raises_instead_of_returning_plaintext(monkeypatch):
    monkeypatch.setattr(dpapi.sys, "platform", "win32")

    def fail(_data: bytes) -> bytes:
        raise OSError("synthetic DPAPI failure")

    monkeypatch.setattr(dpapi, "_protect", fail)

    with pytest.raises(RuntimeError, match="DPAPI"):
        dpapi.encrypt_secret("secret-that-must-not-leak")


def test_dpapi_success_returns_only_encrypted_representation(monkeypatch):
    monkeypatch.setattr(dpapi.sys, "platform", "win32")
    monkeypatch.setattr(dpapi, "_protect", lambda _: b"synthetic-protected-bytes")

    value = dpapi.encrypt_secret("sensitive-value")
    assert value.startswith(dpapi.PREFIX)
    assert value != "sensitive-value"


def test_legacy_cloud_secret_fail_closed_before_config_write(tmp_path, monkeypatch):
    import app.config as config_module

    monkeypatch.setattr(config_module, "encrypt_secret", lambda value: value)
    config = config_module.Config(ollama={"cloud_api_key": "old-plaintext-key"})
    target = tmp_path / "config.yaml"
    target.write_text("previous: config\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="legacy cloud AI key"):
        config_module.save_config(config, target)

    assert target.read_text(encoding="utf-8") == "previous: config\n"


def test_plaintext_legacy_cloud_secret_cannot_be_written_to_new_config(tmp_path, monkeypatch):
    import app.config as config_module

    monkeypatch.setattr(config_module, "encrypt_secret", lambda value: value)
    config = config_module.Config(ollama={"cloud_api_key": "old-plaintext-key"})
    target = tmp_path / "new-config.yaml"

    with pytest.raises(RuntimeError, match="DPAPI"):
        config_module.save_config(config, target)

    assert not target.exists()
