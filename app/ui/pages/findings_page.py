"""Findings Page."""
from __future__ import annotations

from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QFont, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableView,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.artifacts.models import Artifact
from app.findings.models import Finding, FindingOrigin, FindingStatus
from app.ui.base import CaseContext, OriginBadge, ResponsivePage, StatusBadge
from app.ui.layouts import configure_detail_pane, configure_detail_splitter
from app.ui.markdown import looks_like_markdown
from app.ui.theme.tokens import Color, Spacing, Typography
from app.util.time import format_local_date


def _set_rich_text(editor: QTextEdit, text: str):
    """Show AI text as rendered Markdown when it is Markdown, plain otherwise."""
    if looks_like_markdown(text):
        editor.setMarkdown(text)
    else:
        editor.setPlainText(text)


class FindingTableModel(QStandardItemModel):
    HEADERS = ["ID", "Title", "Status", "Origin", "Created By", "Created", "Verified"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setHorizontalHeaderLabels(self.HEADERS)

    def populate(self, findings: list[Finding]):
        self.removeRows(0, self.rowCount())
        for f in findings:
            row = [
                QStandardItem(f.finding_id),
                QStandardItem(f.title),
                QStandardItem(f.status.value.replace("_", " ").title()),
                QStandardItem(f.origin.value.replace("_", " ").title()),
                QStandardItem(f.created_by.full_name if f.created_by else "Unknown"),
                QStandardItem(format_local_date(f.created_at) if f.created_at else ""),
                QStandardItem(format_local_date(f.verified_at) if f.verified_at else "—"),
            ]
            for item in row:
                item.setEditable(False)
            # Color status
            status_item = row[2]
            if f.status == FindingStatus.VERIFIED:
                status_item.setForeground(Color.SUCCESS)
            elif f.status == FindingStatus.REJECTED:
                status_item.setForeground(Color.ERROR)
            elif f.status == FindingStatus.UNDER_REVIEW:
                status_item.setForeground(Color.WARNING)
            self.appendRow(row)


class FindingDetailPane(QFrame):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("DetailPane")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        configure_detail_pane(self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(Spacing.MD, Spacing.MD, Spacing.MD, Spacing.MD)
        layout.setSpacing(Spacing.SM)

        # Title row with origin badge
        title_row = QHBoxLayout()
        self.title = QLabel("Select finding to view details")
        self.title.setFont(QFont(Typography.FONT_FAMILY, Typography.HEADING_SM[0], Typography.HEADING_SM[1]))
        title_row.addWidget(self.title)
        title_row.addStretch()
        self.origin_badge = OriginBadge("investigator")
        title_row.addWidget(self.origin_badge)
        layout.addLayout(title_row)

        # Status badge
        self.status_badge = StatusBadge("Draft", "draft")
        layout.addWidget(self.status_badge, alignment=Qt.AlignmentFlag.AlignLeft)

        # Description
        desc_label = QLabel("Description:")
        desc_label.setFont(QFont(Typography.FONT_FAMILY, Typography.BODY_SM[0], QFont.Weight.Bold))
        layout.addWidget(desc_label)

        self.desc_text = QTextEdit()
        self.desc_text.setReadOnly(True)
        self.desc_text.setMaximumHeight(150)
        layout.addWidget(self.desc_text)

        # Conclusion
        conc_label = QLabel("Conclusion:")
        conc_label.setFont(QFont(Typography.FONT_FAMILY, Typography.BODY_SM[0], QFont.Weight.Bold))
        layout.addWidget(conc_label)

        self.conc_text = QTextEdit()
        self.conc_text.setReadOnly(True)
        self.conc_text.setMaximumHeight(100)
        layout.addWidget(self.conc_text)

        # AI fields (shown for AI-suggested)
        self.ai_frame = QFrame()
        self.ai_frame.setVisible(False)
        ai_layout = QVBoxLayout(self.ai_frame)
        ai_layout.setContentsMargins(0, 0, 0, 0)
        ai_layout.setSpacing(Spacing.SM)

        self.ai_question = QTextEdit()
        self.ai_question.setReadOnly(True)
        self.ai_question.setMaximumHeight(60)
        ai_layout.addWidget(QLabel("AI Question:"))
        ai_layout.addWidget(self.ai_question)

        self.ai_answer = QTextEdit()
        self.ai_answer.setReadOnly(True)
        self.ai_answer.setMaximumHeight(100)
        ai_layout.addWidget(QLabel("AI Answer:"))
        ai_layout.addWidget(self.ai_answer)

        layout.addWidget(self.ai_frame)

        # Supporting artifacts
        art_label = QLabel("Supporting Artifacts:")
        art_label.setFont(QFont(Typography.FONT_FAMILY, Typography.BODY_SM[0], QFont.Weight.Bold))
        layout.addWidget(art_label)

        self.artifacts_list = QLabel("—")
        self.artifacts_list.setWordWrap(True)
        self.artifacts_list.setStyleSheet(f"color: {Color.TEXT_SECONDARY.name()};")
        layout.addWidget(self.artifacts_list)

        layout.addStretch()

        # Action buttons
        self.verify_btn = QPushButton("Mark Verified")
        self.verify_btn.clicked.connect(self._on_verify)
        layout.addWidget(self.verify_btn)

        self.reject_btn = QPushButton("Reject")
        self.reject_btn.setProperty("secondary", True)
        self.reject_btn.clicked.connect(self._on_reject)
        layout.addWidget(self.reject_btn)

    def set_finding(self, finding: Finding | None, artifacts: list[Artifact] = None):
        if not finding:
            self.title.setText("Select finding to view details")
            self.desc_text.clear()
            self.conc_text.clear()
            self.ai_frame.setVisible(False)
            self.artifacts_list.setText("—")
            self.status_badge.setText("Draft")
            self.status_badge.setProperty("status", "draft")
            self.origin_badge.setText("Investigator")
            self.origin_badge.setProperty("origin", "investigator")
            return

        self.title.setText(finding.title)
        _set_rich_text(self.desc_text, finding.description)
        _set_rich_text(self.conc_text, finding.conclusion or "—")
        self.status_badge.setText(finding.status.value.replace("_", " ").title())
        self.status_badge.setProperty("status", finding.status.value)
        self.origin_badge.setText("Investigator" if finding.origin == FindingOrigin.INVESTIGATOR else "AI Suggested")
        self.origin_badge.setProperty("origin", finding.origin.value)

        # AI fields
        if finding.origin == FindingOrigin.AI_SUGGESTED:
            self.ai_frame.setVisible(True)
            _set_rich_text(self.ai_question, finding.ai_question or "—")
            _set_rich_text(self.ai_answer, finding.ai_answer or "—")
        else:
            self.ai_frame.setVisible(False)

        # Artifacts
        if artifacts:
            self.artifacts_list.setText("\n".join([f"{a.artifact_id}: {a.name}" for a in artifacts]))
        else:
            self.artifacts_list.setText("—")

    def _on_verify(self):
        # TODO: Implement verification
        pass

    def _on_reject(self):
        # TODO: Implement rejection
        pass


class NewFindingDialog(QDialog):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("New Finding")
        self.setModal(True)
        self.resize(600, 500)

        layout = QFormLayout(self)
        layout.setSpacing(Spacing.MD)
        layout.setContentsMargins(Spacing.LG, Spacing.LG, Spacing.LG, Spacing.LG)

        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("Finding title")
        layout.addRow("Title:", self.title_edit)

        self.desc_edit = QTextEdit()
        self.desc_edit.setPlaceholderText("Detailed description")
        layout.addRow("Description:", self.desc_edit)

        self.conc_edit = QTextEdit()
        self.conc_edit.setPlaceholderText("Conclusion (optional)")
        layout.addRow("Conclusion:", self.conc_edit)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def get_data(self) -> dict:
        return {
            "title": self.title_edit.text().strip(),
            "description": self.desc_edit.toPlainText().strip(),
            "conclusion": self.conc_edit.toPlainText().strip() or None,
        }


class FindingsPage(ResponsivePage):
    def __init__(self, nav=None, parent: QWidget | None = None):
        super().__init__(parent=parent)
        self.nav = nav
        self.case_context: CaseContext | None = None
        self.finding_service = None
        

    def _setup_layout(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(Spacing.LG, Spacing.LG, Spacing.LG, Spacing.LG)
        layout.setSpacing(Spacing.LG)

        # Header
        header_row = QHBoxLayout()
        title = QLabel("Findings")
        title.setProperty("pageTitle", True)
        title.setFont(QFont(Typography.FONT_FAMILY, Typography.HEADING_LG[0], Typography.HEADING_LG[1]))
        header_row.addWidget(title)
        header_row.addStretch()

        self.new_btn = QPushButton("New Finding")
        self.new_btn.clicked.connect(self._on_new_finding)
        header_row.addWidget(self.new_btn)

        self.ai_suggest_btn = QPushButton("AI Suggested")
        self.ai_suggest_btn.setProperty("secondary", True)
        self.ai_suggest_btn.clicked.connect(self._on_ai_suggested)
        header_row.addWidget(self.ai_suggest_btn)

        layout.addLayout(header_row)

        # Filters
        filter_row = QHBoxLayout()
        self.status_filter = QComboBox()
        self.status_filter.addItems(["All", "draft", "under_review", "verified", "rejected"])
        self.status_filter.currentTextChanged.connect(self._apply_filters)
        filter_row.addWidget(QLabel("Status:"))
        filter_row.addWidget(self.status_filter)

        self.origin_filter = QComboBox()
        self.origin_filter.addItems(["All", "investigator", "ai_suggested"])
        self.origin_filter.currentTextChanged.connect(self._apply_filters)
        filter_row.addWidget(QLabel("Origin:"))
        filter_row.addWidget(self.origin_filter)

        filter_row.addStretch()
        layout.addLayout(filter_row)

        # Splitter
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Table
        self.table_view = QTableView()
        self.table_model = FindingTableModel(self.table_view)
        self.table_view.setModel(self.table_model)
        self.table_view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table_view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table_view.setAlternatingRowColors(True)
        self.table_view.verticalHeader().setVisible(False)
        self.table_view.horizontalHeader().setStretchLastSection(True)
        self.table_view.selectionModel().selectionChanged.connect(self._on_selection_changed)
        splitter.addWidget(self.table_view)

        # Detail pane
        self.detail_pane = FindingDetailPane()
        splitter.addWidget(self.detail_pane)

        configure_detail_splitter(splitter, preferred_detail_width=380)
        layout.addWidget(splitter, 1)

    def set_case_context(self, context: CaseContext):
        self.case_context = context
        self.refresh()

    def set_finding_service(self, service):
        self.finding_service = service

    def refresh(self):
        if not self.finding_service or not self.case_context:
            return
        findings = self.finding_service.list_findings(self.case_context.case_id)
        self.table_model.populate(findings)
        self._apply_filters()

    def _apply_filters(self):
        # TODO: Implement filtering
        pass

    def _on_selection_changed(self):
        indexes = self.table_view.selectionModel().selectedRows()
        if indexes and self.finding_service and self.case_context:
            row = indexes[0].row()
            finding_id = self.table_model.item(row, 0).text()
            finding = self.finding_service.get_finding_by_finding_id(self.case_context.case_id, finding_id)
            if finding:
                artifacts = self.finding_service.get_finding_artifacts(finding.id)
                self.detail_pane.set_finding(finding, artifacts)
                return
        self.detail_pane.set_finding(None)

    def _on_new_finding(self):
        if not self.finding_service or not self.case_context:
            return
        # Get current user from session
        from app.auth.models import User
        from app.db.session import session_scope
        with session_scope() as session:
            user = session.get(User, 1)  # TODO: get actual current user
            if not user:
                return
        
        dialog = NewFindingDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            data = dialog.get_data()
            if not data["title"] or not data["description"]:
                QMessageBox.warning(self, "Validation Error", "Title and description are required")
                return
            try:
                from app.db.session import session_scope
                with session_scope() as session:
                    from app.findings.service import FindingService
                    finding_service = FindingService(session)
                    finding_service.create_finding(
                        case_id=self.case_context.case_id,
                        title=data["title"],
                        description=data["description"],
                        conclusion=data["conclusion"],
                        created_by=user,
                    )
                    session.commit()
                self.refresh()
                QMessageBox.information(self, "Success", "Finding created successfully")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to create finding: {e}")

    def _on_ai_suggested(self):
        # Navigate to AI Analysis page
        if self.nav and hasattr(self.nav, 'case_shell'):
            # Emit signal or navigate - for now just show message
            QMessageBox.information(self, "Info", "Navigate to AI Analysis tab to create AI-suggested findings")
