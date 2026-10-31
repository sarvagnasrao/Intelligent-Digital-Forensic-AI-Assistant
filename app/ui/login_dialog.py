
"""IDFA — Investigator Authentication Dialog."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QEvent, QPoint, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.i18n import retranslate_widgets, tr
from app.ui.theme.tokens import Color


class LoginDialog(QDialog):
    """Professional authentication dialog for IDFA investigators."""

    login_success = Signal(object)

    # Palette-derived so the dialog follows the theme chosen in Settings. It is
    # rebuilt for every sign-in, so there is no live restyle to worry about.
    COLORS = {
        "BG": "BG_PRIMARY",
        "TITLE_BG": "BG_SECONDARY",
        "INPUT_BG": "BG_INPUT",
        "BORDER": "BORDER_DEFAULT",
        "BORDER_HOVER": "TEXT_SECONDARY",
        "TEXT": "TEXT_PRIMARY",
        "SECONDARY": "TEXT_SECONDARY",
        "MUTED": "TEXT_MUTED",
        "ACCENT": "TEXT_LINK",
        "ACCENT_HOVER": "TEXT_LINK_HOVER",
        "ERROR": "ERROR",
        "MONOGRAM_BG": "BG_TERTIARY",
        "CLOSE_HOVER": "ERROR",
        "CLOSE_HOVER_FG": "TEXT_INVERSE",
        "SIGNIN_FG": "TEXT_INVERSE",
        "SIGNIN_BG": "PRIMARY_LIGHT",
        "SIGNIN_HOVER": "PRIMARY_HOVER",
        "PASSWORD_TOGGLE_PRESSED": "TEXT_LINK_HOVER",
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self._load_colors()

        self.login_callback: Callable[[str, str], Any] | None = None
        self._drag_offset: QPoint | None = None
        self.title_bar = None
        self.password_edit = None
        self.show_password_btn = None

        self.setWindowTitle("IDFA — Investigator Authentication")
        self.setModal(True)
        self.setMinimumWidth(410)
        self.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.FramelessWindowHint
        )
        self.setAttribute(
            Qt.WidgetAttribute.WA_TranslucentBackground, True
        )

        self._build_ui()
        # Start keyboard navigation at the first credential field, not the
        # custom title bar's minimize button.
        self.username_edit.setFocus(Qt.FocusReason.OtherFocusReason)

        # The dialog is built in English; this renders it in the configured
        # language, and in a language picked since the last sign-in.
        retranslate_widgets(self)

        # Size to the laid-out content so the footer never collides with the
        # sign-in button when the system font is larger than assumed.
        self.adjustSize()

    def _load_colors(self) -> None:
        """Resolve every colour this dialog uses from the active palette."""
        for attribute, token in self.COLORS.items():
            setattr(self, attribute, getattr(Color, token).name())

    # ------------------------------------------------------------------
    # Main layout
    # ------------------------------------------------------------------

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(0)

        self.container = QFrame()
        self.container.setObjectName("LoginContainer")
        self.container.setStyleSheet(f"""
            QFrame#LoginContainer {{
                background-color: {self.BG};
                border: 1px solid {self.BORDER};
                border-radius: 9px;
            }}
        """)

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(24)
        shadow.setOffset(0, 4)
        shadow.setColor(QColor(0, 0, 0, 100))
        self.container.setGraphicsEffect(shadow)
        outer.addWidget(self.container)

        container_layout = QVBoxLayout(self.container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(0)

        self._build_title_bar(container_layout)
        self._build_content(container_layout)

    # ------------------------------------------------------------------
    # Custom title bar
    # ------------------------------------------------------------------

    def _build_title_bar(self, parent_layout):
        self.title_bar = QFrame()
        self.title_bar.setObjectName("TitleBar")
        self.title_bar.setMinimumHeight(42)
        self.title_bar.setStyleSheet(f"""
            QFrame#TitleBar {{
                background-color: {self.TITLE_BG};
                border: none;
                border-bottom: 1px solid {self.BORDER};
                border-top-left-radius: 8px;
                border-top-right-radius: 8px;
            }}
        """)

        bar = QHBoxLayout(self.title_bar)
        bar.setContentsMargins(14, 0, 5, 0)
        bar.setSpacing(9)

        monogram = QLabel("ID")
        monogram.setFixedSize(23, 23)
        monogram.setAlignment(Qt.AlignmentFlag.AlignCenter)
        monogram.setStyleSheet(f"""
            QLabel {{
                color: {self.ACCENT};
                background-color: {self.MONOGRAM_BG};
                border: 1px solid {self.BORDER_HOVER};
                border-radius: 4px;
                font-size: 10px;
                font-weight: 700;
            }}
        """)
        bar.addWidget(monogram)

        name = QLabel("IDFA")
        name.setStyleSheet(f"""
            color: {self.TEXT};
            font-size: 12px;
            font-weight: 600;
            background: transparent;
        """)
        bar.addWidget(name)

        separator = QFrame()
        separator.setFixedSize(1, 15)
        separator.setStyleSheet(
            f"background-color: {self.BORDER_HOVER}; border: none;"
        )
        bar.addWidget(separator)

        subtitle = QLabel("Investigator Access")
        subtitle.setStyleSheet(f"""
            color: {self.MUTED};
            font-size: 10px;
            background: transparent;
        """)
        bar.addWidget(subtitle)
        bar.addStretch()

        self.minimize_btn = self._title_button("—", "Minimize")
        self.minimize_btn.clicked.connect(self.showMinimized)
        bar.addWidget(self.minimize_btn)

        self.close_btn = self._title_button("×", "Close", close=True)
        self.close_btn.clicked.connect(self.reject)
        bar.addWidget(self.close_btn)

        # Only the title bar and non-button children handle dragging.
        self.title_bar.installEventFilter(self)
        for widget in self.title_bar.findChildren(QWidget):
            if widget not in (self.minimize_btn, self.close_btn):
                widget.installEventFilter(self)

        parent_layout.addWidget(self.title_bar)

    def _title_button(self, text, tooltip, close=False):
        button = QToolButton()
        button.setText(text)
        button.setToolTip(tooltip)
        button.setAccessibleName(tooltip)
        button.setMinimumSize(36, 32)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        hover = self.CLOSE_HOVER if close else self.MONOGRAM_BG
        hover_text = self.CLOSE_HOVER_FG if close else self.TEXT

        button.setStyleSheet(f"""
            QToolButton {{
                color: {self.SECONDARY};
                background: transparent;
                border: none;
                border-radius: 4px;
                font-family: "Segoe UI";
                font-size: 15px;
                padding: 0;
            }}
            QToolButton:hover {{
                color: {hover_text};
                background-color: {hover};
            }}
            QToolButton:pressed {{
                background-color: {self.BORDER};
            }}
            QToolButton:focus {{
                border: 1px solid {self.ACCENT};
            }}
        """)
        return button

    # ------------------------------------------------------------------
    # Login form
    # ------------------------------------------------------------------

    def _build_content(self, parent_layout):
        content = QFrame()
        content.setObjectName("LoginContent")
        content.setStyleSheet(
            "QFrame#LoginContent { background: transparent; border: none; }"
        )

        root = QVBoxLayout(content)
        root.setContentsMargins(30, 25, 30, 20)
        root.setSpacing(0)

        eyebrow = QLabel("DIGITAL FORENSICS")
        eyebrow.setStyleSheet(f"""
            color: {self.ACCENT};
            font-size: 9px;
            font-weight: 700;
            letter-spacing: 2px;
            background: transparent;
        """)
        root.addWidget(eyebrow)
        root.addSpacing(8)

        brand = QLabel("IDFA")
        brand.setStyleSheet(f"""
            color: {self.TEXT};
            font-size: 29px;
            font-weight: 600;
            background: transparent;
        """)
        root.addWidget(brand)
        root.addSpacing(5)

        subtitle = QLabel("Intelligent Digital Forensic Analysis")
        subtitle.setStyleSheet(f"""
            color: {self.SECONDARY};
            font-size: 12px;
            background: transparent;
        """)
        root.addWidget(subtitle)
        root.addSpacing(20)

        divider = QFrame()
        divider.setFixedHeight(1)
        divider.setStyleSheet(
            f"background-color: {self.BORDER}; border: none;"
        )
        root.addWidget(divider)
        root.addSpacing(21)

        heading = QLabel("Investigator sign in")
        heading.setStyleSheet(f"""
            color: {self.TEXT};
            font-size: 18px;
            font-weight: 600;
            background: transparent;
        """)
        root.addWidget(heading)
        root.addSpacing(5)

        description = QLabel(
            "Authenticate to access your investigation workspace."
        )
        description.setWordWrap(True)
        description.setStyleSheet(f"""
            color: {self.SECONDARY};
            background: transparent;
        """)
        root.addWidget(description)
        root.addSpacing(19)

        username_label = self._field_label("Username")
        root.addWidget(username_label)
        root.addSpacing(7)

        self.username_edit = QLineEdit()
        username_label.setBuddy(self.username_edit)
        self.username_edit.setAccessibleName(tr("Username"))
        self.username_edit.setObjectName("UsernameInput")
        self.username_edit.setPlaceholderText("Enter your username")
        self.username_edit.setClearButtonEnabled(True)
        self.username_edit.setMinimumHeight(41)
        self.username_edit.setStyleSheet(self._input_style())
        self.username_edit.returnPressed.connect(self._focus_password)
        root.addWidget(self.username_edit)
        root.addSpacing(15)

        password_label = self._field_label("Password")
        root.addWidget(password_label)
        root.addSpacing(7)

        self.password_edit = QLineEdit()
        password_label.setBuddy(self.password_edit)
        self.password_edit.setAccessibleName(tr("Password"))
        self.password_edit.setObjectName("PasswordInput")
        self.password_edit.setPlaceholderText("Enter your password")
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_edit.setMinimumHeight(41)
        self.password_edit.setTextMargins(0, 0, 50, 0)
        self.password_edit.setStyleSheet(self._input_style())
        self.password_edit.returnPressed.connect(self._on_login)
        root.addWidget(self.password_edit)

        self.show_password_btn = QToolButton(self.password_edit)
        self.show_password_btn.setText("Show")
        self.show_password_btn.setAccessibleName(tr("Show password"))
        self.show_password_btn.setCursor(
            Qt.CursorShape.PointingHandCursor
        )
        self.show_password_btn.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.show_password_btn.setStyleSheet(f"""
            QToolButton {{
                color: {self.ACCENT};
                background: transparent;
                border: none;
                font-weight: 600;
            }}
            QToolButton:hover {{
                color: {self.ACCENT_HOVER};
            }}
            QToolButton:focus {{
                border: 1px solid {self.ACCENT};
            }}
        """)
        self.show_password_btn.clicked.connect(self._toggle_password)
        self.password_edit.installEventFilter(self)
        self._position_password_toggle()

        root.addSpacing(13)

        self.error_label = QLabel()
        self.error_label.setObjectName("LoginError")
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet(f"""
            QLabel#LoginError {{
                color: {self.ERROR};
                background: transparent;
                border: none;
            }}
        """)
        self.error_label.hide()
        root.addWidget(self.error_label)

        options = QHBoxLayout()
        options.setContentsMargins(0, 0, 0, 0)
        options.setSpacing(5)

        self.remember_check = QCheckBox("Remember me")
        self.remember_check.setCursor(
            Qt.CursorShape.PointingHandCursor
        )
        self.remember_check.setStyleSheet(f"""
            QCheckBox {{
                color: {self.SECONDARY};
                spacing: 7px;
                font-size: 10px;
                background: transparent;
            }}
            QCheckBox::indicator {{
                width: 14px;
                height: 14px;
                background: {self.INPUT_BG};
                border: 1px solid {self.BORDER_HOVER};
                border-radius: 3px;
            }}
            QCheckBox::indicator:checked {{
                background: {self.ACCENT};
                border-color: {self.ACCENT};
            }}
        """)
        options.addWidget(self.remember_check)
        options.addStretch()

        root.addLayout(options)
        root.addSpacing(18)

        self.login_btn = QPushButton("Sign in")
        self.login_btn.setObjectName("SignInButton")
        self.login_btn.setMinimumHeight(42)
        self.login_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.login_btn.setDefault(True)
        self.login_btn.setStyleSheet(f"""
            QPushButton#SignInButton {{
                color: {self.SIGNIN_FG};
                background-color: {self.SIGNIN_BG};
                border: 1px solid {self.SIGNIN_BG};
                border-radius: 4px;
                font-size: 12px;
                font-weight: 700;
            }}
            QPushButton#SignInButton:hover {{
                background-color: {self.SIGNIN_HOVER};
                border-color: {self.SIGNIN_HOVER};
            }}
            QPushButton#SignInButton:pressed {{
                background-color: {self.ACCENT_HOVER};
            }}
            QPushButton#SignInButton:disabled {{
                color: {self.MUTED};
                background-color: {self.TITLE_BG};
                border-color: {self.BORDER};
            }}
        """)
        self.login_btn.clicked.connect(self._on_login)
        root.addWidget(self.login_btn)
        root.addStretch(1)

        footer_divider = QFrame()
        footer_divider.setFixedHeight(1)
        footer_divider.setStyleSheet(
            f"background-color: {self.BORDER}; border: none;"
        )
        root.addWidget(footer_divider)
        root.addSpacing(10)

        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)

        version = QLabel("IDFA  /  v0.1.0")
        version.setStyleSheet(
            f"color: {self.MUTED}; font-size: 9px;"
        )
        footer.addWidget(version)
        footer.addStretch()

        institution = QLabel("KSIT Bengaluru")
        institution.setStyleSheet(
            f"color: {self.MUTED}; font-size: 9px;"
        )
        footer.addWidget(institution)

        root.addLayout(footer)
        parent_layout.addWidget(content, 1)

    def _field_label(self, text):
        label = QLabel(text)
        label.setStyleSheet(f"""
            color: {self.SECONDARY};
            font-weight: 600;
            background: transparent;
        """)
        return label

    def _input_style(self):
        return f"""
            QLineEdit {{
                color: {self.TEXT};
                background-color: {self.INPUT_BG};
                border: 1px solid {self.BORDER};
                border-radius: 4px;
                padding: 0 11px;
                min-height: 39px;
                selection-background-color: {self.ACCENT};
            }}
            QLineEdit:hover {{
                border-color: {self.BORDER_HOVER};
            }}
            QLineEdit:focus {{
                border: 1px solid {self.ACCENT};
            }}
        """

    # ------------------------------------------------------------------
    # Event handling — safe during partial initialization
    # ------------------------------------------------------------------

    def eventFilter(self, obj, event):
        password_edit = getattr(self, "password_edit", None)
        toggle = getattr(self, "show_password_btn", None)

        if (
            password_edit is not None
            and toggle is not None
            and obj is password_edit
            and event.type() in (
                QEvent.Type.Resize,
                QEvent.Type.Show,
            )
        ):
            self._position_password_toggle()

        title_bar = getattr(self, "title_bar", None)
        minimize_btn = getattr(self, "minimize_btn", None)
        close_btn = getattr(self, "close_btn", None)

        is_title_bar = obj is title_bar
        if not is_title_bar and title_bar is not None:
            current = (
                obj.parentWidget()
                if isinstance(obj, QWidget)
                else None
            )
            while current is not None:
                if current is title_bar:
                    is_title_bar = True
                    break
                current = current.parentWidget()

        # Do not intercept clicks on title-bar buttons.
        if obj is minimize_btn or obj is close_btn:
            is_title_bar = False

        if is_title_bar:
            if event.type() == QEvent.Type.MouseButtonPress:
                if event.button() == Qt.MouseButton.LeftButton:
                    self._drag_offset = (
                        event.globalPosition().toPoint()
                        - self.frameGeometry().topLeft()
                    )
                    return True

            elif event.type() == QEvent.Type.MouseMove:
                if (
                    self._drag_offset is not None
                    and event.buttons() & Qt.MouseButton.LeftButton
                ):
                    self.move(
                        event.globalPosition().toPoint()
                        - self._drag_offset
                    )
                    return True

            elif event.type() == QEvent.Type.MouseButtonRelease:
                self._drag_offset = None
                return True

        return super().eventFilter(obj, event)

    def _position_password_toggle(self):
        password_edit = getattr(self, "password_edit", None)
        toggle = getattr(self, "show_password_btn", None)

        if password_edit is None or toggle is None:
            return

        width = max(46, toggle.sizeHint().width() + 8)
        height = min(password_edit.height(), max(29, toggle.sizeHint().height()))
        password_edit.setTextMargins(0, 0, width + 4, 0)
        toggle.resize(width, height)
        toggle.move(
            password_edit.width() - width - 7,
            (password_edit.height() - height) // 2,
        )
        toggle.raise_()

    def _focus_password(self):
        password_edit = getattr(self, "password_edit", None)
        if password_edit is not None:
            password_edit.setFocus()

    def _toggle_password(self):
        visible = (
            self.password_edit.echoMode()
            == QLineEdit.EchoMode.Password
        )

        self.password_edit.setEchoMode(
            QLineEdit.EchoMode.Normal
            if visible
            else QLineEdit.EchoMode.Password
        )
        self.show_password_btn.setText(tr("Hide") if visible else tr("Show"))
        self.show_password_btn.setAccessibleName(
            tr("Hide password") if visible else tr("Show password")
        )
        self._position_password_toggle()

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    def set_login_callback(self, callback):
        """Register authentication callback returning (success, user)."""
        self.login_callback = callback

    def _show_error(self, message):
        self.error_label.setText(message)
        self.error_label.show()

    def _on_login(self):
        username = self.username_edit.text().strip()
        password = self.password_edit.text()

        if not username or not password:
            self._show_error(
                "Enter both your username and password."
            )
            (
                self.username_edit
                if not username
                else self.password_edit
            ).setFocus()
            return

        if self.login_callback is None:
            self._show_error(
                "Authentication service is unavailable."
            )
            return

        self.login_btn.setEnabled(False)
        self.login_btn.setText("Authenticating...")

        try:
            result = self.login_callback(username, password)

            if not isinstance(result, tuple) or len(result) != 2:
                self._show_error(
                    "Unexpected authentication response."
                )
                return

            success, user = result

            if success:
                self.error_label.hide()
                self.login_success.emit(user)
                self.accept()
            else:
                self.password_edit.clear()
                self._show_error("Invalid username or password.")
                self.password_edit.setFocus()

        except Exception:
            self._show_error(
                "Unable to sign in. Check the application logs."
            )

        finally:
            self.login_btn.setEnabled(True)
            self.login_btn.setText("Sign in")
