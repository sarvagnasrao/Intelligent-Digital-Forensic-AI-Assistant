"""Tools Page - system diagnostics and management."""
from __future__ import annotations

import shutil
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTableView, QHeaderView,
    QPushButton, QProgressBar, QMessageBox, QTabWidget,
    QTextEdit, QGroupBox, QLineEdit, QComboBox, QDialog,
    QDialogButtonBox, QFileDialog
)
from PySide6.QtCore import Qt, QThread, Signal, QObject
from PySide6.QtGui import QStandardItemModel, QStandardItem, QFont, QTextCursor

from app.ui.base import ResponsivePage
from app.ui.theme.tokens import Color, Spacing, Typography
from app.config import get_config

if TYPE_CHECKING:
    from app.db.session import session_scope


def pyside_version() -> str:
    """Installed PySide6 and Qt versions.

    ``QApplication`` has no ``version`` attribute; the binding exposes its
    version on the package and Qt's on ``qVersion()``.
    """
    try:
        import PySide6
        from PySide6.QtCore import qVersion

        return f"{PySide6.__version__} (Qt {qVersion()})"
    except Exception:
        return "Unknown"


class ToolsPage(ResponsivePage):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent=parent)

    def _setup_layout(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(Spacing.LG, Spacing.LG, Spacing.LG, Spacing.LG)
        layout.setSpacing(Spacing.LG)

        # Header with title and primary action
        header = QHBoxLayout()
        title = QLabel("Tools & Diagnostics")
        title.setFont(QFont(Typography.FONT_FAMILY, Typography.HEADING_LG[0], Typography.HEADING_LG[1]))
        header.addWidget(title)
        header.addStretch()

        self.diagnostics_btn = QPushButton("Run Full Diagnostics")
        self.diagnostics_btn.clicked.connect(self.run_diagnostics)
        header.addWidget(self.diagnostics_btn)

        layout.addLayout(header)

        # Secondary actions open the dedicated tool dialogs. They sit on their
        # own row so the title bar never crowds the primary action.
        actions = QHBoxLayout()
        actions.setSpacing(Spacing.SM)

        self.db_mgmt_btn = QPushButton("Database Management")
        self.db_mgmt_btn.setProperty("secondary", True)
        self.db_mgmt_btn.clicked.connect(self._open_db_management)
        actions.addWidget(self.db_mgmt_btn)

        self.cache_mgmt_btn = QPushButton("Cache Management")
        self.cache_mgmt_btn.setProperty("secondary", True)
        self.cache_mgmt_btn.clicked.connect(self._open_cache_management)
        actions.addWidget(self.cache_mgmt_btn)

        self.logs_btn = QPushButton("View Logs")
        self.logs_btn.setProperty("secondary", True)
        self.logs_btn.clicked.connect(self._open_logs)
        actions.addWidget(self.logs_btn)

        self.sysinfo_btn = QPushButton("System Info")
        self.sysinfo_btn.setProperty("secondary", True)
        self.sysinfo_btn.clicked.connect(self._open_sysinfo)
        actions.addWidget(self.sysinfo_btn)

        actions.addStretch()
        layout.addLayout(actions)

        # Tab widget for different tool categories
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)

        # Diagnostics Tab
        self.diag_tab = QWidget()
        diag_layout = QVBoxLayout(self.diag_tab)
        diag_layout.setContentsMargins(Spacing.MD, Spacing.MD, Spacing.MD, Spacing.MD)
        diag_layout.setSpacing(Spacing.MD)

        # Service status table
        self.diag_table = QTableView()
        self.diag_model = QStandardItemModel()
        self.diag_model.setHorizontalHeaderLabels(["Service", "Status", "Details", "Actions"])
        self.diag_table.setModel(self.diag_model)
        self.diag_table.verticalHeader().setVisible(False)
        self.diag_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.diag_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.diag_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.diag_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.diag_table.setAlternatingRowColors(True)
        self.diag_table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.diag_table.setShowGrid(False)
        diag_layout.addWidget(self.diag_table, 1)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.hide()
        diag_layout.addWidget(self.progress_bar)

        # Status label
        self.status_label = QLabel("Run diagnostics to check service and tool availability.")
        self.status_label.setStyleSheet(f"color: {Color.TEXT_SECONDARY.name()}; font-size: {Typography.BODY_SM[0]}px;")
        diag_layout.addWidget(self.status_label)

        self.tabs.addTab(self.diag_tab, "Diagnostics")

        # Database Tab
        self.db_tab = QWidget()
        db_layout = QVBoxLayout(self.db_tab)
        db_layout.setContentsMargins(Spacing.MD, Spacing.MD, Spacing.MD, Spacing.MD)
        db_layout.setSpacing(Spacing.MD)

        db_info = QLabel(
            "Back up, restore, or run maintenance on the local SQLite case database. "
            "These operations open the database management dialog."
        )
        db_info.setStyleSheet(f"color: {Color.TEXT_SECONDARY.name()};")
        db_info.setWordWrap(True)
        db_layout.addWidget(db_info)

        db_btn_row = QHBoxLayout()
        db_btn_row.setSpacing(Spacing.SM)
        db_backup_btn = QPushButton("Backup Database")
        db_backup_btn.clicked.connect(self._open_db_management)
        db_btn_row.addWidget(db_backup_btn)

        db_restore_btn = QPushButton("Restore Database")
        db_restore_btn.setProperty("secondary", True)
        db_restore_btn.clicked.connect(self._open_db_management)
        db_btn_row.addWidget(db_restore_btn)

        db_maint_btn = QPushButton("Maintenance (VACUUM/ANALYZE)")
        db_maint_btn.setProperty("secondary", True)
        db_maint_btn.clicked.connect(self._open_db_management)
        db_btn_row.addWidget(db_maint_btn)
        db_btn_row.addStretch()
        db_layout.addLayout(db_btn_row)

        db_layout.addStretch()

        self.tabs.addTab(self.db_tab, "Database")

        # Cache Tab
        self.cache_tab = QWidget()
        cache_layout = QVBoxLayout(self.cache_tab)
        cache_layout.setContentsMargins(Spacing.MD, Spacing.MD, Spacing.MD, Spacing.MD)
        cache_layout.setSpacing(Spacing.MD)

        cache_info = QLabel("Review and clear temporary files stored by the application.")
        cache_info.setStyleSheet(f"color: {Color.TEXT_SECONDARY.name()};")
        cache_info.setWordWrap(True)
        cache_layout.addWidget(cache_info)

        self.cache_size_label = QLabel("Calculating cache size...")
        self.cache_size_label.setFont(
            QFont(Typography.FONT_FAMILY, Typography.BODY_MD[0], Typography.BODY_MD[1])
        )
        cache_layout.addWidget(self.cache_size_label)

        cache_btn_row = QHBoxLayout()
        cache_btn_row.setSpacing(Spacing.SM)
        self.clear_cache_btn = QPushButton("Clear All Cache")
        self.clear_cache_btn.setProperty("danger", True)
        self.clear_cache_btn.clicked.connect(self._clear_cache)
        cache_btn_row.addWidget(self.clear_cache_btn)

        cache_refresh_btn = QPushButton("Refresh Stats")
        cache_refresh_btn.setProperty("secondary", True)
        cache_refresh_btn.clicked.connect(self._refresh_cache_info)
        cache_btn_row.addWidget(cache_refresh_btn)
        cache_btn_row.addStretch()
        cache_layout.addLayout(cache_btn_row)

        cache_layout.addStretch()

        self.tabs.addTab(self.cache_tab, "Cache")

        # Logs Tab
        self.logs_tab = QWidget()
        logs_layout = QVBoxLayout(self.logs_tab)
        logs_layout.setContentsMargins(Spacing.MD, Spacing.MD, Spacing.MD, Spacing.MD)
        logs_layout.setSpacing(Spacing.MD)

        logs_top_row = QHBoxLayout()
        logs_top_row.setSpacing(Spacing.SM)
        refresh_logs_btn = QPushButton("Refresh Logs")
        refresh_logs_btn.setProperty("secondary", True)
        refresh_logs_btn.clicked.connect(self._refresh_logs)
        logs_top_row.addWidget(refresh_logs_btn)

        self.log_filter = QComboBox()
        self.log_filter.addItems(["All", "DEBUG", "INFO", "WARNING", "ERROR"])
        self.log_filter.setMinimumWidth(140)
        self.log_filter.currentTextChanged.connect(self._filter_logs)
        logs_top_row.addWidget(self.log_filter)
        logs_top_row.addStretch()
        logs_layout.addLayout(logs_top_row)

        self.logs_text = QTextEdit()
        self.logs_text.setReadOnly(True)
        self.logs_text.setFont(QFont("Consolas", 10))
        self.logs_text.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self.logs_text.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        logs_layout.addWidget(self.logs_text, 1)

        self.tabs.addTab(self.logs_tab, "Logs")

        # System Info Tab
        self.sysinfo_tab = QWidget()
        sysinfo_layout = QVBoxLayout(self.sysinfo_tab)
        sysinfo_layout.setContentsMargins(Spacing.MD, Spacing.MD, Spacing.MD, Spacing.MD)
        sysinfo_layout.setSpacing(Spacing.MD)

        sysinfo_top_row = QHBoxLayout()
        sysinfo_top_row.setSpacing(Spacing.SM)
        refresh_sysinfo_btn = QPushButton("Refresh System Info")
        refresh_sysinfo_btn.setProperty("secondary", True)
        refresh_sysinfo_btn.clicked.connect(self._refresh_sysinfo)
        sysinfo_top_row.addWidget(refresh_sysinfo_btn)
        sysinfo_top_row.addStretch()
        sysinfo_layout.addLayout(sysinfo_top_row)

        self.sysinfo_text = QTextEdit()
        self.sysinfo_text.setReadOnly(True)
        self.sysinfo_text.setFont(QFont("Consolas", 10))
        self.sysinfo_text.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        sysinfo_layout.addWidget(self.sysinfo_text, 1)

        self.tabs.addTab(self.sysinfo_tab, "System Info")

        # Status bar at bottom
        self.status_bar = QLabel("Ready")
        self.status_bar.setObjectName("ToolStatusBar")
        layout.addWidget(self.status_bar)

        self._refresh_cache_info()
        self._refresh_sysinfo()
        self._refresh_logs()

    def _open_db_management(self):
        dialog = DatabaseManagementDialog(self)
        dialog.exec()

    def _open_cache_management(self):
        dialog = CacheManagementDialog(self)
        dialog.exec()

    def _open_logs(self):
        dialog = LogViewerDialog(self)
        dialog.exec()

    def _open_sysinfo(self):
        dialog = SystemInfoDialog(self)
        dialog.exec()

    def run_diagnostics(self):
        self.diag_model.removeRows(0, self.diag_model.rowCount())
        self.progress_bar.show()
        self.diagnostics_btn.setEnabled(False)
        self.status_label.setText("Running diagnostics...")

        self._worker = DiagnosticWorker()
        self._thread = QThread()
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.finished.connect(self._thread.quit)
        self._worker.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.start()

    def _on_progress(self, message: str):
        self.status_label.setText(message)
        self.status_bar.setText(message)

    def _on_finished(self, results: list):
        self.progress_bar.hide()
        self.diagnostics_btn.setEnabled(True)
        self.status_label.setText("Diagnostics complete")
        self.status_bar.setText("Diagnostics complete")

        self.diag_model.removeRows(0, self.diag_model.rowCount())
        for name, status, details in results:
            row = [
                QStandardItem(name),
                QStandardItem("✅ OK" if status else "❌ Unavailable"),
                QStandardItem(details),
                QStandardItem(""),
            ]
            for item in row:
                item.setEditable(False)
            self.diag_model.appendRow(row)

    def _refresh_cache_info(self):
        try:
            config = get_config()
            cache_dir = Path(config.app.data_dir) / "cache"
            if cache_dir.exists():
                total_size = sum(f.stat().st_size for f in cache_dir.rglob("*") if f.is_file())
                file_count = sum(1 for f in cache_dir.rglob("*") if f.is_file())
                self.cache_size_label.setText(
                    f"Cache Size: {self._format_size(total_size)} | Files: {file_count}"
                )
            else:
                self.cache_size_label.setText("Cache Size: 0 B | Files: 0")
        except Exception as e:
            self.cache_size_label.setText(f"Error: {e}")

    @staticmethod
    def _format_size(bytes_val):
        for unit in ["B", "KB", "MB", "GB"]:
            if bytes_val < 1024:
                return f"{bytes_val:.1f} {unit}"
            bytes_val /= 1024
        return f"{bytes_val:.1f} TB"

    def _clear_cache(self):
        reply = QMessageBox.question(
            self,
            "Clear Cache",
            "Are you sure you want to clear all cached data?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            config = get_config()
            cache_dir = Path(config.app.data_dir) / "cache"
            if cache_dir.exists():
                shutil.rmtree(cache_dir)
            cache_dir.mkdir(parents=True, exist_ok=True)
            QMessageBox.information(self, "Success", "Cache cleared successfully")
            self._refresh_cache_info()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to clear cache: {e}")

    def _refresh_logs(self):
        try:
            config = get_config()
            log_path = Path(config.app.logs_dir) / "idfa.log"
            if log_path.exists():
                with log_path.open("r", encoding="utf-8") as file:
                    lines = file.readlines()[-1000:]
                self.logs_text.setPlainText("".join(lines))
                self.logs_text.moveCursor(QTextCursor.MoveOperation.End)
            else:
                self.logs_text.setPlainText("Log file not found")
        except Exception as e:
            self.logs_text.setPlainText(f"Error loading logs: {e}")

    def _filter_logs(self, level: str):
        self._refresh_logs()

    def _refresh_sysinfo(self):
        try:
            import platform
            import psutil

            info = [
                f"OS: {platform.system()} {platform.release()} ({platform.version()})",
                f"Architecture: {platform.machine()}",
                f"Processor: {platform.processor()}",
                f"Python: {sys.version.split()[0]}",
                f"PySide6: {self._get_pyside_version()}",
                f"CPU Cores: {psutil.cpu_count(logical=True)}",
                f"Memory: {psutil.virtual_memory().total / (1024**3):.1f} GB",
                f"Disk: {shutil.disk_usage(get_config().app.data_dir).total / (1024**3):.1f} GB",
            ]

            try:
                import pytsk3
                info.append("pytsk3: Available")
            except ImportError:
                info.append("pytsk3: Not installed (disk examination unavailable)")

            try:
                import pyewf
                info.append("pyewf: Available")
            except ImportError:
                info.append("pyewf: Not installed (E01 images unsupported)")

            self.sysinfo_text.setPlainText("\n".join(info))
        except Exception as e:
            self.sysinfo_text.setPlainText(f"Error: {e}")

    def _get_pyside_version(self):
        return pyside_version()


class DiagnosticWorker(QObject):
    """Background worker for running diagnostics."""
    progress = Signal(str)
    finished = Signal(list)

    def __init__(self):
        super().__init__()

    def run(self):
        checks = [
            ("Database", self._check_database),
            ("Data folder", self._check_data_folder),
            ("PySide6", self._check_pyside6),
            ("Forensic Worker", self._check_worker),
            ("pytsk3", self._check_ptsk3),
            ("EWF images (pyewf)", self._check_pyewf),
            ("Ollama", self._check_ollama),
            ("Embedding model", self._check_embeddings),
            ("Qdrant", self._check_qdrant),
            ("ReportLab", self._check_reportlab),
            ("Disk Space", self._check_disk_space),
        ]

        results = []
        for name, check_func in checks:
            self.progress.emit(f"Checking {name}...")
            try:
                result = check_func()
                results.append((name, *result))
            except Exception as e:
                results.append((name, False, f"Error: {e}"))
            self.progress.emit(f"Done: {name}")

        self.finished.emit(results)

    def _check_database(self):
        try:
            from app.db.session import init_db, get_engine
            from sqlalchemy import text
            engine = get_engine()
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return True, "SQLite connected and accessible"
        except Exception as e:
            return False, f"Database error: {e}"

    def _check_pyside6(self):
        try:
            version = pyside_version()
            if version == "Unknown":
                return False, "PySide6 is installed but its version is unknown"
            return True, f"PySide6 {version}"
        except Exception as e:
            return False, str(e)

    def _check_worker(self):
        try:
            import httpx
            config = get_config()
            response = httpx.get(f"{config.worker.url}/health", timeout=5.0)
            if response.status_code == 200:
                data = response.json()
                return True, f"Worker healthy: {data}"
            return False, f"Worker returned {response.status_code}"
        except Exception as e:
            return False, f"Worker unreachable: {e}"

    def _check_ptsk3(self):
        """pytsk3 runs inside the GUI process now, so check the import."""
        try:
            import pytsk3
            return True, f"pytsk3 {getattr(pytsk3, '__version__', 'available')}"
        except ImportError:
            return False, "pytsk3 is not installed: pip install pytsk3"

    def _check_pyewf(self):
        """EWF (E01) support is optional and comes from ``libewf-python``."""
        try:
            import pyewf
            version = getattr(pyewf, "__version__", "available")
            return True, f"pyewf {version} (E01 images supported)"
        except ImportError:
            return False, "pyewf is not installed: pip install libewf-python"

    def _check_data_folder(self):
        """The data folder holds the database, evidence and vector store."""
        try:
            from app.config import check_data_folder

            config = get_config()
            usable, reason = check_data_folder(config.app.data_dir)
            return usable, config.app.data_dir if usable else f"{config.app.data_dir}: {reason}"
        except Exception as e:
            return False, str(e)

    def _check_ollama(self):
        try:
            import httpx
            config = get_config()
            response = httpx.get(f"{config.ollama.host}/api/tags", timeout=5.0)
            if response.status_code == 200:
                models = response.json().get("models", [])
                model_names = [m["name"] for m in models]
                return True, f"Ollama running with {len(model_names)} model(s): {', '.join(model_names)}"
            return False, f"Ollama returned {response.status_code}"
        except Exception as e:
            return False, f"Ollama unreachable: {e}"

    def _check_embeddings(self):
        """Semantic search needs the embedding model pulled in Ollama."""
        try:
            import httpx
            from app.ai.embeddings import model_id

            config = get_config()
            response = httpx.get(f"{config.ollama.host}/api/tags", timeout=5.0)
            if response.status_code != 200:
                return False, f"Ollama returned {response.status_code}; cannot verify {model_id()}"
            names = [m.get("name", "") for m in response.json().get("models", [])]
            found = any(name == model_id() or name.startswith(f"{model_id()}:") for name in names)
            if found:
                return True, f"{model_id()} available ({config.qdrant.vector_size}-dim vectors)"
            return False, (
                f"{model_id()} is not pulled: run \"ollama pull {model_id()}\" "
                "to enable semantic search"
            )
        except Exception as e:
            return False, f"Embedding check failed: {e}"

    def _check_qdrant(self):
        try:
            import httpx
            config = get_config()
            response = httpx.get(f"{config.qdrant.url}/healthz", timeout=5.0)
            if response.status_code == 200:
                return True, f"Qdrant healthy at {config.qdrant.url}"
            return False, f"Qdrant returned {response.status_code}"
        except Exception as e:
            return False, f"Qdrant unreachable: {e}"

    def _check_reportlab(self):
        try:
            import reportlab
            return True, f"ReportLab {reportlab.Version}"
        except Exception as e:
            return False, str(e)

    def _check_disk_space(self):
        try:
            import shutil
            data_dir = get_config().app.data_dir
            total, used, free = shutil.disk_usage(data_dir)
            free_gb = free / (1024**3)
            total_gb = total / (1024**3)
            return free_gb > 1, f"Data drive: {free_gb:.1f}GB free of {total_gb:.1f}GB"
        except Exception as e:
            return False, f"Disk check failed: {e}"


class DatabaseManagementDialog(QDialog):
    """Dialog for database management operations."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Database Management")
        self.setModal(True)
        self.resize(640, 520)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(Spacing.LG, Spacing.LG, Spacing.LG, Spacing.LG)
        layout.setSpacing(Spacing.MD)

        header = QVBoxLayout()
        header.setSpacing(Spacing.XS)
        title = QLabel("Database Management")
        title.setFont(
            QFont(Typography.FONT_FAMILY, Typography.HEADING_MD[0], Typography.HEADING_MD[1])
        )
        header.addWidget(title)

        subtitle = QLabel("Back up, restore, and maintain the local SQLite case database.")
        subtitle.setStyleSheet(f"color: {Color.TEXT_SECONDARY.name()};")
        subtitle.setWordWrap(True)
        header.addWidget(subtitle)
        layout.addLayout(header)

        # Backup section
        backup_group = QGroupBox("Backup & Restore")
        backup_layout = QVBoxLayout(backup_group)
        backup_layout.setContentsMargins(Spacing.MD, Spacing.LG, Spacing.MD, Spacing.MD)
        backup_layout.setSpacing(Spacing.MD)

        path_label = QLabel("Backup File")
        path_label.setProperty("fieldLabel", True)
        backup_layout.addWidget(path_label)

        backup_row = QHBoxLayout()
        backup_row.setSpacing(Spacing.SM)
        self.backup_path = QLineEdit()
        self.backup_path.setPlaceholderText("Choose a destination file for the backup...")
        self.backup_path.setReadOnly(True)
        backup_row.addWidget(self.backup_path, 1)

        browse_btn = QPushButton("Browse...")
        browse_btn.setProperty("secondary", True)
        browse_btn.clicked.connect(self._browse_backup)
        backup_row.addWidget(browse_btn)
        backup_layout.addLayout(backup_row)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(Spacing.SM)
        backup_btn = QPushButton("Backup Database")
        backup_btn.clicked.connect(self._backup_database)
        btn_row.addWidget(backup_btn)

        restore_btn = QPushButton("Restore Database")
        restore_btn.setProperty("secondary", True)
        restore_btn.clicked.connect(self._restore_database)
        btn_row.addWidget(restore_btn)
        btn_row.addStretch()
        backup_layout.addLayout(btn_row)

        layout.addWidget(backup_group)

        # Maintenance section
        maint_group = QGroupBox("Maintenance")
        maint_layout = QVBoxLayout(maint_group)
        maint_layout.setContentsMargins(Spacing.MD, Spacing.LG, Spacing.MD, Spacing.MD)
        maint_layout.setSpacing(Spacing.MD)

        maint_info = QLabel("Compact and re-index the database to improve query performance.")
        maint_info.setStyleSheet(f"color: {Color.TEXT_SECONDARY.name()};")
        maint_info.setWordWrap(True)
        maint_layout.addWidget(maint_info)

        maint_btn_row = QHBoxLayout()
        maint_btn_row.setSpacing(Spacing.SM)
        vacuum_btn = QPushButton("VACUUM")
        vacuum_btn.setProperty("secondary", True)
        vacuum_btn.clicked.connect(self._vacuum_db)
        maint_btn_row.addWidget(vacuum_btn)

        analyze_btn = QPushButton("ANALYZE")
        analyze_btn.setProperty("secondary", True)
        analyze_btn.clicked.connect(self._analyze_db)
        maint_btn_row.addWidget(analyze_btn)
        maint_btn_row.addStretch()
        maint_layout.addLayout(maint_btn_row)

        layout.addWidget(maint_group)
        layout.addStretch()

        # Buttons
        btn_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

    def _browse_backup(self):
        path, _ = QFileDialog.getSaveFileName(self, "Backup Database", "idfa_backup.db", "SQLite (*.db *.sqlite)")
        if path:
            self.backup_path.setText(path)

    def _backup_database(self):
        path = self.backup_path.text()
        if not path:
            QMessageBox.warning(self, "No Path", "Please select a backup file path.")
            return
        try:
            from app.config import get_config
            import shutil
            config = get_config()
            db_path = config.database.url.replace("sqlite:///", "")
            shutil.copy2(db_path, path)
            QMessageBox.information(self, "Success", f"Database backed up to {path}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Backup failed: {e}")

    def _restore_database(self):
        path, _ = QFileDialog.getOpenFileName(self, "Restore Database", "", "SQLite (*.db *.sqlite)")
        if path:
            reply = QMessageBox.warning(self, "Confirm Restore",
                "This will overwrite the current database. Continue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.Yes:
                try:
                    from app.config import get_config
                    import shutil
                    config = get_config()
                    db_path = config.database.url.replace("sqlite:///", "")
                    shutil.copy2(path, db_path)
                    QMessageBox.information(self, "Success", "Database restored. Please restart the application.")
                except Exception as e:
                    QMessageBox.critical(self, "Error", f"Restore failed: {e}")

    def _vacuum_db(self):
        try:
            from app.db.session import get_engine
            from sqlalchemy import text
            engine = get_engine()
            with engine.connect() as conn:
                conn.execute(text("VACUUM"))
            QMessageBox.information(self, "Success", "Database vacuumed successfully")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Vacuum failed: {e}")

    def _analyze_db(self):
        try:
            from app.db.session import get_engine
            from sqlalchemy import text
            engine = get_engine()
            with engine.connect() as conn:
                conn.execute(text("ANALYZE"))
            QMessageBox.information(self, "Success", "Database analyzed successfully")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Analyze failed: {e}")


class CacheManagementDialog(QDialog):
    """Dialog for cache management."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Cache Management")
        self.setModal(True)
        self.resize(520, 360)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(Spacing.LG, Spacing.LG, Spacing.LG, Spacing.LG)
        layout.setSpacing(Spacing.MD)

        header = QVBoxLayout()
        header.setSpacing(Spacing.XS)
        title = QLabel("Cache Management")
        title.setFont(
            QFont(Typography.FONT_FAMILY, Typography.HEADING_MD[0], Typography.HEADING_MD[1])
        )
        header.addWidget(title)

        subtitle = QLabel("Review and clear temporary files stored by the application.")
        subtitle.setStyleSheet(f"color: {Color.TEXT_SECONDARY.name()};")
        subtitle.setWordWrap(True)
        header.addWidget(subtitle)
        layout.addLayout(header)

        # Cache info
        info_group = QGroupBox("Cache Information")
        info_layout = QVBoxLayout(info_group)
        info_layout.setContentsMargins(Spacing.MD, Spacing.LG, Spacing.MD, Spacing.MD)
        info_layout.setSpacing(Spacing.SM)

        self.cache_size_label = QLabel("Cache Size: calculating...")
        self.cache_size_label.setFont(
            QFont(Typography.FONT_FAMILY, Typography.BODY_MD[0], Typography.BODY_MD[1])
        )
        info_layout.addWidget(self.cache_size_label)

        self.cache_count_label = QLabel("Files: calculating...")
        self.cache_count_label.setStyleSheet(f"color: {Color.TEXT_SECONDARY.name()};")
        info_layout.addWidget(self.cache_count_label)

        layout.addWidget(info_group)
        layout.addStretch()

        # Actions
        btn_row = QHBoxLayout()
        btn_row.setSpacing(Spacing.SM)
        clear_btn = QPushButton("Clear All Cache")
        clear_btn.setProperty("danger", True)
        clear_btn.clicked.connect(self._clear_cache)
        btn_row.addWidget(clear_btn)

        refresh_btn = QPushButton("Refresh Info")
        refresh_btn.setProperty("secondary", True)
        refresh_btn.clicked.connect(self._refresh_info)
        btn_row.addWidget(refresh_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        # Buttons
        btn_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

        # Initial load
        self._refresh_info()

    def _refresh_info(self):
        try:
            from app.config import get_config
            config = get_config()
            cache_dir = Path(config.app.data_dir) / "cache"
            if cache_dir.exists():
                total_size = sum(f.stat().st_size for f in cache_dir.rglob("*") if f.is_file())
                file_count = sum(1 for f in cache_dir.rglob("*") if f.is_file())
                self.cache_size_label.setText(f"Cache Size: {self._format_size(total_size)}")
                self.cache_count_label.setText(f"Files: {file_count}")
            else:
                self.cache_size_label.setText("Cache Size: 0 B")
                self.cache_count_label.setText("Files: 0")
        except Exception as e:
            self.cache_size_label.setText(f"Error: {e}")

    def _format_size(self, bytes_val):
        for unit in ["B", "KB", "MB", "GB"]:
            if bytes_val < 1024:
                return f"{bytes_val:.1f} {unit}"
            bytes_val /= 1024
        return f"{bytes_val:.1f} TB"

    def _clear_cache(self):
        reply = QMessageBox.question(self, "Clear Cache",
            "Are you sure you want to clear all cached data?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            try:
                from app.config import get_config
                import shutil
                config = get_config()
                cache_dir = Path(config.app.data_dir) / "cache"
                if cache_dir.exists():
                    shutil.rmtree(cache_dir)
                    cache_dir.mkdir(parents=True)
                QMessageBox.information(self, "Success", "Cache cleared successfully")
                self._refresh_info()
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to clear cache: {e}")


class LogViewerDialog(QDialog):
    """Dialog for viewing application logs."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Log Viewer")
        self.setModal(True)
        self.resize(800, 600)
        self._setup_ui()
        self._load_logs()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(Spacing.LG, Spacing.LG, Spacing.LG, Spacing.LG)
        layout.setSpacing(Spacing.MD)

        # Header
        header = QHBoxLayout()
        header.setSpacing(Spacing.SM)

        title = QLabel("Application Logs")
        title.setFont(
            QFont(Typography.FONT_FAMILY, Typography.HEADING_MD[0], Typography.HEADING_MD[1])
        )
        header.addWidget(title)
        header.addStretch()

        filter_label = QLabel("Level")
        filter_label.setProperty("fieldLabel", True)
        header.addWidget(filter_label, 0, Qt.AlignmentFlag.AlignVCenter)

        self.filter_combo = QComboBox()
        self.filter_combo.addItems(["All", "DEBUG", "INFO", "WARNING", "ERROR"])
        self.filter_combo.setMinimumWidth(140)
        self.filter_combo.currentTextChanged.connect(self._filter_logs)
        header.addWidget(self.filter_combo)

        refresh_btn = QPushButton("Refresh")
        refresh_btn.setProperty("secondary", True)
        refresh_btn.clicked.connect(self._load_logs)
        header.addWidget(refresh_btn)
        layout.addLayout(header)

        # Log display
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFont(QFont("Consolas", 10))
        self.log_text.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self.log_text.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        layout.addWidget(self.log_text, 1)

        # Buttons
        btn_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

    def _load_logs(self):
        try:
            from app.config import get_config
            config = get_config()
            log_path = Path(config.app.logs_dir) / "idfa.log"
            if log_path.exists():
                with open(log_path, "r", encoding="utf-8") as f:
                    lines = f.readlines()[-1000:]  # Last 1000 lines
                self.log_text.setPlainText("".join(lines))
                # Scroll to bottom
                cursor = self.log_text.textCursor()
                cursor.movePosition(QTextCursor.MoveOperation.End)
                self.log_text.setTextCursor(cursor)
            else:
                self.log_text.setPlainText("Log file not found")
        except Exception as e:
            self.log_text.setPlainText(f"Error loading logs: {e}")

    def _filter_logs(self, level: str):
        self._load_logs()
        if level != "All":
            # Simple filtering - hide lines not containing the level
            pass  # Could implement filtering


class SystemInfoDialog(QDialog):
    """Dialog showing system information."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("System Information")
        self.setModal(True)
        self.resize(600, 500)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(Spacing.LG, Spacing.LG, Spacing.LG, Spacing.LG)
        layout.setSpacing(Spacing.MD)

        header = QVBoxLayout()
        header.setSpacing(Spacing.XS)
        title = QLabel("System Information")
        title.setFont(
            QFont(Typography.FONT_FAMILY, Typography.HEADING_MD[0], Typography.HEADING_MD[1])
        )
        header.addWidget(title)

        subtitle = QLabel("Host platform, hardware, and forensic library availability.")
        subtitle.setStyleSheet(f"color: {Color.TEXT_SECONDARY.name()};")
        subtitle.setWordWrap(True)
        header.addWidget(subtitle)
        layout.addLayout(header)

        self.info_text = QTextEdit()
        self.info_text.setReadOnly(True)
        self.info_text.setFont(QFont("Consolas", 10))
        self.info_text.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        layout.addWidget(self.info_text, 1)

        btn_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

        self._load_info()

    def _load_info(self):
        import platform
        import sys
        import psutil

        info = []
        info.append(f"OS: {platform.system()} {platform.release()} ({platform.version()})")
        info.append(f"Architecture: {platform.machine()}")
        info.append(f"Processor: {platform.processor()}")
        info.append(f"Python: {sys.version.split()[0]}")
        info.append(f"PySide6: {self._get_pyside_version()}")
        info.append(f"CPU Cores: {psutil.cpu_count(logical=True)}")
        info.append(f"Memory: {psutil.virtual_memory().total / (1024**3):.1f} GB")
        info.append(f"Disk: {shutil.disk_usage(get_config().app.data_dir).total / (1024**3):.1f} GB")

        try:
            import pytsk3
            info.append("pytsk3: Available")
        except ImportError:
            info.append("pytsk3: Not installed (disk examination unavailable)")

        try:
            import pyewf
            info.append("pyewf: Available")
        except ImportError:
            info.append("pyewf: Not installed (E01 images unsupported)")

        self.info_text.setPlainText("\n".join(info))

    def _get_pyside_version(self):
        return pyside_version()
