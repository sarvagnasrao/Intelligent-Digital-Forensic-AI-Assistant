"""Configuration resolution: derived paths, portability, validation."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.config import (
    Config,
    check_data_folder,
    clear_config_cache,
    database_path,
    describe_layout_paths,
    embedding_model_name,
    folder_size_bytes,
    free_space_bytes,
    get_config,
    load_config,
    loopback_url,
    reset_config,
    save_config,
    set_data_dir,
)


def test_legacy_embedding_model_is_migrated():
    assert embedding_model_name("sentence-transformers/all-MiniLM-L6-v2") == "all-minilm"
    assert embedding_model_name("all-MiniLM-L6-v2") == "all-minilm"
    assert embedding_model_name("") == "all-minilm"
    assert embedding_model_name("nomic-embed-text") == "nomic-embed-text"


def test_embedding_chunk_configuration_is_validated():
    from pydantic import ValidationError

    from app.config import EmbeddingConfig

    config = EmbeddingConfig(chunk_size=2400, chunk_overlap=300)
    assert config.chunk_size == 2400
    assert config.chunk_overlap == 300
    with pytest.raises(ValidationError):
        EmbeddingConfig(chunk_size=1000, chunk_overlap=1000)


def test_localhost_is_normalised():
    assert loopback_url("http://localhost:8000") == "http://127.0.0.1:8000"
    assert loopback_url("http://localhost") == "http://127.0.0.1"
    assert loopback_url("https://localhost:6333/") == "https://127.0.0.1:6333/"
    assert loopback_url("http://example.test:8000") == "http://example.test:8000"


def test_an_old_config_is_upgraded_on_load(config_home):
    """Existing configs keep working without hand editing."""
    config_home.mkdir(parents=True, exist_ok=True)
    (config_home / "config.yaml").write_text(
        "worker:\n  url: http://localhost:8000\n"
        "ollama:\n  host: http://localhost:11434\n"
        "embeddings:\n  model_id: sentence-transformers/all-MiniLM-L6-v2\n",
        encoding="utf-8",
    )
    clear_config_cache()
    try:
        config = load_config()
    finally:
        clear_config_cache()

    assert config.worker.url == "http://127.0.0.1:8000"
    assert config.ollama.host == "http://127.0.0.1:11434"
    assert config.embeddings.model_id == "all-minilm"


def test_defaults_derive_from_data_dir(data_dir):
    config = set_data_dir(Config(), data_dir)

    assert config.database.url == f"sqlite:///{(data_dir / 'idfa.db').as_posix()}"
    assert config.app.logs_dir == (data_dir / "logs").as_posix()
    assert config.worker.evidence_root_windows == (data_dir / "cases").as_posix()
    assert config.qdrant.storage_path == (data_dir / "qdrant").as_posix()


def test_database_path_matches_url(data_dir):
    config = set_data_dir(Config(), data_dir)

    assert database_path(config) == data_dir / "idfa.db"


def test_layout_lists_every_derived_path(data_dir):
    config = set_data_dir(Config(), data_dir)

    layout = describe_layout_paths(config)
    assert set(layout) == {"data", "database", "logs", "evidence", "vectors"}
    assert layout["data"] == Path(data_dir).as_posix()
    assert layout["database"].endswith("idfa.db")
    assert layout["evidence"].endswith("cases")


def test_saved_config_only_pins_the_data_dir(config_home, data_dir):
    """Derived paths must not be written, or the file stops being portable."""
    config = set_data_dir(Config(), data_dir)
    save_config(config)

    text = (config_home / "config.yaml").read_text(encoding="utf-8")
    assert f"data_dir: {Path(data_dir).as_posix()}" in text
    assert "logs_dir: ''" in text
    assert "url: ''" in text
    assert "evidence_root_windows: ''" in text
    assert "storage_path: ''" in text

    reloaded = load_config(config_home / "config.yaml")
    assert reloaded.database.url == config.database.url
    assert reloaded.app.logs_dir == config.app.logs_dir


def test_custom_paths_are_preserved(config_home, data_dir, tmp_path):
    """A deliberately customised path is explicit, so keep it."""
    custom_logs = tmp_path / "custom-logs"
    config = set_data_dir(Config(), data_dir)
    config.app.logs_dir = custom_logs.as_posix()
    save_config(config)

    reloaded = load_config(config_home / "config.yaml")
    assert Path(reloaded.app.logs_dir) == custom_logs
    assert reloaded.database.url == f"sqlite:///{(data_dir / 'idfa.db').as_posix()}"


def test_env_override_wins(config_home, tmp_path):
    os.environ["APP__DATA_DIR"] = str(tmp_path / "from-env")
    try:
        clear_config_cache()
        config = load_config()
        assert config.app.data_dir == (tmp_path / "from-env").as_posix()
    finally:
        del os.environ["APP__DATA_DIR"]
        clear_config_cache()


def test_missing_folder_is_rejected(tmp_path):
    usable, reason = check_data_folder(tmp_path / "nope")
    assert usable is False
    assert "does not exist" in reason


def test_file_is_not_a_folder(tmp_path):
    target = tmp_path / "a-file"
    target.write_text("x", encoding="utf-8")
    usable, reason = check_data_folder(target)
    assert usable is False
    assert "not a folder" in reason


def test_writable_folder_is_accepted(data_dir):
    usable, reason = check_data_folder(data_dir)
    assert usable is True
    assert reason == ""
    # The probe file must not be left behind.
    assert not (data_dir / ".idfa_write_test").exists()


def test_reset_keeps_the_data_folder(config_home, data_dir):
    config = set_data_dir(Config(), data_dir)
    config.ui.refresh_interval_seconds = 999
    save_config(config)

    reset_config()
    reloaded = load_config(config_home / "config.yaml")

    assert reloaded.app.data_dir == Path(data_dir).as_posix()
    assert reloaded.database.url.endswith("idfa.db")
    assert reloaded.ui.refresh_interval_seconds == 30


def test_folder_size_and_free_space(data_dir):
    (data_dir / "a.bin").write_bytes(b"x" * 100)
    (data_dir / "nested").mkdir()
    (data_dir / "nested" / "b.bin").write_bytes(b"y" * 50)

    assert folder_size_bytes(data_dir) == 150
    free = free_space_bytes(data_dir)
    assert free is None or free > 0


def test_get_config_returns_cached_instance(config_home, data_dir):
    config = Config()
    config.app.data_dir = str(data_dir)
    save_config(config)

    clear_config_cache()
    first = get_config()
    second = get_config()
    assert first is second
