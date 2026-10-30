"""Findings Page."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTableView,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy import select
from sqlalchemy.orm import object_session

from app.artifacts.models import Artifact
from app.devices.models import DeviceEvidenceLink, PhysicalDevice
from app.findings.models import Finding, FindingOrigin, FindingStatus
from app.ui.base import CaseContext, OriginBadge, ResponsivePage, StatusBadge
from app.ui.layouts import (
    DETAIL_PANE_MIN_WIDTH,
    configure_detail_pane,
    configure_detail_splitter,
)
from app.ui.markdown import looks_like_markdown
from app.ui.theme.tokens import Color, Spacing, Typography
from app.util.time import format_local_date


def _set_rich_text(editor: QTextEdit, text: str):
    """Show AI text as rendered Markdown when it is Markdown, plain otherwise."""
    if looks_like_markdown(text):
        editor.setMarkdown(text)
    else:
        editor.setPlainText(text)


def _source_label(artifact) -> str:
    """Describe an artifact and its evidence without exposing database IDs."""
    evidence = getattr(artifact, "evidence", None)
    if evidence is None or getattr(evidence, "case_id", None) != getattr(artifact, "case_id", None):
        provenance = "Evidence unavailable"
    else:
        provenance = f"Evidence {evidence.evidence_id} — {evidence.name}"
        if evidence.removed_at is not None:
            provenance += " (removed from case)"
        session = object_session(evidence)
        if session is not None:
            devices = session.scalars(
                select(PhysicalDevice.label)
                .join(DeviceEvidenceLink, DeviceEvidenceLink.device_id == PhysicalDevice.id)
                .where(DeviceEvidenceLink.evidence_id == evidence.id,
                       PhysicalDevice.case_id == artifact.case_id)
                .order_by(PhysicalDevice.id)
            ).all()
            provenance += (" | Investigator-associated device(s): " + ", ".join(devices)
                           if devices else " | No associated physical device")
    return f"{artifact.artifact_id} — {artifact.name} | {provenance}"


class FindingTableModel(QStandardItemModel):
    HEADERS = ["ID", "Title", "Status", "Origin", "Created By", "Created", "Reviewed"]

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
    verify_requested = Signal()
    reject_requested = Signal()
    review_requested = Signal()
    edit_requested = Signal()
    link_requested = Signal()
    unlink_requested = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("DetailPane")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        # The page wraps this pane in a scroll area, so the pane itself only
        # needs a minimum width; the scroll area carries the splitter bounds.
        self.setMinimumWidth(DETAIL_PANE_MIN_WIDTH)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(Spacing.MD, Spacing.MD, Spacing.MD, Spacing.MD)
        layout.setSpacing(Spacing.SM)

        # Title row with origin badge
        title_row = QHBoxLayout()
        self.title = QLabel("Select finding to view details")
        self.title.setTextFormat(Qt.TextFormat.PlainText)
        self.title.setWordWrap(True)
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
        self.artifacts_list.setTextFormat(Qt.TextFormat.PlainText)
        self.artifacts_list.setWordWrap(True)
        self.artifacts_list.setStyleSheet(f"color: {Color.TEXT_SECONDARY.name()};")
        layout.addWidget(self.artifacts_list)

        self.review_note = QLabel("")
        self.review_note.setTextFormat(Qt.TextFormat.PlainText)
        self.review_note.setWordWrap(True)
        self.review_note.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.review_note)

        layout.addStretch()

        # Action buttons
        self.verify_btn = QPushButton("Mark Verified")
        self.verify_btn.clicked.connect(self._on_verify)
        layout.addWidget(self.verify_btn)

        self.reject_btn = QPushButton("Reject")
        self.reject_btn.setProperty("secondary", True)
        self.reject_btn.clicked.connect(self._on_reject)
        layout.addWidget(self.reject_btn)

        self.review_btn = QPushButton("Mark under review")
        self.review_btn.setProperty("secondary", True)
        self.review_btn.clicked.connect(self.review_requested.emit)
        layout.addWidget(self.review_btn)
        self.edit_btn = QPushButton("Edit finding")
        self.edit_btn.setProperty("secondary", True)
        self.edit_btn.setToolTip("Editing a verified or rejected finding returns it to draft.")
        self.edit_btn.clicked.connect(self.edit_requested.emit)
        layout.addWidget(self.edit_btn)
        link_row = QHBoxLayout()
        self.link_btn = QPushButton("Link artifact")
        self.link_btn.setToolTip("Changing linked artifacts returns a reviewed finding to draft.")
        self.link_btn.setProperty("secondary", True)
        self.link_btn.clicked.connect(self.link_requested.emit)
        link_row.addWidget(self.link_btn)
        self.unlink_btn = QPushButton("Unlink artifact")
        self.unlink_btn.setToolTip("Changing linked artifacts returns a reviewed finding to draft.")
        self.unlink_btn.setProperty("secondary", True)
        self.unlink_btn.clicked.connect(self.unlink_requested.emit)
        link_row.addWidget(self.unlink_btn)
        layout.addLayout(link_row)
        self.set_finding(None)

    def set_finding(self, finding: Finding | None, artifacts: list[Artifact] = None):
        for button in (self.verify_btn, self.reject_btn, self.review_btn,
                       self.edit_btn, self.link_btn, self.unlink_btn):
            button.setEnabled(finding is not None)
        if not finding:
            self.title.setText("Select finding to view details")
            self.desc_text.clear()
            self.conc_text.clear()
            self.ai_frame.setVisible(False)
            self.artifacts_list.setText("—")
            self.review_note.clear()
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
        reviewer = finding.verified_by.full_name if finding.verified_by else ""
        reviewed = format_local_date(finding.verified_at) if finding.verified_at else ""
        details = []
        if reviewer or reviewed:
            details.append("Reviewed: " + " · ".join(part for part in (reviewer, reviewed) if part))
        if finding.verification_notes:
            details.append(f"Review notes: {finding.verification_notes}")
        self.review_note.setText("\n".join(details))
        for badge in (self.status_badge, self.origin_badge):
            badge.style().unpolish(badge)
            badge.style().polish(badge)
        self.verify_btn.setEnabled(finding.status != FindingStatus.VERIFIED)
        self.reject_btn.setEnabled(finding.status != FindingStatus.REJECTED)
        self.review_btn.setEnabled(finding.status != FindingStatus.UNDER_REVIEW)
        self.unlink_btn.setEnabled(bool(artifacts))

        # AI fields
        if finding.origin == FindingOrigin.AI_SUGGESTED:
            self.ai_frame.setVisible(True)
            _set_rich_text(self.ai_question, finding.ai_question or "—")
            _set_rich_text(self.ai_answer, finding.ai_answer or "—")
        else:
            self.ai_frame.setVisible(False)

        # Artifacts
        if artifacts:
            self.artifacts_list.setText("\n".join(_source_label(a) for a in artifacts))
        else:
            self.artifacts_list.setText("—")

    def _on_verify(self):
        self.verify_requested.emit()

    def _on_reject(self):
        self.reject_requested.emit()


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


class IdentityHypothesisDialog(QDialog):
    """Collect investigator interpretations; excerpts are not identity proof."""

    def __init__(self, artifacts, parent=None):
        super().__init__(parent)
        self.setWindowTitle("New identity hypothesis")
        self.resize(700, 650)
        self.sources = []
        self._artifacts = {item.id: item for item in artifacts}
        layout = QVBoxLayout(self)
        warning = QLabel("Unverified investigator hypothesis. An excerpt establishes provenance, not identity.")
        warning.setWordWrap(True)
        layout.addWidget(warning)
        form = QFormLayout()
        self.hypothesis = QTextEdit()
        self.hypothesis.setMaximumHeight(80)
        form.addRow("Hypothesis:", self.hypothesis)
        self.alternatives = QTextEdit()
        self.alternatives.setPlaceholderText("At least one alternative explanation; one per line")
        self.alternatives.setMaximumHeight(80)
        form.addRow("Alternatives:", self.alternatives)
        self.artifact = QComboBox()
        for item in artifacts:
            self.artifact.addItem(_source_label(item), item.id)
        form.addRow("Source artifact:", self.artifact)
        self.excerpt = QTextEdit()
        self.excerpt.setPlaceholderText("Paste an exact excerpt from extracted text")
        self.excerpt.setMaximumHeight(80)
        form.addRow("Literal excerpt:", self.excerpt)
        self.role = QComboBox()
        for label, value in (("Supporting", "supports"), ("Contradicting", "contradicts"), ("Context", "contextual")):
            self.role.addItem(label, value)
        form.addRow("Role:", self.role)
        self.explanation = QLineEdit()
        form.addRow("Interpretation:", self.explanation)
        layout.addLayout(form)
        add = QPushButton("Add source")
        add.clicked.connect(self.add_source)
        layout.addWidget(add)
        self.source_list = QLabel("No sources added")
        self.source_list.setTextFormat(Qt.TextFormat.PlainText)
        self.source_list.setWordWrap(True)
        layout.addWidget(self.source_list)
        remove = QPushButton("Remove last source")
        remove.clicked.connect(self.remove_source)
        layout.addWidget(remove)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def add_source(self):
        from app.findings.identity import IdentitySource

        artifact_id = self.artifact.currentData()
        if artifact_id is None:
            return
        self.sources.append(IdentitySource(artifact_id, self.excerpt.toPlainText(),
                                           self.role.currentData(), self.explanation.text()))
        self._show_sources()
        self.excerpt.clear()
        self.explanation.clear()

    def remove_source(self):
        if self.sources:
            self.sources.pop()
            self._show_sources()

    def accept(self):
        if not self.hypothesis.toPlainText().strip() or not self.alternatives.toPlainText().strip():
            message = "Enter a hypothesis and at least one alternative explanation."
        elif any(
            heading in self.hypothesis.toPlainText()
            for heading in ("\n\nAlternative explanations:\n", "\n\nSource excerpts and investigator interpretations:\n")
        ):
            message = "The hypothesis contains a reserved section heading."
        elif not any(source.relevance == "supports" for source in self.sources):
            message = "Add at least one supporting source."
        elif len({source.artifact_id for source in self.sources}) != len(self.sources):
            message = "Use one source entry per artifact. Remove the duplicate source."
        elif any(
            not source.quote.strip()
            or not source.explanation.strip()
            or "\nInterpretation: " in source.quote
            or source.artifact_id not in self._artifacts
            or source.quote not in (self._artifacts[source.artifact_id].content_text or "")
            for source in self.sources
        ):
            message = "Each source needs an exact excerpt from its artifact and an interpretation."
        else:
            super().accept()
            return
        QMessageBox.warning(self, "Check identity hypothesis", message)

    def _show_sources(self):
        labels = []
        for source in self.sources:
            index = self.artifact.findData(source.artifact_id)
            labels.append(f"{self.artifact.itemText(index)} [{source.relevance}]: {source.quote}")
        self.source_list.setText("\n".join(labels) or "No sources added")


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

        self.identity_btn = QPushButton("New identity hypothesis")
        self.identity_btn.clicked.connect(self._on_new_identity)
        header_row.addWidget(self.identity_btn)

        self.ai_suggest_btn = QPushButton("AI Suggested")
        self.ai_suggest_btn.setProperty("secondary", True)
        self.ai_suggest_btn.clicked.connect(self._on_ai_suggested)
        header_row.addWidget(self.ai_suggest_btn)

        layout.addLayout(header_row)

        # Filters
        filter_row = QHBoxLayout()
        self.status_filter = QComboBox()
        self.status_filter.addItem("All statuses", "")
        for status in FindingStatus:
            self.status_filter.addItem(status.value.replace("_", " ").title(), status.value)
        self.status_filter.currentTextChanged.connect(self._apply_filters)
        filter_row.addWidget(QLabel("Status:"))
        filter_row.addWidget(self.status_filter)

        self.origin_filter = QComboBox()
        self.origin_filter.addItem("All origins", "")
        for origin in FindingOrigin:
            self.origin_filter.addItem(origin.value.replace("_", " ").title(), origin.value)
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
        self.detail_pane.verify_requested.connect(lambda: self._review_finding(FindingStatus.VERIFIED))
        self.detail_pane.reject_requested.connect(lambda: self._review_finding(FindingStatus.REJECTED))
        self.detail_pane.review_requested.connect(lambda: self._review_finding(FindingStatus.UNDER_REVIEW))
        self.detail_pane.edit_requested.connect(self._on_edit_finding)
        self.detail_pane.link_requested.connect(self._on_link_artifact)
        self.detail_pane.unlink_requested.connect(self._on_unlink_artifact)
        self.detail_scroll = QScrollArea()
        self.detail_scroll.setWidgetResizable(True)
        self.detail_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.detail_scroll.setWidget(self.detail_pane)
        configure_detail_pane(self.detail_scroll)
        splitter.addWidget(self.detail_scroll)

        configure_detail_splitter(splitter, preferred_detail_width=380)
        layout.addWidget(splitter, 1)

    def set_case_context(self, context: CaseContext):
        self.case_context = context
        self.refresh()

    def set_finding_service(self, service):
        self.finding_service = service
        self.refresh()

    def on_page_shown(self):
        if self.finding_service:
            self.finding_service.session.expire_all()
        self.refresh()

    def refresh(self):
        if not self.finding_service or not self.case_context:
            return
        self._apply_filters()

    def _apply_filters(self):
        if not self.finding_service or not self.case_context:
            return
        status_text = self.status_filter.currentData()
        origin_text = self.origin_filter.currentData()
        try:
            findings = self.finding_service.list_findings(
                self.case_context.case_id,
                status=FindingStatus(status_text) if status_text else None,
                origin=FindingOrigin(origin_text) if origin_text else None,
            )
            self.table_model.populate(findings)
            self.detail_pane.set_finding(None)
        except Exception as exc:
            QMessageBox.warning(self, "Could not load findings", str(exc))

    def _selected_finding(self):
        if not self.finding_service or not self.case_context:
            return None
        indexes = self.table_view.selectionModel().selectedRows()
        if not indexes:
            return None
        item = self.table_model.item(indexes[0].row(), 0)
        if item is None:
            return None
        return self.finding_service.get_finding_by_finding_id(self.case_context.case_id, item.text())

    def _investigator(self):
        from app.auth.models import User, UserRole
        getter = getattr(self.nav, "get_current_user", None)
        current = getter() if callable(getter) else None
        user = self.finding_service.session.get(User, current.id) if current is not None else None
        if user is None:
            QMessageBox.warning(self, "Not signed in", "Sign in before changing a finding.")
        elif not user.is_active or user.role == UserRole.READ_ONLY:
            QMessageBox.warning(self, "Permission denied", "An active investigator account is required.")
            return None
        return user

    def _audit(self, user, finding, action, details=None):
        from app.audit.service import AuditService
        AuditService(self.finding_service.session).log_event(
            event_type="finding", action=action, result="success", user=user,
            case_id=finding.case_id, target_type="finding", target_id=finding.id,
            details={"finding_id": finding.finding_id, **(details or {})},
        )

    @staticmethod
    def _invalidate_review(finding):
        if finding.status in (FindingStatus.VERIFIED, FindingStatus.REJECTED):
            finding.status = FindingStatus.DRAFT
            finding.verified_at = None
            finding.verified_by = None
            finding.verification_notes = None

    def _on_selection_changed(self):
        indexes = self.table_view.selectionModel().selectedRows()
        if indexes and self.finding_service and self.case_context:
            finding = self._selected_finding()
            if finding:
                artifacts = self.finding_service.get_finding_artifacts(finding.id)
                self.detail_pane.set_finding(finding, artifacts)
                return
        self.detail_pane.set_finding(None)

    def _on_new_finding(self):
        if not self.finding_service or not self.case_context:
            return
        user = self._investigator()
        if user is None:
            return
        
        dialog = NewFindingDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            data = dialog.get_data()
            if not data["title"] or not data["description"]:
                QMessageBox.warning(self, "Validation Error", "Title and description are required")
                return
            try:
                session = self.finding_service.session
                finding = self.finding_service.create_finding(
                        case_id=self.case_context.case_id,
                        title=data["title"],
                        description=data["description"],
                        conclusion=data["conclusion"],
                        created_by=user,
                    )
                self._audit(user, finding, "create")
                session.commit()
                self.refresh()
                QMessageBox.information(self, "Success", "Finding created successfully")
            except Exception as e:
                self.finding_service.session.rollback()
                QMessageBox.critical(self, "Error", f"Failed to create finding: {e}")

    def _on_ai_suggested(self):
        # Navigate to AI Analysis page
        navigate = getattr(self.nav, "show_page_by_key", None)
        if callable(navigate):
            navigate("ai")
        else:
            QMessageBox.information(self, "AI Analysis", "Open AI Analysis to save an answer as a draft finding.")

    def _on_new_identity(self):
        if not self.finding_service or not self.case_context:
            return
        user = self._investigator()
        if user is None:
            return
        from sqlalchemy import select

        from app.evidence.models import Evidence
        from app.findings.identity import create_identity_hypothesis

        session = self.finding_service.session
        artifacts = session.scalars(
            select(Artifact).join(Evidence, Artifact.evidence_id == Evidence.id).where(
                Artifact.case_id == self.case_context.case_id,
                Evidence.case_id == self.case_context.case_id,
                Evidence.removed_at.is_(None),
                Artifact.content_text.is_not(None),
            ).order_by(Artifact.artifact_id)
        ).all()
        dialog = IdentityHypothesisDialog(artifacts, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            finding = create_identity_hypothesis(
                session, self.case_context.case_id, user, dialog.hypothesis.toPlainText(),
                dialog.alternatives.toPlainText().splitlines(), dialog.sources,
            )
            self._audit(user, finding, "create", {"kind": "identity_hypothesis"})
            ref = finding.finding_id
            session.commit()
            self._refresh_selection(ref)
        except Exception as exc:
            session.rollback()
            QMessageBox.warning(self, "Could not create identity hypothesis", str(exc))

    def _refresh_selection(self, finding_ref: str):
        self.refresh()
        for row in range(self.table_model.rowCount()):
            if self.table_model.item(row, 0).text() == finding_ref:
                self.table_view.selectRow(row)
                break

    def _review_finding(self, status: FindingStatus):
        finding = self._selected_finding()
        if finding is None:
            return
        user = self._investigator()
        if user is None:
            return
        notes = ""
        if status != FindingStatus.UNDER_REVIEW:
            notes, accepted = QInputDialog.getMultiLineText(
                self, "Review finding", "Review notes (optional):",
                finding.verification_notes or "",
            )
            if not accepted:
                return
        ref = finding.finding_id
        session = self.finding_service.session
        try:
            if status == FindingStatus.VERIFIED:
                self.finding_service.verify_finding(finding.id, user, notes.strip() or None)
            elif status == FindingStatus.REJECTED:
                self.finding_service.reject_finding(finding.id, user, notes.strip() or None)
            else:
                finding.status = status
                finding.verified_at = None
                finding.verified_by = None
                finding.verification_notes = None
            self._audit(user, finding, "review", {"status": status.value, "notes": notes.strip()})
            session.commit()
            self._refresh_selection(ref)
        except Exception as exc:
            session.rollback()
            QMessageBox.critical(self, "Could not update finding", str(exc))

    def _on_edit_finding(self):
        finding = self._selected_finding()
        if finding is None:
            return
        user = self._investigator()
        if user is None:
            return
        dialog = NewFindingDialog(self)
        dialog.setWindowTitle("Edit finding")
        dialog.title_edit.setText(finding.title)
        dialog.desc_edit.setPlainText(finding.description)
        dialog.conc_edit.setPlainText(finding.conclusion or "")
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        data = dialog.get_data()
        if not data["title"] or not data["description"]:
            QMessageBox.warning(self, "Validation Error", "Title and description are required")
            return
        ref = finding.finding_id
        session = self.finding_service.session
        try:
            self.finding_service.update_finding(finding.id, title=data["title"], description=data["description"], updated_by=user)
            finding.conclusion = data["conclusion"]
            self._invalidate_review(finding)
            self._audit(user, finding, "edit", {"status": finding.status.value})
            session.commit()
            self._refresh_selection(ref)
        except Exception as exc:
            session.rollback()
            QMessageBox.critical(self, "Could not edit finding", str(exc))

    def _on_link_artifact(self):
        finding = self._selected_finding()
        if finding is None:
            return
        user = self._investigator()
        if user is None:
            return
        artifact_ref, accepted = QInputDialog.getText(self, "Link artifact", "Artifact ID:")
        if not accepted or not artifact_ref.strip():
            return
        from sqlalchemy import func, select

        from app.evidence.models import Evidence
        session = self.finding_service.session
        try:
            artifact = session.scalar(
                select(Artifact).join(Evidence, Artifact.evidence_id == Evidence.id).where(
                    Artifact.case_id == finding.case_id,
                    func.upper(Artifact.artifact_id) == artifact_ref.strip().upper(),
                    Evidence.removed_at.is_(None),
                )
            )
            if artifact is None:
                raise ValueError("That artifact was not found in active evidence for this case.")
            if any(item.id == artifact.id for item in self.finding_service.get_finding_artifacts(finding.id)):
                raise ValueError("This artifact is already linked to the finding.")
            self.finding_service.link_artifact(finding.id, artifact.id)
            self._invalidate_review(finding)
            self._audit(user, finding, "link_artifact", {"artifact_id": artifact.artifact_id})
            ref = finding.finding_id
            session.commit()
            self._refresh_selection(ref)
        except Exception as exc:
            session.rollback()
            QMessageBox.warning(self, "Could not link artifact", str(exc))

    def _on_unlink_artifact(self):
        finding = self._selected_finding()
        if finding is None:
            return
        user = self._investigator()
        if user is None:
            return
        artifacts = self.finding_service.get_finding_artifacts(finding.id)
        if not artifacts:
            return
        labels = [_source_label(item) for item in artifacts]
        choice, accepted = QInputDialog.getItem(self, "Unlink artifact", "Artifact:", labels, 0, False)
        if not accepted or choice not in labels:
            return
        artifact = artifacts[labels.index(choice)]
        session = self.finding_service.session
        try:
            self.finding_service.unlink_artifact(finding.id, artifact.id)
            self._invalidate_review(finding)
            self._audit(user, finding, "unlink_artifact", {"artifact_id": artifact.artifact_id})
            ref = finding.finding_id
            session.commit()
            self._refresh_selection(ref)
        except Exception as exc:
            session.rollback()
            QMessageBox.warning(self, "Could not unlink artifact", str(exc))
