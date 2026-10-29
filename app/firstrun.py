"""First-run bootstrap and data-folder management.

The GUI needs a data folder before it can open a database, and it needs to ask
for one before the login screen appears. This module holds that decision logic
without importing Qt, so setup scripts and tests can drive the same code path
the dialogs use.
"""
from __future__ import annotations

import secrets
import shutil
import sqlite3
from collections.abc import Callable, Iterable
from pathlib import Path

from app.config import (
    Config,
    database_path,
    default_config_path,
    default_data_dir,
    describe_layout_paths,
    ensure_data_dirs,
    get_config,
    get_config_path,
    load_config,
    project_config_path,
    save_config,
    set_data_dir,
)

# How a new data folder relates to the existing one.
MODE_MOVE = "move"
MODE_ADOPT = "adopt"
MODE_FRESH = "fresh"

_PLACEHOLDER_SECRET = "CHANGE_THIS_IN_PRODUCTION_USE_STRONG_RANDOM_KEY"

ProgressCallback = Callable[[int, str], None]


def needs_first_run() -> bool:
    """True when this user has no configuration yet."""
    return not default_config_path().exists()


def import_legacy_config() -> bool:
    """Adopt a ``config.yaml`` left inside the project folder by an old build.

    Returns True when a config was copied. The original file is never modified
    or deleted, so rolling back is always possible.
    """
    target = default_config_path()
    source = project_config_path()
    if target.exists() or not source.exists():
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return True


def bootstrap_config() -> Config:
    """Load the user config, adopting a legacy one when present.

    This deliberately performs no validation and creates no directories: the
    caller decides how to react to a missing data folder.
    """
    import_legacy_config()
    return load_config()


def describe_layout(config: Config) -> list[tuple[str, str]]:
    """Return ``(label, absolute path)`` pairs for the paths a user should see."""
    paths = describe_layout_paths(config)
    return [
        ("Case data", paths["data"]),
        ("Database", paths["database"]),
        ("Logs", paths["logs"]),
        ("Evidence store", paths["evidence"]),
        ("Vector store", paths["vectors"]),
    ]


def _copy_sqlite_database(source: Path, destination: Path) -> None:
    """Copy a live SQLite database through its backup API.

    Copying the file directly can capture a database mid-write, or miss rows
    still sitting in the write-ahead log. ``Connection.backup`` produces a
    consistent snapshot and works while the app has the database open.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    source_conn = sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True)
    try:
        target_conn = sqlite3.connect(str(destination))
        try:
            source_conn.backup(target_conn)
        finally:
            target_conn.close()
    finally:
        source_conn.close()


def _count_files(root: Path) -> int:
    try:
        return sum(1 for entry in root.rglob("*") if entry.is_file())
    except OSError:
        return 0


def _copy_tree(source: Path, destination: Path, progress: ProgressCallback | None = None) -> None:
    """Copy ``source`` into ``destination``, writing to a staging folder first.

    A half-finished copy must never look like a complete evidence store, so the
    data is written to ``<destination>.part`` and only renamed once every file
    has arrived.
    """
    if not source.exists():
        return
    if source.resolve() == destination.resolve():
        return

    staging = destination.with_name(destination.name + ".part")
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True, exist_ok=True)

    total = _count_files(source)
    copied = 0
    for entry in source.rglob("*"):
        relative = entry.relative_to(source)
        target = staging / relative
        if entry.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(entry, target)
        copied += 1
        if progress and total:
            progress(min(99, int(copied * 100 / total)), f"Copying {relative.name}")

    if destination.exists():
        # Merge into an existing folder rather than replacing it: a user may
        # be consolidating two data roots.
        for entry in staging.rglob("*"):
            relative = entry.relative_to(staging)
            target = destination / relative
            if entry.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(entry), str(target))
        shutil.rmtree(staging, ignore_errors=True)
    else:
        staging.replace(destination)


def apply_data_dir(
    config: Config,
    path: str | Path,
    mode: str,
    progress: ProgressCallback | None = None,
) -> Config:
    """Move, adopt or initialise a data folder and persist the change.

    ``MODE_MOVE`` copies data and leaves the previous folder untouched, so a
    failed or unwanted move is always recoverable.
    """
    target = Path(path).expanduser()

    if mode == MODE_MOVE:
        source_cases = Path(config.worker.evidence_root_windows)
        source_db = database_path(config)
        target.mkdir(parents=True, exist_ok=True)

        new_db = target / "idfa.db"
        if source_db.exists() and source_db.resolve() != new_db.resolve():
            if progress:
                progress(0, "Copying database")
            _copy_sqlite_database(source_db, new_db)

        new_cases = target / "cases"
        if source_cases.exists() and source_cases.resolve() != new_cases.resolve():
            _copy_tree(source_cases, new_cases, progress)

    set_data_dir(config, target)
    ensure_data_dirs(config)
    ensure_secret_key(config)
    save_config(config)

    if progress:
        progress(100, "Done")
    return config


def ensure_secret_key(config: Config) -> Config:
    """Replace the shipped placeholder JWT secret with a per-install value."""
    if not config.auth.secret_key or config.auth.secret_key == _PLACEHOLDER_SECRET:
        config.auth.secret_key = secrets.token_urlsafe(48)
    return config


def write_initial_config(data_dir: str | Path) -> Config:
    """Create a configuration for a brand-new installation."""
    config = Config()
    set_data_dir(config, data_dir)
    ensure_secret_key(config)
    ensure_data_dirs(config)
    save_config(config)
    return config


def missing_layout_items(config: Config) -> list[tuple[str, str]]:
    """Return the layout entries that do not currently exist on disk."""
    return [
        (label, value)
        for label, value in describe_layout(config)
        if value and not Path(value).exists()
    ]


def suggested_data_dir() -> Path:
    """The folder offered as the default in the first-run screen."""
    return default_data_dir()


def current_data_dir() -> Path:
    """Where the running configuration keeps data today."""
    return Path(get_config().app.data_dir)


def config_location() -> Path:
    """Expose the config path for the Settings screen."""
    return get_config_path()


def ensure_layout(config: Config | None = None) -> Iterable[Path]:
    """Create the full data layout and return the directories that now exist."""
    active = config or get_config()
    ensure_data_dirs(active)
    return [Path(value) for _, value in describe_layout(active) if value]
