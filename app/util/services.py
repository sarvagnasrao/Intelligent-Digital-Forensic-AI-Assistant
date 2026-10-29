"""Start, stop and inspect the local services IDFA depends on.

Settings offers the same controls the launcher scripts provide, so a demo can be
recovered without closing the application. Everything here follows one rule:
only a process this installation started (and therefore recorded in a PID file)
may be stopped. A worker or Qdrant that was already running when IDFA opened is
reported as externally managed and left alone.
"""
from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from app.config import PROJECT_ROOT, get_config
from app.util import ollama_service, procs

WORKER = "worker"
QDRANT = "qdrant"
OLLAMA = "ollama"

RUNNING = "running"
STARTING = "starting"
STOPPED = "stopped"
NOT_NEEDED = "not_needed"
ERROR = "error"


@dataclass(frozen=True)
class ServiceStatus:
    key: str
    label: str
    endpoint: str
    state: str
    detail: str
    owned: bool = False

    @property
    def is_running(self) -> bool:
        return self.state == RUNNING

    @property
    def can_start(self) -> bool:
        return self.state in {STOPPED, ERROR}

    @property
    def can_stop(self) -> bool:
        return self.owned and self.state in {RUNNING, STARTING}


def uses_local_ollama() -> bool:
    """Ollama is needed while either chat or embeddings is local."""
    config = get_config()
    return (
        config.ollama.provider != "openai"
        or config.embeddings.provider != "openai"
    )


def _split_url(url: str, default_port: int) -> tuple[str, int]:
    parsed = urlparse(url)
    host = parsed.hostname or "127.0.0.1"
    if host in {"0.0.0.0", "::"}:
        host = "127.0.0.1"
    return host, parsed.port or default_port


def _python() -> Path:
    """The interpreter running the GUI, preferring the console build.

    The app is normally launched with ``python.exe`` from the virtual
    environment. ``pythonw.exe`` cannot redirect output to a log file, so its
    sibling is used for the worker when available.
    """
    executable = Path(sys.executable)
    if executable.name.casefold() == "pythonw.exe":
        candidate = executable.with_name("python.exe")
        if candidate.is_file():
            return candidate
    return executable


