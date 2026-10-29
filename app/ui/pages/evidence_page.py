"""Evidence Page - list, inspect and control the evidence in a case.

The page is built around one idea: an evidence record should never be a black
box. The list says whether the file behind each record is actually present, the
detail pane shows the full record (paths, hashes, segments, custody) with the
actions that apply to it, and every action that changes something writes both a
custody event and an audit entry.

Removal and deletion are deliberately different operations:

* **Remove from case** leaves a tombstone. The record, its hashes, custody trail
  and files all stay; the item is hidden from lists and examinations and can be
  returned.
* **Delete permanently** removes the record and the copies IDFA made inside the
  case store. The original acquisition path is never touched, the case store
  boundary is enforced, and items with examination results are refused.
"""
from __future__ import annotations

import csv
import json
import os
import subprocess
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QFont, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from app.config import free_space_bytes, get_config
from app.evidence.models import (
    Evidence,
    EvidenceStatus,
    EvidenceType,
    HashAlgorithm,
)
from app.evidence.service import EvidenceService
from app.ui import qt_threads
from app.ui.base import CaseContext, ResponsivePage
from app.ui.layouts import configure_detail_pane, configure_detail_splitter
from app.ui.theme.tokens import Color, Spacing, Typography
from app.util.time import format_local_date

FILE_STATE_LABELS = {
    EvidenceService.STORED_PRESENT: "Present",
    EvidenceService.STORED_REFERENCE: "Reference only",
    EvidenceService.STORED_MISSING: "Missing",
}

# Formats a viewer can open without any risk of a write: images, PDFs and plain
# text. Disk images are deliberately excluded - "open" means "show me where it
# is", not "mount it with whatever Windows associates with .dd".
SAFE_PREVIEW_MIME_PREFIXES = ("image/", "text/")
SAFE_PREVIEW_MIME_TYPES = {
    "application/pdf",
    "application/json",
    "application/xml",
}

STATUS_FILTERS = (
    ("All statuses", ""),
    ("Registered", EvidenceStatus.REGISTERED.value),
    ("Integrity verified", EvidenceStatus.INTEGRITY_VERIFIED.value),
    ("Integrity failed", EvidenceStatus.INTEGRITY_FAILED.value),
    ("Examined", EvidenceStatus.EXAMINED.value),
    ("Indexed", EvidenceStatus.INDEXED.value),
    ("Archived", EvidenceStatus.ARCHIVED.value),
)


def _format_size(bytes_value: float) -> str:
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if bytes_value < 1024:
            return f"{bytes_value:.1f} {unit}"
        bytes_value /= 1024
    return f"{bytes_value:.1f} PB"


# --------------------------------------------------------------- worker threads
class _RegisterEvidenceThread(QThread):
    progress = Signal(str, int)
    registered = Signal(str)
    failed = Signal(str)

    def __init__(self, case_id: int, data: dict, user_id: int):
        super().__init__()
        self.case_id = case_id
        self.data = data
        self.user_id = user_id

    def run(self):
        from app.auth.models import User
        from app.db.session import get_session_factory

        session = get_session_factory()()
        try:
            service = EvidenceService(session)
            user = session.get(User, self.user_id)
            if user is None:
                raise ValueError("Signed-in user could not be found")

            def report(message, current, total):
                percent = int(current * 100 / total) if total else 0
                self.progress.emit(message, min(percent, 100))

            reference_hashes = None
            if self.data.get("reference_hash"):
                reference_hashes = {
                    HashAlgorithm(self.data["reference_algorithm"]):
                        self.data["reference_hash"]
                }
            item = service.register_evidence(
                case_id=self.case_id,
                name=self.data["name"],
                source_path=self.data["source_path"],
                description=self.data["description"],
                registered_by=user,
                copy_to_store=self.data["copy_to_store"],
                reference_hashes=reference_hashes,
                progress_callback=report,
            )
            session.commit()
            self.registered.emit(item.evidence_id)
        except Exception as exc:
            session.rollback()
            self.failed.emit(str(exc))
        finally:
            session.close()


class _VerifyThread(QThread):
    """Verify one or more items; each is independent, so one failure does not stop the rest."""

    progress = Signal(str, int)
    done = Signal(object)  # list[tuple[str, bool, str]]
    failed = Signal(str)

    def __init__(self, evidence_ids: list[int], user_id: int):
        super().__init__()
        self.evidence_ids = evidence_ids
        self.user_id = user_id

    def run(self):
        from app.auth.models import User
        from app.db.session import get_session_factory

        session = get_session_factory()()
        results: list[tuple[str, bool, str]] = []
        try:
            service = EvidenceService(session)
            user = session.get(User, self.user_id)
            if user is None:
                raise ValueError("Signed-in user could not be found")

            for index, evidence_pk in enumerate(self.evidence_ids, 1):
                evidence = service.get_evidence_by_id(evidence_pk)
                reference = evidence.evidence_id if evidence else str(evidence_pk)

                def report(message, current, total, _index=index):
                    percent = int(current * 100 / total) if total else 0
                    self.progress.emit(
                        f"{_index}/{len(self.evidence_ids)} · {message}",
                        min(percent, 100),
                    )

                try:
                    outcome = service.verify_integrity(
                        evidence_pk, user, progress_callback=report
                    )
                    passed = all(outcome.values())
                    detail = ", ".join(
                        f"{algo.value.upper()} {'PASS' if ok else 'FAIL'}"
                        for algo, ok in outcome.items()
                    )
                    results.append((reference, passed, detail))
                except Exception as exc:  # noqa: BLE001 - reported per item
                    session.rollback()
                    results.append((reference, False, str(exc)))

            session.commit()
            self.done.emit(results)
        except Exception as exc:  # noqa: BLE001 - surfaced to the investigator
            session.rollback()
            self.failed.emit(str(exc))
        finally:
            session.close()


class _ReferenceHashThread(QThread):
    progress = Signal(str, int)
    done = Signal(object)  # dict[str, bool]
    failed = Signal(str)

    def __init__(self, evidence_id: int, algorithm: str, value: str, note: str, user_id: int):
        super().__init__()
        self.evidence_id = evidence_id
        self.algorithm = algorithm
        self.value = value
        self.note = note
        self.user_id = user_id

    def run(self):
        from app.auth.models import User
        from app.db.session import get_session_factory

        session = get_session_factory()()
        try:
            service = EvidenceService(session)
            user = session.get(User, self.user_id)
            if user is None:
                raise ValueError("Signed-in user could not be found")

            def report(message, current, total):
                percent = int(current * 100 / total) if total else 0
                self.progress.emit(message, min(percent, 100))

            results = service.set_reference_hash(
                self.evidence_id,
                HashAlgorithm(self.algorithm),
                self.value,
                user,
                note=self.note,
                progress_callback=report,
            )
            session.commit()
            self.done.emit({algo.value: ok for algo, ok in results.items()})
        except Exception as exc:  # noqa: BLE001 - surfaced to the investigator
            session.rollback()
            self.failed.emit(str(exc))
        finally:
            session.close()


class _ExportThread(QThread):
    progress = Signal(str, int)
    done = Signal(object)  # dict from EvidenceService.export_copy
    failed = Signal(str)

    def __init__(self, evidence_id: int, destination: str, user_id: int):
        super().__init__()
        self.evidence_id = evidence_id
        self.destination = destination
        self.user_id = user_id

    def run(self):
        from app.auth.models import User
        from app.db.session import get_session_factory

        session = get_session_factory()()
        try:
            service = EvidenceService(session)
            user = session.get(User, self.user_id)
            if user is None:
                raise ValueError("Signed-in user could not be found")

            def report(message, current, total):
                percent = int(current * 100 / total) if total else 0
                self.progress.emit(message, min(percent, 100))

            result = service.export_copy(
                self.evidence_id, self.destination, user, progress_callback=report
            )
            session.commit()
            self.done.emit(result)
        except Exception as exc:  # noqa: BLE001 - surfaced to the investigator
            session.rollback()
            self.failed.emit(str(exc))
        finally:
            session.close()


