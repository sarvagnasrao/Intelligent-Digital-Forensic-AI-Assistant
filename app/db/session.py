"""Database base and session management."""
from __future__ import annotations

import logging
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_config
from app.db.base import Base

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    """Get or create the database engine."""
    global _engine

    if _engine is not None:
        return _engine

    config = get_config()
    db_url = config.database.url

    # Ensure SQLite directory exists
    if db_url.startswith("sqlite:///"):
        db_path = db_url.replace("sqlite:///", "")
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    _engine = create_engine(
        db_url,
        echo=config.database.echo,
        pool_pre_ping=config.database.pool_pre_ping,
        connect_args=(
            {"check_same_thread": False, "timeout": 30.0}
            if "sqlite" in db_url else {}
        ),
    )

    # Enable foreign keys for SQLite
    if "sqlite" in db_url:

        @event.listens_for(_engine, "connect")
        def set_sqlite_pragma(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            # SQLite still has one writer at a time, including in WAL mode.
            # Wait for short progress/audit writes instead of failing a user
            # action immediately with "database is locked".
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.close()

    return _engine


def get_session_factory() -> sessionmaker[Session]:
    """Get or create the session factory."""
    global _session_factory

    if _session_factory is not None:
        return _session_factory

    _session_factory = sessionmaker(
        bind=get_engine(),
        class_=Session,
        expire_on_commit=False,
        autoflush=False,
    )
    return _session_factory


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    """Provide a transactional scope around a series of operations."""
    session_factory = get_session_factory()
    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db() -> None:
    """Initialize database - create all tables."""
    Base.metadata.create_all(bind=get_engine())
    try:
        _ensure_model_indexes()
    except Exception:
        logging.getLogger(__name__).warning(
            "Could not reconcile model indexes", exc_info=True
        )
    # create_all only creates missing tables; it never adds columns to a table
    # that already exists, so a database from an earlier build keeps its old
    # columns. Reconcile the few columns added since the initial schema.
    try:
        _ensure_columns()
    except Exception:
        logging.getLogger(__name__).warning(
            "Could not reconcile database columns", exc_info=True
        )
    try:
        _ensure_deletion_indexes()
    except Exception:
        logging.getLogger(__name__).warning(
            "Could not reconcile evidence cleanup indexes", exc_info=True
        )
    # The FTS table lives outside the SQLAlchemy metadata (it is a virtual
    # table), and the migration that creates it never installed triggers or
    # filled it, so keyword search returned nothing for examined artifacts.
    try:
        ensure_fts_index()
    except Exception:  # FTS5 missing must not stop the app from starting
        logging.getLogger(__name__).warning(
            "FTS5 keyword index could not be initialised", exc_info=True
        )
    # A database built by create_all has the current schema but no revision
    # history, so a later ``alembic upgrade`` would try to create tables that
    # already exist. Record the revision that the schema now represents.
    try:
        _sync_alembic_revision()
    except Exception:
        logging.getLogger(__name__).warning(
            "Could not record the Alembic revision", exc_info=True
        )


def _ensure_columns() -> None:
    """Add columns introduced after a database was first created.

    SQLite supports ``ALTER TABLE ... ADD COLUMN``, which is all that is needed
    here: every added column is nullable, so existing rows stay valid. Doing it
    on startup keeps a working installation upgradeable without asking the
    investigator to run a migration by hand.
    """
    from sqlalchemy import inspect, text

    engine = get_engine()
    inspector = inspect(engine)
    additions_by_table = {
        "evidence": (
            ("removed_at", "DATETIME"),
            ("removed_by_id", "INTEGER"),
            ("removal_reason", "VARCHAR(512)"),
        ),
        "cases": (
            ("cloud_ai_consent_at", "DATETIME"),
            ("cloud_ai_consent_by_id", "INTEGER"),
        ),
    }
    with engine.begin() as connection:
        for table, additions in additions_by_table.items():
            if table not in inspector.get_table_names():
                continue
            existing = {column["name"] for column in inspector.get_columns(table)}
            missing = [(name, kind) for name, kind in additions if name not in existing]
            for name, kind in missing:
                connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {kind}"))
            if missing:
                logging.getLogger(__name__).info(
                    "Added %s columns: %s", table, ", ".join(name for name, _ in missing)
                )


def _ensure_deletion_indexes() -> None:
    """Repair indexes missing from older databases used by artifact cleanup."""
    from sqlalchemy import inspect, text

    engine = get_engine()
    if engine.dialect.name != "sqlite":
        return
    indexes = (
        ("ix_entities_artifact_id", "entities", "artifact_id"),
        ("ix_timeline_events_artifact_id", "timeline_events", "artifact_id"),
        ("ix_timeline_events_entity_id", "timeline_events", "entity_id"),
        ("ix_finding_artifact_links_artifact_id", "finding_artifact_links", "artifact_id"),
        ("ix_artifacts_evidence_id", "artifacts", "evidence_id"),
        ("ix_artifacts_examination_job_id", "artifacts", "examination_job_id"),
    )
    tables = set(inspect(engine).get_table_names())
    with engine.begin() as connection:
        for name, table, column in indexes:
            if table in tables:
                connection.execute(text(f"CREATE INDEX IF NOT EXISTS {name} ON {table} ({column})"))


def _ensure_model_indexes() -> None:
    """Create metadata indexes missing from tables in older SQLite databases.

    ``MetaData.create_all`` skips indexes when their table already exists. As
    a result, an application startup could stamp a newly-added migration as
    current without actually installing that revision's indexes. ``checkfirst``
    makes this safe for fresh databases and repeated startups.
    """
    engine = get_engine()
    if engine.dialect.name != "sqlite":
        return
    for table in Base.metadata.sorted_tables:
        for index in table.indexes:
            try:
                index.create(bind=engine, checkfirst=True)
            except Exception:
                logging.getLogger(__name__).warning(
                    "Could not create index %s on %s",
                    index.name,
                    table.name,
                    exc_info=True,
                )


def _sync_alembic_revision() -> None:
    """Point ``alembic_version`` at the schema that now exists.

    ``create_all`` is what builds the schema here, so once it has run the
    database already has every table the models declare. Alembic still has to
    be told, or the next ``alembic upgrade head`` replays migrations whose
    tables exist and aborts with "table ... already exists".

    Two cases are handled:

    * no revision table at all - a fresh install or a database from before
      Alembic was introduced - so stamp head;
    * an older revision, for example ``001`` on a database whose ``002`` table
      was created by ``create_all`` - stamp head as well.
    """
    from alembic import command
    from alembic.config import Config as AlembicConfig
    from alembic.script import ScriptDirectory
    from sqlalchemy import inspect

    config_path = Path(__file__).resolve().parents[2] / "alembic.ini"
    if not config_path.is_file():
        return

    alembic_config = AlembicConfig(str(config_path))
    head = ScriptDirectory.from_config(alembic_config).get_current_head()

    engine = get_engine()
    has_version_table = "alembic_version" in inspect(engine).get_table_names()
    current = None
    if has_version_table:
        with engine.connect() as connection:
            row = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).fetchone()
        current = row[0] if row else None

    if current == head:
        return

    if current is not None:
        logging.getLogger(__name__).info(
            "Database schema is already current; moving Alembic from %s to %s",
            current,
            head,
        )
    command.stamp(alembic_config, "head")


