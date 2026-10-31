"""Alembic environment configuration."""
from __future__ import annotations

import os
import sys
from logging.config import fileConfig
from pathlib import Path

import sqlalchemy as sa
from alembic import context
from sqlalchemy import engine_from_config, pool

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.config import load_config
from app.db import Base, load_all_models

# Load all models to register with Base.metadata
load_all_models()

# Load config to get database URL. The URL comes from the per-user config so
# migrations always target the same database the application uses; an explicit
# ALEMBIC_DATABASE_URL still wins for one-off maintenance work.
config = load_config()
alembic_config = context.config
alembic_config.set_main_option(
    "sqlalchemy.url", os.environ.get("ALEMBIC_DATABASE_URL") or config.database.url
)

# Interpret the config file for Python logging
if alembic_config.config_file_name is not None:
    fileConfig(alembic_config.config_file_name)

target_metadata = Base.metadata
_migration_connection = None


def include_object(object_, name, type_, reflected, compare_to):
    """Exclude SQLite FTS5's virtual/shadow tables from schema comparison.

    FTS tables are created and maintained by ``app.db.session.ensure_fts_index``
    rather than SQLAlchemy metadata, and SQLite exposes their implementation
    tables as ordinary reflected tables. They are intentionally not migration
    targets.
    """
    if reflected and type_ == "table" and (
        name == "artifacts_fts" or name.startswith("artifacts_fts_")
    ):
        return False

    # The historical migrations use workload-specific composite indexes, while
    # create_all models also declare some of their leading-column indexes
    # individually. Treat an existing index with the same leading columns as
    # equivalent; do not hide indexes with different key order or columns.
    if type_ == "index" and _migration_connection is not None:
        index = object_ if not reflected else (compare_to or object_)
        table = getattr(index, "table", None)
        if table is not None:
            columns = tuple(column.name for column in index.columns)
            if columns:
                inspector = sa.inspect(_migration_connection)
                indexes = inspector.get_indexes(table.name)
                unique_constraints = inspector.get_unique_constraints(table.name)
                if reflected:
                    model_table = target_metadata.tables.get(table.name)
                    model_indexes = list(model_table.indexes) if model_table is not None else []
                    covered = any(
                        tuple(column.name for column in expected.columns) == columns
                        and (not expected.unique or index.unique)
                        for expected in model_indexes
                    )
                    covered |= bool(index.unique) and any(
                        tuple(constraint.get("column_names") or ()) == columns
                        for constraint in unique_constraints
                    )
                else:
                    covered = any(
                        tuple(existing.get("column_names") or ())[: len(columns)] == columns
                        and (not index.unique or existing.get("unique", False))
                        for existing in indexes
                    )
                    covered |= bool(index.unique) and any(
                        tuple(constraint.get("column_names") or ()) == columns
                        for constraint in unique_constraints
                    )
                if covered:
                    return False

    # SQLite reports legacy FK actions/name differences noisily. Ignore only
    # differences for the same local/remote column mapping; a missing or
    # differently-targeted FK remains visible to autogenerate.
    if type_ == "foreign_key_constraint" and _migration_connection is not None:
        candidate = object_ if not reflected else (compare_to or object_)
        table = getattr(candidate, "table", None)
        if table is not None:
            local = tuple(column.name for column in candidate.columns)
            remote_table = tuple(candidate.elements)[0].column.table.name
            remote = tuple(element.column.name for element in candidate.elements)
            model_table = target_metadata.tables.get(table.name)
            model_fks = model_table.foreign_key_constraints if model_table is not None else ()
            if any(
                tuple(column.name for column in fk.columns) == local
                and tuple(fk.elements)[0].column.table.name == remote_table
                and tuple(element.column.name for element in fk.elements) == remote
                for fk in model_fks
            ):
                return False

    # A UNIQUE constraint and a UNIQUE index enforce the same invariant. This
    # avoids SQLite reporting a drop/add pair when a migration and create_all
    # chose different DDL representations.
    if type_ == "unique_constraint" and _migration_connection is not None:
        candidate = object_ if not reflected else (compare_to or object_)
        table = getattr(candidate, "table", None)
        if table is not None:
            columns = tuple(column.name for column in candidate.columns)
            inspector = sa.inspect(_migration_connection)
            if any(
                tuple(index.get("column_names") or ()) == columns
                and index.get("unique", False)
                for index in inspector.get_indexes(table.name)
            ):
                return False
            if reflected:
                model_table = target_metadata.tables.get(table.name)
                if model_table is not None and any(
                    bool(index.unique)
                    and tuple(column.name for column in index.columns) == columns
                    for index in model_table.indexes
                ):
                    return False
    return True


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = alembic_config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    connectable = engine_from_config(
        alembic_config.get_section(alembic_config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        global _migration_connection
        _migration_connection = connection
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=include_object,
            # SQLite stores SQLAlchemy enums as VARCHAR and reports generic
            # affinities for several types. Comparing those dialect-level
            # representations against Python Enum/Float declarations produces
            # false-positive alterations; migrations remain authoritative for
            # actual column changes.
            compare_type=False,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
