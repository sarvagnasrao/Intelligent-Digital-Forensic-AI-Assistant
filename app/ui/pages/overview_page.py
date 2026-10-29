"""Case Overview Page."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.ui.base import CaseContext, ResponsivePage, StatCard
from app.ui.theme.themed import ThemedWidget
from app.ui.theme.tokens import Color, Spacing, Typography
from app.util.time import format_local_date


class WorkflowCard(ThemedWidget, QFrame):
    """One measurable, non-linear case-work stage with a direct page link."""

    open_requested = Signal(str)

    _STATUS = {
        "complete": ("Complete", "SUCCESS"),
        "in_progress": ("In progress", "TEXT_LINK"),
        "needs_attention": ("Needs attention", "ERROR"),
        "not_started": ("Not started", "TEXT_SECONDARY"),
        "optional": ("Optional", "TEXT_SECONDARY"),
    }

    def __init__(self, title: str, route: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.route = route
        self.setObjectName("WorkflowCard")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setMinimumHeight(126)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(Spacing.MD, Spacing.MD, Spacing.MD, Spacing.MD)
        layout.setSpacing(Spacing.XS)

        top = QHBoxLayout()
        self.title_label = QLabel(title)
        self.title_label.setFont(
            QFont(Typography.FONT_FAMILY, Typography.BODY_MD[0], QFont.Weight.DemiBold)
        )
        top.addWidget(self.title_label, 1)
        self.status_label = QLabel("Not started")
        top.addWidget(self.status_label)
        layout.addLayout(top)

        self.value_label = QLabel("—")
        self.value_label.setFont(
            QFont(Typography.FONT_FAMILY, Typography.HEADING_MD[0], QFont.Weight.Bold)
        )
        layout.addWidget(self.value_label)

        bottom = QHBoxLayout()
        self.detail_label = QLabel("")
        self.detail_label.setWordWrap(True)
        self.detail_label.setProperty("secondaryText", True)
        bottom.addWidget(self.detail_label, 1)
        self.open_button = QPushButton("Open")
        self.open_button.setProperty("secondary", True)
        self.open_button.clicked.connect(lambda: self.open_requested.emit(self.route))
        bottom.addWidget(self.open_button)
        layout.addLayout(bottom)

        self.set_state("not_started", "—", "")

    def set_state(self, status: str, value: str, detail: str) -> None:
        self._status = status
        label, _token = self._STATUS.get(status, self._STATUS["not_started"])
        self.status_label.setText(label)
        self.restyle()
        self.value_label.setText(value)
        self.detail_label.setText(detail)

    def restyle(self, theme: str | None = None) -> None:
        _, token = self._STATUS.get(self._status, self._STATUS["not_started"])
        self.status_label.setStyleSheet(
            f"color: {getattr(Color, token).name()}; font-weight: 600;"
        )


class OverviewPage(ResponsivePage):
    """Case overview landing page."""

    next_action_requested = Signal(str)
    edit_case_requested = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent=parent)
        self.case_context: CaseContext | None = None
        self.case_service = None
        self.activity_rows: list[QLabel] = []

    def _setup_layout(self):
        self.workflow_cards: dict[str, WorkflowCard] = {}
        self.workflow_heading: QLabel | None = None
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll_area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.content_widget = QWidget()
        self.scroll_area.setWidget(self.content_widget)
        outer_layout.addWidget(self.scroll_area)

        layout = QVBoxLayout(self.content_widget)
        layout.setContentsMargins(Spacing.LG, Spacing.LG, Spacing.LG, Spacing.LG)
        layout.setSpacing(Spacing.MD)

        # The shell header already shows case ID, title and investigator.
        # Keep the page header focused on its purpose instead of duplicating it.
        page_header = QHBoxLayout()
        title_stack = QVBoxLayout()
        self.title_label = QLabel("Case overview")
        self.title_label.setProperty("pageTitle", True)
        self.title_label.setFont(
            QFont(Typography.FONT_FAMILY, Typography.HEADING_LG[0], Typography.HEADING_LG[1])
        )
        title_stack.addWidget(self.title_label)
        self.meta_label = QLabel("Evidence processing, review and case activity")
        self.meta_label.setProperty("secondaryText", True)
        title_stack.addWidget(self.meta_label)
        page_header.addLayout(title_stack, 1)
        self.edit_btn = QPushButton("Edit Case")
        self.edit_btn.setProperty("secondary", True)
        self.edit_btn.setFixedWidth(120)
        self.edit_btn.clicked.connect(self.edit_case_requested)
        page_header.addWidget(self.edit_btn, alignment=Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(page_header)

        # A small set of active-work KPIs. Historical data is summarized below.
        self.cards_layout = QHBoxLayout()
        self.cards_layout.setSpacing(Spacing.MD)
        self.stat_cards = {
            "evidence": StatCard("Active evidence", "0", "📁", Color.INFO),
            "examinations": StatCard("Examined / active", "0/0", "🔬", Color.PRIMARY),
            "artifacts": StatCard("Active artifacts", "0", "📄", Color.SUCCESS),
            "indexed": StatCard("Indexed / searchable text", "0/0", "🔍", Color.WARNING),
        }
        for card in self.stat_cards.values():
            self.cards_layout.addWidget(card)
        layout.addLayout(self.cards_layout)

        self.history_note = QLabel("")
        self.history_note.setObjectName("OverviewHistory")
        self.history_note.setWordWrap(True)
        self.history_note.setProperty("secondaryText", True)
        self.history_note.hide()
        layout.addWidget(self.history_note)

        self.workflow_heading = QLabel("Case workflow")
        self.workflow_heading.setProperty("sectionTitle", True)
        self.workflow_heading.setFont(
            QFont(Typography.FONT_FAMILY, Typography.HEADING_MD[0], Typography.HEADING_MD[1])
        )
        layout.addWidget(self.workflow_heading)

        workflow_grid = QGridLayout()
        workflow_grid.setContentsMargins(0, 0, 0, 0)
        workflow_grid.setSpacing(Spacing.MD)
        workflow_specs = (
            ("evidence", "Evidence & integrity", "evidence"),
            ("examination", "Examination", "examination"),
            ("artifacts", "Artifacts & search", "artifacts"),
            ("analysis", "Analysis & review", "entities"),
        )
        for index, (key, title, route) in enumerate(workflow_specs):
            card = WorkflowCard(title, route)
            card.open_requested.connect(self._on_action)
            self.workflow_cards[key] = card
            workflow_grid.addWidget(card, index // 2, index % 2)
        self.workflow_grid_widget = QWidget()
        self.workflow_grid_widget.setLayout(workflow_grid)
        self.workflow_empty = QLabel(
            "No active evidence to process. Register evidence to start; historical "
            "records from removed evidence are retained separately."
        )
        self.workflow_empty.setWordWrap(True)
        self.workflow_empty.setProperty("secondaryText", True)
        layout.addWidget(self.workflow_grid_widget)
        layout.addWidget(self.workflow_empty)

        self.recommendation_frame = QFrame()
        self.recommendation_frame.setObjectName("OverviewRecommendation")
        self.recommendation_frame.setFrameShape(QFrame.Shape.StyledPanel)
        recommendation_layout = QHBoxLayout(self.recommendation_frame)
        recommendation_layout.setContentsMargins(Spacing.LG, Spacing.MD, Spacing.LG, Spacing.MD)
        recommendation_copy = QVBoxLayout()
        self.recommendation_title = QLabel("Next recommended action")
        self.recommendation_title.setProperty("sectionTitle", True)
        self.recommendation_title.setFont(
            QFont(Typography.FONT_FAMILY, Typography.HEADING_SM[0], Typography.HEADING_SM[1])
        )
        recommendation_copy.addWidget(self.recommendation_title)
        self.recommendation_detail = QLabel("Register evidence to start this case.")
        self.recommendation_detail.setWordWrap(True)
        self.recommendation_detail.setProperty("secondaryText", True)
        recommendation_copy.addWidget(self.recommendation_detail)
        recommendation_layout.addLayout(recommendation_copy, 1)
        self.recommendation_button = QPushButton("Register Evidence")
        self.recommendation_button.clicked.connect(self._on_recommendation)
        recommendation_layout.addWidget(self.recommendation_button)
        layout.addWidget(self.recommendation_frame)

        # Recent activity
        activity_heading = QLabel("Recent activity")
        activity_heading.setProperty("sectionTitle", True)
        activity_heading.setFont(
            QFont(Typography.FONT_FAMILY, Typography.HEADING_MD[0], Typography.HEADING_MD[1])
        )
        layout.addWidget(activity_heading)
        self.activity_frame = QFrame()
        self.activity_frame.setObjectName("OverviewActivity")
        self.activity_layout = QVBoxLayout(self.activity_frame)
        self.activity_layout.setContentsMargins(Spacing.MD, Spacing.SM, Spacing.MD, Spacing.SM)
        self.activity_layout.setSpacing(Spacing.XS)
        self.activity_empty = QLabel("No activity has been recorded for this case yet.")
        self.activity_empty.setProperty("secondaryText", True)
        self.activity_empty.setContentsMargins(Spacing.SM, Spacing.SM, Spacing.SM, Spacing.SM)
        self.activity_layout.addWidget(self.activity_empty)
        layout.addWidget(self.activity_frame)

        layout.addStretch()

    def set_case_context(self, context: CaseContext):
        self.case_context = context
        self.refresh()

    def set_case_service(self, service):
        self.case_service = service
        self.refresh()

    def on_page_shown(self):
        self.refresh()

    def refresh(self):
        if not self.case_service or not self.case_context:
            return
        try:
            self.case_service.session.expire_all()
            overview = self.case_service.get_case_overview(self.case_context.case_id)
        except Exception as exc:
            self.update_stats({})
            self.update_workflow({})
            self.update_recommendation({
                "key": "evidence",
                "title": "Overview unavailable",
                "detail": str(exc),
            })
            self.activity_empty.setText(f"Case overview could not be loaded: {exc}")
            return
        self.update_stats(overview["stats"])
        self.update_workflow(overview["workflow"])
        has_active_evidence = overview["stats"].get("evidence", 0) > 0
        self.workflow_grid_widget.setVisible(has_active_evidence)
        self.workflow_empty.setVisible(not has_active_evidence)
        self.workflow_heading.setVisible(has_active_evidence)
        self.update_recommendation(overview["next_action"])
        while self.activity_layout.count():
            item = self.activity_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        events = overview["activity"]
        if not events:
            self.activity_empty = QLabel("No activity has been recorded for this case yet.")
            self.activity_empty.setStyleSheet(
                f"color: {Color.TEXT_MUTED.name()}; padding: {Spacing.SM}px;"
            )
            self.activity_layout.addWidget(self.activity_empty)
            return
        for event in events:
            timestamp = event["timestamp"]
            when = format_local_date(timestamp) if timestamp else ""
            text = QLabel(
                f"{when}  •  {event['action']}  •  {event['result'].replace('_', ' ').title()}"
            )
            text.setWordWrap(True)
            self.activity_layout.addWidget(text)

    def update_stats(self, stats: dict):
        for key, card in self.stat_cards.items():
            if key == "examinations":
                value = f"{stats.get('examinations', 0)}/{stats.get('evidence', 0)}"
            elif key == "indexed":
                value = f"{stats.get('indexed', 0)}/{stats.get('searchable', 0)}"
            else:
                value = stats.get(key, 0)
            card.set_value(str(value))
        removed_artifacts = int(stats.get("removed_artifacts", 0) or 0)
        reports = int(stats.get("reports", 0) or 0)
        history = []
        if removed_artifacts:
            history.append(f"{removed_artifacts} retained artifact(s) from removed evidence")
        if reports:
            history.append(f"{reports} completed report(s) in case history")
        if history:
            self.history_note.setText("Historical records: " + " · ".join(history) + ".")
            self.history_note.show()
        else:
            self.history_note.hide()

    def update_workflow(self, workflow: dict) -> None:
        for key, card in self.workflow_cards.items():
            state = workflow.get(key, {})
            card.set_state(
                state.get("status", "not_started"),
                state.get("value", "—"),
                state.get("detail", ""),
            )

    def update_recommendation(self, recommendation: dict) -> None:
        recommendation = recommendation or {}
        key = recommendation.get("key", "reports")
        self._recommended_action = key
        self.recommendation_title.setText(recommendation.get("title", "Next recommended action"))
        self.recommendation_detail.setText(recommendation.get("detail", ""))
        labels = {
            "evidence": "Open Evidence",
            "examination": "Open Examination",
            "artifacts": "Open Artifacts & Search",
            "entities": "Open Analysis",
            "findings": "Review Findings",
            "reports": "Open Reports",
        }
        self.recommendation_button.setText(labels.get(key, "Open"))

    def _on_recommendation(self) -> None:
        self._on_action(getattr(self, "_recommended_action", "evidence"))

    def _on_action(self, key: str):
        """Ask the case shell to open the page for this next action."""
        self.next_action_requested.emit(key)
