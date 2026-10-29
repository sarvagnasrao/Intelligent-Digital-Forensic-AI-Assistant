"""First-run bootstrap and data-folder moves."""
from __future__ import annotations

import sqlite3

import pytest

from app.config import clear_config_cache, load_config
from app.firstrun import (
    MODE_ADOPT,
    MODE_FRESH,
    MODE_MOVE,
    apply_data_dir,
    bootstrap_config,
    import_legacy_config,
    needs_first_run,
    set_data_dir,
    write_initial_config,
)


def _make_database(path, marker: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(path))
    try:
        connection.execute("CREATE TABLE probes (value TEXT)")
        connection.execute("INSERT INTO probes VALUES (?)", (marker,))
        connection.commit()
    finally:
        connection.close()


def _read_marker(path) -> str | None:
    if not path.exists():
        return None
    connection = sqlite3.connect(str(path))
    try:
        row = connection.execute("SELECT value FROM probes").fetchone()
        return row[0] if row else None
    finally:
        connection.close()


def test_first_run_creates_layout_and_secret(config_home, data_dir):
    assert needs_first_run() is True

    config = write_initial_config(data_dir)

    assert needs_first_run() is False
    assert (data_dir / "cases").is_dir()
    assert (data_dir / "logs").is_dir()
    assert config.auth.secret_key != "CHANGE_THIS_IN_PRODUCTION_USE_STRONG_RANDOM_KEY"
    assert config.database.url.endswith("idfa.db")


def test_bootstrap_adopts_an_existing_config(config_home, data_dir):
    config = write_initial_config(data_dir)
    clear_config_cache()

    reloaded = bootstrap_config()
    assert reloaded.app.data_dir == config.app.data_dir
    assert reloaded.database.url == config.database.url


def test_move_copies_database_and_evidence(config_home, data_dir, tmp_path):
    config = write_initial_config(data_dir)
    _make_database(data_dir / "idfa.db", "case-one")
    evidence = data_dir / "cases" / "42" / "image.001"
    evidence.parent.mkdir(parents=True)
    evidence.write_bytes(b"evidence-bytes")

    target = tmp_path / "moved"
    apply_data_dir(config, target, MODE_MOVE)

    assert _read_marker(target / "idfa.db") == "case-one"
    assert (target / "cases" / "42" / "image.001").read_bytes() == b"evidence-bytes"
    # The source is never removed: a move must be reversible.
    assert _read_marker(data_dir / "idfa.db") == "case-one"
    assert config.app.data_dir == target.as_posix()
    assert config.database.url == f"sqlite:///{(target / 'idfa.db').as_posix()}"


def test_move_uses_a_consistent_snapshot(config_home, data_dir, tmp_path):
    """A committed row must arrive even though the copy is of a live database."""
    config = write_initial_config(data_dir)
    database = data_dir / "idfa.db"
    _make_database(database, "alpha")

    # Keep a writer open while the move copies, mimicking a running app.
    connection = sqlite3.connect(str(database))
    try:
        connection.execute("INSERT INTO probes VALUES ('beta')")
        connection.commit()

        target = tmp_path / "snapshot"
        apply_data_dir(config, target, MODE_MOVE)

        copied = sqlite3.connect(str(target / "idfa.db"))
        try:
            values = [row[0] for row in copied.execute("SELECT value FROM probes")]
        finally:
            copied.close()
    finally:
        connection.close()

    assert sorted(values) == ["alpha", "beta"]


def test_adopt_leaves_existing_data_alone(config_home, data_dir, tmp_path):
    config = write_initial_config(data_dir)
    existing = tmp_path / "existing"
    _make_database(existing / "idfa.db", "case-three")

    apply_data_dir(config, existing, MODE_ADOPT)

    assert _read_marker(existing / "idfa.db") == "case-three"
    assert config.app.data_dir == existing.as_posix()


def test_fresh_creates_an_empty_layout(config_home, data_dir, tmp_path):
    config = write_initial_config(data_dir)
    target = tmp_path / "fresh"

    apply_data_dir(config, target, MODE_FRESH)

    assert (target / "cases").is_dir()
    assert not (target / "idfa.db").exists()
    assert config.app.data_dir == target.as_posix()


def test_set_data_dir_recomputes_every_path(config_home, data_dir, tmp_path):
    config = write_initial_config(data_dir)
    new_root = tmp_path / "other"

    set_data_dir(config, new_root)

    assert config.database.url == f"sqlite:///{(new_root / 'idfa.db').as_posix()}"
    assert config.app.logs_dir == (new_root / "logs").as_posix()
    assert config.worker.evidence_root_windows == (new_root / "cases").as_posix()
    assert config.qdrant.storage_path == (new_root / "qdrant").as_posix()


def test_legacy_config_is_copied_into_place(config_home, tmp_path, monkeypatch):
    from app import firstrun

    legacy = tmp_path / "repo" / "config.yaml"
    legacy.parent.mkdir(parents=True)
    legacy.write_text(
        "app:\n  data_dir: " + (tmp_path / "legacy-data").as_posix() + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(firstrun, "project_config_path", lambda: legacy)

    assert import_legacy_config() is True
    assert (config_home / "config.yaml").is_file()
    # The source file must survive, so a rollback is always possible.
    assert legacy.is_file()

    config = load_config()
    assert config.app.data_dir == (tmp_path / "legacy-data").as_posix()


def test_import_legacy_is_a_no_op_when_a_config_exists(
    config_home, data_dir, tmp_path, monkeypatch
):
    from app import firstrun

    write_initial_config(data_dir)
    legacy = tmp_path / "config.yaml"
    legacy.write_text("app:\n  data_dir: E:/elsewhere\n", encoding="utf-8")
    monkeypatch.setattr(firstrun, "project_config_path", lambda: legacy)

    assert import_legacy_config() is False
    assert load_config().app.data_dir == data_dir.as_posix()


@pytest.mark.parametrize("mode", [MODE_MOVE, MODE_ADOPT, MODE_FRESH])
def test_mode_constants_are_stable(mode):
    assert mode in {"move", "adopt", "fresh"}
