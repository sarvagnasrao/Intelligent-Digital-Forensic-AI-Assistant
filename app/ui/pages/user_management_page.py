"""User Management page - account administration for administrators only.

The page exists in the global shell for every signed-in user (so the widget
stack never has to be rebuilt), but the shell only exposes the navigation entry
to administrators and refuses to switch to it for anybody else.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QColor, QFont, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy import select

from app.auth.models import User, UserRole
from app.auth.service import AuthService
from app.db.session import get_session_factory, session_scope
from app.ui.base import ResponsivePage
from app.ui.theme.tokens import Color, Spacing, Typography
from app.util.time import format_local_date

logger = logging.getLogger(__name__)

ROLE_LABELS: dict[UserRole, str] = {
    UserRole.ADMIN: "Admin",
    UserRole.INVESTIGATOR: "Investigator",
    UserRole.READ_ONLY: "Read Only",
}

ROLE_CHOICES: tuple[UserRole, ...] = (
    UserRole.ADMIN,
    UserRole.INVESTIGATOR,
    UserRole.READ_ONLY,
)

MIN_PASSWORD_LENGTH = 4


# --------------------------------------------------------------------------
# Data helpers
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class UserRow:
    """Plain snapshot of an account.

    ORM instances are not kept alive between operations: each action opens a
    short session, so the table works with immutable copies of the fields it
    actually displays.
    """

    id: int
    username: str
    full_name: str
    email: str
    role: UserRole
    is_active: bool
    last_login_at: datetime | None = None

    @property
    def role_label(self) -> str:
        return ROLE_LABELS.get(self.role, str(self.role))

    @property
    def status_label(self) -> str:
        return "Active" if self.is_active else "Inactive"


def _format_last_login(value: datetime | None) -> str:
    if value is None:
        return "Never"
    try:
        return format_local_date(value) if value else "—"
    except (AttributeError, ValueError):
        return "—"


def _load_user_rows() -> list[UserRow]:
    """Read every account into detached snapshots."""
    session_factory = get_session_factory()
    with session_factory() as session:
        users = list(
            session.execute(select(User).order_by(User.username)).scalars().all()
        )
        return [
            UserRow(
                id=user.id,
                username=user.username,
                full_name=user.full_name,
                email=user.email,
                role=user.role,
                is_active=bool(user.is_active),
                last_login_at=user.last_login_at,
            )
            for user in users
        ]


# --------------------------------------------------------------------------
# Table model
# --------------------------------------------------------------------------
class UserTableModel(QStandardItemModel):
    """Read-only account table."""

    HEADERS = ["Username", "Full Name", "Email", "Role", "Status", "Last Login"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setHorizontalHeaderLabels(self.HEADERS)

    def populate(self, rows: list[UserRow]) -> None:
        self.removeRows(0, self.rowCount())
        for row in rows:
            items = [
                QStandardItem(row.username),
                QStandardItem(row.full_name or "—"),
                QStandardItem(row.email),
                QStandardItem(row.role_label),
                QStandardItem(row.status_label),
                QStandardItem(_format_last_login(row.last_login_at)),
            ]
            for item in items:
                item.setEditable(False)
                item.setToolTip(item.text())
            items[4].setForeground(
                QColor("#34d399") if row.is_active else QColor(Color.TEXT_MUTED.name())
            )
            self.appendRow(items)


# --------------------------------------------------------------------------
# Dialogs
# --------------------------------------------------------------------------
class UserDialog(QDialog):
    """Create a new account or edit the profile of an existing one."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        row: UserRow | None = None,
        validator: Callable[[dict], str | None] | None = None,
    ):
        super().__init__(parent)
        self._creating = row is None
        self._validator = validator

        self.setWindowTitle(
            "New User" if self._creating else f"Edit User: {row.username}"
        )
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(Spacing.LG, Spacing.LG, Spacing.LG, Spacing.LG)
        layout.setSpacing(Spacing.MD)

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(Spacing.MD)
        form.setVerticalSpacing(Spacing.SM)
        form.setLabelAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        form.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow
        )

        self.username_edit = QLineEdit(row.username if row else "")
        self.username_edit.setPlaceholderText("e.g. j.smith")
        if not self._creating:
            self.username_edit.setReadOnly(True)
            self.username_edit.setProperty("readonly", True)
        form.addRow("Username", self.username_edit)

        self.full_name_edit = QLineEdit(row.full_name if row else "")
        self.full_name_edit.setPlaceholderText("Full name shown in the application")
        form.addRow("Full Name", self.full_name_edit)

        self.email_edit = QLineEdit(row.email if row else "")
        self.email_edit.setPlaceholderText("name@idfa.local")
        form.addRow("Email", self.email_edit)

        self.role_combo = QComboBox()
        for role in ROLE_CHOICES:
            self.role_combo.addItem(ROLE_LABELS[role], role)
        current_role = row.role if row is not None else UserRole.INVESTIGATOR
        if current_role in ROLE_CHOICES:
            self.role_combo.setCurrentIndex(ROLE_CHOICES.index(current_role))
        form.addRow("Role", self.role_combo)

        self.password_edit: QLineEdit | None = None
        self.confirm_edit: QLineEdit | None = None
        if self._creating:
            self.password_edit = QLineEdit()
            self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
            self.password_edit.setPlaceholderText(
                f"At least {MIN_PASSWORD_LENGTH} characters"
            )
            form.addRow("Password", self.password_edit)

            self.confirm_edit = QLineEdit()
            self.confirm_edit.setEchoMode(QLineEdit.EchoMode.Password)
            self.confirm_edit.setPlaceholderText("Repeat the password")
            form.addRow("Confirm Password", self.confirm_edit)

        layout.addLayout(form)

        if not self._creating:
            hint = QLabel(
                "Usernames cannot be changed. Access is controlled by the role "
                "and by activating or deactivating the account."
            )
            hint.setWordWrap(True)
            hint.setProperty("muted", True)
            layout.addWidget(hint)

        self._error_label = QLabel()
        self._error_label.setWordWrap(True)
        self._error_label.setStyleSheet("color: #f87171; font-size: 12px;")
        self._error_label.hide()
        layout.addWidget(self._error_label)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._finalize_size(460)

    # ------------------------------------------------------------------ data
    def get_data(self) -> dict:
        return {
            "username": self.username_edit.text().strip(),
            "full_name": self.full_name_edit.text().strip(),
            "email": self.email_edit.text().strip(),
            "role": self.role_combo.currentData(),
            "password": (
                self.password_edit.text() if self.password_edit is not None else None
            ),
        }

    # ------------------------------------------------------------ validation
    def accept(self) -> None:
        error = self._validate(self.get_data())
        if error:
            self._show_error(error)
            return
        self._error_label.hide()
        super().accept()

    def _validate(self, data: dict) -> str | None:
        if not data["full_name"]:
            self.full_name_edit.setFocus()
            return "Full name is required."

        email = data["email"]
        if (
            "@" not in email
            or email.startswith("@")
            or email.endswith("@")
            or " " in email
        ):
            self.email_edit.setFocus()
            return "Enter a valid email address."

        if self._creating:
            if not data["username"]:
                self.username_edit.setFocus()
                return "Username is required."
            if any(ch.isspace() for ch in data["username"]):
                self.username_edit.setFocus()
                return "Usernames cannot contain spaces."

            password = data["password"] or ""
            if len(password) < MIN_PASSWORD_LENGTH:
                self.password_edit.setFocus()
                return f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
            if password != self.confirm_edit.text():
                self.confirm_edit.setFocus()
                return "The passwords do not match."

        if self._validator is not None:
            try:
                return self._validator(data)
            except Exception as exc:  # database problems must not escape the dialog
                logger.exception("Could not validate account details")
                return f"Could not validate the account details: {exc}"
        return None

    # -------------------------------------------------------------- geometry
    def _finalize_size(self, width: int) -> None:
        self.setFixedWidth(width)
        self.layout().activate()
        self.adjustSize()

    def _show_error(self, message: str) -> None:
        self._error_label.setText(message)
        self._error_label.show()
        # The dialog grows downwards to make room for the message.
        self.layout().activate()
        self.adjustSize()


