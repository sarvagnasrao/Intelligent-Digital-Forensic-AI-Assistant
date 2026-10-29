"""Process and endpoint helpers shared by the GUI service controls.

The launcher scripts record every process they start in
``%LOCALAPPDATA%\\IDFA\\run\\<name>.pid``. The GUI uses the same files, so
``STOP_IDFA.bat`` can clean up whatever Settings started and neither side ever
kills a process it does not own.

Set ``IDFA_RUN_DIR`` to point the PID files somewhere else; the test suite uses
it to stay out of the real per-user run directory.
"""
from __future__ import annotations

import os
from pathlib import Path

import httpx

PYTHON_NAMES = frozenset({"python.exe", "pythonw.exe", "python", "pythonw"})
OLLAMA_NAMES = frozenset({"ollama.exe", "ollama"})
QDRANT_NAMES = frozenset({"qdrant.exe", "qdrant"})


def run_dir() -> Path:
    override = os.environ.get("IDFA_RUN_DIR")
    if override:
        return Path(override)
    local = os.environ.get("LOCALAPPDATA")
    root = Path(local) if local else Path.home() / "AppData" / "Local"
    return root / "IDFA" / "run"


def pid_path(name: str) -> Path:
    return run_dir() / f"{name}.pid"


def write_pid(name: str, process_id: int) -> None:
    run_dir().mkdir(parents=True, exist_ok=True)
    pid_path(name).write_text(str(int(process_id)), encoding="ascii")


def read_pid(name: str) -> int | None:
    """The recorded PID, or ``None`` when the file is missing or unreadable."""
    try:
        text = pid_path(name).read_text(encoding="ascii").strip()
    except OSError:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def clear_pid(name: str) -> None:
    pid_path(name).unlink(missing_ok=True)


def is_alive(name: str) -> bool:
    """True when the recorded PID exists and is still running."""
    process_id = read_pid(name)
    if process_id is None:
        return False
    try:
        import psutil

        return psutil.pid_exists(process_id) and psutil.Process(process_id).is_running()
    except Exception:
        return False


def http_ok(url: str, timeout: float = 1.0) -> bool:
    try:
        return httpx.get(url, timeout=timeout).status_code == 200
    except Exception:
        return False


def wait_http(url: str, seconds: float = 30.0, interval: float = 0.5) -> bool:
    """Poll ``url`` until it answers 200 or the timeout expires."""
    waited = 0.0
    while waited <= seconds:
        if http_ok(url):
            return True
        import time

        time.sleep(interval)
        waited += interval
    return False


def wait_down(url: str, seconds: float = 10.0, interval: float = 0.5) -> bool:
    """Poll ``url`` until it stops answering, e.g. after terminating a service."""
    waited = 0.0
    while waited <= seconds:
        if not http_ok(url):
            return True
        import time

        time.sleep(interval)
        waited += interval
    return False


def listener_pid(port: int) -> int | None:
    """The process actually accepting connections on ``port``.

    A virtual environment's ``python.exe`` is a launcher that starts the real
    interpreter as a child, so the PID returned by ``Popen`` is not the process
    that serves requests. Recording the listener keeps "started by IDFA"
    accurate and makes Stop kill the server rather than its wrapper.
    """
    try:
        import psutil

        for connection in psutil.net_connections(kind="inet"):
            if connection.status != psutil.CONN_LISTEN:
                continue
            if connection.laddr and connection.laddr.port == port and connection.pid:
                return connection.pid
    except Exception:
        return None
    return None


def stop_pid(name: str, *, names: frozenset[str], path_prefix: str = "") -> bool:
    """Terminate the process recorded for ``name`` if it is the expected one.

    A recycled PID or a leftover file must never cost an unrelated process its
    life, so the executable name (and optionally its path) is checked first.
    Launcher wrappers are handled by taking their matching children with them;
    without that, stopping a virtual environment's interpreter leaves the real
    server holding its port.
    """
    process_id = read_pid(name)
    if process_id is None:
        # The file is missing or unreadable. Clear it either way: a leftover
        # nobody can parse would otherwise stay forever and keep reporting a
        # service that can never be stopped.
        clear_pid(name)
        return False
    wanted = {item.casefold() for item in names}
    try:
        import psutil

        process = psutil.Process(process_id)
        if process.name().casefold() not in wanted:
            return False
        if path_prefix and path_prefix.casefold() not in process.exe().casefold():
            return False

        targets = [process]
        for child in process.children(recursive=True):
            try:
                if child.name().casefold() in wanted:
                    targets.append(child)
            except psutil.Error:
                continue

        for item in targets:
            try:
                item.terminate()
            except psutil.Error:
                pass
        _, alive = psutil.wait_procs(targets, timeout=5)
        for item in alive:
            try:
                item.kill()
            except psutil.Error:
                pass
        psutil.wait_procs(alive, timeout=3)
        return True
    except Exception:
        # Already exited, access denied, or a stale PID: nothing to stop.
        return False
    finally:
        clear_pid(name)
