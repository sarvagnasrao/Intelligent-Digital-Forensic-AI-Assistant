"""Entities & Timeline Page — extracted entities, relationships, timeline, queue.

Three views over the output of the background analysis, plus the queue that
produces it. Everything is read through :class:`AnalysisService`; the page never
queries the database itself.

The relationship view is the important one: every link shows how many artifacts
support it, which artifacts those are, and a confirm/reject control. An edge the
investigator has reviewed is preserved when the graph is rebuilt, so a
re-examination cannot silently undo a decision.
"""
from __future__ import annotations

import json

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
    QTableView,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.analysis.models import RelationshipStatus
from app.artifacts.models import EntityType
from app.ui.base import CaseContext, ResponsivePage
from app.ui.theme.tokens import Color, Spacing, Typography
from app.util.time import format_local_date

ENTITY_TAB_LIMIT = 1000
TIMELINE_TAB_LIMIT = 2000
RELATIONSHIP_TAB_LIMIT = 1000


def _enum_value(value) -> str:
    return str(getattr(value, "value", value))


def _readable(value: str) -> str:
    return _enum_value(value).replace("_", " ")


def _muted(text: str) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    label.setProperty("muted", True)
    label.setStyleSheet(f"color: {Color.TEXT_MUTED.name()};")
    return label


