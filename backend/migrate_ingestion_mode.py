"""Add the ingestion_mode column to ingestion_jobs.

Three profiles trade accuracy against time: 'fastest', 'normal' and
'accurate'. The profile is chosen when a file is queued and stored on the
job so the worker applies the same settings on every attempt - including
retries after a stop.

The column is nullable and backfilled to 'normal' rather than being added
NOT NULL: SQLite cannot add a column with a non-constant default, and rows
written before this migration exist. resolve_mode_for_device() already
treats NULL as 'normal', so the backfill is belt-and-braces that also makes
the value visible to ad-hoc SQL and reports.
"""
from backend.database import engine
from sqlalchemy import text

with engine.connect() as conn:
    # 1. Add the column if this is a database created before the column.
    try:
        conn.execute(text(
            "ALTER TABLE ingestion_jobs "
            "ADD COLUMN ingestion_mode VARCHAR(20)"
        ))
        print("Added ingestion_mode column")
    except Exception as e:
        print(f"ingestion_mode column: {e}")

    # 2. Backfill anything already queued so no job is left ambiguous.
    try:
        result = conn.execute(text(
            "UPDATE ingestion_jobs "
            "SET ingestion_mode = 'normal' "
            "WHERE ingestion_mode IS NULL"
        ))
        if result.rowcount:
            print(f"Backfilled {result.rowcount} existing job(s) to 'normal'")
    except Exception as e:
        print(f"ingestion_mode backfill: {e}")

    conn.commit()

print("Ingestion mode migration complete")
