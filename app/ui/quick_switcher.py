"""Keyboard-driven navigation palette for the IDFA investigation workspace.

Only navigation destinations supplied by the active shell are displayed: the
dialog never constructs pages, bypasses role checks or performs forensic work.
"""
from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.ui.theme.tokens import Spacing


class QuickSwitcher(QDialog):
    """Find and switch to an allowed page without using the mouse.

    Entries contain ``(route, title, description)``. The caller is responsible
    for enumerating only destinations visible to the current user, then still
    applying normal navigation authorization when opening the selected route.
    """

    def __init__(
        self,
        entries: Sequence[tuple[str, str, str]],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("QuickSwitcher")
        self.setWindowTitle("Quick navigation")
        self.setModal(True)
        self.setMinimumWidth(420)
        self.resize(560, 420)
        self.selected_route: str | None = None
        self._entries = list(entries)
        self._setup_ui()
        self._apply_filter("")

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(Spacing.LG, Spacing.LG, Spacing.LG, Spacing.MD)
        layout.setSpacing(Spacing.MD)

        title_row = QHBoxLayout()
        title = QLabel("Go to a workspace")
        title.setObjectName("QuickSwitcherTitle")
        title_row.addWidget(title)
        title_row.addStretch()
        shortcut = QLabel("Ctrl+Shift+P")
        shortcut.setObjectName("QuickSwitcherShortcut")
        title_row.addWidget(shortcut)
        layout.addLayout(title_row)

        self.search = QLineEdit()
        self.search.setObjectName("QuickSwitcherSearch")
        self.search.setPlaceholderText("Search pages and tools…")
        self.search.setAccessibleName("Search navigation destinations")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._apply_filter)
        self.search.returnPressed.connect(self._activate_current)
        self.search.installEventFilter(self)
        layout.addWidget(self.search)

        self.results = QListWidget()
        self.results.setObjectName("QuickSwitcherList")
        self.results.setUniformItemSizes(True)
        self.results.setAlternatingRowColors(False)
        self.results.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.results.itemActivated.connect(self._activate_item)
        self.results.itemDoubleClicked.connect(self._activate_item)
        self.results.setAccessibleName("Matching navigation destinations")
        layout.addWidget(self.results, 1)

        self.empty_hint = QLabel("No matching pages. Try a different search.")
        self.empty_hint.setObjectName("QuickSwitcherEmpty")
        self.empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_hint.hide()
        layout.addWidget(self.empty_hint)

        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setObjectName("QuickSwitcherDivider")
        layout.addWidget(separator)

        footer = QLabel("↑ ↓  Navigate    Enter  Open    Esc  Close")
        footer.setObjectName("QuickSwitcherHint")
        footer.setAccessibleName("Use arrow keys to select, Enter to open, Escape to close")
        layout.addWidget(footer)
        self.search.setFocus(Qt.FocusReason.OtherFocusReason)

    def _apply_filter(self, query: str) -> None:
        """Filter destination names and descriptions without changing identity."""
        words = query.casefold().split()
        self.results.clear()
        for route, title, description in self._entries:
            searchable = f"{title} {description}".casefold()
            if not all(word in searchable for word in words):
                continue
            item = QListWidgetItem(title)
            item.setData(Qt.ItemDataRole.UserRole, route)
            item.setToolTip(description)
            item.setStatusTip(description)
            item.setData(Qt.ItemDataRole.AccessibleDescriptionRole, description)
            self.results.addItem(item)
        has_results = self.results.count() > 0
        self.results.setVisible(has_results)
        self.empty_hint.setVisible(not has_results)
        if has_results:
            self.results.setCurrentRow(0)

    def _activate_item(self, item: QListWidgetItem) -> None:
        route = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(route, str) and route:
            self.selected_route = route
            self.accept()

    def _activate_current(self) -> None:
        item = self.results.currentItem()
        if item is not None:
            self._activate_item(item)

    def eventFilter(self, watched, event) -> bool:
        if watched is self.search and event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if key in (Qt.Key.Key_Down, Qt.Key.Key_Up) and self.results.count():
                current = self.results.currentRow()
                delta = 1 if key == Qt.Key.Key_Down else -1
                self.results.setCurrentRow((current + delta) % self.results.count())
                return True
        return super().eventFilter(watched, event)