class PasswordResetDialog(QDialog):
    """Set a new password for an account without knowing the old one."""

    def __init__(self, row: UserRow, parent: QWidget | None = None):
        super().__init__(parent)

        self.setWindowTitle(f"Reset Password: {row.username}")
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(Spacing.LG, Spacing.LG, Spacing.LG, Spacing.LG)
        layout.setSpacing(Spacing.MD)

        intro = QLabel(
            f"Set a new password for <b>{row.full_name}</b> ({row.username})."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(Spacing.MD)
        form.setVerticalSpacing(Spacing.SM)
        form.setLabelAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        form.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow
        )

        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_edit.setPlaceholderText(f"At least {MIN_PASSWORD_LENGTH} characters")
        form.addRow("New Password", self.password_edit)

        self.confirm_edit = QLineEdit()
        self.confirm_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.confirm_edit.setPlaceholderText("Repeat the new password")
        form.addRow("Confirm Password", self.confirm_edit)

        layout.addLayout(form)

        note = QLabel(
            "The new password takes effect immediately. Sessions that are already "
            "signed in are not ended."
        )
        note.setWordWrap(True)
        note.setProperty("muted", True)
        layout.addWidget(note)

        self._error_label = QLabel()
        self._error_label.setWordWrap(True)
        self._error_label.setStyleSheet("color: #f87171; font-size: 12px;")
        self._error_label.hide()
        layout.addWidget(self._error_label)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Reset Password")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.setFixedWidth(440)
        self.layout().activate()
        self.adjustSize()

    def password(self) -> str:
        return self.password_edit.text()

    def accept(self) -> None:
        password = self.password_edit.text()
        if len(password) < MIN_PASSWORD_LENGTH:
            self._show_error(
                f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
            )
            self.password_edit.setFocus()
            return
        if password != self.confirm_edit.text():
            self._show_error("The passwords do not match.")
            self.confirm_edit.setFocus()
            return
        self._error_label.hide()
        super().accept()

    def _show_error(self, message: str) -> None:
        self._error_label.setText(message)
        self._error_label.show()
        self.layout().activate()
        self.adjustSize()


