"""Isolated connection catalog persistence; never touches the user's config."""
import pytest

from app.config import Config, connection_api_key, load_config, save_config


def test_legacy_migration_and_explicit_empty():
    config = Config(ollama={"model": "local:v1", "cloud_model": "remote",
                            "cloud_api_key": "legacy"})
    local, cloud = config.ollama.chat_connections
    assert local.models[0].id == "local:v1"
    assert cloud.models[0].id == "remote"
    assert connection_api_key(cloud) == "legacy"
    assert Config(ollama={"chat_connections": []}).ollama.chat_connections == []


def test_catalog_round_trip_and_protection(tmp_path, monkeypatch):
    import app.config as config_module

    monkeypatch.setattr(config_module, "encrypt_secret", lambda s: "dpapi:" + s if s and not s.startswith("dpapi:") else s)
    monkeypatch.setattr(config_module, "decrypt_secret", lambda s: s.removeprefix("dpapi:"))
    config = Config(ollama={"chat_connections": [
        {"id": "a", "name": "A", "provider": "openai", "base_url": "https://example.test/v1",
         "api_key": "secret-one", "models": [{"id": "m1", "enabled": False}]},
        {"id": "b", "name": "B", "provider": "openai", "base_url": "https://other.test/v1",
         "api_key": "secret-two", "models": [{"id": "m2", "enabled": True}]},
    ]})
    path = tmp_path / "config.yaml"
    save_config(config, path)
    restored = load_config(path)
    assert [connection_api_key(c) for c in restored.ollama.chat_connections] == ["secret-one", "secret-two"]
    assert not restored.ollama.chat_connections[0].models[0].enabled
    assert "secret-one" not in repr(restored.ollama.chat_connections[0])


def test_failed_protection_does_not_write(tmp_path, monkeypatch):
    import app.config as config_module

    monkeypatch.setattr(config_module, "encrypt_secret", lambda s: s)
    config = Config(ollama={"chat_connections": [{"id": "a", "name": "A", "provider": "openai",
        "base_url": "https://example.test", "api_key": "secret"}]})
    path = tmp_path / "config.yaml"
    with pytest.raises(RuntimeError, match="DPAPI"):
        save_config(config, path)
    assert not path.exists()
