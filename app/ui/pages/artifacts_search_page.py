"""Artifacts & Search Page."""
from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import shutil
import subprocess
import tempfile
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
from PySide6.QtCore import QDate, QObject, Qt, QThread, QUrl, Signal, Slot
from PySide6.QtGui import (
    QDesktopServices,
    QFont,
    QStandardItem,
    QStandardItemModel,
    QTextCharFormat,
    QTextCursor,
)
from PySide6.QtPdf import QPdfDocument, QPdfSearchModel
from PySide6.QtPdfWidgets import QPdfView
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTabBar,
    QTableView,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.artifacts.models import Artifact, ArtifactType
from app.config import get_config
from app.ui import qt_threads
from app.ui.base import CaseContext, ResponsivePage
from app.ui.layouts import configure_detail_pane, configure_detail_splitter
from app.ui.theme.tokens import Color, Spacing, Typography
from app.util.time import format_local_date


def _enum_value(value) -> str:
    """Normalize SQLAlchemy enums and raw SQLite/FTS values for display."""
    return str(getattr(value, "value", value))


def _has_extracted_text(artifact: Artifact) -> bool:
    """Use stored content, not file type, snippet, or indexing state.

    Older deep scans stored these descriptions instead of extracted text.
    Match only the complete known stand-in, never a substring of real text.
    """
    content = (artifact.content_text or "").strip()
    if not content:
        return False
    return re.fullmatch(
        r"\[(?:Image|Office Document|SQLite Database) - \d+ bytes\]",
        content,
    ) is None


def _evidence_label(artifact: Artifact) -> str:
    """Show the case-visible identifier, never the internal database key."""
    evidence = getattr(artifact, "evidence", None)
    evidence_id = getattr(evidence, "evidence_id", None) or "Unknown ID"
    name = getattr(evidence, "name", None) or "Unknown evidence"
    return f"{evidence_id} — {name}"

if TYPE_CHECKING:
    from app.artifacts.service import SearchService