_FTS_TABLE_SQL = """
    CREATE VIRTUAL TABLE IF NOT EXISTS artifacts_fts USING fts5(
        artifact_id, case_id, content_text, name, source_path,
        content='artifacts', content_rowid='id'
    )
"""

# External-content FTS5 needs explicit delete-then-insert rows to stay in
# sync; these triggers keep keyword search working as artifacts are added.
_FTS_TRIGGER_SQL = (
    """
    CREATE TRIGGER artifacts_fts_ai AFTER INSERT ON artifacts BEGIN
        INSERT INTO artifacts_fts(
            rowid, artifact_id, case_id, content_text, name, source_path
        ) VALUES (
            new.id, new.artifact_id, new.case_id, new.content_text,
            new.name, new.source_path
        );
    END
    """,
    """
    CREATE TRIGGER artifacts_fts_ad AFTER DELETE ON artifacts BEGIN
        INSERT INTO artifacts_fts(
            artifacts_fts, rowid, artifact_id, case_id, content_text,
            name, source_path
        ) VALUES (
            'delete', old.id, old.artifact_id, old.case_id,
            old.content_text, old.name, old.source_path
        );
    END
    """,
    """
    CREATE TRIGGER artifacts_fts_au
    AFTER UPDATE OF artifact_id, case_id, content_text, name, source_path
    ON artifacts BEGIN
        INSERT INTO artifacts_fts(
            artifacts_fts, rowid, artifact_id, case_id, content_text,
            name, source_path
        ) VALUES (
            'delete', old.id, old.artifact_id, old.case_id,
            old.content_text, old.name, old.source_path
        );
        INSERT INTO artifacts_fts(
            rowid, artifact_id, case_id, content_text, name, source_path
        ) VALUES (
            new.id, new.artifact_id, new.case_id, new.content_text,
            new.name, new.source_path
        );
    END
    """,
)


def ensure_fts_index() -> None:
    """Create the FTS5 keyword index, its triggers, and fill it once.

    Safe to call repeatedly: the table and triggers are idempotent, and rows
    are only rebuilt when the triggers are installed for the first time.
    """
    with get_engine().begin() as connection:
        connection.execute(text(_FTS_TABLE_SQL))
        installed = connection.execute(
            text(
                "SELECT 1 FROM sqlite_master "
                "WHERE type = 'trigger' AND name = 'artifacts_fts_ai'"
            )
        ).first() is not None
        for name in ("artifacts_fts_ai", "artifacts_fts_ad", "artifacts_fts_au"):
            connection.execute(text(f"DROP TRIGGER IF EXISTS {name}"))
        for statement in _FTS_TRIGGER_SQL:
            connection.execute(text(statement))
        if not installed:
            # Backfill artifacts that were examined before the triggers
            # existed. 'rebuild' reads the content table.
            connection.execute(
                text("INSERT INTO artifacts_fts(artifacts_fts) VALUES('rebuild')")
            )


def drop_db() -> None:
    """Drop all tables (use with caution)."""
    Base.metadata.drop_all(bind=get_engine())


def close_db() -> None:
    """Close database connections."""
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
        _engine = None
    _session_factory = None
