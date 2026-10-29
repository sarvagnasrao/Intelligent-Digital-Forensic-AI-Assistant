"""Base UI components for IDFA - Professional Forensic Analysis."""
from __future__ import annotations

from PySide6.QtCore import QRect, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QPainter,
    QPainterPath,
    QPen,
    QStandardItem,
    QStandardItemModel,
)
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QVBoxLayout,
    QWidget,
)

from app.ui.icons import button_icon, draw_icon
from app.ui.theme.themed import ThemedWidget
from app.ui.theme.tokens import Color, Spacing, Typography


class SidebarWidget(QFrame):
    """Professional sidebar container with dark theme."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("SidebarWidget")
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        self.setMinimumWidth(240)
        self.setMaximumWidth(280)
        self._collapsed = False

    @property
    def collapsed(self) -> bool:
        return self._collapsed

    @collapsed.setter
    def collapsed(self, value: bool):
        self._collapsed = value
        if value:
            self.setMinimumWidth(68)
            self.setMaximumWidth(68)
        else:
            self.setMinimumWidth(240)
            self.setMaximumWidth(280)
        self.update()


class BrandingHeader(ThemedWidget, QWidget):
    """Professional branding header for sidebar."""

    toggle_requested = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFixedHeight(88)
        self.setObjectName("BrandingHeader")
        self._collapsed = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(Spacing.MD, Spacing.MD, Spacing.MD, Spacing.SM)
        layout.setSpacing(Spacing.XS)

        # Logo + Name row
        top_row = QHBoxLayout()
        top_row.setSpacing(Spacing.SM)

        # Logo icon
        self.logo = QLabel()
        self.logo.setFixedSize(32, 32)
        self.logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.logo.setText("")
        self.logo.setFont(QFont(Typography.FONT_FAMILY, 16))
        self.logo.hide()

        # Brand text
        self.brand = QLabel("IDFA")
        self.brand.setObjectName("BrandName")
        self.brand.setFont(QFont(Typography.FONT_FAMILY, Typography.HEADING_LG[0], Typography.HEADING_LG[1]))
        top_row.addWidget(self.brand)
        top_row.addStretch()
        self.toggle_button = QPushButton()
        self.toggle_button.setObjectName("SidebarToggle")
        self.toggle_button.setProperty("ghost", True)
        self.toggle_button.setFixedSize(28, 28)
        self.toggle_button.setIconSize(QSize(20, 20))
        self.toggle_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.toggle_button.setToolTip("Collapse navigation")
        self.toggle_button.setAccessibleName("Collapse navigation")
        self.toggle_button.clicked.connect(self.toggle_requested.emit)
        top_row.addWidget(self.toggle_button)
        layout.addLayout(top_row)

        # Subtitle
        self.subtitle = QLabel("Digital forensic workspace")
        self.subtitle.setWordWrap(True)
        self.subtitle.setFont(QFont(Typography.FONT_FAMILY, Typography.BODY_SM[0]))
        layout.addWidget(self.subtitle)

        self.restyle()

    def set_collapsed(self, collapsed: bool) -> None:
        """Compact the branding row while keeping its expand control visible."""
        self._collapsed = collapsed
        self.brand.setVisible(not collapsed)
        self.subtitle.setVisible(not collapsed)
        self.logo.setFixedSize(24 if collapsed else 32, 24 if collapsed else 32)
        self.toggle_button.setIcon(button_icon(
            "panel-open" if collapsed else "panel-close", Color.TEXT_SECONDARY.name()
        ))
        self.toggle_button.setToolTip(
            "Expand navigation" if collapsed else "Collapse navigation"
        )
        self.toggle_button.setAccessibleName(self.toggle_button.toolTip())
        self.toggle_button.setFixedSize(32, 32)
        layout = self.layout()
        if layout is not None:
            margin = 18 if collapsed else 20
            layout.setContentsMargins(margin, margin, margin, Spacing.SM)
            layout.setSpacing(Spacing.XS)
            top_row = layout.itemAt(0).layout()
            if top_row is not None:
                top_row.setSpacing(4 if collapsed else Spacing.SM)

    def restyle(self, theme: str | None = None) -> None:
        """Rebuild the brand colours for the active theme."""
        self.brand.setStyleSheet(f"color: {Color.TEXT_PRIMARY.name()};")
        self.subtitle.setStyleSheet(f"color: {Color.TEXT_MUTED.name()};")
        self.toggle_button.setIcon(button_icon(
            "panel-open" if self._collapsed else "panel-close", Color.TEXT_SECONDARY.name()
        ))


class NavList(QListView):
    """Navigation list for sidebar with professional styling."""

    ICON_ROLE = Qt.ItemDataRole.UserRole + 1

    def __init__(self, items: list[str], parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("NavList")
        # A standard-item model, not a string-list model: the row's icon is
        # stored in a custom role, and QStringListModel silently drops roles it
        # does not know.
        self.model = QStandardItemModel(self)
        self.setModel(self.model)
        self.setSpacing(0)
        self.setUniformItemSizes(True)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setSelectionMode(QListView.SelectionMode.SingleSelection)
        self.setIconSize(QSize(20, 20))

        # Add icon support for items
        self.setItemDelegate(NavItemDelegate(self))

        if items:
            self.set_entries([(label, NavItemDelegate.ICONS.get(label, "•")) for label in items])
        self.setCurrentIndex(self.model.index(0, 0))

    def set_entries(self, entries: list[tuple[str, str]]) -> None:
        """Replace the visible rows with ``(label, icon)`` pairs.

        Labels are translated, so the icon cannot be looked up from the label
        the way it used to be; it travels with the row as data instead.
        """
        current = self.currentIndex().row()
        self.model.clear()
        for label, icon in entries:
            item = QStandardItem(label)
            item.setEditable(False)
            item.setData(icon, self.ICON_ROLE)
            item.setToolTip(label)
            self.model.appendRow(item)
        if 0 <= current < len(entries):
            self.setCurrentIndex(self.model.index(current, 0))

    def set_collapsed(self, collapsed: bool) -> None:
        self._collapsed = collapsed
        self.setProperty("collapsed", collapsed)
        self.style().unpolish(self)
        self.style().polish(self)
        self.viewport().update()


class NavItemDelegate(QStyledItemDelegate):
    """Custom delegate for navigation items with icons."""

    ICONS = {
        "Case Management": "folder",
        "Global Audit": "audit",
        "Tools": "tools",
        "User Management": "users",
        "Settings": "settings",
        "Overview": "overview",
        "Evidence": "folder",
        "Examination": "examine",
        "Artifacts & Search": "search",
        "AI Analysis": "ai",
        "Entities & Timeline": "entities",
        "Findings": "audit",
        "Reports": "report",
        "Audit & Custody": "link",
    }

    def sizeHint(self, option, index) -> QSize:  # noqa: N802 - Qt override
        return QSize(220, 44)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        text = index.data(Qt.ItemDataRole.DisplayRole)

        # The row carries its icon explicitly so a translated label still gets
        # the right glyph; the table above is only a fallback for untranslated
        # rows built directly from English titles.
        icon_text = index.data(NavList.ICON_ROLE) or self.ICONS.get(text, "•")

        # Inset the selection so navigation reads as a quiet, rounded list.
        row_rect = option.rect.adjusted(8, 2, -8, -2)
        background = None
        if option.state & QStyle.StateFlag.State_Selected:
            background = Color.SIDEBAR_ITEM_ACTIVE_BG
            text_color = Color.TEXT_PRIMARY
        elif option.state & QStyle.StateFlag.State_MouseOver:
            background = Color.BG_TERTIARY
            text_color = Color.TEXT_PRIMARY
        else:
            text_color = Color.TEXT_SECONDARY
        if background is not None:
            path = QPainterPath()
            path.addRoundedRect(row_rect, 6, 6)
            painter.fillPath(path, background)
        if option.state & QStyle.StateFlag.State_Selected:
            painter.setPen(QPen(Color.SIDEBAR_ACCENT, 3))
            painter.drawLine(row_rect.left() + 1, row_rect.top() + 10,
                             row_rect.left() + 1, row_rect.bottom() - 10)
        if option.state & QStyle.StateFlag.State_HasFocus:
            painter.setPen(QPen(Color.BORDER_FOCUS, 1))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(row_rect, 6, 6)

        view = self.parent()
        collapsed = bool(getattr(view, "_collapsed", False))

        # Draw icon centered in compact mode, with labels retained only in the
        # full-width sidebar. Tooltips still expose the full page title.
        painter.setPen(text_color)
        icon_left = (
            option.rect.left() + (option.rect.width() - 24) // 2
            if collapsed else option.rect.left() + 16
        )
        icon_rect = QRect(
            icon_left,
            option.rect.top() + (option.rect.height() - 20) // 2,
            24 if collapsed else 20,
            20,
        )
        draw_icon(painter, icon_rect, icon_text, text_color.name())

        # Draw text
        if not collapsed:
            text_rect = QRect(
                option.rect.left() + 44,
                option.rect.top(),
                option.rect.width() - 50,
                option.rect.height(),
            )
            font = QFont(Typography.FONT_FAMILY)
            font.setPixelSize(13)
            font.setWeight(QFont.Weight.Medium)
            painter.setFont(font)
            painter.setPen(text_color)
            painter.drawText(
                text_rect,
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                painter.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight,
                                                text_rect.width()),
            )
        painter.restore()


class HeaderBar(QFrame):
    """Top header bar for global shell."""

    def __init__(self, title: str = "Case Management", parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("HeaderBar")
        self.setFixedHeight(56)
        self.setFrameShape(QFrame.Shape.NoFrame)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(Spacing.LG, 0, Spacing.LG, 0)
        layout.setSpacing(Spacing.SM)

        # Logo + Title
        logo_label = QLabel()
        logo_label.setFixedSize(28, 28)
        logo_label.setStyleSheet("""
            background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #3b82f6, stop:1 #60a5fa);
            border-radius: 6px;
        """)
        logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo_label.setText("🔍")
        logo_label.setFont(QFont(Typography.FONT_FAMILY, 14))
        layout.addWidget(logo_label)

        self.title_label = QLabel(title)
        self.title_label.setFont(QFont(Typography.FONT_FAMILY, Typography.HEADING_LG[0], Typography.HEADING_LG[1]))
        layout.addWidget(self.title_label)

        # Global search
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search cases, evidence, artifacts...")
        self.search_input.setProperty("search", True)
        self.search_input.setMinimumWidth(180)
        self.search_input.setMaximumWidth(420)
        self.search_input.setFixedHeight(36)
        layout.addWidget(self.search_input, 1)

        # Right side group: notification + user menu
        right_group = QWidget()
        right_layout = QHBoxLayout(right_group)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(Spacing.SM)
        right_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        # Notification button
        self.notif_btn = QPushButton()
        self.notif_btn.setObjectName("IconButton")
        self.notif_btn.setFixedSize(36, 36)
        self.notif_btn.setText("🔔")
        self.notif_btn.setProperty("ghost", True)
        right_layout.addWidget(self.notif_btn)

        # User menu
        self.user_btn = QPushButton()
        self.user_btn.setObjectName("UserButton")
        self.user_btn.setFixedHeight(36)
        self.user_btn.setText("  👤  Investigator  ▾")
        self.user_btn.setProperty("ghost", True)
        right_layout.addWidget(self.user_btn)

        layout.addWidget(right_group)

    def set_title(self, title: str):
        """Update the header title."""
        self.title_label.setText(title)


class ElidedLabel(QLabel):
    """Keep the full label available while fitting one line into its layout."""

    def __init__(self, text: str = "", parent: QWidget | None = None):
        super().__init__(text, parent)
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

    def paintEvent(self, event):  # noqa: N802 - Qt override
        painter = QPainter(self)
        painter.setPen(self.palette().color(self.foregroundRole()))
        painter.setFont(self.font())
        text = self.fontMetrics().elidedText(
            self.text(), Qt.TextElideMode.ElideRight, self.contentsRect().width()
        )
        painter.drawText(self.contentsRect(), self.alignment(), text)


class CaseHeaderBar(ThemedWidget, QFrame):
    """Compact case toolbar with aligned identity, metadata and actions."""

    back_requested = Signal()
    case_changed = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("CaseHeaderBar")
        self.setFixedHeight(80)
        self.setFrameShape(QFrame.Shape.NoFrame)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(24, 12, 24, 12)
        layout.setSpacing(16)

        self.back_btn = QPushButton("‹  All cases")
        self.back_btn.setObjectName("CaseBackButton")
        self.back_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.back_btn.setFixedSize(112, 36)
        self.back_btn.setToolTip("Return to Case Management")
        self.back_btn.setAccessibleName("Return to Case Management")
        self.back_btn.clicked.connect(self.back_requested.emit)
        layout.addWidget(self.back_btn)

        self.divider = QFrame()
        self.divider.setFrameShape(QFrame.Shape.VLine)
        self.divider.setFixedHeight(38)
        layout.addWidget(self.divider)

        info = QVBoxLayout()
        info.setContentsMargins(0, 0, 0, 0)
        info.setSpacing(4)

        self.case_id_label = ElidedLabel("No case loaded")
        self.case_id_label.setObjectName("CaseHeaderTitle")
        self.case_id_label.setFont(
            QFont(Typography.FONT_FAMILY, 11, QFont.Weight.DemiBold)
        )
        info.addWidget(self.case_id_label)

        self.case_meta_label = ElidedLabel("")
        self.case_meta_label.setObjectName("CaseHeaderMetadata")
        self.case_meta_label.setFont(
            QFont(Typography.FONT_FAMILY, 9)
        )
        info.addWidget(self.case_meta_label)

        info_widget = QWidget()
        info_widget.setObjectName("CaseHeaderInfo")
        info_widget.setStyleSheet("QWidget#CaseHeaderInfo { background: transparent; }")
        info_widget.setLayout(info)
        info_widget.setMinimumWidth(0)
        info_widget.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred,
        )
        layout.addWidget(info_widget, 1)

        # Keep the case header focused on case identity and navigation.
        # Evidence registration and examination actions belong on their
        # respective case pages, where their workflows and validation live.

        self.restyle()

    def restyle(self, theme: str | None = None) -> None:
        """Rebuild the header chrome for the active theme."""
        self.setStyleSheet(f"""
            QFrame#CaseHeaderBar {{
                background-color: {Color.BG_SECONDARY.name()};
                border: none;
                border-bottom: 1px solid {Color.BORDER_SUBTLE.name()};
            }}
        """)
        self.back_btn.setStyleSheet(f"""
            QPushButton#CaseBackButton {{
                color: {Color.TEXT_SECONDARY.name()};
                background: transparent;
                border: 1px solid transparent;
                border-radius: 6px;
                padding: 0 8px;
                text-align: left;
                font-size: 13px;
            }}
            QPushButton#CaseBackButton:hover {{
                color: {Color.TEXT_PRIMARY.name()};
                background: {Color.BG_TERTIARY.name()};
                border-color: {Color.BORDER_DEFAULT.name()};
            }}
        """)
        self.divider.setStyleSheet(f"color: {Color.BORDER_SUBTLE.name()};")
        self.case_id_label.setStyleSheet(
            f"color: {Color.TEXT_PRIMARY.name()}; background: transparent; border: none;"
            " font-size: 16px; font-weight: 600;"
        )
        self.case_meta_label.setStyleSheet(
            f"color: {Color.TEXT_SECONDARY.name()}; background: transparent; border: none;"
            " font-size: 12px;"
        )

    def set_case_context(
        self,
        case_id: str,
        title: str,
        status: str,
        priority: str,
        investigator: str,
    ):
        """Update the displayed case identity and compact metadata."""
        case_id = str(case_id or "").strip()
        title = str(title or "").strip()
        status = str(status or "Unknown").strip()
        priority = str(priority or "Normal").strip()
        investigator = str(investigator or "Unassigned").strip()

        identity = " — ".join(part for part in (case_id, title) if part)
        self.case_id_label.setText(identity or "No case loaded")
        self.case_id_label.setToolTip(identity)
        self.case_meta_label.setText(
            f"{status.replace('_', ' ').title()}   ·   "
            f"{priority.replace('_', ' ').title()} priority   ·   "
            f"Investigator: {investigator}"
        )
        self.case_meta_label.setToolTip(self.case_meta_label.text())


class OutlineIcon(QLabel):
    """A theme-aware vector icon with a fixed footprint."""

    def __init__(self, name: str, parent: QWidget | None = None):
        super().__init__(parent)
        self._icon_name = name
        self.setFixedSize(20, 20)

    def paintEvent(self, event):  # noqa: N802 - Qt override
        painter = QPainter(self)
        draw_icon(painter, self.rect(), self._icon_name, Color.TEXT_SECONDARY.name())


class StatCard(ThemedWidget, QFrame):
    """Professional dashboard statistic card."""

    clicked = Signal()

    def __init__(
        self,
        title: str,
        value: str,
        icon: str = "",
        color: QColor | None = None,
        trend: str = "",
        trend_up: bool = True,
        parent: QWidget | None = None
    ):
        super().__init__(parent)
        # Resolved here rather than in the signature so the colour follows the
        # active theme instead of whatever was active at import time.
        self._accent_color = color if color is not None else Color.PRIMARY
        self.setObjectName("StatCard")
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        # Keep dashboard rows usable on smaller windows while allowing the
        # cards to expand naturally on wider screens.
        self.setMinimumWidth(150)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(Spacing.MD, Spacing.MD, Spacing.MD, Spacing.MD)
        layout.setSpacing(Spacing.SM)

        # Top row: icon and value
        top_row = QHBoxLayout()
        top_row.setSpacing(Spacing.SM)

        # Icon
        if icon:
            self.icon_label = OutlineIcon(icon)
            top_row.addWidget(self.icon_label)

        # Value
        self.value_label = QLabel(value)
        self.value_label.setObjectName("StatValue")
        self.value_label.setFont(QFont(Typography.FONT_FAMILY, Typography.DISPLAY_LG[0], Typography.DISPLAY_LG[1]))
        self.value_label.setStyleSheet(f"color: {Color.TEXT_PRIMARY.name()};")
        top_row.addWidget(self.value_label)
        top_row.addStretch()

        layout.addLayout(top_row)

        # Title
        self.title_label = QLabel(title)
        self.title_label.setObjectName("StatTitle")
        self.title_label.setWordWrap(True)
        self.title_label.setFont(QFont(Typography.FONT_FAMILY, Typography.BODY_SM[0]))
        self.title_label.setStyleSheet(f"color: {Color.TEXT_SECONDARY.name()}; text-transform: uppercase; letter-spacing: 0.5px;")
        layout.addWidget(self.title_label)

        # Bottom accent line
        self.accent = QFrame()
        self.accent.setFixedHeight(3)
        layout.addWidget(self.accent)

        self.restyle()

    def restyle(self, theme: str | None = None) -> None:
        """Rebuild the card's own colours and its hover state."""
        self.value_label.setStyleSheet(f"color: {Color.TEXT_PRIMARY.name()};")
        self.title_label.setStyleSheet(f"color: {Color.TEXT_SECONDARY.name()};")
        self.accent.setStyleSheet(
            "background: qlineargradient(x1:0, y1:0, x2:1, y2:0,"
            f" stop:0 {self._accent_color.name()},"
            f" stop:1 {Color.TEXT_LINK.name()});"
            " border-radius: 1.5px;"
        )

    def set_value(self, value: str):
        self.value_label.setText(value)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    def enterEvent(self, event):
        self.setStyleSheet(f"""
            StatCard {{
                border: 1px solid {Color.BORDER_FOCUS.name()};
                background: {Color.BG_HOVER.name()};
            }}
        """)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.setStyleSheet("")
        super().leaveEvent(event)