class ArtifactTableModel(QStandardItemModel):
    HEADERS = [
        "Artifact ID", "Type", "Name", "Evidence", "Index", "Matched",
        "Excerpt", "Size", "Created",
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setHorizontalHeaderLabels(self.HEADERS)
        self._search_results: list[dict] = []

    def populate(self, results: list[dict]):
        """Populate from search results (dict with artifact, source, snippet)."""
        self._search_results = results
        self.removeRows(0, self.rowCount())
        for item in results:
            art = item["artifact"]
            size_str = self._format_size(art.source_size or 0)
            evidence_name = _evidence_label(art)
            index_status = _enum_value(getattr(art, "index_status", "unknown"))
            source = item.get("source", "") or ", ".join(item.get("sources", []))
            matched = ", ".join(item.get("matched_fields") or []) or source
            snippet = item.get("snippet") or ""
            row = [
                QStandardItem(art.artifact_id),
                QStandardItem(_enum_value(art.artifact_type)),
                QStandardItem(art.name),
                QStandardItem(evidence_name),
                QStandardItem(index_status.replace("_", " ").title()),
                QStandardItem(matched),
                QStandardItem(snippet),
                QStandardItem(size_str),
                QStandardItem(format_local_date(art.created_time) if art.created_time else ""),
            ]
            tooltip = (
                f"Artifact: {art.artifact_id}\nEvidence: {evidence_name}\n"
                f"Path: {art.source_path or 'N/A'}\n"
                f"SHA-256: {art.content_hash or 'Not available'}"
            )
            for cell in row:
                cell.setEditable(False)
                cell.setToolTip(f"{cell.text()}\n\n{tooltip}" if cell.text() else tooltip)
            self.appendRow(row)

    @staticmethod
    def _format_size(bytes_val: int) -> str:
        for unit in ["B", "KB", "MB", "GB"]:
            if bytes_val < 1024:
                return f"{bytes_val:.1f} {unit}"
            bytes_val /= 1024
        return f"{bytes_val:.1f} TB"

    def get_artifact_at_row(self, row: int) -> Artifact | None:
        if 0 <= row < len(self._search_results):
            return self._search_results[row]["artifact"]
        return None

    def get_result_at_row(self, row: int) -> dict | None:
        if 0 <= row < len(self._search_results):
            return self._search_results[row]
        return None


class ArtifactDocumentDialog(QDialog):
    """Large in-app viewer for PDFs and extracted document text."""

    def __init__(self, artifact: Artifact, query: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle(f"{artifact.name} — IDFA Document Viewer")
        self.setMinimumSize(500, 400)
        self._artifact = artifact
        self._query = query.strip()
        self._pdf_document: QPdfDocument | None = None
        self._text_matches: list[QTextCursor] = []
        self._text_match_index = -1

        layout = QVBoxLayout(self)
        title = QLabel(f"{artifact.name}  ·  {_enum_value(artifact.artifact_type)}")
        title.setStyleSheet("font-weight: 600;")
        title.setWordWrap(True)
        title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        title.setToolTip(title.text())
        layout.addWidget(title)
        toolbar = QHBoxLayout()
        toolbar.addStretch(1)
        self.previous_match_button = QPushButton("↑")
        self.previous_match_button.setToolTip("Previous occurrence")
        self.previous_match_button.setFixedWidth(38)
        self.previous_match_button.setEnabled(False)
        self.previous_match_button.clicked.connect(lambda: self._move_search_result(-1))
        toolbar.addWidget(self.previous_match_button)
        self.next_match_button = QPushButton("↓")
        self.next_match_button.setToolTip("Next occurrence")
        self.next_match_button.setFixedWidth(38)
        self.next_match_button.setEnabled(False)
        self.next_match_button.clicked.connect(lambda: self._move_search_result(1))
        toolbar.addWidget(self.next_match_button)
        self.match_count_label = QLabel("0 / 0")
        self.match_count_label.setMinimumWidth(55)
        self.match_count_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        toolbar.addWidget(self.match_count_label)
        self.maximize_button = QPushButton("□  Maximize")
        self.maximize_button.setToolTip("Maximize or restore this document viewer")
        self.maximize_button.clicked.connect(self._toggle_maximized)
        toolbar.addWidget(self.maximize_button)
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.accept)
        toolbar.addWidget(close_button)
        layout.addLayout(toolbar)

        self.viewer_stack = QVBoxLayout()
        layout.addLayout(self.viewer_stack, 1)
        self.text_view = QTextEdit()
        self.text_view.setReadOnly(True)
        self.text_view.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self.text_view.setFont(QFont(Typography.FONT_FAMILY, Typography.BODY_MD[0]))

        self._load_document()

    def _toggle_maximized(self):
        if self.isMaximized():
            self.showNormal()
            self.maximize_button.setText("□  Maximize")
        else:
            self.showMaximized()
            self.maximize_button.setText("❐  Restore")

    def _load_document(self):
        extension = (self._artifact.extension or Path(self._artifact.name).suffix).lower()
        evidence = getattr(self._artifact, "evidence", None)
        evidence_paths = [
            getattr(evidence, "stored_path", None),
            getattr(evidence, "source_path", None),
        ]
        evidence_path = next(
            (candidate for candidate in evidence_paths if candidate and Path(candidate).is_file()),
            None,
        )
        if extension == ".pdf":
            # An evidence image is not the selected file, even if it happens to
            # have a PDF extension. source_offset stores the filesystem inode.
            if (self._artifact.source_offset is not None or not evidence_path
                    or Path(evidence_path).suffix.lower() != ".pdf"):
                self.text_view.setPlainText(
                    "The original PDF is not available as a standalone evidence file. "
                    "Showing the selected artifact's extracted text instead.\n\n"
                    + (self._artifact.content_text or "No extracted text is available for this document.")
                )
                self.viewer_stack.addWidget(self.text_view)
                if self._query:
                    self._highlight_query(self._query)
                return
            # PDF loading is asynchronous: add the native page viewer before
            # checking status, otherwise fast status checks incorrectly fall
            # through to the indexed placeholder text.
            pdf_view = QPdfView(self)
            pdf_view.setPageMode(QPdfView.PageMode.MultiPage)
            self.viewer_stack.addWidget(pdf_view)
            self._pdf_document = QPdfDocument(self)
            pdf_view.setDocument(self._pdf_document)
            self._pdf_search_model = QPdfSearchModel(self)
            self._pdf_search_model.setDocument(self._pdf_document)
            pdf_view.setSearchModel(self._pdf_search_model)
            self._pdf_search_model.countChanged.connect(self._on_pdf_search_count_changed)
            pdf_view.currentSearchResultIndexChanged.connect(self._on_pdf_search_index_changed)
            self._pdf_view = pdf_view
            self._pdf_status_label = QLabel("Loading PDF…")
            self._pdf_status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.viewer_stack.addWidget(self._pdf_status_label)
            self._pdf_document.statusChanged.connect(self._on_pdf_status_changed)
            if evidence_path:
                self._pdf_document.load(evidence_path)
                if self._query:
                    self._pdf_search_model.setSearchString(self._query)
            else:
                self._pdf_status_label.setText(
                    "PDF source file is unavailable. The original evidence path could not be opened."
                )
            return

        content = self._artifact.content_text or "No extracted text is available for this document."
        self.text_view.setPlainText(content)
        self.viewer_stack.addWidget(self.text_view)
        if self._query:
            self._highlight_query(self._query)

    def _on_pdf_search_count_changed(self, *_args):
        count = self._pdf_search_model.count()
        has_results = count > 0
        self.previous_match_button.setEnabled(has_results)
        self.next_match_button.setEnabled(has_results)
        self.match_count_label.setText(f"{1 if has_results else 0} / {count}")
        if has_results:
            self._pdf_view.setCurrentSearchResultIndex(0)

    def _on_pdf_search_index_changed(self, index: int):
        count = self._pdf_search_model.count()
        if count:
            self.match_count_label.setText(f"{index + 1} / {count}")

    def _move_search_result(self, direction: int):
        if self._pdf_document is not None:
            count = self._pdf_search_model.count()
            if not count:
                return
            current = self._pdf_view.currentSearchResultIndex()
            self._pdf_view.setCurrentSearchResultIndex((current + direction) % count)
            return

        count = len(self._text_matches)
        if not count:
            return
        self._text_match_index = (self._text_match_index + direction) % count
        self.text_view.setTextCursor(self._text_matches[self._text_match_index])
        self.text_view.ensureCursorVisible()
        self.match_count_label.setText(f"{self._text_match_index + 1} / {count}")

    def _on_pdf_status_changed(self, status: QPdfDocument.Status):
        if not hasattr(self, "_pdf_status_label"):
            return
        if status == QPdfDocument.Status.Ready:
            self._pdf_status_label.hide()
        elif status == QPdfDocument.Status.Error:
            self._pdf_status_label.setText(
                "IDFA could not read this PDF. The source may be damaged or encrypted."
            )
            self._pdf_status_label.show()

    def _highlight_query(self, query: str):
        terms = list(dict.fromkeys(re.findall(r"\w+", query, flags=re.UNICODE)))
        selections = []
        self._text_matches = []
        self._text_match_index = -1
        fmt = QTextCharFormat()
        fmt.setBackground(Color.WARNING)
        fmt.setForeground(Color.TEXT_INVERSE)
        for term in terms:
            cursor = QTextCursor(self.text_view.document())
            while True:
                found = self.text_view.document().find(term, cursor)
                if found.isNull():
                    break
                selection = QTextEdit.ExtraSelection()
                selection.cursor = found
                selection.format = fmt
                selections.append(selection)
                self._text_matches.append(QTextCursor(found))
                cursor = QTextCursor(found)
                cursor.setPosition(found.selectionEnd())
        self._text_matches.sort(key=lambda match: match.selectionStart())
        self.text_view.setExtraSelections(selections)
        if self._text_matches:
            self._text_match_index = 0
            self.text_view.setTextCursor(self._text_matches[0])
            self.text_view.ensureCursorVisible()
            count = len(self._text_matches)
            self.previous_match_button.setEnabled(True)
            self.next_match_button.setEnabled(True)
            self.match_count_label.setText(f"1 / {count}")
        else:
            self.previous_match_button.setEnabled(False)
            self.next_match_button.setEnabled(False)
            self.match_count_label.setText("0 / 0")


class _WrappedMetadata(QLabel):
    """Reserve the full wrapped height so provenance remains scrollable."""

    def setText(self, text):
        super().setText(text)
        self.setMinimumHeight(max(0, self.heightForWidth(self.width())))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.setMinimumHeight(max(0, self.heightForWidth(event.size().width())))


class ArtifactDetailPane(QFrame):
    delete_requested = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("DetailPane")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        configure_detail_pane(self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(Spacing.MD, Spacing.MD, Spacing.MD, Spacing.MD)
        layout.setSpacing(Spacing.SM)

        self.title = QLabel("Select artifact to view details")
        self.title.setWordWrap(True)
        self.title.setFont(QFont(Typography.FONT_FAMILY, Typography.HEADING_SM[0], Typography.HEADING_SM[1]))
        layout.addWidget(self.title)

        # The passage that matched, so the reason a result was returned is
        # visible without opening the file.
        self.snippet_label = QLabel("")
        self.snippet_label.setWordWrap(True)
        self.snippet_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.snippet_label.setStyleSheet(f"color: {Color.TEXT_SECONDARY.name()};")
        layout.addWidget(self.snippet_label)

        self.content_label = QLabel("Content:")
        self.content_label.setFont(QFont(Typography.FONT_FAMILY, Typography.BODY_SM[0], QFont.Weight.Bold))
        content_header = QHBoxLayout()
        content_header.addWidget(self.content_label)
        content_header.addStretch()
        self.expand_button = QPushButton("Open viewer")
        self.expand_button.setProperty("compact", True)
        self.expand_button.setProperty("secondary", True)
        self.expand_button.setToolTip("Open a large, maximizable document viewer")
        self.expand_button.clicked.connect(self._open_document_viewer)
        content_header.addWidget(self.expand_button)
        layout.addLayout(content_header)

        self.metadata_label = _WrappedMetadata("")
        self.metadata_label.setWordWrap(True)
        self.metadata_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        layout.addWidget(self.metadata_label)

        hash_row = QHBoxLayout()
        self.hash_label = QLabel("SHA-256:")
        hash_row.addWidget(self.hash_label)
        self.hash_value = QLineEdit()
        self.hash_value.setReadOnly(True)
        self.hash_value.setMinimumWidth(0)
        self.hash_value.setToolTip("Select or scroll horizontally to inspect the complete value.")
        hash_row.addWidget(self.hash_value, 1)
        self.copy_hash_button = QPushButton("Copy hash")
        self.copy_hash_button.clicked.connect(lambda: QApplication.clipboard().setText(self.hash_value.text()))
        hash_row.addWidget(self.copy_hash_button)
        layout.addLayout(hash_row)

        action_row = QHBoxLayout()
        self.copy_id_button = QPushButton("Copy artifact ID")
        self.copy_id_button.clicked.connect(self._copy_artifact_id)
        action_row.addWidget(self.copy_id_button)
        self.copy_path_button = QPushButton("Copy path")
        self.copy_path_button.clicked.connect(self._copy_artifact_path)
        action_row.addWidget(self.copy_path_button)
        self.delete_button = QPushButton("Delete artifact")
        self.delete_button.setProperty("destructive", True)
        self.delete_button.setToolTip(
            "Permanently remove this extracted record and its derived analysis data. "
            "The registered evidence file is not affected."
        )
        self.delete_button.clicked.connect(self.delete_requested.emit)
        layout.addLayout(action_row)
        layout.addWidget(self.delete_button)
        self.copy_id_button.setEnabled(False)
        self.copy_path_button.setEnabled(False)
        self.delete_button.setEnabled(False)

        self.content_text = QTextEdit()
        self.content_text.setReadOnly(True)
        self.content_text.setFont(QFont(Typography.FONT_FAMILY, Typography.MONO_SM[0]))
        self.content_text.setMaximumHeight(200)
        layout.addWidget(self.content_text)

        self.match_status = QLabel("")
        self.match_status.setWordWrap(True)
        self.match_status.setStyleSheet(f"color: {Color.TEXT_SECONDARY.name()};")
        layout.addWidget(self.match_status)

        layout.addStretch()
        self._artifact: Artifact | None = None
        self._query = ""
        self.set_artifact(None)

    def set_artifact(
        self,
        artifact: Artifact | None,
        query: str = "",
        snippet: str = "",
        matched_fields: list[str] | None = None,
    ):
        self._artifact = artifact
        self._query = query
        # Show a useful empty state until there is a record to inspect.
        for widget in (
            self.content_label, self.expand_button, self.metadata_label,
            self.copy_id_button, self.copy_path_button, self.delete_button,
            self.content_text, self.match_status, self.snippet_label,
            self.hash_label, self.hash_value, self.copy_hash_button,
        ):
            widget.setVisible(artifact is not None)
        if not artifact:
            self.title.setText("Select artifact to view details")
            self.content_text.clear()
            self.match_status.clear()
            self.snippet_label.clear()
            self.metadata_label.clear()
            self.hash_value.clear()
            self.copy_id_button.setEnabled(False)
            self.copy_path_button.setEnabled(False)
            self.delete_button.setEnabled(False)
            return

        self.title.setText(f"{_enum_value(artifact.artifact_type)}: {artifact.name}")
        evidence_name = _evidence_label(artifact)
        try:
            extraction = json.loads(artifact.metadata_json or "{}")
        except (TypeError, json.JSONDecodeError):
            extraction = {}
        extraction_status = extraction.get("extraction_status", "legacy_unknown")
        extraction_labels = {
            "extracted": "Text extracted",
            "partial": "Partial extraction",
            "metadata_only_deleted": "Deleted entry — metadata only",
            "unsupported_or_no_text": "No extracted text (unsupported or unreadable format)",
            "error": "Extraction error",
            "legacy_unknown": "Status unavailable (older examination)",
        }
        extraction_text = extraction_labels.get(
            extraction_status, str(extraction_status).replace("_", " ").title()
        )
        if extraction.get("content_truncated"):
            extraction_text += " — partial content"
        if extraction.get("read_error"):
            label = "Extraction warning" if extraction_status == "partial" else "Read error"
            extraction_text += f"\n{label}: {extraction['read_error']}"
        self.metadata_label.setText(
            f"Artifact ID: {artifact.artifact_id}\n"
            f"Evidence: {evidence_name}\n"
            f"Path: {artifact.source_path or 'N/A'}\n"
            f"Size: {ArtifactTableModel._format_size(artifact.source_size or 0)}  ·  "
            f"Index: {_enum_value(artifact.index_status).replace('_', ' ').title()}\n"
            f"Extraction: {extraction_text}\n"
            f"Created: {format_local_date(artifact.created_time) if artifact.created_time else 'Unknown'}"
        )
        self.hash_value.setText(artifact.content_hash or "Not available")
        self.hash_value.home(False)
        self.copy_hash_button.setEnabled(bool(artifact.content_hash))
        self.copy_id_button.setEnabled(True)
        self.copy_path_button.setEnabled(bool(artifact.source_path))
        self.delete_button.setEnabled(True)
        if snippet:
            fields = ", ".join(matched_fields or ["content"])
            self.snippet_label.setText(f"Matched in {fields}: {snippet}")
        else:
            self.snippet_label.setText(f"Path: {artifact.source_path or 'N/A'}")
        content = artifact.content_text or "(no text content)"
        terms = list(dict.fromkeys(re.findall(r"\w+", query, flags=re.UNICODE)))

        # Center the preview on the first literal search-term occurrence, even
        # when the hit is deep in a long extracted document.
        def term_pattern(term: str) -> re.Pattern:
            # A name/token may be split by spaces or punctuation in extracted
            # document text (for example, "srigowri" vs "Sri Gowri"). Match
            # those separators, but never skip letters or digits.
            pieces = [re.escape(character) for character in term]
            return re.compile(r"[\W_]*".join(pieces), re.IGNORECASE | re.UNICODE)

        patterns = [term_pattern(term) for term in terms if term]
        first_match = None
        for pattern in patterns:
            match = pattern.search(content)
            if match:
                first_match = match.start()
                break

        window_size = 5000
        source_start = 0
        source_end = len(content)
        if len(content) > window_size:
            if first_match is not None:
                source_start = max(0, first_match - window_size // 3)
                source_start = min(source_start, len(content) - window_size)
            source_end = source_start + window_size
        body = content[source_start:source_end]
        prefix = "…\n" if source_start else ""
        suffix = "\n…" if source_end < len(content) else ""
        preview = prefix + body + suffix
        self.content_text.setPlainText(preview)

        selections = []
        first_cursor = None
        highlight_format = QTextCharFormat()
        highlight_format.setBackground(Color.WARNING)
        highlight_format.setForeground(Color.TEXT_INVERSE)
        document = self.content_text.document()
        for pattern in patterns:
            for match in pattern.finditer(body):
                display_start = len(prefix) + match.start()
                display_end = len(prefix) + match.end()
                # QTextCursor positions are UTF-16 code units, while Python
                # regular-expression offsets count Unicode code points.
                start_pos = len(preview[:display_start].encode("utf-16-le", errors="surrogatepass")) // 2
                end_pos = len(preview[:display_end].encode("utf-16-le", errors="surrogatepass")) // 2
                found = QTextCursor(document)
                found.setPosition(start_pos)
                found.setPosition(end_pos, QTextCursor.MoveMode.KeepAnchor)
                selection = QTextEdit.ExtraSelection()
                selection.cursor = found
                selection.format = highlight_format
                selections.append(selection)
                if first_cursor is None:
                    first_cursor = QTextCursor(found)
        self.content_text.setExtraSelections(selections)
        if first_cursor is not None:
            self.content_text.setTextCursor(first_cursor)
            self.content_text.ensureCursorVisible()
            self.match_status.setText(
                f"{len(selections)} matching occurrence(s) highlighted; "
                "the first match is selected."
            )
        elif query and content != "(no text content)":
            self.match_status.setText(
                "No literal query match in this document (semantic result); "
                "showing the preview without highlighting unrelated text."
            )
        else:
            self.match_status.setText("")

    def _open_document_viewer(self):
        if self._artifact is None:
            return
        dialog = ArtifactDocumentDialog(self._artifact, self._query, self)
        dialog.showMaximized()
        dialog.exec()

    def _copy_artifact_id(self):
        if self._artifact is not None:
            QApplication.clipboard().setText(self._artifact.artifact_id)

    def _copy_artifact_path(self):
        if self._artifact is not None and self._artifact.source_path:
            QApplication.clipboard().setText(self._artifact.source_path)


class SearchWorker(QObject):
    """Background worker for search operations."""
    finished = Signal(list)
    error = Signal(str)

    def __init__(self, search_service: "SearchService", case_id: int, query: str, 
                 mode: str, artifact_type: ArtifactType | None,
                 date_from: date | None = None, date_to: date | None = None,
                 regex: bool = False, evidence_id: int | None = None):
        super().__init__()
        self.search_service = search_service
        self.case_id = case_id
        self.query = query
        self.mode = mode
        self.artifact_type = artifact_type
        self.date_from = date_from
        self.date_to = date_to
        self.regex = regex
        self.evidence_id = evidence_id

    def run(self):
        loop = None
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            if self.mode == "Keyword":
                results = loop.run_until_complete(
                    self.search_service.keyword_search(
                        self.case_id, self.query, self.artifact_type,
                        date_from=self.date_from, date_to=self.date_to,
                        regex=self.regex, evidence_id=self.evidence_id,
                    )
                )
            elif self.mode == "Semantic":
                results = loop.run_until_complete(
                    self.search_service.semantic_search(
                        self.case_id, self.query, self.artifact_type,
                        date_from=self.date_from, date_to=self.date_to,
                        evidence_id=self.evidence_id,
                    )
                )
            else:  # Hybrid
                results = loop.run_until_complete(
                    self.search_service.hybrid_search(
                        self.case_id, self.query, self.artifact_type,
                        date_from=self.date_from, date_to=self.date_to,
                        regex=self.regex, evidence_id=self.evidence_id,
                    )
                )
            
            self.finished.emit(results)
        except Exception as e:
            self.error.emit(str(e))
        finally:
            if loop is not None:
                loop.close()
                asyncio.set_event_loop(None)


class OpenArtifactWorker(QObject):
    """Materialize an artifact to a temporary file for an external viewer."""

    finished = Signal(dict)

    def __init__(self, artifact_info: dict):
        super().__init__()
        self.artifact_info = artifact_info

    def run(self):
        temp_path = None
        try:
            info = self.artifact_info
            extension = (info.get("extension") or Path(info["name"]).suffix).lower()
            supported = {".pdf", ".doc", ".docx", ".rtf", ".txt", ".odt", ".xls", ".xlsx", ".ppt", ".pptx"}
            if extension not in supported:
                raise ValueError(
                    f"Opening .{extension.lstrip('.')} files externally is disabled. "
                    "Supported types are PDF and common office/text documents."
                )

            content: bytes
            evidence_path = info.get("evidence_path") or ""
            direct_path = Path(evidence_path) if evidence_path else None
            if (info.get("inode") is None and direct_path is not None
                    and direct_path.is_file() and direct_path.suffix.lower() == extension):
                if direct_path.stat().st_size > 100 * 1024 * 1024:
                    raise ValueError("Documents over 100 MB cannot be opened from the search page.")
                handle, temp_path = tempfile.mkstemp(
                    prefix="IDFA_artifact_", suffix=extension
                )
                os.close(handle)
                shutil.copyfile(direct_path, temp_path)
                self.finished.emit({"path": temp_path, "error": None})
                return
            else:
                config = get_config()
                payload = {
                    "image_path": evidence_path,
                    "inode": info.get("inode"),
                    "source_path": info.get("source_path"),
                    "partition_offset": int(info.get("partition_offset") or 0),
                }
                response = httpx.post(
                    f"{config.worker.url}/extract-artifact",
                    json=payload,
                    timeout=max(30.0, float(config.worker.timeout_seconds)),
                )
                if response.status_code != 200:
                    try:
                        detail = response.json().get("detail", response.text)
                    except Exception:
                        detail = response.text
                    raise RuntimeError(f"Worker could not extract this file: {detail}")
                content = response.content

            handle, temp_path = tempfile.mkstemp(
                prefix="IDFA_artifact_", suffix=extension
            )
            os.close(handle)
            Path(temp_path).write_bytes(content)
            self.finished.emit({"path": temp_path, "error": None})
        except Exception as exc:
            if temp_path:
                try:
                    Path(temp_path).unlink(missing_ok=True)
                except OSError:
                    pass
            self.finished.emit({"path": "", "error": str(exc)})


class IndexWorker(QObject):
    """Background worker for indexing."""
    finished = Signal(dict)
    error = Signal(str)
    progress = Signal(str, int, int, int, int)

    def __init__(self, search_service: "SearchService", case_id: int, rebuild: bool = False):
        super().__init__()
        self.search_service = search_service
        self.case_id = case_id
        self.rebuild = rebuild

    def run(self):
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            result = loop.run_until_complete(
                self.search_service.index_artifacts(
                    self.case_id, progress_callback=self.progress.emit, rebuild=self.rebuild
                )
            )
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))


class ArtifactsSearchPage(ResponsivePage):
    artifact_file_ready = Signal(dict, str)

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
        self.artifact_file_ready.connect(self._on_artifact_file_ready)
        self.case_context: CaseContext | None = None
        self.search_service: "SearchService | None" = None
        self._last_search_query = ""
        self._search_generation = 0
        self._search_active = False
        self._open_threads: list[QThread] = []
        

    def _setup_layout(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(Spacing.LG, Spacing.LG, Spacing.LG, Spacing.LG)
        layout.setSpacing(Spacing.LG)

        title = QLabel("Artifacts & Search")
        title.setStyleSheet("font-size: 20px; font-weight: 600;")
        layout.addWidget(title)
        subtitle = QLabel("Search files and extracted content from this case.")
        subtitle.setProperty("muted", True)
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        # Search controls are split into two compact rows so the page remains
        # comfortable at the minimum desktop window width.
        search_bar = QHBoxLayout()
        search_bar.setSpacing(Spacing.SM)

        # Mode tabs
        self.mode_tabs = QTabBar()
        self.mode_tabs.addTab("Keyword")
        self.mode_tabs.addTab("Semantic")
        self.mode_tabs.addTab("Hybrid")
        search_bar.addWidget(self.mode_tabs)

        # Query input
        self.query_edit = QLineEdit()
        self.query_edit.setPlaceholderText(
            'Search names, paths and content — "exact phrase", OR, NOT, NEAR'
        )
        self.query_edit.setToolTip(
            "Plain words match every word (prefix). Use quotes for a phrase, "
            "OR / NOT / NEAR for FTS5 syntax, or tick Regex."
        )
        self.query_edit.returnPressed.connect(self._on_search)
        self.query_edit.setClearButtonEnabled(True)
        search_bar.addWidget(self.query_edit, 1)

        self.search_btn = QPushButton("Search")
        self.search_btn.clicked.connect(self._on_search)
        search_bar.addWidget(self.search_btn)
        layout.addLayout(search_bar)

        filter_row = QHBoxLayout()
        filter_row.setSpacing(Spacing.SM)
        self.regex_check = QCheckBox("Regex")
        self.regex_check.setToolTip(
            "Treat the query as a regular expression over names, paths and "
            "content. Slower on large cases."
        )
        filter_row.addWidget(self.regex_check)

        # Type filter
        self.type_filter = QComboBox()
        self.type_filter.addItem("All Types")
        for t in ArtifactType:
            self.type_filter.addItem(t.value)
        filter_row.addWidget(self.type_filter)

        filter_row.addWidget(QLabel("Content:"))
        self.content_filter = QComboBox()
        self.content_filter.addItem("All", "all")
        self.content_filter.addItem("With extracted text", "with_text")
        self.content_filter.addItem("Without extracted text", "without_text")
        self.content_filter.setToolTip(
            "Filter by stored extracted text, independently of artifact type or indexing status. "
            "Empty, whitespace-only and known legacy placeholder text count as no text. "
            "Applied when you Search; clear the query to filter the case inventory. "
            "Search results are filtered after backend result limits, so other matching "
            "artifacts may not be shown. Semantic search only retrieves indexed text."
        )
        filter_row.addWidget(self.content_filter)

        # Default to an explicit no-date-limit state rather than displaying a
        # misleading sentinel such as 2000-01-01.
        filter_row.addWidget(QLabel("Evidence:"))
        self.evidence_filter = QComboBox()
        self.evidence_filter.addItem("All evidence", None)
        self.evidence_filter.setToolTip(
            "Limit results to one active evidence item. Older semantic indexes may require rebuilding."
        )
        filter_row.addWidget(self.evidence_filter)
        filter_row.addStretch(1)
        layout.addLayout(filter_row)

        date_row = QHBoxLayout()
        date_row.setSpacing(Spacing.SM)
        date_label = QLabel("Created:")
        date_label.setToolTip("Filter by the artifact's creation date; artifacts without a creation date are excluded.")
        date_row.addWidget(date_label)
        self.date_preset = QComboBox()
        self.date_preset.setToolTip(date_label.toolTip())
        for label, key in self.DATE_PRESETS:
            self.date_preset.addItem(label, key)
        self.date_preset.setMinimumWidth(145)
        date_row.addWidget(self.date_preset)

        self.custom_range = QWidget()
        custom_row = QHBoxLayout(self.custom_range)
        custom_row.setContentsMargins(0, 0, 0, 0)
        self.date_from = QDateEdit()
        self.date_to = QDateEdit()
        for picker in (self.date_from, self.date_to):
            picker.setDisplayFormat("yyyy-MM-dd")
            picker.setCalendarPopup(True)
            # Evidence timestamps can predate 2000 or be in the future when
            # a device clock was incorrect. Do not silently exclude them.
            picker.setMinimumDate(QDate(1752, 9, 14))
            picker.setMaximumDate(QDate(9999, 12, 31))
        today = QDate.currentDate()
        self.date_from.setDate(today.addDays(-29))
        self.date_to.setDate(today)
        custom_row.addWidget(QLabel("From:"))
        custom_row.addWidget(self.date_from)
        custom_row.addWidget(QLabel("To:"))
        custom_row.addWidget(self.date_to)
        custom_row.addStretch(1)
        self.custom_range.hide()
        date_row.addStretch()
        self.show_all_btn = QPushButton("Show all")
        self.show_all_btn.setProperty("secondary", True)
        self.show_all_btn.setToolTip(
            "Clear the query and filters and list every active case artifact"
        )
        self.show_all_btn.clicked.connect(self._show_all_artifacts)
        date_row.addWidget(self.show_all_btn)
        layout.addLayout(date_row)
        layout.addWidget(self.custom_range)

        index_row = QHBoxLayout()
        index_row.setSpacing(Spacing.SM)

        self.index_options_toggle = QToolButton()
        self.index_options_toggle.setText("Semantic indexing")
        self.index_options_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.index_options_toggle.setArrowType(Qt.ArrowType.RightArrow)
        self.index_options_toggle.setCheckable(True)
        self.index_options_toggle.setToolTip(
            "Show indexing and rebuild actions for semantic search"
        )
        index_row.addWidget(self.index_options_toggle)
        self.result_summary = QLabel("")
        self.result_summary.setProperty("muted", True)
        index_row.addStretch()
        index_row.addWidget(self.result_summary)
        layout.addLayout(index_row)

        self.index_options = QWidget()
        index_actions = QHBoxLayout(self.index_options)
        index_actions.setContentsMargins(0, 0, 0, 0)
        index_actions.setSpacing(Spacing.SM)
        self.index_options.hide()
        self.index_options_toggle.toggled.connect(self.index_options.setVisible)
        self.index_options_toggle.toggled.connect(
            lambda expanded: self.index_options_toggle.setArrowType(
                Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow
            )
        )

        # Index button
        self.index_btn = QPushButton("Index for Semantic Search")
        self.index_btn.setProperty("secondary", True)
        self.index_btn.setToolTip(
            "Embed each artifact's text in passages and store the vectors in "
            "Qdrant. Artifacts already indexed are skipped."
        )
        self.index_btn.clicked.connect(self._on_index)
        index_actions.addWidget(self.index_btn)
        self.rebuild_index_btn = QPushButton("Rebuild semantic index")
        self.rebuild_index_btn.setProperty("secondary", True)
        self.rebuild_index_btn.setToolTip("Re-embed all active case artifacts using current settings.")
        self.rebuild_index_btn.clicked.connect(lambda: self._on_index(rebuild=True))
        index_actions.addWidget(self.rebuild_index_btn)
        index_actions.addStretch()
        layout.addWidget(self.index_options)
        self.date_preset.currentIndexChanged.connect(self._on_date_preset_changed)
        self.mode_tabs.currentChanged.connect(
            lambda index: self.regex_check.setEnabled(index != 1)
        )

        # Progress bar (hidden initially)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)  # Indeterminate
        self.progress_bar.hide()
        layout.addWidget(self.progress_bar)

        self.index_status_label = QLabel("")
        self.index_status_label.setObjectName("SemanticIndexStatus")
        self.index_status_label.setWordWrap(True)
        self.index_status_label.hide()
        layout.addWidget(self.index_status_label)

        self.index_progress_bar = QProgressBar()
        self.index_progress_bar.setRange(0, 1000)
        self.index_progress_bar.setValue(0)
        self.index_progress_bar.hide()
        layout.addWidget(self.index_progress_bar)

        # Results splitter
        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.results_splitter = splitter

        # Results table
        self.table_view = QTableView()
        self.table_model = ArtifactTableModel(self.table_view)
        self.table_view.setModel(self.table_model)
        self.table_view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table_view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table_view.setAlternatingRowColors(True)
        self.table_view.verticalHeader().setVisible(False)
        self.table_view.horizontalHeader().setStretchLastSection(True)
        self.table_view.selectionModel().selectionChanged.connect(self._on_selection_changed)
        self.table_view.doubleClicked.connect(self._on_result_double_clicked)
        self.table_view.setToolTip(
            "Double-click a PDF or document result to extract a temporary copy and open it externally."
        )
        results_container = QWidget()
        results_layout = QVBoxLayout(results_container)
        results_layout.setContentsMargins(0, 0, 0, 0)
        results_heading = QLabel("Results")
        results_heading.setStyleSheet("font-weight: 600;")
        results_layout.addWidget(results_heading)
        self.empty_results = QLabel("No artifacts to display. Add evidence and run an examination to extract artifacts.")
        self.empty_results.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_results.setWordWrap(True)
        self.empty_results.setProperty("muted", True)
        results_layout.addWidget(self.empty_results, 1)
        self.empty_results.hide()
        results_layout.addWidget(self.table_view, 1)
        splitter.addWidget(results_container)

        # Detail pane
        self.detail_pane = ArtifactDetailPane()
        self.detail_pane.setMaximumWidth(16777215)
        self.detail_pane.delete_requested.connect(self._on_delete_artifact)
        self.detail_scroll = QScrollArea()
        self.detail_scroll.setWidgetResizable(True)
        self.detail_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.detail_scroll.setWidget(self.detail_pane)
        splitter.addWidget(self.detail_scroll)

        configure_detail_splitter(splitter, preferred_detail_width=300)
        layout.addWidget(splitter, 1)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "results_splitter"):
            orientation = (Qt.Orientation.Vertical if event.size().width() < 850
                           else Qt.Orientation.Horizontal)
            if self.results_splitter.orientation() != orientation:
                self.results_splitter.setOrientation(orientation)

    def _set_empty_results(self, message: str | None) -> None:
        self.empty_results.setText(message or "")
        self.empty_results.setVisible(bool(message))
        self.table_view.setVisible(not message)
        # An empty inspector duplicates the empty-state message and consumes
        # valuable space on a laptop. Restore it when results are available.
        self.detail_scroll.setVisible(not message)

    def set_case_context(self, context: CaseContext):
        self._invalidate_search()
        self.case_context = context
        self._refresh_evidence_filter()
        if self.search_service:
            self._load_case_artifacts()

    def on_page_shown(self):
        self._refresh_evidence_filter()
        if self.search_service and self.case_context and not self._last_search_query:
            self._load_case_artifacts()

    def shutdown(self) -> None:
        """Stop search and indexing so closing the window cannot abort Qt."""
        qt_threads.stop(getattr(self, "_worker_thread", None))
        qt_threads.stop(getattr(self, "_index_thread", None))
        for thread in list(self._open_threads):
            qt_threads.stop(thread, wait_ms=1000)

    def _on_date_preset_changed(self, *_args):
        self.custom_range.setVisible(self.date_preset.currentData() == "custom")

    def _date_range(self) -> tuple[date | None, date | None]:
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
            return date(today.year(), 1, 1), today.toPython()
        if key == "custom":
            start, end = self.date_from.date().toPython(), self.date_to.date().toPython()
            return (end, start) if start > end else (start, end)
        return None, None

    def _filter_results_by_date(self, results: list[dict]) -> list[dict]:
        start, end = self._date_range()
        if start is None and end is None:
            return results
        filtered = []
        for item in results:
            artifact = item.get("artifact")
            created = getattr(artifact, "created_time", None)
            created_date = created.date() if created is not None else None
            if created_date is None:
                continue
            if start is not None and created_date < start:
                continue
            if end is not None and created_date > end:
                continue
            filtered.append(item)
        return filtered

    def _filter_results_by_content(self, results: list[dict]) -> list[dict]:
        mode = self.content_filter.currentData()
        if mode == "all":
            return results
        return [
            item for item in results
            if _has_extracted_text(item["artifact"]) == (mode == "with_text")
        ]

    def set_search_service(self, service: "SearchService"):
        self._invalidate_search()
        self.search_service = service
        self._refresh_evidence_filter()
        # Enable semantic/hybrid tabs if service is available
        self.mode_tabs.setTabEnabled(1, True)
        self.mode_tabs.setTabEnabled(2, True)
        self.mode_tabs.setTabToolTip(1, "")
        self.mode_tabs.setTabToolTip(2, "")
        if self.case_context:
            self._load_case_artifacts()

    def _refresh_evidence_filter(self):
        previous = self.evidence_filter.currentData()
        self.evidence_filter.clear()
        self.evidence_filter.addItem("All evidence", None)
        if self.search_service and self.case_context:
            for evidence in self.search_service.list_case_evidence(self.case_context.case_id):
                self.evidence_filter.addItem(f"{evidence.evidence_id} — {evidence.name}", evidence.id)
        index = self.evidence_filter.findData(previous)
        if index >= 0:
            self.evidence_filter.setCurrentIndex(index)

    def _load_case_artifacts(self):
        """Display the case inventory when no search query is active."""
        if not self.search_service or not self.case_context:
            return
        artifact_type = (
            ArtifactType(self.type_filter.currentText())
            if self.type_filter.currentIndex() > 0 else None
        )
        date_from, date_to = self._date_range()
        try:
            results = self.search_service.list_case_artifacts(
                self.case_context.case_id, artifact_type, date_from, date_to,
                evidence_id=self.evidence_filter.currentData(),
            )
        except Exception as exc:
            self.result_summary.setText("Could not load artifacts")
            QMessageBox.critical(self, "Artifact List Error", str(exc))
            return
        results = self._filter_results_by_content(results)
        self.table_model.populate(results)
        filtered = (self.type_filter.currentIndex() > 0 or
                    self.content_filter.currentIndex() > 0 or
                    self.evidence_filter.currentIndex() > 0 or
                    self.date_preset.currentIndex() > 0)
        self._set_empty_results(None if results else (
            "No artifacts match these filters. Try changing or clearing them." if filtered else
            "No artifacts yet. Add evidence and run an examination to extract artifacts."
        ))
        self.table_view.clearSelection()
        if results:
            self.table_view.selectRow(0)
        else:
            self.detail_pane.set_artifact(None)
        scope = "matching filters" if filtered else "in this case"
        self.result_summary.setText(f"{len(results):,} artifact(s) {scope}")

    def _show_all_artifacts(self):
        self._invalidate_search()
        self.query_edit.clear()
        self.type_filter.setCurrentIndex(0)
        self.content_filter.setCurrentIndex(0)
        self.evidence_filter.setCurrentIndex(0)
        self.date_preset.setCurrentIndex(0)
        self.regex_check.setChecked(False)
        self._last_search_query = ""
        self._load_case_artifacts()

    def _on_search(self):
        if not self.search_service or not self.case_context:
            QMessageBox.warning(self, "Not Ready", "Search service not available")
            return

        query = self.query_edit.text().strip()
        if not query:
            self._invalidate_search()
            self._last_search_query = ""
            self._load_case_artifacts()
            return
        if self._search_active:
            return
        self._search_active = True
        self._search_generation += 1
        generation = self._search_generation
        self._last_search_query = query

        mode_idx = self.mode_tabs.currentIndex()
        modes = ["Keyword", "Semantic", "Hybrid"]
        mode = modes[mode_idx]

        artifact_type = None
        if self.type_filter.currentIndex() > 0:
            artifact_type = ArtifactType(self.type_filter.currentText())

        date_from, date_to = self._date_range()

        # Show progress
        self.progress_bar.show()
        self.search_btn.setEnabled(False)

        # Run search in background thread
        self._worker_thread = QThread()
        qt_threads.track(self._worker_thread)
        self._worker = SearchWorker(
            self.search_service, 
            self.case_context.case_id, 
            query, 
            mode, 
            artifact_type,
            date_from,
            date_to,
            regex=self.regex_check.isChecked() and mode != "Semantic",
            evidence_id=self.evidence_filter.currentData(),
        )
        self._worker.moveToThread(self._worker_thread)
        self._worker_thread.started.connect(self._worker.run)
        self._worker.finished.connect(lambda results: self._deliver_search_results(generation, results))
        self._worker.error.connect(lambda error: self._deliver_search_error(generation, error))
        self._worker.finished.connect(self._worker_thread.quit)
        self._worker.finished.connect(self._worker.deleteLater)
        self._worker.error.connect(self._worker_thread.quit)
        self._worker.error.connect(self._worker.deleteLater)
        self._worker_thread.finished.connect(self._search_thread_finished)
        self._worker_thread.finished.connect(self._worker_thread.deleteLater)
        self._worker_thread.start()

    def _invalidate_search(self):
        self._search_generation += 1
        self._last_search_query = ""
        self.progress_bar.hide()

    def _deliver_search_results(self, generation: int, results: list[dict]):
        if generation == self._search_generation:
            self._on_search_finished(results)

    def _deliver_search_error(self, generation: int, error: str):
        if generation == self._search_generation:
            self._on_search_error(error)

    def _search_thread_finished(self):
        self._search_active = False
        self.progress_bar.hide()
        self.search_btn.setEnabled(True)

    def _on_search_finished(self, results: list[dict]):
        self.progress_bar.hide()
        results = self._filter_results_by_date(results)
        returned_count = len(results)
        results = self._filter_results_by_content(results)
        self.table_model.populate(results)
        self._set_empty_results(None if results else
                                "No results found. Try another query or clear your filters.")
        self.table_view.clearSelection()
        if results:
            self.table_view.selectRow(0)
            self.result_summary.setText(f"{len(results)} result(s)")
        else:
            self.detail_pane.set_artifact(None)
            self.result_summary.setText("No results — check the syntax or try another mode")
        if self.content_filter.currentData() != "all":
            self.result_summary.setText(
                f"{len(results)} of {returned_count} returned result(s) · "
                "content filter applied after search limits"
            )

    def _on_search_error(self, error: str):
        self.progress_bar.hide()
        QMessageBox.critical(self, "Search Error", error)

    def _on_index(self, rebuild=False):
        if not self.search_service or not self.case_context:
            return
        
        self.index_status_label.setText("Starting semantic indexing…")
        self.index_status_label.show()
        self.index_progress_bar.setValue(0)
        self.index_progress_bar.setFormat("Preparing…")
        self.index_progress_bar.show()
        self.index_btn.setEnabled(False)
        self.rebuild_index_btn.setEnabled(False)
        self.index_btn.setText("Indexing…")
        
        # Run indexing in background
        self._index_thread = QThread()
        qt_threads.track(self._index_thread)
        self._index_worker = IndexWorker(self.search_service, self.case_context.case_id, rebuild)
        self._index_worker.moveToThread(self._index_thread)
        self._index_thread.started.connect(self._index_worker.run)
        self._index_worker.progress.connect(self._on_index_progress)
        self._index_worker.finished.connect(self._on_index_finished)
        self._index_worker.error.connect(self._on_index_error)
        self._index_worker.error.connect(self._index_thread.quit)
        self._index_worker.error.connect(self._index_worker.deleteLater)
        self._index_worker.finished.connect(self._index_thread.quit)
        self._index_worker.finished.connect(self._index_worker.deleteLater)
        self._index_thread.finished.connect(self._index_thread.deleteLater)
        self._index_thread.start()

    def _on_index_finished(self, result: dict):
        self.index_btn.setEnabled(True)
        self.rebuild_index_btn.setEnabled(True)
        self.index_btn.setText("Index for Semantic Search")
        if "error" in result:
            self.index_status_label.setText(f"Semantic indexing failed: {result['error']}")
            self.index_progress_bar.hide()
            QMessageBox.critical(self, "Index Error", result["error"])
        else:
            indexed = result.get("indexed", 0)
            total = result.get("total", 0)
            failures = result.get("errors") or []
            message = f"Indexed {indexed} of {total} eligible artifacts."
            if total:
                self.index_progress_bar.setValue(1000)
                self.index_progress_bar.setFormat(f"Complete · {total:,}/{total:,} artifacts")
                self.index_status_label.setText(
                    f"Semantic indexing complete · {indexed:,} indexed · "
                    f"{len(failures):,} failed"
                )
            else:
                self.index_progress_bar.hide()
                self.index_status_label.setText(
                    result.get("message", "No text-bearing artifacts need indexing.")
                )
            if failures:
                message += "\n\nSome artifacts could not be indexed:\n" + "\n".join(failures[:8])
                if len(failures) > 8:
                    message += f"\n…and {len(failures) - 8} more."
            elif not total:
                message = result.get("message", "No text-bearing artifacts need indexing.")
            selected_row = self.table_view.currentIndex().row()
            self.table_model.populate(self.table_model._search_results)
            if 0 <= selected_row < self.table_model.rowCount():
                self.table_view.selectRow(selected_row)
            QMessageBox.information(self, "Indexing Complete", message)

    def _on_index_error(self, error: str):
        self.index_status_label.setText(f"Semantic indexing failed: {error}")
        self.index_progress_bar.hide()
        self.index_btn.setEnabled(True)
        self.rebuild_index_btn.setEnabled(True)
        self.index_btn.setText("Index for Semantic Search")
        QMessageBox.critical(self, "Index Error", error)

    def _on_index_progress(
        self,
        message: str,
        current: int,
        total: int,
        indexed: int,
        failed: int,
    ) -> None:
        if total > 0:
            bounded = max(0, min(total, current))
            value = int(bounded * 1000 / total)
            self.index_progress_bar.setValue(value)
            self.index_progress_bar.setFormat(
                f"{bounded:,}/{total:,} artifacts · {value // 10}%"
            )
        else:
            self.index_progress_bar.setValue(0)
            self.index_progress_bar.setFormat("Preparing…")
        self.index_status_label.setText(
            f"{message} · {indexed:,} indexed · {failed:,} failed"
        )

    def _on_selection_changed(self):
        indexes = self.table_view.selectionModel().selectedRows()
        if indexes:
            row = indexes[0].row()
            result = self.table_model.get_result_at_row(row)
            if result:
                self.detail_pane.set_artifact(
                    result["artifact"],
                    self._last_search_query,
                    result.get("snippet", ""),
                    result.get("matched_fields"),
                )
                return
        self.detail_pane.set_artifact(None)

    def _on_delete_artifact(self):
        artifact = self.detail_pane._artifact
        if artifact is None or self.search_service is None or self.case_context is None:
            return
        answer = QMessageBox.question(
            self,
            "Delete extracted artifact?",
            f"Permanently delete {artifact.artifact_id} — {artifact.name}?\n\n"
            "This removes the artifact record, extracted text/chunks, entity and "
            "timeline results, graph links, and finding links. Registered evidence "
            "and source files are not deleted. This cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        getter = getattr(self.nav, "get_current_user", None)
        user = getter() if callable(getter) else None
        if user is None:
            QMessageBox.warning(
                self, "Investigator required", "A signed-in investigator is required."
            )
            return
        try:
            deleted = self.search_service.delete_artifact(
                self.case_context.case_id, artifact.id, user
            )
            if not deleted:
                raise ValueError("The artifact no longer exists in this case.")
            self.search_service.session.commit()
            self.search_service.session.expire_all()
        except Exception as exc:
            self.search_service.session.rollback()
            QMessageBox.critical(self, "Artifact deletion failed", str(exc))
            return
        self.detail_pane.set_artifact(None)
        if self._last_search_query:
            self._on_search()
        else:
            self._load_case_artifacts()

    def _on_result_double_clicked(self, index):
        artifact = self.table_model.get_artifact_at_row(index.row())
        if artifact is None:
            return
        # Open the in-app, maximized viewer immediately. It renders a standalone
        # PDF with QtPdf and uses the extracted text for other document formats;
        # double-click no longer waits on external-file materialization.
        self.detail_pane.set_artifact(artifact, self._last_search_query)
        self.detail_pane._open_document_viewer()

    def _forget_open_thread(self, thread: QThread):
        if thread in self._open_threads:
            self._open_threads.remove(thread)

    @staticmethod
    def _open_in_word(path: str, query: str) -> bool:
        """Open Word and use its Find selection to highlight the query."""
        try:
            encoded_path = base64.b64encode(path.encode("utf-8")).decode("ascii")
            encoded_query = base64.b64encode(query.encode("utf-8")).decode("ascii")
            script = rf"""
$ErrorActionPreference = 'Stop'
$p = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{encoded_path}'))
$q = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{encoded_query}'))
try {{
    $word = New-Object -ComObject Word.Application
    $word.Visible = $true
    $doc = $word.Documents.Open($p, $false, $true)
    if ($q) {{
        $find = $word.Selection.Find
        $find.ClearFormatting()
        $find.Text = $q
        $find.Forward = $true
        $find.Wrap = 1
        [void]$find.Execute()
    }}
}} catch {{ Start-Process -FilePath $p }}
"""
            creation_flags = getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
            creation_flags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
            subprocess.Popen(
                ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creation_flags,
            )
            return True
        except OSError:
            return False

    @staticmethod
    def _open_external_document(path: str, query: str) -> bool:
        extension = Path(path).suffix.lower()
        if extension in {".doc", ".docx", ".rtf"} and ArtifactsSearchPage._open_in_word(path, query):
            return True

        url = QUrl.fromLocalFile(path)
        if extension == ".pdf" and query:
            # Chromium/Edge's built-in PDF viewer honors #search= and selects
            # the matching text when the PDF contains searchable text.
            url.setFragment("search=" + query)
            edge_paths = [
                Path(os.environ.get("ProgramFiles(x86)", "")) / "Microsoft/Edge/Application/msedge.exe",
                Path(os.environ.get("ProgramFiles", "")) / "Microsoft/Edge/Application/msedge.exe",
                Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft/Edge/Application/msedge.exe",
            ]
            edge = next((candidate for candidate in edge_paths if candidate.is_file()), None)
            if edge is not None:
                creation_flags = getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
                creation_flags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
                subprocess.Popen(
                    [str(edge), url.toString()],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=creation_flags,
                )
                return True
        return QDesktopServices.openUrl(url)

    @Slot(dict, str)
    def _on_artifact_file_ready(self, result: dict, query: str):
        if result.get("error"):
            self.detail_pane.match_status.setText("External document open failed.")
            QMessageBox.warning(self, "Cannot Open Document", result["error"])
            return
        path = result.get("path")
        if not path or not self._open_external_document(path, query):
            QMessageBox.warning(
                self, "Cannot Open Document",
                "Windows could not launch an application for this document type.",
            )
            return
        self.detail_pane.match_status.setText(
            f"Opened a temporary extracted copy externally. Search requested: {query or '(none)'}. "
            "The viewer highlights it only if the document contains the term."
        )
