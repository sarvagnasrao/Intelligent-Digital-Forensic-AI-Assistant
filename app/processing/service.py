"""Serial processing coordinator, independent of Qt, databases and model clients.

Nothing executes until a caller explicitly approves and runs a plan. Callers
must enforce case permissions before creating/approving plans and supply trusted
completed prerequisites for the exact scope/settings in use. This module does
not verify those assertions or implement authentication.

LIMITATION: plans, approvals, progress and errors exist only in this service
instance's memory. They are NOT a durable queue, audit trail or crash recovery
mechanism. Callback side effects may persist independently; cancellation cannot
undo them and is checked only between stages. No callback is retried implicitly.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from threading import RLock
from types import MappingProxyType
from typing import Any
from uuid import uuid4


class Stage(StrEnum):
    VERIFY = "verify"
    EXTRACT = "extract"
    INDEX = "index"
    ANALYZE = "analyze"
    BRIEFING = "briefing"


STAGES = tuple(Stage)
PERSISTENCE_LIMITATION = "In-memory only; runs and approvals are lost on process exit."


def _freeze(value: Any) -> Any:
    """Snapshot JSON-shaped settings without retaining mutable caller objects."""
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise TypeError("Snapshot keys must be strings")
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    raise TypeError("Scope and settings must contain JSON-shaped values")


@dataclass(frozen=True)
class StageProgress:
    stage: Stage
    status: str = "pending"
    error: str | None = None
    blocked_by: tuple[Stage, ...] = ()


@dataclass(frozen=True)
class RunSnapshot:
    run_id: str
    actor_id: str | int
    scope: Mapping[str, Any]
    settings: Mapping[str, Any]
    selected_stages: tuple[Stage, ...]
    completed_prerequisites: tuple[Stage, ...]
    created_at: datetime
    status: str
    stages: tuple[StageProgress, ...]
    approved_by: str | int | None = None
    approved_at: datetime | None = None
    cancel_requested: bool = False
    persistence_limitation: str = PERSISTENCE_LIMITATION

    @property
    def progress(self) -> float:
        """Fraction of selected stages successfully completed (0..1)."""
        return sum(stage.status == "completed" for stage in self.stages) / len(self.stages)


@dataclass(frozen=True)
class StageContext:
    run_id: str
    stage: Stage
    actor_id: str | int
    approved_by: str | int
    scope: Mapping[str, Any]
    settings: Mapping[str, Any]


StageCallback = Callable[[StageContext], None]


@dataclass
class _Run:
    snapshot: RunSnapshot
    executing: bool = False


class ProcessingService:
    """Own an ephemeral registry; execute injected callbacks serially.

    ``run`` blocks its calling thread. A UI should call it on its own worker
    thread and poll ``get`` for progress; ``cancel`` is safe from another thread.
    Callbacks signal failure by raising an Exception; return values are ignored.
    There are no default callbacks, model calls, timers or automatic execution.
    """

    def __init__(self, callbacks: Mapping[Stage | str, StageCallback]):
        self._callbacks = {Stage(stage): callback for stage, callback in callbacks.items()}
        if not all(callable(callback) for callback in self._callbacks.values()):
            raise TypeError("Stage callbacks must be callable")
        self._runs: dict[str, _Run] = {}
        self._lock = RLock()

    def create_plan(
        self,
        *,
        actor_id: str | int,
        scope: Mapping[str, Any],
        settings: Mapping[str, Any],
        selected_stages: Iterable[Stage | str],
        completed_prerequisites: Iterable[Stage | str] = (),
    ) -> RunSnapshot:
        self._validate_actor(actor_id)
        selected = set(map(Stage, selected_stages))
        completed = set(map(Stage, completed_prerequisites))
        if not selected:
            raise ValueError("Select at least one stage")
        if selected & completed:
            raise ValueError("Selected stages cannot also be completed prerequisites")
        snapshot = RunSnapshot(
            run_id=uuid4().hex,
            actor_id=actor_id,
            scope=_freeze(scope),
            settings=_freeze(settings),
            selected_stages=tuple(stage for stage in STAGES if stage in selected),
            completed_prerequisites=tuple(stage for stage in STAGES if stage in completed),
            created_at=datetime.now(UTC),
            status="awaiting_approval",
            stages=tuple(StageProgress(stage) for stage in STAGES if stage in selected),
        )
        with self._lock:
            self._runs[snapshot.run_id] = _Run(snapshot)
        return snapshot

    @staticmethod
    def _validate_actor(actor_id: str | int) -> None:
        if isinstance(actor_id, bool) or not isinstance(actor_id, (str, int)):
            raise ValueError("An initiating/approving actor ID is required")
        if not str(actor_id).strip():
            raise ValueError("An initiating/approving actor ID is required")

    def get(self, run_id: str) -> RunSnapshot:
        with self._lock:
            return self._runs[run_id].snapshot

    def _update(self, run: _Run, **changes: Any) -> RunSnapshot:
        run.snapshot = replace(run.snapshot, **changes)
        return run.snapshot

    def approve(self, run_id: str, *, approved_by: str | int) -> RunSnapshot:
        self._validate_actor(approved_by)
        with self._lock:
            run = self._runs[run_id]
            if run.snapshot.status != "awaiting_approval":
                raise ValueError("Only a pending plan can be approved")
            return self._update(
                run, status="approved", approved_by=approved_by, approved_at=datetime.now(UTC)
            )

    def cancel(self, run_id: str) -> RunSnapshot:
        with self._lock:
            run = self._runs[run_id]
            if run.snapshot.status in {"completed", "failed", "blocked", "cancelled"}:
                return run.snapshot
            self._update(run, cancel_requested=True)
            if not run.executing:
                self._finish_pending(run, "cancelled")
            return run.snapshot

    def _finish_pending(self, run: _Run, status: str) -> RunSnapshot:
        stages = tuple(
            replace(stage, status=status) if stage.status == "pending" else stage
            for stage in run.snapshot.stages
        )
        return self._update(run, status=status, stages=stages)

    def run(self, run_id: str) -> RunSnapshot:
        with self._lock:
            run = self._runs[run_id]
            if run.executing or run.snapshot.status != "approved":
                raise ValueError("Run requires explicit approval and can execute only once")
            run.executing = True
            self._update(run, status="running")
        try:
            available = set(run.snapshot.completed_prerequisites)
            for stage in run.snapshot.selected_stages:
                with self._lock:
                    if run.snapshot.cancel_requested:
                        return self._finish_pending(run, "cancelled")
                    missing = tuple(
                        item for item in STAGES[: STAGES.index(stage)] if item not in available
                    )
                    if missing:
                        stages = tuple(
                            replace(item, status="blocked", blocked_by=missing)
                            if item.status == "pending"
                            else item
                            for item in run.snapshot.stages
                        )
                        return self._update(run, status="blocked", stages=stages)
                    self._update(
                        run,
                        stages=tuple(
                            replace(item, status="running") if item.stage == stage else item
                            for item in run.snapshot.stages
                        ),
                    )
                    snapshot = run.snapshot
                try:
                    callback = self._callbacks.get(stage)
                    if callback is None:
                        raise RuntimeError(f"No callback configured for {stage.value}")
                    callback(
                        StageContext(
                            run_id,
                            stage,
                            snapshot.actor_id,
                            snapshot.approved_by,
                            snapshot.scope,
                            snapshot.settings,
                        )
                    )
                except Exception as exc:
                    with self._lock:
                        stages = tuple(
                            replace(item, status="failed", error=f"{type(exc).__name__}: {exc}")
                            if item.stage == stage
                            else replace(item, status="blocked", blocked_by=(stage,))
                            if item.status == "pending"
                            else item
                            for item in run.snapshot.stages
                        )
                        return self._update(run, status="failed", stages=stages)
                with self._lock:
                    available.add(stage)
                    self._update(
                        run,
                        stages=tuple(
                            replace(item, status="completed") if item.stage == stage else item
                            for item in run.snapshot.stages
                        ),
                    )
            with self._lock:
                return self._update(run, status="completed")
        finally:
            with self._lock:
                run.executing = False