# ---------------------------------------------------------------------- dialogs
class RegisterEvidenceDialog(QDialog):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Register Evidence")
        self.setModal(True)
        self.resize(640, 520)

        layout = QFormLayout(self)
        layout.setSpacing(Spacing.MD)
        layout.setContentsMargins(Spacing.LG, Spacing.LG, Spacing.LG, Spacing.LG)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Evidence name")
        layout.addRow("Name:", self.name_edit)

        file_row = QHBoxLayout()
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText("Select the source file or the .001 segment of an image")
        self.path_edit.setReadOnly(True)
        browse_btn = QPushButton("Browse")
        browse_btn.clicked.connect(self._browse_file)
        file_row.addWidget(self.path_edit)
        file_row.addWidget(browse_btn)
        layout.addRow("Source file:", file_row)

        file_hint = QLabel(
            "The format is detected automatically. For a segmented raw image, "
            "select .001 or any later segment; the complete set is registered as "
            "one item."
        )
        file_hint.setWordWrap(True)
        file_hint.setStyleSheet(f"color: {Color.TEXT_SECONDARY.name()};")
        layout.addRow("", file_hint)

        self.detected_type_label = QLabel("Select a file to identify its type automatically.")
        self.detected_type_label.setWordWrap(True)
        self.detected_type_label.setStyleSheet(f"color: {Color.TEXT_SECONDARY.name()};")
        layout.addRow("Detected type:", self.detected_type_label)

        self.desc_edit = QLineEdit()
        self.desc_edit.setPlaceholderText("Optional description")
        layout.addRow("Description:", self.desc_edit)

        self.copy_check = QComboBox()
        self.copy_check.addItems(["Copy to case store", "Reference only"])
        self.copy_check.setToolTip(
            "Copy to case store keeps a managed copy under the case data folder, "
            "so the evidence survives the original being moved. Reference only "
            "records the path in place."
        )
        layout.addRow("Storage:", self.copy_check)

        # The hash printed on the evidence bag or lab sheet. Recording it at
        # intake compares it with the copy immediately instead of at the first
        # verification run.
        self.hash_algorithm = QComboBox()
        for algorithm, label in (
            (HashAlgorithm.SHA256, "SHA-256"),
            (HashAlgorithm.SHA1, "SHA-1"),
            (HashAlgorithm.MD5, "MD5"),
        ):
            self.hash_algorithm.addItem(label, algorithm.value)
        layout.addRow("Known hash:", self.hash_algorithm)

        self.reference_hash = QLineEdit()
        self.reference_hash.setPlaceholderText("Optional: paste the hash from the evidence bag")
        self.reference_hash.setFont(QFont("Consolas", Typography.MONO_SM[0]))
        layout.addRow("", self.reference_hash)

        hash_hint = QLabel(
            "Leave blank to use the hash IDFA calculates. If supplied, it becomes "
            "the reference and the copy is checked against it at registration."
        )
        hash_hint.setWordWrap(True)
        hash_hint.setStyleSheet(f"color: {Color.TEXT_SECONDARY.name()};")
        layout.addRow("", hash_hint)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept_if_valid)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def _browse_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Evidence File",
            "",
            "All Files (*);;Disk Images (*.001 *.002 *.dd *.img *.raw *.e01 *.E01)",
        )
        if not path:
            return
        suffix = path.rsplit(".", 1)[-1].lower() if "." in path else ""
        if len(suffix) == 3 and suffix.isdigit() and int(suffix) > 0:
            first_part = path[: -len(suffix)] + "001"
            if Path(first_part).is_file():
                path = first_part
        detected_type, mime_type = EvidenceService.detect_file_type(path)
        friendly = "Forensic disk image" if detected_type == EvidenceType.IMAGE else "File"
        self.detected_type_label.setText(f"{friendly} — {mime_type}")
        self.path_edit.setText(path)
        if not self.name_edit.text():
            image_name = Path(path).name
            if image_name.lower().endswith(".001"):
                image_name = image_name[:-4]
            self.name_edit.setText(image_name)

    def _accept_if_valid(self):
        algorithm = HashAlgorithm(self.hash_algorithm.currentData())
        value = self.reference_hash.text().strip()
        if value:
            expected = EvidenceService._HEX_LENGTH[algorithm]
            cleaned = value.lower()
            if len(cleaned) != expected or any(
                character not in "0123456789abcdef" for character in cleaned
            ):
                QMessageBox.warning(
                    self,
                    "Hash looks wrong",
                    f"A {algorithm.value.upper()} hash is {expected} hexadecimal "
                    f"characters, but this one is {len(cleaned)}.",
                )
                return
        self.accept()

    def get_data(self) -> dict:
        return {
            "name": self.name_edit.text().strip(),
            "source_path": self.path_edit.text().strip(),
            "description": self.desc_edit.text().strip() or None,
            "copy_to_store": self.copy_check.currentIndex() == 0,
            "reference_algorithm": self.hash_algorithm.currentData(),
            "reference_hash": self.reference_hash.text().strip().lower(),
        }


