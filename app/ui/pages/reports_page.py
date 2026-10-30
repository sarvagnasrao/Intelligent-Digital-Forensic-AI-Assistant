"""Reports Page."""
from __future__ import annotations

import html
import json
import os
import re
import shutil
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QThread, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QFont, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from app.reports.models import Report
from app.reports.templates import (
    BUILTIN_DEFAULT_ID,
    SECTION_LABELS,
    ReportTemplate,
    TemplateError,
)
from app.ui import qt_threads
from app.ui.base import CaseContext, ResponsivePage
from app.ui.theme.tokens import Color, Spacing, Typography
from app.util.time import format_local_date

if TYPE_CHECKING:
    from app.auth.models import User
    from app.reports.service import ReportService

TEMPLATE_FILTER = (
    "Report templates (*.json *.docx *.html *.htm *.txt *.md);;"
    "IDFA template (*.json);;Word template (*.docx);;"
    "Web/text template (*.html *.htm *.txt *.md)"
)


class ReportTableModel(QStandardItemModel):
    HEADERS = ["Report ID", "Title", "Template", "Status", "Generated", "Size"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setHorizontalHeaderLabels(self.HEADERS)

    def populate(self, reports: list[Report]):
        self.removeRows(0, self.rowCount())
        for report in reports:
            size_str = self._format_size(report.file_size_bytes) if report.file_size_bytes else "—"
            row = [
                QStandardItem(report.report_id),
                QStandardItem(report.title),
                QStandardItem(self._template_name(report)),
                QStandardItem(report.status.value.replace("_", " ").title()),
                QStandardItem(format_local_date(report.generated_at) if report.generated_at else ""),
                QStandardItem(size_str),
            ]
            for item in row:
                item.setEditable(False)
            if report.error_message:
                row[3].setToolTip(report.error_message)
            self.appendRow(row)

    @staticmethod
    def _template_name(report: Report) -> str:
        try:
            data = json.loads(report.included_sections_json or "{}")
        except (TypeError, ValueError):
            return "—"
        if isinstance(data, dict):
            return str(data.get("template_name") or "—")
        return "—"

    @staticmethod
    def _format_size(bytes_val: int) -> str:
        value = float(bytes_val)
        for unit in ["B", "KB", "MB", "GB"]:
            if value < 1024:
                return f"{value:.1f} {unit}"
            value /= 1024
        return f"{value:.1f} TB"


def _clear_layout(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.deleteLater()


class ReportGenerateDialog(QDialog):
    """Dialog for choosing a template, title and sections before generation."""

    def __init__(
        self,
        templates: list[ReportTemplate],
        selected_template_id: str = "",
        service: "ReportService | None" = None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Generate Report")
        self.setModal(True)
        self.resize(560, 640)

        self.service = service
        self.templates = list(templates)
        self.templates_changed = False
        self.sections: dict[str, QCheckBox] = {}

        layout = QVBoxLayout(self)
        layout.setSpacing(Spacing.MD)
        layout.setContentsMargins(Spacing.LG, Spacing.LG, Spacing.LG, Spacing.LG)

        title_label = QLabel("Report title")
        title_label.setFont(QFont(Typography.FONT_FAMILY, Typography.BODY_MD[0], Typography.BODY_MD[1]))
        layout.addWidget(title_label)

        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("Forensic Examination Report")
        layout.addWidget(self.title_edit)

        template_label = QLabel("Report template")
        template_label.setFont(QFont(Typography.FONT_FAMILY, Typography.BODY_MD[0], Typography.BODY_MD[1]))
        layout.addWidget(template_label)

        template_row = QHBoxLayout()
        self.template_combo = QComboBox()
        self.template_combo.setToolTip(
            "Choose a layout and review its sections. Admissibility is not guaranteed; "
            "investigator and legal review under applicable jurisdiction rules is required."
        )
        template_row.addWidget(self.template_combo, 1)

        self.upload_btn = QPushButton("Upload Template…")
        self.upload_btn.setProperty("secondary", True)
        self.upload_btn.clicked.connect(self._on_upload_template)
        self.upload_btn.setEnabled(self.service is not None)
        template_row.addWidget(self.upload_btn)
        layout.addLayout(template_row)

        self.template_info = QLabel()
        self.template_info.setWordWrap(True)
        self.template_info.setStyleSheet(f"color: {Color.TEXT_SECONDARY.name()};")
        layout.addWidget(self.template_info)

        self.sections_group = QGroupBox("Sections to include")
        group_layout = QVBoxLayout(self.sections_group)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumHeight(190)
        self.sections_host = QWidget()
        self.sections_layout = QVBoxLayout(self.sections_host)
        self.sections_layout.setContentsMargins(4, 4, 4, 4)
        self.sections_layout.setSpacing(Spacing.XS)
        scroll.setWidget(self.sections_host)
        group_layout.addWidget(scroll)
        layout.addWidget(self.sections_group, 1)

        note = QLabel(
            "Sections are supplied by the selected template. Uploading a template "
            "keeps a copy in the case data folder so the same layout can be reused."
        )
        note.setWordWrap(True)
        note.setStyleSheet(f"color: {Color.TEXT_MUTED.name()};")
        layout.addWidget(note)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.template_combo.currentIndexChanged.connect(self._on_template_changed)
        self._populate_templates(selected_template_id)

    # ----------------------------------------------------------- templates
    def _populate_templates(self, selected_template_id: str = "") -> None:
        self.template_combo.blockSignals(True)
        self.template_combo.clear()
        selected_index = 0
        for index, template in enumerate(self.templates):
            label = template.name + ("  (default)" if template.template_id == BUILTIN_DEFAULT_ID else "")
            self.template_combo.addItem(label, template.template_id)
            if template.template_id == selected_template_id:
                selected_index = index
        self.template_combo.setCurrentIndex(selected_index if self.templates else -1)
        self.template_combo.blockSignals(False)
        self._on_template_changed()

    def _selected_template(self) -> ReportTemplate | None:
        index = self.template_combo.currentIndex()
        if 0 <= index < len(self.templates):
            return self.templates[index]
        return None

    def _on_template_changed(self, *_args) -> None:
        template = self._selected_template()
        if template is None:
            return
        source = template.source_label
        self.template_info.setText(
            f"{template.description}\n\n"
            f"Organisation: {template.organization}  ·  Jurisdiction: {template.jurisdiction}\n"
            f"Source: {source}"
        )
        if not self.title_edit.text().strip():
            self.title_edit.setPlaceholderText(template.report_type)
        self._rebuild_sections(template)

    def _rebuild_sections(self, template: ReportTemplate) -> None:
        _clear_layout(self.sections_layout)
        self.sections = {}
        for key in template.sections:
            label = SECTION_LABELS.get(key, key)
            checkbox = QCheckBox(label)
            checkbox.setChecked(True)
            if key == "cover":
                checkbox.setEnabled(False)
                checkbox.setToolTip("A report must start with a cover page.")
            if key == "integrity":
                checkbox.setToolTip(
                    "Reference hashes let the court verify that evidence has not changed."
                )
            if key == "certification":
                checkbox.setToolTip(
                    "The certification and signature page carries the examiner's declaration."
                )
            self.sections[key] = checkbox
            self.sections_layout.addWidget(checkbox)
        self.sections_layout.addStretch()

    def _on_upload_template(self) -> None:
        if self.service is None:
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Upload Report Template", "", TEMPLATE_FILTER
        )
        if not path:
            return
        try:
            template = self.service.import_template(path)
        except TemplateError as exc:
            QMessageBox.warning(self, "Template not accepted", str(exc))
            return
        except Exception as exc:  # unexpected IO/DB problem
            QMessageBox.critical(self, "Upload failed", f"Could not load the template:\n{exc}")
            return

        self.templates_changed = True
        try:
            self.templates = self.service.list_templates()
        except Exception:
            self.templates = [template]
        self._populate_templates(template.template_id)
        QMessageBox.information(
            self,
            "Template loaded",
            f"'{template.name}' was validated and saved.\n\n"
            f"Stored in: {template.source_path}",
        )

    def get_data(self) -> dict:
        template = self._selected_template()
        return {
            "title": self.title_edit.text().strip()
            or (template.report_type if template else "Forensic Examination Report"),
            "sections": [key for key, box in self.sections.items() if box.isChecked()],
            "template_id": template.template_id if template else "",
        }


class ReportTemplatesDialog(QDialog):
    """Manage the built-in court template and investigator uploads."""

    def __init__(
        self,
        service: "ReportService",
        selected_template_id: str = "",
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Report Templates")
        self.setModal(True)
        self.resize(820, 560)
        self.service = service
        self.templates: list[ReportTemplate] = []
        self.templates_changed = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(Spacing.LG, Spacing.LG, Spacing.LG, Spacing.LG)
        layout.setSpacing(Spacing.MD)

        heading = QLabel("Report Templates")
        heading.setFont(QFont(
            Typography.FONT_FAMILY, Typography.HEADING_MD[0], Typography.HEADING_MD[1]
        ))
        layout.addWidget(heading)

        intro = QLabel(
            "Choose a built-in layout or upload your laboratory's template. Investigator "
            "and legal review under the applicable jurisdiction's rules is required; "
            "admissibility is not guaranteed. Placeholders such as {{case_id}} are filled in automatically."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet(f"color: {Color.TEXT_SECONDARY.name()};")
        layout.addWidget(intro)

        body = QHBoxLayout()
        body.setSpacing(Spacing.MD)

        left = QVBoxLayout()
        self.template_list = QListWidget()
        self.template_list.setAlternatingRowColors(True)
        self.template_list.currentItemChanged.connect(self._on_selection_changed)
        left.addWidget(self.template_list, 1)

        button_row = QHBoxLayout()
        self.upload_btn = QPushButton("Upload…")
        self.upload_btn.setProperty("secondary", True)
        self.upload_btn.clicked.connect(self._on_upload)
        button_row.addWidget(self.upload_btn)

        self.save_btn = QPushButton("Save As…")
        self.save_btn.setProperty("secondary", True)
        self.save_btn.clicked.connect(self._on_save)
        button_row.addWidget(self.save_btn)

        self.delete_btn = QPushButton("Delete")
        self.delete_btn.setProperty("danger", True)
        self.delete_btn.clicked.connect(self._on_delete)
        button_row.addWidget(self.delete_btn)
        button_row.addStretch()
        left.addLayout(button_row)
        body.addLayout(left, 1)

        details_group = QGroupBox("Template details")
        details_layout = QVBoxLayout(details_group)
        details_scroll = QScrollArea()
        details_scroll.setWidgetResizable(True)
        details_scroll.setFrameShape(QFrame.Shape.NoFrame)
        details_host = QWidget()
        details_host_layout = QVBoxLayout(details_host)
        details_host_layout.setContentsMargins(0, 0, 0, 0)
        self.details = QLabel()
        self.details.setWordWrap(True)
        self.details.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.details.setTextFormat(Qt.TextFormat.RichText)
        self.details.setOpenExternalLinks(False)
        details_host_layout.addWidget(self.details)
        details_host_layout.addStretch()
        details_scroll.setWidget(details_host)
        details_layout.addWidget(details_scroll)
        body.addWidget(details_group, 1)

        layout.addLayout(body, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._refresh(selected_template_id)

    # --------------------------------------------------------------- helpers
    def _refresh(self, selected_template_id: str = "") -> None:
        try:
            self.templates = self.service.list_templates()
        except Exception as exc:
            QMessageBox.critical(self, "Templates unavailable", str(exc))
            self.templates = []
        self._selected_id = selected_template_id or (
            self.templates[0].template_id if self.templates else ""
        )
        self._rebuild_list()
        self._update_details()

    def _rebuild_list(self) -> None:
        self.template_list.blockSignals(True)
        self.template_list.clear()
        selected_row = 0
        for row, template in enumerate(self.templates):
            suffix = "built-in" if template.builtin else "uploaded"
            item = QListWidgetItem(f"{template.name}  ·  {suffix}")
            item.setData(Qt.ItemDataRole.UserRole, template.template_id)
            item.setToolTip(template.description)
            self.template_list.addItem(item)
            if template.template_id == self._selected_id:
                selected_row = row
        self.template_list.blockSignals(False)
        if self.templates:
            self.template_list.setCurrentRow(selected_row)

    def _on_selection_changed(self, current: QListWidgetItem | None, _previous=None) -> None:
        if current is None:
            return
        self._selected_id = str(current.data(Qt.ItemDataRole.UserRole) or "")
        self._update_details()

    def _selected_template(self) -> ReportTemplate | None:
        for template in self.templates:
            if template.template_id == self._selected_id:
                return template
        return self.templates[0] if self.templates else None

    def _update_details(self) -> None:
        template = self._selected_template()
        if template is None:
            self.details.setText("No templates available.")
            self.save_btn.setEnabled(False)
            self.delete_btn.setEnabled(False)
            return

        included = [
            f"<li>{html.escape(SECTION_LABELS.get(key, key))}</li>"
            for key in template.sections
        ]
        missing_core = [
            SECTION_LABELS.get(key, key)
            for key in ("cover", "authority_scope", "examiner_declaration", "methodology",
                        "evidence", "limitations", "certification", "integrity")
            if key not in template.sections
        ]
        warning = ""
        if missing_core:
            warning = (
                "<p style='color:#f59e0b;'><b>Court checklist:</b> this template omits "
                + html.escape(", ".join(missing_core))
                + ". Review which sections are needed for the intended purpose.</p>"
            )
        self.details.setText(
            f"<p><b>{html.escape(template.name)}</b><br>"
            f"{html.escape(template.description)}</p>"
            f"<p><b>Organisation:</b> {html.escape(template.organization)}<br>"
            f"<b>Jurisdiction:</b> {html.escape(template.jurisdiction)}<br>"
            f"<b>Report type:</b> {html.escape(template.report_type)}<br>"
            f"<b>Classification:</b> {html.escape(template.classification)}<br>"
            f"<b>Prepared for:</b> {html.escape(template.prepared_for)}</p>"
            f"<p><b>Source:</b> {html.escape(template.source_label)}</p>"
            f"{warning}"
            f"<p><b>Sections in this template</b></p><ul>{''.join(included)}</ul>"
        )
        self.save_btn.setEnabled(True)
        self.delete_btn.setEnabled(not template.builtin)
        self.delete_btn.setToolTip(
            "Built-in templates cannot be deleted."
            if template.builtin else "Delete this uploaded template."
        )

    # --------------------------------------------------------------- actions
    def _on_upload(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Upload Report Template", "", TEMPLATE_FILTER
        )
        if not path:
            return
        try:
            template = self.service.import_template(path)
        except TemplateError as exc:
            QMessageBox.warning(self, "Template not accepted", str(exc))
            return
        except Exception as exc:
            QMessageBox.critical(self, "Upload failed", f"Could not load the template:\n{exc}")
            return
        self.templates_changed = True
        self._refresh(template.template_id)
        QMessageBox.information(
            self, "Template loaded",
            f"'{template.name}' was validated and saved.\n\nStored in: {template.source_path}",
        )

    def _on_save(self) -> None:
        template = self._selected_template()
        if template is None:
            return
        suggested = re.sub(r"[^A-Za-z0-9_-]+", "-", template.name).strip("-") or "report-template"
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Report Template", f"{suggested}.json", "IDFA template (*.json)"
        )
        if not path:
            return
        try:
            written = self.service.export_template(template.template_id, path)
        except Exception as exc:
            QMessageBox.critical(self, "Save failed", f"Could not save the template:\n{exc}")
            return
        QMessageBox.information(
            self, "Template saved",
            f"Template written to:\n{written}\n\nEdit the JSON and upload it to reuse it.",
        )

    def _on_delete(self) -> None:
        template = self._selected_template()
        if template is None or template.builtin:
            return
        confirm = QMessageBox.question(
            self,
            "Delete template",
            f"Delete the uploaded template '{template.name}'?\n\n"
            "Reports already generated with it are not affected.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        try:
            deleted = self.service.delete_template(template.template_id)
        except TemplateError as exc:
            QMessageBox.warning(self, "Cannot delete", str(exc))
            return
        except Exception as exc:
            QMessageBox.critical(self, "Delete failed", str(exc))
            return
        self.templates_changed = True
        self._refresh()
        if not deleted:
            QMessageBox.warning(self, "Not found", "The template file was already removed.")


class ReportWorker(QObject):
    """Background worker for report generation with its own database session."""

    finished = Signal(dict)
    error = Signal(str)

    def __init__(
        self,
        case_id: int,
        title: str,
        sections: list[str],
        template_id: str,
        generated_by_id: int,
        generated_by_name: str,
    ):
        super().__init__()
        self.case_id = case_id
        self.title = title
        self.sections = sections
        self.template_id = template_id
        self.generated_by_id = generated_by_id
        self.generated_by_name = generated_by_name

    def run(self) -> None:
        from types import SimpleNamespace

        from app.db.session import get_session_factory
        from app.reports.service import ReportService

        session = get_session_factory()()
        try:
            service = ReportService(session)
            examiner = SimpleNamespace(id=self.generated_by_id, full_name=self.generated_by_name)
            report = service.generate_report(
                case_id=self.case_id,
                title=self.title,
                sections=self.sections,
                template_id=self.template_id,
                generated_by=examiner,
            )
            payload = {
                "report_id": report.id,
                "report_id_str": report.report_id,
                "file_path": report.file_path,
                "file_size": report.file_size_bytes,
            }
        except Exception as exc:
            self.error.emit(str(exc))
            return
        finally:
            session.close()
        self.finished.emit(payload)


class ReportsPage(ResponsivePage):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent=parent)
        self.case_context: CaseContext | None = None
        self.report_service: "ReportService | None" = None
        self.current_user: "User | None" = None
        self.current_user_id = 1
        self.current_user_name = "Investigator"
        self._worker_thread: QThread | None = None
        self._worker: ReportWorker | None = None
        self._generation_running = False

    def _setup_layout(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(Spacing.LG, Spacing.LG, Spacing.LG, Spacing.LG)
        layout.setSpacing(Spacing.MD)

        header_row = QHBoxLayout()
        title = QLabel("Reports")
        title.setProperty("pageTitle", True)
        title.setFont(QFont(
            Typography.FONT_FAMILY, Typography.HEADING_LG[0], Typography.HEADING_LG[1]
        ))
        header_row.addWidget(title)
        header_row.addStretch()

        self.templates_btn = QPushButton("Report Templates")
        self.templates_btn.setProperty("secondary", True)
        self.templates_btn.setToolTip(
            "Choose, upload, inspect or export a court-oriented report template."
        )
        self.templates_btn.clicked.connect(self._on_manage_templates)
        header_row.addWidget(self.templates_btn)

        self.generate_btn = QPushButton("Generate Report")
        self.generate_btn.clicked.connect(self._on_generate)
        header_row.addWidget(self.generate_btn)

        layout.addLayout(header_row)

        self.template_label = QLabel("Active template: loading…")
        self.template_label.setWordWrap(True)
        self.template_label.setStyleSheet(f"color: {Color.TEXT_SECONDARY.name()};")
        layout.addWidget(self.template_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.hide()
        layout.addWidget(self.progress_bar)

        self.table_view = QTableView()
        self.table_model = ReportTableModel(self.table_view)
        self.table_view.setModel(self.table_model)
        self.table_view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table_view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table_view.setAlternatingRowColors(True)
        self.table_view.verticalHeader().setVisible(False)
        header = self.table_view.horizontalHeader()
        header.setStretchLastSection(False)
        for column, mode in enumerate([
            QHeaderView.ResizeMode.ResizeToContents,
            QHeaderView.ResizeMode.Stretch,
            QHeaderView.ResizeMode.Stretch,
            QHeaderView.ResizeMode.ResizeToContents,
            QHeaderView.ResizeMode.ResizeToContents,
            QHeaderView.ResizeMode.ResizeToContents,
        ]):
            header.setSectionResizeMode(column, mode)
        self.table_view.doubleClicked.connect(self._on_open)
        layout.addWidget(self.table_view, 1)

        btn_row = QHBoxLayout()
        self.open_btn = QPushButton("Open")
        self.open_btn.setProperty("secondary", True)
        self.open_btn.clicked.connect(self._on_open)
        btn_row.addWidget(self.open_btn)

        self.export_btn = QPushButton("Export")
        self.export_btn.setProperty("secondary", True)
        self.export_btn.clicked.connect(self._on_export)
        btn_row.addWidget(self.export_btn)

        btn_row.addStretch()
        layout.addLayout(btn_row)

    # ------------------------------------------------------------ lifecycle
    def set_case_context(self, context: CaseContext):
        self.case_context = context

    def shutdown(self) -> None:
        """Wait for a running report build so a close cannot abort Qt."""
        qt_threads.stop(self._worker_thread, wait_ms=5000)

    def set_report_service(self, service: "ReportService", current_user: "User"):
        self.report_service = service
        self.current_user = current_user
        try:
            self.current_user_id = int(getattr(current_user, "id", 1) or 1)
        except Exception:
            self.current_user_id = 1
        try:
            self.current_user_name = (
                str(getattr(current_user, "full_name", "") or "")
                or str(getattr(current_user, "username", "") or "")
                or "Investigator"
            )
        except Exception:
            self.current_user_name = "Investigator"
        self._refresh_template_label()
        self.refresh()

    def _require_writer(self) -> User | None:
        """Check if current user has write permissions. Returns user if allowed, None if denied."""
        # ReportsPage receives current_user via set_report_service; fallback to nav if available
        user = getattr(self, "current_user", None)
        if user is None:
            getter = getattr(self.nav, "get_current_user", None) if hasattr(self, "nav") else None
            user = getter() if callable(getter) else None
        if user is None:
            QMessageBox.warning(self, "No User", "Could not identify the signed-in user")
            return None
        from app.auth.models import UserRole
        if user.role == UserRole.READ_ONLY:
            QMessageBox.warning(
                self, "Permission denied", "Read-only users cannot perform this action."
            )
            return None
        return user

    def on_page_shown(self):
        self.refresh()

    def refresh(self):
        if not self.report_service or not self.case_context:
            return
        try:
            reports = self.report_service.list_reports(self.case_context.case_id)
        except Exception:
            return
        self.table_model.populate(reports)

    def _refresh_template_label(self) -> None:
        if not self.report_service:
            self.template_label.setText("Active template: not available")
            return
        try:
            templates = self.report_service.list_templates()
            default = self.report_service.default_template()
        except Exception as exc:
            self.template_label.setText(f"Active template: unavailable ({exc})")
            return
        uploaded = sum(not template.builtin for template in templates)
        self.template_label.setText(
            f"Active template: {default.name}  ·  {uploaded} uploaded template(s)  ·  "
            "use Report Templates to upload or inspect a template"
        )
        self.template_label.setToolTip(
            f"{default.description}\n\nSource: {default.source_label}\n"
            f"Organisation: {default.organization}  |  Jurisdiction: {default.jurisdiction}"
        )

    # -------------------------------------------------------------- actions
    def _on_manage_templates(self):
        user = self._require_writer()
        if user is None:
            return
        if not self.report_service:
            QMessageBox.warning(self, "Not Ready", "Report service not available")
            return
        selected = ""
        try:
            selected = self.report_service.default_template().template_id
        except Exception:
            pass
        dialog = ReportTemplatesDialog(self.report_service, selected, self)
        dialog.exec()
        if dialog.templates_changed:
            self._refresh_template_label()

    def _on_generate(self):
        user = self._require_writer()
        if user is None:
            return
        if not self.case_context or not self.report_service or not self.current_user:
            QMessageBox.warning(self, "Not Ready", "Report service not available")
            return
        if self._generation_running:
            QMessageBox.information(
                self, "Report in progress", "Wait for the current report to finish."
            )
            return

        try:
            templates = self.report_service.list_templates()
            default_id = self.report_service.default_template().template_id
        except Exception as exc:
            QMessageBox.critical(self, "Templates unavailable", str(exc))
            return

        dialog = ReportGenerateDialog(templates, default_id, self.report_service, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            if dialog.templates_changed:
                self._refresh_template_label()
            return

        data = dialog.get_data()
        if not data["sections"]:
            QMessageBox.warning(
                self, "No sections selected", "Select at least one section to include."
            )
            return
        self._refresh_template_label()

        self._generation_running = True
        self.progress_bar.show()
        self.generate_btn.setEnabled(False)
        self.templates_btn.setEnabled(False)

        self._worker_thread = QThread()
        qt_threads.track(self._worker_thread)
        self._worker = ReportWorker(
            case_id=self.case_context.case_id,
            title=data["title"],
            sections=data["sections"],
            template_id=data["template_id"],
            generated_by_id=self.current_user_id,
            generated_by_name=self.current_user_name,
        )
        self._worker.moveToThread(self._worker_thread)
        self._worker_thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_generate_finished)
        self._worker.error.connect(self._on_generate_error)
        self._worker.finished.connect(self._worker_thread.quit)
        self._worker.error.connect(self._worker_thread.quit)
        self._worker.finished.connect(self._worker.deleteLater)
        self._worker.error.connect(self._worker.deleteLater)
        self._worker_thread.finished.connect(self._on_worker_thread_finished)
        self._worker_thread.finished.connect(self._worker_thread.deleteLater)
        self._worker_thread.start()

    def _finish_generation(self):
        self._generation_running = False
        self.progress_bar.hide()
        self.generate_btn.setEnabled(True)
        self.templates_btn.setEnabled(True)

    def _on_worker_thread_finished(self):
        self._worker = None
        self._worker_thread = None

    def _on_generate_finished(self, result: dict):
        self._finish_generation()
        QMessageBox.information(
            self,
            "Report generated",
            f"Report generated: {result['report_id_str']}\n"
            f"Size: {self._format_size(result['file_size'] or 0)}",
        )
        self.refresh()

    def _on_generate_error(self, error: str):
        self._finish_generation()
        QMessageBox.critical(
            self,
            "Report generation failed",
            "The report could not be generated.\n\n"
            f"{error}\n\n"
            "Check that the template is still present and that the case data "
            "folder is writable.",
        )

    def _selected_report(self) -> Report | None:
        indexes = self.table_view.selectionModel().selectedRows()
        if not indexes:
            QMessageBox.information(self, "No Selection", "Select a report first")
            return None
        row = indexes[0].row()
        report_id = self.table_model.item(row, 0).text()
        if not self.report_service or not self.case_context:
            return None
        return self.report_service.get_report_by_report_id(
            self.case_context.case_id, report_id
        )

    def _on_open(self):
        report = self._selected_report()
        if report is None:
            return
        if not report.file_path or not Path(report.file_path).exists():
            QMessageBox.warning(self, "Not Found", "Report file not found")
            return
        if sys.platform == "win32":
            os.startfile(report.file_path)
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(report.file_path))

    def _on_export(self):
        report = self._selected_report()
        if report is None:
            return
        if not report.file_path or not Path(report.file_path).exists():
            QMessageBox.warning(self, "Not Found", "Report file not found")
            return
        save_path, _ = QFileDialog.getSaveFileName(
            self, "Export Report", f"{report.report_id}.pdf", "PDF Files (*.pdf)"
        )
        if not save_path:
            return
        try:
            shutil.copy2(report.file_path, save_path)
        except OSError as exc:
            QMessageBox.critical(self, "Export failed", str(exc))
            return
        QMessageBox.information(self, "Exported", f"Report exported to {save_path}")

    @staticmethod
    def _format_size(bytes_val: int) -> str:
        value = float(bytes_val)
        for unit in ["B", "KB", "MB", "GB"]:
            if value < 1024:
                return f"{value:.1f} {unit}"
            value /= 1024
        return f"{value:.1f} TB"
