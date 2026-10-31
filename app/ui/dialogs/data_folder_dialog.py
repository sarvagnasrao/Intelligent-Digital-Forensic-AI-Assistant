"""Dialogs that decide where IDFA keeps its data.

Three situations share the same pieces:

* first launch on a new machine — pick a folder, show what will be created,
* a configured folder that is missing (external drive unplugged),
* changing the folder later from Settings — move, adopt existing data, or start
  fresh.

``resolve_startup`` is the entry point used by ``app.__main__``.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QTextOption
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from app.config import (
    Config,
    check_data_folder,
    default_data_dir,
    describe_layout_paths,
    ensure_data_dirs,
    folder_size_bytes,
    free_space_bytes,
)
from app.firstrun import (
    MODE_ADOPT,
    MODE_FRESH,
    MODE_MOVE,
    apply_data_dir,
    bootstrap_config,
    needs_first_run,
    set_data_dir,
    write_initial_config,
)


def _human_size(value: int | None) -> str:
    """Format a byte count for display."""
    if value is None:
        return "unknown"
    size = float(value)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def _derived_rows(config: Config, root: Path) -> list[tuple[str, str]]:
    """Return the paths that would result from using ``root`` as data folder."""
    probe = set_data_dir(config.model_copy(deep=True), root)
    return [
        ("Database", describe_layout_paths(probe)["database"]),
        ("Logs", describe_layout_paths(probe)["logs"]),
        ("Evidence", describe_layout_paths(probe)["evidence"]),
        ("Vector store", describe_layout_paths(probe)["vectors"]),
    ]


class _FolderPicker(QWidget):
    """A line edit, a browse button and the paths the choice implies."""

    def __init__(self, config: Config, initial: Path, parent=None):
        super().__init__(parent)
        self._config = config
        self._base = config.model_copy(deep=True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.path_edit = QLineEdit(str(initial))
        self.path_edit.textChanged.connect(self._refresh)
        row.addWidget(self.path_edit, 1)

        browse = QPushButton("Browse…")
        browse.setProperty("secondary", True)
        browse.clicked.connect(self._browse)
        row.addWidget(browse)
        layout.addLayout(row)

        self.details = QGridLayout()
        self.details.setContentsMargins(0, 4, 0, 0)
        self.details.setHorizontalSpacing(12)
        self.details.setVerticalSpacing(2)
        layout.addLayout(self.details)

        self.free_label = QLabel()
        self.free_label.setProperty("muted", True)
        layout.addWidget(self.free_label)

        self._refresh()

    def _browse(self) -> None:
        chosen = QFileDialog.getExistingDirectory(
            self, "Choose data folder", self.path_edit.text()
        )
        if chosen:
            self.path_edit.setText(chosen)

    def _refresh(self) -> None:
        while self.details.count():
            item = self.details.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        root = Path(self.path_edit.text().strip() or ".")
        for row, (label, value) in enumerate(_derived_rows(self._base, root)):
            caption = QLabel(label)
            caption.setProperty("muted", True)
            # A read-only line edit keeps long paths selectable and horizontally
            # scrollable without forcing the whole dialog wider than the screen.
            path_label = QLineEdit(value)
            path_label.setReadOnly(True)
            path_label.setFrame(False)
            path_label.setStyleSheet("background: transparent; border: none; padding: 0;")
            path_label.setToolTip(value)
            self.details.addWidget(caption, row, 0)
            self.details.addWidget(path_label, row, 1)

        free = free_space_bytes(root)
        self.free_label.setText(
            f"Free space on this drive: {_human_size(free)}" if free is not None
            else "Free space: unavailable"
        )

    def selected_path(self) -> Path:
        return Path(self.path_edit.text().strip())


class FirstRunDialog(QDialog):
    """Shown once, before the login screen, to choose the data folder."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Welcome to IDFA")
        self.setModal(True)
        self.setMinimumWidth(640)

        config = Config()
        suggested = default_data_dir()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 16)
        layout.setSpacing(12)

        heading = QLabel("Where should IDFA keep case data?")
        heading.setStyleSheet("font-size: 16px; font-weight: 600;")
        layout.addWidget(heading)

        explanation = QLabel(
            "Cases, evidence copies, the database, logs and the vector index all "
            "live under this folder. Choose a location with enough space for "
            "disk images — evidence is copied here, so a full disk image needs "
            "its own size again. You can change this later in Settings."
        )
        explanation.setWordWrap(True)
        explanation.setProperty("muted", True)
        layout.addWidget(explanation)

        self.picker = _FolderPicker(config, suggested)
        layout.addWidget(self.picker)

        note = QLabel(
            "Only this folder location is stored in your user profile; "
            "nothing is written into the application folder."
        )
        note.setWordWrap(True)
        note.setProperty("muted", True)
        layout.addWidget(note)

        layout.addStretch(1)

        buttons = QDialogButtonBox()
        use_recommended = QPushButton("Use recommended folder")
        use_recommended.setProperty("secondary", True)
        use_recommended.clicked.connect(
            lambda: self.picker.path_edit.setText(str(default_data_dir()))
        )
        buttons.addButton(use_recommended, QDialogButtonBox.ButtonRole.ResetRole)

        self.continue_btn = buttons.addButton("Continue", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self._on_continue)
        layout.addWidget(buttons)

    def _on_continue(self) -> None:
        target = self.picker.selected_path()
        if not target.exists():
            reply = QMessageBox.question(
                self,
                "Create folder?",
                f"{target} does not exist yet.\n\nCreate it now?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
            try:
                target.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                QMessageBox.critical(self, "Cannot create folder", str(exc))
                return

        usable, reason = check_data_folder(target)
        if not usable:
            QMessageBox.warning(self, "Folder not usable", reason)
            return
        self.accept()

    def selected_path(self) -> Path:
        return self.picker.selected_path()


class MissingDataFolderDialog(QDialog):
    """Shown when the configured data folder cannot be reached."""

    RETRY = "retry"
    CHANGE = "change"
    QUIT = "quit"

    def __init__(self, data_dir: str, reason: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("IDFA cannot reach its data folder")
        self.setModal(True)
        self.setMinimumWidth(560)
        self.choice = self.QUIT

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 16)
        layout.setSpacing(12)

        heading = QLabel("Case data folder is unavailable")
        heading.setStyleSheet("font-size: 16px; font-weight: 600;")
        layout.addWidget(heading)

        # Wrap even long, unbroken path components without altering the text
        # investigators can select and copy. Extra-long paths remain scrollable.
        path_label = QPlainTextEdit()
        path_label.setPlainText(data_dir)
        path_label.setReadOnly(True)
        path_label.setWordWrapMode(QTextOption.WrapMode.WrapAnywhere)
        path_label.setFixedHeight(70)
        layout.addWidget(path_label)

        reason_label = QLabel(reason)
        reason_label.setWordWrap(True)
        reason_label.setProperty("muted", True)
        layout.addWidget(reason_label)

        warning = QLabel(
            "IDFA will not start with an empty database, because that would look "
            "like existing cases had disappeared. Reconnect the drive and retry, "
            "or choose a different folder."
        )
        warning.setWordWrap(True)
        layout.addWidget(warning)

        layout.addStretch(1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)

        quit_btn = QPushButton("Quit")
        quit_btn.setProperty("ghost", True)
        quit_btn.clicked.connect(lambda: self._finish(self.QUIT))
        buttons.addWidget(quit_btn)

        change_btn = QPushButton("Choose another folder…")
        change_btn.setProperty("secondary", True)
        change_btn.clicked.connect(lambda: self._finish(self.CHANGE))
        buttons.addWidget(change_btn)

        retry_btn = QPushButton("Retry")
        retry_btn.clicked.connect(lambda: self._finish(self.RETRY))
        buttons.addWidget(retry_btn)
        buttons.setStretch(0, 1)

        layout.addLayout(buttons)

    def _finish(self, choice: str) -> None:
        self.choice = choice
        self.accept()


class ChangeDataFolderDialog(QDialog):
    """Settings entry point for pointing IDFA at another data folder."""

    def __init__(self, config: Config, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Change data folder")
        self.setModal(True)
        self.setMinimumWidth(640)
        self._config = config

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 16)
        layout.setSpacing(12)

        heading = QLabel("Move case data to a new folder")
        heading.setStyleSheet("font-size: 16px; font-weight: 600;")
        layout.addWidget(heading)

        self.picker = _FolderPicker(config, Path(config.app.data_dir))
        layout.addWidget(self.picker)

        usage = QLabel(
            f"Current data folder uses {_human_size(folder_size_bytes(config.app.data_dir))}."
        )
        usage.setProperty("muted", True)
        layout.addWidget(usage)

        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setProperty("muted", True)
        layout.addWidget(divider)

        self.move_radio = QRadioButton(
            "Move data — copy database and evidence;\n"
            "keep the old folder as backup"
        )
        self.adopt_radio = QRadioButton(
            "Use data already in that folder\n— nothing is copied"
        )
        self.fresh_radio = QRadioButton(
            "Start fresh — create an empty database\nin that folder"
        )
        self.move_radio.setChecked(True)

        for radio in (self.move_radio, self.adopt_radio, self.fresh_radio):
            layout.addWidget(radio)

        caution = QLabel(
            "The existing folder is never deleted. Copying large evidence sets can "
            "take a long time and needs free space equal to the current data size."
        )
        caution.setWordWrap(True)
        caution.setProperty("muted", True)
        layout.addWidget(caution)

        layout.addStretch(1)

        buttons = QDialogButtonBox()
        buttons.addButton("Cancel", QDialogButtonBox.ButtonRole.RejectRole)
        apply_btn = buttons.addButton("Apply", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self._on_apply)
        layout.addWidget(buttons)
        self._apply_button = apply_btn

    def _selected_mode(self) -> str:
        if self.adopt_radio.isChecked():
            return MODE_ADOPT
        if self.fresh_radio.isChecked():
            return MODE_FRESH
        return MODE_MOVE

    def _on_apply(self) -> None:
        target = self.picker.selected_path()
        mode = self._selected_mode()

        if mode == MODE_ADOPT:
            if not (target / "idfa.db").exists():
                reply = QMessageBox.question(
                    self,
                    "No database found",
                    f"{target} does not contain an idfa.db database.\n\n"
                    "Continue anyway and start with an empty database there?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                )
                if reply != QMessageBox.StandardButton.Yes:
                    return
            usable, reason = check_data_folder(target)
            if not usable:
                QMessageBox.warning(self, "Folder not usable", reason)
                return
        else:
            if not target.exists():
                reply = QMessageBox.question(
                    self,
                    "Create folder?",
                    f"{target} does not exist yet.\n\nCreate it now?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                )
                if reply != QMessageBox.StandardButton.Yes:
                    return
                try:
                    target.mkdir(parents=True, exist_ok=True)
                except OSError as exc:
                    QMessageBox.critical(self, "Cannot create folder", str(exc))
                    return
            usable, reason = check_data_folder(target)
            if not usable:
                QMessageBox.warning(self, "Folder not usable", reason)
                return

        if mode == MODE_MOVE:
            needed = folder_size_bytes(self._config.app.data_dir)
            free = free_space_bytes(target)
            if free is not None and free < needed:
                QMessageBox.critical(
                    self,
                    "Not enough space",
                    f"Copying needs about {_human_size(needed)} but only "
                    f"{_human_size(free)} is free on that drive.",
                )
                return

        self.accept()

    def selected_path(self) -> Path:
        return self.picker.selected_path()

    def selected_mode(self) -> str:
        """Return the mode the radio buttons describe, not a stale cached one."""
        return self._selected_mode()


def resolve_startup(parent: QWidget | None = None) -> Config | None:
    """Return a usable configuration, or ``None`` if the user chose to quit.

    Called before logging and database setup, so any dialog here can still show
    a clean error rather than failing on a missing database.
    """
    if needs_first_run():
        dialog = FirstRunDialog(parent)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        return write_initial_config(dialog.selected_path())
    config = bootstrap_config()

    while True:
        usable, reason = check_data_folder(config.app.data_dir)
        if usable:
            break

        dialog = MissingDataFolderDialog(config.app.data_dir, reason, parent)
        dialog.exec()

        if dialog.choice == MissingDataFolderDialog.QUIT:
            return None

        if dialog.choice == MissingDataFolderDialog.RETRY:
            continue

        change = ChangeDataFolderDialog(config, parent)
        if change.exec() != QDialog.DialogCode.Accepted:
            continue
        apply_data_dir(config, change.selected_path(), change.selected_mode())

    ensure_data_dirs(config)
    return config
