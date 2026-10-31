"""Schema creation and Alembic revision bookkeeping.

``init_db`` builds the schema with ``create_all``, so the database is always
ahead of what Alembic believes. If the recorded revision is not reconciled,
the next ``alembic upgrade head`` replays migrations against existing tables
and aborts. That happened on a real installation: the database was stamped
``001`` while the ``002`` table already existed.
"""
from __future__ import annotations

import pytest
from alembic.config import Config as AlembicConfig
from alembic.script import ScriptDirectory
from sqlalchemy import text

from tests.conftest import WORKSPACE

ALEMBIC_INI = WORKSPACE / "alembic.ini"


def head_revision() -> str:
    script = ScriptDirectory.from_config(AlembicConfig(str(ALEMBIC_INI)))
    revision = script.get_current_head()
    assert revision is not None
    return revision


@pytest.fixture
def database(config_home, data_dir):
    """A fresh data root with the app's own engine pointed at it."""
    from app import db as db_package
    from app.config import Config, save_config, set_data_dir
    from app.db import session as session_module

    save_config(set_data_dir(Config(), data_dir))
    db_package.load_all_models()

    # The engine is a module global; reset it so this test uses the new root.
    session_module._engine = None
    session_module._session_factory = None
    yield session_module
    if session_module._engine is not None:
        session_module._engine.dispose()
    session_module._engine = None
    session_module._session_factory = None


def recorded_revision(session_module) -> str:
    with session_module.get_engine().connect() as connection:
        return connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()


def test_init_db_creates_the_schema_and_records_head(database):
    database.init_db()

    assert recorded_revision(database) == head_revision()
    table_names = set(database.Base.metadata.tables)
    with database.get_engine().connect() as connection:
        existing = {
            row[0]
            for row in connection.execute(
                text("SELECT name FROM sqlite_master WHERE type='table'")
            )
        }
    assert table_names <= existing


def test_sqlite_connections_wait_for_brief_write_contention(database):
    with database.get_engine().connect() as connection:
        assert connection.exec_driver_sql("PRAGMA busy_timeout").scalar_one() == 30_000


def test_init_db_is_idempotent(database):
    database.init_db()
    database.init_db()

    assert recorded_revision(database) == head_revision()


def test_cleanup_indexes_are_restored_for_older_databases(database):
    database.init_db()
    engine = database.get_engine()
    with engine.begin() as connection:
        connection.exec_driver_sql("DROP INDEX IF EXISTS ix_timeline_events_entity_id")
        connection.exec_driver_sql("DROP INDEX IF EXISTS ix_artifacts_evidence_id")
    database._ensure_deletion_indexes()
    with engine.connect() as connection:
        indexes = {row[0] for row in connection.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='index'"
        )}
    assert {"ix_timeline_events_entity_id", "ix_artifacts_evidence_id"} <= indexes


def test_init_db_restores_indexes_on_existing_tables(database):
    database.init_db()
    with database.get_engine().begin() as connection:
        connection.exec_driver_sql("DROP INDEX IF EXISTS ix_entities_value")

    # create_all alone does not recreate indexes when their table already exists.
    database.init_db()

    with database.get_engine().connect() as connection:
        indexes = {
            row[0]
            for row in connection.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type='index'"
            )
        }
    assert "ix_entities_value" in indexes


def test_a_stale_revision_is_moved_to_head(database):
    """The failure seen in the field: schema at 002, revision says 001."""
    database.init_db()
    head = head_revision()
    with database.get_engine().begin() as connection:
        connection.execute(text("UPDATE alembic_version SET version_num = '001'"))

    database.init_db()

    assert head != "001"
    assert recorded_revision(database) == head


def test_alembic_upgrade_after_init_db_changes_nothing(database):
    """A packaged install runs ``alembic upgrade head``; it must be a no-op."""
    from alembic import command

    database.init_db()
    tables_before = _table_names(database)

    command.upgrade(AlembicConfig(str(ALEMBIC_INI)), "head")

    assert recorded_revision(database) == head_revision()
    assert _table_names(database) == tables_before


def _table_names(session_module) -> set[str]:
    with session_module.get_engine().connect() as connection:
        return {
            row[0]
            for row in connection.execute(
                text("SELECT name FROM sqlite_master WHERE type='table'")
            )
        }
