"""
backend/migrate_all.py

Master migration script for IDF AI Assistant.
Runs every migration in the correct order.
Safe to re-run — already-applied migrations are skipped gracefully.

Usage:
    PYTHONPATH=. python3 backend/migrate_all.py
"""

import sys
import os
import importlib
import traceback

# This script prints box-drawing and check-mark characters. The default
# Windows console codepage is cp1252, which cannot encode them, so the
# banner raised UnicodeEncodeError before a single migration ran. Force
# UTF-8 on stdout (and reconfigure errors) so it works on Windows.
for _stream in ("stdout", "stderr"):
    try:
        getattr(sys, _stream).reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        # Python < 3.7, or a stream with no reconfigure (e.g. captured)
        pass

# Ensure the project root is on the path regardless of where
# this script is invoked from.
sys.path.insert(0, os.path.dirname(
    os.path.dirname(
        os.path.abspath(__file__))))

print()
print("╔══════════════════════════════════╗")
print("║  IDF AI Assistant — Migration Tool  ║")
print("╚══════════════════════════════════╝")
print()

ok = skip = error = 0

# Phrases that indicate the migration was already applied.
# All comparisons are done on the lower-cased exception message.
_SKIP_PHRASES = [
    "duplicate column",
    "already exists",
    "table already exists",
]


# ── Migration registry ────────────────────────────────────────────────────────
#
# Each module is imported fresh via importlib so its top-level code runs.
# The labels and module names are kept in parallel lists to preserve
# the human-readable names shown in the output.
#
# NOTE: this list is declared before step 1 runs so that `total` can be
# derived from it. A hard-coded count silently drifts out of date every
# time a migration is added (it read "[17/16]" once already).

MIGRATIONS = [
    (2,  "migrate_auth",                "backend.migrate_auth"),
    (3,  "migrate_queue",               "backend.migrate_queue"),
    (4,  "migrate_queue_fix",           "backend.migrate_queue_fix"),
    (5,  "migrate_security",            "backend.migrate_security"),
    (6,  "migrate_entropy",             "backend.migrate_entropy"),
    (7,  "migrate (anomaly columns)",   "backend.migrate"),
    (8,  "migrate_geo",                 "backend.migrate_geo"),
    (9,  "migrate_watchlist",           "backend.migrate_watchlist"),
    (10, "migrate_filestore",           "backend.migrate_filestore"),
    (11, "migrate_profiles",            "backend.migrate_profiles"),
    (12, "migrate_credentials",         "backend.migrate_credentials"),
    (13, "migrate_case_access",         "backend.migrate_case_access"),
    (14, "migrate_2fa",                 "backend.migrate_2fa"),
    (15, "migrate_audit_severity",      "backend.migrate_audit_severity"),
    (16, "migrate_final (create_all)",  "backend.migrate_final"),
    (17, "migrate_user_prefs",          "backend.migrate_user_prefs"),
    (18, "migrate_ingestion_mode",      "backend.migrate_ingestion_mode"),
    (19, "migrate_eta",                 "backend.migrate_eta"),
]

# Step 1 (init_db) plus everything in the registry.
total = 1 + len(MIGRATIONS)


def run_step(num: int, label: str, fn):
    """Run one migration step and update counters."""
    global ok, skip, error
    prefix = f"[{num:>2}/{total}]"
    try:
        fn()
        print(f"  \u2713  {prefix} {label}")
        ok += 1
    except Exception as e:
        msg = str(e).lower()
        if any(phrase in msg for phrase in _SKIP_PHRASES):
            print(f"  \u2500  {prefix} {label} \u2014 already applied")
            skip += 1
        else:
            print(f"  \u2717  {prefix} {label} \u2014 ERROR: {e}")
            error += 1


# ── Step 1 — init_db ──────────────────────────────────────────────────────────

def do_init_db():
    from backend.database import init_db
    init_db()

run_step(1, "init_db", do_init_db)


def make_fn(module_name: str):
    """Return a zero-argument function that imports the given module."""
    def fn():
        importlib.import_module(module_name)
    return fn


for num, label, module_name in MIGRATIONS:
    run_step(num, label, make_fn(module_name))

# ── Summary ───────────────────────────────────────────────────────────────────

print()
print(f"  Migration complete: "
      f"{ok} OK, {skip} already applied, {error} error(s)")

if error > 0:
    print()
    print("  \u26a0  Some migrations had errors.")
    print("  Check the output above and resolve before starting the app.")
    sys.exit(1)
else:
    print()
    print("  \u2713 Database is ready.")
    print()
