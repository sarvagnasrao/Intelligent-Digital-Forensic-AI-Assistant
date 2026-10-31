"""In-process background runner for the analysis queue.

One job at a time, on a plain thread with its own database session, driven by a
`QTimer` on the GUI thread. That shape keeps the window responsive without a
second process, and it is what lets the queue be paused and cancelled from the
UI.

The rules the runner enforces:

* **Never more than one job.** Two jobs writing entities for the same case would
  race on SQLite.
* **Never during a scan.** Examination owns the worker and the disk; analysis
  waits so it cannot slow an acquisition down.
* **Never silently.** Every state change is emitted so the queue pane updates,
  and the current job's progress is polled from the database.
"""
from __future__ import annotations

import asyncio
import logging
import threading

from PySide6.QtCore import QObject, QTimer, Signal

from app.analysis.service import AnalysisService, _CANCELLED
from app.auth.models import User
from app.auth.service import AuthService
from app.db.session import get_session_factory

logger = logging.getLogger(__name__)


class AnalysisRunner(QObject):
    """Polls the queue and runs one analysis job at a time."""

    # Emitted on the GUI thread. Payloads are plain dictionaries so a listener
    # never has to hold a session-bound ORM object from the worker thread.
    job_started = Signal(dict)
    job_progress = Signal(dict)
    job_finished = Signal(dict)
    queue_changed = Signal(dict)
    status_changed = Signal(str)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._case_id: int | None = None
        self._user_id: int | None = None
        self._generation = 0
        self._thread: threading.Thread | None = None
        self._active_job_id: int | None = None
        self._active_generation = 0
        self._paused = False
        self._timer = QTimer(self)
        self._timer.setInterval(4000)
        self._timer.timeout.connect(self._tick)
        self._last_status = ""

    # ------------------------------------------------------------------
    # Control
    # ------------------------------------------------------------------
    def set_case(self, case_id: int | None, user_id: int | None = None) -> None:
        """Bind dispatch to the signed-in investigator and open case."""
        if (case_id, user_id) != (self._case_id, self._user_id) and self._active_job_id is not None:
            # Stop our own worker even if the user's permissions were revoked.
            _CANCELLED.add(self._active_job_id)
            session = get_session_factory()()
            try:
                user = session.get(User, self._user_id) if self._user_id is not None else None
                AnalysisService(session).cancel(self._active_job_id, self._case_id, user)
            except Exception:
                logger.warning("Could not cancel analysis on context change", exc_info=True)
            finally:
                session.close()
        if (case_id, user_id) != (self._case_id, self._user_id):
            self._generation += 1
        self._case_id = case_id
        self._user_id = user_id

    def start(self) -> None:
        self._timer.start()
        self._tick()

    def stop(self) -> None:
        self._timer.stop()
        self.set_case(None, None)

    def pause(self) -> None:
        self._paused = True
        self._emit_status("Analysis paused")

    def resume(self) -> None:
        self._paused = False
        self._emit_status("Analysis running")
        self._tick()

    @property
    def paused(self) -> bool:
        return self._paused

    @property
    def busy(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def active_job_id(self) -> int | None:
        return self._active_job_id

    # ------------------------------------------------------------------
    # Polling
    # ------------------------------------------------------------------
    def _tick(self) -> None:
        if self._paused:
            return
        if self._case_id is None or self._user_id is None:
            return
        if self.busy:
            self._emit_progress()
            return
        if self._active_job_id is not None:
            # The thread finished; announce it once.
            self._active_job_id = None

        session = get_session_factory()()
        try:
            service = AnalysisService(session)
            user = session.get(User, self._user_id)
            if (user is None or not user.is_active
                    or not AuthService(session).user_can_write_case(user, self._case_id)):
                self._emit_status("Analysis unavailable: case write access required")
                return
            if not service.config.analysis.enabled:
                self._emit_status("Analysis disabled in settings")
                return
            if service.is_examination_running(self._case_id):
                self._emit_status("Waiting for the examination to finish")
                return

            # Also queue anything that completed while the app was closed, so a
            # case added on a previous session is analysed today.
            if self._case_id is not None and service.config.analysis.auto_queue:
                try:
                    service.enqueue_missing(self._case_id, created_by=user)
                    session.commit()
                except Exception:  # noqa: BLE001
                    session.rollback()
                    logger.warning("Could not queue missing analysis", exc_info=True)

            job = service.next_pending(self._case_id)
            if job is None:
                self._emit_status("Analysis queue empty")
                self.queue_changed.emit(service.counts(self._case_id))
                return

            payload = {
                "id": job.id,
                "job_id": job.job_id,
                "case_id": job.case_id,
                "evidence_id": job.evidence_id,
                "artifact_count": job.artifact_count,
            }
            self._active_job_id = job.id
            self._active_generation = self._generation
            user_id, case_id = self._user_id, self._case_id
        except Exception:  # noqa: BLE001 - keep the timer alive
            session.rollback()
            logger.exception("Could not dispatch analysis")
            self._emit_status("Could not dispatch analysis")
            return
        finally:
            session.close()

        self.job_started.emit(payload)
        self._emit_status("Analysing…")
        self._thread = threading.Thread(
            target=self._run_job,
            args=(payload["id"], case_id, user_id, self._generation), daemon=True,
        )
        self._thread.start()

    def _emit_progress(self) -> None:
        if self._active_job_id is None or self._active_generation != self._generation:
            return
        session = get_session_factory()()
        try:
            job = AnalysisService(session).get_job(self._active_job_id)
            if job is None:
                return
            self.job_progress.emit({
                "id": job.id,
                "job_id": job.job_id,
                "status": job.status.value,
                "stage": job.stage,
                "percent": job.progress_percent,
                "message": job.progress_message,
            })
        finally:
            session.close()

    # ------------------------------------------------------------------
    # Worker thread
    # ------------------------------------------------------------------
    def _run_job(self, job_pk: int, case_id: int, user_id: int, generation: int) -> None:
        session = get_session_factory()()
        try:
            service = AnalysisService(session)
            user = session.get(User, user_id)
            job = service.get_job(job_pk)
            if (self._case_id, self._user_id) != (case_id, user_id):
                raise PermissionError("Analysis context changed")
            if job is None or job.case_id != case_id:
                raise PermissionError("Analysis job does not belong to the selected case")
            if (user is None or not user.is_active
                    or not AuthService(session).user_can_write_case(user, case_id)):
                raise PermissionError("Case write access required")
            result = asyncio.run(service.run(job_pk, user))
        except Exception as exc:  # noqa: BLE001 - never lose the queue to a bug
            logger.exception("Analysis job %s crashed", job_pk)
            # Do not repeatedly dispatch a pending job that failed before run()
            # could record a failure. An investigator can resume explicitly.
            if (self._case_id, self._user_id) == (case_id, user_id):
                self._paused = True
            result = {"ok": False, "error": str(exc) or exc.__class__.__name__}
        finally:
            session.close()

        _CANCELLED.discard(job_pk)
        # Re-read the final state for the UI: the job may have completed, failed
        # or been cancelled, and the outcome belongs to the summary either way.
        summary: dict = {"id": job_pk, **result}
        session = get_session_factory()()
        try:
            job = AnalysisService(session).get_job(job_pk)
            if job is not None:
                summary.update({
                    "job_id": job.job_id,
                    "status": job.status.value,
                    "percent": job.progress_percent,
                    "message": job.progress_message,
                    "error": job.error_message or result.get("error"),
                    "entities": job.entity_count,
                    "relationships": job.relationship_count,
                })
            counts = AnalysisService(session).counts(case_id)
        except Exception:  # noqa: BLE001
            counts = {}
        finally:
            session.close()

        self._active_job_id = None
        if generation != self._generation:
            return
        self.job_finished.emit(summary)
        self.queue_changed.emit(counts)
        if not result.get("ok"):
            self._emit_status("Analysis failed: " + str(result.get("error", "Unknown error")))
        else:
            self._emit_status("Analysis queue empty")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _emit_status(self, text: str) -> None:
        if text != self._last_status:
            self._last_status = text
            self.status_changed.emit(text)
