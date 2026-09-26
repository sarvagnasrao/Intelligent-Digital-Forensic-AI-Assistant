"""Add a per-user "show system resources" preference.

Investigators who do not care about CPU/RAM telemetry can switch the
System Resources panel off in Settings > Preferences. Existing users keep
the panel, so the default is ON (1) - the column is added with
DEFAULT 1 NOT NULL rather than a nullable tri-state.
"""
from backend.database import engine
from sqlalchemy import text

with engine.connect() as conn:
    try:
        conn.execute(text(
            "ALTER TABLE user_preferences "
            "ADD COLUMN show_system_resources BOOLEAN NOT NULL DEFAULT 1"
        ))
        print("Added show_system_resources")
    except Exception as e:
        print(f"show_system_resources: {e}")
    conn.commit()
print("User preferences migration complete")