def _spawn(
    args: list[str], *, cwd: Path, env: dict[str, str], log: str
) -> subprocess.Popen:
    logs = Path(get_config().app.logs_dir)
    logs.mkdir(parents=True, exist_ok=True)
    out = (logs / f"{log}.log").open("ab")
    err = (logs / f"{log}.err.log").open("ab")
    try:
        process = subprocess.Popen(
            args,
            cwd=str(cwd),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=out,
            stderr=err,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    finally:
        # The child inherited the handles; the parent no longer needs them.
        out.close()
        err.close()
    return process


def _worker_env() -> dict[str, str]:
    config = get_config()
    host, port = _split_url(config.worker.url, 8000)
    environment = os.environ.copy()
    environment["IDFA_WORKER_HOST"] = host
    environment["IDFA_WORKER_PORT"] = str(port)
    environment["IDFA_OLLAMA_HOST"] = config.ollama.host.rstrip("/")
    environment["IDFA_OLLAMA_MODEL"] = config.ollama.model
    environment["IDFA_EMBEDDING_MODEL"] = config.embeddings.model_id
    environment["IDFA_QDRANT_URL"] = config.qdrant.url.rstrip("/")
    return environment


def _health_url(key: str) -> str:
    config = get_config()
    if key == WORKER:
        return f"{config.worker.url.rstrip('/')}/health"
    if key == QDRANT:
        return f"{config.qdrant.url.rstrip('/')}/healthz"
    return f"{config.ollama.host.rstrip('/')}/api/tags"


def _pid_name(key: str) -> str:
    return {
        WORKER: "worker",
        QDRANT: "qdrant",
        OLLAMA: ollama_service.PID_NAME,
    }[key]


def _label(key: str) -> str:
    return {WORKER: "Forensic worker", QDRANT: "Qdrant", OLLAMA: "Ollama"}[key]


def statuses() -> list[ServiceStatus]:
    """Current state of every service, as shown in Settings."""
    config = get_config()
    result: list[ServiceStatus] = []

    for key, endpoint in (
        (WORKER, config.worker.url.rstrip("/")),
        (QDRANT, config.qdrant.url.rstrip("/")),
        (OLLAMA, config.ollama.host.rstrip("/")),
    ):
        needed = True
        if key == OLLAMA and not uses_local_ollama():
            needed = False

        healthy = procs.http_ok(_health_url(key))
        owned = procs.is_alive(_pid_name(key))

        if not needed:
            state, detail = NOT_NEEDED, "Cloud chat and embeddings"
        elif healthy and owned:
            state, detail = RUNNING, "Started by IDFA"
        elif healthy:
            state, detail = RUNNING, "Started outside IDFA"
        elif owned:
            state, detail = STARTING, "Starting…"
        else:
            state, detail = STOPPED, "Not running"

        result.append(
            ServiceStatus(
                key=key,
                label=_label(key),
                endpoint=endpoint,
                state=state,
                detail=detail,
                owned=owned,
            )
        )
    return result


def start(key: str) -> tuple[bool, str]:
    """Start one service and wait for it to answer."""
    config = get_config()
    if key == OLLAMA:
        if ollama_service.ensure_running():
            return True, "Ollama is running."
        return False, "Ollama could not be started. Check that it is installed."

    if key == WORKER:
        if procs.http_ok(_health_url(WORKER)):
            return True, "The forensic worker is already running."
        host, port = _split_url(config.worker.url, 8000)
        process = _spawn(
            [str(_python()), str(PROJECT_ROOT / "worker" / "main.py")],
            cwd=PROJECT_ROOT,
            env=_worker_env(),
            log="worker",
        )
        procs.write_pid("worker", process.pid)
        # A cold start also runs the database setup, which can take a while on a
        # laptop; 90s leaves room without hiding a genuinely broken worker.
        if procs.wait_http(_health_url(WORKER), seconds=90):
            # The launcher shim is not the server; record the process that
            # actually holds the port so Stop targets the right one.
            procs.write_pid("worker", procs.listener_pid(port) or process.pid)
            return True, f"The forensic worker is running on {host}:{port}."
        # A worker that never answered must not be left holding the port: the
        # next Start would fail to bind and look like a broken installation.
        procs.stop_pid("worker", names=procs.PYTHON_NAMES)
        return False, "The worker did not answer within 90 seconds. See the worker log."

    if key == QDRANT:
        if procs.http_ok(_health_url(QDRANT)):
            return True, "Qdrant is already running."
        executable = PROJECT_ROOT / "tools" / "qdrant" / "qdrant.exe"
        if not executable.is_file():
            return False, "Qdrant is not installed. Run SETUP_IDFA.bat."
        storage = config.qdrant.storage_path or str(Path(config.app.data_dir) / "qdrant")
        Path(storage).mkdir(parents=True, exist_ok=True)
        environment = os.environ.copy()
        environment["QDRANT__STORAGE__STORAGE_PATH"] = storage
        environment["QDRANT__TELEMETRY_DISABLED"] = "true"
        process = _spawn(
            [str(executable)],
            cwd=executable.parent,
            env=environment,
            log="qdrant",
        )
        procs.write_pid("qdrant", process.pid)
        if procs.wait_http(_health_url(QDRANT), seconds=60):
            return True, "Qdrant is running."
        procs.stop_pid("qdrant", names=procs.QDRANT_NAMES)
        return False, "Qdrant did not become healthy within 60 seconds. See the Qdrant log."

    return False, f"Unknown service: {key}"


def stop(key: str) -> tuple[bool, str]:
    """Stop a service this installation started."""
    if key == OLLAMA:
        if ollama_service.stop_managed():
            return True, "Ollama was stopped."
        return False, "No IDFA-managed Ollama process was running."

    if key == WORKER:
        if procs.stop_pid("worker", names=procs.PYTHON_NAMES):
            if procs.wait_down(_health_url(WORKER), seconds=10):
                return True, "The forensic worker was stopped."
            return False, (
                "The worker process ended, but port "
                f"{_split_url(get_config().worker.url, 8000)[1]} is still answering. "
                "Another copy may be running outside IDFA."
            )
        return False, (
            "The worker was not started by IDFA, so it was left running."
        )

    if key == QDRANT:
        if procs.stop_pid("qdrant", names=procs.QDRANT_NAMES):
            if procs.wait_down(_health_url(QDRANT), seconds=10):
                return True, "Qdrant was stopped."
            return False, "Qdrant is still answering; it may have been started outside IDFA."
        return False, "Qdrant was not started by IDFA, so it was left running."

    return False, f"Unknown service: {key}"


def restart(key: str) -> tuple[bool, str]:
    stop(key)
    return start(key)


def start_all() -> list[tuple[str, bool, str]]:
    """Start in dependency order: vector store, worker, then Ollama."""
    results = []
    for key in (QDRANT, WORKER):
        results.append((key, *start(key)))
    if uses_local_ollama():
        results.append((OLLAMA, *start(OLLAMA)))
    return results


def stop_all() -> list[tuple[str, bool, str]]:
    results = []
    for key in (OLLAMA, WORKER, QDRANT):
        results.append((key, *stop(key)))
    return results


def logs_dir() -> Path:
    return Path(get_config().app.logs_dir)
