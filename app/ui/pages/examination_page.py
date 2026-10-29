"""Examination Page."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableView, QHeaderView,
    QAbstractItemView, QPushButton, QSplitter, QFrame, QComboBox,
    QLabel, QProgressBar, QTextEdit, QTabWidget, QMessageBox, QDialog,
    QFormLayout, QDialogButtonBox, QSpinBox, QCheckBox, QToolButton,
    QGroupBox, QLineEdit, QScrollArea, QApplication
)
import json
import math
from datetime import datetime, timezone
from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QStandardItemModel, QStandardItem, QFont

from app.ui.base import ResponsivePage, CaseContext
from app.ui.theme.tokens import Color, Spacing, Typography
from app.util.time import format_local
from app.examination.models import ExaminationJob, ExaminationOperation, JobStatus
from app.examination.profiles import (
    PROFILES,
    DEFAULT_PROFILE,
    parameter_summary,
    profile_parameters,
    validate_parameters,
)
from app.examination.service import ExaminationService
from app.evidence.service import EvidenceService
from app.evidence.models import Evidence, EvidenceStatus


def _enum_text(value) -> str:
    """Text for an enum value, tolerating plain strings from Qt widgets."""
    return str(getattr(value, "value", value))


def _combo_index_for(combo: QComboBox, value) -> int:
    """Index of ``value`` in ``combo``, tolerating enum/string differences.

    Qt turns ``str``-based enums stored as item data back into plain strings,
    so ``findData`` alone misses them.
    """
    target = _enum_text(value)
    for index in range(combo.count()):
        if _enum_text(combo.itemData(index)) == target:
            return index
    return -1


class JobTableModel(QStandardItemModel):
    HEADERS = [
        "Job ID", "Evidence", "Operation", "Status", "Progress (est.)",
        "Elapsed", "ETA (est.)", "Started", "Completed",
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setHorizontalHeaderLabels(self.HEADERS)

    def populate(self, jobs: list[ExaminationJob]):
        self.removeRows(0, self.rowCount())
        now = datetime.now(timezone.utc)
        for job in jobs:
            evidence_name = job.evidence.name if job.evidence else f"ID:{job.evidence_id}"
            progress_message = (getattr(job, "progress_message", None) or "").lower()
            display_status = (
                "cancelling" if job.status == JobStatus.RUNNING
                and progress_message.startswith("cancelling") else
                "paused" if job.status == JobStatus.RUNNING
                and progress_message.startswith(("paused", "pausing")) else
                _enum_text(job.status)
            )
            elapsed_text, eta_text = _job_time_text(job, now)
            row = [
                QStandardItem(job.job_id),
                QStandardItem(evidence_name),
                QStandardItem(_enum_text(job.operation).replace("_", " ").title()),
                QStandardItem(display_status),
                QStandardItem(
                    f"~{job.progress_percent}%" if job.status == JobStatus.RUNNING
                    else f"{job.progress_percent}%"
                ),
                QStandardItem(elapsed_text),
                QStandardItem(eta_text),
                QStandardItem(format_local(job.started_at)),
                QStandardItem(format_local(job.completed_at)),
            ]
            for item in row:
                item.setEditable(False)
            # Color status
            status_item = row[3]
            if job.status == JobStatus.RUNNING:
                status_item.setForeground(
                    Color.WARNING if display_status in ("paused", "cancelling")
                    else Color.PRIMARY
                )
            elif job.status == JobStatus.COMPLETED:
                status_item.setForeground(Color.SUCCESS)
            elif job.status == JobStatus.FAILED:
                status_item.setForeground(Color.ERROR)
            elif job.status == JobStatus.INTERRUPTED:
                status_item.setForeground(Color.WARNING)
            self.appendRow(row)


def _format_duration(seconds: float) -> str:
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def _job_time_text(job, now: datetime | None = None) -> tuple[str, str]:
    """Return wall-clock elapsed time and a conservative progress-based ETA."""
    started = job.started_at
    if started is None:
        return "—", "—"
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    else:
        started = started.astimezone(timezone.utc)

    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    else:
        now = now.astimezone(timezone.utc)

    end = job.completed_at
    if end is not None:
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        else:
            end = end.astimezone(timezone.utc)
    else:
        end = now
    elapsed = max(0.0, (end - started).total_seconds())

    if job.status != JobStatus.RUNNING:
        return _format_duration(elapsed), "—"
    message = (getattr(job, "progress_message", None) or "").lower()
    if message.startswith("paused"):
        return _format_duration(elapsed), "Paused"
    if message.startswith("pausing"):
        return _format_duration(elapsed), "Pausing…"

    percent = max(0, min(99, int(job.progress_percent or 0)))
    if percent < 3 or elapsed < 3:
        return _format_duration(elapsed), "Estimating…"
    eta_seconds = elapsed * (100 - percent) / percent
    return _format_duration(elapsed), f"~{_format_duration(math.ceil(eta_seconds))}"


class ExaminationPage(ResponsivePage):
    start_finished = Signal(str)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent=parent)
        self.case_context: CaseContext | None = None
        self.exam_service: ExaminationService | None = None
        self.evidence_service: EvidenceService | None = None
        self._selected_job: ExaminationJob | None = None
        self._evidence_list: list[Evidence] = []
        # ORM jobs in the same order as the jobs table rows.
        self._jobs: list[ExaminationJob] = []
        self._starting = False
        self._active_job_id: str | None = None
        self._job_thread = None
        # The result of a run arrives from a worker thread; this signal is
        # delivered on the GUI thread. Without this connection the button
        # stayed on a startup state and nothing ever refreshed.
        self.start_finished.connect(self._finish_start)

    def _setup_layout(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(Spacing.LG, Spacing.LG, Spacing.LG, Spacing.LG)
        layout.setSpacing(Spacing.LG)

        # Evidence selector
        selector_row = QHBoxLayout()
        selector_row.addWidget(QLabel("Evidence:"))
        self.evidence_combo = QComboBox()
        self.evidence_combo.setMinimumWidth(300)
        selector_row.addWidget(self.evidence_combo)
        selector_row.addSpacing(Spacing.LG)

        selector_row.addStretch()
        layout.addLayout(selector_row)

        self.selector_hint = QLabel()
        self.selector_hint.setWordWrap(True)
        self.selector_hint.setStyleSheet(
            f"color: {Color.TEXT_SECONDARY.name()};"
        )
        layout.addWidget(self.selector_hint)

        self.evidence_combo.currentIndexChanged.connect(self._on_evidence_changed)
        self._update_hint()

        # Jobs table
        jobs_label = QLabel("Examination Jobs")
        jobs_label.setFont(QFont(Typography.FONT_FAMILY, Typography.HEADING_SM[0], Typography.HEADING_SM[1]))
        layout.addWidget(jobs_label)

        self.jobs_table = QTableView()
        self.jobs_model = JobTableModel(self.jobs_table)
        self.jobs_table.setModel(self.jobs_model)
        self.jobs_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.jobs_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.jobs_table.setAlternatingRowColors(True)
        self.jobs_table.verticalHeader().setVisible(False)
        jobs_header = self.jobs_table.horizontalHeader()
        jobs_header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        jobs_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        jobs_header.setStretchLastSection(True)
        self.jobs_table.selectionModel().selectionChanged.connect(self._on_job_selected)
        self.jobs_table.setMinimumHeight(190)
        layout.addWidget(self.jobs_table, 3)

        # Action buttons
        btn_row = QHBoxLayout()
        
        self.new_job_btn = QPushButton("New Job")
        self.new_job_btn.setToolTip(
            "Choose evidence and configure the operation for a new job."
        )
        self.new_job_btn.clicked.connect(self._on_new_job)
        btn_row.addWidget(self.new_job_btn)

        self.start_btn = QPushButton("Start Examination")
        self.start_btn.setToolTip(
            "Run the selected pending or failed job on the forensic worker."
        )
        self.start_btn.clicked.connect(self._on_start)
        btn_row.addWidget(self.start_btn)

        self.pause_btn = QPushButton("Pause")
        self.pause_btn.setProperty("secondary", True)
        self.pause_btn.setToolTip(
            "Pause a running examination at its next safe checkpoint."
        )
        self.pause_btn.clicked.connect(self._on_pause_resume)
        self.pause_btn.setEnabled(False)
        btn_row.addWidget(self.pause_btn)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setProperty("secondary", True)
        self.cancel_btn.setToolTip(
            "Cancel a pending job, or request that a running examination stop "
            "at its next safe checkpoint."
        )
        self.cancel_btn.clicked.connect(self._on_cancel)
        self.cancel_btn.setEnabled(False)
        btn_row.addWidget(self.cancel_btn)

        self.delete_job_btn = QPushButton("Delete Job")
        self.delete_job_btn.setProperty("secondary", True)
        self.delete_job_btn.setToolTip(
            "Delete any non-running job, its extracted artifacts, and derived analysis results."
        )
        self.delete_job_btn.clicked.connect(self._on_delete_job)
        self.delete_job_btn.setEnabled(False)
        btn_row.addWidget(self.delete_job_btn)

        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.setProperty("secondary", True)
        self.refresh_btn.setToolTip("Reload evidence and jobs for this case.")
        self.refresh_btn.clicked.connect(self.refresh)
        btn_row.addWidget(self.refresh_btn)

        btn_row.addStretch()
        layout.addLayout(btn_row)

        # Results/Log pane
        results_label = QLabel("Results / Log")
        results_label.setFont(QFont(Typography.FONT_FAMILY, Typography.HEADING_SM[0], Typography.HEADING_SM[1]))
        layout.addWidget(results_label)

        self.results_tabs = QTabWidget()
        self.results_log = QTextEdit()
        self.results_log.setReadOnly(True)
        self.results_log.setFont(QFont(Typography.FONT_FAMILY, Typography.MONO_SM[0]))
        self.results_tabs.addTab(self.results_log, "Log")

        self.results_summary = QTextEdit()
        self.results_summary.setReadOnly(True)
        self.results_tabs.addTab(self.results_summary, "Summary")

        self.results_tabs.setMinimumHeight(125)
        layout.addWidget(self.results_tabs, 2)

        self.operation_progress = QProgressBar()
        self.operation_progress.setRange(0, 100)
        self.operation_progress.setFormat("Preparing examination…")
        self.operation_progress.hide()
        layout.addWidget(self.operation_progress)
        self._progress_timer = QTimer(self)
        self._progress_timer.setInterval(750)
        self._progress_timer.timeout.connect(self._refresh_running_progress)

    def set_case_context(self, context: CaseContext):
        """Set case scope before or after service injection."""
        self.case_context = context
        self.refresh()

    def set_exam_service(self, service: ExaminationService):
        self.exam_service = service
        self.refresh()

    def set_evidence_service(self, service: EvidenceService):
        self.evidence_service = service
        self._populate_evidence_combo()

    def _ensure_services(self):
        """Create this page's services when the shell did not inject them.

        The page keeps these sessions open for the life of the page: sessions
        closed by a ``with`` block release their writes, so each service owns
        one long-lived session.
        """
        if self.exam_service is None:
            try:
                from app.db.session import get_session_factory
                self.exam_service = ExaminationService(get_session_factory()())
            except Exception as exc:
                self.results_log.append(
                    f"Examination service unavailable: {exc}"
                )
        if self.evidence_service is None:
            try:
                from app.db.session import get_session_factory
                self.evidence_service = EvidenceService(get_session_factory()())
            except Exception as exc:
                self.results_log.append(
                    f"Evidence service unavailable: {exc}"
                )

    def _populate_evidence_combo(self):
        """Load evidence for the active case using persisted evidence IDs.

        This method is safe regardless of whether the case context or service
        is injected first. It never uses a table row number as an identifier.
        """
        previous = self.evidence_combo.currentData()
        self.evidence_combo.blockSignals(True)
        self.evidence_combo.clear()
        self._evidence_list = []

        if not self.evidence_service or not self.case_context:
            self.evidence_combo.addItem("No evidence available", None)
            self.evidence_combo.setEnabled(False)
            self.evidence_combo.blockSignals(False)
            self._update_hint()
            return

        try:
            evidence = self.evidence_service.get_evidence_by_case(
                self.case_context.case_id
            )
            self._evidence_list = [
                item for item in (evidence or [])
                if item.status != EvidenceStatus.ARCHIVED
            ]
        except Exception as exc:
            self.evidence_combo.addItem("Evidence could not be loaded", None)
            self.evidence_combo.setEnabled(False)
            self.evidence_combo.blockSignals(False)
            self.results_log.append(
                f"Unable to load evidence for this case: {exc}"
            )
            self._update_hint()
            return

        if not self._evidence_list:
            self.evidence_combo.addItem("No evidence registered", None)
        else:
            self.evidence_combo.addItem("Select evidence...", None)
        for ev in self._evidence_list:
            evidence_pk = getattr(ev, "id", None)
            evidence_label = (
                f"{getattr(ev, 'evidence_id', evidence_pk)} — "
                f"{getattr(ev, 'name', 'Unnamed evidence')}"
            )
            self.evidence_combo.addItem(evidence_label, evidence_pk)

        self.evidence_combo.setEnabled(bool(self._evidence_list))
        # Keep the current choice across refreshes so "Start Examination" on the
        # Evidence page lands with that item still selected.
        if previous is not None:
            index = self.evidence_combo.findData(previous)
            if index >= 0:
                self.evidence_combo.setCurrentIndex(index)
        self.evidence_combo.setToolTip(
            "Choose evidence registered to the active case."
            if self._evidence_list
            else "No registered evidence was found for the active case."
        )
        self.evidence_combo.blockSignals(False)
        self._update_hint()

    def _update_hint(self):
        """Explain what the selectors and buttons do in the current state."""
        hint = getattr(self, "selector_hint", None)
        if hint is None:
            return
        evidence_list = getattr(self, "_evidence_list", [])
        if not evidence_list:
            hint.setText(
                "No evidence is registered for this case yet — register it on "
                "the Evidence page, then come back here."
            )
            return
        chosen = self.evidence_combo.currentData()
        if chosen is None:
            hint.setText(
                "Choose evidence, then use New Job to configure its operation "
                "and create an examination job. Select a pending or failed job to start it."
            )
            return
        for ev in evidence_list:
            if getattr(ev, "id", None) == chosen:
                status = _enum_text(getattr(ev, "status", ""))
                hint.setText(
                    f"Selected: {getattr(ev, 'evidence_id', chosen)} — "
                    f"{getattr(ev, 'name', 'evidence')} ({status}). "
                    "Use New Job, or select a job below to start it."
                )
                return

    def _on_evidence_changed(self, _index: int = 0):
        """Keep the hint and the selected job in step with the evidence."""
        self._update_hint()
        evidence_pk = self.evidence_combo.currentData()
        if evidence_pk is None:
            return
        # Jobs are newest first, so this picks the latest one for the evidence.
        for job in getattr(self, "_jobs", []):
            if job.evidence_id == evidence_pk:
                self._select_job(job.job_id)
                return

    def start_examination_for(self, evidence_pk: int) -> None:
        """Show this page ready for ``evidence_pk`` (used by the Evidence page)."""
        self.refresh()
        index = self.evidence_combo.findData(evidence_pk)
        if index >= 0:
            self.evidence_combo.setCurrentIndex(index)

    def _supported_operations(self) -> list[dict]:
        """Operations offered by the page, falling back to the enum."""
        service = getattr(self, "exam_service", None)
        if service is not None:
            try:
                return service.get_supported_operations()
            except Exception:
                pass
        # The worker does not implement every enum value (metadata_extraction
        # is declared but unsupported), so the fallback skips those too.
        return [
            {
                "operation": op.value,
                "name": op.value.replace("_", " ").title(),
                "description": "",
                "supported": True,
            }
            for op in ExaminationOperation
            if op is not ExaminationOperation.METADATA_EXTRACTION
        ]

    def on_page_shown(self):
        """Reload evidence and jobs whenever the page is opened."""
        self.refresh()

    def refresh(self):
        self._ensure_services()
        # Evidence loading is independent of examination-service availability.
        self._populate_evidence_combo()

        if not self.exam_service or not self.case_context:
            self._jobs = []
            self.jobs_model.populate([])
            self._selected_job = None
            self._update_buttons()
            return

        previous = self._selected_job.job_id if self._selected_job else None
        try:
            jobs = self.exam_service.list_jobs(self.case_context.case_id)
            self._jobs = list(jobs or [])
            self.jobs_model.populate(self._jobs)
        except Exception as exc:
            self._jobs = []
            self.jobs_model.populate([])
            self._selected_job = None
            self._update_buttons()
            self.results_log.append(f"Unable to refresh examination jobs: {exc}")
            return

        if previous and self._select_job(previous):
            return
        self._selected_job = None
        self._update_buttons()

    def _update_buttons(self):
        job = self._selected_job
        running = job is not None and job.status == JobStatus.RUNNING
        progress_message = (job.progress_message or "").lower() if job else ""
        paused = progress_message.startswith("paused")
        pausing = progress_message.startswith("pausing")
        cancelling = progress_message.startswith("cancelling")
        self.start_btn.setText("Running..." if self._starting else "Start Examination")
        self.start_btn.setEnabled(
            not self._starting
            and job is not None
            and job.status in (
                JobStatus.PENDING,
                JobStatus.FAILED,
                JobStatus.INTERRUPTED,
            )
        )
        self.cancel_btn.setEnabled(
            job is not None
            and job.status in (JobStatus.PENDING, JobStatus.RUNNING)
            and not cancelling
        )
        self.cancel_btn.setToolTip(
            "Cancellation requested; waiting for the next safe checkpoint."
            if cancelling else
            "Cancel a pending job, or request that a running examination stop "
            "at its next safe checkpoint."
        )
        self.pause_btn.setText("Resume" if paused else "Pausing…" if pausing else "Pause")
        self.pause_btn.setToolTip(
            "Resume this paused examination."
            if paused else
            "Pause a running examination at its next safe checkpoint."
        )
        self.pause_btn.setEnabled(running and not pausing)
        self.delete_job_btn.setEnabled(
            not self._starting
            and job is not None
            and job.status != JobStatus.RUNNING
        )

    def _select_job(self, job_id: str) -> bool:
        """Select the row for ``job_id`` in the jobs table."""
        for row, job in enumerate(self._jobs):
            if job.job_id == job_id:
                self.jobs_table.selectRow(row)
                self._selected_job = job
                self._update_buttons()
                return True
        return False

    def _on_job_selected(self, *args):
        indexes = self.jobs_table.selectionModel().selectedRows()
        if not indexes:
            self._selected_job = None
            self._update_buttons()
            return
        row = indexes[0].row()
        if 0 <= row < len(self._jobs):
            self._selected_job = self._jobs[row]
        else:
            self._selected_job = None
        self._update_buttons()
        if self._selected_job:
            self._show_job_results(self._selected_job)


    def _show_job_results(self, job: ExaminationJob):
        self.results_log.clear()
        self.results_log.append(f"Job: {job.job_id}")
        self.results_log.append(f"Operation: {_enum_text(job.operation)}")
        self.results_log.append(f"Status: {_enum_text(job.status)}")
        progress_text = (
            f"~{job.progress_percent}% (estimated)"
            if job.status == JobStatus.RUNNING else f"{job.progress_percent}%"
        )
        self.results_log.append(f"Progress: {progress_text}")
        self.results_log.append(f"Message: {job.progress_message or 'N/A'}")
        try:
            stored = json.loads(job.parameters_json) if job.parameters_json else {}
        except (TypeError, json.JSONDecodeError):
            stored = {}
        if stored:
            self.results_log.append(f"Parameters: {parameter_summary(stored)}")
            self.results_log.append(f"Raw parameters: {json.dumps(stored, sort_keys=True)}")
        if job.error_message:
            self.results_log.append(f"Error: {job.error_message}")
        self.results_log.append("---")

        self.results_summary.clear()
        for result in job.results:
            self.results_summary.append(f"Type: {result.result_type}")
            self.results_summary.append(f"Summary: {result.summary or 'N/A'}")
            self.results_summary.append(f"Artifacts: {result.artifact_count}")
            self.results_summary.append("---")

    def _on_start(self):
        if not self.exam_service:
            QMessageBox.warning(
                self, "Examination unavailable",
                "The examination service has not been initialized."
            )
            return

        if not self._selected_job:
            QMessageBox.information(
                self, "Select examination job",
                "Select an existing job, or choose New Job to create one first."
            )
            return

        if self._selected_job.status not in (
            JobStatus.PENDING, JobStatus.FAILED, JobStatus.INTERRUPTED
        ):
            QMessageBox.information(
                self, "Job cannot be started",
                f"This job is currently {_enum_text(self._selected_job.status)}."
            )
            return

        if self._starting:
            return

        import threading

        job_pk = self._selected_job.id
        self._active_job_id = self._selected_job.job_id
        self._starting = True
        self._last_progress_message = None
        # Clear the previous attempt's error before showing this run's progress.
        self.results_log.clear()
        self.results_summary.clear()
        self.results_log.append(f"Job: {self._active_job_id}")
        self.results_log.append(f"Operation: {_enum_text(self._selected_job.operation)}")
        self.results_log.append("Status: starting")
        self.operation_progress.setValue(0)
        self.operation_progress.setFormat("Starting examination…")
        self.operation_progress.show()
        self._progress_timer.start()
        self._update_buttons()
        self.results_log.append(
            f"Starting examination job {self._active_job_id} "
            f"({_enum_text(self._selected_job.operation)})..."
        )
        self.results_log.append("Waiting for the forensic worker to finish...")

        # Finish any open read transaction before the worker session writes.
        try:
            self.exam_service.session.commit()
        except Exception:
            self.exam_service.session.rollback()

        self._job_thread = threading.Thread(
            target=self._run_job, args=(job_pk,), daemon=True
        )
        self._job_thread.start()

    def _run_job(self, job_pk: int):
        """Run one job in a background thread with its own session.

        Sessions are not thread-safe, so the page's session is never used
        here. The service commits its own work, which is what makes the job
        status, results and artifacts survive a restart.
        """
        import asyncio

        from app.db.session import get_session_factory

        session = get_session_factory()()
        message = "Examination finished"
        try:
            service = ExaminationService(session)
            loop = asyncio.new_event_loop()
            try:
                asyncio.set_event_loop(loop)
                ok = loop.run_until_complete(service.start_job(job_pk))
                loop.run_until_complete(service.close())
            finally:
                loop.close()

            job = service.get_job(job_pk)
            if job is None:
                message = "The examination job no longer exists."
            elif job.status == JobStatus.CANCELLED:
                message = f"Job {job.job_id} cancelled."
            elif ok:
                message = (
                    f"Job {job.job_id} {_enum_text(job.status)}"
                    f" ({job.progress_message or 'done'})."
                )
            else:
                detail = job.error_message or job.progress_message or "unknown error"
                message = f"Job {job.job_id} failed: {detail}"
        except Exception as exc:
            message = f"Failed to start examination: {exc}"
        finally:
            session.close()

        # Emitted from a worker thread; Qt queues it onto the GUI thread.
        self.start_finished.emit(message)

    def _finish_start(self, message: str):
        self._starting = False
        self._progress_timer.stop()
        self.operation_progress.hide()
        if self.exam_service:
            try:
                # Another session wrote the job's new state.
                self.exam_service.session.expire_all()
            except Exception:
                pass
        self.refresh()
        if self._active_job_id:
            self._select_job(self._active_job_id)
            self._active_job_id = None
        self._update_buttons()
        # Appended last: selecting the job rewrites the log with its details.
        self.results_log.append(message)

    def _refresh_running_progress(self):
        """Read the worker's committed progress without blocking examination."""
        now = datetime.now(timezone.utc)
        for row, job in enumerate(self._jobs):
            elapsed_text, eta_text = _job_time_text(job, now)
            self.jobs_model.item(row, 5).setText(elapsed_text)
            self.jobs_model.item(row, 6).setText(eta_text)

        if not self._starting or not self._active_job_id or not self.exam_service:
            return
        try:
            session = self.exam_service.session
            session.expire_all()
            job = self.exam_service.get_job_by_job_id(self._active_job_id)
            if not job:
                return
            percent = min(99, max(0, int(job.progress_percent or 0)))
            message = job.progress_message or "Examining evidence"
            elapsed_text, eta_text = _job_time_text(job, now)
            self.operation_progress.setValue(percent)
            self.operation_progress.setFormat(
                f"~{percent}%  ·  Elapsed {elapsed_text}  ·  ETA {eta_text}  —  {message}"
            )
            for row, listed_job in enumerate(self._jobs):
                if listed_job.job_id == self._active_job_id:
                    display_status = (
                        "cancelling" if (job.progress_message or "").lower().startswith(
                            "cancelling"
                        ) else
                        "paused" if (job.progress_message or "").lower().startswith(
                            ("paused", "pausing")
                        ) else _enum_text(job.status)
                    )
                    self.jobs_model.item(row, 3).setText(display_status)
                    self.jobs_model.item(row, 4).setText(f"~{percent}%")
                    self.jobs_model.item(row, 3).setForeground(
                        Color.WARNING if display_status in ("paused", "cancelling")
                        else Color.PRIMARY
                    )
                    break
            if message != getattr(self, "_last_progress_message", None):
                self.results_log.append(f"Approx. {percent}% — {message}")
                self._last_progress_message = message
            if self._selected_job and self._selected_job.job_id == job.job_id:
                self._update_buttons()
        except Exception:
            # Progress display must never interfere with the running job.
            return

    def _on_cancel(self):
        if not self.exam_service:
            return

        # Prefer the live worker job to a stale/table selection, especially
        # while the examination has just started and the row is being refreshed.
        job = None
        if self._active_job_id:
            active = self.exam_service.get_job_by_job_id(self._active_job_id)
            if active is not None and active.status == JobStatus.RUNNING:
                job = active
        if job is None:
            job = self._selected_job
        if job is None:
            return

        if job.status not in (JobStatus.PENDING, JobStatus.RUNNING):
            QMessageBox.information(
                self, "Job cannot be cancelled",
                f"This job is currently {_enum_text(job.status)}."
            )
            return

        session = self.exam_service.session
        try:
            cancelled = self.exam_service.cancel_job(job.id)
            session.commit()
        except Exception as exc:
            session.rollback()
            QMessageBox.critical(self, "Cancel failed", str(exc))
            return

        if cancelled:
            if job.status == JobStatus.RUNNING:
                self.results_log.append(
                    f"Job {job.job_id}: cancel requested — the worker stops at "
                    "the next filesystem entry."
                )
            else:
                self.results_log.append(f"Job {job.job_id} cancelled.")
        else:
            QMessageBox.information(
                self, "Job cannot be cancelled",
                "The worker did not accept the cancel request. It may already "
                "be finishing; refresh to see its final state."
            )
        try:
            session.expire_all()
        except Exception:
            pass
        self.refresh()

    def _on_pause_resume(self):
        if not self.exam_service:
            return
        job = self._selected_job
        if job is None and self._active_job_id:
            job = self.exam_service.get_job_by_job_id(self._active_job_id)
        if job is None or job.status != JobStatus.RUNNING:
            return
        paused = (job.progress_message or "").lower().startswith("paused")
        if not self.exam_service.pause_job(job.id, pause=not paused):
            self.results_log.append(
                f"Could not {'resume' if paused else 'pause'} job {job.job_id}; "
                "check that the worker is reachable and refresh the job."
            )
        else:
            self.results_log.append(
                f"Job {job.job_id}: {'resume' if paused else 'pause'} requested."
            )
        self.exam_service.session.expire_all()
        self.refresh()

    def _on_delete_job(self):
        if not self._selected_job or not self.exam_service:
            return
        job = self._selected_job
        if job.status == JobStatus.RUNNING:
            QMessageBox.information(
                self, "Job cannot be deleted",
                "A running examination cannot be deleted. Wait for it to finish first.",
            )
            return
        answer = QMessageBox.question(
            self, "Delete Examination Job",
            f"Delete job {job.job_id} ({_enum_text(job.operation)})?\n\n"
            "This removes the job, artifacts produced by that run, and their derived "
            "analysis results. The source evidence remains. This action is audited.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        from app.auth.models import User
        session = self.exam_service.session
        try:
            user = session.get(User, 1)  # TODO: authenticated user
            deleted = self.exam_service.delete_job(job.id, user)
            if not deleted:
                raise ValueError("This job can no longer be deleted")
            session.commit()
            session.expire_all()
            self._selected_job = None
            self.refresh()
        except Exception as exc:
            session.rollback()
            QMessageBox.critical(self, "Delete Failed", str(exc))

    def _on_new_job(self):
        if not self.exam_service or not self.case_context:
            QMessageBox.warning(
                self, "Examination unavailable",
                "The examination service has not been initialized."
            )
            return

        # Reload so evidence registered while this page was open is offered.
        self._populate_evidence_combo()
        if not self._evidence_list:
            QMessageBox.information(
                self, "No evidence",
                "Register evidence for this case on the Evidence page first."
            )
            return

        dialog = NewExamJobDialog(
            self._evidence_list, self, operations=self._supported_operations()
        )
        # Start from whatever is chosen in the page's evidence selector; with
        # nothing chosen, default to the first registered evidence.
        selected = self.evidence_combo.currentData()
        if selected is None and dialog.evidence_combo.count() > 1:
            dialog.evidence_combo.setCurrentIndex(1)
        elif selected is not None:
            index = dialog.evidence_combo.findData(selected)
            if index >= 0:
                dialog.evidence_combo.setCurrentIndex(index)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        try:
            data = dialog.get_data()
        except ValueError as exc:
            QMessageBox.warning(self, "Validation Error", str(exc))
            return
        if not data["evidence_id"]:
            QMessageBox.warning(self, "Validation Error", "Select evidence")
            return

        # Write through the service's own session and commit that session.
        session = self.exam_service.session
        try:
            from app.auth.models import User
            user = session.get(User, 1)  # TODO: get actual current user
            if not user:
                QMessageBox.warning(
                    self, "No User", "Could not identify the signed-in user"
                )
                return
            job = self.exam_service.create_job(
                case_id=self.case_context.case_id,
                evidence_id=data["evidence_id"],
                operation=data["operation"],
                parameters=data["parameters"],
                created_by=user,
            )
            session.commit()
        except Exception as e:
            session.rollback()
            QMessageBox.critical(self, "Error", f"Failed to create job: {e}")
            return

        self.refresh()
        self._select_job(job.job_id)
        QMessageBox.information(self, "Success", f"Job created: {job.job_id}")


class NewExamJobDialog(QDialog):
    def __init__(
        self,
        evidence_list: list[Evidence],
        parent: QWidget | None = None,
        operations: list[dict] | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("New Examination Job")
        self.setModal(True)
        screen = QApplication.primaryScreen()
        available_height = screen.availableGeometry().height() if screen else 800
        dialog_height = min(640, max(420, available_height - 80))
        self.resize(620, dialog_height)

        layout = QVBoxLayout(self)
        layout.setSpacing(Spacing.SM)
        layout.setContentsMargins(Spacing.LG, Spacing.LG, Spacing.LG, Spacing.LG)

        self.form_scroll = QScrollArea()
        self.form_scroll.setWidgetResizable(True)
        self.form_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.form_content = QWidget()
        form_layout = QFormLayout(self.form_content)
        form_layout.setSpacing(Spacing.MD)
        form_layout.setContentsMargins(0, 0, 0, 0)
        self.form_scroll.setWidget(self.form_content)
        layout.addWidget(self.form_scroll, 1)

        self.evidence_combo = QComboBox()
        self.evidence_combo.addItem("Select evidence...", 0)
        for ev in evidence_list:
            self.evidence_combo.addItem(f"{ev.evidence_id} — {ev.name}", ev.id)
        form_layout.addRow("Evidence:", self.evidence_combo)

        # Examination walks a filesystem, so disk images get the full pipeline.
        # Any other evidence is examined as a single artifact.
        hint = QLabel(
            "Disk images (raw/DD/E01) are examined with the full pipeline. "
            "Other files are examined as a single artifact: hash, size, type "
            "and timestamps."
        )
        hint.setWordWrap(True)
        hint.setProperty("muted", True)
        form_layout.addRow("", hint)

        self.operation_combo = QComboBox()
        if operations is None:
            for op in ExaminationOperation:
                self.operation_combo.addItem(op.value.replace("_", " ").title(), op)
        else:
            for op in operations:
                if not op.get("supported", True):
                    continue
                try:
                    value = ExaminationOperation(op["operation"])
                except ValueError:
                    continue
                self.operation_combo.addItem(op["name"], value)
        form_layout.addRow("Operation:", self.operation_combo)

        # Presets are the one-click path; the expander holds the exact numbers.
        self.profile_combo = QComboBox()
        for key, profile in PROFILES.items():
            self.profile_combo.addItem(profile.name, key)
        default_index = self.profile_combo.findData(DEFAULT_PROFILE)
        if default_index >= 0:
            self.profile_combo.setCurrentIndex(default_index)
        form_layout.addRow("Preset:", self.profile_combo)

        self.profile_description = QLabel()
        self.profile_description.setWordWrap(True)
        self.profile_description.setProperty("muted", True)
        form_layout.addRow("", self.profile_description)

        self.advanced_toggle = QToolButton()
        self.advanced_toggle.setText("Advanced parameters")
        self.advanced_toggle.setCheckable(True)
        self.advanced_toggle.setChecked(False)
        self.advanced_toggle.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextBesideIcon
        )
        self.advanced_toggle.setArrowType(Qt.ArrowType.RightArrow)
        form_layout.addRow("", self.advanced_toggle)

        self.advanced_box = QGroupBox()
        advanced_form = QFormLayout(self.advanced_box)
        advanced_form.setContentsMargins(0, 0, 0, 0)
        advanced_form.setSpacing(Spacing.SM)

        self.max_files_spin = QSpinBox()
        self.max_files_spin.setRange(1, 2_000_000)
        self.max_files_spin.setSingleStep(1000)
        self.max_files_spin.setGroupSeparatorShown(True)
        self.max_files_spin.setToolTip(
            "Compatibility field for saved jobs. Current examinations inventory every "
            "discovered entry; this value does not cap the walk."
        )
        advanced_form.addRow("Legacy file cap (not enforced):", self.max_files_spin)

        self.max_file_size_spin = QSpinBox()
        self.max_file_size_spin.setRange(1, 4096)
        self.max_file_size_spin.setSuffix(" MB")
        self.max_file_size_spin.setToolTip(
            "Compatibility field for saved jobs. Readable files are not skipped based "
            "on size; very large files may require substantial memory and time."
        )
        advanced_form.addRow("Legacy size cap (not enforced):", self.max_file_size_spin)

        self.max_text_chars_spin = QSpinBox()
        self.max_text_chars_spin.setRange(0, 2_000_000)
        self.max_text_chars_spin.setSingleStep(1000)
        self.max_text_chars_spin.setGroupSeparatorShown(True)
        self.max_text_chars_spin.setToolTip(
            "Compatibility field for saved jobs. All extracted readable text is retained "
            "and stored in passages; this value does not truncate it."
        )
        advanced_form.addRow("Legacy text cap (not enforced):", self.max_text_chars_spin)
        self.max_files_spin.setEnabled(False)
        self.max_file_size_spin.setEnabled(False)
        self.max_text_chars_spin.setEnabled(False)

        completeness_note = QLabel(
            "Current scans inventory all discovered files, including deleted entries "
            "(metadata only), and retain all readable extracted text. Unsupported "
            "formats are reported as having no extracted text. PDF text, OCR/EXIF, "
            "and media transcription are not currently provided."
        )
        completeness_note.setWordWrap(True)
        completeness_note.setProperty("muted", True)
        advanced_form.addRow("Coverage:", completeness_note)

        self.include_deleted = QCheckBox("Include deleted files (metadata only; always inventoried)")
        self.include_deleted.setEnabled(False)
        advanced_form.addRow("", self.include_deleted)

        self.skip_media = QCheckBox("Skip media content (compatibility option; not enforced)")
        self.skip_media.setEnabled(False)
        advanced_form.addRow("", self.skip_media)

        self.hash_large_files = QCheckBox("Hash large files (readable files are always hashed)")
        self.hash_large_files.setEnabled(False)
        advanced_form.addRow("", self.hash_large_files)

        self.deep_extraction = QCheckBox(
            "Extract SQLite database table text"
        )
        self.deep_extraction.setToolTip(
            "When enabled, IDFA extracts SQLite table names and row values. This "
            "does not perform OCR, PDF text extraction, EXIF parsing, archive "
            "expansion, or media transcription."
        )
        advanced_form.addRow("", self.deep_extraction)

        self.partition_offset_edit = QLineEdit()
        self.partition_offset_edit.setPlaceholderText("Auto (first mountable partition)")
        self.partition_offset_edit.setToolTip(
            "Byte offset of the partition to examine. Leave blank to use the "
            "first partition that mounts. Offsets are listed by Partition Analysis."
        )
        advanced_form.addRow("Partition offset:", self.partition_offset_edit)

        self.timeout_spin = QSpinBox()
        self.timeout_spin.setRange(30, 86_400)
        self.timeout_spin.setSuffix(" s")
        advanced_form.addRow("Job timeout:", self.timeout_spin)

        self.advanced_box.setVisible(False)
        form_layout.addRow("", self.advanced_box)

        self.hash_note = QLabel("SHA-256 is always computed for stored content.")
        self.hash_note.setProperty("muted", True)
        self.hash_note.setWordWrap(True)
        form_layout.addRow("", self.hash_note)

        self.profile_combo.currentIndexChanged.connect(self._apply_profile)
        self.advanced_toggle.toggled.connect(self._toggle_advanced)
        self._apply_profile()

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _toggle_advanced(self, shown: bool):
        self.advanced_box.setVisible(shown)
        self.advanced_toggle.setArrowType(
            Qt.ArrowType.DownArrow if shown else Qt.ArrowType.RightArrow
        )
        # Keep the dialog within the screen; the form scrolls when advanced
        # controls exceed the available height, while actions stay visible.
        self.form_scroll.verticalScrollBar().setValue(0)

    def _apply_profile(self, *_args):
        """Fill the advanced controls from the selected preset."""
        profile_key = self.profile_combo.currentData() or DEFAULT_PROFILE
        profile = PROFILES.get(profile_key) or PROFILES[DEFAULT_PROFILE]
        self.profile_description.setText(profile.description)
        params = profile_parameters(profile_key)

        self.max_files_spin.setValue(int(params["max_files"]))
        self.max_file_size_spin.setValue(int(profile.max_file_size_mb))
        self.max_text_chars_spin.setValue(int(params["max_text_chars"]))
        self.include_deleted.setChecked(bool(params["include_deleted"]))
        self.skip_media.setChecked(bool(params["skip_media"]))
        self.hash_large_files.setChecked(bool(params["hash_large_files"]))
        self.deep_extraction.setChecked(bool(params["deep_extraction"]))
        self.partition_offset_edit.clear()
        self.timeout_spin.setValue(int(params["timeout_seconds"]))

    def get_data(self) -> dict:
        evidence_id = self.evidence_combo.currentData()
        operation = self.operation_combo.currentData()
        if operation is None:
            raise ValueError("Select an operation.")
        # Qt hands str-based enums back as plain strings; store the enum so the
        # service never has to guess.
        try:
            operation = ExaminationOperation(_enum_text(operation))
        except ValueError as exc:
            raise ValueError(f"Unsupported operation: {operation}") from exc

        offset_text = self.partition_offset_edit.text().strip().replace(",", "")
        try:
            partition_offset = int(offset_text) if offset_text else 0
        except ValueError as exc:
            raise ValueError(
                "Partition offset must be a whole number of bytes."
            ) from exc
        if partition_offset < 0:
            raise ValueError("Partition offset cannot be negative.")

        parameters = {
            "profile": self.profile_combo.currentData() or DEFAULT_PROFILE,
            "max_files": self.max_files_spin.value(),
            "max_file_size": self.max_file_size_spin.value() * 1024 * 1024,
            "max_text_chars": self.max_text_chars_spin.value(),
            "include_deleted": self.include_deleted.isChecked(),
            "skip_media": self.skip_media.isChecked(),
            "hash_large_files": self.hash_large_files.isChecked(),
            "deep_extraction": self.deep_extraction.isChecked(),
            "partition_offset": partition_offset,
            "timeout_seconds": self.timeout_spin.value(),
        }
        return {
            "evidence_id": evidence_id if evidence_id else None,
            "operation": operation,
            "parameters": validate_parameters(parameters),
        }