# --------------------------------------------------------------------------
# Page
# --------------------------------------------------------------------------
class UserManagementPage(ResponsivePage):
    """Administrator view of every account in the database."""

    def __init__(self, parent: QWidget | None = None):
        self._rows: list[UserRow] = []
        self._visible_rows: list[UserRow] = []
        self._current_user_id: int | None = None
        super().__init__(parent=parent)

    # ------------------------------------------------------------------ layout
    def _setup_layout(self):
        page = QVBoxLayout(self)
        page.setContentsMargins(0, 0, 0, 0)
        page.setSpacing(0)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(Spacing.LG, Spacing.LG, Spacing.LG, Spacing.MD)
        layout.setSpacing(Spacing.MD)
        page.addWidget(content, 1)

        # Header: page identity and the two page-level actions.
        header_row = QVBoxLayout()
        header_row.setSpacing(Spacing.SM)

        title = QLabel("User Management")
        title.setProperty("pageTitle", True)
        title.setFont(
            QFont(
                Typography.FONT_FAMILY,
                Typography.HEADING_LG[0],
                Typography.HEADING_LG[1],
            )
        )
        header_row.addWidget(title)
        header_actions = QHBoxLayout()
        header_actions.addStretch()
        header_row.addLayout(header_actions)

        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.setProperty("secondary", True)
        self.refresh_btn.clicked.connect(self.refresh)
        header_actions.addWidget(self.refresh_btn)

        self.new_user_btn = QPushButton("+ New User")
        self.new_user_btn.clicked.connect(self._on_new_user)
        header_actions.addWidget(self.new_user_btn)

        layout.addLayout(header_row)

        # Filters.
        filter_row = QGridLayout()
        filter_row.setSpacing(Spacing.SM)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search users...")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.setMinimumWidth(150)
        self.search_edit.setMaximumWidth(300)
        self.search_edit.setFixedHeight(36)
        self.search_edit.textChanged.connect(self._apply_filters)
        filter_row.addWidget(QLabel("Search:"), 0, 0)
        filter_row.addWidget(self.search_edit, 0, 1, 1, 3)

        self.role_filter = QComboBox()
        self.role_filter.addItem("All roles", None)
        for role in ROLE_CHOICES:
            self.role_filter.addItem(ROLE_LABELS[role], role)
        self.role_filter.setFixedHeight(36)
        self.role_filter.currentIndexChanged.connect(self._apply_filters)
        filter_row.addWidget(QLabel("Role:"), 1, 0)
        filter_row.addWidget(self.role_filter, 1, 1)

        self.status_filter = QComboBox()
        self.status_filter.addItem("All statuses", None)
        self.status_filter.addItem("Active", True)
        self.status_filter.addItem("Inactive", False)
        self.status_filter.setFixedHeight(36)
        self.status_filter.currentIndexChanged.connect(self._apply_filters)
        filter_row.addWidget(QLabel("Status:"), 2, 0)
        filter_row.addWidget(self.status_filter, 2, 1)

        filter_row.setColumnStretch(4, 1)
        layout.addLayout(filter_row)

        # Table. Sorting is deliberately off so a row index always maps to the
        # same entry in ``_visible_rows``.
        self.table = QTableView()
        self.table_model = UserTableModel(self.table)
        self.table.setModel(self.table_model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(False)
        self.table.setWordWrap(False)
        self.table.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.table.verticalHeader().setVisible(False)
        self.table.doubleClicked.connect(self._on_double_click)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_context_menu)

        table_header = self.table.horizontalHeader()
        table_header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        table_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        table_header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        table_header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        table_header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        table_header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        table_header.setStretchLastSection(False)

        selection = self.table.selectionModel()
        if selection is not None:
            selection.selectionChanged.connect(self._on_selection_changed)

        layout.addWidget(self.table, 1)

        self.empty_label = QLabel("No user accounts yet. Click + New User to add one.")
        self.empty_label.setObjectName("EmptyStateMessage")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setWordWrap(True)
        self.empty_label.setStyleSheet(
            f"color: {Color.TEXT_MUTED.name()}; font-size: 14px; padding: 48px;"
        )
        self.empty_label.hide()
        layout.addWidget(self.empty_label, 1)

        # Action bar, pinned to the bottom of the page.
        footer = QFrame()
        footer.setObjectName("PageActionBar")
        footer.setFrameShape(QFrame.Shape.NoFrame)
        page.addWidget(footer)

        footer_layout = QVBoxLayout(footer)
        footer_layout.setContentsMargins(Spacing.LG, Spacing.SM, Spacing.LG, Spacing.SM)
        footer_layout.setSpacing(Spacing.SM)

        self.summary_label = QLabel("")
        self.summary_label.setProperty("muted", True)
        self.summary_label.setWordWrap(True)
        footer_layout.addWidget(self.summary_label)
        actions = QHBoxLayout()
        actions.addStretch()
        footer_layout.addLayout(actions)

        self.edit_btn = QPushButton("Edit")
        self.edit_btn.setProperty("secondary", True)
        self.edit_btn.clicked.connect(self._on_edit_selected)
        actions.addWidget(self.edit_btn)

        self.reset_password_btn = QPushButton("Reset Password")
        self.reset_password_btn.setProperty("secondary", True)
        self.reset_password_btn.clicked.connect(self._on_reset_password)
        actions.addWidget(self.reset_password_btn)

        self.toggle_active_btn = QPushButton("Deactivate")
        self.toggle_active_btn.setProperty("secondary", True)
        self.toggle_active_btn.clicked.connect(self._on_toggle_active)
        actions.addWidget(self.toggle_active_btn)

        self._update_actions()
        self._update_summary()

    # ------------------------------------------------------------------ data
    def set_current_user(self, user) -> None:
        """Tell the page who is signed in, so self-targeting guards work."""
        self._current_user_id = getattr(user, "id", None) if user is not None else None
        if self._current_user_id is None:
            # Signed out: drop the cached accounts and show the empty state.
            self._rows = []
            self._apply_filters()
            return
        self.refresh()

    def refresh(self) -> None:
        if self._current_user_id is None:
            return
        try:
            self._rows = _load_user_rows()
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("Could not load user accounts")
            self._rows = []
            QMessageBox.warning(
                self, "User Management", f"Could not load user accounts:\n{exc}"
            )
        self._apply_filters()

    def _apply_filters(self, *_args) -> None:
        search = self.search_edit.text().strip().lower()
        role = self.role_filter.currentData()
        active = self.status_filter.currentData()

        visible: list[UserRow] = []
        for row in self._rows:
            if role is not None and row.role != role:
                continue
            if active is not None and row.is_active != active:
                continue
            if search:
                haystack = f"{row.username} {row.full_name} {row.email}".lower()
                if search not in haystack:
                    continue
            visible.append(row)

        self._visible_rows = visible
        self.table_model.populate(visible)
        self.empty_label.setText(
            "No user accounts match these filters."
            if self._rows
            else "No user accounts yet. Click + New User to add one."
        )
        self._update_table_state()
        self._update_summary()
        self._update_actions()

    def _update_table_state(self) -> None:
        has_rows = bool(self._visible_rows)
        self.table.setVisible(has_rows)
        self.empty_label.setVisible(not has_rows)

    def _update_summary(self) -> None:
        total = len(self._rows)
        if total == 0:
            self.summary_label.setText("No accounts")
            return

        active = sum(1 for row in self._rows if row.is_active)
        admins = sum(
            1
            for row in self._rows
            if row.is_active and row.role == UserRole.ADMIN
        )
        parts = [
            f"{total} account{'s' if total != 1 else ''}",
            f"{active} active",
            f"{admins} admin{'s' if admins != 1 else ''}",
        ]
        shown = len(self._visible_rows)
        if shown != total:
            parts.append(f"{shown} shown")
        self.summary_label.setText("  ·  ".join(parts))

    # -------------------------------------------------------------- selection
    def _selected_row(self) -> UserRow | None:
        selection = self.table.selectionModel()
        if selection is None:
            return None
        indexes = selection.selectedRows()
        if not indexes:
            return None
        row_index = indexes[0].row()
        if 0 <= row_index < len(self._visible_rows):
            return self._visible_rows[row_index]
        return None

    def _row_at(self, index) -> UserRow | None:
        if not index.isValid():
            return None
        row_index = index.row()
        if 0 <= row_index < len(self._visible_rows):
            return self._visible_rows[row_index]
        return None

    def _select_user(self, user_id: int) -> None:
        for row_index, row in enumerate(self._visible_rows):
            if row.id == user_id:
                self.table.selectRow(row_index)
                self.table.scrollTo(self.table_model.index(row_index, 0))
                return

    def _on_selection_changed(self, *_args) -> None:
        self._update_actions()

    def _update_actions(self) -> None:
        row = self._selected_row()
        enabled = row is not None
        self.edit_btn.setEnabled(enabled)
        self.reset_password_btn.setEnabled(enabled)
        self.toggle_active_btn.setEnabled(enabled)
        self.toggle_active_btn.setText(
            "Deactivate" if row is None or row.is_active else "Activate"
        )

    # ---------------------------------------------------------------- actions
    def _on_new_user(self) -> None:
        dialog = UserDialog(self, validator=self._validate_new_account)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        data = dialog.get_data()
        try:
            with session_scope() as session:
                created = AuthService(session).create_user(
                    username=data["username"],
                    email=data["email"],
                    password=data["password"],
                    full_name=data["full_name"],
                    role=data["role"],
                )
                new_user_id = created.id
        except Exception as exc:
            logger.exception("Could not create user account")
            QMessageBox.critical(
                self, "Create User Failed", f"Could not create the account:\n{exc}"
            )
            return

        self._audit(
            "create",
            target_id=new_user_id,
            details={"username": data["username"], "role": data["role"].value},
        )
        self.refresh()
        self._select_user(new_user_id)
        QMessageBox.information(
            self,
            "User Created",
            f"Account '{data['username']}' was created.",
        )

    def _on_edit_selected(self) -> None:
        row = self._selected_row()
        if row is not None:
            self._edit_user(row)

    def _edit_user(self, row: UserRow | None) -> None:
        if row is None:
            return

        dialog = UserDialog(
            self,
            row=row,
            validator=lambda data, target=row: self._validate_edit(target, data),
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        data = dialog.get_data()
        blocked = self._role_change_error(row, data["role"])
        if blocked:
            QMessageBox.warning(self, "Role Change Blocked", blocked)
            return

        try:
            with session_scope() as session:
                AuthService(session).update_user(
                    row.id,
                    full_name=data["full_name"],
                    email=data["email"],
                    role=data["role"],
                )
        except Exception as exc:
            logger.exception("Could not update user account")
            QMessageBox.critical(
                self, "Update Failed", f"Could not update the account:\n{exc}"
            )
            return

        details = {"username": row.username}
        if row.role != data["role"]:
            details["role"] = {"from": row.role.value, "to": data["role"].value}
        self._audit("update", target=row, details=details)
        self.refresh()
        self._select_user(row.id)

    def _on_reset_password(self) -> None:
        row = self._selected_row()
        if row is None:
            return

        dialog = PasswordResetDialog(row, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        try:
            with session_scope() as session:
                AuthService(session).admin_reset_password(row.id, dialog.password())
        except Exception as exc:
            logger.exception("Could not reset password")
            QMessageBox.critical(
                self, "Reset Failed", f"Could not reset the password:\n{exc}"
            )
            return

        self._audit("reset_password", target=row)
        QMessageBox.information(
            self,
            "Password Reset",
            f"The password for '{row.username}' was updated.",
        )

    def _on_toggle_active(self) -> None:
        row = self._selected_row()
        if row is None:
            return

        activating = not row.is_active
        if not activating and row.id == self._current_user_id:
            QMessageBox.warning(
                self,
                "Not Allowed",
                "You cannot deactivate the account you are signed in with.",
            )
            return
        if not activating and row.role == UserRole.ADMIN:
            if self._count_active_admins(exclude=row.id) == 0:
                QMessageBox.warning(
                    self,
                    "Not Allowed",
                    "At least one active administrator is required. "
                    "Promote another account first.",
                )
                return

        verb = "Activate" if activating else "Deactivate"
        consequence = (
            "They will be able to sign in again."
            if activating
            else "They will no longer be able to sign in."
        )
        reply = QMessageBox.question(
            self,
            f"{verb} User",
            f"{verb} the account '{row.username}'?\n\n{consequence}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            with session_scope() as session:
                AuthService(session).update_user(row.id, is_active=activating)
        except Exception as exc:
            logger.exception("Could not change account status")
            QMessageBox.critical(
                self, "Update Failed", f"Could not change the account status:\n{exc}"
            )
            return

        self._audit(
            "activate" if activating else "deactivate",
            target=row,
            details={"is_active": activating},
        )
        self.refresh()
        self._select_user(row.id)

    # ------------------------------------------------------------ table hooks
    def _on_double_click(self, index) -> None:
        row = self._row_at(index)
        if row is not None:
            self._edit_user(row)

    def _show_context_menu(self, pos) -> None:
        index = self.table.indexAt(pos)
        row = self._row_at(index)
        if row is None:
            return

        self.table.selectRow(index.row())

        menu = QMenu(self)

        edit_action = QAction("Edit User", self)
        edit_action.triggered.connect(lambda: self._edit_user(row))
        menu.addAction(edit_action)

        reset_action = QAction("Reset Password...", self)
        reset_action.triggered.connect(self._on_reset_password)
        menu.addAction(reset_action)

        menu.addSeparator()

        toggle_action = QAction(
            "Deactivate Account" if row.is_active else "Activate Account", self
        )
        toggle_action.triggered.connect(self._on_toggle_active)
        menu.addAction(toggle_action)

        menu.exec(self.table.viewport().mapToGlobal(pos))

    # ------------------------------------------------------------ validation
    def _validate_new_account(self, data: dict) -> str | None:
        session_factory = get_session_factory()
        with session_factory() as session:
            auth = AuthService(session)
            if auth.get_user_by_username(data["username"]) is not None:
                return f"The username '{data['username']}' is already taken."
            if auth.get_user_by_email(data["email"]) is not None:
                return "Another account already uses this email address."
        return None

    def _validate_edit(self, row: UserRow, data: dict) -> str | None:
        session_factory = get_session_factory()
        with session_factory() as session:
            existing = AuthService(session).get_user_by_email(data["email"])
            if existing is not None and existing.id != row.id:
                return "Another account already uses this email address."
        return None

    def _count_active_admins(self, exclude: int | None = None) -> int:
        session_factory = get_session_factory()
        with session_factory() as session:
            return AuthService(session).count_active_admins(exclude_user_id=exclude)

    def _role_change_error(self, row: UserRow, new_role: UserRole) -> str | None:
        if row.role == new_role:
            return None
        if row.id == self._current_user_id and new_role != UserRole.ADMIN:
            return "You cannot remove your own administrator role."
        if (
            row.is_active
            and row.role == UserRole.ADMIN
            and new_role != UserRole.ADMIN
            and self._count_active_admins(exclude=row.id) == 0
        ):
            return (
                "At least one active administrator is required. "
                "Promote another account first."
            )
        return None

    # ----------------------------------------------------------------- audit
    def _audit(
        self,
        action: str,
        *,
        target: UserRow | None = None,
        target_id: int | None = None,
        details: dict | None = None,
    ) -> None:
        from app.audit.service import AuditService

        payload = dict(details or {})
        if target is not None:
            payload.setdefault("username", target.username)

        session_factory = get_session_factory()
        try:
            with session_factory() as session:
                actor = (
                    session.get(User, self._current_user_id)
                    if self._current_user_id is not None
                    else None
                )
                AuditService(session).log_event(
                    event_type="user",
                    action=action,
                    result="success",
                    user=actor,
                    target_type="user",
                    target_id=target.id if target is not None else target_id,
                    details=payload or None,
                )
                session.commit()
        except Exception:  # auditing must never break a completed change
            logger.exception("Could not write audit event for user action %s", action)
