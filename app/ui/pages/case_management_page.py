"""Case Management Page - Global dashboard."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from PySide6.QtCore import QSortFilterProxyModel, Qt, Signal
from PySide6.QtGui import QAction, QFont, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QTableView,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.auth.models import User, UserRole
from app.cases.service import CaseService
from app.ui.base import ResponsivePage, StatCard
from app.ui.theme.tokens import Color, Spacing, Typography
from app.util.time import format_local_date

if TYPE_CHECKING:
    pass


class NewCaseDialog(QDialog):
    """Dialog for creating a new case."""

    def __init__(
        self,
        investigators: list,
        parent: QWidget | None = None,
        *,
        show_assignee: bool = True,
    ):
        super().__init__(parent)
        self.setWindowTitle("New Case")
        self.setModal(True)
        self.resize(500, 450)

        layout = QFormLayout(self)
        layout.setSpacing(Spacing.MD)
        layout.setContentsMargins(Spacing.LG, Spacing.LG, Spacing.LG, Spacing.LG)

        self.case_id_edit = QLineEdit()
        self.case_id_edit.setPlaceholderText("e.g., CASE-2024-001")
        layout.addRow("Case ID:", self.case_id_edit)

        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("Case title")
        layout.addRow("Title:", self.title_edit)

        self.description_edit = QTextEdit()
        self.description_edit.setPlaceholderText("Case description")
        self.description_edit.setMaximumHeight(80)
        layout.addRow("Description:", self.description_edit)

        self.objective_edit = QTextEdit()
        self.objective_edit.setPlaceholderText("Investigation objective")
        self.objective_edit.setMaximumHeight(80)
        layout.addRow("Objective:", self.objective_edit)

        self.priority_combo = QComboBox()
        self.priority_combo.addItems(["low", "medium", "high", "critical"])
        self.priority_combo.setCurrentText("medium")
        layout.addRow("Priority:", self.priority_combo)

        self.assignee_combo: QComboBox | None = None
        if show_assignee:
            self.assignee_combo = QComboBox()
            self.assignee_combo.addItem("Unassigned", 0)
            for inv in investigators:
                self.assignee_combo.addItem(f"{inv.full_name} ({inv.username})", inv.id)
            layout.addRow("Assignee:", self.assignee_combo)
        else:
            # Keep the investigator-facing create form focused on case details;
            # the case creator remains responsible for the case by ownership.
            self.resize(500, 400)

        self.status_combo = QComboBox()
        self.status_combo.addItems(["open", "active", "on_hold", "closed"])
        self.status_combo.setCurrentText("open")
        layout.addRow("Status:", self.status_combo)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def get_data(self) -> dict:
        return {
            "case_id": self.case_id_edit.text().strip(),
            "title": self.title_edit.text().strip(),
            "description": self.description_edit.toPlainText().strip() or None,
            "objective": self.objective_edit.toPlainText().strip() or None,
            "priority": self.priority_combo.currentText(),
            "status": self.status_combo.currentText(),
            "assignee_id": (
                self.assignee_combo.currentData() or None
                if self.assignee_combo is not None else None
            ),
        }


class EditCaseDialog(QDialog):
    """Dialog for editing an existing case."""

    def __init__(self, case, investigators: list, parent: QWidget | None = None):
        super().__init__(parent)
        self.case = case
        self.setWindowTitle(f"Edit Case: {case.case_id}")
        self.setModal(True)
        self.resize(500, 450)

        layout = QFormLayout(self)
        layout.setSpacing(Spacing.MD)
        layout.setContentsMargins(Spacing.LG, Spacing.LG, Spacing.LG, Spacing.LG)

        self.case_id_edit = QLineEdit(case.case_id)
        self.case_id_edit.setReadOnly(True)
        layout.addRow("Case ID:", self.case_id_edit)

        self.title_edit = QLineEdit(case.title)
        layout.addRow("Title:", self.title_edit)

        self.description_edit = QTextEdit()
        self.description_edit.setPlainText(case.description or "")
        self.description_edit.setMaximumHeight(80)
        layout.addRow("Description:", self.description_edit)

        self.objective_edit = QTextEdit()
        self.objective_edit.setPlainText(case.objective or "")
        self.objective_edit.setMaximumHeight(80)
        layout.addRow("Objective:", self.objective_edit)

        self.priority_combo = QComboBox()
        self.priority_combo.addItems(["low", "medium", "high", "critical"])
        self.priority_combo.setCurrentText(case.priority)
        layout.addRow("Priority:", self.priority_combo)

        self.status_combo = QComboBox()
        self.status_combo.addItems(["open", "active", "on_hold", "closed"])
        self.status_combo.setCurrentText(case.status)
        layout.addRow("Status:", self.status_combo)

        self.assignee_combo = QComboBox()
        self.assignee_combo.addItem("Unassigned", 0)
        for inv in investigators:
            self.assignee_combo.addItem(f"{inv.full_name} ({inv.username})", inv.id)
        if case.assignee_id:
            idx = self.assignee_combo.findData(case.assignee_id)
            if idx >= 0:
                self.assignee_combo.setCurrentIndex(idx)
        layout.addRow("Assignee:", self.assignee_combo)

        self.closed_at_label = QLabel()
        if case.closed_at:
            self.closed_at_label.setText(f"Closed: {format_local_date(case.closed_at)}")
        else:
            self.closed_at_label.setText("Not closed")
        self.closed_at_label.setStyleSheet(f"color: {Color.TEXT_MUTED.name()};")
        layout.addRow("", self.closed_at_label)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def get_data(self) -> dict:
        return {
            "title": self.title_edit.text().strip(),
            "description": self.description_edit.toPlainText().strip() or None,
            "objective": self.objective_edit.toPlainText().strip() or None,
            "priority": self.priority_combo.currentText(),
            "status": self.status_combo.currentText(),
            "assignee_id": self.assignee_combo.currentData() or None,
        }


class CaseTableModel(QStandardItemModel):
    """Table model for cases."""

    HEADERS = ["Case ID", "Title", "Status", "Priority", "Assignee", "Created", "Last Activity"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setHorizontalHeaderLabels(self.HEADERS)

    def populate(self, cases: list):
        self.removeRows(0, self.rowCount())
        for case in cases:
            row = [
                QStandardItem(case.case_id),
                QStandardItem(case.title),
                QStandardItem(case.status),
                QStandardItem(case.priority),
                QStandardItem(case.assignee.full_name if case.assignee else "Unassigned"),
                QStandardItem(format_local_date(case.created_at) if case.created_at else ""),
                QStandardItem(format_local_date(case.updated_at) if case.updated_at else ""),
            ]
            # Make non-editable
            for item in row:
                item.setEditable(False)
            self.appendRow(row)


class CaseFilterProxyModel(QSortFilterProxyModel):
    """Proxy model for filtering cases."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.setFilterKeyColumn(-1)  # Search all columns

    def set_filters(self, status: str = None, priority: str = None, search: str = None):
        self._status_filter = status
        self._priority_filter = priority
        self._search_filter = search or ""
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row, source_parent) -> bool:
        model = self.sourceModel()
        if not model:
            return False

        # Status filter
        if hasattr(self, '_status_filter') and self._status_filter and self._status_filter != "All":
            status_idx = model.index(source_row, 2, source_parent)
            if model.data(status_idx) != self._status_filter:
                return False

        # Priority filter
        if hasattr(self, '_priority_filter') and self._priority_filter and self._priority_filter != "All":
            priority_idx = model.index(source_row, 3, source_parent)
            if model.data(priority_idx) != self._priority_filter:
                return False

        # Search filter
        if hasattr(self, '_search_filter') and self._search_filter:
            search_lower = self._search_filter.lower()
            match = False
            for col in range(model.columnCount()):
                idx = model.index(source_row, col, source_parent)
                data = model.data(idx)
                if data and search_lower in str(data).lower():
                    match = True
                    break
            if not match:
                return False

        return True


