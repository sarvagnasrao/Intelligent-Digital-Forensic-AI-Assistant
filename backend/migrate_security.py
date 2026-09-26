"""
Security migration — adds failed_login_attempts
and locked_until columns to the users table.

Run with:
    python -m backend.migrate_security
or:
    cd IDFA_main3 && python backend/migrate_security.py
"""
from backend.database import engine
from sqlalchemy import text

print("Running security migration...")

with engine.connect() as conn:
    for col, definition in [
        ("failed_login_attempts", "INTEGER DEFAULT 0"),
        ("locked_until",          "DATETIME"),
    ]:
        try:
            conn.execute(text(
                f"ALTER TABLE users "
                f"ADD COLUMN {col} {definition}"
            ))
            print(f"  ✓ Added column: {col}")
        except Exception as e:
            # Column already exists — safe to ignore
            print(f"  ↷ {col}: {e}")
    conn.commit()

print("Security migration complete.")