class StatusBadge(QLabel):
    """Professional colored status badge."""

    def __init__(self, text: str, status: str = "", parent: QWidget | None = None):
        super().__init__(text, parent)
        self.setObjectName("StatusBadge")
        self.setProperty("status", status)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        self.setMinimumHeight(24)
        self.setContentsMargins(Spacing.MD, Spacing.XS, Spacing.MD, Spacing.XS)
        self.setFont(QFont(Typography.FONT_FAMILY, Typography.LABEL[0], Typography.LABEL[1]))


class OriginBadge(QLabel):
    """Origin badge for findings."""

    def __init__(self, origin: str, parent: QWidget | None = None):
        text = "Investigator" if origin == "investigator" else "AI Suggested"
        super().__init__(text, parent)
        self.setObjectName("OriginBadge")
        self.setProperty("origin", origin)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        self.setMinimumHeight(20)
        self.setContentsMargins(Spacing.SM, Spacing.XS, Spacing.SM, Spacing.XS)
        self.setFont(QFont(Typography.FONT_FAMILY, Typography.LABEL[0], Typography.LABEL[1]))


class StateStackedWidget(QStackedWidget):
    """Widget that shows different states: content, loading, empty, error, unavailable."""

    STATE_CONTENT = 0
    STATE_LOADING = 1
    STATE_EMPTY = 2
    STATE_ERROR = 3
    STATE_UNAVAILABLE = 4

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._states = {}
        self._build_states()

    def _build_states(self):
        pass

    def set_state(self, state: int, message: str = "", retry_callback=None):
        if state == self.STATE_CONTENT:
            self.setCurrentIndex(0)
        elif state == self.STATE_LOADING:
            self._show_loading(message)
        elif state == self.STATE_EMPTY:
            self._show_empty(message)
        elif state == self.STATE_ERROR:
            self._show_error(message, retry_callback)
        elif state == self.STATE_UNAVAILABLE:
            self._show_unavailable(message)

    def _show_loading(self, message: str):
        widget = self._get_or_create_state("loading", self._create_loading_widget(message))
        self.setCurrentWidget(widget)

    def _show_empty(self, message: str):
        widget = self._get_or_create_state("empty", self._create_empty_widget(message))
        self.setCurrentWidget(widget)

    def _show_error(self, message: str, retry_callback):
        widget = self._get_or_create_state("error", self._create_error_widget(message, retry_callback))
        self.setCurrentWidget(widget)

    def _show_unavailable(self, message: str):
        widget = self._get_or_create_state("unavailable", self._create_unavailable_widget(message))
        self.setCurrentWidget(widget)

    def _get_or_create_state(self, key: str, creator):
        if key not in self._states:
            widget = creator()
            self._states[key] = widget
            self.addWidget(widget)
        return self._states[key]

    def _create_loading_widget(self, message: str) -> QWidget:
        w = QWidget()
        w.setObjectName("StateWidget")
        layout = QVBoxLayout(w)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(Spacing.MD)

        spinner = QProgressBar()
        spinner.setRange(0, 0)
        spinner.setFixedSize(48, 48)
        spinner.setStyleSheet("QProgressBar { border: none; background: transparent; }")
        layout.addWidget(spinner, alignment=Qt.AlignmentFlag.AlignCenter)

        label = QLabel(message or "Loading...")
        label.setFont(QFont(Typography.FONT_FAMILY, Typography.BODY_MD[0]))
        label.setStyleSheet(f"color: {Color.TEXT_SECONDARY.name()};")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(label)
        return w

    def _create_empty_widget(self, message: str) -> QWidget:
        w = QWidget()
        w.setObjectName("StateWidget")
        layout = QVBoxLayout(w)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(Spacing.MD)

        icon = QLabel("📭")
        icon.setFont(QFont(Typography.FONT_FAMILY, 48))
        icon.setObjectName("EmptyStateIcon")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(icon)

        title = QLabel("No Data")
        title.setObjectName("EmptyStateTitle")
        layout.addWidget(title, alignment=Qt.AlignmentFlag.AlignCenter)

        msg = QLabel(message or "No items to display")
        msg.setObjectName("EmptyStateMessage")
        msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        msg.setWordWrap(True)
        layout.addWidget(msg)
        return w

    def _create_error_widget(self, message: str, retry_callback) -> QWidget:
        w = QWidget()
        w.setObjectName("StateWidget")
        layout = QVBoxLayout(w)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(Spacing.MD)

        icon = QLabel("⚠️")
        icon.setFont(QFont(Typography.FONT_FAMILY, 48))
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(icon)

        title = QLabel("Error")
        title.setObjectName("EmptyStateTitle")
        layout.addWidget(title, alignment=Qt.AlignmentFlag.AlignCenter)

        msg = QLabel(message or "An error occurred")
        msg.setObjectName("EmptyStateMessage")
        msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        msg.setWordWrap(True)
        layout.addWidget(msg)

        if retry_callback:
            btn = QPushButton("Retry")
            btn.clicked.connect(retry_callback)
            btn.setFixedWidth(120)
            layout.addWidget(btn, alignment=Qt.AlignmentFlag.AlignCenter)
        return w

    def _create_unavailable_widget(self, message: str) -> QWidget:
        w = QWidget()
        w.setObjectName("StateWidget")
        layout = QVBoxLayout(w)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(Spacing.MD)

        icon = QLabel("🔧")
        icon.setFont(QFont(Typography.FONT_FAMILY, 48))
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(icon)

        title = QLabel("Service Unavailable")
        title.setObjectName("EmptyStateTitle")
        layout.addWidget(title, alignment=Qt.AlignmentFlag.AlignCenter)

        msg = QLabel(message or "This feature requires a service that is not currently running")
        msg.setObjectName("EmptyStateMessage")
        msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        msg.setWordWrap(True)
        layout.addWidget(msg)
        return w


