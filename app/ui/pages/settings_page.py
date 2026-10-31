"""Five category panes with flat, content-sized sections and one save bar.

Chat connections, background analysis and search indexing are separate workflows.
Provider editors keep drafts until Save; process and storage actions are immediate.
"""
from __future__ import annotations

import os
import time
import uuid

import httpx
from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.config import (
    AIConnectionConfig,
    AIModelConfig,
    cloud_api_key,
    connection_api_key,
    database_path,
    describe_layout_paths,
    free_space_bytes,
    get_config,
    get_config_path,
    reset_config,
    save_config,
)
from app.firstrun import apply_data_dir
from app.i18n import DEFAULT_LANGUAGE, LanguageManager, available_languages, tr
from app.ui import qt_threads
from app.ui.base import ResponsivePage
from app.ui.dialogs.data_folder_dialog import ChangeDataFolderDialog
from app.ui.theme.manager import ThemeManager
from app.ui.theme.tokens import Spacing, Typography
from app.util import services

# Settings read as a form, not a dashboard: cap the column on wide monitors.
CONTENT_MAX_WIDTH = 880

# Provider dialogs retain paired fields; main panes use label/control rows.
CONTROL_MAX_WIDTH = 420
PATH_LABEL_WIDTH = 96
NAV_WIDTH = 176

MODE_LOCAL = "ollama"
MODE_CLOUD = "openai"

NAV_ITEMS = (
    ("general", "General"),
    ("ai", "AI & Models"),
    ("services", "Services"),
    ("data", "Data & Storage"),
    ("security", "Security"),
)

SERVICE_LABELS = {
    "worker": "Forensic worker",
    "qdrant": "Qdrant",
    "ollama": "Ollama",
}

# Presets save typing the one value people get wrong. "custom" keeps the
# endpoint editable for any other OpenAI-compatible service.
CLOUD_PRESETS = {
    "nim": {
        "label": "NVIDIA NIM",
        "url": "https://integrate.api.nvidia.com/v1",
        "models": [
            "meta/llama-3.3-70b-instruct",
            "nvidia/llama-3.1-nemotron-70b-instruct",
            "mistralai/mixtral-8x7b-instruct-v0.1",
        ],
    },
    "openai": {
        "label": "OpenAI",
        "url": "https://api.openai.com/v1",
        "models": ["gpt-4o-mini", "gpt-4.1-mini", "gpt-4o"],
    },
    "custom": {
        "label": "Custom endpoint",
        "url": "",
        "models": [],
    },
}


class _TaskWorker(QThread):
    """Run one blocking call off the GUI thread and report ``(ok, message)``."""

    finished_with_result = Signal(bool, str)

    def __init__(self, action):
        super().__init__()
        self._action = action

    def run(self) -> None:
        try:
            ok, message = self._action()
        except Exception as exc:  # noqa: BLE001 - surfaced to the investigator
            ok, message = False, str(exc)
        self.finished_with_result.emit(ok, message)


class _FeedbackLabel(QLabel):
    """Reserve space for feedback only while there is something to report."""

    def __init__(self, text=""):
        super().__init__(text)
        self.setVisible(bool(text))

    def setText(self, text):  # noqa: N802 - Qt override
        super().setText(text)
        self.setVisible(bool(text))

    def clear(self):
        self.setText("")


class _StatusWorker(QThread):
    """Collect service health without blocking the window."""

    finished_with_result = Signal(object)

    def run(self) -> None:
        try:
            result = services.statuses()
        except Exception:  # noqa: BLE001 - an empty list is a safe answer
            result = []
        self.finished_with_result.emit(result)


class _ModelDiscoveryWorker(QThread):
    """List model IDs without transmitting evidence or exposing provider errors."""

    finished_with_result = Signal(object, object, str)

    def __init__(self, request, token):
        super().__init__()
        self._request = request
        self._token = token

    def run(self):
        provider, base_url, api_key = self._request
        try:
            headers = {"Authorization": f"Bearer {api_key}"} if provider == MODE_CLOUD else {}
            path = "/models" if provider == MODE_CLOUD else "/api/tags"
            response = httpx.get(
                f"{base_url}{path}", headers=headers,
                timeout=httpx.Timeout(5.0, connect=3.0), follow_redirects=False,
            )
            if response.status_code != 200:
                self.finished_with_result.emit(self._token, [], "Could not load models from the provider.")
                return
            payload = response.json()
            entries = payload.get("data" if provider == MODE_CLOUD else "models")
            if not isinstance(entries, list):
                raise ValueError("Invalid model list")
            field = "id" if provider == MODE_CLOUD else "name"
            ids = list(dict.fromkeys(
                entry[field].strip() for entry in entries
                if isinstance(entry, dict) and isinstance(entry.get(field), str) and entry[field].strip()
            ))
            self.finished_with_result.emit(self._token, ids, "")
        except Exception:  # noqa: BLE001 - request and response details may contain secrets
            self.finished_with_result.emit(self._token, [], "Could not load models from the provider.")


class _CloudTestWorker(QThread):
    """Send a one-token request so a bad key is found before the demo."""

    finished_with_result = Signal(bool, str)

    def __init__(self, base_url: str, api_key: str, model: str):
        super().__init__()
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model

    def run(self) -> None:
        started = time.monotonic()
        try:
            response = httpx.post(
                f"{self._base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={
                    "model": self._model,
                    "messages": [{"role": "user", "content": "ping"}],
                    "max_tokens": 1,
                },
                timeout=20.0,
            )
        except httpx.TimeoutException:
            self.finished_with_result.emit(False, "Timed out after 20 seconds.")
            return
        except Exception:  # noqa: BLE001 - exception details can contain credentials
            self.finished_with_result.emit(False, "Could not connect to the provider.")
            return

        elapsed_ms = int((time.monotonic() - started) * 1000)
        if response.status_code == 200:
            self.finished_with_result.emit(True, f"Connected · {elapsed_ms} ms")
        elif response.status_code in (401, 403):
            self.finished_with_result.emit(False, "The provider rejected this API key.")
        else:
            self.finished_with_result.emit(
                False, f"HTTP {response.status_code} from provider."
            )


# A QThread that is destroyed while still running aborts the whole process.
# Workers are therefore kept alive here - not as children of the page - until
# they report completion, so leaving Settings (or dropping the page in a test)
# can never take a running thread down with it.
_LIVE_WORKERS: set[QThread] = set()


def _track(worker: QThread) -> None:
    _LIVE_WORKERS.add(worker)
    qt_threads.track(worker)
    worker.finished.connect(lambda w=worker: _LIVE_WORKERS.discard(w))
    worker.finished.connect(worker.deleteLater)


