"""Add the eta_seconds column to ingestion_jobs.

The worker rewrites this on every progress frame from the live tracker in
backend/modules/eta.py, so /queue/list can report a countdown that moves
instead of only the queue-time estimate it was seeded with.

The column is nullable and there is no backfill, which is the point. A job
that has never produced a defensible estimate has no estimate, and 0 would
be a fabricated claim that it has no time remaining. NULL is the honest
value and the UI renders it as an em dash.

That is also why the column cannot be NOT NULL DEFAULT 0: SQLite cannot
ALTER TABLE ADD COLUMN with a non-constant default, and rows written
before this migration exist. Identical trap and identical reason to
migrate_ingestion_mode.py.
"""
from backend.database import engine
from sqlalchemy import text

with engine.connect() as conn:
    # 1. Add the column if this is a database created before the column.
    #    The try/except is what makes re-running this a no-op: a second
    #    run gets "duplicate column name" from SQLite, prints the reason
    #    and carries on rather than aborting the whole migration run.
    try:
        conn.execute(text(
            "ALTER TABLE ingestion_jobs "
            "ADD COLUMN eta_seconds INTEGER"
        ))
        print("Added eta_seconds column")
    except Exception as e:
        print(f"eta_seconds column: {e}")

    # 2. No backfill, deliberately. Every existing row is left NULL, which
    #    is the correct value: a job that last ran before this column
    #    existed has no live estimate, and elapsed_seconds already carries
    #    what the worker can honestly say about how long it took. Writing
    #    0 here would put a fake "no time remaining" on rows the UI shows.

    conn.commit()

print("ETA migration complete")