class ResponsivePage(QWidget):
    """Base class for all pages with responsive behavior."""

    def __init__(self, case_context: CaseContext | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.case_context = case_context
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._setup_layout()

    def _setup_layout(self):
        """Override in subclasses."""
        pass

    def refresh(self):
        """Refresh page data. Override in subclasses."""
        pass


class CaseContext:
    """Holds the current case context for case-scoped pages."""

    def __init__(
        self,
        case_id: int,
        case_id_str: str,
        title: str,
        status: str,
        priority: str,
        investigator: str
    ):
        self.case_id = case_id
        self.case_id_str = case_id_str
        self.title = title
        self.status = status
        self.priority = priority
        self.investigator = investigator

    def __repr__(self):
        return f"CaseContext(case_id={self.case_id}, title={self.title})"


class ProfessionalCard(ThemedWidget, QFrame):
    """Professional card widget with consistent styling."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("ProfessionalCard")
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.restyle()

    def restyle(self, theme: str | None = None) -> None:
        self.setStyleSheet(f"""
            ProfessionalCard {{
                background: {Color.BG_CARD.name()};
                border: 1px solid {Color.BORDER_SUBTLE.name()};
                border-radius: 8px;
            }}
            ProfessionalCard:hover {{
                border-color: {Color.BORDER_DEFAULT.name()};
            }}
        """)


class SectionHeader(QWidget):
    """Professional section header with title and optional action."""

    action_clicked = Signal(str)

    def __init__(self, title: str, action_text: str = "", action_id: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, Spacing.SM)
        layout.setSpacing(Spacing.MD)

        self.title = QLabel(title)
        self.title.setFont(QFont(Typography.FONT_FAMILY, Typography.HEADING_MD[0], Typography.HEADING_MD[1]))
        layout.addWidget(self.title)

        layout.addStretch()

        if action_text:
            self.action_btn = QPushButton(action_text)
            self.action_btn.setProperty("secondary", True)
            self.action_btn.clicked.connect(lambda: self.action_clicked.emit(action_id))
            layout.addWidget(self.action_btn)