class EntitiesTimelinePage(ResponsivePage):
    """Entities, relationships, timeline and the analysis queue."""

    def __init__(self, parent: QWidget | None = None):
        self.case_context: CaseContext | None = None
        self.analysis_service = None
        self.runner = None
        self._entities: list = []
        self._relationships: list = []
        self._timeline: list = []
        self._jobs: list = []
        super().__init__(parent=parent)

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------
    def _setup_layout(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(Spacing.LG, Spacing.LG, Spacing.LG, Spacing.LG)
        layout.setSpacing(Spacing.MD)

        layout.addWidget(self._build_status_bar())

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_relationships_tab(), "Relationships")
        self.tabs.addTab(self._build_entities_tab(), "Entities")
        self.tabs.addTab(self._build_timeline_tab(), "Timeline")
        self.tabs.addTab(self._build_queue_tab(), "Analysis Queue")
        layout.addWidget(self.tabs, 1)

    def _build_status_bar(self) -> QWidget:
        frame = QFrame()
        frame.setObjectName("AnalysisStatusBar")
        frame.setFrameShape(QFrame.Shape.StyledPanel)
        row = QHBoxLayout(frame)
        row.setContentsMargins(Spacing.MD, Spacing.SM, Spacing.MD, Spacing.SM)
        row.setSpacing(Spacing.MD)

        self.status_label = QLabel("Analysis idle")
        self.status_label.setFont(
            QFont(Typography.FONT_FAMILY, Typography.BODY_SM[0], QFont.Weight.Bold)
        )
        row.addWidget(self.status_label)

        self.status_detail = _muted("")
        row.addWidget(self.status_detail, 1)

        self.queue_progress = QProgressBar()
        self.queue_progress.setRange(0, 100)
        self.queue_progress.setFixedWidth(160)
        self.queue_progress.hide()
        row.addWidget(self.queue_progress)

        self.run_now_btn = QPushButton("Run analysis now")
        self.run_now_btn.setToolTip(
            "Queue analysis for any examination that has not been analysed yet."
        )
        self.run_now_btn.clicked.connect(self._on_run_now)
        row.addWidget(self.run_now_btn)

        self.pause_btn = QPushButton("Pause")
        self.pause_btn.setProperty("secondary", True)
        self.pause_btn.clicked.connect(self._on_toggle_pause)
        row.addWidget(self.pause_btn)

        return frame

    def _build_entities_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(Spacing.MD)

        row = QHBoxLayout()
        row.addWidget(QLabel("Type:"))
        self.entity_type_filter = QComboBox()
        self.entity_type_filter.addItem("All types", "")
        for entity_type in EntityType:
            self.entity_type_filter.addItem(_readable(entity_type.value), entity_type.value)
        self.entity_type_filter.currentIndexChanged.connect(self._refresh_entities)
        row.addWidget(self.entity_type_filter)

        self.entity_search = QLineEdit()
        self.entity_search.setPlaceholderText("Filter by value…")
        self.entity_search.textChanged.connect(self._refresh_entities)
        row.addWidget(self.entity_search, 1)

        self.entity_summary = _muted("")
        row.addWidget(self.entity_summary)
        layout.addLayout(row)

        self.entity_table = QTableView()
        self.entity_model = QStandardItemModel()
        self.entity_model.setHorizontalHeaderLabels(
            ["Type", "Value", "Artifact", "Review tier", "Confidence", "Extracted by"]
        )
        self.entity_table.setModel(self.entity_model)
        self.entity_table.setAlternatingRowColors(True)
        self.entity_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.entity_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.entity_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.entity_table.verticalHeader().setVisible(False)
        header = self.entity_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        self.entity_table.doubleClicked.connect(self._on_entity_activated)
        layout.addWidget(self.entity_table, 1)

        self.entity_hint = _muted(
            "Entities are extracted automatically after each examination. "
            "Double-click one to see the artifacts it links."
        )
        layout.addWidget(self.entity_hint)
        return tab

    def _build_relationships_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(Spacing.MD)

        row = QHBoxLayout()
        row.addWidget(QLabel("Status:"))
        self.rel_status_filter = QComboBox()
        for label, value in (
            ("Pending review", RelationshipStatus.PENDING.value),
            ("Confirmed", RelationshipStatus.CONFIRMED.value),
            ("Rejected", RelationshipStatus.REJECTED.value),
            ("All", ""),
        ):
            self.rel_status_filter.addItem(label, value)
        self.rel_status_filter.currentIndexChanged.connect(self._refresh_relationships)
        row.addWidget(self.rel_status_filter)

        row.addWidget(QLabel("Kind:"))
        self.rel_kind_filter = QComboBox()
        self.rel_kind_filter.addItem("All kinds", "")
        self.rel_kind_filter.addItem("Shared entity", "shared_entity")
        self.rel_kind_filter.addItem("Related artifacts", "related_artifacts")
        self.rel_kind_filter.addItem("Duplicate content", "duplicate_content")
        self.rel_kind_filter.currentIndexChanged.connect(self._refresh_relationships)
        row.addWidget(self.rel_kind_filter)

        self.rel_search = QLineEdit()
        self.rel_search.setPlaceholderText("Filter by entity value…")
        self.rel_search.textChanged.connect(self._refresh_relationships)
        row.addWidget(self.rel_search, 1)

        self.rel_summary = _muted("")
        row.addWidget(self.rel_summary)
        layout.addLayout(row)

        splitter = QSplitter(Qt.Orientation.Vertical)

        self.rel_table = QTableView()
        self.rel_model = QStandardItemModel()
        self.rel_model.setHorizontalHeaderLabels(
            ["Left", "Right", "Kind", "Shared", "Score", "Status"]
        )
        self.rel_table.setModel(self.rel_model)
        self.rel_table.setAlternatingRowColors(True)
        self.rel_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.rel_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.rel_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.rel_table.verticalHeader().setVisible(False)
        header = self.rel_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        self.rel_table.selectionModel().selectionChanged.connect(
            self._on_relationship_selected
        )
        splitter.addWidget(self.rel_table)

        detail = QFrame()
        detail.setFrameShape(QFrame.Shape.StyledPanel)
        detail_layout = QVBoxLayout(detail)
        detail_layout.setContentsMargins(Spacing.MD, Spacing.MD, Spacing.MD, Spacing.MD)
        detail_layout.setSpacing(Spacing.SM)

        self.rel_detail = QLabel("Select a relationship to see the evidence behind it.")
        self.rel_detail.setWordWrap(True)
        self.rel_detail.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        detail_layout.addWidget(self.rel_detail)

        self.rel_evidence = QTextEdit()
        self.rel_evidence.setReadOnly(True)
        self.rel_evidence.setMaximumHeight(140)
        self.rel_evidence.setFont(
            QFont(Typography.FONT_FAMILY, Typography.MONO_SM[0])
        )
        detail_layout.addWidget(self.rel_evidence, 1)

        buttons = QHBoxLayout()
        self.confirm_btn = QPushButton("Confirm")
        self.confirm_btn.clicked.connect(
            lambda: self._review_relationship(RelationshipStatus.CONFIRMED)
        )
        buttons.addWidget(self.confirm_btn)

        self.reject_btn = QPushButton("Reject")
        self.reject_btn.setProperty("secondary", True)
        self.reject_btn.clicked.connect(
            lambda: self._review_relationship(RelationshipStatus.REJECTED)
        )
        buttons.addWidget(self.reject_btn)

        self.reset_btn = QPushButton("Back to pending")
        self.reset_btn.setProperty("secondary", True)
        self.reset_btn.clicked.connect(
            lambda: self._review_relationship(RelationshipStatus.PENDING)
        )
        buttons.addWidget(self.reset_btn)
        buttons.addStretch()
        self.rel_review_note = _muted("")
        buttons.addWidget(self.rel_review_note)
        detail_layout.addLayout(buttons)

        splitter.addWidget(detail)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter, 1)

        self.rel_hint = _muted(
            "A link needs at least two artifacts, or two exact identifiers "
            "(e-mail, phone, wallet, digest) in one artifact. A value that "
            "appears across most of the case is treated as a hub and skipped."
        )
        layout.addWidget(self.rel_hint)
        return tab

    def _build_timeline_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(Spacing.MD)

        row = QHBoxLayout()
        row.addWidget(QLabel("Event:"))
        self.tl_type_filter = QComboBox()
        self.tl_type_filter.currentIndexChanged.connect(self._refresh_timeline)
        row.addWidget(self.tl_type_filter)

        self.tl_search = QLineEdit()
        self.tl_search.setPlaceholderText("Filter timeline…")
        self.tl_search.textChanged.connect(self._refresh_timeline)
        row.addWidget(self.tl_search, 1)

        self.tl_summary = _muted("")
        row.addWidget(self.tl_summary)
        layout.addLayout(row)

        self.timeline_table = QTableView()
        self.timeline_model = QStandardItemModel()
        self.timeline_model.setHorizontalHeaderLabels(
            ["Timestamp (IST)", "Event", "Title", "Path", "Certainty"]
        )
        self.timeline_table.setModel(self.timeline_model)
        self.timeline_table.setAlternatingRowColors(True)
        self.timeline_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.timeline_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.timeline_table.verticalHeader().setVisible(False)
        header = self.timeline_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.timeline_table, 1)

        layout.addWidget(_muted(
            "File created, modified and accessed times from the examined "
            "artifacts, newest first. Times shown in IST."
        ))
        return tab

    def _build_queue_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(Spacing.MD)

        row = QHBoxLayout()
        self.queue_summary = _muted("")
        row.addWidget(self.queue_summary, 1)

        self.queue_refresh_btn = QPushButton("Refresh")
        self.queue_refresh_btn.setProperty("secondary", True)
        self.queue_refresh_btn.clicked.connect(self.refresh)
        row.addWidget(self.queue_refresh_btn)

        self.retry_btn = QPushButton("Retry")
        self.retry_btn.setProperty("secondary", True)
        self.retry_btn.clicked.connect(self._on_retry)
        row.addWidget(self.retry_btn)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setProperty("secondary", True)
        self.cancel_btn.clicked.connect(self._on_cancel)
        row.addWidget(self.cancel_btn)
        layout.addLayout(row)

        self.queue_table = QTableView()
        self.queue_model = QStandardItemModel()
        self.queue_model.setHorizontalHeaderLabels(
            ["Job", "Evidence", "Status", "Progress", "Entities", "Relationships", "Detail"]
        )
        self.queue_table.setModel(self.queue_model)
        self.queue_table.setAlternatingRowColors(True)
        self.queue_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.queue_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.queue_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.queue_table.verticalHeader().setVisible(False)
        header = self.queue_table.horizontalHeader()
        for column in (0, 1, 2, 3, 4, 5):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.queue_table, 1)

        layout.addWidget(_muted(
            "One analysis at a time. It waits while an examination is running, "
            "so a scan is never slowed down. Progress is committed in batches, "
            "so cancelling keeps what has already been extracted."
        ))
        return tab

    # ------------------------------------------------------------------
    # Wiring
    # ------------------------------------------------------------------
    def set_analysis_service(self, service) -> None:
        self.analysis_service = service
        self.refresh()

    def set_runner(self, runner) -> None:
        """Attach the background runner and mirror its state in the status bar."""
        self.runner = runner
        runner.status_changed.connect(self._on_runner_status)
        runner.job_started.connect(self._on_runner_started)
        runner.job_progress.connect(self._on_runner_progress)
        runner.job_finished.connect(self._on_runner_finished)
        runner.queue_changed.connect(self._on_queue_changed)
        self._sync_pause_button()

    def set_case_context(self, context: CaseContext):
        self.case_context = context
        if self.runner is not None:
            self.runner.set_case(getattr(context, "case_id", None))
        self.refresh()

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------
    def refresh(self) -> None:
        if self.analysis_service is None or self.case_context is None:
            return
        self._refresh_entities()
        self._refresh_relationships()
        self._refresh_timeline()
        self._refresh_queue()

    def _refresh_entities(self) -> None:
        if self.analysis_service is None or self.case_context is None:
            return
        case_id = self.case_context.case_id
        type_value = self.entity_type_filter.currentData() or ""
        entity_type = EntityType(type_value) if type_value else None
        query = self.entity_search.text().strip() or None

        self._entities = self.analysis_service.list_entities(
            case_id, entity_type=entity_type, query=query, limit=ENTITY_TAB_LIMIT
        )
        counts = self.analysis_service.entity_type_counts(case_id)
        total = sum(counts.values())

        self.entity_model.removeRows(0, self.entity_model.rowCount())
        for entity in self._entities:
            artifact_name = ""
            artifact = getattr(entity, "artifact", None)
            if artifact is not None:
                artifact_name = f"{artifact.name} ({artifact.artifact_id})"
            confidence = float(entity.confidence)
            extractor = entity.extractor or ""
            if extractor == "llm":
                review_tier = "Higher confidence" if confidence >= 0.8 else "Candidate"
            else:
                review_tier = "Rule-based"
            row = [
                QStandardItem(_readable(entity.entity_type)),
                QStandardItem(entity.value),
                QStandardItem(artifact_name),
                QStandardItem(review_tier),
                QStandardItem(f"{confidence:.2f}"),
                QStandardItem(extractor),
            ]
            tooltip = (
                f"Type: {_readable(entity.entity_type)}\n"
                f"Value: {entity.value}\n"
                f"Review tier: {review_tier}\n"
                f"Confidence: {confidence:.2f}\n"
                f"Normalised: {entity.normalized_value or ''}\n"
                f"Artifact: {artifact_name or 'N/A'}\n\n"
                f"Source quote/context (verify against the artifact):\n"
                f"{entity.context_snippet or 'No quote/context recorded.'}"
            )
            for cell in row:
                cell.setEditable(False)
                cell.setToolTip(tooltip)
            self.entity_model.appendRow(row)

        if total == 0:
            self.entity_summary.setText("No entities yet")
        else:
            breakdown = ", ".join(
                f"{_readable(key)} {value:,}" for key, value in sorted(counts.items())
            )
            shown = len(self._entities)
            self.entity_summary.setText(
                f"{shown:,} shown of {total:,} — {breakdown}"
            )

    def _refresh_relationships(self) -> None:
        if self.analysis_service is None or self.case_context is None:
            return
        case_id = self.case_context.case_id
        status_value = self.rel_status_filter.currentData() or ""
        status = RelationshipStatus(status_value) if status_value else None
        kind = self.rel_kind_filter.currentData() or None
        query = self.rel_search.text().strip().lower()

        rows = self.analysis_service.list_relationships(
            case_id, status=status, kind=kind, limit=RELATIONSHIP_TAB_LIMIT
        )
        if query:
            rows = [
                row for row in rows
                if query in (row.left_value or "").lower()
                or query in (row.right_value or "").lower()
                or query in (row.details_json or "").lower()
            ]
        self._relationships = rows
        labels = self._artifact_label_map()

        self.rel_model.removeRows(0, self.rel_model.rowCount())
        for row in rows:
            left = self._side_label(row.left_type, row.left_value, labels)
            right = self._side_label(row.right_type, row.right_value, labels)
            cells = [
                QStandardItem(left),
                QStandardItem(right),
                QStandardItem(_readable(row.kind.value)),
                QStandardItem(str(row.shared_count)),
                QStandardItem(f"{float(row.score):.2f}"),
                QStandardItem(_readable(row.status.value)),
            ]
            details = _loads(row.details_json)
            tooltip = details.get("sample") or ""
            for cell in cells:
                cell.setEditable(False)
                if tooltip:
                    cell.setToolTip(tooltip)
            self.rel_model.appendRow(cells)

        counts = self.analysis_service.relationship_counts(case_id)
        self.rel_summary.setText(
            f"{len(rows):,} shown — {counts.get('pending', 0):,} pending, "
            f"{counts.get('confirmed', 0):,} confirmed, "
            f"{counts.get('rejected', 0):,} rejected"
        )
        if not rows:
            self.rel_detail.setText(
                "No relationships yet. They are built after each examination; "
                "use Run analysis now to rebuild them for this case."
            )
            self.rel_evidence.clear()

    def _refresh_timeline(self) -> None:
        if self.analysis_service is None or self.case_context is None:
            return
        case_id = self.case_context.case_id
        rows = self.analysis_service.list_timeline(case_id, limit=TIMELINE_TAB_LIMIT)
        self._timeline = rows

        # Rebuild the event-type filter only when the set of types changed, so
        # refreshing does not reset the investigator's choice.
        types = sorted({row.event_type for row in rows})
        existing = [
            self.tl_type_filter.itemData(index)
            for index in range(self.tl_type_filter.count())
        ]
        if existing[1:] != types:
            current = self.tl_type_filter.currentData()
            self.tl_type_filter.blockSignals(True)
            self.tl_type_filter.clear()
            self.tl_type_filter.addItem("All events", "")
            for event_type in types:
                self.tl_type_filter.addItem(_readable(event_type), event_type)
            index = self.tl_type_filter.findData(current or "")
            self.tl_type_filter.setCurrentIndex(max(0, index))
            self.tl_type_filter.blockSignals(False)

        selected_type = self.tl_type_filter.currentData() or ""
        query = self.tl_search.text().strip().lower()
        visible = [
            row for row in rows
            if (not selected_type or row.event_type == selected_type)
            and (
                not query
                or query in (row.title or "").lower()
                or query in (row.description or "").lower()
            )
        ]

        self.timeline_model.removeRows(0, self.timeline_model.rowCount())
        for event in visible:
            cells = [
                QStandardItem(format_local_date(event.timestamp, "%Y-%m-%d %H:%M:%S")),
                QStandardItem(_readable(event.event_type)),
                QStandardItem(event.title),
                QStandardItem(event.description or ""),
                QStandardItem(event.certainty),
            ]
            for cell in cells:
                cell.setEditable(False)
            self.timeline_model.appendRow(cells)

        self.tl_summary.setText(f"{len(visible):,} of {len(rows):,} events")

    def _refresh_queue(self) -> None:
        if self.analysis_service is None or self.case_context is None:
            return
        case_id = self.case_context.case_id
        self._jobs = self.analysis_service.list_jobs(case_id, limit=50)

        self.queue_model.removeRows(0, self.queue_model.rowCount())
        for job in self._jobs:
            evidence = getattr(job, "evidence", None)
            evidence_label = (
                f"{evidence.evidence_id} — {evidence.name}"
                if evidence is not None else f"#{job.evidence_id}"
            )
            detail = job.error_message or job.progress_message or ""
            cells = [
                QStandardItem(job.job_id),
                QStandardItem(evidence_label),
                QStandardItem(_readable(job.status.value)),
                QStandardItem(f"{job.progress_percent}%"),
                QStandardItem(f"{job.entity_count:,}"),
                QStandardItem(f"{job.relationship_count:,}"),
                QStandardItem(detail),
            ]
            for cell in cells:
                cell.setEditable(False)
                cell.setToolTip(detail)
            self.queue_model.appendRow(cells)

        counts = self.analysis_service.counts(case_id)
        self.queue_summary.setText(
            f"{counts.get('pending', 0):,} queued, {counts.get('running', 0):,} running, "
            f"{counts.get('completed', 0):,} completed, {counts.get('failed', 0):,} failed"
        )

    # ------------------------------------------------------------------
    # Entity → relationship drill-down
    # ------------------------------------------------------------------
    def _on_entity_activated(self, index) -> None:
        if not (0 <= index.row() < len(self._entities)):
            return
        entity = self._entities[index.row()]
        self.rel_search.setText(entity.value)
        self.tabs.setCurrentIndex(0)
        if not self._relationships:
            QMessageBox.information(
                self,
                "No links yet",
                f"'{entity.value}' is recorded in this case, but nothing else "
                "is linked to it yet.",
            )

    # ------------------------------------------------------------------
    # Relationship review
    # ------------------------------------------------------------------
    def _selected_relationship(self):
        indexes = self.rel_table.selectionModel().selectedRows()
        if not indexes:
            return None
        row = indexes[0].row()
        if 0 <= row < len(self._relationships):
            return self._relationships[row]
        return None

    def _on_relationship_selected(self, *_args) -> None:
        relationship = self._selected_relationship()
        if relationship is None:
            self.rel_detail.setText(
                "Select a relationship to see the evidence behind it."
            )
            self.rel_evidence.clear()
            return

        details = _loads(relationship.details_json)
        artifact_ids = _loads(relationship.artifact_ids_json) or []
        evidence_ids = _loads(relationship.evidence_ids_json) or []
        kind = relationship.kind.value

        if kind == "duplicate_content":
            self.rel_detail.setText(
                f"Identical content ({details.get('content_hash', '')[:16]}…) "
                f"found {relationship.shared_count} times."
            )
        elif kind == "related_artifacts":
            self.rel_detail.setText(
                f"'{details.get('left_name') or relationship.left_value}' and "
                f"'{details.get('right_name') or relationship.right_value}' "
                f"mention {relationship.shared_count} of the same identifier(s)."
            )
        else:
            sample = details.get("sample")
            self.rel_detail.setText(
                f"{_readable(relationship.left_type)} '{relationship.left_value}' and "
                f"{_readable(relationship.right_type)} '{relationship.right_value}' "
                f"appear together in {relationship.shared_count} artifact(s) "
                f"(coverage {float(relationship.score):.0%})."
                + (f"\n\n“{sample}”" if sample else "")
            )

        names = self._artifact_labels(artifact_ids)
        if kind == "related_artifacts":
            lines = [f"Artifacts in this link ({len(artifact_ids)}):"]
        else:
            lines = [f"Supporting artifacts ({len(artifact_ids)}):"]
        if names:
            lines.extend(f"  • {name}" for name in names)
        else:
            lines.append("  (the artifacts are no longer in this case)")
        if kind == "related_artifacts" and details.get("shared"):
            lines.append("")
            lines.append("Shared identifiers:")
            for item in details["shared"]:
                if isinstance(item, dict):
                    lines.append(
                        f"  • {_readable(item.get('type', ''))}: {item.get('value', '')}"
                    )
        lines.append("")
        lines.append(
            "Evidence ids: " + (", ".join(str(value) for value in evidence_ids) or "—")
        )
        if details.get("paths"):
            lines.append("")
            lines.append("Copies:")
            lines.extend(f"  • {path}" for path in details["paths"][:20])
        self.rel_evidence.setPlainText("\n".join(lines))

        if relationship.status != RelationshipStatus.PENDING:
            self.rel_review_note.setText(
                f"Reviewed: {_readable(relationship.status.value)}"
            )
        else:
            self.rel_review_note.setText("")

    def _artifact_labels(self, artifact_ids: list) -> list[str]:
        """Resolve artifact primary keys to readable names."""
        if not artifact_ids or self.analysis_service is None:
            return []
        from sqlalchemy import select

        from app.artifacts.models import Artifact

        session = self.analysis_service.session
        try:
            rows = session.execute(
                select(Artifact.id, Artifact.artifact_id, Artifact.name, Artifact.source_path)
                .where(Artifact.id.in_([int(value) for value in artifact_ids]))
            ).all()
        except Exception:
            return []
        by_id = {row.id: row for row in rows}
        labels = []
        for value in artifact_ids:
            row = by_id.get(int(value))
            if row is None:
                continue
            labels.append(f"{row.name} ({row.artifact_id}) — {row.source_path or 'no path'}")
        return labels

    def _artifact_label_map(self) -> dict[str, str]:
        """Case-wide ``{artifact_id: label}`` for edges keyed by artifact id.

        One query per refresh instead of one per row: the relationship table can
        hold hundreds of rows and every artifact-artifact edge needs two lookups.
        """
        if self.analysis_service is None or self.case_context is None:
            return {}
        from sqlalchemy import select

        from app.artifacts.models import Artifact

        try:
            rows = self.analysis_service.session.execute(
                select(Artifact.artifact_id, Artifact.name, Artifact.source_path)
                .where(Artifact.case_id == self.case_context.case_id)
            ).all()
        except Exception:  # noqa: BLE001 - a label is never worth an exception
            return {}
        return {
            str(row.artifact_id).lower(): f"{row.name} ({row.artifact_id})"
            for row in rows
        }

    def _side_label(self, side_type: str, value: str, labels: dict[str, str]) -> str:
        """Readable text for one side of an edge.

        Entity edges carry a type and a value; artifact edges carry
        ``artifact`` and the human-readable artifact id, which is resolved
        through ``labels`` so the table shows a filename rather than a key.
        """
        if str(side_type).lower() == "artifact":
            return labels.get(str(value).lower(), f"artifact: {value}")
        return f"{_readable(side_type)}: {value}"

    def _review_relationship(self, status: RelationshipStatus) -> None:
        relationship = self._selected_relationship()
        if relationship is None or self.analysis_service is None:
            QMessageBox.information(
                self, "Nothing selected", "Select a relationship first."
            )
            return
        user_id = _current_user_id(self)
        try:
            self.analysis_service.review_relationship(relationship.id, status, user_id)
        except Exception as exc:  # noqa: BLE001
            self.analysis_service.session.rollback()
            QMessageBox.critical(self, "Could not record the decision", str(exc))
            return
        self._refresh_relationships()
        self.rel_review_note.setText(f"Marked {_readable(status.value)}")

    # ------------------------------------------------------------------
    # Queue actions
    # ------------------------------------------------------------------
    def _on_run_now(self) -> None:
        if self.analysis_service is None or self.case_context is None:
            return
        try:
            created = self.analysis_service.enqueue_missing(self.case_context.case_id)
            self.analysis_service.session.commit()
        except Exception as exc:  # noqa: BLE001
            self.analysis_service.session.rollback()
            QMessageBox.critical(self, "Could not queue analysis", str(exc))
            return
        if created:
            self.status_detail.setText(f"Queued {len(created)} analysis job(s)")
        else:
            self.status_detail.setText(
                "Every examination in this case has already been analysed"
            )
        if self.runner is not None:
            self.runner.resume()
        self._refresh_queue()

    def _on_toggle_pause(self) -> None:
        if self.runner is None:
            return
        if self.runner.paused:
            self.runner.resume()
        else:
            self.runner.pause()
        self._sync_pause_button()

    def _sync_pause_button(self) -> None:
        if self.runner is None:
            self.pause_btn.setEnabled(False)
            return
        self.pause_btn.setEnabled(True)
        self.pause_btn.setText("Resume" if self.runner.paused else "Pause")

    def _selected_job(self):
        indexes = self.queue_table.selectionModel().selectedRows()
        if not indexes:
            return None
        row = indexes[0].row()
        if 0 <= row < len(self._jobs):
            return self._jobs[row]
        return None

    def _on_retry(self) -> None:
        job = self._selected_job()
        if job is None or self.analysis_service is None:
            QMessageBox.information(self, "Nothing selected", "Select a job first.")
            return
        if self.analysis_service.retry(job.id):
            self.status_detail.setText(f"{job.job_id} queued again")
            if self.runner is not None:
                self.runner.resume()
        else:
            QMessageBox.information(
                self, "Cannot retry", "This job is already queued or running."
            )
        self._refresh_queue()

    def _on_cancel(self) -> None:
        job = self._selected_job()
        if job is None or self.analysis_service is None:
            QMessageBox.information(self, "Nothing selected", "Select a job first.")
            return
        if not self.analysis_service.cancel(job.id):
            QMessageBox.information(
                self,
                "Cannot cancel",
                "Only a queued or running job can be cancelled.",
            )
        self._refresh_queue()

    # ------------------------------------------------------------------
    # Runner signals
    # ------------------------------------------------------------------
    def _on_runner_status(self, text: str) -> None:
        self.status_label.setText(text)
        self._sync_pause_button()

    def _on_runner_started(self, payload: dict) -> None:
        self.status_label.setText(f"Analysing {payload.get('job_id', '')}")
        self.queue_progress.setValue(0)
        self.queue_progress.show()
        self._refresh_queue()

    def _on_runner_progress(self, payload: dict) -> None:
        percent = int(payload.get("percent") or 0)
        self.queue_progress.setValue(percent)
        message = payload.get("message") or payload.get("stage") or ""
        self.status_detail.setText(message)

    def _on_runner_finished(self, summary: dict) -> None:
        self.queue_progress.hide()
        if summary.get("ok"):
            self.status_label.setText("Analysis complete")
            self.status_detail.setText(summary.get("message") or "")
        elif summary.get("error"):
            self.status_label.setText("Analysis stopped")
            self.status_detail.setText(summary["error"])
        else:
            self.status_label.setText("Analysis cancelled")
            self.status_detail.setText(summary.get("message") or "")
        self.refresh()

    def _on_queue_changed(self, counts: dict) -> None:
        if not isinstance(counts, dict) or not counts:
            return
        self.queue_summary.setText(
            f"{counts.get('pending', 0):,} queued, "
            f"{counts.get('running', 0):,} running, "
            f"{counts.get('completed', 0):,} completed, "
            f"{counts.get('failed', 0):,} failed"
        )


def _loads(value) -> dict | list:
    if not value:
        return {}
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}


def _current_user_id(page: QWidget) -> int | None:
    """Best-effort current user, walking up to whichever shell owns the page."""
    parent = page.parent()
    while parent is not None:
        get_user = getattr(parent, "get_current_user", None)
        if callable(get_user):
            user = get_user()
            if user is not None:
                return getattr(user, "id", None)
        parent = parent.parent()
    return None
