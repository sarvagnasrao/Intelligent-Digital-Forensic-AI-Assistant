"""Global Audit Page - Audit log viewer."""
from __future__ import annotations

from datetime import date

from PySide6.QtCore import QDate, Qt, Slot
from PySide6.QtGui import QFont, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDateEdit,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSplitter,
    QTableView,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.audit.models import AuditEvent
from app.ui.base import CaseContext, ResponsivePage
from app.ui.layouts import configure_detail_pane, configure_detail_splitter
from app.ui.theme.tokens import Color, Spacing, Typography
from app.util.time import format_local_date


class AuditTableModel(QStandardItemModel):
    HEADERS = ["Time", "Event Type", "Action", "Result", "Target", "User", "Details"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._events: list[AuditEvent] = []
        self.setHorizontalHeaderLabels(self.HEADERS)

    def populate(self, events: list[AuditEvent]):
        self._events = list(events)
        self.removeRows(0, self.rowCount())
        for evt in events:
            target = f"{evt.target_type}:{evt.target_id}" if evt.target_type and evt.target_id else "—"
            user = evt.user.username if evt.user else "System"
            row = [
                QStandardItem(format_local_date(evt.timestamp) if evt.timestamp else ""),
                QStandardItem(evt.event_type),
                QStandardItem(evt.action),
                QStandardItem(evt.result),
                QStandardItem(target),
                QStandardItem(user),
                QStandardItem(evt.details_json or ""),
            ]
            for item in row:
                item.setEditable(False)
            # Color result
            result_item = row[3]
            if evt.result == "success":
                result_item.setForeground(Color.SUCCESS)
            elif evt.result == "failure":
                result_item.setForeground(Color.ERROR)
            self.appendRow(row)


class AuditDetailPane(QFrame):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("DetailPane")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        configure_detail_pane(self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(Spacing.MD, Spacing.MD, Spacing.MD, Spacing.MD)
        layout.setSpacing(Spacing.SM)

        self.title = QLabel("Select audit event to view details")
        self.title.setWordWrap(True)
        self.title.setFont(QFont(Typography.FONT_FAMILY, Typography.HEADING_SM[0], Typography.HEADING_SM[1]))
        layout.addWidget(self.title)

        self.detail_text = QTextEdit()
        self.detail_text.setReadOnly(True)
        self.detail_text.setFont(QFont(Typography.FONT_FAMILY, Typography.MONO_SM[0]))
        layout.addWidget(self.detail_text, 1)

    def set_event(self, event: AuditEvent | None):
        if not event:
            self.title.setText("Select audit event to view details")
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
            event.details_json or "—",
        ]
        if event.error_message:
            lines.extend(["", "Error:", event.error_message])

        self.detail_text.setPlainText("\n".join(lines))


class GlobalAuditPage(ResponsivePage):
    # (label, key) — "Any time" is the default so no bogus sentinel date is
    # ever rendered in a picker.
    DATE_PRESETS = (
        ("Any time", "any"),
        ("Today", "today"),
        ("Last 7 days", "last7"),
        ("Last 30 days", "last30"),
        ("Last 90 days", "last90"),
        ("This year", "year"),
        ("Custom range", "custom"),
    )

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent=parent)
        self.audit_service = None
        self._all_events: list[AuditEvent] = []

    def set_audit_service(self, service):
        self.audit_service = service
        self.refresh()

    def refresh(self):
        if not self.audit_service:
            return
        events = self.audit_service.get_global_audit_events(limit=500)
        self._all_events = list(events)
        self._update_type_filter(self._all_events)
        self._apply_filters()

    def _update_type_filter(self, events: list[AuditEvent]) -> None:
        current = self.type_filter.currentText()
        values = sorted({event.event_type for event in events if event.event_type})
        self.type_filter.blockSignals(True)
        self.type_filter.clear()
        self.type_filter.addItem("All Types")
        self.type_filter.addItems(values)
        index = self.type_filter.findText(current)
        self.type_filter.setCurrentIndex(index if index >= 0 else 0)
        self.type_filter.blockSignals(False)

    def _date_range(self) -> tuple[date | None, date | None]:
        """Resolve the date preset into an inclusive ``(from, to)`` range."""
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
            return QDate(today.year(), 1, 1).toPython(), today.toPython()
        if key == "custom":
            start, end = self.date_from.date(), self.date_to.date()
            if start > end:
                start, end = end, start
            return start.toPython(), end.toPython()
        return None, None

    def _apply_filters(self) -> None:
        events = getattr(self, "_all_events", [])
        event_type = self.type_filter.currentText()
        result = self.result_filter.currentText()
        username = self.user_filter.text().strip().casefold()
        from_date, to_date = self._date_range()

        filtered = []
        for event in events:
            if event_type != "All Types" and event.event_type != event_type:
                continue
            if result != "All Results" and event.result != result:
                continue
            event_user = (event.user.username if event.user else "System").casefold()
            if username and username not in event_user:
                continue
            event_date = event.timestamp.date() if event.timestamp else None
            if from_date and (event_date is None or event_date < from_date):
                continue
            if to_date and (event_date is None or event_date > to_date):
                continue
            filtered.append(event)

        self.table_model.populate(filtered)
        self.detail_pane.set_event(None)
        self._sync_detail_column()

    def _setup_layout(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(Spacing.LG, Spacing.LG, Spacing.LG, Spacing.LG)
        layout.setSpacing(Spacing.LG)

        # Filters -------------------------------------------------------------
        # The toolbar is a grid so it can drop the search field onto a second
        # row when the page is too narrow, instead of squeezing it to nothing.
        self.filter_bar = QWidget()
        self._filter_grid = QGridLayout(self.filter_bar)
        self._filter_grid.setContentsMargins(0, 0, 0, 0)
        self._filter_grid.setHorizontalSpacing(Spacing.SM)
        self._filter_grid.setVerticalSpacing(Spacing.SM)
        self._filters_single_row: bool | None = None
        layout.addWidget(self.filter_bar)

        self._type_label = self._filter_label("Type")
        self.type_filter = QComboBox()
        self.type_filter.addItem("All Types")
        self.type_filter.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToContentsOnFirstShow
        )
        self.type_filter.setMinimumWidth(128)

        self._result_label = self._filter_label("Result")
        self.result_filter = QComboBox()
        self.result_filter.addItems(["All Results", "success", "failure", "partial"])
        self.result_filter.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToContentsOnFirstShow
        )
        self.result_filter.setMinimumWidth(128)

        self.user_filter = QLineEdit()
        self.user_filter.setPlaceholderText("Filter by user...")
        self.user_filter.setMinimumWidth(150)

        self._date_label = self._filter_label("Date")
        self.date_preset = QComboBox()
        for label, key in self.DATE_PRESETS:
            self.date_preset.addItem(label, key)
        self.date_preset.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToContentsOnFirstShow
        )
        self.date_preset.setMinimumWidth(158)

        self.reset_filters_btn = QPushButton("Reset")
        self.reset_filters_btn.setProperty("ghost", True)
        self.reset_filters_btn.setToolTip("Clear all filters")
        self.reset_filters_btn.clicked.connect(self._reset_filters)

        self._filter_widgets = [
            self._type_label, self.type_filter,
            self._result_label, self.result_filter,
            self._date_label, self.date_preset,
            self.user_filter, self.reset_filters_btn,
        ]
        self._update_filter_layout()

        # A custom range needs real dates, so it only appears on demand instead
        # of crowding the toolbar with two empty pickers.
        self.custom_range = QWidget()
        custom_row = QHBoxLayout(self.custom_range)
        custom_row.setContentsMargins(0, 0, 0, 0)
        custom_row.setSpacing(Spacing.SM)

        self.date_from = QDateEdit()
        self.date_to = QDateEdit()
        for picker in (self.date_from, self.date_to):
            picker.setDisplayFormat("yyyy-MM-dd")
            picker.setCalendarPopup(True)
            picker.setMinimumDate(QDate(2000, 1, 1))
            picker.setMaximumDate(QDate.currentDate())
            picker.setDate(QDate.currentDate())

        today = QDate.currentDate()
        self.date_from.setDate(today.addDays(-29))
        self.date_to.setDate(today)

        custom_row.addWidget(self._filter_label("From"))
        custom_row.addWidget(self.date_from)
        custom_row.addSpacing(Spacing.SM)
        custom_row.addWidget(self._filter_label("To"))
        custom_row.addWidget(self.date_to)
        custom_row.addStretch()
        self.custom_range.setVisible(False)
        layout.addWidget(self.custom_range)

        self.type_filter.currentTextChanged.connect(self._apply_filters)
        self.result_filter.currentTextChanged.connect(self._apply_filters)
        self.user_filter.textChanged.connect(self._apply_filters)
        self.date_preset.currentIndexChanged.connect(self._on_date_preset_changed)
        self.date_from.dateChanged.connect(self._on_custom_range_changed)
        self.date_to.dateChanged.connect(self._on_custom_range_changed)

        # Splitter
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Table
        self.table_view = QTableView()
        self.table_model = AuditTableModel(self.table_view)
        self.table_view.setModel(self.table_model)
        self.table_view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table_view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table_view.setAlternatingRowColors(True)
        self.table_view.verticalHeader().setVisible(False)
        header = self.table_view.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        # Long action names would otherwise force the whole table wider than the
        # window; let this column elide instead.
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        self.table_view.setColumnWidth(2, 142)
        for column in (3, 4, 5):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)
        self.table_view.selectionModel().selectionChanged.connect(self._on_selection_changed)
        splitter.addWidget(self.table_view)

        # Detail pane
        self.detail_pane = AuditDetailPane()
        splitter.addWidget(self.detail_pane)

        configure_detail_splitter(splitter, preferred_detail_width=360)
        layout.addWidget(splitter, 1)

    @staticmethod
    def _filter_label(text: str) -> QLabel:
        label = QLabel(text)
        label.setProperty("caption", True)
        return label

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_filter_layout()
        self._sync_detail_column()

    def showEvent(self, event):
        super().showEvent(event)
        self._update_filter_layout()
        self._sync_detail_column()

    def _sync_detail_column(self) -> None:
        """Hide the Details column when it would collapse to a sliver.

        The detail pane already renders the full JSON, so on a narrow window
        the column is redundant rather than merely squeezed. Keeping it hidden
        also stops the remaining columns from being clipped.
        """
        if not hasattr(self, "table_view"):
            return

        view = self.table_view
        fixed = sum(view.sizeHintForColumn(column) for column in (0, 1, 3, 4, 5))
        fixed += view.columnWidth(2)
        viewport = view.viewport().width()

        if view.isColumnHidden(6):
            if viewport >= fixed + 140:
                view.setColumnHidden(6, False)
        elif viewport < fixed + 120:
            view.setColumnHidden(6, True)

    def _update_filter_layout(self) -> None:
        """Keep the toolbar on one row, wrapping the search field when tight."""
        if not hasattr(self, "_filter_grid"):
            return

        available = self.filter_bar.width() or self.width() - 2 * Spacing.LG
        needed = sum(
            max(widget.minimumSizeHint().width(), widget.minimumWidth())
            for widget in self._filter_widgets
        ) + Spacing.SM * (len(self._filter_widgets) - 1)

        single_row = available >= needed
        if single_row == self._filters_single_row:
            return
        self._filters_single_row = single_row

        grid = self._filter_grid
        for widget in self._filter_widgets:
            grid.removeWidget(widget)
        for column in range(len(self._filter_widgets)):
            grid.setColumnStretch(column, 0)

        if single_row:
            for column, widget in enumerate(self._filter_widgets):
                grid.addWidget(widget, 0, column)
            grid.setColumnStretch(self._filter_widgets.index(self.user_filter), 1)
        else:
            row = [w for w in self._filter_widgets if w is not self.user_filter]
            for column, widget in enumerate(row):
                grid.addWidget(widget, 0, column)
            grid.addWidget(self.user_filter, 1, 0, 1, len(row))

        grid.activate()

    @Slot()
    def _on_date_preset_changed(self) -> None:
        key = self.date_preset.currentData()
        self.custom_range.setVisible(key == "custom")
        if key == "custom":
            # Keep the pickers usable if the app has been left running overnight.
            today = QDate.currentDate()
            self.date_from.setMaximumDate(today)
            self.date_to.setMaximumDate(today)
            if self.date_to.date() > today:
                self.date_to.setDate(today)
        self._apply_filters()

    @Slot()
    def _on_custom_range_changed(self) -> None:
        if self.date_preset.currentData() == "custom":
            self._apply_filters()

    @Slot()
    def _reset_filters(self) -> None:
        widgets = (
            self.type_filter,
            self.result_filter,
            self.user_filter,
            self.date_preset,
            self.date_from,
            self.date_to,
        )
        for widget in widgets:
            widget.blockSignals(True)
        self.type_filter.setCurrentIndex(0)
        self.result_filter.setCurrentIndex(0)
        self.user_filter.clear()
        self.date_preset.setCurrentIndex(0)
        today = QDate.currentDate()
        self.date_from.setDate(today.addDays(-29))
        self.date_to.setDate(today)
        for widget in widgets:
            widget.blockSignals(False)

        self.custom_range.setVisible(False)
        self._apply_filters()

    def set_case_context(self, context: CaseContext):
        self.case_context = context
        self.refresh()

    def _on_selection_changed(self):
        indexes = self.table_view.selectionModel().selectedRows()
        if indexes:
            row = indexes[0].row()
            events = getattr(self.table_model, "_events", [])
            if 0 <= row < len(events):
                self.detail_pane.set_event(events[row])
                return
        self.detail_pane.set_event(None)
