"""Ad-hoc checks for the data-folder bootstrap logic.

Run from the project root:

    .venv\\Scripts\\python.exe tests\\manual\\test_firstrun.py

Covers the paths the GUI depends on without opening any window: first-run
creation, folder validation, moving data, adopting a folder, portable YAML, and
reset behaviour. Temporary folders only; the real data folder is never touched.
"""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(WORKSPACE))

# Isolate the run from the user's real configuration.
_SANDBOX = Path(tempfile.mkdtemp(prefix="idfa_firstrun_"))
os.environ["IDFA_CONFIG_DIR"] = str(_SANDBOX / "config")

from app.config import (  # noqa: E402
    check_data_folder,
    default_config_path,
    describe_layout_paths,
    load_config,
    reset_config,
)
from app.firstrun import (  # noqa: E402
    MODE_ADOPT,
    MODE_FRESH,
    MODE_MOVE,
    apply_data_dir,
    needs_first_run,
    write_initial_config,
)

failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  ok   {label}")
    else:
        failures.append(f"{label} {detail}".strip())
        print(f"  FAIL {label} {detail}")


def _make_database(path: Path, marker: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE probes (value TEXT)")
    conn.execute("INSERT INTO probes VALUES (?)", (marker,))
    conn.commit()
    conn.close()


def _read_marker(path: Path) -> str | None:
    if not path.exists():
        return None
    conn = sqlite3.connect(str(path))
    try:
        row = conn.execute("SELECT value FROM probes").fetchone()
        return row[0] if row else None
    finally:
        conn.close()


print("first run")
check("no config yet", needs_first_run())
data_one = _SANDBOX / "data-one"
config = write_initial_config(data_one)
check("config written", default_config_path().exists())
check("data folder created", data_one.is_dir())
check("cases folder created", (data_one / "cases").is_dir())
check("no longer first run", not needs_first_run())
check(
    "secret replaced",
    config.auth.secret_key != "CHANGE_THIS_IN_PRODUCTION_USE_STRONG_RANDOM_KEY",
)

layout = describe_layout_paths(config)
check("database under data root", layout["database"] == (data_one / "idfa.db").as_posix())
check("logs under data root", layout["logs"] == (data_one / "logs").as_posix())

print("validation")
usable, reason = check_data_folder(_SANDBOX / "does-not-exist")
check("missing folder rejected", not usable)
check("reason mentions missing", "does not exist" in reason, reason)
usable, _ = check_data_folder(data_one)
check("existing folder accepted", usable)

print("portable YAML")
text = default_config_path().read_text(encoding="utf-8")
check("derived database url blank", "url: ''" in text)
check("explicit data_dir kept", f"data_dir: {data_one.as_posix()}" in text)
reloaded = load_config(default_config_path())
check(
    "reload derives same database",
    reloaded.database.url == f"sqlite:///{(data_one / 'idfa.db').as_posix()}",
    reloaded.database.url,
)

print("move")
_make_database(data_one / "idfa.db", "case-one")
(data_one / "cases" / "42").mkdir(parents=True, exist_ok=True)
(data_one / "cases" / "42" / "image.001").write_bytes(b"evidence-bytes")

data_two = _SANDBOX / "data-two"
apply_data_dir(config, data_two, MODE_MOVE)
check("database copied", _read_marker(data_two / "idfa.db") == "case-one")
evidence = (data_two / "cases" / "42" / "image.001")
check("evidence copied", evidence.read_bytes() == b"evidence-bytes")
check("old database kept", _read_marker(data_one / "idfa.db") == "case-one")
check("config points at new root", config.app.data_dir == data_two.as_posix())
check(
    "derived database followed",
    config.database.url.endswith("data-two/idfa.db"),
    config.database.url,
)

print("adopt")
data_three = _SANDBOX / "data-three"
_make_database(data_three / "idfa.db", "case-three")
apply_data_dir(config, data_three, MODE_ADOPT)
check("adopted database untouched", _read_marker(data_three / "idfa.db") == "case-three")
check("config points at adopted root", config.app.data_dir == data_three.as_posix())

print("fresh")
data_four = _SANDBOX / "data-four"
apply_data_dir(config, data_four, MODE_FRESH)
check("fresh folder created", (data_four / "cases").is_dir())
check("fresh has no database yet", not (data_four / "idfa.db").exists())

print("reset")
reset_config()
after_reset = load_config(default_config_path())
check("reset keeps data folder", after_reset.app.data_dir == data_four.as_posix())
check("reset restores defaults", after_reset.ui.refresh_interval_seconds == 30)
check("reset keeps derived database", after_reset.database.url.endswith("data-four/idfa.db"))

print("env override")
os.environ["APP__DATA_DIR"] = str(_SANDBOX / "from-env")
from app.config import reset_config as _reset  # noqa: E402

_reset()
env_config = load_config(default_config_path())
check("env data_dir wins", env_config.app.data_dir == (_SANDBOX / "from-env").as_posix())
del os.environ["APP__DATA_DIR"]

print()
if failures:
    print(f"{len(failures)} failure(s):")
    for item in failures:
        print(f"  - {item}")
    sys.exit(1)
print("all first-run checks passed")
