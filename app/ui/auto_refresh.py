"""Periodic refresh of the page the investigator is looking at.

The refresh interval in Settings used to be stored and ignored. This drives it:
a timer ticks in the background and asks the visible page to reload, so a job
that finishes in the worker shows up without pressing Refresh.

Pages expose ``refresh()``; anything without it is simply skipped, which lets
partially built pages contribute nothing rather than raise.
"""
from __future__ import annotations

import logging
from collections.abc import Callable

from PySide6.QtCore import QObject, Qt, QTimer
from PySide6.QtWidgets import QWidget

logger = logging.getLogger(__name__)

MIN_INTERVAL_SECONDS = 10


class AutoRefreshController(QObject):
    """Calls ``refresh()`` on the current page every ``interval`` seconds."""

    def __init__(
        self,
        current_page: Callable[[], QWidget | None],
        parent: QObject | None = None,
    ):
        super().__init__(parent)
        self._current_page = current_page
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.CoarseTimer)
        self._timer.timeout.connect(self.refresh_now)

    # ------------------------------------------------------------------
    @property
    def enabled(self) -> bool:
        return self._timer.isActive()

    @property
    def interval_seconds(self) -> int:
        return max(MIN_INTERVAL_SECONDS, self._timer.interval() // 1000)

    def configure(self, enabled: bool, interval_seconds: int) -> None:
        """Start, stop or re-time the timer from the saved settings."""
        interval = max(MIN_INTERVAL_SECONDS, int(interval_seconds or 0))
        self._timer.setInterval(interval * 1000)
        if enabled:
            self._timer.start()
        else:
            self._timer.stop()

    def refresh_now(self) -> None:
        """Refresh the visible page once. Safe to call directly."""
        from PySide6.QtWidgets import QApplication

        # Never reload a table out from under an open dialog or message box.
        if QApplication.activeModalWidget() is not None:
            return

        page = self._current_page()
        if page is None:
            return
        if not page.isVisible():
            return
        refresh = getattr(page, "refresh", None)
        if not callable(refresh):
            return
        try:
            refresh()
        except Exception:
            # A page that fails to reload must not spam the log every tick.
            logger.warning(
                "Automatic refresh failed for %s",
                type(page).__name__,
                exc_info=True,
            )
            self._timer.stop()
