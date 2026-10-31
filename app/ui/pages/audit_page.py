"""Case audit trail and evidence chain-of-custody viewer."""
from __future__ import annotations

import csv
import json
from datetime import date
from pathlib import Path

from PySide6.QtCore import QDate, Qt
from PySide6.QtGui import QFont, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QAbstractItemView,
    QBoxLayout,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableView,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.audit.models import AuditEvent
from app.evidence.models import CustodyEvent, Evidence
from app.ui.base import CaseContext, ResponsivePage
from app.ui.layouts import configure_detail_pane, configure_detail_splitter
from app.ui.theme.tokens import Color, Spacing, Typography
from app.util.time import format_local_date


class AuditTableModel(QStandardItemModel):
    HEADERS = ["Time", "Event Type", "Action", "Result", "Target", "User", "Details"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.events: list[AuditEvent] = []
        self.setHorizontalHeaderLabels(self.HEADERS)

    def populate(self, events: list[AuditEvent]):
        self.events = list(events)
        self.removeRows(0, self.rowCount())
        for event in self.events:
            target = (
                f"{event.target_type}:{event.target_id}"
                if event.target_type and event.target_id is not None else "—"
            )
            user = event.user.username if event.user else "System"
            details = _pretty_json(event.details_json)
            row = [
                QStandardItem(format_local_date(event.timestamp) if event.timestamp else ""),
                QStandardItem(event.event_type),
                QStandardItem(event.action),
                QStandardItem(event.result),
                QStandardItem(target),
                QStandardItem(user),
                QStandardItem(details.replace("\n", " ")),
            ]
            for item in row:
                item.setEditable(False)
            if event.result == "success":
                row[3].setForeground(Color.SUCCESS)
            elif event.result == "failure":
                row[3].setForeground(Color.ERROR)
            elif event.result == "partial":
                row[3].setForeground(Color.WARNING)
            self.appendRow(row)


class CustodyTableModel(QStandardItemModel):
    HEADERS = ["Time", "Evidence", "Event", "Performed By", "Tool", "From", "To"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.events: list[CustodyEvent] = []
        self.setHorizontalHeaderLabels(self.HEADERS)

    def populate(self, events: list[CustodyEvent]):
        self.events = list(events)
        self.removeRows(0, self.rowCount())
        for event in self.events:
            evidence = event.evidence
            evidence_label = (
                f"{evidence.evidence_id} — {evidence.name}" if evidence else "Evidence unavailable"
            )
            row = [
                QStandardItem(format_local_date(event.performed_at) if event.performed_at else ""),
                QStandardItem(evidence_label),
                QStandardItem(event.event_type.replace("_", " ").title()),
                QStandardItem(event.performed_by.username if event.performed_by else "Unknown"),
                QStandardItem(event.tool_used or "—"),
                QStandardItem(event.source_location or "—"),
                QStandardItem(event.destination_location or "—"),
            ]
            for item in row:
                item.setEditable(False)
            self.appendRow(row)


def _pretty_json(raw: str | None) -> str:
    if not raw:
        return "—"
    try:
        return json.dumps(json.loads(raw), indent=2, ensure_ascii=False)
    except (TypeError, json.JSONDecodeError):
        return raw


class AuditDetailPane(QFrame):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("DetailPane")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        configure_detail_pane(self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(Spacing.MD, Spacing.MD, Spacing.MD, Spacing.MD)
        layout.setSpacing(Spacing.SM)
        self.title = QLabel("Select an event to view details")
        self.title.setWordWrap(True)
        self.title.setFont(QFont(Typography.FONT_FAMILY, Typography.HEADING_SM[0], Typography.HEADING_SM[1]))
        layout.addWidget(self.title)
        self.detail_text = QTextEdit()
        self.detail_text.setReadOnly(True)
        self.detail_text.setFont(QFont(Typography.FONT_FAMILY, Typography.MONO_SM[0]))
        layout.addWidget(self.detail_text, 1)

    def set_audit_event(self, event: AuditEvent | None):
        if event is None:
            self.title.setText("Select an audit event to view details")
            self.detail_text.clear()
            return
        self.title.setText(f"{event.event_type} — {event.action}")
        lines = [
            f"Event ID: {event.event_id}",
            f"Timestamp: {event.timestamp.isoformat() if event.timestamp else '—'}",
            f"Type: {event.event_type}",
            f"Action: {event.action}",
            f"Result: {event.result}",
            f"Target: {event.target_type}:{event.target_id}" if event.target_type else "Target: —",
            f"User: {event.user.username if event.user else 'System'}",
            f"IP: {event.ip_address or '—'}",
            f"Request ID: {event.request_id or '—'}",
            "",
            "Details:",
            _pretty_json(event.details_json),
        ]
        if event.error_message:
            lines.extend(["", "Error:", event.error_message])
        self.detail_text.setPlainText("\n".join(lines))

    def set_custody_event(self, event: CustodyEvent | None):
        if event is None:
            self.title.setText("Select a custody event to view details")
            self.detail_text.clear()
            return
        evidence = event.evidence
        self.title.setText(f"{event.event_type.replace('_', ' ').title()} — {evidence.evidence_id if evidence else 'Evidence'}")
        lines = [
            f"Custody record: #{event.id}",
            f"Timestamp: {event.performed_at.isoformat() if event.performed_at else '—'}",
            f"Evidence: {evidence.evidence_id if evidence else '—'} — {evidence.name if evidence else '—'}",
            f"Evidence status: {getattr(getattr(evidence, 'status', None), 'value', '—')}",
            f"Event: {event.event_type}",
            f"Performed by: {event.performed_by.username if event.performed_by else 'Unknown'}",
            f"Description: {event.description}",
            f"Source location: {event.source_location or '—'}",
            f"Destination location: {event.destination_location or '—'}",
            f"Tool used: {event.tool_used or '—'}",
            "",
            "Metadata:",
            _pretty_json(event.metadata_json),
        ]
        self.detail_text.setPlainText("\n".join(lines))


class RecordCustodyDialog(QDialog):
    """Capture an investigator-observed custody movement or handling event."""

    EVENT_TYPES = (
        "transferred", "examined", "copied", "viewed", "stored", "released", "other",
    )

    def __init__(self, evidence_items: list[Evidence], parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Record Chain-of-Custody Event")
        self.setModal(True)
        self.resize(560, 410)
        layout = QFormLayout(self)
        layout.setContentsMargins(Spacing.LG, Spacing.LG, Spacing.LG, Spacing.LG)
        layout.setSpacing(Spacing.MD)
        self.evidence_combo = QComboBox()
        for evidence in evidence_items:
            self.evidence_combo.addItem(
                f"{evidence.evidence_id} — {evidence.name}", evidence.id
            )
        layout.addRow("Evidence:", self.evidence_combo)
        self.type_combo = QComboBox()
        self.type_combo.addItems(self.EVENT_TYPES)
        layout.addRow("Event:", self.type_combo)
        self.description_edit = QTextEdit()
        self.description_edit.setPlaceholderText(
            "Describe who handled the evidence, what happened and any relevant conditions."
        )
        self.description_edit.setMinimumHeight(90)
        layout.addRow("Description:", self.description_edit)
        self.source_edit = QLineEdit()
        self.source_edit.setPlaceholderText("Optional")
        layout.addRow("From location:", self.source_edit)
        self.destination_edit = QLineEdit()
        self.destination_edit.setPlaceholderText("Optional")
        layout.addRow("To location:", self.destination_edit)
        self.tool_edit = QLineEdit()
        self.tool_edit.setPlaceholderText("Optional, e.g. write blocker or imaging tool")
        layout.addRow("Tool / method:", self.tool_edit)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def get_data(self) -> dict:
        return {
            "evidence_id": self.evidence_combo.currentData(),
            "event_type": self.type_combo.currentText(),
            "description": self.description_edit.toPlainText().strip(),
            "source_location": self.source_edit.text().strip() or None,
            "destination_location": self.destination_edit.text().strip() or None,
            "tool_used": self.tool_edit.text().strip() or None,
        }


class AuditPage(ResponsivePage):
    RECORD_LIMIT = 10000
    DATE_PRESETS = (
        ("Any time", "any"), ("Today", "today"), ("Last 7 days", "last7"),
        ("Last 30 days", "last30"), ("Last 90 days", "last90"),
        ("This year", "year"), ("Custom range", "custom"),
    )

    def __init__(self, nav=None, parent: QWidget | None = None):
        self.nav = nav
        self.audit_service = None
        self.case_context: CaseContext | None = None
        self._all_audit_events: list[AuditEvent] = []
        self._all_custody_events: list[CustodyEvent] = []
        super().__init__(parent=parent)

    def _setup_layout(self):
        layout = QVBoxLayout(self)
        # The filter row reflows on resize; do not let its wide layout impose a
        # temporary minimum width that prevents the resize from reaching it.
        layout.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        layout.setContentsMargins(Spacing.LG, Spacing.LG, Spacing.LG, Spacing.LG)
        layout.setSpacing(Spacing.MD)

        self.filter_row = QBoxLayout(QBoxLayout.Direction.TopToBottom)
        self.filter_row.setSpacing(Spacing.SM)
        type_result_row = QHBoxLayout()
        type_result_row.setSpacing(Spacing.SM)
        self.type_filter = QComboBox()
        self.type_filter.addItem("All Types")
        self.type_filter.setMinimumWidth(130)
        type_result_row.addWidget(QLabel("Type:"))
        type_result_row.addWidget(self.type_filter)

        self.result_filter = QComboBox()
        self.result_filter.addItems(["All Results", "success", "failure", "partial"])
        self.result_filter.setMinimumWidth(130)
        type_result_row.addWidget(QLabel("Result:"))
        type_result_row.addWidget(self.result_filter)
        type_result_row.addStretch(1)
        self.filter_row.addLayout(type_result_row)

        user_date_row = QHBoxLayout()
        user_date_row.setSpacing(Spacing.SM)

        self.user_filter = QLineEdit()
        self.user_filter.setPlaceholderText("Filter by user…")
        self.user_filter.setMinimumWidth(150)
        user_date_row.addWidget(self.user_filter, 1)

        self.date_preset = QComboBox()
        for label, key in self.DATE_PRESETS:
            self.date_preset.addItem(label, key)
        self.date_preset.setMinimumWidth(145)
        user_date_row.addWidget(QLabel("Date:"))
        user_date_row.addWidget(self.date_preset)
        self.filter_row.addLayout(user_date_row, 1)

        layout.addLayout(self.filter_row)

        action_row = QHBoxLayout()
        action_row.setSpacing(Spacing.SM)

        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self.refresh)
        action_row.addWidget(self.refresh_btn)
        self.reset_btn = QPushButton("Reset")
        self.reset_btn.setProperty("ghost", True)
        self.reset_btn.clicked.connect(self._reset_filters)
        action_row.addWidget(self.reset_btn)
        self.record_custody_btn = QPushButton("Record Custody Event")
        self.record_custody_btn.setProperty("secondary", True)
        self.record_custody_btn.setVisible(False)
        self.record_custody_btn.clicked.connect(self._record_custody_event)
        action_row.addWidget(self.record_custody_btn)
        action_row.addStretch(1)
        self.export_btn = QPushButton("Export…")
        self.export_btn.setToolTip("Export the displayed records in the current tab, after filtering.")
        self.export_btn.setProperty("secondary", True)
        self.export_btn.clicked.connect(self._export_current)
        action_row.addWidget(self.export_btn)
        layout.addLayout(action_row)

        self.custom_range = QWidget()
        date_row = QHBoxLayout(self.custom_range)
        date_row.setContentsMargins(0, 0, 0, 0)
        self.date_from = QDateEdit()
        self.date_to = QDateEdit()
        for picker in (self.date_from, self.date_to):
            picker.setDisplayFormat("yyyy-MM-dd")
            picker.setCalendarPopup(True)
            picker.setMinimumDate(QDate(2000, 1, 1))
            picker.setMaximumDate(QDate.currentDate())
            picker.setDate(QDate.currentDate())
        self.date_from.setDate(QDate.currentDate().addDays(-29))
        date_row.addWidget(QLabel("From:"))
        date_row.addWidget(self.date_from)
        date_row.addWidget(QLabel("To:"))
        date_row.addWidget(self.date_to)
        date_row.addStretch(1)
        self.custom_range.setVisible(False)
        layout.addWidget(self.custom_range)

        self.count_label = QLabel("No events loaded")
        self.count_label.setProperty("caption", True)
        self.count_label.setWordWrap(True)
        layout.addWidget(self.count_label)

        self.tabs = QTabWidget()
        self.audit_table = self._make_table(AuditTableModel)
        self.audit_detail = AuditDetailPane()
        self.audit_splitter = self._make_splitter(self.audit_table, self.audit_detail)
        self.custody_table = self._make_table(CustodyTableModel)
        self.custody_detail = AuditDetailPane()
        self.custody_splitter = self._make_splitter(self.custody_table, self.custody_detail)
        self.audit_table.selectionModel().selectionChanged.connect(
            lambda *_args: self._on_selection_changed(self.audit_table)
        )
        self.custody_table.selectionModel().selectionChanged.connect(
            lambda *_args: self._on_selection_changed(self.custody_table)
        )
        self.tabs.addTab(self.audit_splitter, "Audit Trail")
        self.tabs.addTab(self.custody_splitter, "Chain of Custody")
        layout.addWidget(self.tabs, 1)

        self.type_filter.currentTextChanged.connect(self._apply_filters)
        self.result_filter.currentTextChanged.connect(self._apply_filters)
        self.user_filter.textChanged.connect(self._apply_filters)
        self.date_preset.currentIndexChanged.connect(self._on_date_preset_changed)
        self.date_from.dateChanged.connect(self._apply_filters)
        self.date_to.dateChanged.connect(self._apply_filters)
        self.tabs.currentChanged.connect(self._on_tab_changed)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.filter_row.setDirection(
            QBoxLayout.Direction.LeftToRight if event.size().width() >= 800
            else QBoxLayout.Direction.TopToBottom
        )

    @staticmethod
    def _make_table(model_type):
        table = QTableView()
        model = model_type(table)
        table.setModel(model)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.setAlternatingRowColors(True)
        table.setWordWrap(False)
        table.verticalHeader().setVisible(False)
        table.setSortingEnabled(False)
        header = table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setStretchLastSection(True)
        return table

    @staticmethod
    def _make_splitter(table: QTableView, detail: AuditDetailPane) -> QSplitter:
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(table)
        splitter.addWidget(detail)
        configure_detail_splitter(splitter, preferred_detail_width=360)
        return splitter

    def _on_selection_changed(self, table: QTableView):
        selected = table.selectionModel().selectedRows()
        if selected:
            row = selected[0].row()
            if table is self.audit_table:
                events = self.audit_table.model().events
                self.audit_detail.set_audit_event(events[row] if row < len(events) else None)
            else:
                events = self.custody_table.model().events
                self.custody_detail.set_custody_event(events[row] if row < len(events) else None)
        elif table is self.audit_table:
            self.audit_detail.set_audit_event(None)
        else:
            self.custody_detail.set_custody_event(None)

    def set_audit_service(self, service):
        self.audit_service = service
        self.refresh()

    def set_case_context(self, context: CaseContext):
        self.case_context = context
        self.refresh()

    def on_page_shown(self):
        self.refresh()

    def refresh(self):
        if not self.audit_service or not self.case_context or not self.case_context.case_id:
            self._all_audit_events = []
            self._all_custody_events = []
            self._apply_filters()
            return
        try:
            # Finish the previous read transaction so updates committed by
            # Evidence/Examination services in other sessions are visible.
            self.audit_service.session.rollback()
            self._all_audit_events = self.audit_service.get_case_audit_events(
                self.case_context.case_id, limit=self.RECORD_LIMIT
            )
            self._all_custody_events = self.audit_service.get_case_custody_events(
                self.case_context.case_id, limit=self.RECORD_LIMIT
            )
        except Exception as exc:
            try:
                self.audit_service.session.rollback()
            except Exception:
                pass
            self._all_audit_events = []
            self._all_custody_events = []
            self._apply_filters()
            QMessageBox.warning(self, "Audit data unavailable", f"Could not load case audit/custody history:\n{exc}")
            return
        self._update_type_filter()
        self._apply_filters()

    def _update_type_filter(self):
        current = self.type_filter.currentText()
        values = sorted({event.event_type for event in self._all_audit_events if event.event_type})
        self.type_filter.blockSignals(True)
        self.type_filter.clear()
        self.type_filter.addItem("All Types")
        self.type_filter.addItems(values)
        index = self.type_filter.findText(current)
        self.type_filter.setCurrentIndex(index if index >= 0 else 0)
        self.type_filter.blockSignals(False)

    def _date_range(self) -> tuple[date | None, date | None]:
        key = self.date_preset.currentData()
        today = QDate.currentDate()
        if key == "today":
            return today.toPython(), today.toPython()
        if key == "last7":
            return today.addDays(-6).toPython(), today.toPython()
        if key == "last30":
            return today.addDays(-29).toPython(), today.toPython()
        if key == "last90":
            return today.addDays(-89).toPython(), today.toPython()
        if key == "year":
            return date(today.year(), 1, 1), today.toPython()
        if key == "custom":
            start, end = self.date_from.date().toPython(), self.date_to.date().toPython()
            return (end, start) if start > end else (start, end)
        return None, None

    def _on_date_preset_changed(self):
        custom = self.date_preset.currentData() == "custom"
        self.custom_range.setVisible(custom)
        if custom:
            today = QDate.currentDate()
            self.date_from.setMaximumDate(today)
            self.date_to.setMaximumDate(today)
        self._apply_filters()

    def _apply_filters(self, *_args):
        event_type = self.type_filter.currentText()
        result = self.result_filter.currentText()
        username = self.user_filter.text().strip().casefold()
        from_date, to_date = self._date_range()

        def in_date_range(timestamp):
            event_date = timestamp.date() if timestamp else None
            return not (
                (from_date and (event_date is None or event_date < from_date))
                or (to_date and (event_date is None or event_date > to_date))
            )

        audit_events = []
        for event in self._all_audit_events:
            if event_type != "All Types" and event.event_type != event_type:
                continue
            if result != "All Results" and event.result != result:
                continue
            event_user = (event.user.username if event.user else "System").casefold()
            if username and username not in event_user:
                continue
            if in_date_range(event.timestamp):
                audit_events.append(event)

        custody_events = []
        for event in self._all_custody_events:
            event_user = (event.performed_by.username if event.performed_by else "Unknown").casefold()
            if username and username not in event_user:
                continue
            if in_date_range(event.performed_at):
                custody_events.append(event)

        self.audit_table.model().populate(audit_events)
        self.custody_table.model().populate(custody_events)
        self.audit_detail.set_audit_event(None)
        self.custody_detail.set_custody_event(None)
        self.audit_table.clearSelection()
        self.custody_table.clearSelection()
        self._update_count()

    def _update_count(self, *_args):
        if not hasattr(self, "tabs"):
            return
        if self.tabs.currentIndex() == 0:
            count = self.audit_table.model().rowCount()
            total = len(self._all_audit_events)
            name = "audit events"
        else:
            count = self.custody_table.model().rowCount()
            total = len(self._all_custody_events)
            name = "chain-of-custody records"
        text = f"Showing {count} of {total} loaded {name}. Export includes only displayed records."
        text += f" Up to the newest {self.RECORD_LIMIT:,} records are loaded per tab before filtering."
        if total >= self.RECORD_LIMIT:
            text += " Load limit reached; older records may be omitted from display and export."
        if self.tabs.currentIndex() == 1:
            text += " Type and result filters apply only to the audit trail."
        self.count_label.setText(text)

    def _on_tab_changed(self, index: int):
        self.type_filter.setEnabled(index == 0)
        self.result_filter.setEnabled(index == 0)
        self.record_custody_btn.setVisible(index == 1)
        self._update_count()

    def _record_custody_event(self):
        if not self.audit_service or not self.case_context or not self.case_context.case_id:
            QMessageBox.warning(self, "No case", "Open a case before recording custody history.")
            return
        try:
            from sqlalchemy import select

            self.audit_service.session.rollback()
            evidence_items = list(self.audit_service.session.execute(
                select(Evidence)
                .where(Evidence.case_id == self.case_context.case_id)
                .order_by(Evidence.evidence_id)
            ).scalars().all())
        except Exception as exc:
            QMessageBox.critical(self, "Evidence unavailable", f"Could not load this case's evidence:\n{exc}")
            return
        if not evidence_items:
            QMessageBox.information(
                self, "No evidence registered",
                "Register evidence for this case before adding a custody event.",
            )
            return
        dialog = RecordCustodyDialog(evidence_items, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        data = dialog.get_data()
        if not data["description"]:
            QMessageBox.warning(self, "Description required", "Describe the custody event before saving.")
            return

        user_id = None
        if self.nav is not None and callable(getattr(self.nav, "get_current_user", None)):
            try:
                user_id = getattr(self.nav.get_current_user(), "id", None)
            except Exception:
                user_id = None
        if user_id is None:
            QMessageBox.warning(self, "Not signed in", "A signed-in investigator is required to record custody.")
            return
        try:
            from app.auth.models import User

            session = self.audit_service.session
            user = session.get(User, user_id)
            if user is None or not user.is_active:
                raise ValueError("The signed-in account is no longer active")
            self.audit_service.record_custody_event(
                case_id=self.case_context.case_id,
                performed_by=user,
                **data,
            )
            session.commit()
        except Exception as exc:
            self.audit_service.session.rollback()
            QMessageBox.critical(self, "Could not record custody event", str(exc))
            return
        self.refresh()
        QMessageBox.information(self, "Custody event recorded", "The event was added to the case custody history.")

    def _reset_filters(self):
        self.type_filter.blockSignals(True)
        self.result_filter.blockSignals(True)
        self.user_filter.blockSignals(True)
        self.date_preset.blockSignals(True)
        self.date_from.blockSignals(True)
        self.date_to.blockSignals(True)
        self.type_filter.setCurrentIndex(0)
        self.result_filter.setCurrentIndex(0)
        self.user_filter.clear()
        self.date_preset.setCurrentIndex(0)
        today = QDate.currentDate()
        self.date_from.setDate(today.addDays(-29))
        self.date_to.setDate(today)
        self.type_filter.blockSignals(False)
        self.result_filter.blockSignals(False)
        self.user_filter.blockSignals(False)
        self.date_preset.blockSignals(False)
        self.date_from.blockSignals(False)
        self.date_to.blockSignals(False)
        self.custom_range.hide()
        self._apply_filters()

    def _export_current(self):
        if not self.case_context:
            return
        is_custody = self.tabs.currentIndex() == 1
        export_type = "custody" if is_custody else "audit"
        if is_custody:
            rows = []
            for event in self.custody_table.model().events:
                evidence = event.evidence
                try:
                    metadata = json.loads(event.metadata_json) if event.metadata_json else None
                except (TypeError, json.JSONDecodeError):
                    metadata = event.metadata_json
                rows.append({
                    "timestamp": event.performed_at.isoformat() if event.performed_at else None,
                    "event_type": event.event_type,
                    "evidence_id": evidence.evidence_id if evidence else None,
                    "evidence_name": evidence.name if evidence else None,
                    "performed_by": event.performed_by.username if event.performed_by else "Unknown",
                    "description": event.description,
                    "source_location": event.source_location,
                    "destination_location": event.destination_location,
                    "tool_used": event.tool_used,
                    "metadata": metadata,
                })
        else:
            rows = []
            for event in self.audit_table.model().events:
                try:
                    details = json.loads(event.details_json) if event.details_json else None
                except (TypeError, json.JSONDecodeError):
                    details = event.details_json
                rows.append({
                    "event_id": event.event_id,
                    "timestamp": event.timestamp.isoformat() if event.timestamp else None,
                    "event_type": event.event_type,
                    "action": event.action,
                    "result": event.result,
                    "user": event.user.username if event.user else "System",
                    "target_type": event.target_type,
                    "target_id": event.target_id,
                    "details": details,
                    "error": event.error_message,
                    "ip_address": event.ip_address,
                    "request_id": event.request_id,
                })
        if not rows:
            QMessageBox.information(self, "Nothing to export", "No records are displayed in this tab. Adjust the filters or refresh to check for records.")
            return
        case_tag = self.case_context.case_id_str or f"case-{self.case_context.case_id}"
        path, selected_filter = QFileDialog.getSaveFileName(
            self,
            "Export case history",
            f"{case_tag}_{export_type}.json",
            "JSON files (*.json);;CSV files (*.csv)",
        )
        if not path:
            return
        destination = Path(path)
        try:
            if destination.suffix.lower() == ".csv" or "CSV" in selected_filter:
                if destination.suffix.lower() != ".csv":
                    destination = destination.with_suffix(".csv")
                with destination.open("w", encoding="utf-8-sig", newline="") as stream:
                    writer = csv.DictWriter(stream, fieldnames=list(rows[0].keys()))
                    writer.writeheader()
                    writer.writerows({
                        key: json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else value
                        for key, value in row.items()
                    } for row in rows)
            else:
                if destination.suffix.lower() != ".json":
                    destination = destination.with_suffix(".json")
                destination.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
        except (OSError, csv.Error, TypeError, ValueError) as exc:
            QMessageBox.critical(self, "Export failed", f"Could not export records:\n{exc}")
            return
        QMessageBox.information(self, "Export complete", f"Exported {len(rows)} records to:\n{destination}")