class SettingsPage(ResponsivePage):
    """Editor for the application-wide configuration in ``config.yaml``."""

    # Emitted after Save/Reset so the running application can adopt the new
    # values without a restart for everything that supports it.
    settings_applied = Signal()

    def __init__(self, parent: QWidget | None = None):
        # Built during _setup_layout, so the collections must exist first.
        self._panes: list[tuple[QScrollArea, QWidget]] = []
        self._service_rows: dict[str, dict[str, QWidget]] = {}
        self._service_workers: list[QThread] = []
        self._status_worker: _StatusWorker | None = None
        self._test_worker: _CloudTestWorker | None = None
        self._services_index = 0
        self.ai_mode = MODE_LOCAL
        self._connections = []
        self._connection_index = -1
        self._discovery_generation = 0
        self._discovery_worker = None
        super().__init__(parent=parent)
        # Quitting the application must not leave a poll or a connection test
        # running: the page's slots would disappear before the thread ends.
        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.shutdown)
        self._load_current_settings()

    # ------------------------------------------------------------------ layout
    def _setup_layout(self):
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self._nav_panel = self._build_nav()
        outer.addWidget(self._nav_panel)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)

        self._stack = QStackedWidget()
        right_layout.addWidget(self._stack, 1)
        right_layout.addWidget(self._build_footer())
        outer.addWidget(right, 1)

        self._build_general_pane()
        self._build_ai_pane()
        self._build_services_pane()
        self._build_data_pane()
        self._build_security_pane()
        self._switch_pane(0)

    def _build_nav(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("SettingsNav")
        panel.setFrameShape(QFrame.Shape.NoFrame)
        panel.setFixedWidth(NAV_WIDTH)

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(Spacing.MD, Spacing.LG, Spacing.MD, Spacing.LG)
        layout.setSpacing(Spacing.XS)

        title = QLabel("Settings")
        title.setProperty("pageTitle", True)
        title.setFont(
            QFont(
                Typography.FONT_FAMILY,
                Typography.HEADING_LG[0],
                Typography.HEADING_LG[1],
            )
        )
        layout.addWidget(title)
        layout.addSpacing(Spacing.MD)

        self._nav_group = QButtonGroup(self)
        self._nav_group.setExclusive(True)
        self.nav_buttons: list[QPushButton] = []
        for index, (_key, label) in enumerate(NAV_ITEMS):
            button = QPushButton(label.replace("&", "&&"))
            button.setCheckable(True)
            button.setProperty("compact", True)
            button.setFixedHeight(38)
            button.setProperty("navItem", True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _checked=False, i=index: self._switch_pane(i))
            self._nav_group.addButton(button, index)
            self.nav_buttons.append(button)
            layout.addWidget(button)

        layout.addStretch(1)
        return panel

    def _add_pane(self) -> QVBoxLayout:
        """Create a scrolling pane and return the layout of its centred column."""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        content = QWidget()
        scroll.setWidget(content)

        centring = QHBoxLayout(content)
        centring.setContentsMargins(Spacing.LG, Spacing.LG, Spacing.LG, Spacing.LG)
        centring.setSpacing(0)

        column = QWidget()
        column.setMaximumWidth(CONTENT_MAX_WIDTH)
        column.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        centring.addWidget(column)
        centring.addStretch(1)

        layout = QVBoxLayout(column)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(Spacing.MD)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        title = QLabel(NAV_ITEMS[len(self._panes)][1])
        title.setProperty("pageTitle", True)
        title.setFont(QFont(
            Typography.FONT_FAMILY, Typography.HEADING_LG[0], Typography.HEADING_LG[1]
        ))
        layout.addWidget(title)
        descriptions = (
            "Make IDFA comfortable to use and choose how pages refresh.",
            "Choose chat connections separately from background analysis and semantic search.",
            "Manage local processes and the forensic worker connection.",
            "Manage the folder that holds your investigation data.",
            "Configure session and authentication preferences.",
        )
        description = QLabel(descriptions[len(self._panes)])
        description.setWordWrap(True)
        description.setProperty("sectionHint", True)
        layout.addWidget(description)

        self._stack.addWidget(scroll)
        self._panes.append((scroll, column))
        return layout

    def _switch_pane(self, index: int) -> None:
        if not (0 <= index < self._stack.count()):
            return
        self._stack.setCurrentIndex(index)
        for position, button in enumerate(self.nav_buttons):
            button.setChecked(position == index)
        self._fit_column()
        self._update_services_timer()

    # ---------------------------------------------------------------- general
    def _build_general_pane(self):
        layout = self._add_pane()

        _card, grid = self._add_card(
            layout,
            "Appearance",
            "Theme and language are previewed immediately. Save Settings to keep your choices.",
        )

        self.theme_combo = QComboBox()
        # The stored value lives in the item data so translating the visible
        # label can never change what Settings saves.
        for label, value in (("Light", "light"), ("Dark", "dark"), ("System", "system")):
            self.theme_combo.addItem(label, value)
        self.theme_combo.currentIndexChanged.connect(self._preview_theme)
        self._add_field(grid, 0, 0, "Theme", self.theme_combo)

        self.language_combo = QComboBox()
        for name in available_languages():
            self.language_combo.addItem(name, name)
        self.language_combo.currentIndexChanged.connect(self._preview_language)
        self._add_field(grid, 0, 1, "Language", self.language_combo)

        _card, grid = self._add_card(
            layout,
            "Background refresh",
            "Reload the open page on a timer so new examination output appears "
            "without pressing Refresh.",
        )

        self.auto_refresh_check = QCheckBox("Reload the open page automatically")
        self.auto_refresh_check.toggled.connect(
            lambda checked: self.refresh_interval.setEnabled(checked)
        )
        self._add_field(
            grid, 0, 0, "Automatic updates", self.auto_refresh_check, colspan=2
        )

        self.refresh_interval = QSpinBox()
        self.refresh_interval.setRange(10, 3600)
        self.refresh_interval.setSuffix(" seconds")
        self.refresh_interval.setValue(30)
        self._add_field(grid, 1, 0, "Refresh interval", self.refresh_interval)

        layout.addStretch(1)

    # --------------------------------------------------------------------- AI
    def _build_ai_pane(self):
        layout = self._add_pane()

        # Keep the saved background provider for compatibility, without a
        # separate mode selector in the chat-connection workflow.
        self.analysis_provider = QComboBox(self)
        self.analysis_provider.addItem("Local (Ollama)", MODE_LOCAL)
        self.analysis_provider.addItem("Cloud", MODE_CLOUD)
        self.analysis_provider.currentIndexChanged.connect(
            lambda _index: setattr(self, "ai_mode", self.analysis_provider.currentData())
        )
        self._build_connections_card(layout)
        background = QWidget()
        background_layout = QVBoxLayout(background)
        background_layout.setContentsMargins(0, 0, 0, 0)
        background_layout.setSpacing(Spacing.LG)
        layout.addWidget(background)

        # --- Offline -----------------------------------------------------
        self._offline_card, grid = self._add_card(
            background_layout,
            "Background analysis",
            "Automatic entity analysis uses its own provider, independent of chat connections.",
        )
        self._add_field(grid, 0, 0, "Analysis provider", self.analysis_provider)
        self.analysis_provider.currentIndexChanged.connect(
            lambda: self.set_ai_mode(self.analysis_provider.currentData()))

        self.ollama_model = QComboBox()
        self.ollama_model.setEditable(True)
        self.ollama_model.addItems(["phi3:mini", "llama3.2:3b", "qwen2.5:3b"])
        self.ollama_model.setCurrentText("phi3:mini")
        self._add_field(grid, 0, 0, "Background chat model", self.ollama_model)

        _section, grid = self._add_card(
            background_layout, "Embeddings & semantic search",
            "Indexing settings apply to new vectors. Re-index existing artifacts after "
            "changing the model or passages.",
        )
        # The two frequently used options belong together; unlike the generic
        # settings rows, these are compact caption-above-control cells.
        grid.setProperty("settingsRows", False)
        self.embedding_provider = QComboBox()
        self.embedding_provider.addItem("Local (Ollama)", MODE_LOCAL)
        self.embedding_provider.addItem("Cloud", MODE_CLOUD)
        self.embedding_provider.setToolTip(
            "Cloud embeddings send artifact text to the provider; case consent is required."
        )
        self._add_field(grid, 0, 0, "Embedding source", self.embedding_provider)
        self.embedding_provider.currentIndexChanged.connect(self._update_background_visibility)

        self.embedding_model = QComboBox()
        self.embedding_model.setEditable(True)
        self.embedding_model.addItems(["all-minilm", "nomic-embed-text"])
        self.embedding_model.setCurrentText("all-minilm")
        self._add_field(grid, 0, 1, "Embedding model", self.embedding_model)

        self._embedding_advanced_toggle = QToolButton()
        self._embedding_advanced_toggle.setText("Advanced indexing settings")
        self._embedding_advanced_toggle.setCheckable(True)
        self._embedding_advanced_toggle.setArrowType(Qt.ArrowType.RightArrow)
        self._embedding_advanced_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        grid.addWidget(self._embedding_advanced_toggle, 1, 0, 1, 2, Qt.AlignmentFlag.AlignLeft)
        self._embedding_advanced_content = QWidget()
        advanced_grid = QGridLayout(self._embedding_advanced_content)
        advanced_grid.setContentsMargins(0, 0, 0, 0)
        advanced_grid.setHorizontalSpacing(Spacing.LG)
        advanced_grid.setVerticalSpacing(Spacing.MD)
        advanced_grid.setColumnStretch(0, 1)
        advanced_grid.setColumnStretch(1, 1)
        grid.addWidget(self._embedding_advanced_content, 2, 0, 1, 2)
        self._embedding_advanced_content.hide()
        self._embedding_advanced_toggle.toggled.connect(self._embedding_advanced_content.setVisible)
        self._embedding_advanced_toggle.toggled.connect(
            lambda expanded: self._embedding_advanced_toggle.setArrowType(
                Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow))

        self.embedding_chunk_size = QSpinBox()
        self.embedding_chunk_size.setRange(100, 20_000)
        self.embedding_chunk_size.setSingleStep(100)
        self.embedding_chunk_size.setSuffix(" chars")
        self.embedding_chunk_size.setToolTip(
            "Characters per semantic passage. Larger passages carry more context; "
            "smaller passages can improve topical precision. Changing this requires re-indexing."
        )
        self._add_field(advanced_grid, 0, 0, "Search chunk size", self.embedding_chunk_size)

        self.embedding_chunk_overlap = QSpinBox()
        self.embedding_chunk_overlap.setRange(0, 19_900)
        self.embedding_chunk_overlap.setSingleStep(50)
        self.embedding_chunk_overlap.setSuffix(" chars")
        self.embedding_chunk_overlap.setToolTip(
            "Repeated characters between passages. Must remain smaller than chunk size."
        )
        self._add_field(advanced_grid, 0, 1, "Chunk overlap", self.embedding_chunk_overlap)

        self.embedding_chunk_size.valueChanged.connect(
            lambda size: self.embedding_chunk_overlap.setMaximum(size - 1)
        )

        self.embedding_batch_size = QSpinBox()
        self.embedding_batch_size.setRange(1, 512)
        self.embedding_batch_size.setToolTip(
            "Passages sent per embedding request. Reduce this if the model runs out of memory."
        )
        self._add_field(advanced_grid, 1, 0, "Embedding batch size", self.embedding_batch_size)

        hint = QLabel(
            "all-minilm produces the 384-dimension vectors the existing search "
            "index expects. Changing the model or chunk settings requires re-indexing "
            "the affected case artifacts."
        )
        hint.setProperty("sectionHint", True)
        hint.setWordWrap(True)
        advanced_grid.addWidget(hint, 2, 0, 1, 2)

        # --- Cloud -------------------------------------------------------
        self._background_cloud_toggle = QToolButton()
        self._background_cloud_toggle.setText("Background cloud credentials")
        self._background_cloud_toggle.setCheckable(True)
        self._background_cloud_toggle.setArrowType(Qt.ArrowType.RightArrow)
        self._background_cloud_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        background_layout.addWidget(self._background_cloud_toggle, 0, Qt.AlignmentFlag.AlignLeft)
        self._background_cloud_content = QWidget()
        cloud_layout = QVBoxLayout(self._background_cloud_content)
        cloud_layout.setContentsMargins(0, 0, 0, 0)
        background_layout.addWidget(self._background_cloud_content)
        self._background_cloud_content.hide()
        self._background_cloud_toggle.toggled.connect(self._background_cloud_content.setVisible)
        self._background_cloud_toggle.toggled.connect(
            lambda expanded: self._background_cloud_toggle.setArrowType(
                Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow))
        self._cloud_card, grid = self._add_card(
            cloud_layout,
            "Background cloud provider",
            "Used only for background analysis and cloud embeddings. The key is encrypted for this "
            "Windows account before it is written to disk.",
        )

        self.cloud_preset = QComboBox()
        for key, preset in CLOUD_PRESETS.items():
            self.cloud_preset.addItem(preset["label"], key)
        self.cloud_preset.currentIndexChanged.connect(self._on_preset_changed)
        self._add_field(grid, 0, 0, "Provider", self.cloud_preset)

        self.cloud_model = QComboBox()
        self.cloud_model.setEditable(True)
        self._add_field(grid, 0, 1, "Model ID", self.cloud_model)

        self.cloud_endpoint = QLineEdit()
        self.cloud_endpoint.setPlaceholderText("https://…/v1")
        self._add_field(
            grid, 1, 0, "Endpoint", self.cloud_endpoint, colspan=2, width=None
        )

        self.cloud_api_key = QLineEdit()
        self.cloud_api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.cloud_api_key.setPlaceholderText("Paste the provider API key")

        self.reveal_btn = QPushButton("Show")
        self.reveal_btn.setProperty("ghost", True)
        self.reveal_btn.setCheckable(True)
        self.reveal_btn.toggled.connect(self._toggle_key_visibility)

        key_row = QWidget()
        key_row.setObjectName("SettingsFieldCell")
        key_layout = QHBoxLayout(key_row)
        key_layout.setContentsMargins(0, 0, 0, 0)
        key_layout.setSpacing(Spacing.SM)
        key_layout.addWidget(self.cloud_api_key, 1)
        key_layout.addWidget(self.reveal_btn)
        self._add_field(grid, 2, 0, "API key", key_row, colspan=2, width=None)

        self.test_btn = QPushButton("Test connection")
        self.test_btn.setProperty("secondary", True)
        self.test_btn.clicked.connect(self._test_connection)
        self.test_status = _FeedbackLabel()
        self.test_status.setProperty("testResult", "idle")
        self.test_status.setWordWrap(True)

        test_row = QWidget()
        test_row.setObjectName("SettingsFieldCell")
        test_layout = QHBoxLayout(test_row)
        test_layout.setContentsMargins(0, 0, 0, 0)
        test_layout.setSpacing(Spacing.MD)
        test_layout.addWidget(self.test_btn)
        test_layout.addWidget(self.test_status, 1)
        grid.addWidget(test_row, grid.rowCount(), 0, 1, 2)
        test_hint = QLabel("Testing does not save settings. Select Save to keep them.")
        test_hint.setProperty("sectionHint", True)
        test_hint.setWordWrap(True)
        grid.addWidget(test_hint, grid.rowCount(), 0, 1, 2)

        # --- Advanced ----------------------------------------------------
        self._build_advanced_card(background_layout)
        layout.addStretch(1)

    def _build_connections_card(self, layout):
        _card, grid = self._add_card(
            layout, "Chat connections",
            "Manage chat connections and enable individual models. Cloud models need an API key "
            "to appear in AI Analysis. Changes are kept only after Save Settings. "
            "These choices do not change background analysis or embeddings.",
        )
        grid.setProperty("settingsRows", False)
        providers = QWidget()
        provider_layout = QVBoxLayout(providers)
        provider_layout.setContentsMargins(0, 0, 0, 0)
        provider_layout.setSpacing(Spacing.SM)
        models = QWidget()
        models_layout = QVBoxLayout(models)
        models_layout.setContentsMargins(0, 0, 0, 0)
        models_layout.setSpacing(Spacing.SM)
        grid.addWidget(providers, 0, 0, 1, 2)
        self.connection_combo = QListWidget()
        self.connection_combo.setObjectName("SettingsConnections")
        self.connection_combo.setFrameShape(QFrame.Shape.NoFrame)
        self.connection_combo.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.connection_combo.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.connection_combo.setSpacing(3)
        self.connection_combo.currentRowChanged.connect(self._select_connection)
        self.connection_combo.model().rowsInserted.connect(self._fit_connection_list)
        self.connection_combo.model().rowsRemoved.connect(self._fit_connection_list)
        self.connection_combo.model().modelReset.connect(self._fit_connection_list)
        provider_layout.addWidget(self.connection_combo)
        actions = QWidget()
        actions.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        row = QHBoxLayout(actions)
        row.setContentsMargins(0, 0, 0, 0)
        add = QPushButton("Connect provider")
        add.clicked.connect(self._connect_provider)
        manage = QPushButton("Edit provider…")
        self.manage_connection_btn = manage
        manage.clicked.connect(self._manage_connection)
        self.remove_connection_btn = QPushButton("Remove")
        self.remove_connection_btn.setToolTip(
            "Remove the selected provider. The built-in local connection cannot be removed.")
        self.remove_connection_btn.clicked.connect(self._remove_connection)
        for button in (add, manage, self.remove_connection_btn):
            button.setProperty("ghost", True)
            button.setProperty("compact", True)
            row.addWidget(button)
        row.addStretch(1)
        provider_layout.addWidget(actions)
        _models_section, model_grid = self._add_card(
            layout, "Chat models",
            "Enable models for AI Analysis. Select a model to target its provider actions.")
        model_grid.addWidget(models, 0, 0, 1, 2)
        self.connection_dialog = QDialog(self)
        self.connection_dialog.setWindowTitle("Manage provider")
        self.connection_dialog.setMinimumWidth(520)
        dialog_layout = QVBoxLayout(self.connection_dialog)
        dialog_layout.setContentsMargins(Spacing.LG, Spacing.LG, Spacing.LG, Spacing.LG)
        dialog_layout.setSpacing(Spacing.MD)
        dialog_hint = QLabel("Changes are a draft. Select Save Settings on the main page to keep them.")
        dialog_hint.setProperty("sectionHint", True)
        dialog_hint.setWordWrap(True)
        dialog_layout.addWidget(dialog_hint)
        editor = QGridLayout()
        dialog_layout.addLayout(editor)
        self.connection_name = QLineEdit()
        self.connection_name.textChanged.connect(self._update_connection_label)
        self.connection_provider = QComboBox()
        self.connection_provider.addItem("Ollama", MODE_LOCAL)
        self.connection_provider.addItem("NVIDIA NIM", MODE_CLOUD)
        self.connection_provider.addItem("OpenAI", MODE_CLOUD)
        self.connection_provider.addItem("Custom OpenAI-compatible", MODE_CLOUD)
        self.connection_provider.currentIndexChanged.connect(self._provider_preset_changed)
        self.connection_endpoint = QLineEdit()
        self.connection_endpoint.setToolTip(
            "Local connections must use the Ollama host configured under Advanced. "
            "Cloud connections use their own endpoint."
        )
        self.connection_key = QLineEdit()
        self.connection_key.setEchoMode(QLineEdit.EchoMode.Password)
        self._add_field(editor, 0, 0, "Name", self.connection_name)
        self._add_field(editor, 0, 1, "Provider", self.connection_provider)
        self._add_field(editor, 1, 0, "Endpoint", self.connection_endpoint, colspan=2, width=None)
        self._add_field(editor, 2, 0, "API key", self.connection_key, colspan=2, width=None)
        self.connection_model_filter = QLineEdit()
        self.connection_model_filter.setPlaceholderText("Filter models by name…")
        self.connection_model_filter.textChanged.connect(self._filter_connection_models)
        models_layout.addWidget(self.connection_model_filter)
        self.connection_models = QListWidget()
        self.connection_models.hide()
        self.connection_models.setParent(self)
        self.model_tree = QTreeWidget()
        self.model_tree.setFrameShape(QFrame.Shape.NoFrame)
        self.model_tree.setObjectName("SettingsChatModels")
        self.model_tree.setHeaderHidden(True)
        self.model_tree.itemChanged.connect(self._model_tree_changed)
        self.model_tree.itemClicked.connect(self._model_tree_selected)
        models_layout.addWidget(self.model_tree)
        self.model_action_target = QLabel()
        self.model_action_target.setProperty("sectionHint", True)
        self.model_action_target.setWordWrap(True)
        models_layout.addWidget(self.model_action_target)
        model_actions = QWidget()
        row = QHBoxLayout(model_actions)
        row.setContentsMargins(0, 0, 0, 0)
        add_model = QPushButton("Add model")
        add_model.clicked.connect(self._add_connection_model)
        remove_model = QPushButton("Remove model")
        remove_model.clicked.connect(self._remove_connection_model)
        row.addWidget(add_model)
        row.addWidget(remove_model)
        self.load_models_btn = QPushButton("Refresh models")
        self.load_models_btn.clicked.connect(self._load_available_models)
        row.addWidget(self.load_models_btn)
        row.addStretch(1)
        models_layout.addWidget(model_actions)
        self.connection_test_btn = QPushButton("Test connection")
        self.connection_test_btn.clicked.connect(self._test_chat_connection)
        self.connection_test_status = _FeedbackLabel()
        self.connection_test_status.setWordWrap(True)
        dialog_layout.addWidget(self.connection_test_btn)
        dialog_layout.addWidget(self.connection_test_status)
        self.connection_enabled = QCheckBox("Enable this connection in AI Analysis")
        dialog_layout.addWidget(self.connection_enabled)
        done = QPushButton("Done")
        done.clicked.connect(self.connection_dialog.accept)
        dialog_layout.addWidget(done)
        self.model_discovery_status = _FeedbackLabel()
        self.model_discovery_status.setWordWrap(True)
        models_layout.addWidget(self.model_discovery_status)
        self.background_cloud_warning = QLabel(
            "Background analysis is currently configured to use cloud AI; "
            "case consent is required before evidence is sent."
        )
        self.background_cloud_warning.setWordWrap(True)
        self.background_cloud_warning.setProperty("sectionHint", True)
        self.background_cloud_warning.hide()
        grid.addWidget(self.background_cloud_warning, 1, 0, 1, 2)

    def _fit_connection_list(self, *_args):
        """Size the list to its contents, with scrolling only for longer lists."""
        height = max(38, self.connection_combo.sizeHintForRow(0) + 2)
        rows = min(5, max(1, self.connection_combo.count()))
        self.connection_combo.setFixedHeight(rows * height + 4)

    def _refresh_connection_summaries(self):
        for index, connection in enumerate(self._connections):
            enabled = sum(model.enabled for model in connection.models)
            state = "Enabled" if connection.enabled else "Disabled"
            text = (f"{connection.name}  ·  {state}\n"
                    f"{connection.base_url}  ·  {enabled}/{len(connection.models)} models enabled")
            self.connection_combo.item(index).setText(text)
            self.connection_combo.item(index).setToolTip(text)
        self._fit_connection_list()

    def _connect_provider(self):
        self._add_connection()
        self._manage_connection()

    def _provider_preset_changed(self, index):
        if getattr(self, "_loading_connection", False) or index < 0:
            return
        presets = {
            0: ("Ollama", get_config().ollama.host),
            1: ("NVIDIA NIM", "https://integrate.api.nvidia.com/v1"),
            2: ("OpenAI", "https://api.openai.com/v1"),
            3: ("Custom", ""),
        }
        name, endpoint = presets[index]
        self.connection_name.setText(name)
        self.connection_endpoint.setText(endpoint)

    def _manage_connection(self):
        if self._connection_index < 0:
            return
        self.connection_dialog.exec()
        self._store_connection()
        self._rebuild_model_tree()

    def _rebuild_model_tree(self):
        self._store_connection()
        self.model_tree.blockSignals(True)
        self.model_tree.clear()
        needle = self.connection_model_filter.text().strip().casefold()
        for index, connection in enumerate(self._connections):
            group = QTreeWidgetItem([connection.name])
            self.model_tree.addTopLevelItem(group)
            for model in connection.models:
                if needle and needle not in model.id.casefold() and needle not in connection.name.casefold():
                    continue
                item = QTreeWidgetItem([model.id])
                item.setData(0, Qt.ItemDataRole.UserRole, (index, model.id))
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(0, Qt.CheckState.Checked if model.enabled else Qt.CheckState.Unchecked)
                group.addChild(item)
            group.setHidden(bool(needle) and group.childCount() == 0)
            group.setExpanded(True)
        self.model_tree.blockSignals(False)
        self._refresh_connection_summaries()
        visible_rows = sum(1 + self.model_tree.topLevelItem(i).childCount()
                           for i in range(self.model_tree.topLevelItemCount())
                           if not self.model_tree.topLevelItem(i).isHidden())
        self.model_tree.setFixedHeight(min(7, max(1, visible_rows)) * 30 + 4)

    def _model_tree_changed(self, item, _column):
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if data is None:
            return
        index, model_id = data
        for model in self._connections[index].models:
            if model.id == model_id:
                model.enabled = item.checkState(0) == Qt.CheckState.Checked
        if index == self._connection_index:
            for i in range(self.connection_models.count()):
                entry = self.connection_models.item(i)
                if entry.text() == model_id:
                    entry.setCheckState(item.checkState(0))
        self._refresh_connection_summaries()

    def _model_tree_selected(self, item, _column):
        data = item.data(0, Qt.ItemDataRole.UserRole)
        group = item.parent() or item
        index = data[0] if data is not None else self.model_tree.indexOfTopLevelItem(group)
        if index >= 0:
            self.connection_combo.setCurrentRow(index)
            if data is not None:
                for row in range(self.connection_models.count()):
                    if self.connection_models.item(row).text() == data[1]:
                        self.connection_models.setCurrentRow(row)
                        break

    def _load_available_models(self):
        if self._discovery_worker is not None or not 0 <= self._connection_index < len(self._connections):
            return
        provider = self.connection_provider.currentData()
        url = self.connection_endpoint.text().strip().rstrip("/")
        key = self.connection_key.text().strip()
        if not url.startswith(("http://", "https://")) or (provider == MODE_CLOUD and not key):
            self.model_discovery_status.setText("Enter a valid endpoint and, for cloud connections, an API key.")
            return
        self._discovery_generation += 1
        token = (self._discovery_generation, self._connections[self._connection_index].id,
                 provider, url, key)
        worker = _ModelDiscoveryWorker((provider, url, key), token)
        self._discovery_worker = worker
        self.load_models_btn.setEnabled(False)
        self.model_discovery_status.setText("Loading models…")
        worker.finished_with_result.connect(self._on_models_discovered)
        _track(worker)
        worker.start()

    def _on_models_discovered(self, token, ids, error):
        self._discovery_worker = None
        self.load_models_btn.setEnabled(True)
        if not 0 <= self._connection_index < len(self._connections):
            return
        current = (self._discovery_generation, self._connections[self._connection_index].id,
                   self.connection_provider.currentData(), self.connection_endpoint.text().strip().rstrip("/"),
                   self.connection_key.text().strip())
        if token != current:
            return
        if error:
            self.model_discovery_status.setText(error)
            return
        existing = {self.connection_models.item(i).text() for i in range(self.connection_models.count())}
        added = 0
        for model_id in ids:
            if model_id not in existing:
                self._append_model(model_id, False)
                existing.add(model_id)
                added += 1
        self.model_discovery_status.setText(f"Added {added} model(s), disabled until selected. Save to keep changes.")
        self._rebuild_model_tree()

    def _test_chat_connection(self):
        if self._connection_index < 0:
            return
        url = self.connection_endpoint.text().strip().rstrip("/")
        provider = self.connection_provider.currentData()
        key = self.connection_key.text().strip()
        if not url.startswith(("http://", "https://")) or (provider == MODE_CLOUD and not key):
            self.connection_test_status.setText("Enter a valid endpoint and API key.")
            return
        self.connection_test_btn.setEnabled(False)
        self.connection_test_status.setText("Testing…")
        def test():
            started = time.perf_counter()
            try:
                if provider == MODE_LOCAL:
                    response = httpx.get(f"{url}/api/tags", timeout=20.0)
                else:
                    response = httpx.get(f"{url}/models",
                        headers={"Authorization": f"Bearer {key}"},
                        timeout=20.0)
                elapsed = round((time.perf_counter() - started) * 1000)
                ok = response.status_code == 200
                result = "Success" if ok else "Failure"
                return ok, f"{result} — {elapsed} ms (HTTP {response.status_code}; model list only)"
            except Exception:  # noqa: BLE001 - never expose request details or secrets
                elapsed = round((time.perf_counter() - started) * 1000)
                return False, f"Failure — {elapsed} ms (could not connect)"
        worker = _TaskWorker(test)
        worker.finished_with_result.connect(self._on_chat_test_result)
        _track(worker)
        worker.start()

    def _on_chat_test_result(self, _ok, message):
        self.connection_test_btn.setEnabled(True)
        self.connection_test_status.setText(message)

    def _store_connection(self):
        if not 0 <= self._connection_index < len(self._connections):
            return
        connection = self._connections[self._connection_index]
        connection.name = self.connection_name.text().strip()
        connection.provider = self.connection_provider.currentData()
        connection.base_url = self.connection_endpoint.text().strip()
        connection.enabled = self.connection_enabled.isChecked()
        key = self.connection_key.text()
        if key or not (connection.api_key.startswith("dpapi:") and not connection_api_key(connection)):
            connection.api_key = key
        connection.models = [AIModelConfig(id=self.connection_models.item(i).text().strip(),
                             enabled=self.connection_models.item(i).checkState() == Qt.CheckState.Checked)
                             for i in range(self.connection_models.count())]

    def _select_connection(self, index):
        if getattr(self, "_loading_connection", False):
            return
        self._discovery_generation += 1
        self.model_discovery_status.clear()
        self._store_connection()
        self._connection_index = index
        self._loading_connection = True
        valid = 0 <= index < len(self._connections)
        self.manage_connection_btn.setEnabled(valid)
        self.model_action_target.setText(
            f"Model actions apply to: {self._connections[index].name}" if valid
            else "Connect a provider to add or discover models.")
        self.load_models_btn.setEnabled(valid and self._discovery_worker is None)
        for widget in (self.connection_name, self.connection_provider, self.connection_endpoint,
                       self.connection_key, self.connection_models, self.connection_model_filter,
                       self.connection_enabled):
            widget.setEnabled(valid)
        self.remove_connection_btn.setEnabled(valid and self._connections[index].id != "local")
        self.connection_models.clear()
        self.connection_model_filter.clear()
        if not valid:
            self.connection_name.clear()
            self.connection_endpoint.clear()
            self.connection_key.clear()
            self._loading_connection = False
            return
        connection = self._connections[index]
        self.connection_name.setText(connection.name)
        self.connection_enabled.setChecked(connection.enabled)
        endpoint = connection.base_url.rstrip("/").lower()
        if connection.provider == MODE_LOCAL:
            preset = 0
        elif endpoint == "https://integrate.api.nvidia.com/v1":
            preset = 1
        elif endpoint == "https://api.openai.com/v1":
            preset = 2
        else:
            preset = 3
        self.connection_provider.setCurrentIndex(preset)
        self.connection_provider.setEnabled(connection.id != "local")
        self.connection_endpoint.setText(connection.base_url)
        self.connection_key.setText(connection_api_key(connection))
        for model in connection.models:
            self._append_model(model.id, model.enabled)
        self._loading_connection = False

    def _update_connection_label(self, text):
        if not getattr(self, "_loading_connection", False) and 0 <= self._connection_index < self.connection_combo.count():
            self._connections[self._connection_index].name = text.strip() or "New connection"
            self._refresh_connection_summaries()

    def _append_model(self, model_id, enabled=True):
        item = QListWidgetItem(model_id)
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(Qt.CheckState.Checked if enabled else Qt.CheckState.Unchecked)
        self.connection_models.addItem(item)
        item.setHidden(self.connection_model_filter.text().strip().casefold() not in model_id.casefold())

    def _filter_connection_models(self, text):
        needle = text.strip().casefold()
        for index in range(self.connection_models.count()):
            item = self.connection_models.item(index)
            item.setHidden(needle not in item.text().casefold())
        if hasattr(self, "model_tree") and not getattr(self, "_loading_connection", False):
            self._rebuild_model_tree()

    def _add_connection(self):
        self._store_connection()
        self._connection_index = -1
        self._connections.append(AIConnectionConfig(id=str(uuid.uuid4()), name="New connection",
                                 provider=MODE_LOCAL, base_url="http://127.0.0.1:11434"))
        self.connection_combo.addItem("New connection")
        self.connection_combo.setCurrentRow(len(self._connections) - 1)
        self._rebuild_model_tree()

    def _remove_connection(self):
        index = self._connection_index
        if index < 0 or self._connections[index].id == "local":
            return
        self._connection_index = -1
        self._connections.pop(index)
        self.connection_combo.takeItem(index)
        self._select_connection(self.connection_combo.currentRow())
        self._rebuild_model_tree()

    def _add_connection_model(self):
        if self._connection_index < 0:
            return
        value, ok = QInputDialog.getText(self, "Add model", "Exact model ID:")
        value = value.strip()
        if ok and value and not any(self.connection_models.item(i).text() == value
                                    for i in range(self.connection_models.count())):
            self._append_model(value)
            self._rebuild_model_tree()

    def _remove_connection_model(self):
        row = self.connection_models.currentRow()
        if row >= 0:
            self.connection_models.takeItem(row)
            self._rebuild_model_tree()

    def _build_advanced_card(self, layout: QVBoxLayout) -> None:
        card = QFrame()
        card.setObjectName("SettingsAdvanced")
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        card.setFrameShape(QFrame.Shape.NoFrame)

        body = QVBoxLayout(card)
        body.setContentsMargins(0, Spacing.SM, 0, Spacing.SM)
        body.setSpacing(Spacing.SM)

        self._advanced_toggle = QToolButton()
        self._advanced_toggle.setObjectName("SettingsAdvancedToggle")
        self._advanced_toggle.setText("Advanced")
        self._advanced_toggle.setCheckable(True)
        self._advanced_toggle.setArrowType(Qt.ArrowType.RightArrow)
        self._advanced_toggle.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextBesideIcon
        )
        self._advanced_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self._advanced_toggle.toggled.connect(self._toggle_advanced)
        body.addWidget(self._advanced_toggle, 0, Qt.AlignmentFlag.AlignLeft)

        self._advanced_content = QWidget()
        self._advanced_content.setObjectName("SettingsFieldCell")
        inner = QVBoxLayout(self._advanced_content)
        inner.setContentsMargins(0, 0, 0, 0)
        inner.setSpacing(Spacing.SM)

        note = QLabel(
            "Rarely changed. The defaults suit a laptop; larger context windows "
            "need more memory than most machines have."
        )
        note.setProperty("sectionHint", True)
        note.setWordWrap(True)
        inner.addWidget(note)

        grid = QGridLayout()
        grid.setProperty("settingsRows", True)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(Spacing.LG)
        grid.setVerticalSpacing(Spacing.MD)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        inner.addLayout(grid)

        body.addWidget(self._advanced_content)
        self._advanced_content.setVisible(False)
        layout.addWidget(card)

        self.ollama_host = QLineEdit()
        self.ollama_host.setPlaceholderText("http://127.0.0.1:11434")
        self._add_field(
            grid, 0, 0, "Ollama host", self.ollama_host, colspan=2, width=None
        )

        self.ai_temperature = QSpinBox()
        self.ai_temperature.setRange(0, 100)
        self.ai_temperature.setSuffix("%")
        self.ai_temperature.setValue(30)
        self._add_field(grid, 1, 0, "Temperature", self.ai_temperature)

        self.ai_max_tokens = QSpinBox()
        self.ai_max_tokens.setRange(256, 8192)
        self.ai_max_tokens.setSingleStep(256)
        self.ai_max_tokens.setValue(2048)
        self._add_field(grid, 1, 1, "Max output tokens", self.ai_max_tokens)

        self.ai_context_tokens = QSpinBox()
        self.ai_context_tokens.setRange(2048, 8192)
        self.ai_context_tokens.setSingleStep(2048)
        self.ai_context_tokens.setValue(8192)
        self.ai_context_tokens.setToolTip(
            "Requested context window. phi3:mini needs about 384 KiB of memory "
            "per token, so 8192 keeps the model under ~5 GiB."
        )
        self._add_field(grid, 2, 0, "Context window", self.ai_context_tokens)

    def set_ai_mode(self, mode: str) -> None:
        """Set the background provider (legacy callers use this method)."""
        self.ai_mode = MODE_CLOUD if mode == MODE_CLOUD else MODE_LOCAL
        self.analysis_provider.setCurrentIndex(self.analysis_provider.findData(self.ai_mode))
        self.background_cloud_warning.setVisible(self.ai_mode == MODE_CLOUD)
        self._update_background_visibility()

    def _update_background_visibility(self, *_args):
        if not hasattr(self, "_cloud_card"):
            return
        analysis_cloud = self.analysis_provider.currentData() == MODE_CLOUD
        embedding_cloud = self.embedding_provider.currentData() == MODE_CLOUD
        cloud = analysis_cloud or embedding_cloud
        if cloud:
            uses = " and ".join(
                name for enabled, name in (
                    (analysis_cloud, "Background analysis"),
                    (embedding_cloud, "embeddings"),
                ) if enabled
            )
            self.background_cloud_warning.setText(
                f"{uses} use a cloud provider; "
                "case consent is required before evidence is sent."
            )
        previous = getattr(self, "_background_cloud_required", False)
        if cloud != previous:
            self._background_cloud_toggle.setChecked(cloud)
        self._background_cloud_required = cloud
        self.background_cloud_warning.setVisible(cloud)

    def _toggle_advanced(self, expanded: bool) -> None:
        self._advanced_content.setVisible(expanded)
        self._advanced_toggle.setArrowType(
            Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow
        )
        self._fit_column()

    def _on_preset_changed(self, _index: int = -1) -> None:
        key = self.cloud_preset.currentData() or "custom"
        preset = CLOUD_PRESETS.get(key, CLOUD_PRESETS["custom"])

        if key == "custom":
            self.cloud_endpoint.setReadOnly(False)
            if self.cloud_endpoint.text().strip() in {
                item["url"] for item in CLOUD_PRESETS.values() if item["url"]
            }:
                self.cloud_endpoint.clear()
        else:
            self.cloud_endpoint.setText(preset["url"])
            self.cloud_endpoint.setReadOnly(True)

        current = self.cloud_model.currentText().strip()
        self.cloud_model.blockSignals(True)
        self.cloud_model.clear()
        self.cloud_model.addItems(preset["models"])
        if current and (current in preset["models"] or key == "custom"):
            self.cloud_model.setCurrentText(current)
        elif preset["models"]:
            self.cloud_model.setCurrentText(preset["models"][0])
        self.cloud_model.blockSignals(False)

    def _toggle_key_visibility(self, visible: bool) -> None:
        self.cloud_api_key.setEchoMode(
            QLineEdit.EchoMode.Normal if visible else QLineEdit.EchoMode.Password
        )
        self.reveal_btn.setText("Hide" if visible else "Show")

    def _test_connection(self) -> None:
        base_url = self.cloud_endpoint.text().strip().rstrip("/")
        api_key = self.cloud_api_key.text().strip()
        model = self.cloud_model.currentText().strip()

        if not (base_url and api_key and model):
            self._set_test_status(
                False, "Fill in the provider, model and API key first."
            )
            return
        if not base_url.startswith(("https://", "http://")):
            self._set_test_status(False, "The endpoint must start with https://.")
            return

        self.test_btn.setEnabled(False)
        self._set_test_status(None, "Testing…")
        self._test_worker = _CloudTestWorker(base_url, api_key, model)
        self._test_worker.finished_with_result.connect(self._on_test_result)
        _track(self._test_worker)
        self._test_worker.start()

    def _on_test_result(self, ok: bool, message: str) -> None:
        self.test_btn.setEnabled(True)
        self._set_test_status(ok, message)

    def _set_test_status(self, ok: bool | None, message: str) -> None:
        self.test_status.setText(message)
        self.test_status.setProperty(
            "testResult", "idle" if ok is None else ("ok" if ok else "error")
        )
        # Qt only re-evaluates a property selector after the widget is polished.
        self.test_status.style().unpolish(self.test_status)
        self.test_status.style().polish(self.test_status)

    # --------------------------------------------------------------- services
    def _build_services_pane(self):
        layout = self._add_pane()
        self._services_index = len(self._panes) - 1

        _card, grid = self._add_card(
            layout,
            "Local services",
            "Start, stop or restart the processes IDFA depends on. Only a "
            "process IDFA started is ever stopped; anything else is reported "
            "as started outside IDFA and left running.",
        )

        for row, key in enumerate(("worker", "qdrant", "ollama")):
            dot = QLabel("●")
            dot.setProperty("serviceDot", "unknown")

            name = QLabel(SERVICE_LABELS[key])
            name.setProperty("serviceName", True)

            endpoint = QLabel("")
            endpoint.setProperty("pathValue", True)
            endpoint.setFont(QFont("Consolas", Typography.MONO_SM[0]))
            endpoint.setWordWrap(True)
            endpoint.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

            state = QLabel("Checking…")
            state.setProperty("sectionHint", True)
            state.setWordWrap(True)

            start_btn = QPushButton("Start")
            start_btn.setProperty("compact", True)
            start_btn.setProperty("secondary", True)
            start_btn.clicked.connect(
                lambda _checked=False, k=key: self._run_service(k, "start")
            )

            stop_btn = QPushButton("Stop")
            stop_btn.setProperty("compact", True)
            stop_btn.setProperty("secondary", True)
            stop_btn.clicked.connect(
                lambda _checked=False, k=key: self._run_service(k, "stop")
            )

            restart_btn = QPushButton("Restart")
            restart_btn.setProperty("compact", True)
            restart_btn.setProperty("secondary", True)
            restart_btn.clicked.connect(
                lambda _checked=False, k=key: self._run_service(k, "restart")
            )

            service = QWidget()
            service.setObjectName("SettingsFieldCell")
            service_layout = QGridLayout(service)
            service_layout.setContentsMargins(0, 0, 0, 0)
            service_layout.setSpacing(Spacing.XS)
            heading = QHBoxLayout()
            heading.setSpacing(Spacing.SM)
            heading.addWidget(dot)
            heading.addWidget(name)
            heading.addStretch(1)
            service_layout.addLayout(heading, 0, 0)
            service_layout.addWidget(endpoint, 1, 0)
            service_layout.addWidget(state, 2, 0)
            service_layout.setColumnStretch(0, 1)

            button_layout = QHBoxLayout()
            button_layout.setContentsMargins(0, 0, 0, 0)
            button_layout.setSpacing(Spacing.XS)
            button_layout.addWidget(start_btn)
            button_layout.addWidget(stop_btn)
            button_layout.addWidget(restart_btn)
            service_layout.addLayout(button_layout, 0, 1, 3, 1)
            grid.addWidget(service, row, 0, 1, 2)

            self._service_rows[key] = {
                "dot": dot,
                "endpoint": endpoint,
                "state": state,
                "start": start_btn,
                "stop": stop_btn,
                "restart": restart_btn,
            }

        actions = QWidget()
        actions.setObjectName("SettingsFieldCell")
        actions_layout = QHBoxLayout(actions)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        actions_layout.setSpacing(Spacing.SM)

        start_all = QPushButton("Start all")
        start_all.setProperty("secondary", True)
        start_all.clicked.connect(lambda: self._run_all("start_all"))
        actions_layout.addWidget(start_all)

        stop_all = QPushButton("Stop all")
        stop_all.setProperty("secondary", True)
        stop_all.clicked.connect(lambda: self._run_all("stop_all"))
        actions_layout.addWidget(stop_all)

        refresh = QPushButton("Refresh")
        refresh.setProperty("ghost", True)
        refresh.clicked.connect(lambda: self._refresh_services(force=True))
        actions_layout.addWidget(refresh)

        logs = QPushButton("Open logs")
        logs.setProperty("ghost", True)
        logs.clicked.connect(self._open_logs)
        actions_layout.addWidget(logs)
        grid.addWidget(actions, 4, 0, 1, 2, Qt.AlignmentFlag.AlignLeft)

        self.services_message = _FeedbackLabel()
        self.services_message.setProperty("sectionHint", True)
        self.services_message.setWordWrap(True)
        grid.addWidget(self.services_message, 5, 0, 1, 2)

        self._services_timer = QTimer(self)
        self._services_timer.setInterval(4000)
        self._services_timer.timeout.connect(self._refresh_services)

        _card, grid = self._add_card(
            layout,
            "Forensic worker",
            "Connection to the local worker that performs disk examination. "
            "Leave the default unless the worker runs on another machine.",
        )

        self.worker_url = QLineEdit()
        self.worker_url.setPlaceholderText("http://127.0.0.1:8000")
        self._add_field(
            grid, 0, 0, "Worker URL", self.worker_url, colspan=2, width=None
        )

        self.worker_timeout = QSpinBox()
        self.worker_timeout.setRange(30, 3600)
        self.worker_timeout.setSuffix(" seconds")
        self.worker_timeout.setValue(300)
        self._add_field(grid, 1, 0, "Timeout", self.worker_timeout)

        layout.addStretch(1)

    def _run_service(self, key: str, action: str) -> None:
        self._set_services_busy(True, f"{action.title()} {SERVICE_LABELS[key]}…")
        self._start_task(lambda: getattr(services, action)(key))

    def _run_all(self, action: str) -> None:
        def call() -> tuple[bool, str]:
            results = getattr(services, action)()
            failures = [
                f"{SERVICE_LABELS.get(key, key)}: {message}"
                for key, ok, message in results
                if not ok
            ]
            if failures:
                return False, " ".join(failures)
            return True, "All requested services are running."

        self._set_services_busy(True, "Working…")
        self._start_task(call)

    def _start_task(self, action) -> None:
        worker = _TaskWorker(action)
        worker.finished_with_result.connect(self._on_service_done)
        worker.finished.connect(lambda w=worker: self._forget_task(w))
        _track(worker)
        self._service_workers.append(worker)
        worker.start()

    def _forget_task(self, worker) -> None:
        if worker in self._service_workers:
            self._service_workers.remove(worker)

    def _on_service_done(self, ok: bool, message: str) -> None:
        self._set_services_busy(False, message)
        self._refresh_services(force=True)

    def _set_services_busy(self, busy: bool, message: str = "") -> None:
        for row in self._service_rows.values():
            for name in ("start", "stop", "restart"):
                row[name].setEnabled(not busy)
        self.services_message.setText(message)

    def _refresh_services(self, force: bool = False) -> None:
        if not force:
            # The timer fires whether or not the pane is on screen.
            if not self.isVisible() or self._stack.currentIndex() != self._services_index:
                return
        if self._status_worker is not None and self._status_worker.isRunning():
            return

        worker = _StatusWorker()
        worker.finished_with_result.connect(self._apply_statuses)
        worker.finished.connect(lambda w=worker: self._clear_status_worker(w))
        _track(worker)
        self._status_worker = worker
        worker.start()

    def _clear_status_worker(self, worker) -> None:
        # The QThread object is deleted after it finishes; holding the Python
        # wrapper would make the next ``isRunning()`` call touch dead memory.
        if self._status_worker is worker:
            self._status_worker = None

    def _apply_statuses(self, statuses) -> None:
        for status in statuses or []:
            row = self._service_rows.get(status.key)
            if row is None:
                continue
            row["endpoint"].setText(status.endpoint)
            row["endpoint"].setToolTip(status.endpoint)
            # The theme uses the same error colour for stopped and failed
            # services; keep the actual state in the detail and tooltip.
            dot_state = "stopped" if status.state == services.ERROR else status.state
            row["dot"].setProperty("serviceDot", dot_state)
            row["dot"].style().unpolish(row["dot"])
            row["dot"].style().polish(row["dot"])

            detail = status.detail
            row["state"].setText(detail)
            row["state"].setToolTip(f"{status.label}: {status.state} ({detail})")

            row["start"].setEnabled(status.can_start)
            row["stop"].setEnabled(status.can_stop)
            row["restart"].setEnabled(status.can_start or status.can_stop)

    def _update_services_timer(self) -> None:
        active = (
            self.isVisible()
            and self._stack.currentIndex() == self._services_index
        )
        if active:
            self._services_timer.start()
            self._refresh_services(force=True)
        else:
            self._services_timer.stop()

    def _open_logs(self) -> None:
        path = services.logs_dir()
        path.mkdir(parents=True, exist_ok=True)
        try:
            os.startfile(path)  # noqa: S606 - opening a folder is the intent
        except OSError as exc:
            QMessageBox.warning(self, "Logs", f"Could not open {path}: {exc}")

    # ------------------------------------------------------------------- data
    def _build_data_pane(self):
        layout = self._add_pane()

        _card, grid = self._add_card(
            layout,
            "Data & Storage",
            "One folder holds cases, evidence copies, the database and the vector "
            "index. Everything below is derived from it.",
        )

        self.data_dir_display = QLineEdit()
        self.data_dir_display.setReadOnly(True)
        self.data_dir_display.setProperty("readonly", True)
        self._add_field(
            grid, 0, 0, "Data folder", self.data_dir_display, colspan=2, width=None
        )

        actions = QWidget()
        actions_layout = QHBoxLayout(actions)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        actions_layout.setSpacing(Spacing.SM)

        self.change_folder_btn = QPushButton("Change folder…")
        self.change_folder_btn.setProperty("secondary", True)
        self.change_folder_btn.clicked.connect(self._on_change_data_folder)
        actions_layout.addWidget(self.change_folder_btn)

        self.backup_db_btn = QPushButton("Back up database")
        self.backup_db_btn.setProperty("secondary", True)
        self.backup_db_btn.clicked.connect(self._on_backup_db)
        actions_layout.addWidget(self.backup_db_btn)
        actions_layout.addStretch(1)

        grid.addWidget(actions, grid.rowCount(), 0, 1, 2, Qt.AlignmentFlag.AlignLeft)
        grid.addWidget(self._build_paths_panel(), grid.rowCount(), 0, 1, 2)

        layout.addStretch(1)

    def _build_paths_panel(self) -> QFrame:
        """A compact list of the paths derived from the data folder."""
        panel = QFrame()
        panel.setObjectName("SettingsPaths")
        panel.setFrameShape(QFrame.Shape.NoFrame)

        grid = QGridLayout(panel)
        grid.setContentsMargins(Spacing.MD, Spacing.MD, Spacing.MD, Spacing.MD)
        grid.setHorizontalSpacing(Spacing.MD)
        grid.setVerticalSpacing(Spacing.XS)
        grid.setColumnStretch(1, 1)

        self.path_labels: dict[str, QLabel] = {}
        rows = [
            ("Database", "database"),
            ("Logs", "logs"),
            ("Evidence", "evidence"),
            ("Vector store", "vectors"),
        ]
        for row, (caption, key) in enumerate(rows):
            name = QLabel(caption)
            name.setProperty("pathLabel", True)
            name.setFixedWidth(PATH_LABEL_WIDTH)
            name.setAlignment(
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
            )

            value = QLabel()
            value.setProperty("pathValue", True)
            value.setWordWrap(True)
            value.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
            )
            value.setFont(QFont("Consolas", Typography.MONO_SM[0]))

            grid.addWidget(name, row, 0)
            grid.addWidget(value, row, 1)
            self.path_labels[key] = value

        self.free_space_label = QLabel()
        self.free_space_label.setProperty("pathFree", True)
        grid.addWidget(
            self.free_space_label,
            len(rows),
            0,
            1,
            2,
            Qt.AlignmentFlag.AlignLeft,
        )
        return panel

    # --------------------------------------------------------------- security
    def _build_security_pane(self):
        layout = self._add_pane()

        _card, grid = self._add_card(
            layout,
            "Security",
            "Session settings for this installation. Bcrypt rounds is saved but is not currently applied to password hashing.",
        )

        self.session_timeout = QSpinBox()
        self.session_timeout.setRange(15, 10000)
        self.session_timeout.setSuffix(" minutes")
        self.session_timeout.setValue(480)
        self._add_field(grid, 0, 0, "Session timeout", self.session_timeout)

        self.bcrypt_rounds = QSpinBox()
        self.bcrypt_rounds.setRange(4, 31)
        self.bcrypt_rounds.setValue(12)
        self.bcrypt_rounds.setToolTip("This value is saved but is not currently used for password hashing.")
        self._add_field(grid, 0, 1, "Bcrypt rounds", self.bcrypt_rounds)

        layout.addStretch(1)

    # ---------------------------------------------------------------- footer
    def _build_footer(self) -> QFrame:
        footer = QFrame()
        footer.setObjectName("SettingsFooter")
        footer.setFrameShape(QFrame.Shape.NoFrame)
        # The content width follows the viewport; it must not in turn become
        # the minimum width of the viewport when the window is narrowed.
        footer.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

        footer_centring = QHBoxLayout(footer)
        footer_centring.setContentsMargins(Spacing.LG, Spacing.SM, Spacing.LG, Spacing.SM)
        footer_centring.setSpacing(0)

        footer_content = QWidget()
        self._footer_content = footer_content
        footer_content.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred
        )
        footer_centring.addWidget(footer_content)
        footer_centring.addStretch(1)

        self._footer_layout = QHBoxLayout(footer_content)
        self._footer_layout.setContentsMargins(0, 0, 0, 0)
        self._footer_layout.setSpacing(Spacing.SM)

        hint = QLabel(
            "Save to keep edits. Appearance previews immediately; service and folder actions run immediately. Some changes may require a restart."
        )
        hint.setProperty("muted", True)
        hint.setToolTip(f"Saved to {get_config_path()}")
        # Translated hints are longer than the English original; wrap instead of
        # pushing the buttons past the right edge of the column.
        hint.setWordWrap(True)
        hint.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self._footer_hint = hint
        self._footer_layout.addWidget(hint, 1)

        self._footer_help = QPushButton("Save info")
        self._footer_help.setProperty("ghost", True)
        self._footer_help.setAccessibleName("Show save and restart settings guidance")
        self._footer_help.setToolTip(hint.text())
        self._footer_help.clicked.connect(
            lambda: QMessageBox.information(self, "Settings guidance", hint.text())
        )
        self._footer_layout.addWidget(self._footer_help)

        self.reset_btn = QPushButton("Reset to Defaults")
        self.reset_btn.setProperty("ghost", True)
        self.reset_btn.setAccessibleName("Reset to Defaults")
        self.reset_btn.clicked.connect(self._on_reset)
        self._footer_layout.addWidget(self.reset_btn)

        self.save_btn = QPushButton("Save Settings")
        self.save_btn.setAccessibleName("Save Settings")
        self.save_btn.setToolTip(hint.text())
        self.save_btn.clicked.connect(self._on_save)
        self._footer_layout.addWidget(self.save_btn)

        return footer

    # -------------------------------------------------------------- geometry
    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "_nav_panel"):
            narrow = event.size().width() < 800
            self._nav_panel.setFixedWidth(150 if narrow else NAV_WIDTH)
            self._footer_hint.setVisible(not narrow)
            self._footer_help.setVisible(narrow)
            self.reset_btn.setText("Reset" if narrow else "Reset to Defaults")
            self.save_btn.setText("Save" if narrow else "Save Settings")
        self._fit_column()

    def showEvent(self, event):
        super().showEvent(event)
        self._fit_column()
        self._refresh_paths()
        self._update_services_timer()

    def hideEvent(self, event):
        super().hideEvent(event)
        self._services_timer.stop()

    def closeEvent(self, event):
        self.shutdown()
        super().closeEvent(event)

    def shutdown(self) -> None:
        """Stop polling and let in-flight workers finish before teardown.

        A status poll or a connection test keeps running for as long as the
        endpoint takes to answer. Waiting here means the window can close
        without a thread outliving the page that owns its slots.
        """
        self._services_timer.stop()
        for worker in list(_LIVE_WORKERS):
            if worker.isRunning():
                worker.wait(3000)

    def _fit_column(self):
        """Size every pane's column to its viewport, capped at ``CONTENT_MAX_WIDTH``."""
        if not self._panes:
            return

        current = self._stack.currentWidget() if hasattr(self, "_stack") else None
        for scroll, column in self._panes:
            viewport = scroll.viewport().width() or self.width()
            width = max(1, min(viewport - 2 * Spacing.LG, CONTENT_MAX_WIDTH))
            column.setFixedWidth(width)
            if scroll is current and hasattr(self, "_footer_content"):
                # The scrollbar sits inside the scroll area but outside the
                # cards, so shrink the action bar by its width to keep both
                # right edges flush.
                scrollbar = scroll.verticalScrollBar()
                reserve = scrollbar.sizeHint().width() if scrollbar.isVisible() else 0
                self._footer_content.setFixedWidth(max(1, width - reserve))

    # --------------------------------------------------------------- helpers
    def _add_card(
        self, parent_layout: QVBoxLayout, title: str, description: str = ""
    ) -> tuple[QFrame, QGridLayout]:
        """Add a flat, content-sized section (the name is kept for callers)."""
        card = QFrame()
        card.setObjectName("SettingsSection")
        card.setFrameShape(QFrame.Shape.NoFrame)
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)

        body = QVBoxLayout(card)
        body.setContentsMargins(0, Spacing.SM, 0, Spacing.MD)
        body.setSpacing(Spacing.XS)

        heading = QLabel(title)
        heading.setProperty("settingsHeading", True)
        heading.setFont(
            QFont(Typography.FONT_FAMILY, Typography.HEADING_SM[0], Typography.HEADING_SM[1])
        )
        body.addWidget(heading)

        if description:
            hint = QLabel(description)
            hint.setProperty("sectionHint", True)
            hint.setWordWrap(True)
            body.addWidget(hint)

        grid = QGridLayout()
        grid.setProperty("settingsRows", True)
        grid.setContentsMargins(0, Spacing.MD, 0, 0)
        grid.setHorizontalSpacing(Spacing.LG)
        grid.setVerticalSpacing(Spacing.MD)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        body.addLayout(grid)

        parent_layout.addWidget(card)
        return card, grid

    def _add_field(
        self,
        grid: QGridLayout,
        row: int,
        column: int,
        caption: str,
        widget: QWidget,
        colspan: int = 1,
        width: int | None = CONTROL_MAX_WIDTH,
        align_bottom: bool = False,
    ) -> None:
        """Add a caption-above-field cell so every input lines up.

        Two-column rows get equal-width controls: the widget is allowed to grow
        and stopped at ``CONTROL_MAX_WIDTH``, which is the width of the column,
        so there is no dead space to the right of a short combo box. Pass
        ``width=None`` for a path or URL that spans the card. ``align_bottom``
        centres a checkbox in the height of the input beside it.
        """
        if grid.property("settingsRows"):
            # Existing builders specify paired cells; sections now use one
            # readable label/control row per option. Dialogs keep paired fields.
            row = grid.rowCount()
            label = QLabel(caption)
            label.setProperty("fieldLabel", True)
            label.setBuddy(widget)
            label.setWordWrap(True)
            label.setMinimumWidth(150)
            label.setMaximumWidth(210)
            grid.addWidget(label, row, 0)
            widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            grid.addWidget(widget, row, 1)
            grid.setColumnStretch(0, 2)
            grid.setColumnStretch(1, 3)
            return
        cell = QVBoxLayout()
        cell.setContentsMargins(0, 0, 0, 0)
        cell.setSpacing(Spacing.XS)

        label = QLabel(caption)
        label.setProperty("fieldLabel", True)
        label.setBuddy(widget)
        cell.addWidget(label)

        if width is not None:
            widget.setMaximumWidth(width)

        # QComboBox and QSpinBox default to a content-sized policy, which left
        # the second column visibly narrower than the first.
        widget.setSizePolicy(
            QSizePolicy.Policy.Expanding, widget.sizePolicy().verticalPolicy()
        )

        if align_bottom:
            # A checkbox is shorter than a text field. Filling the rest of the
            # row and centring inside it lines the two up without depending on
            # the height the style gives an input.
            holder = QWidget()
            holder.setObjectName("SettingsFieldCell")
            holder_layout = QVBoxLayout(holder)
            holder_layout.setContentsMargins(0, 0, 0, 0)
            holder_layout.addStretch(1)
            holder_layout.addWidget(widget)
            holder_layout.addStretch(1)
            cell.addWidget(holder, 1)
        else:
            cell.addWidget(widget)

        wrapper = QWidget()
        wrapper.setObjectName("SettingsFieldCell")
        wrapper.setLayout(cell)
        grid.addWidget(wrapper, row, column, 1, colspan)

    # ------------------------------------------------------------------ data
    def _refresh_paths(self):
        """Show the active data folder and everything derived from it."""
        config = get_config()
        paths = describe_layout_paths(config)

        self.data_dir_display.setText(paths["data"])
        for key, label in self.path_labels.items():
            label.setText(paths.get(key, ""))
            label.setToolTip(paths.get(key, ""))

        free = free_space_bytes(paths["data"])
        self.free_space_label.setText(
            tr("{gb} GB free on this drive").replace("{gb}", f"{free / (1024 ** 3):.1f}")
            if free is not None
            else tr("Free space unknown")
        )

    def retranslate(self) -> None:
        """Rebuild the text this page composes rather than stores.

        The free-space line is a template filled at display time, so a label
        walk cannot translate it; everything else is plain label text.
        """
        self._refresh_paths()

    def _on_change_data_folder(self):
        """Let the user move, adopt, or start a data folder from Settings."""
        config = get_config()
        dialog = ChangeDataFolderDialog(config, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        progress = QProgressDialog("Preparing to copy…", None, 0, 100, self)
        progress.setWindowTitle("Changing data folder")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.setValue(0)

        def report(percent: int, message: str) -> None:
            progress.setValue(max(0, min(100, percent)))
            progress.setLabelText(message)
            QApplication.processEvents()

        try:
            apply_data_dir(config, dialog.selected_path(), dialog.selected_mode(), report)
        except Exception as exc:
            progress.close()
            QMessageBox.critical(
                self,
                "Data folder not changed",
                f"IDFA could not use that folder:\n\n{exc}\n\n"
                f"The current folder {config.app.data_dir} is still in use.",
            )
            return
        finally:
            progress.close()

        self._load_current_settings()
        QMessageBox.information(
            self,
            "Data folder changed",
            f"IDFA now uses:\n{dialog.selected_path()}\n\n"
            "Restart the application so every service picks up the new paths.",
        )

    # ------------------------------------------------------------ load/save
    def _load_current_settings(self):
        """Load current config values into UI fields."""
        config = get_config()

        # General. Signals are blocked: loading the saved values must not look
        # like the investigator picking a new theme or language.
        for combo, value in (
            (self.theme_combo, config.ui.theme),
            (self.language_combo, config.ui.language),
        ):
            combo.blockSignals(True)
            index = combo.findData(value)
            combo.setCurrentIndex(index if index >= 0 else 0)
            combo.blockSignals(False)
        self.auto_refresh_check.setChecked(config.ui.auto_refresh)
        self.refresh_interval.setValue(config.ui.refresh_interval_seconds)
        self.refresh_interval.setEnabled(config.ui.auto_refresh)

        # Worker
        self.worker_url.setText(config.worker.url)
        self.worker_timeout.setValue(config.worker.timeout_seconds)

        # AI
        self.ollama_host.setText(config.ollama.host)
        self.ollama_model.setCurrentText(config.ollama.model)
        self._connection_index = -1
        self._connections = [item.model_copy(deep=True) for item in config.ollama.chat_connections or []]
        self.connection_combo.blockSignals(True)
        self.connection_combo.clear()
        for item in self._connections:
            self.connection_combo.addItem(item.name)
        self.connection_combo.blockSignals(False)
        self.connection_combo.setCurrentRow(0 if self._connections else -1)
        self._select_connection(self.connection_combo.currentRow())
        self._fit_connection_list()
        self._rebuild_model_tree()
        self.embedding_model.setCurrentText(config.embeddings.model_id)
        self.embedding_chunk_size.setValue(config.embeddings.chunk_size)
        self.embedding_chunk_overlap.setMaximum(
            max(self.embedding_chunk_overlap.value(), config.embeddings.chunk_size - 1)
        )
        self.embedding_chunk_overlap.setValue(config.embeddings.chunk_overlap)
        self.embedding_chunk_overlap.setMaximum(config.embeddings.chunk_size - 1)
        self.embedding_batch_size.setValue(config.embeddings.batch_size)
        self.embedding_provider.setCurrentIndex(
            max(0, self.embedding_provider.findData(config.embeddings.provider))
        )

        endpoint = config.ollama.cloud_base_url.rstrip("/")
        preset_key = next(
            (
                key
                for key, preset in CLOUD_PRESETS.items()
                if key != "custom" and preset["url"] == endpoint
            ),
            "custom",
        )
        self.cloud_preset.blockSignals(True)
        self.cloud_preset.setCurrentIndex(
            max(0, self.cloud_preset.findData(preset_key))
        )
        self.cloud_preset.blockSignals(False)

        self.cloud_model.clear()
        self.cloud_model.addItems(CLOUD_PRESETS[preset_key]["models"])
        self.cloud_model.setCurrentText(config.ollama.cloud_model)
        self.cloud_endpoint.setText(endpoint)
        self.cloud_endpoint.setReadOnly(preset_key != "custom")

        # Shown decrypted so the field can be edited; save_config encrypts it.
        self.cloud_api_key.setText(cloud_api_key(config))

        self.ai_temperature.setValue(round(config.ollama.temperature * 100))
        self.ai_max_tokens.setValue(config.ollama.max_tokens)
        self.ai_context_tokens.setValue(config.ollama.context_window_tokens)

        self.set_ai_mode(config.ollama.provider)
        self._set_test_status(None, "")

        # Security
        self.session_timeout.setValue(config.auth.access_token_expire_minutes)
        self.bcrypt_rounds.setValue(config.auth.bcrypt_rounds)

    def _on_save(self):
        """Save all settings to config.yaml."""
        config = get_config()

        self._store_connection()
        for connection in self._connections:
            ids = [model.id for model in connection.models]
            if (not connection.name or not connection.base_url.startswith(("http://", "https://"))
                    or not all(ids) or len(ids) != len(set(ids))):
                QMessageBox.warning(self, "Invalid connection", "Each connection needs a name, a valid endpoint and unique nonempty model IDs.")
                return

        if self.embedding_chunk_overlap.value() >= self.embedding_chunk_size.value():
            QMessageBox.warning(
                self,
                "Invalid chunk settings",
                "Chunk overlap must be smaller than chunk size.",
            )
            return

        indexing_changed = (
            config.embeddings.chunk_size != self.embedding_chunk_size.value()
            or config.embeddings.chunk_overlap != self.embedding_chunk_overlap.value()
            or config.embeddings.model_id != self.embedding_model.currentText().strip()
            or config.embeddings.provider
            != (self.embedding_provider.currentData() or "ollama")
        )

        # Cloud providers fail only when the investigator asks a question, so
        # reject incomplete cloud settings here rather than at the demo.
        chat_provider = self.analysis_provider.currentData() or MODE_LOCAL
        embedding_provider = self.embedding_provider.currentData() or "ollama"
        cloud_model = self.cloud_model.currentText().strip()
        cloud_url = self.cloud_endpoint.text().strip().rstrip("/")
        cloud_key = self.cloud_api_key.text().strip()
        if "openai" in (chat_provider, embedding_provider):
            if not cloud_key:
                QMessageBox.warning(
                    self,
                    "API key required",
                    "A cloud provider is selected, but the API key is empty. "
                    "Paste the provider key, or select local providers.",
                )
                return
            if not cloud_url.startswith(("https://", "http://")):
                QMessageBox.warning(
                    self,
                    "Invalid endpoint",
                    "The cloud endpoint must start with https:// or http://.",
                )
                return
            if chat_provider == "openai" and not cloud_model:
                QMessageBox.warning(
                    self,
                    "Model required",
                    "Enter the exact cloud chat model ID from the provider's catalog.",
                )
                return

        # General
        config.ui.theme = self.theme_combo.currentData() or "dark"
        config.ui.language = self.language_combo.currentData() or DEFAULT_LANGUAGE
        config.ui.auto_refresh = self.auto_refresh_check.isChecked()
        config.ui.refresh_interval_seconds = self.refresh_interval.value()

        # Worker
        config.worker.url = self.worker_url.text()
        config.worker.timeout_seconds = self.worker_timeout.value()

        # AI
        config.ollama.host = self.ollama_host.text().strip()
        config.ollama.provider = chat_provider
        config.ollama.model = self.ollama_model.currentText().strip()
        config.ollama.cloud_model = cloud_model
        config.ollama.chat_connections = [item.model_copy(deep=True) for item in self._connections]
        config.ollama.cloud_base_url = cloud_url
        # A DPAPI value may be unreadable under another Windows account. An
        # empty field in that case is not an instruction to erase the original.
        if cloud_key or not (config.ollama.cloud_api_key.startswith("dpapi:")
                             and not cloud_api_key(config)):
            config.ollama.cloud_api_key = cloud_key
        config.embeddings.provider = embedding_provider
        config.embeddings.model_id = self.embedding_model.currentText().strip()
        config.embeddings.chunk_size = self.embedding_chunk_size.value()
        config.embeddings.chunk_overlap = self.embedding_chunk_overlap.value()
        config.embeddings.batch_size = self.embedding_batch_size.value()
        config.ollama.temperature = self.ai_temperature.value() / 100
        config.ollama.max_tokens = self.ai_max_tokens.value()
        config.ollama.context_window_tokens = self.ai_context_tokens.value()

        # Database paths are derived from the data folder, so they are not
        # written back here — a stale absolute path would pin the app to one
        # machine again.

        # Security
        config.auth.access_token_expire_minutes = self.session_timeout.value()
        config.auth.bcrypt_rounds = self.bcrypt_rounds.value()

        save_config(config)
        self._load_current_settings()
        self._refresh_paths()

        ThemeManager().set_mode(config.ui.theme)
        self.settings_applied.emit()

        QMessageBox.information(
            self,
            "Settings Saved",
            "Settings have been saved. "
            + (
                "Existing semantic vectors keep their previous settings until those artifacts are re-indexed. "
                if indexing_changed else ""
            )
            + "Some changes may require a restart.",
        )

    def _preview_theme(self, _index: int = -1) -> None:
        """Apply a theme as soon as it is picked, so the choice is visible.

        Nothing is written to disk here; Save persists the value. This only
        makes the control do something instead of waiting silently.
        """
        ThemeManager().set_mode(self.theme_combo.currentData() or "dark")

    def _preview_language(self, _index: int = -1) -> None:
        """Switch the interface language as soon as it is picked."""
        language = self.language_combo.currentData() or DEFAULT_LANGUAGE
        LanguageManager().set_language(language)

    def _on_reset(self):
        reply = QMessageBox.question(
            self, "Reset Settings",
            "Are you sure you want to reset all settings to defaults?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            reset_config()
            self._load_current_settings()
            ThemeManager().set_mode(get_config().ui.theme)
            self.settings_applied.emit()
            QMessageBox.information(
                self, "Settings Reset", "Settings have been reset to defaults."
            )

    def _on_backup_db(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Backup Database", "idfa_backup.db", "SQLite Database (*.db *.sqlite)"
        )
        if path:
            try:
                import shutil

                shutil.copy2(database_path(get_config()), path)
                QMessageBox.information(self, "Backup Complete", f"Database backed up to {path}")
            except Exception as e:
                QMessageBox.critical(
                    self, "Backup Failed", f"Failed to backup database: {e}"
                )

    def set_case_context(self, context):
        pass  # Settings are global, not case-specific