class CaseManagementPage(ResponsivePage):
    """Global case management dashboard."""

    open_case_requested = Signal(int, str, str, str, str)

    def __init__(self, nav_controller, parent: QWidget | None = None):
        super().__init__(parent=parent)
        self.nav = nav_controller
        self.case_service: CaseService | None = None
        self.current_user: User | None = None
        self._cases_cache: list = []
        

    def _setup_layout(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(Spacing.LG, Spacing.LG, Spacing.LG, Spacing.LG)
        layout.setSpacing(Spacing.LG)

        # Keep the page title aligned with the page actions.
        header_row = QHBoxLayout()
        title = QLabel("Case Management")
        title.setProperty("pageTitle", True)
        title.setFont(
            QFont(
                Typography.FONT_FAMILY,
                Typography.HEADING_LG[0],
                Typography.HEADING_LG[1],
            )
        )
        header_row.addWidget(title)
        header_row.addStretch()

        self.new_case_btn = QPushButton("+ New Case")
        self.new_case_btn.clicked.connect(self._on_new_case)
        header_row.addWidget(self.new_case_btn)
        layout.addLayout(header_row)

        # Stat cards
        self.cards_layout = QGridLayout()
        self.cards_layout.setSpacing(Spacing.MD)
        self.stat_cards = {
            "total": StatCard("Total Cases", "0", "📁", Color.INFO),
            "active": StatCard("Active", "0", "🟢", Color.SUCCESS),
            "on_hold": StatCard("On Hold", "0", "🟡", Color.WARNING),
            "closed": StatCard("Closed", "0", "🔴", Color.ERROR),
            "needs_attention": StatCard("Needs Attention", "0", "⚠️", Color.ERROR),
        }
        for key, card in self.stat_cards.items():
            card.clicked.connect(lambda _, k=key: self._on_stat_card_clicked(k))
            self.cards_layout.addWidget(card, 0, self.cards_layout.count())
        layout.addLayout(self.cards_layout)

        # Filters
        filter_row = QGridLayout()
        filter_row.setSpacing(Spacing.SM)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search cases...")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(self._on_search_changed)
        self.search_edit.setMinimumWidth(150)
        self.search_edit.setMaximumWidth(300)
        self.search_edit.setFixedHeight(36)
        search_label = QLabel("Search:")

        self.status_filter = QComboBox()
        self.status_filter.addItems(["All", "open", "active", "on_hold", "closed"])
        self.status_filter.currentTextChanged.connect(self._apply_filters)
        self.status_filter.setFixedHeight(36)
        status_label = QLabel("Status:")

        self.priority_filter = QComboBox()
        self.priority_filter.addItems(["All", "low", "medium", "high", "critical"])
        self.priority_filter.currentTextChanged.connect(self._apply_filters)
        self.priority_filter.setFixedHeight(36)
        priority_label = QLabel("Priority:")

        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.setProperty("secondary", True)
        self.refresh_btn.setFixedHeight(36)
        self.refresh_btn.clicked.connect(self.refresh)

        self.export_btn = QPushButton("Export CSV")
        self.export_btn.setProperty("secondary", True)
        self.export_btn.setFixedHeight(36)
        self.export_btn.clicked.connect(self._export_cases_selected)
        self._filter_row = filter_row
        self._filter_widgets = [search_label, self.search_edit, status_label,
                                self.status_filter, priority_label, self.priority_filter,
                                self.refresh_btn, self.export_btn]
        self._compact_layout = None
        self._arrange_toolbar(True)
        layout.addLayout(filter_row)

        # Case table
        self.table_view = QTableView()
        self.table_model = CaseTableModel(self.table_view)
        self.proxy_model = CaseFilterProxyModel(self)
        self.proxy_model.setSourceModel(self.table_model)
        self.table_view.setModel(self.proxy_model)
        self.table_view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table_view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table_view.setAlternatingRowColors(True)
        self.table_view.verticalHeader().setVisible(False)
        self.table_view.setSortingEnabled(True)
        # Column sizing: Case ID resize to content, Title stretch, others resize to content
        header = self.table_view.horizontalHeader()
        # Keep the title legible when the narrow table needs horizontal scrolling.
        header.setMinimumSectionSize(90)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)  # Case ID
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)           # Title
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)  # Status
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)  # Priority
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)  # Assignee
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)  # Created
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)  # Last Activity
        header.setStretchLastSection(False)
        self.table_view.doubleClicked.connect(self._on_double_click)
        # Context menu for right-click
        self.table_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table_view.customContextMenuRequested.connect(self._show_context_menu)
        layout.addWidget(self.table_view, 1)

        # Empty state label (shown when no cases)
        self.empty_label = QLabel("No cases yet. Click + New Case to create one.")
        self.empty_label.setObjectName("EmptyStateMessage")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setStyleSheet(f"color: {Color.TEXT_MUTED.name()}; font-size: 14px; padding: 48px;")
        self.empty_label.hide()
        layout.addWidget(self.empty_label, 1)

    def _arrange_toolbar(self, compact: bool):
        if compact == self._compact_layout:
            return
        self._compact_layout = compact
        for index, card in enumerate(self.stat_cards.values()):
            self.cards_layout.addWidget(card, index // 3 if compact else 0,
                                        index % 3 if compact else index)
        for widget in self._filter_widgets:
            self._filter_row.removeWidget(widget)
        for index, widget in enumerate(self._filter_widgets):
            if compact and index >= 4:
                self._filter_row.addWidget(widget, 1, index - 4)
            else:
                self._filter_row.addWidget(widget, 0, index)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._arrange_toolbar(event.size().width() < 900)

    def set_user(self, user: User):
        self.current_user = user

    def set_case_service(self, service: CaseService):
        self.case_service = service

    def refresh(self):
        if not self.case_service or not self.current_user:
            return

        # Update stats
        stats = self.case_service.get_case_stats(self.current_user)
        self.stat_cards["total"].set_value(str(stats["total"]))
        self.stat_cards["active"].set_value(str(stats["active"]))
        self.stat_cards["on_hold"].set_value(str(stats["on_hold"]))
        self.stat_cards["closed"].set_value(str(stats["closed"]))
        self.stat_cards["needs_attention"].set_value(str(stats["needs_attention"]))

        # Update table
        self._cases_cache = self.case_service.list_cases(self.current_user)
        self.table_model.populate(self._cases_cache)
        self._apply_filters()

    def _apply_filters(self):
        status = self.status_filter.currentText()
        priority = self.priority_filter.currentText()
        search = self.search_edit.text()

        self.proxy_model.set_filters(
            status=status if status != "All" else None,
            priority=priority if priority != "All" else None,
            search=search if search else None
        )

        # Show/hide empty state
        row_count = self.proxy_model.rowCount()
        if row_count == 0:
            if self.table_model.rowCount():
                self.empty_label.setText("No cases match the current filters.")
            else:
                self.empty_label.setText("No cases yet. Click + New Case to create one.")
            self.table_view.hide()
            self.empty_label.show()
        else:
            self.table_view.show()
            self.empty_label.hide()

    def set_search_text(self, text: str) -> None:
        """Set search text from header and trigger filter."""
        self.search_edit.setText(text)
        self._apply_filters()

    def _on_search_changed(self, text: str):
        self._apply_filters()

    def _on_stat_card_clicked(self, key: str):
        """Filter table when a stat card is clicked."""
        status_map = {
            "total": "All",
            "active": "active",
            "on_hold": "on_hold",
            "closed": "closed",
            "needs_attention": "high",  # This would need special handling
        }
        if key in status_map:
            self.status_filter.setCurrentText(status_map[key])
            self._apply_filters()

    def _export_cases_selected(self):
        """Export selected cases to CSV."""
        selection = self.table_view.selectionModel().selectedRows()
        if not selection:
            QMessageBox.warning(self, "No Selection", "Please select cases to export.")
            return

        path, _ = QFileDialog.getSaveFileName(
            self, "Export Cases", "cases_export.csv", "CSV Files (*.csv)"
        )
        if not path:
            return

        try:
            import csv
            from io import StringIO

            # Get selected cases
            cases_to_export = []
            for proxy_index in selection:
                source_index = self.proxy_model.mapToSource(proxy_index)
                row = source_index.row()
                case_id = self.table_model.item(row, 0).text()
                for case in self._cases_cache:
                    if case.case_id == case_id:
                        cases_to_export.append(case)
                        break

            if not cases_to_export:
                QMessageBox.warning(self, "No Cases", "No valid cases selected for export.")
                return

            output = StringIO()
            writer = csv.writer(output)
            writer.writerow(["Case ID", "Title", "Status", "Priority", "Assignee", "Created", "Last Updated"])

            for case in cases_to_export:
                writer.writerow([
                    case.case_id,
                    case.title,
                    case.status,
                    case.priority,
                    case.assignee.full_name if case.assignee else "Unassigned",
                    format_local_date(case.created_at) if case.created_at else "",
                    format_local_date(case.updated_at) if case.updated_at else "",
                ])

            with open(path, "w", newline="", encoding="utf-8") as f:
                f.write(output.getvalue())

            QMessageBox.information(self, "Export Complete", f"Exported {len(cases_to_export)} cases to {path}")

        except Exception as e:
            QMessageBox.critical(self, "Export Failed", f"Failed to export cases: {e}")

    def _on_new_case(self):
        if not self.current_user:
            return

        role = getattr(self.current_user, "role", None)
        role_value = getattr(role, "value", role)
        is_admin = str(role_value).strip().lower() == UserRole.ADMIN.value

        investigators = []
        if is_admin:
            from app.auth.service import AuthService
            from app.db.session import session_scope

            with session_scope() as session:
                auth_service = AuthService(session)
                investigators = [
                    u for u in auth_service.list_users()
                    if u.role.value in (UserRole.ADMIN.value, UserRole.INVESTIGATOR.value)
                ]

        dialog = NewCaseDialog(investigators, self, show_assignee=is_admin)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            data = dialog.get_data()
            if not data["case_id"] or not data["title"]:
                QMessageBox.warning(self, "Validation Error", "Case ID and Title are required")
                return

            try:
                with session_scope() as session:
                    case_service = CaseService(session)
                    case = case_service.create_case(
                        case_id=data["case_id"],
                        title=data["title"],
                        description=data["description"],
                        objective=data["objective"],
                        priority=data["priority"],
                        created_by=self.current_user,
                        # Investigators cannot assign other users from the
                        # create form; administrators retain assignment control.
                        assignee_id=data["assignee_id"] if is_admin else None,
                    )
                    session.commit()
                self.refresh()
                QMessageBox.information(self, "Success", f"Case '{case.case_id}' created successfully")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to create case: {e}")

    def _on_double_click(self, index):
        # Map proxy index to source index
        source_index = self.proxy_model.mapToSource(index)
        row = source_index.row()
        case_id = self.table_model.item(row, 0).text()
        # Find the case object from cache (matches table display)
        for case in self._cases_cache:
            if case.case_id == case_id:
                self.open_case_requested.emit(
                    case.id, case.title, case.status, case.priority,
                    case.assignee.full_name if case.assignee else "Unassigned"
                )
                break

    def _show_context_menu(self, pos):
        index = self.table_view.indexAt(pos)
        if not index.isValid():
            return

        source_index = self.proxy_model.mapToSource(index)
        row = source_index.row()
        case_id = self.table_model.item(row, 0).text()

        # Find case
        case = None
        for c in self._cases_cache:
            if c.case_id == case_id:
                case = c
                break

        if not case:
            return

        menu = QMenu(self)

        # Open case action (primary)
        open_action = QAction("Open Case", self)
        open_action.triggered.connect(lambda: self.open_case_requested.emit(
            case.id, case.title, case.status, case.priority,
            case.assignee.full_name if case.assignee else "Unassigned"
        ))
        menu.addAction(open_action)

        menu.addSeparator()

        # Edit action
        edit_action = QAction("Edit", self)
        edit_action.triggered.connect(lambda: self._edit_case(case))
        menu.addAction(edit_action)

        # View details action
        view_action = QAction("View Details", self)
        view_action.triggered.connect(lambda: self._view_case_details(case))
        menu.addAction(view_action)

        menu.addSeparator()

        # Export action
        export_action = QAction("Export Case", self)
        export_action.triggered.connect(lambda: self._export_case(case))
        menu.addAction(export_action)

        menu.addSeparator()

        # Delete action
        delete_action = QAction("Delete", self)
        delete_action.setProperty("danger", True)
        delete_action.triggered.connect(lambda: self._delete_case(case))
        menu.addAction(delete_action)

        menu.exec(self.table_view.viewport().mapToGlobal(pos))

    def _edit_case(self, case):
        from app.auth.service import AuthService
        from app.db.session import session_scope

        with session_scope() as session:
            auth_service = AuthService(session)
            investigators = [u for u in auth_service.list_users() if u.role.value in ("admin", "investigator")]

        dialog = EditCaseDialog(case, investigators, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            data = dialog.get_data()
            try:
                with session_scope() as session:
                    case_service = CaseService(session)
                    case_service.update_case(
                        case.id,
                        title=data["title"],
                        description=data["description"],
                        objective=data.get("objective"),
                        priority=data["priority"],
                        status=data["status"],
                        assignee_id=data["assignee_id"],
                    )
                    session.commit()
                self.refresh()
                QMessageBox.information(self, "Success", f"Case '{case.case_id}' updated successfully")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to update case: {e}")

    def _view_case_details(self, case):
        dialog = QDialog(self)
        dialog.setWindowTitle(f"Case Details: {case.case_id}")
        dialog.setModal(True)
        dialog.resize(600, 500)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(Spacing.LG, Spacing.LG, Spacing.LG, Spacing.LG)
        layout.setSpacing(Spacing.MD)

        # Case info
        info_group = QGroupBox("Case Information")
        info_layout = QFormLayout(info_group)
        info_layout.setSpacing(Spacing.MD)

        fields = [
            ("Case ID", case.case_id),
            ("Title", case.title),
            ("Status", case.status.replace("_", " ").title()),
            ("Priority", case.priority.title()),
            ("Assignee", case.assignee.full_name if case.assignee else "Unassigned"),
            ("Created", format_local_date(case.created_at) if case.created_at else "—"),
            ("Last Updated", format_local_date(case.updated_at) if case.updated_at else "—"),
            ("Created By", case.created_by.full_name if case.created_by else "Unknown"),
        ]

        for label, value in fields:
            lbl = QLabel(label)
            lbl.setFont(QFont(Typography.FONT_FAMILY, Typography.BODY_SM[0]))
            lbl.setStyleSheet(f"color: {Color.TEXT_SECONDARY.name()};")
            val = QLabel(str(value))
            val.setFont(QFont(Typography.FONT_FAMILY, Typography.BODY_MD[0]))
            val.setWordWrap(True)
            info_layout.addRow(lbl, val)

        layout.addWidget(info_group)

        # Description
        desc_group = QGroupBox("Description")
        desc_layout = QVBoxLayout(desc_group)
        desc_text = QTextEdit()
        desc_text.setReadOnly(True)
        desc_text.setPlainText(case.description or "—")
        desc_text.setMaximumHeight(100)
        desc_layout.addWidget(desc_text)
        layout.addWidget(desc_group)

        # Objective
        obj_group = QGroupBox("Objective")
        obj_layout = QVBoxLayout(obj_group)
        obj_text = QTextEdit()
        obj_text.setReadOnly(True)
        obj_text.setPlainText(case.objective or "—")
        obj_text.setMaximumHeight(80)
        obj_layout.addWidget(obj_text)
        layout.addWidget(obj_group)

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(dialog.accept)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

        dialog.exec()

    def _delete_case(self, case):
        reply = QMessageBox.question(
            self, "Delete Case",
            f"Are you sure you want to delete case '{case.case_id}'?\n"
            "This will delete all associated evidence, examinations, artifacts, and findings.\n"
            "This action cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        from app.db.session import session_scope

        try:
            with session_scope() as session:
                case_service = CaseService(session)
                case_service.delete_case(case.id)
                session.commit()
            self.refresh()
            QMessageBox.information(self, "Success", f"Case '{case.case_id}' deleted successfully")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to delete case: {e}")

    def _export_case(self, case):
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Case", f"{case.case_id}_export.json", "JSON Files (*.json)"
        )
        if not path:
            return

        try:
            import json

            from app.artifacts.models import Artifact
            from app.db.session import session_scope
            from app.evidence.models import Evidence
            from app.examination.models import ExaminationJob
            from app.findings.models import Finding

            with session_scope() as session:
                # Gather all related data
                evidence = session.query(Evidence).filter(Evidence.case_id == case.id).all()
                examinations = session.query(ExaminationJob).filter(ExaminationJob.case_id == case.id).all()
                artifacts = session.query(Artifact).filter(Artifact.case_id == case.id).all()
                findings = session.query(Finding).filter(Finding.case_id == case.id).all()

            export_data = {
                "case": {
                    "case_id": case.case_id,
                    "title": case.title,
                    "description": case.description,
                    "objective": case.objective,
                    "status": case.status,
                    "priority": case.priority,
                    "created_at": case.created_at.isoformat() if case.created_at else None,
                    "updated_at": case.updated_at.isoformat() if case.updated_at else None,
                    "closed_at": case.closed_at.isoformat() if case.closed_at else None,
                },
                "evidence": [
                    {
                        "evidence_id": e.evidence_id,
                        "name": e.name,
                        "type": e.evidence_type.value,
                        "size_bytes": e.size_bytes,
                        "hashes": {h.algorithm.value: h.hash_value for h in e.hashes},
                    } for e in evidence
                ],
                "examinations": [
                    {
                        "job_id": e.job_id,
                        "operation": e.operation.value,
                        "status": e.status.value,
                        "started_at": e.started_at.isoformat() if e.started_at else None,
                        "completed_at": e.completed_at.isoformat() if e.completed_at else None,
                    } for e in examinations
                ],
                "artifacts": [
                    {
                        "artifact_id": a.artifact_id,
                        "type": a.artifact_type.value,
                        "name": a.name,
                        "source_path": a.source_path,
                        "content_text": a.content_text,
                        "content_hash": a.content_hash,
                    } for a in artifacts
                ],
                "findings": [
                    {
                        "finding_id": f.finding_id,
                        "title": f.title,
                        "status": f.status.value,
                        "origin": f.origin.value,
                    } for f in findings
                ],
                "exported_at": datetime.now(timezone.utc).isoformat(),
            }

            with open(path, "w", encoding="utf-8") as f:
                json.dump(export_data, f, indent=2, default=str)

            QMessageBox.information(self, "Export Complete", f"Case exported to {path}")

        except Exception as e:
            QMessageBox.critical(self, "Export Failed", f"Failed to export case: {e}")
