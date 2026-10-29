"""Track page-owned ``QThread`` objects so IDFA can exit without crashing.

Qt aborts the process when a ``QThread``'s C++ object is destroyed while its
thread is still running; on Windows that surfaces as a crash dialog rather than
an exit. Closing IDFA during an AI status check, a search or an export used to
do exactly that, because nothing stopped the pages' threads.

Pages register every thread they start with :func:`track`. :func:`stop_all` asks
them to stop and waits briefly, and the entry point checks :func:`alive` before
Python tears the interpreter down.
"""
from __future__ import annotations

import logging
import time
import weakref

from PySide6.QtCore import QThread

logger = logging.getLogger(__name__)

# Weak references: a page keeps its own strong reference while it cares about a
# thread, and a finished thread must not be kept alive by this module.
_threads: list[weakref.ref] = []


def track(thread: QThread) -> QThread:
    """Register a thread so shutdown can find it. Returns the thread."""
    _threads[:] = [ref for ref in _threads if ref() is not None]
    _threads.append(weakref.ref(thread))
    return thread


def alive() -> list[QThread]:
    """The tracked threads that are still running."""
    running: list[QThread] = []
    kept: list[weakref.ref] = []
    for ref in _threads:
        thread = ref()
        if thread is None:
            continue
        kept.append(ref)
        try:
            if thread.isRunning():
                running.append(thread)
        except RuntimeError:
            # The C++ object was already deleted; nothing left to stop.
            continue
    _threads[:] = kept
    return running


def stop(thread: QThread | None, wait_ms: int = 3000) -> bool:
    """Ask one thread to stop and wait for it. True when it is no longer running."""
    if thread is None:
        return True
    try:
        if not thread.isRunning():
            return True
        thread.quit()
        if thread.wait(wait_ms):
            return True
    except RuntimeError:
        return True
    logger.warning("Background thread did not stop within %d ms", wait_ms)
    return False


def stop_all(wait_ms: int = 3000) -> list[QThread]:
    """Stop every tracked thread within one overall budget.

    The budget is shared, not per thread: three stuck threads must not make
    closing the window take three times as long.
    """
    deadline = time.monotonic() + max(0, wait_ms) / 1000
    remaining: list[QThread] = []
    for thread in alive():
        left = max(0, int((deadline - time.monotonic()) * 1000))
        if not stop(thread, wait_ms=left):
            remaining.append(thread)
    return remaining
