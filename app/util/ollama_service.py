"""Start/stop only the Ollama process managed by IDFA.

Ollama may be shared with other applications. IDFA therefore stops only the PID
it launched (recorded under the per-user run directory), never an arbitrary
process listening on port 11434. The same PID file is written by
``start_idfa.ps1``, so both entry points agree on ownership.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlparse

from app.config import PROJECT_ROOT, get_config
from app.util import procs

PID_NAME = "ollama-idfa"


def _find_executable() -> Path | None:
    candidates = [PROJECT_ROOT / "tools" / "ollama" / "ollama.exe"]
    which = shutil.which("ollama.exe") or shutil.which("ollama")
    if which:
        candidates.append(Path(which))
    candidates += [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe",
        Path(os.environ.get("PROGRAMFILES", "C:\\Program Files")) / "Ollama" / "ollama.exe",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def is_running(host: str | None = None) -> bool:
    """True when a server answers on the configured Ollama endpoint."""
    target = (host or get_config().ollama.host).rstrip("/")
    return procs.http_ok(f"{target}/api/tags")


def ensure_running() -> bool:
    """Ensure a local Ollama server is up; launch it without blocking the caller."""
    host = get_config().ollama.host.rstrip("/")
    parsed = urlparse(host)
    if parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        # This is an externally managed endpoint, not a local process to launch.
        return is_running(host)
    if is_running(host):
        return True
    # The launcher may already be bringing the same server up. Wait for it
    # instead of spawning a second process that cannot bind the port and would
    # overwrite the launcher's PID file.
    if procs.wait_http(f"{host}/api/tags", seconds=3.0):
        return True

    executable = _find_executable()
    if executable is None:
        return False

    port = parsed.port or (443 if parsed.scheme == "https" else 11434)
    bind_host = "[::1]" if parsed.hostname == "::1" else "127.0.0.1"
    environment = os.environ.copy()
    environment["OLLAMA_HOST"] = f"{bind_host}:{port}"
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        process = subprocess.Popen(
            [str(executable), "serve"],
            cwd=str(executable.parent),
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )
    except OSError:
        return False

    procs.write_pid(PID_NAME, process.pid)
    return True


def stop_managed() -> bool:
    """Stop only the server launched by IDFA; leave a user's Ollama untouched."""
    return procs.stop_pid(PID_NAME, names=procs.OLLAMA_NAMES)
