
"""AppHeaderBar — professional investigator application header."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QToolButton,
    QWidget,
)

from app.ui.icons import button_icon
from app.ui.theme.themed import ThemedWidget
from app.ui.theme.tokens import Color, Typography


class AppHeaderBar(ThemedWidget, QWidget):
    """Application header with global search, notifications and user menu."""

    search_submitted = Signal(str)
    settings_requested = Signal()
    about_requested = Signal()
    logout_requested = Signal()

    def __init__(
        self,
        title: str = "Case Management",
        parent: QWidget | None = None,
    ):
        super().__init__(parent)

        self.setObjectName("AppHeaderBar")
        self.setFixedHeight(60)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        self._notifications: list[dict] = []
        self._bell_menu: QMenu | None = None
        self._user_menu: QMenu | None = None
        self._current_user = None

        self._setup_ui(title)

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _setup_ui(self, title: str) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 0, 16, 0)
        layout.setSpacing(12)

        # Page title
        self._title_lbl = QLabel(title)
        self._title_lbl.setProperty("headerTitle", True)
        self._title_lbl.setFont(
            QFont(
                Typography.FONT_FAMILY,
                Typography.HEADING_MD[0],
                Typography.HEADING_LG[1],
            )
        )

        self._title_lbl.setMinimumWidth(150)
        layout.addWidget(self._title_lbl)

        # Global search
        self._search_edit = QLineEdit()
        self._search_edit.setObjectName("GlobalSearch")
        self._search_edit.setPlaceholderText(
            "Search cases, evidence, artifacts..."
        )
        self._search_edit.setMinimumWidth(160)
        self._search_edit.setMaximumWidth(340)
        self._search_edit.setFixedHeight(38)
        self._search_edit.setClearButtonEnabled(True)
        self._search_edit.setToolTip(
            "Search across cases, evidence and artifacts"
        )
        self._search_edit.returnPressed.connect(self._on_search_return)

        layout.addWidget(self._search_edit, 1)

        # Vertical separator
        self._separator = QFrame()
        self._separator.setFrameShape(QFrame.Shape.VLine)
        self._separator.setFixedHeight(25)

        layout.addWidget(self._separator)

        # Notification button
        self._bell_btn = QToolButton()
        self._bell_btn.setObjectName("NotificationButton")
        self._bell_btn.setFixedSize(38, 38)
        self._bell_btn.setToolTip("Notifications")
        self._bell_btn.setAccessibleName("Notifications")
        self._bell_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._bell_btn.setPopupMode(
            QToolButton.ToolButtonPopupMode.InstantPopup
        )


        self._bell_menu = QMenu(self)
        self._bell_menu.aboutToShow.connect(self._mark_notifications_read)
        self._bell_btn.setMenu(self._bell_menu)

        self._notification_badge = QLabel(self._bell_btn)
        self._notification_badge.setObjectName("NotificationBadge")
        self._notification_badge.setAlignment(
            Qt.AlignmentFlag.AlignCenter
        )
        self._notification_badge.setFixedSize(16, 16)
        self._notification_badge.move(22, 1)
        self._notification_badge.setStyleSheet(self._badge_qss())
        self._notification_badge.hide()

        self._rebuild_bell_menu()
        layout.addWidget(self._bell_btn)

        # User identity control
        self._user_btn = QToolButton()
        self._user_btn.setObjectName("UserButton")
        self._user_btn.setFixedHeight(40)
        self._user_btn.setMinimumWidth(170)
        self._user_btn.setMaximumWidth(230)
        self._user_btn.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextBesideIcon
        )
        self._user_btn.setPopupMode(
            QToolButton.ToolButtonPopupMode.InstantPopup
        )
        self._user_btn.setCursor(Qt.CursorShape.PointingHandCursor)


        self._user_menu = QMenu(self)
        self._user_btn.setMenu(self._user_menu)

        self._user_avatar = QLabel("A", self._user_btn)
        self._user_avatar.setObjectName("UserAvatar")
        self._user_avatar.setFixedSize(27, 27)
        self._user_avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._user_avatar.raise_()

        self._user_btn.installEventFilter(self)
        self._position_avatar()

        self._search_shortcut = QShortcut(QKeySequence("Ctrl+K"), self)
        self._search_shortcut.setContext(
            Qt.ShortcutContext.ApplicationShortcut
        )
        self._search_shortcut.activated.connect(self._focus_search)

        self.set_user(None)
        layout.addWidget(self._user_btn)

        self.restyle()

    # ------------------------------------------------------------------
    # Styles
    # ------------------------------------------------------------------

    def restyle(self, theme: str | None = None) -> None:
        """Rebuild every piece of chrome this bar styles itself."""
        self.setStyleSheet(f"""
            QWidget#AppHeaderBar {{
                background-color: {Color.BG_PRIMARY.name()};
                border: none;
            }}
        """)
        self._title_lbl.setStyleSheet(f"""
            color: {Color.TEXT_PRIMARY.name()};
            background: transparent;
            border: none;
        """)
        self._search_edit.setStyleSheet(f"""
            QLineEdit#GlobalSearch {{
                color: {Color.TEXT_PRIMARY.name()};
                background-color: {Color.BG_SECONDARY.name()};
                border: 1px solid {Color.BORDER_DEFAULT.name()};
                border-radius: 5px;
                padding: 0 12px;
                font-family: "{Typography.FONT_FAMILY}";
                font-size: 13px;
            }}
            QLineEdit#GlobalSearch:hover {{
                border-color: {Color.TEXT_SECONDARY.name()};
            }}
            QLineEdit#GlobalSearch:focus {{
                border: 1px solid {Color.BORDER_FOCUS.name()};
            }}
        """)
        self._separator.setStyleSheet(f"color: {Color.BORDER_DEFAULT.name()};")
        self._bell_btn.setStyleSheet(self._icon_button_style())
        self._bell_btn.setIcon(button_icon("bell", Color.TEXT_SECONDARY.name()))
        self._bell_menu.setStyleSheet(self._menu_qss())
        self._notification_badge.setStyleSheet(self._badge_qss())
        self._user_btn.setStyleSheet(self._user_btn_qss())
        self._user_menu.setStyleSheet(self._menu_qss())
        self._user_avatar.setStyleSheet(self._avatar_qss())

    def _badge_qss(self) -> str:
        return f"""
            QLabel#NotificationBadge {{
                color: #FFFFFF;
                background-color: {Color.ERROR.name()};
                border: 1px solid {Color.BG_PRIMARY.name()};
                border-radius: 8px;
                font-size: 9px;
                font-weight: 700;
            }}
        """

    def _avatar_qss(self) -> str:
        return f"""
            QLabel#UserAvatar {{
                color: {Color.TEXT_PRIMARY.name()};
                background-color: {Color.BG_TERTIARY.name()};
                border: 1px solid {Color.BORDER_DEFAULT.name()};
                border-radius: 13px;
                font-size: 13px;
                font-weight: 700;
            }}
        """

    # ------------------------------------------------------------------
    # Styles
    # ------------------------------------------------------------------

    def _icon_button_style(self) -> str:
        return f"""
            QToolButton#NotificationButton {{
                color: {Color.TEXT_PRIMARY.name()};
                background-color: transparent;
                border: 1px solid transparent;
                border-radius: 5px;
                font-family: "Segoe UI";
                font-size: 13px;
                font-weight: 700;
            }}
            QToolButton#NotificationButton:hover {{
                background-color: {Color.BG_HOVER.name()};
                border-color: {Color.BORDER_DEFAULT.name()};
            }}
            QToolButton#NotificationButton:pressed {{
                background-color: {Color.BG_SECONDARY.name()};
            }}
            QToolButton#NotificationButton::menu-indicator {{
                image: none;
                width: 0;
            }}
        """

    def _user_btn_qss(self) -> str:
        return f"""
            QToolButton#UserButton {{
                color: {Color.TEXT_PRIMARY.name()};
                background-color: transparent;
                border: 1px solid transparent;
                border-radius: 5px;
                padding: 0 10px 0 38px;
                text-align: left;
                font-family: "{Typography.FONT_FAMILY}";
                font-size: 13px;
                font-weight: 500;
            }}
            QToolButton#UserButton:hover {{
                background-color: {Color.BG_HOVER.name()};
                border-color: {Color.BORDER_DEFAULT.name()};
            }}
            QToolButton#UserButton:pressed,
            QToolButton#UserButton::menu-button:pressed {{
                background-color: {Color.BG_SECONDARY.name()};
            }}
            QToolButton#UserButton::menu-indicator {{
                image: none;
                width: 0;
            }}
        """

    def _menu_qss(self) -> str:
        return f"""
            QMenu {{
                background-color: {Color.BG_SECONDARY.name()};
                border: 1px solid {Color.BORDER_DEFAULT.name()};
                border-radius: 6px;
                padding: 5px;
            }}
            QMenu::item {{
                color: {Color.TEXT_PRIMARY.name()};
                padding: 8px 24px 8px 12px;
                border-radius: 3px;
                font-size: 11px;
            }}
            QMenu::item:selected {{
                background-color: {Color.BG_HOVER.name()};
            }}
            QMenu::item:disabled {{
                color: {Color.TEXT_SECONDARY.name()};
            }}
            QMenu::separator {{
                height: 1px;
                background-color: {Color.BORDER_SUBTLE.name()};
                margin: 4px 6px;
            }}
        """

    # ------------------------------------------------------------------
    # Public API — retain compatibility with the existing application
    # ------------------------------------------------------------------

    def set_title(self, title: str) -> None:
        self._title_lbl.setText(title)

    def set_user(self, user) -> None:
        """Update the user control and its associated menu."""
        self._current_user = user

        if user is None:
            self._user_btn.setText("Sign in")
            self._user_btn.setEnabled(True)
            self._user_avatar.setText("?")
            self._build_user_menu(None)
            self._position_avatar()
            return

        name = (
            getattr(user, "full_name", None)
            or getattr(user, "username", None)
            or "Investigator"
        )
        role = getattr(user, "role", None)
        role_str = role.value if hasattr(role, "value") else str(role or "")

        # Keep the header compact. Full identity remains in the menu.
        display_name = str(name)
        if len(display_name) > 18:
            display_name = display_name[:17] + "…"

        self._user_btn.setText(
            f"{display_name}  ·  {role_str}     ▾"
            if role_str
            else f"{display_name}     ▾"
        )
        self._user_btn.setEnabled(True)

        self._user_avatar.setText(
            str(name).strip()[:1].upper() or "I"
        )
        self._build_user_menu(user)
        self._position_avatar()

    def add_notification(
        self,
        title: str,
        message: str = "",
        level: str = "info",
        on_click: Callable[[], None] | None = None,
    ) -> None:
        """Add a notification and update the unread-count badge."""
        self._notifications.insert(
            0,
            {
                "title": str(title),
                "message": str(message),
                "level": str(level),
                "on_click": on_click,
            },
        )
        self._rebuild_bell_menu()

    def clear_notifications(self) -> None:
        self._notifications.clear()
        self._rebuild_bell_menu()

    def _mark_notifications_read(self) -> None:
        """Clear the unread indicator without removing notification history."""
        if self._notifications:
            self._notification_badge.hide()
            self._bell_btn.setToolTip("Notifications")

    def _focus_search(self) -> None:
        self._search_edit.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self._search_edit.selectAll()

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def _on_search_return(self) -> None:
        text = self._search_edit.text().strip()
        if text:
            self.search_submitted.emit(text)

    # ------------------------------------------------------------------
    # Notification menu
    # ------------------------------------------------------------------

    def _rebuild_bell_menu(self) -> None:
        if self._bell_menu is None:
            return

        self._bell_menu.clear()
        count = len(self._notifications)

        self._notification_badge.setText(
            str(count) if count < 100 else "99+"
        )
        self._notification_badge.setVisible(count > 0)
        self._bell_btn.setToolTip(
            f"{count} notification(s)" if count else "No notifications"
        )

        if not self._notifications:
            action = QAction("You're all caught up", self)
            action.setEnabled(False)
            self._bell_menu.addAction(action)
            return

        for notification in self._notifications:
            title = notification["title"]
            message = notification["message"]
            level = notification["level"].upper()

            text = f"{level}  ·  {title}"
            if message:
                text += f"\n{message}"

            action = QAction(text, self)
            callback = notification.get("on_click")
            action.setEnabled(callback is not None)
            if callback is not None:
                action.setToolTip("Open related item")
                action.triggered.connect(lambda checked=False, fn=callback: fn())
            self._bell_menu.addAction(action)

        self._bell_menu.addSeparator()

        clear_action = self._bell_menu.addAction("Clear all")
        clear_action.triggered.connect(self.clear_notifications)

    # ------------------------------------------------------------------
    # User menu
    # ------------------------------------------------------------------

    def _build_user_menu(self, user=None) -> None:
        if self._user_menu is None:
            return

        self._user_menu.clear()

        if user is None:
            action = self._user_menu.addAction("Not signed in")
            action.setEnabled(False)
            self._user_menu.addSeparator()

            sign_in_action = self._user_menu.addAction("Sign in…")
            sign_in_action.triggered.connect(
                self.logout_requested.emit
            )
            return

        name = (
            getattr(user, "full_name", None)
            or getattr(user, "username", None)
            or "Investigator"
        )
        username = getattr(user, "username", "") or ""
        role = getattr(user, "role", None)
        role_str = role.value if hasattr(role, "value") else str(role or "")

        identity = username or str(name)
        signed_in_as = f"Signed in as {identity}"
        if role_str:
            signed_in_as += f" ({role_str})"
        info = self._user_menu.addAction(signed_in_as)
        info.setEnabled(False)

        self._user_menu.addSeparator()

        settings_action = self._user_menu.addAction("Settings")
        settings_action.triggered.connect(self.settings_requested.emit)

        about_action = self._user_menu.addAction("About IDFA")
        about_action.triggered.connect(self.about_requested.emit)

        self._user_menu.addSeparator()

        logout_action = self._user_menu.addAction("Log out")
        logout_action.triggered.connect(self.logout_requested.emit)

    # ------------------------------------------------------------------
    # Layout helpers
    # ------------------------------------------------------------------

    def _position_avatar(self) -> None:
        """Place the avatar consistently inside the user button."""
        if not hasattr(self, "_user_avatar"):
            return

        self._user_avatar.move(8, (self._user_btn.height() - 27) // 2)
        self._user_avatar.raise_()

    def eventFilter(self, obj, event):
        if obj is getattr(self, "_user_btn", None):
            if event.type() in (
                event.Type.Resize,
                event.Type.Show,
            ):
                self._position_avatar()

        return super().eventFilter(obj, event)
