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
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QTableView,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.analysis.models import AnalysisJobStatus, RelationshipStatus
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
    label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
    label.setProperty("muted", True)
    label.setStyleSheet(f"color: {Color.TEXT_MUTED.name()};")
    return label


class _ScrollableDescription(QLabel):
    """Keep wrapped text tall enough for its scroll area at the current width."""

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.setMinimumHeight(max(0, self.heightForWidth(event.size().width())))


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
        self._queue_counts: dict[str, int] = {}
        self._result_counts: dict[str, int] = {}
        super().__init__(parent=parent)

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------
    @staticmethod
    def _empty_state(title: str, description: str) -> QFrame:
        frame = QFrame()
        frame.setObjectName("AnalysisEmptyState")
        frame.setFrameShape(QFrame.Shape.StyledPanel)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(Spacing.XL, Spacing.XL, Spacing.XL, Spacing.XL)
        layout.setSpacing(Spacing.SM)
        heading = QLabel(title)
        heading.setWordWrap(True)
        heading.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        heading.setFont(
            QFont(Typography.FONT_FAMILY, Typography.HEADING_SM[0], QFont.Weight.Bold)
        )
        body = _muted(description)
        body.setAlignment(Qt.AlignmentFlag.AlignCenter)
        frame.empty_title = heading
        frame.empty_description = body
        layout.addStretch(1)
        layout.addWidget(heading)
        layout.addWidget(body)
        layout.addStretch(1)
        return frame

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
        frame.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        frame.setFrameShape(QFrame.Shape.StyledPanel)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(Spacing.MD, Spacing.SM, Spacing.MD, Spacing.SM)
        layout.setSpacing(Spacing.SM)
        row = QHBoxLayout()
        layout.addLayout(row)

        self.status_label = QLabel("No analysis jobs")
        self.status_label.setWordWrap(True)
        self.status_label.setFont(
            QFont(Typography.FONT_FAMILY, Typography.BODY_SM[0], QFont.Weight.Bold)
        )
        row.addWidget(self.status_label, 1)

        self.status_detail = _muted("")
        self.status_detail.hide()

        self.queue_progress = QProgressBar()
        self.queue_progress.setRange(0, 100)
        self.queue_progress.setFixedWidth(160)
        self.queue_progress.hide()
        row.addWidget(self.queue_progress)

        self.run_now_btn = QPushButton("Analyse new examinations")
        self.run_now_btn.setToolTip(
            "Create jobs only for completed examinations without an analysis job. "
            "To retry or re-run an existing job, open Analysis Queue."
        )
        self.run_now_btn.clicked.connect(self._on_run_now)
        actions = QHBoxLayout()
        layout.addLayout(actions)
        actions.addWidget(self.run_now_btn)

        self.manage_jobs_btn = QPushButton("Review / re-run jobs")
        self.manage_jobs_btn.setProperty("secondary", True)
        self.manage_jobs_btn.setToolTip("Open Analysis Queue; select a completed job to re-run it.")
        self.manage_jobs_btn.clicked.connect(self._show_analysis_queue)
        actions.addWidget(self.manage_jobs_btn)

        self.pause_btn = QPushButton("Pause queue")
        self.pause_btn.setProperty("secondary", True)
        self.pause_btn.setToolTip("Pause starting new jobs; the current analysis continues.")
        self.pause_btn.clicked.connect(self._on_toggle_pause)
        actions.addWidget(self.pause_btn)
        actions.addStretch(1)

        layout.addWidget(self.status_detail)

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
        layout.addLayout(row)
        layout.addWidget(self.entity_summary)

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
        self.entity_table.selectionModel().selectionChanged.connect(self._on_entity_selected)
        self.entity_stack = QStackedWidget()
        self.entity_stack.addWidget(self.entity_table)
        self.entity_empty_state = self._empty_state(
            "No entities extracted yet",
            "Run analysis after examining evidence to find identifiers, accounts and named entities.",
        )
        self.entity_stack.addWidget(self.entity_empty_state)
        layout.addWidget(self.entity_stack, 1)

        self.entity_source = QTextEdit()
        self.entity_source.setReadOnly(True)
        self.entity_source.setMaximumHeight(120)
        self.entity_source.setPlaceholderText("Select an entity to inspect its recorded source and context.")
        layout.addWidget(self.entity_source)

        self.entity_hint = _muted(
            "Entities are extracted automatically after each examination. "
            "Select an entity to inspect its source; double-click to filter relationships."
        )
        layout.addWidget(self.entity_hint)
        return tab

    def _build_relationships_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(Spacing.MD)

        self.rel_filters = QGridLayout()
        self.rel_status_label = QLabel("Status:")
        self.rel_status_filter = QComboBox()
        for label, value in (
            ("Unreviewed", RelationshipStatus.PENDING.value),
            ("Confirmed", RelationshipStatus.CONFIRMED.value),
            ("Rejected", RelationshipStatus.REJECTED.value),
            ("All", ""),
        ):
            self.rel_status_filter.addItem(label, value)
        self.rel_status_filter.currentIndexChanged.connect(self._refresh_relationships)
        self.rel_kind_label = QLabel("Kind:")
        self.rel_kind_filter = QComboBox()
        self.rel_kind_filter.addItem("All kinds", "")
        self.rel_kind_filter.addItem("Shared entity", "shared_entity")
        self.rel_kind_filter.addItem("Related artifacts", "related_artifacts")
        self.rel_kind_filter.addItem("Duplicate content", "duplicate_content")
        self.rel_kind_filter.currentIndexChanged.connect(self._refresh_relationships)

        self.rel_search = QLineEdit()
        self.rel_search.setPlaceholderText("Filter by entity value…")
        self.rel_search.textChanged.connect(self._refresh_relationships)
        self.rel_search.setMinimumWidth(100)
        layout.addLayout(self.rel_filters)
        self._layout_relationship_filters()

        self.rel_summary = _muted("")
        layout.addWidget(self.rel_summary)

        splitter = QSplitter(Qt.Orientation.Vertical)

        self.rel_table = QTableView()
        self.rel_model = QStandardItemModel()
        self.rel_model.setHorizontalHeaderLabels(
            ["Left", "Right", "Kind", "Shared", "Score", "Review"]
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
        self.relationship_stack = QStackedWidget()
        self.relationship_stack.addWidget(self.rel_table)
        self.relationship_empty_state = self._empty_state(
            "No relationship candidates",
            "Run analysis after examining evidence. Candidate links appear here with their supporting artifacts for review.",
        )
        self.relationship_stack.addWidget(self.relationship_empty_state)
        splitter.addWidget(self.relationship_stack)

        detail = QFrame()
        self.rel_detail_panel = detail
        detail.setFrameShape(QFrame.Shape.StyledPanel)
        detail_layout = QVBoxLayout(detail)
        detail_layout.setContentsMargins(Spacing.MD, Spacing.MD, Spacing.MD, Spacing.MD)
        detail_layout.setSpacing(Spacing.SM)

        self.rel_detail = _ScrollableDescription("Select a relationship to see the evidence behind it.")
        self.rel_detail.setWordWrap(True)
        self.rel_detail.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        detail_scroll = QScrollArea()
        detail_scroll.setWidgetResizable(True)
        detail_scroll.setFrameShape(QFrame.Shape.NoFrame)
        detail_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        detail_scroll.setWidget(self.rel_detail)
        detail_scroll.setMinimumHeight(45)
        detail_scroll.setMaximumHeight(120)
        detail_layout.addWidget(detail_scroll, 1)

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

        self.reset_btn = QPushButton("Mark unreviewed")
        self.reset_btn.setProperty("secondary", True)
        self.reset_btn.clicked.connect(
            lambda: self._review_relationship(RelationshipStatus.PENDING)
        )
        buttons.addWidget(self.reset_btn)
        buttons.addStretch()
        self.rel_review_controls = QWidget()
        review_layout = QVBoxLayout(self.rel_review_controls)
        review_layout.setContentsMargins(0, 0, 0, 0)
        review_layout.setSpacing(Spacing.SM)
        review_layout.addLayout(buttons)
        self.rel_review_note = _muted("")
        review_layout.addWidget(self.rel_review_note)
        detail_layout.addWidget(self.rel_review_controls)

        splitter.addWidget(detail)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        splitter.setCollapsible(0, False)
        splitter.setCollapsible(1, True)
        splitter.setSizes([620, 130])
        self.rel_evidence.hide()
        self.rel_review_controls.hide()
        self.rel_detail_panel.hide()
        layout.addWidget(splitter, 1)

        self.rel_hint = _muted(
            "Unreviewed links are automatic candidates, not investigator conclusions. "
            "Links are leads, not proof of identity or ownership. Review the source artifacts "
            "and their context before deciding; confirmation records your review, not identity proof."
        )
        layout.addWidget(self.rel_hint)
        return tab

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        if hasattr(self, "rel_filters"):
            self._layout_relationship_filters()

    def _layout_relationship_filters(self) -> None:
        """Keep filters on one row when they fit; wrap search on narrow pages."""
        widgets = (self.rel_status_label, self.rel_status_filter,
                   self.rel_kind_label, self.rel_kind_filter, self.rel_search)
        required = sum(widget.sizeHint().width() for widget in widgets) + 100
        narrow = self.width() < max(760, required)
        for widget in widgets:
            self.rel_filters.removeWidget(widget)
        for column in range(5):
            self.rel_filters.setColumnStretch(column, 0)
        for column, widget in enumerate(widgets[:4]):
            self.rel_filters.addWidget(widget, 0, column)
        if narrow:
            self.rel_filters.addWidget(self.rel_search, 1, 0, 1, 4)
            self.rel_filters.setColumnStretch(3, 1)
        else:
            self.rel_filters.addWidget(self.rel_search, 0, 4)
            self.rel_filters.setColumnStretch(4, 1)

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
        self.tl_search.setPlaceholderText("Filter title, path or source artifact…")
        self.tl_search.textChanged.connect(self._refresh_timeline)
        row.addWidget(self.tl_search, 1)

        self.tl_summary = _muted("")
        layout.addLayout(row)
        layout.addWidget(self.tl_summary)

        self.timeline_table = QTableView()
        self.timeline_model = QStandardItemModel()
        self.timeline_model.setHorizontalHeaderLabels(
            ["Timestamp", "Event", "Title", "Source path", "Source artifact", "Confidence"]
        )
        self.timeline_table.setModel(self.timeline_model)
        self.timeline_table.setAlternatingRowColors(True)
        self.timeline_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.timeline_table.setWordWrap(False)
        self.timeline_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.timeline_table.verticalHeader().setVisible(False)
        header = self.timeline_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        self.timeline_stack = QStackedWidget()
        self.timeline_stack.addWidget(self.timeline_table)
        self.timeline_empty_state = self._empty_state(
            "No timeline events yet",
            "File timestamps are added after analysis. Times use IDFA's display time zone (IST by default).",
        )
        self.timeline_stack.addWidget(self.timeline_empty_state)
        layout.addWidget(self.timeline_stack, 1)

        layout.addWidget(_muted(
            "Events are ordered newest first. Verify timestamps against the source device and its clock settings."
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
        self.queue_table.selectionModel().selectionChanged.connect(self._update_queue_actions)
        self.retry_btn.setEnabled(False)
        self.cancel_btn.setEnabled(False)
        header = self.queue_table.horizontalHeader()
        for column in (0, 1, 2, 3, 4, 5):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)
        self.queue_stack = QStackedWidget()
        self.queue_stack.addWidget(self.queue_table)
        self.queue_empty_state = self._empty_state(
            "No analysis jobs",
            "Use Analyse new examinations for completed examinations without an analysis job.",
        )
        self.queue_stack.addWidget(self.queue_empty_state)
        layout.addWidget(self.queue_stack, 1)

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
        self._result_counts = {}
        self._set_status_detail("")
        self.queue_progress.hide()
        self.refresh()

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------
    def refresh(self) -> None:
        if self.analysis_service is None or self.case_context is None:
            return
        self._refresh_queue()
        self._refresh_entities()
        self._refresh_relationships()
        self._refresh_timeline()

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
        self._result_counts["entities"] = total
        self._sync_analysis_status()

        self.entity_model.removeRows(0, self.entity_model.rowCount())
        self.entity_source.clear()
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
            self.entity_empty_state.empty_title.setText("No entities extracted yet")
            self.entity_empty_state.empty_description.setText(
                "Run analysis after examining evidence to find identifiers, accounts and named entities."
            )
        else:
            breakdown = ", ".join(
                f"{_readable(key)} {value:,}" for key, value in sorted(counts.items())
            )
            shown = len(self._entities)
            self.entity_summary.setText(
                f"{shown:,} shown of {total:,} — {breakdown}"
            )
            self.entity_empty_state.empty_title.setText("No matching entities")
            self.entity_empty_state.empty_description.setText(
                "Change the type filter or search text to see other extracted entities."
            )
        self.entity_stack.setCurrentIndex(1 if not self._entities else 0)

    def _refresh_relationships(self) -> None:
        if self.analysis_service is None or self.case_context is None:
            return
        case_id = self.case_context.case_id
        status_value = self.rel_status_filter.currentData() or ""
        status = RelationshipStatus(status_value) if status_value else None
        kind = self.rel_kind_filter.currentData() or None
        query = self.rel_search.text().strip().lower()

        rows = self.analysis_service.list_relationships(
            case_id, status=status, kind=kind, limit=RELATIONSHIP_TAB_LIMIT + 1
        )
        truncated = len(rows) > RELATIONSHIP_TAB_LIMIT
        rows = rows[:RELATIONSHIP_TAB_LIMIT]
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
                QStandardItem("Unreviewed" if row.status == RelationshipStatus.PENDING
                              else _readable(row.status.value)),
            ]
            details = _loads(row.details_json)
            tooltip = details.get("sample") or ""
            for cell in cells:
                cell.setEditable(False)
                if tooltip:
                    cell.setToolTip(tooltip)
            self.rel_model.appendRow(cells)

        counts = self.analysis_service.relationship_counts(case_id)
        self._result_counts["relationships"] = sum(counts.values())
        self._sync_analysis_status()
        self.rel_summary.setText(
            f"{len(rows):,} shown · {counts.get('pending', 0):,} unreviewed · "
            f"{counts.get('confirmed', 0):,} confirmed · "
            f"{counts.get('rejected', 0):,} rejected"
        )
        if truncated:
            self.rel_summary.setText(
                self.rel_summary.text()
                + f" · Search covers only the top {RELATIONSHIP_TAB_LIMIT:,} by score"
                " for the selected status and kind; change those filters to see other candidates"
            )
        self.relationship_stack.setCurrentIndex(1 if not rows else 0)
        if not rows:
            if sum(counts.values()):
                self.relationship_empty_state.empty_title.setText(
                    "No candidates match these filters"
                )
                self.relationship_empty_state.empty_description.setText(
                    "Change the status, kind or search filters to review other relationships."
                )
            else:
                self.relationship_empty_state.empty_title.setText(
                    "No relationship candidates yet"
                )
                job_states = {
                    job.status for job in self._jobs
                    if job.evidence is not None and job.evidence.removed_at is None
                }
                if job_states & {AnalysisJobStatus.RUNNING, AnalysisJobStatus.PENDING}:
                    guidance = "Analysis is queued or running. Results will appear here when ready."
                elif job_states & {AnalysisJobStatus.FAILED, AnalysisJobStatus.INTERRUPTED}:
                    guidance = "Analysis stopped. Open Analysis Queue to inspect the job and retry it."
                elif AnalysisJobStatus.COMPLETED in job_states:
                    guidance = "Analysis completed without relationship candidates. Review entities and timeline for other results."
                else:
                    guidance = "Examine evidence first, then queue any missing analysis."
                self.relationship_empty_state.empty_description.setText(
                    guidance
                )
            if sum(counts.values()):
                self.rel_detail.setText(
                    "No candidates match these filters. Adjust the filters to see other links."
                )
            else:
                self.rel_detail.setText(
                    "No relationships yet. Run analysis after examining evidence to generate candidates for review."
                )
            self.rel_evidence.clear()
            self.rel_evidence.hide()
            self.rel_review_controls.hide()
            self.rel_detail_panel.hide()
        elif self._selected_relationship() is None:
            self.rel_detail.setText(
                "Select a candidate to inspect its supporting evidence."
            )
            self.rel_evidence.clear()
            self.rel_evidence.hide()
            self.rel_review_controls.hide()
            self.rel_detail_panel.hide()

    def _refresh_timeline(self) -> None:
        if self.analysis_service is None or self.case_context is None:
            return
        case_id = self.case_context.case_id
        rows = self.analysis_service.list_timeline(case_id, limit=TIMELINE_TAB_LIMIT + 1)
        truncated = len(rows) > TIMELINE_TAB_LIMIT
        rows = rows[:TIMELINE_TAB_LIMIT]
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
                or query in self._timeline_source_label(row).lower()
            )
        ]

        self.timeline_model.removeRows(0, self.timeline_model.rowCount())
        for event in visible:
            cells = [
                QStandardItem(format_local_date(event.timestamp, "%Y-%m-%d %H:%M:%S")),
                QStandardItem(_readable(event.event_type)),
                QStandardItem(event.title),
                QStandardItem(event.description or ""),
                QStandardItem(self._timeline_source_label(event)),
                QStandardItem(event.certainty),
            ]
            for cell in cells:
                cell.setEditable(False)
                cell.setToolTip(cell.text())
            self.timeline_model.appendRow(cells)

        self.tl_summary.setText(f"{len(visible):,} of {len(rows):,} events")
        if truncated:
            self.tl_summary.setText(
                self.tl_summary.text()
                + f" · Filters and event types cover only the most recent {TIMELINE_TAB_LIMIT:,} events"
                "; older events are not included"
            )
        if rows and not visible:
            self.timeline_empty_state.empty_title.setText("No events match these filters")
            self.timeline_empty_state.empty_description.setText(
                "Change the event type or search text to show other timeline events."
            )
        else:
            self.timeline_empty_state.empty_title.setText("No timeline events yet")
            self.timeline_empty_state.empty_description.setText(
                "File timestamps are added after analysis. Times use IDFA's display time zone (IST by default)."
            )
        self.timeline_stack.setCurrentIndex(1 if not visible else 0)

    @staticmethod
    def _timeline_source_label(event) -> str:
        artifact = getattr(event, "artifact", None)
        if artifact is None:
            return "—"
        name = getattr(artifact, "name", "") or "Artifact"
        artifact_id = getattr(artifact, "artifact_id", "") or ""
        path = getattr(artifact, "source_path", "") or ""
        label = f"{name} ({artifact_id})" if artifact_id else name
        return f"{label} — {path}" if path else label

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
                if evidence is not None else "Evidence unavailable"
            )
            if evidence is not None and evidence.removed_at is not None:
                evidence_label += " (removed from case)"
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
        self._queue_counts = counts
        self._sync_analysis_status()
        self.queue_summary.setText(
            f"{counts.get('pending', 0):,} queued, {counts.get('running', 0):,} running, "
            f"{counts.get('completed', 0):,} completed, {counts.get('failed', 0):,} failed"
        )
        self.queue_stack.setCurrentIndex(1 if not self._jobs else 0)
        self._update_queue_actions()

    # ------------------------------------------------------------------
    # Entity → relationship drill-down
    # ------------------------------------------------------------------
    def _on_entity_selected(self, *_args) -> None:
        indexes = self.entity_table.selectionModel().selectedRows()
        if not indexes or not 0 <= indexes[0].row() < len(self._entities):
            self.entity_source.clear()
            return
        entity = self._entities[indexes[0].row()]
        artifact = getattr(entity, "artifact", None)
        if artifact is None:
            source = "Source artifact unavailable"
        else:
            source = (f"{getattr(artifact, 'name', '') or 'Artifact'} "
                      f"({getattr(artifact, 'artifact_id', '') or 'ID unavailable'})\n"
                      f"Path: {getattr(artifact, 'source_path', '') or 'not recorded'}")
        self.entity_source.setPlainText(
            f"{source}\n\nRecorded context (verify against the source):\n"
            f"{entity.context_snippet or 'No quote/context recorded.'}"
        )

    def _on_entity_activated(self, index) -> None:
        if not (0 <= index.row() < len(self._entities)):
            return
        entity = self._entities[index.row()]
        self.rel_status_filter.setCurrentIndex(self.rel_status_filter.findData(""))
        self.rel_kind_filter.setCurrentIndex(self.rel_kind_filter.findData(""))
        self.rel_search.setText(entity.value)
        self.tabs.setCurrentIndex(0)
        if not self._relationships:
            QMessageBox.information(
                self,
                "No links yet",
                f"No displayed links match '{entity.value}'. Search covers only "
                f"the top {RELATIONSHIP_TAB_LIMIT:,} candidates by score; other "
                "links may exist outside that limit.",
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
            self.rel_evidence.hide()
            self.rel_review_controls.hide()
            self.rel_detail_panel.hide()
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
                f"mention {relationship.shared_count} of the same identifier(s). "
                "A shared identifier alone does not establish identity or ownership."
            )
        else:
            sample = details.get("sample")
            self.rel_detail.setText(
                f"{_readable(relationship.left_type)} '{relationship.left_value}' and "
                f"{_readable(relationship.right_type)} '{relationship.right_value}' "
                f"appear together in {relationship.shared_count} artifact(s) "
                f"(coverage {float(relationship.score):.0%})."
                + (
                    f"\n\nUnattributed sample (source artifact not recorded; "
                    f"verify against supporting artifacts):\n“{sample}”"
                    if sample else ""
                )
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
                    count = item.get("case_artifact_count")
                    frequency = (
                        f" (seen in {count} case artifact(s))" if isinstance(count, int) else ""
                    )
                    lines.append(
                        f"  • {_readable(item.get('type', ''))}: {item.get('value', '')}{frequency}"
                    )
                    for excerpt in item.get("excerpts", []):
                        if isinstance(excerpt, dict) and excerpt.get("text"):
                            labels = self._artifact_labels([excerpt.get("artifact_id")])
                            label = labels[0] if labels else "Artifact unavailable"
                            lines.append(f"    {label}: {excerpt['text']}")
                    if not item.get("excerpts"):
                        lines.append("    Source excerpts unavailable; inspect artifacts directly.")
            lines.append("Counts reflect extracted mentions, not independent sources or identity.")
        lines.append("")
        lines.append("Evidence sources:")
        evidence_labels = self._evidence_labels(evidence_ids)
        lines.extend(f"  • {label}" for label in evidence_labels)
        if not evidence_labels:
            lines.append("  No evidence sources recorded.")
        if details.get("paths"):
            lines.append("")
            lines.append("Copies:")
            lines.extend(f"  • {path}" for path in details["paths"][:20])
        self.rel_evidence.setPlainText("\n".join(lines))
        self.rel_detail_panel.show()
        self.rel_evidence.show()
        self.rel_review_controls.show()

        self.confirm_btn.setVisible(relationship.status != RelationshipStatus.CONFIRMED)
        self.reject_btn.setVisible(relationship.status != RelationshipStatus.REJECTED)
        self.reset_btn.setVisible(relationship.status != RelationshipStatus.PENDING)
        if relationship.status != RelationshipStatus.PENDING:
            self.rel_review_note.setText(
                f"Reviewed: {_readable(relationship.status.value)}"
            )
        else:
            self.rel_review_note.setText("Unreviewed — verify the sources before deciding")

    def _artifact_labels(self, artifact_ids: list) -> list[str]:
        """Resolve artifact primary keys to readable names."""
        if not artifact_ids or self.analysis_service is None or self.case_context is None:
            return []
        from sqlalchemy import select

        from app.artifacts.models import Artifact

        session = self.analysis_service.session
        ids = [int(value) for value in artifact_ids if str(value).isdigit()]
        try:
            rows = session.execute(
                select(Artifact.id, Artifact.artifact_id, Artifact.name, Artifact.source_path)
                .where(Artifact.id.in_(ids), Artifact.case_id == self.case_context.case_id)
            ).all()
        except Exception:
            rows = []
        by_id = {row.id: row for row in rows}
        labels = []
        for value in artifact_ids:
            row = by_id.get(int(value)) if str(value).isdigit() else None
            if row is None:
                labels.append("Artifact unavailable in this case")
                continue
            labels.append(f"{row.name} ({row.artifact_id}) — {row.source_path or 'no path'}")
        return labels

    def _evidence_labels(self, evidence_ids: list) -> list[str]:
        """Resolve recorded database keys only within the current case."""
        if not evidence_ids:
            return []
        from sqlalchemy import select

        from app.evidence.models import Evidence

        ids = [int(value) for value in evidence_ids if str(value).isdigit()]
        rows = []
        if self.analysis_service is not None and self.case_context is not None:
            try:
                rows = self.analysis_service.session.execute(
                    select(Evidence.id, Evidence.evidence_id, Evidence.name, Evidence.removed_at)
                    .where(Evidence.case_id == self.case_context.case_id, Evidence.id.in_(ids))
                ).all()
            except Exception:  # noqa: BLE001 - provenance must not break review
                pass
        by_id = {row.id: row for row in rows}
        labels = []
        for value in evidence_ids:
            row = by_id.get(int(value)) if str(value).isdigit() else None
            if row is None:
                labels.append("Evidence unavailable in this case")
            else:
                label = f"{row.evidence_id} — {row.name}"
                if row.removed_at is not None:
                    label += " (removed from case)"
                labels.append(label)
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
    def _set_status_detail(self, text: str) -> None:
        self.status_detail.setText(text)
        self.status_detail.setVisible(bool(text))

    def _sync_analysis_status(self) -> None:
        counts = self._queue_counts
        pending = counts.get("pending", 0)
        running = counts.get("running", 0)
        completed = counts.get("completed", 0)
        stopped = sum(counts.get(key, 0) for key in ("failed", "interrupted", "cancelled"))
        if running or pending:
            text = f"Analysis: {running:,} running · {pending:,} queued"
        elif completed:
            text = f"Analysis complete · {completed:,} completed job(s) · No jobs queued"
        elif stopped:
            text = "Analysis stopped · No jobs queued"
        else:
            text = "No analysis jobs · Examine evidence to get started"
        if stopped:
            text += f" · {stopped:,} stopped (see Analysis Queue)"
        if self._result_counts:
            text += " · " + " · ".join(
                f"{count:,} {name}" for name, count in self._result_counts.items()
            )
        if self.runner is not None and self.runner.paused:
            text = "Queue paused · " + text
        self.status_label.setText(text)
        self.manage_jobs_btn.setEnabled(bool(sum(counts.values())))

    def _show_analysis_queue(self) -> None:
        self.tabs.setCurrentIndex(3)
        if self._selected_job() is None:
            for index, job in enumerate(self._jobs):
                if job.status == AnalysisJobStatus.COMPLETED:
                    self.queue_table.selectRow(index)
                    break

    def _on_run_now(self) -> None:
        if self.analysis_service is None or self.case_context is None:
            return
        try:
            if not self.analysis_service.config.analysis.enabled:
                self._set_status_detail("Analysis is disabled in Settings.")
                return
            from app.auth.models import User

            user_id = _current_user_id(self)
            user = self.analysis_service.session.get(User, user_id) if user_id is not None else None
            if user is not None:
                self.analysis_service.session.refresh(user)
            created = self.analysis_service.enqueue_missing(
                self.case_context.case_id, created_by=user, manual=True
            )
            self.analysis_service.session.commit()
        except Exception as exc:  # noqa: BLE001
            self.analysis_service.session.rollback()
            QMessageBox.critical(self, "Could not queue analysis", str(exc))
            return
        if created:
            self._set_status_detail(f"Queued {len(created)} analysis job(s)")
        else:
            self._set_status_detail(
                "No new examinations need analysis. "
                "Open Analysis Queue to retry or re-run an existing job."
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
        self._sync_analysis_status()

    def _sync_pause_button(self) -> None:
        if self.runner is None:
            self.pause_btn.setEnabled(False)
            return
        self.pause_btn.setEnabled(True)
        self.pause_btn.setText("Resume queue" if self.runner.paused else "Pause queue")

    def _selected_job(self):
        indexes = self.queue_table.selectionModel().selectedRows()
        if not indexes:
            return None
        row = indexes[0].row()
        if 0 <= row < len(self._jobs):
            return self._jobs[row]
        return None

    def _update_queue_actions(self, *_args):
        job = self._selected_job()
        status = job.status if job else None
        self.retry_btn.setText("Re-run" if status == AnalysisJobStatus.COMPLETED else "Retry")
        self.retry_btn.setToolTip(
            "Run this completed analysis again." if status == AnalysisJobStatus.COMPLETED
            else "Retry a stopped or failed analysis."
        )
        self.retry_btn.setEnabled(status in (
            AnalysisJobStatus.FAILED, AnalysisJobStatus.CANCELLED,
            AnalysisJobStatus.INTERRUPTED, AnalysisJobStatus.COMPLETED,
        ))
        self.cancel_btn.setEnabled(status in (AnalysisJobStatus.PENDING, AnalysisJobStatus.RUNNING))

    def _on_retry(self) -> None:
        job = self._selected_job()
        if job is None or self.analysis_service is None:
            QMessageBox.information(self, "Nothing selected", "Select a job first.")
            return
        if self.case_context is None:
            return
        if job.status in (AnalysisJobStatus.PENDING, AnalysisJobStatus.RUNNING):
            self._update_queue_actions()
            return
        if job.status == AnalysisJobStatus.COMPLETED and QMessageBox.question(
            self, "Re-run completed analysis?",
            "Re-run this job? Extracted results may be rebuilt. "
            "Confirmed and rejected relationship decisions are preserved.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        ) != QMessageBox.StandardButton.Yes:
            return
        from app.auth.models import User
        user_id = _current_user_id(self)
        user = self.analysis_service.session.get(User, user_id) if user_id is not None else None
        if user is not None:
            self.analysis_service.session.refresh(user)
        try:
            retried = self.analysis_service.retry(job.id, self.case_context.case_id, user)
        except PermissionError as exc:
            QMessageBox.warning(self, "Cannot retry", str(exc))
            return
        if retried:
            self._set_status_detail(f"{job.job_id} queued again")
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
        from app.auth.models import User
        user_id = _current_user_id(self)
        user = self.analysis_service.session.get(User, user_id) if user_id is not None else None
        if user is not None:
            self.analysis_service.session.refresh(user)
        try:
            cancelled = self.analysis_service.cancel(job.id, self.case_context.case_id, user)
        except PermissionError as exc:
            QMessageBox.warning(self, "Cannot cancel", str(exc))
            return
        if not cancelled:
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
        # Runner idle messages describe scheduling, not whether results exist.
        self._sync_analysis_status()
        if text not in {
            "Analysis queue empty", "Analysis running", "Analysis paused", "Analysing…"
        }:
            self._set_status_detail(text)
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
        self._set_status_detail(message)

    def _on_runner_finished(self, summary: dict) -> None:
        self.queue_progress.hide()
        if summary.get("ok"):
            self.status_label.setText("Analysis complete")
            self._set_status_detail(summary.get("message") or "")
        elif summary.get("error"):
            self.status_label.setText("Analysis stopped")
            self._set_status_detail(summary["error"])
        else:
            self.status_label.setText("Analysis cancelled")
            self._set_status_detail(summary.get("message") or "")
        self.refresh()

    def _on_queue_changed(self, counts: dict) -> None:
        if not isinstance(counts, dict) or not counts:
            return
        self._queue_counts = counts
        self._sync_analysis_status()
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