class RemoveEvidenceDialog(QDialog):
    """Take an item out of the case without touching the record or files."""

    def __init__(self, evidence: Evidence, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle(f"Remove {evidence.evidence_id}")
        self.setModal(True)
        self.resize(520, 260)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(Spacing.LG, Spacing.LG, Spacing.LG, Spacing.LG)
        layout.setSpacing(Spacing.MD)

        title = QLabel(f"Remove {evidence.evidence_id} — {evidence.name} from the case?")
        title.setWordWrap(True)
        title.setFont(
            QFont(Typography.FONT_FAMILY, Typography.HEADING_SM[0], Typography.HEADING_SM[1])
        )
        layout.addWidget(title)

        detail = QLabel(
            "The record, its hashes, its custody history and any stored files are "
            "kept. The item is hidden from the evidence list, examinations and "
            "reports, and you can return it later."
        )
        detail.setWordWrap(True)
        detail.setProperty("sectionHint", True)
        layout.addWidget(detail)

        layout.addWidget(QLabel("Reason (recorded in the custody trail):"))
        self.reason_edit = QLineEdit()
        self.reason_edit.setPlaceholderText("e.g. duplicate registration of E002")
        layout.addWidget(self.reason_edit)
        layout.addStretch(1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Remove from case")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_reason(self) -> str:
        return self.reason_edit.text().strip()


class DeleteEvidenceDialog(QDialog):
    """Permanent deletion, showing exactly what will go and why it may not."""

    def __init__(
        self,
        evidence: Evidence,
        files: list[Path],
        blockers: list[str],
        parent: QWidget | None = None,
        impact: dict[str, int] | None = None,
    ):
        super().__init__(parent)
        self.evidence = evidence
        self.setWindowTitle(f"Delete {evidence.evidence_id} permanently")
        self.setModal(True)
        self.resize(560, 430)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(Spacing.LG, Spacing.LG, Spacing.LG, Spacing.LG)
        layout.setSpacing(Spacing.MD)

        title = QLabel(f"Delete {evidence.evidence_id} — {evidence.name}?")
        title.setWordWrap(True)
        title.setFont(
            QFont(Typography.FONT_FAMILY, Typography.HEADING_SM[0], Typography.HEADING_SM[1])
        )
        layout.addWidget(title)

        total = sum(part.stat().st_size for part in files if part.is_file())
        impact = impact or {"jobs": 0, "artifacts": 0}
        derived = (
            f"\n\nThis also permanently deletes {impact['jobs']} examination job(s) "
            f"and {impact['artifacts']} extracted artifact(s), including their chunks "
            "and derived analysis results."
        )
        if files:
            summary = QLabel(
                f"{len(files)} file(s), {_format_size(total)}, will be deleted from the "
                f"case store. The record and its custody history go with it.{derived}"
            )
        else:
            summary = QLabel(
                "No case-store files are present. Only the record and its custody "
                "history will be deleted; the original acquisition is never touched."
                f"{derived}"
            )
        summary.setWordWrap(True)
        layout.addWidget(summary)

        if files:
            listing = QLabel("\n".join(str(part) for part in files))
            listing.setFont(QFont("Consolas", Typography.MONO_SM[0]))
            listing.setWordWrap(True)
            listing.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            layout.addWidget(listing)

        note = QLabel(f"The original file is kept: {evidence.source_path}")
        note.setWordWrap(True)
        note.setProperty("sectionHint", True)
        layout.addWidget(note)

        self.confirm_edit = QLineEdit()
        self.confirm_edit.setPlaceholderText(evidence.evidence_id)
        layout.addWidget(QLabel(f"Type {evidence.evidence_id} to confirm:"))
        layout.addWidget(self.confirm_edit)

        layout.addWidget(QLabel("Reason (recorded in the audit trail):"))
        self.reason_edit = QLineEdit()
        self.reason_edit.setPlaceholderText("e.g. wrong file registered twice")
        layout.addWidget(self.reason_edit)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Delete permanently")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        if blockers:
            blocker_label = QLabel(
                "Cannot delete yet:\n"
                + "\n".join(f"• {item}" for item in blockers)
            )
            blocker_label.setWordWrap(True)
            blocker_label.setStyleSheet(f"color: {Color.ERROR.name()};")
            layout.addWidget(blocker_label)
            self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)
            self.confirm_edit.setEnabled(False)
            self.reason_edit.setEnabled(False)
        else:
            self._update_ok()
            self.confirm_edit.textChanged.connect(self._update_ok)

    def _update_ok(self):
        typed = self.confirm_edit.text().strip()
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(
            typed == self.evidence.evidence_id
        )

    def get_reason(self) -> str:
        return self.reason_edit.text().strip()


class ReferenceHashDialog(QDialog):
    """Record the hash from an evidence bag and check the copy against it."""

    def __init__(self, evidence: Evidence, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle(f"Reference hash for {evidence.evidence_id}")
        self.setModal(True)
        self.resize(560, 300)

        layout = QFormLayout(self)
        layout.setContentsMargins(Spacing.LG, Spacing.LG, Spacing.LG, Spacing.LG)
        layout.setSpacing(Spacing.MD)

        hint = QLabel(
            "The value you enter becomes the reference for this item, and the "
            "stored copy is hashed immediately to show whether they match."
        )
        hint.setWordWrap(True)
        hint.setProperty("sectionHint", True)
        layout.addRow(hint)

        existing = next(
            (item for item in evidence.hashes if item.is_reference), None
        )
        self.algorithm = QComboBox()
        for algorithm, label in (
            (HashAlgorithm.SHA256, "SHA-256"),
            (HashAlgorithm.SHA1, "SHA-1"),
            (HashAlgorithm.MD5, "MD5"),
        ):
            self.algorithm.addItem(label, algorithm.value)
        if existing is not None:
            self.algorithm.setCurrentIndex(
                max(0, self.algorithm.findData(existing.algorithm.value))
            )
        layout.addRow("Algorithm:", self.algorithm)

        self.value_edit = QLineEdit(existing.hash_value if existing else "")
        self.value_edit.setFont(QFont("Consolas", Typography.MONO_SM[0]))
        self.value_edit.setPlaceholderText("Paste the hash exactly as recorded")
        layout.addRow("Hash:", self.value_edit)

        self.note_edit = QLineEdit()
        self.note_edit.setPlaceholderText("Where it came from, e.g. evidence bag label")
        layout.addRow("Source:", self.note_edit)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept_if_valid)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def _accept_if_valid(self):
        algorithm = HashAlgorithm(self.algorithm.currentData())
        value = self.value_edit.text().strip().lower()
        expected = EvidenceService._HEX_LENGTH[algorithm]
        if len(value) != expected or any(
            character not in "0123456789abcdef" for character in value
        ):
            QMessageBox.warning(
                self,
                "Hash looks wrong",
                f"A {algorithm.value.upper()} hash is {expected} hexadecimal "
                f"characters, but this one is {len(value)}.",
            )
            return
        self.accept()

    def get_data(self) -> dict:
        return {
            "algorithm": self.algorithm.currentData(),
            "value": self.value_edit.text().strip().lower(),
            "note": self.note_edit.text().strip(),
        }


class EditDetailsDialog(QDialog):
    def __init__(self, evidence: Evidence, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle(f"Edit {evidence.evidence_id}")
        self.setModal(True)
        self.resize(520, 260)

        layout = QFormLayout(self)
        layout.setContentsMargins(Spacing.LG, Spacing.LG, Spacing.LG, Spacing.LG)
        layout.setSpacing(Spacing.MD)

        self.name_edit = QLineEdit(evidence.name)
        layout.addRow("Name:", self.name_edit)

        self.description_edit = QLineEdit(evidence.description or "")
        self.description_edit.setPlaceholderText("Optional description")
        layout.addRow("Description:", self.description_edit)

        hint = QLabel("Edits are recorded in the custody trail and the audit log.")
        hint.setProperty("sectionHint", True)
        hint.setWordWrap(True)
        layout.addRow(hint)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept_if_valid)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def _accept_if_valid(self):
        if not self.name_edit.text().strip():
            QMessageBox.warning(self, "Name required", "The evidence name cannot be empty.")
            return
        self.accept()

    def get_data(self) -> dict:
        return {
            "name": self.name_edit.text().strip(),
            "description": self.description_edit.text().strip(),
        }


# ------------------------------------------------------------------ table model
class EvidenceTableModel(QStandardItemModel):
    HEADERS = [
        "ID", "Name", "Detected Type", "Size", "File", "Integrity",
        "Status", "Registered",
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setHorizontalHeaderLabels(self.HEADERS)

    def populate(self, evidence_list: list[Evidence], file_states: dict[int, str]):
        self.removeRows(0, self.rowCount())
        for ev in evidence_list:
            state = file_states.get(ev.id, EvidenceService.STORED_MISSING)
            name = ev.name + ("  · removed" if ev.is_removed else "")

            id_item = QStandardItem(ev.evidence_id)
            # The database id, so a row can be resolved without matching text.
            id_item.setData(ev.id, Qt.ItemDataRole.UserRole)

            row = [
                id_item,
                QStandardItem(name),
                QStandardItem(self._display_type(ev)),
                QStandardItem(_format_size(ev.size_bytes)),
                QStandardItem(FILE_STATE_LABELS.get(state, state)),
                QStandardItem(self._get_integrity_status(ev)),
                QStandardItem(ev.status.value.replace("_", " ").title()),
                QStandardItem(
                    format_local_date(ev.registered_at) if ev.registered_at else ""
                ),
            ]
            for item in row:
                item.setEditable(False)

            file_item = row[4]
            if state == EvidenceService.STORED_MISSING:
                file_item.setForeground(Color.ERROR)
                file_item.setToolTip(
                    "The file this record points at is not on disk. It may have "
                    "been moved or deleted outside IDFA."
                )
            elif state == EvidenceService.STORED_REFERENCE:
                file_item.setToolTip(
                    "Registered in place: no managed copy exists in the case store."
                )

            if ev.is_removed:
                for item in row:
                    item.setForeground(Color.TEXT_SECONDARY)

            self.appendRow(row)

    @staticmethod
    def _display_type(evidence: Evidence) -> str:
        mime_type = evidence.mime_type
        known_types = {
            "application/x-raw-disk-image": "Raw disk image",
            "application/x-ewf": "EWF disk image",
            "application/pdf": "PDF document",
            "application/zip": "ZIP archive",
            "application/vnd.sqlite3": "SQLite database",
            "application/vnd.microsoft.portable-executable": "Windows executable",
            "application/x-elf": "ELF executable",
        }
        if mime_type in known_types:
            return known_types[mime_type]
        if mime_type and mime_type != "application/octet-stream":
            return mime_type
        return "Unknown file type"

    def _get_integrity_status(self, ev: Evidence) -> str:
        if not ev.hashes:
            return "Not calculated"
        ref_hashes = [item for item in ev.hashes if item.is_reference]
        if not ref_hashes:
            return "Calculated"
        verified = [item for item in ref_hashes if item.verified_at]
        if len(verified) == len(ref_hashes):
            if all(item.match_result for item in verified):
                return "Verified ✓"
            return "Mismatch ✗"
        return "Calculated"


# ----------------------------------------------------------------- detail pane
class EvidenceDetailPane(QFrame):
    """The selected item's full record, with the actions that apply to it."""

    action_requested = Signal(str, int)  # action name, evidence database id

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("DetailPane")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        configure_detail_pane(self)
        self._evidence_id: int | None = None

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(Spacing.SM, Spacing.SM, Spacing.SM, Spacing.SM)
        self._layout.setSpacing(Spacing.SM)

        # The record can be taller than the pane (several segments, hashes and
        # custody events), so it scrolls instead of being squeezed: a compressed
        # layout overlaps labels and hides the very paths this pane exists to
        # show.
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._scroll.viewport().setAutoFillBackground(False)

        self._body = QWidget()
        self._body.setAutoFillBackground(False)
        self._body_layout = QVBoxLayout(self._body)
        self._body_layout.setContentsMargins(0, 0, 0, 0)
        self._body_layout.setSpacing(Spacing.SM)
        self._scroll.setWidget(self._body)
        self._layout.addWidget(self._scroll, 1)

        # Actions stay outside the scroll area so they are always reachable.
        self._actions_host = QWidget()
        self._actions_host.setObjectName("DetailActions")
        self._actions_layout = QVBoxLayout(self._actions_host)
        self._actions_layout.setContentsMargins(0, Spacing.SM, 0, 0)
        self._actions_layout.setSpacing(Spacing.XS)
        self._layout.addWidget(self._actions_host)

        self.set_evidence(None, EvidenceService.STORED_MISSING, [])

    # -- construction ------------------------------------------------------
    def _clear(self) -> None:
        self._clear_layout(self._body_layout)
        self._clear_layout(self._actions_layout)

    @staticmethod
    def _clear_layout(layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                # deleteLater alone leaves the widget parented and painted at
                # its old geometry until the event loop catches up, which drew
                # the previous record on top of the new one.
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
            elif item.layout() is not None:
                EvidenceDetailPane._clear_layout(item.layout())

    def set_evidence(
        self,
        evidence: Evidence | None,
        file_state: str = EvidenceService.STORED_MISSING,
        parts: list[Path] | None = None,
    ) -> None:
        self._clear()
        self._evidence_id = evidence.id if evidence else None

        if evidence is None:
            self._actions_host.setVisible(False)
            placeholder = QLabel("Select an item to see its full record and actions.")
            placeholder.setWordWrap(True)
            placeholder.setProperty("sectionHint", True)
            self._body_layout.addWidget(placeholder)
            return

        self._actions_host.setVisible(True)

        title = QLabel(f"{evidence.evidence_id} · {evidence.name}")
        title.setWordWrap(True)
        title.setFont(
            QFont(Typography.FONT_FAMILY, Typography.HEADING_SM[0], Typography.HEADING_SM[1])
        )
        self._body_layout.addWidget(title)

        status = QLabel(self._status_line(evidence, file_state))
        status.setWordWrap(True)
        if evidence.is_removed:
            status.setStyleSheet(f"color: {Color.WARNING.name()};")
        elif file_state == EvidenceService.STORED_MISSING:
            status.setStyleSheet(f"color: {Color.ERROR.name()};")
        else:
            status.setProperty("sectionHint", True)
        self._body_layout.addWidget(status)

        form = QFormLayout()
        form.setSpacing(Spacing.XS)
        form.setContentsMargins(0, 0, 0, 0)

        self._add_row(form, "Category", evidence.evidence_type.value.replace("_", " ").title())
        self._add_row(form, "Detected type", EvidenceTableModel._display_type(evidence))
        self._add_row(form, "Size", _format_size(evidence.size_bytes))
        self._add_row(
            form,
            "Registered",
            format_local_date(evidence.registered_at) if evidence.registered_at else "Unknown",
        )
        if evidence.description:
            self._add_row(form, "Description", evidence.description)
        self._body_layout.addLayout(form)

        self._add_path_block(evidence, file_state, parts or [])
        self._add_hash_block(evidence)
        self._add_custody_block(evidence)
        self._add_actions(evidence)
        self._body_layout.addStretch(1)

    @staticmethod
    def _status_line(evidence: Evidence, file_state: str) -> str:
        pieces = [evidence.status.value.replace("_", " ").title()]
        if evidence.is_removed:
            pieces.append("removed from case")
        if file_state == EvidenceService.STORED_MISSING:
            pieces.append("file missing on disk")
        elif file_state == EvidenceService.STORED_REFERENCE:
            pieces.append("reference only, no managed copy")
        return " · ".join(pieces)

    def _add_row(self, form: QFormLayout, caption: str, value: str) -> None:
        label = QLabel(caption)
        label.setStyleSheet(f"color: {Color.TEXT_SECONDARY.name()};")
        text = QLabel(str(value))
        text.setWordWrap(True)
        text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        form.addRow(label, text)

    def _add_path_block(self, evidence: Evidence, file_state: str, parts: list[Path]) -> None:
        box = QFrame()
        box.setProperty("card", True)
        layout = QVBoxLayout(box)
        layout.setContentsMargins(Spacing.SM, Spacing.SM, Spacing.SM, Spacing.SM)
        layout.setSpacing(Spacing.XS)

        heading = QLabel("Files")
        heading.setFont(QFont(Typography.FONT_FAMILY, Typography.BODY_SM[0], QFont.Weight.Bold))
        layout.addWidget(heading)

        if evidence.stored_path:
            layout.addWidget(self._hint("Stored copy (managed by IDFA)"))
            layout.addLayout(self._field_row(evidence.stored_path))
            layout.addWidget(self._path_buttons(evidence.stored_path, file_state))
        else:
            layout.addWidget(self._hint("Reference only (registered in place)"))
            layout.addLayout(self._field_row(evidence.source_path))
            layout.addWidget(self._path_buttons(evidence.source_path, file_state))

        if len(parts) > 1:
            listing = QLabel(
                "\n".join(
                    f"{part.name} · {_format_size(part.stat().st_size)}"
                    for part in parts
                    if part.is_file()
                )
            )
            listing.setFont(QFont("Consolas", Typography.MONO_SM[0]))
            listing.setWordWrap(True)
            layout.addWidget(listing)
            count = QLabel(f"{len(parts)} segments of one image")
            count.setProperty("sectionHint", True)
            layout.addWidget(count)

        layout.addWidget(self._hint("Original acquisition (never modified)"))
        layout.addLayout(self._field_row(evidence.source_path, secondary=True))

        self._body_layout.addWidget(box)

    def _field_row(
        self, text: str, secondary: bool = False, color=None
    ) -> QHBoxLayout:
        """A value field with its Copy button, so the value keeps the width."""
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(Spacing.XS)
        row.addWidget(self._mono_field(text, secondary=secondary, color=color), 1)
        copy = QPushButton("Copy")
        copy.setProperty("compact", True)
        copy.setProperty("ghost", True)
        copy.clicked.connect(lambda _checked=False, value=text: self._emit("copy", value))
        row.addWidget(copy)
        return row

    def _mono_field(self, text: str, secondary: bool = False, color=None) -> QLineEdit:
        """Show a path or hash in full, selectable, without stretching the pane.

        A wrapped QLabel cannot break an unbroken path at a separator, so its
        minimum width made the detail pane wider than the window. A read-only
        line edit keeps the exact string (no inserted characters), scrolls
        horizontally on its own, and is still selectable and copyable.
        """
        field = QLineEdit(text)
        field.setReadOnly(True)
        field.setFont(QFont("Consolas", Typography.MONO_SM[0]))
        field.setMinimumWidth(60)
        field.setCursorPosition(0)
        field.setToolTip(text)
        if color is not None:
            field.setStyleSheet(f"color: {color.name()};")
        elif secondary:
            field.setStyleSheet(f"color: {Color.TEXT_SECONDARY.name()};")
        return field

    def _path_buttons(self, path: str, file_state: str) -> QWidget:
        holder = QWidget()
        row = QHBoxLayout(holder)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(Spacing.XS)

        open_folder = QPushButton("Open folder")
        open_folder.setProperty("compact", True)
        open_folder.setProperty("ghost", True)
        open_folder.clicked.connect(
            lambda _checked=False, p=path: self._emit("open_folder", p)
        )
        row.addWidget(open_folder)

        if file_state == EvidenceService.STORED_PRESENT:
            open_file = QPushButton("Open file")
            open_file.setProperty("compact", True)
            open_file.setProperty("ghost", True)
            open_file.clicked.connect(
                lambda _checked=False, p=path: self._emit("open_file", p)
            )
            row.addWidget(open_file)

        row.addStretch(1)
        return holder

    def _add_hash_block(self, evidence: Evidence) -> None:
        box = QFrame()
        box.setProperty("card", True)
        layout = QVBoxLayout(box)
        layout.setContentsMargins(Spacing.SM, Spacing.SM, Spacing.SM, Spacing.SM)
        layout.setSpacing(Spacing.XS)

        heading = QLabel("Hashes")
        heading.setFont(QFont(Typography.FONT_FAMILY, Typography.BODY_SM[0], QFont.Weight.Bold))
        layout.addWidget(heading)

        if not evidence.hashes:
            layout.addWidget(self._hint("No hash has been calculated for this item."))
        order = {HashAlgorithm.SHA256: 0, HashAlgorithm.SHA1: 1, HashAlgorithm.MD5: 2}
        records = sorted(
            evidence.hashes,
            key=lambda item: (order.get(item.algorithm, 9), not item.is_reference),
        )
        for record in records:
            failed = record.is_reference and record.match_result is False
            passed = record.is_reference and record.match_result is True
            caption = QLabel(
                record.algorithm.value.upper()
                + (" · reference" if record.is_reference else " · calculated")
                + (" · MATCH" if passed else " · MISMATCH" if failed else "")
            )
            caption.setStyleSheet(
                f"color: {Color.ERROR.name()};" if failed
                else f"color: {Color.SUCCESS.name()};" if passed
                else f"color: {Color.TEXT_SECONDARY.name()};"
            )
            layout.addWidget(caption)

            layout.addLayout(
                self._field_row(
                    record.hash_value,
                    color=Color.ERROR if failed else Color.SUCCESS if passed else None,
                )
            )

            if record.verified_at:
                verified = QLabel(
                    "Verified " + format_local_date(record.verified_at)
                    + ("" if record.match_result is None else
                       " · PASS" if record.match_result else " · FAIL")
                )
                verified.setProperty("sectionHint", True)
                layout.addWidget(verified)

        self._body_layout.addWidget(box)

    def _add_custody_block(self, evidence: Evidence) -> None:
        events = sorted(
            evidence.custody_events,
            key=lambda event: event.performed_at or 0,
            reverse=True,
        )[:4]
        if not events:
            return

        box = QFrame()
        box.setProperty("card", True)
        layout = QVBoxLayout(box)
        layout.setContentsMargins(Spacing.SM, Spacing.SM, Spacing.SM, Spacing.SM)
        layout.setSpacing(Spacing.XS)

        heading = QLabel("Recent custody")
        heading.setFont(QFont(Typography.FONT_FAMILY, Typography.BODY_SM[0], QFont.Weight.Bold))
        layout.addWidget(heading)

        for event in events:
            line = QLabel(
                f"{format_local_date(event.performed_at)} · "
                f"{event.event_type.replace('_', ' ')} — {event.description}"
            )
            line.setWordWrap(True)
            line.setProperty("sectionHint", True)
            layout.addWidget(line)

        total = QLabel(f"{len(evidence.custody_events)} events in Audit & Custody")
        total.setProperty("sectionHint", True)
        layout.addWidget(total)
        self._body_layout.addWidget(box)

    def _add_actions(self, evidence: Evidence) -> None:
        grid = QGridLayout()
        grid.setContentsMargins(0, Spacing.XS, 0, 0)
        grid.setSpacing(Spacing.XS)

        def button(caption, action, destructive=False):
            control = QPushButton(caption)
            control.setProperty("compact", True)
            control.setProperty("ghost", not destructive)
            if destructive:
                control.setProperty("destructive", True)
            control.clicked.connect(
                lambda _checked=False, a=action: self._emit(a)
            )
            return control

        removed = evidence.is_removed
        grid.addWidget(button("Verify", "verify"), 0, 0)
        grid.addWidget(button("Export copy…", "export"), 0, 1)
        grid.addWidget(button("Reference hash…", "reference_hash"), 1, 0)
        grid.addWidget(button("Edit details…", "edit"), 1, 1)
        grid.addWidget(
            button("Return to case" if removed else "Remove…",
                   "return" if removed else "remove"), 2, 0
        )
        grid.addWidget(
            button("Delete permanently…", "delete", destructive=True), 2, 1
        )
        self._actions_layout.addLayout(grid)

    @staticmethod
    def _hint(text: str) -> QLabel:
        label = QLabel(text)
        label.setWordWrap(True)
        label.setProperty("sectionHint", True)
        return label

    def _emit(self, action: str, payload: str | None = None) -> None:
        if self._evidence_id is None:
            return
        if payload is not None:
            self.action_requested.emit(f"{action}:{payload}", self._evidence_id)
        else:
            self.action_requested.emit(action, self._evidence_id)


# ---------------------------------------------------------------------- page
class EvidencePage(ResponsivePage):
    """Evidence list and control panel for the active case."""

    examine_requested = Signal(int)  # database id of the evidence to examine

    def __init__(self, nav=None, parent: QWidget | None = None):
        self.nav = nav
        self.case_context: CaseContext | None = None
        self.evidence_service: EvidenceService | None = None
        self._all_evidence: list[Evidence] = []
        self._evidence_by_id: dict[int, Evidence] = {}
        self._file_states: dict[int, str] = {}
        self._threads: list[QThread] = []
        self._progress: QProgressDialog | None = None
        super().__init__(parent=parent)

    # ------------------------------------------------------------- layout
    def _setup_layout(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(Spacing.LG, Spacing.LG, Spacing.LG, Spacing.LG)
        layout.setSpacing(Spacing.MD)

        header_row = QHBoxLayout()
        title = QLabel("Evidence")
        title.setProperty("pageTitle", True)
        title.setFont(
            QFont(Typography.FONT_FAMILY, Typography.HEADING_LG[0], Typography.HEADING_LG[1])
        )
        header_row.addWidget(title)

        self.summary_label = QLabel("")
        self.summary_label.setProperty("sectionHint", True)
        header_row.addSpacing(Spacing.MD)
        header_row.addWidget(self.summary_label)
        header_row.addStretch()

        self.register_btn = QPushButton("Register Evidence")
        self.register_btn.clicked.connect(self._on_register)
        header_row.addWidget(self.register_btn)
        layout.addLayout(header_row)

        # Filters ---------------------------------------------------------
        filter_row = QHBoxLayout()
        filter_row.setSpacing(Spacing.SM)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Filter by ID, name or path…")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.setMaximumWidth(320)
        self.search_edit.textChanged.connect(self._apply_filters)
        filter_row.addWidget(self.search_edit)

        self.status_filter = QComboBox()
        for label, value in STATUS_FILTERS:
            self.status_filter.addItem(label, value)
        self.status_filter.currentIndexChanged.connect(self._apply_filters)
        filter_row.addWidget(self.status_filter)

        self.show_archived_check = QCheckBox("Archived")
        self.show_archived_check.setChecked(True)
        self.show_archived_check.setToolTip("Show archived items in the list.")
        self.show_archived_check.toggled.connect(self._apply_filters)
        filter_row.addWidget(self.show_archived_check)

        self.show_removed_check = QCheckBox("Removed")
        self.show_removed_check.setToolTip(
            "Show items that were removed from the case. They stay in the record."
        )
        self.show_removed_check.toggled.connect(self._apply_filters)
        filter_row.addWidget(self.show_removed_check)

        filter_row.addStretch()

        self.check_files_btn = QPushButton("Check files")
        self.check_files_btn.setProperty("secondary", True)
        self.check_files_btn.setToolTip(
            "Confirm that every stored file is still where the record says it is."
        )
        self.check_files_btn.clicked.connect(self._on_check_files)
        filter_row.addWidget(self.check_files_btn)

        self.manifest_btn = QPushButton("Export manifest")
        self.manifest_btn.setProperty("secondary", True)
        self.manifest_btn.setToolTip(
            "Write the case evidence list, with hashes and status, to CSV or JSON."
        )
        self.manifest_btn.clicked.connect(self._on_export_manifest)
        filter_row.addWidget(self.manifest_btn)
        layout.addLayout(filter_row)

        # Table + detail --------------------------------------------------
        splitter = QSplitter(Qt.Orientation.Horizontal)

        table_frame = QFrame()
        table_layout = QVBoxLayout(table_frame)
        table_layout.setContentsMargins(0, 0, 0, 0)
        table_layout.setSpacing(Spacing.XS)

        self.table_model = EvidenceTableModel(self)
        self.table_view = QTableView()
        self.table_view.setModel(self.table_model)
        self.table_view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table_view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table_view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table_view.setAlternatingRowColors(True)
        self.table_view.setSortingEnabled(False)
        self.table_view.verticalHeader().setVisible(False)
        self.table_view.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        self.table_view.horizontalHeader().setStretchLastSection(True)
        self.table_view.doubleClicked.connect(lambda _index: self._on_open_file())
        self.table_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table_view.customContextMenuRequested.connect(self._show_context_menu)
        self.table_view.selectionModel().selectionChanged.connect(self._on_selection_changed)
        table_layout.addWidget(self.table_view, 1)

        self.empty_hint = QLabel("No evidence matches the current filter.")
        self.empty_hint.setProperty("sectionHint", True)
        self.empty_hint.setVisible(False)
        table_layout.addWidget(self.empty_hint)

        splitter.addWidget(table_frame)

        self.detail_pane = EvidenceDetailPane()
        self.detail_pane.action_requested.connect(self._on_detail_action)
        splitter.addWidget(self.detail_pane)

        configure_detail_splitter(splitter, preferred_detail_width=380)
        layout.addWidget(splitter, 1)

    # ------------------------------------------------------------- context
    def set_case_context(self, context: CaseContext):
        self.case_context = context

    def set_evidence_service(self, service: EvidenceService):
        self.evidence_service = service

    def on_page_shown(self):
        self.refresh()

    def shutdown(self) -> None:
        """Wait for registration, verification, export or hashing to stop.

        Those threads write to the case store and the database, so they are
        given time to finish rather than being killed mid-copy.
        """
        for thread in list(self._threads):
            qt_threads.stop(thread, wait_ms=5000)

    def refresh(self):
        if not self.evidence_service or not self.case_context:
            return
        selected = [evidence_pk for evidence_pk, _ in self._selected_evidence()]
        self._all_evidence = self.evidence_service.get_evidence_by_case(
            self.case_context.case_id, include_removed=True
        )
        self._evidence_by_id = {item.id: item for item in self._all_evidence}
        self._file_states = self.evidence_service.check_files(self.case_context.case_id)
        self._apply_filters()
        self._reselect(selected)
        self._update_summary()

    # ------------------------------------------------------------- filters
    def _visible_evidence(self) -> list[Evidence]:
        text = self.search_edit.text().strip().lower()
        status_value = self.status_filter.currentData()
        show_archived = self.show_archived_check.isChecked()
        show_removed = self.show_removed_check.isChecked()

        visible = []
        for evidence in self._all_evidence:
            if evidence.is_removed and not show_removed:
                continue
            if evidence.status == EvidenceStatus.ARCHIVED and not show_archived:
                continue
            if status_value and evidence.status.value != status_value:
                continue
            if text:
                haystack = " ".join(
                    filter(
                        None,
                        (
                            evidence.evidence_id,
                            evidence.name,
                            evidence.source_path,
                            evidence.stored_path or "",
                        ),
                    )
                ).lower()
                if text not in haystack:
                    continue
            visible.append(evidence)
        return visible

    def _apply_filters(self):
        visible = self._visible_evidence()
        self.table_model.populate(visible, self._file_states)
        self.empty_hint.setVisible(not visible)
        self._on_selection_changed()

    def _update_summary(self):
        if not self.evidence_service or not self.case_context:
            return
        summary = self.evidence_service.case_storage(self.case_context.case_id)
        free = free_space_bytes(get_config().app.data_dir)
        parts = [
            f"{summary['items']} item(s)",
            f"{_format_size(summary['bytes'])} recorded",
        ]
        if summary["missing"]:
            parts.append(f"{summary['missing']} file(s) missing")
        if summary["archived"]:
            parts.append(f"{summary['archived']} archived")
        if summary["removed"]:
            parts.append(f"{summary['removed']} removed")
        if free is not None:
            parts.append(f"{_format_size(free)} free")
        self.summary_label.setText(" · ".join(parts))
        self.summary_label.setStyleSheet(
            f"color: {Color.ERROR.name()};" if summary["missing"]
            else f"color: {Color.TEXT_SECONDARY.name()};"
        )

    # ----------------------------------------------------------- selection
    def _selected_rows(self) -> list[int]:
        return sorted(
            {index.row() for index in self.table_view.selectionModel().selectedRows()}
        )

    def _selected_evidence(self) -> list[tuple[int, Evidence]]:
        selected = []
        for row in self._selected_rows():
            item = self.table_model.item(row, 0)
            if item is None:
                continue
            evidence_pk = item.data(Qt.ItemDataRole.UserRole)
            evidence = self._evidence_by_id.get(evidence_pk)
            if evidence is not None:
                selected.append((evidence_pk, evidence))
        return selected

    def _single_selection(self) -> Evidence | None:
        selected = self._selected_evidence()
        return selected[0][1] if len(selected) == 1 else None

    def _reselect(self, evidence_pks: list[int]) -> None:
        if not evidence_pks:
            return
        selection = self.table_view.selectionModel()
        for row in range(self.table_model.rowCount()):
            item = self.table_model.item(row, 0)
            if item and item.data(Qt.ItemDataRole.UserRole) in evidence_pks:
                selection.select(
                    self.table_model.index(row, 0),
                    selection.SelectionFlag.Select | selection.SelectionFlag.Rows,
                )

    def _on_selection_changed(self, *_args):
        pane = getattr(self, "detail_pane", None)
        if pane is None:  # selection cannot change before the layout is built
            return
        evidence = self._single_selection()
        if evidence is None:
            pane.set_evidence(None, EvidenceService.STORED_MISSING, [])
            return
        pane.set_evidence(
            evidence,
            self._file_states.get(evidence.id, EvidenceService.STORED_MISSING),
            self.evidence_service.stored_parts(evidence) if self.evidence_service else [],
        )

    # --------------------------------------------------------------- users
    def _current_user(self):
        """The signed-in investigator, or ``None``.

        There is deliberately no fallback to "the first user in the database":
        attributing a removal or a deletion to the wrong account would falsify
        the custody trail, so a page without a signed-in user simply refuses.
        """
        nav = getattr(self, "nav", None)
        getter = getattr(nav, "get_current_user", None)
        if callable(getter):
            try:
                return getter()
            except Exception:  # noqa: BLE001 - treated as not signed in
                return None
        return None

    def _require_user(self):
        user = self._current_user()
        if user is None:
            QMessageBox.warning(
                self,
                "No investigator",
                "A signed-in investigator is required to change evidence.",
            )
        return user

    # ------------------------------------------------------------ context menu
    def _show_context_menu(self, position) -> None:
        index = self.table_view.indexAt(position)
        if not index.isValid():
            return
        if index.row() not in self._selected_rows():
            self.table_view.selectRow(index.row())

        evidence = self._single_selection()
        selection = self._selected_evidence()
        menu = QMenu(self)

        if evidence is not None:
            menu.addAction("Open file", self._on_open_file)
            menu.addAction("Open file location", self._on_open_folder)
            menu.addSeparator()
            copy_menu = menu.addMenu("Copy")
            stored = evidence.stored_path or evidence.source_path
            copy_menu.addAction("Stored path", lambda: self._copy(stored))
            copy_menu.addAction("Source path", lambda: self._copy(evidence.source_path))
            copy_menu.addAction("Evidence ID", lambda: self._copy(evidence.evidence_id))
            sha = next(
                (item.hash_value for item in evidence.hashes
                 if item.algorithm == HashAlgorithm.SHA256),
                "",
            )
            copy_action = copy_menu.addAction(
                "SHA-256", lambda: self._copy(sha)
            )
            copy_action.setEnabled(bool(sha))
            menu.addSeparator()

        verify = menu.addAction(
            f"Verify {len(selection)} item(s)" if len(selection) > 1 else "Verify integrity",
            self._on_verify,
        )
        verify.setEnabled(bool(selection))
        export = menu.addAction("Export copy…", self._on_export)
        export.setEnabled(
            evidence is not None
            and self._file_states.get(evidence.id) != EvidenceService.STORED_MISSING
        )
        reference = menu.addAction("Set reference hash…", self._on_set_reference_hash)
        reference.setEnabled(evidence is not None)
        edit = menu.addAction("Edit details…", self._on_edit_details)
        edit.setEnabled(evidence is not None)

        if evidence is not None:
            menu.addSeparator()
            if evidence.status == EvidenceStatus.ARCHIVED:
                menu.addAction("Restore from archive", self._on_archive)
            else:
                menu.addAction("Archive", self._on_archive)
            examine = menu.addAction("Start examination", self._on_examine)
            examine.setEnabled(
                not evidence.is_removed and evidence.status != EvidenceStatus.ARCHIVED
            )
            menu.addSeparator()
            if evidence.is_removed:
                menu.addAction("Return to case", self._on_return)
            else:
                menu.addAction("Remove from case…", self._on_remove)
            delete = menu.addAction("Delete permanently…", self._on_delete)
            delete.setEnabled(evidence is not None)
        else:
            menu.addSeparator()
            remove = menu.addAction(
                f"Remove {len(selection)} item(s) from case…", self._on_remove
            )
            remove.setEnabled(bool(selection))

        menu.exec(self.table_view.viewport().mapToGlobal(position))

    # ------------------------------------------------------------- register
    def _on_register(self):
        if not self.case_context or not self.evidence_service:
            return
        dialog = RegisterEvidenceDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        data = dialog.get_data()
        if not data["name"] or not data["source_path"]:
            QMessageBox.warning(self, "Validation Error", "Name and source file are required")
            return
        user = self._require_user()
        if user is None:
            return

        self.register_btn.setEnabled(False)
        self._open_progress("Registering Evidence", "Preparing…")
        self._register_thread = _RegisterEvidenceThread(
            self.case_context.case_id, data, user.id
        )
        self._register_thread.progress.connect(
            lambda message, percent: self._set_progress(message, percent)
        )
        self._register_thread.registered.connect(self._registration_complete)
        self._register_thread.failed.connect(self._registration_failed)
        self._track(self._register_thread)
        self._register_thread.start()

    def _registration_complete(self, evidence_id: str):
        self._close_progress()
        self.register_btn.setEnabled(True)
        self._expire()
        QMessageBox.information(self, "Evidence Registered", f"Evidence registered: {evidence_id}")

    def _registration_failed(self, error: str):
        self._close_progress()
        self.register_btn.setEnabled(True)
        QMessageBox.critical(self, "Registration Failed", error)

    # --------------------------------------------------------------- verify
    def _on_verify(self):
        selection = self._selected_evidence()
        if not selection:
            QMessageBox.warning(self, "No Selection", "Select evidence to verify")
            return
        user = self._require_user()
        if user is None:
            return

        self._open_progress(
            "Verifying Integrity",
            f"Hashing {len(selection)} item(s)…",
            cancelable=True,
        )
        self._verify_thread = _VerifyThread([pk for pk, _ in selection], user.id)
        self._verify_thread.progress.connect(
            lambda message, percent: self._set_progress(message, percent)
        )
        self._verify_thread.done.connect(self._verification_complete)
        self._verify_thread.failed.connect(self._verification_failed)
        self._track(self._verify_thread)
        self._verify_thread.start()

    def _verification_complete(self, results: list[tuple[str, bool, str]]):
        self._close_progress()
        self._expire()
        if not results:
            QMessageBox.information(self, "Verification", "Nothing to verify.")
            return
        lines = [
            f"{reference}: {'PASS' if passed else 'FAIL'} — {detail}"
            for reference, passed, detail in results
        ]
        passed_all = all(passed for _, passed, _ in results)
        message = "\n".join(lines)
        if passed_all:
            QMessageBox.information(self, "Verification Passed", message)
        else:
            QMessageBox.warning(self, "Verification Failed", message)

    def _verification_failed(self, error: str):
        self._close_progress()
        QMessageBox.critical(self, "Verification Failed", error)

    # -------------------------------------------------------------- archive
    def _on_archive(self):
        evidence = self._single_selection()
        if evidence is None:
            QMessageBox.information(self, "Select Evidence", "Select one evidence record first.")
            return
        restoring = evidence.status == EvidenceStatus.ARCHIVED
        action = "Restore" if restoring else "Archive"
        prompt = (
            f"{action} {evidence.evidence_id} — {evidence.name}?\n\n"
            + ("It becomes available for examination again."
               if restoring else
               "The record, hashes, custody trail and stored files are retained.")
        )
        answer = QMessageBox.question(
            self, f"{action} Evidence", prompt,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        user = self._require_user()
        if user is None:
            return
        service = self.evidence_service
        try:
            changed = (
                service.restore_evidence(evidence.id, user) if restoring
                else service.archive_evidence(evidence.id, user)
            )
            service.session.commit()
            if changed:
                self._expire()
        except Exception as exc:  # noqa: BLE001 - surfaced to the investigator
            service.session.rollback()
            QMessageBox.critical(self, "Evidence Action Failed", str(exc))

    # -------------------------------------------------------------- examine
    def _on_examine(self):
        evidence = self._single_selection()
        if evidence is None:
            QMessageBox.warning(self, "No Selection", "Select evidence to examine")
            return
        if evidence.is_removed or evidence.status == EvidenceStatus.ARCHIVED:
            QMessageBox.information(
                self, "Not available",
                "Return or restore this item before examining it.",
            )
            return
        self.examine_requested.emit(evidence.id)

    # ----------------------------------------------------------- open/copy
    def _on_detail_action(self, action: str, evidence_pk: int) -> None:
        if action.startswith("open_folder:"):
            self._open_folder(action.split(":", 1)[1])
        elif action.startswith("open_file:"):
            self._open_path(action.split(":", 1)[1])
        elif action.startswith("copy:"):
            self._copy(action.split(":", 1)[1])
        elif action == "verify":
            self._on_verify()
        elif action == "export":
            self._on_export()
        elif action == "reference_hash":
            self._on_set_reference_hash()
        elif action == "edit":
            self._on_edit_details()
        elif action == "remove":
            self._on_remove()
        elif action == "return":
            self._on_return()
        elif action == "delete":
            self._on_delete()

    def _on_open_folder(self):
        evidence = self._single_selection()
        if evidence is None:
            return
        self._open_folder(evidence.stored_path or evidence.source_path)

    def _on_open_file(self):
        evidence = self._single_selection()
        if evidence is None:
            return
        path = evidence.stored_path or evidence.source_path
        if not Path(path).is_file():
            QMessageBox.warning(
                self, "File missing",
                f"{path}\n\nThis record points at a file that is no longer there.",
            )
            return
        safe = (evidence.mime_type or "").startswith(SAFE_PREVIEW_MIME_PREFIXES) or (
            evidence.mime_type in SAFE_PREVIEW_MIME_TYPES
        )
        if not safe:
            # A disk image or an unknown binary opens its folder: launching it
            # would hand the evidence to whatever is associated with the suffix.
            self._open_folder(path)
            return
        self._open_path(path)

    @staticmethod
    def _open_folder(path: str) -> None:
        target = Path(path)
        try:
            if target.is_file():
                subprocess.Popen(["explorer", "/select,", str(target)])
            else:
                folder = target if target.is_dir() else target.parent
                os.startfile(folder)  # noqa: S606 - opening a folder is the intent
        except OSError as exc:
            QMessageBox.warning(None, "Could not open", f"{target}\n\n{exc}")

    @staticmethod
    def _open_path(path: str) -> None:
        try:
            os.startfile(path)  # noqa: S606 - the investigator asked to open it
        except OSError as exc:
            QMessageBox.warning(None, "Could not open", f"{path}\n\n{exc}")

    def _copy(self, value: str) -> None:
        if not value:
            return
        from PySide6.QtWidgets import QApplication

        QApplication.clipboard().setText(value)

    # --------------------------------------------------------------- export
    def _on_export(self):
        evidence = self._single_selection()
        if evidence is None:
            QMessageBox.information(self, "Select Evidence", "Select one evidence record first.")
            return
        if self._file_states.get(evidence.id) == EvidenceService.STORED_MISSING:
            QMessageBox.warning(
                self, "Nothing to export",
                "The file for this record is missing, so there is nothing to copy.",
            )
            return
        user = self._require_user()
        if user is None:
            return

        destination = QFileDialog.getExistingDirectory(
            self, "Export a verified copy to…"
        )
        if not destination:
            return

        self._open_progress("Exporting Evidence", "Copying…", cancelable=True)
        self._export_thread = _ExportThread(evidence.id, destination, user.id)
        self._export_thread.progress.connect(
            lambda message, percent: self._set_progress(message, percent)
        )
        self._export_thread.done.connect(self._export_complete)
        self._export_thread.failed.connect(self._export_failed)
        self._track(self._export_thread)
        self._export_thread.start()

    def _export_complete(self, result: dict):
        self._close_progress()
        self._expire()
        verified = result.get("verified")
        if verified is True:
            outcome = "The copy matches the reference hash."
        elif verified is False:
            outcome = "WARNING: the copy does not match the reference hash."
        else:
            outcome = "No reference hash exists, so the copy was not checked."
        message = (
            f"{len(result['files'])} file(s) exported to:\n{result['destination']}\n\n"
            f"{outcome}"
        )
        if verified is False:
            QMessageBox.warning(self, "Export finished with a mismatch", message)
        else:
            QMessageBox.information(self, "Export complete", message)

    def _export_failed(self, error: str):
        self._close_progress()
        QMessageBox.critical(self, "Export Failed", error)

    # ------------------------------------------------------- reference hash
    def _on_set_reference_hash(self):
        evidence = self._single_selection()
        if evidence is None:
            QMessageBox.information(self, "Select Evidence", "Select one evidence record first.")
            return
        if self._file_states.get(evidence.id) == EvidenceService.STORED_MISSING:
            QMessageBox.warning(
                self, "File missing",
                "The stored file is missing, so a reference hash cannot be checked against it.",
            )
            return
        dialog = ReferenceHashDialog(evidence, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        data = dialog.get_data()
        user = self._require_user()
        if user is None:
            return

        self._open_progress(
            "Checking Reference Hash", "Hashing the stored copy…", cancelable=True
        )
        self._hash_thread = _ReferenceHashThread(
            evidence.id, data["algorithm"], data["value"], data["note"], user.id
        )
        self._hash_thread.progress.connect(
            lambda message, percent: self._set_progress(message, percent)
        )
        self._hash_thread.done.connect(self._reference_hash_complete)
        self._hash_thread.failed.connect(
            lambda error: (self._close_progress(),
                           QMessageBox.critical(self, "Hash Check Failed", error))
        )
        self._track(self._hash_thread)
        self._hash_thread.start()

    def _reference_hash_complete(self, results: dict):
        self._close_progress()
        self._expire()
        if not results:
            return
        lines = [
            f"{algorithm.upper()}: {'MATCH' if matched else 'MISMATCH'}"
            for algorithm, matched in results.items()
        ]
        passed = all(results.values())
        message = "\n".join(lines)
        if passed:
            QMessageBox.information(self, "Reference hash recorded", message)
        else:
            QMessageBox.warning(
                self, "Reference hash does not match",
                message + "\n\nThe stored copy does not match the hash you entered.",
            )

    # -------------------------------------------------------------- editing
    def _on_edit_details(self):
        evidence = self._single_selection()
        if evidence is None:
            QMessageBox.information(self, "Select Evidence", "Select one evidence record first.")
            return
        dialog = EditDetailsDialog(evidence, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        data = dialog.get_data()
        user = self._require_user()
        if user is None:
            return
        service = self.evidence_service
        try:
            service.update_details(
                evidence.id, data["name"], data["description"], user
            )
            service.session.commit()
            self._expire()
        except Exception as exc:  # noqa: BLE001 - surfaced to the investigator
            service.session.rollback()
            QMessageBox.critical(self, "Could not save", str(exc))

    # -------------------------------------------------------------- removal
    def _on_remove(self):
        selection = self._selected_evidence()
        if not selection:
            QMessageBox.information(self, "Select Evidence", "Select evidence to remove.")
            return
        active = [(pk, item) for pk, item in selection if not item.is_removed]
        if not active:
            QMessageBox.information(self, "Already removed", "That item is already removed.")
            return

        if len(active) == 1:
            dialog = RemoveEvidenceDialog(active[0][1], self)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            reason = dialog.get_reason()
        else:
            answer = QMessageBox.question(
                self,
                "Remove from case",
                f"Remove {len(active)} items from the case?\n\n"
                "Records, hashes, custody history and files are kept, and the "
                "items can be returned later.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
            reason = "removed from the evidence list"

        user = self._require_user()
        if user is None:
            return
        service = self.evidence_service
        removed = 0
        try:
            for evidence_pk, _item in active:
                if service.remove_evidence(evidence_pk, user, reason):
                    removed += 1
            service.session.commit()
        except Exception as exc:  # noqa: BLE001 - surfaced to the investigator
            service.session.rollback()
            QMessageBox.critical(self, "Could not remove", str(exc))
            return
        self._expire()
        QMessageBox.information(
            self, "Removed", f"{removed} item(s) removed from the case. Use the "
            "Removed filter to see them."
        )

    def _on_return(self):
        evidence = self._single_selection()
        if evidence is None or not evidence.is_removed:
            return
        user = self._require_user()
        if user is None:
            return
        service = self.evidence_service
        try:
            service.return_evidence(evidence.id, user)
            service.session.commit()
        except Exception as exc:  # noqa: BLE001 - surfaced to the investigator
            service.session.rollback()
            QMessageBox.critical(self, "Could not return", str(exc))
            return
        self._expire()

    def _on_delete(self):
        evidence = self._single_selection()
        if evidence is None:
            QMessageBox.information(self, "Select Evidence", "Select one evidence record first.")
            return
        service = self.evidence_service
        files = service.case_store_files(evidence)
        blockers = service.deletion_blockers(evidence)
        impact = service.deletion_impact(evidence)
        # Captured before the row is deleted: the instance is detached once the
        # delete is committed, so reading a field afterwards would raise.
        reference = evidence.evidence_id

        dialog = DeleteEvidenceDialog(
            evidence, files, blockers, self, impact=impact
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        user = self._require_user()
        if user is None:
            return
        try:
            result = service.delete_evidence(evidence.id, user, dialog.get_reason())
            service.session.commit()
        except Exception as exc:  # noqa: BLE001 - surfaced to the investigator
            service.session.rollback()
            QMessageBox.critical(self, "Could not delete", str(exc))
            return
        self._expire()
        QMessageBox.information(
            self, "Deleted",
            f"{reference} deleted.\n\n"
            f"{result['files']} file(s) removed from the case store, "
            f"{_format_size(result['bytes'])} freed.\n"
            f"Also deleted {result['jobs']} examination job(s) and "
            f"{result['artifacts']} artifact(s).",
        )

    # --------------------------------------------------------- transparency
    def _on_check_files(self):
        if not self.evidence_service or not self.case_context:
            return
        self._file_states = self.evidence_service.check_files(self.case_context.case_id)
        self._apply_filters()
        self._update_summary()

        missing = [
            evidence.evidence_id
            for evidence in self._all_evidence
            if self._file_states.get(evidence.id) == EvidenceService.STORED_MISSING
        ]
        if missing:
            QMessageBox.warning(
                self, "Files missing",
                "These items point at files that are not on disk:\n\n"
                + "\n".join(missing),
            )
        else:
            QMessageBox.information(
                self, "All files present",
                "Every evidence record points at a file that exists.",
            )

    def _on_export_manifest(self):
        if not self.evidence_service or not self.case_context:
            return
        path, selected_filter = QFileDialog.getSaveFileName(
            self,
            "Export evidence manifest",
            f"evidence_manifest_{self.case_context.case_id_str}.csv",
            "CSV file (*.csv);;JSON file (*.json)",
        )
        if not path:
            return

        rows = self.evidence_service.case_manifest(self.case_context.case_id)
        if not rows:
            QMessageBox.information(
                self, "Nothing to export",
                "This case has no evidence records, so there is no manifest to write.",
            )
            return
        target = Path(path)
        try:
            if target.suffix.lower() == ".json" or "json" in selected_filter.lower():
                target.write_text(json.dumps(rows, indent=2), encoding="utf-8")
            else:
                flat_rows = [
                    {
                        **{key: value for key, value in row.items() if key != "hashes"},
                        "hashes": "; ".join(
                            f"{algorithm}:{value}"
                            for algorithm, value in row["hashes"].items()
                        ),
                    }
                    for row in rows
                ]
                with target.open("w", newline="", encoding="utf-8") as handle:
                    writer = csv.DictWriter(handle, fieldnames=list(flat_rows[0]))
                    writer.writeheader()
                    writer.writerows(flat_rows)
        except Exception as exc:  # noqa: BLE001 - surfaced to the investigator
            QMessageBox.critical(self, "Could not write manifest", str(exc))
            return
        QMessageBox.information(
            self, "Manifest written", f"{len(rows)} item(s) written to:\n{target}"
        )

    # ------------------------------------------------------------- progress
    def _open_progress(
        self, title: str, message: str, cancelable: bool = False
    ) -> QProgressDialog:
        self._close_progress()
        progress = QProgressDialog(message, "Cancel" if cancelable else "", 0, 100, self)
        progress.setWindowTitle(title)
        progress.setWindowModality(Qt.WindowModality.NonModal)
        # QProgressDialog may retain and style an empty Cancel button even when
        # constructed with an empty label (it appears as a blank outlined box).
        if not cancelable:
            progress.setCancelButton(None)
        progress.setMinimumWidth(360)
        progress.setMinimumDuration(0)
        progress.setAutoClose(False)
        progress.setAutoReset(False)
        if cancelable:
            progress.canceled.connect(self._cancel_current_thread)
        progress.show()
        self._progress = progress
        return progress

    def _set_progress(self, message: str, percent: int) -> None:
        if self._progress is None:
            return
        self._progress.setLabelText(f"{message}… {percent}%")
        self._progress.setValue(percent)

    def _close_progress(self) -> None:
        if self._progress is not None:
            self._progress.close()
            self._progress.deleteLater()
            self._progress = None

    def _cancel_current_thread(self) -> None:
        """Ask the running worker to stop between items, then close the dialog."""
        self._close_progress()

    def _track(self, thread: QThread) -> None:
        """Keep a worker alive until it finishes.

        A QThread destroyed while running aborts the process, so the page holds
        a reference and drops it only once the thread has reported completion.
        """
        self._threads.append(thread)
        qt_threads.track(thread)
        thread.finished.connect(lambda: self._forget(thread))

    def _forget(self, thread: QThread) -> None:
        if thread in self._threads:
            self._threads.remove(thread)
        thread.deleteLater()

    def _expire(self) -> None:
        if self.evidence_service:
            self.evidence_service.session.expire_all()
        self.refresh()
