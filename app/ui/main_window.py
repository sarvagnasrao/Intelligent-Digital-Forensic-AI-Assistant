"""Main window and navigation controller - Professional Forensic UI."""
from __future__ import annotations

import logging
import threading
from collections.abc import Callable

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QStackedWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from app.auth.models import User, UserRole
from app.config import get_config
from app.i18n import LanguageManager, retranslate_widgets, tr
from app.ui.auto_refresh import AutoRefreshController
from app.ui.base import (
    BrandingHeader,
    CaseContext,
    CaseHeaderBar,
    NavItemDelegate,
    NavList,
    SidebarWidget,
)
from app.ui.header_bar import AppHeaderBar
from app.ui.pages import (
    AIAnalysisPage,
    ArtifactsSearchPage,
    AuditPage,
    CaseManagementPage,
    EntitiesTimelinePage,
    EvidencePage,
    ExaminationPage,
    FindingsPage,
    GlobalAuditPage,
    OverviewPage,
    ReportsPage,
    SettingsPage,
    ToolsPage,
    UserManagementPage,
)
from app.ui.theme.manager import ThemeManager
from app.util.ollama_service import ensure_running as ensure_ollama_running
from app.util.ollama_service import stop_managed as stop_managed_ollama

_GLOBAL_PAGES: tuple[tuple[str, str, bool], ...] = (
    ("cases", "Case Management", False),
    ("audit", "Global Audit", False),
    ("tools", "Tools", False),
    ("users", "User Management", True),
    ("settings", "Settings", False),
)

# Fixed stack order and titles, independent of which pages a user may see.
_PAGE_TITLES = {key: title for key, title, _admin in _GLOBAL_PAGES}


class GlobalShell(QWidget):
    """Global shell - shown after login, before opening a case."""

    open_case_requested = Signal(int, str, str, str, str)  # case_id, title, status, priority, investigator
    logout_requested = Signal()

    def __init__(self, nav_controller: NavigationController, parent: QWidget | None = None):
        super().__init__(parent)
        self.nav = nav_controller
        self._user: User | None = None
        self._current_key: str | None = None
        self._visible_keys: list[str] = [
            key for key, _title, admin_only in _GLOBAL_PAGES if not admin_only
        ]
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header (search, notifications and user menu are wired here)
        self.header = AppHeaderBar("Case Management")
        self.header.settings_requested.connect(lambda: self.show_page_by_key("settings"))
        self.header.about_requested.connect(self._show_about)
        self.header.logout_requested.connect(self.logout_requested.emit)
        self.header.search_submitted.connect(self._on_header_search)
        layout.addWidget(self.header)

        # Content splitter
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setObjectName("NavigationSplitter")
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(1)
        self._splitter = splitter
        layout.addWidget(splitter, 1)

        # Sidebar with branding
        self.sidebar = SidebarWidget()
        sidebar_layout = QVBoxLayout(self.sidebar)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.setSpacing(0)

        # Branding header
        self.branding = BrandingHeader()
        self.branding.toggle_requested.connect(self._toggle_sidebar)
        sidebar_layout.addWidget(self.branding)

        # Navigation
        self.nav_list = NavList([])
        self.nav_list.clicked.connect(self._on_nav_clicked)
        self._refresh_nav()
        sidebar_layout.addWidget(self.nav_list, 1)

        # System status at bottom: subtle strip instead of a bright green block.
        # Scoped by object name so the style cannot leak to other labels.
        self.status_label = QLabel("●  All systems operational")
        self.status_label.setObjectName("SystemStatus")

        self.status_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.status_label.setToolTip("All systems operational")
        sidebar_layout.addWidget(self.status_label)

        splitter.addWidget(self.sidebar)

        # Pages stack
        self.pages_stack = QStackedWidget()
        self.case_mgmt_page = CaseManagementPage(self.nav)
        self.global_audit_page = GlobalAuditPage()
        self.tools_page = ToolsPage()
        self.user_mgmt_page = UserManagementPage()
        self.settings_page = SettingsPage()

        self._pages_by_key = {
            "cases": self.case_mgmt_page,
            "audit": self.global_audit_page,
            "tools": self.tools_page,
            "users": self.user_mgmt_page,
            "settings": self.settings_page,
        }

        # Wire up global audit service
        if self.global_audit_page and hasattr(self.global_audit_page, "set_audit_service"):
            from app.db.session import session_scope
            with session_scope() as session:
                from app.audit.service import AuditService
                audit_service = AuditService(session)
                self.global_audit_page.set_audit_service(audit_service)

        # Forward case open signal from case management page to global shell
        self.case_mgmt_page.open_case_requested.connect(self.open_case_requested.emit)

        # Fixed order: the sidebar filters this list per user, the stack does not.
        for key, _title, _admin_only in _GLOBAL_PAGES:
            self.pages_stack.addWidget(self._pages_by_key[key])

        splitter.addWidget(self.pages_stack)

        # Set splitter sizes
        splitter.setSizes([260, 800])
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        self.set_sidebar_collapsed(bool(getattr(self.nav, "sidebar_collapsed", False)))

    def _toggle_sidebar(self) -> None:
        collapsed = not self.sidebar.collapsed
        self.nav.sidebar_collapsed = collapsed
        for shell in (self.nav.global_shell, self.nav.case_shell):
            shell.set_sidebar_collapsed(collapsed)

    def set_sidebar_collapsed(self, collapsed: bool) -> None:
        self.sidebar.collapsed = collapsed
        self.branding.set_collapsed(collapsed)
        self.nav_list.set_collapsed(collapsed)
        self.status_label.setText("●" if collapsed else "●  All systems operational")
        self.status_label.setProperty("collapsed", collapsed)
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)
        self.status_label.setAlignment(
            Qt.AlignmentFlag.AlignCenter if collapsed
            else Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        width = 68 if collapsed else 260
        self._splitter.setSizes([width, max(1, self._splitter.width() - width)])

    def _show_about(self) -> None:
        QMessageBox.about(
            self,
            "About IDFA",
            "<b>IDFA</b><br>Intelligent Digital Forensic Analysis<br><br>"
            "Local-first forensic investigation workspace.<br>"
            "Version 0.1.0",
        )

    # ------------------------------------------------------------- navigation
    @staticmethod
    def _is_admin(user: User | None) -> bool:
        try:
            role = getattr(user, "role", None) if user is not None else None
            value = getattr(role, "value", role)
        except Exception:  # detached/expired ORM instance: fail closed
            return False
        return str(value).strip().lower() == UserRole.ADMIN.value

    def set_user(self, user: User | None) -> None:
        """Apply the signed-in user's role to the navigation and its pages.

        All global pages stay in the stack; only the navigation entries and the
        guard in ``show_page_by_key`` change with the role.
        """
        self._user = user
        is_admin = self._is_admin(user)

        self._visible_keys = [
            key
            for key, _title, admin_only in _GLOBAL_PAGES
            if is_admin or not admin_only
        ]
        self._refresh_nav()

        # The page itself also clears its rows when there is no administrator.
        self.user_mgmt_page.set_current_user(user if is_admin else None)

        # Sign-in and sign-out both land on Case Management, as before.
        self.show_page_by_key("cases")

    def show_page_by_key(self, key: str) -> None:
        """Switch page by key, keeping the sidebar selection and title in sync."""
        page = self._pages_by_key.get(key)
        if page is None:
            return
        if self._is_admin_only(key) and not self._is_admin(self._user):
            return

        self.pages_stack.setCurrentWidget(page)
        self._current_key = key

        if key in self._visible_keys:
            model = self.nav_list.model
            if model is not None:
                index = model.index(self._visible_keys.index(key), 0)
                self.nav_list.setCurrentIndex(index)

        if key == "audit" and hasattr(self.global_audit_page, "refresh"):
            self.global_audit_page.refresh()

        self.header.set_title(tr(_PAGE_TITLES[key]))

    def _refresh_nav(self) -> None:
        """Rebuild the sidebar rows for the visible keys in the active language."""
        self.nav_list.set_entries([
            (tr(_PAGE_TITLES[key]), NavItemDelegate.ICONS.get(_PAGE_TITLES[key], "•"))
            for key in self._visible_keys
        ])

    def retranslate(self) -> None:
        """Re-apply the active language to this shell and its navigation."""
        self._refresh_nav()
        retranslate_widgets(self)
        title = _PAGE_TITLES.get(self._current_key or "")
        if title:
            self.header.set_title(tr(title))

    @staticmethod
    def _is_admin_only(key: str) -> bool:
        return any(
            admin_only for page_key, _title, admin_only in _GLOBAL_PAGES if page_key == key
        )

    def _on_nav_clicked(self, index):
        if not index.isValid():
            return
        row = index.row()
        if not 0 <= row < len(self._visible_keys):
            return
        self.show_page_by_key(self._visible_keys[row])

    def _on_header_search(self, text: str) -> None:
        """Header search: jump to Case Management and pass the text on."""
        self.show_page_by_key("cases")
        page = self.case_mgmt_page
        setter = getattr(page, "set_search_text", None)
        if callable(setter):
            setter(text)
            return
        for name in ("search_edit", "search_input", "search_box", "search_field"):
            widget = getattr(page, name, None)
            if isinstance(widget, QLineEdit):
                widget.setText(text)
                widget.returnPressed.emit()
                break


_CASE_PAGES = (
    ("overview", "Overview"),
    ("evidence", "Evidence"),
    ("examination", "Examination"),
    ("artifacts", "Artifacts & Search"),
    ("ai", "AI Analysis"),
    ("entities", "Entities & Timeline"),
    ("findings", "Findings"),
    ("reports", "Reports"),
    ("audit", "Audit & Custody"),
)


class CaseShell(QWidget):
    """Case shell - shown when a case is opened."""

    back_requested = Signal()

    def __init__(self, nav_controller: NavigationController, parent: QWidget | None = None):
        super().__init__(parent)
        self.nav = nav_controller
        self._case_context: CaseContext | None = None
        self._setup_ui()

    def get_current_user(self) -> User | None:
        """Expose the authenticated user to case-scoped pages.

        Pages receive the case shell as their navigation/context object, while
        authentication state is owned by NavigationController.
        """
        getter = getattr(self.nav, "get_current_user", None)
        return getter() if callable(getter) else None

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Case header
        self.header = CaseHeaderBar()
        self.header.back_requested.connect(self.back_requested.emit)
        layout.addWidget(self.header)

        # Content splitter
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setObjectName("NavigationSplitter")
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(1)
        self._splitter = splitter
        layout.addWidget(splitter, 1)

        # Sidebar with branding
        self.sidebar = SidebarWidget()
        sidebar_layout = QVBoxLayout(self.sidebar)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.setSpacing(0)

        # Branding header
        self.branding = BrandingHeader()
        self.branding.toggle_requested.connect(self._toggle_sidebar)
        sidebar_layout.addWidget(self.branding)

        self.nav_list = NavList([])
        self.nav_list.clicked.connect(self._on_nav_clicked)
        self._refresh_nav()
        sidebar_layout.addWidget(self.nav_list, 1)

        # Case context info at bottom (scoped by object name)
        self.context_label = QLabel("No case loaded")
        self.context_label.setObjectName("CaseContextInfo")
        self.context_label.setWordWrap(True)

        sidebar_layout.addWidget(self.context_label)

        splitter.addWidget(self.sidebar)

        # Pages stack
        self.pages_stack = QStackedWidget()
        self.overview_page = OverviewPage()
        self.evidence_page = EvidencePage(nav=self)
        self.examination_page = ExaminationPage()
        self.artifacts_page = ArtifactsSearchPage()
        self.ai_page = AIAnalysisPage(nav=self)
        self.entities_page = EntitiesTimelinePage()
        self.findings_page = FindingsPage(nav=self)
        self.reports_page = ReportsPage()
        self.audit_page = AuditPage(nav=self)

        pages = [
            self.overview_page, self.evidence_page, self.examination_page,
            self.artifacts_page, self.ai_page, self.entities_page,
            self.findings_page, self.reports_page, self.audit_page
        ]
        self._pages_by_key = {
            key: page for (key, _title), page in zip(_CASE_PAGES, pages)
        }
        for page in pages:
            self.pages_stack.addWidget(page)

        self.overview_page.next_action_requested.connect(self.show_page_by_key)
        self.overview_page.edit_case_requested.connect(self._edit_current_case)
        self.evidence_page.examine_requested.connect(self._start_examination_for)

        splitter.addWidget(self.pages_stack)
        splitter.setSizes([260, 800])
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        self.set_sidebar_collapsed(bool(getattr(self.nav, "sidebar_collapsed", False)))

    def _toggle_sidebar(self) -> None:
        collapsed = not self.sidebar.collapsed
        self.nav.sidebar_collapsed = collapsed
        for shell in (self.nav.global_shell, self.nav.case_shell):
            shell.set_sidebar_collapsed(collapsed)

    def set_sidebar_collapsed(self, collapsed: bool) -> None:
        self.sidebar.collapsed = collapsed
        self.branding.set_collapsed(collapsed)
        self.nav_list.set_collapsed(collapsed)
        self.context_label.setVisible(not collapsed)
        self.context_label.setToolTip(self.context_label.text())
        width = 68 if collapsed else 260
        self._splitter.setSizes([width, max(1, self._splitter.width() - width)])

    def _on_nav_clicked(self, index):
        row = index.row()
        if 0 <= row < len(_CASE_PAGES):
            self.show_page_by_key(_CASE_PAGES[row][0])

    def show_page_by_key(self, key: str) -> None:
        """Switch case page by key, keeping the sidebar selection in sync."""
        page = getattr(self, "_pages_by_key", {}).get(key)
        if page is None:
            return

        self.pages_stack.setCurrentWidget(page)
        model = self.nav_list.model
        if model is not None:
            for row, (page_key, _title) in enumerate(_CASE_PAGES):
                if page_key == key:
                    self.nav_list.setCurrentIndex(model.index(row, 0))
                    break
        # Pages that read from the database reload when they are opened, so
        # evidence/jobs created elsewhere show up without pressing Refresh.
        on_shown = getattr(page, "on_page_shown", None)
        if callable(on_shown):
            on_shown()

    def _start_examination_for(self, evidence_pk: int) -> None:
        """Open Examination with the evidence picked on the Evidence page."""
        self.show_page_by_key("examination")
        starter = getattr(self.examination_page, "start_examination_for", None)
        if callable(starter):
            starter(evidence_pk)

    def _refresh_nav(self) -> None:
        self.nav_list.set_entries([
            (tr(title), NavItemDelegate.ICONS.get(title, "•"))
            for _key, title in _CASE_PAGES
        ])

    def retranslate(self) -> None:
        """Re-apply the active language to the case shell."""
        self._refresh_nav()
        retranslate_widgets(self)
        # "No case loaded" is replaced by the context text as soon as a case is
        # open, so only restore it while there is no case.
        if getattr(self, "_case_context", None) is None:
            self.context_label.setText(tr("No case loaded"))

    def _edit_current_case(self) -> None:
        """Open the case edit dialog for the case currently loaded."""
        from PySide6.QtWidgets import QDialog

        from app.auth.service import AuthService
        from app.cases.service import CaseService
        from app.db.session import session_scope
        from app.ui.pages.case_management_page import EditCaseDialog

        context = self._case_context
        if context is None or not getattr(context, "case_id", 0):
            return

        try:
            with session_scope() as session:
                case = CaseService(session).get_case_by_id(context.case_id)
                if case is None:
                    QMessageBox.warning(
                        self, "Case not found",
                        "This case no longer exists. Return to Case Management to refresh.",
                    )
                    return
                investigators = [
                    user for user in AuthService(session).list_users()
                    if user.role.value in ("admin", "investigator")
                ]
        except Exception as exc:
            QMessageBox.critical(self, "Error", f"Failed to load case: {exc}")
            return

        dialog = EditCaseDialog(case, investigators, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        data = dialog.get_data()
        try:
            with session_scope() as session:
                updated = CaseService(session).update_case(
                    context.case_id,
                    title=data["title"],
                    description=data["description"],
                    objective=data["objective"],
                    priority=data["priority"],
                    status=data["status"],
                    assignee_id=data["assignee_id"],
                )
                if updated is None:
                    raise ValueError("case disappeared before it could be saved")
                assignee = updated.assignee.full_name if updated.assignee else "Unassigned"
                refreshed = CaseContext(
                    updated.id,
                    f"CASE-{updated.id:04d}",
                    updated.title,
                    updated.status,
                    updated.priority,
                    assignee,
                )
        except Exception as exc:
            QMessageBox.critical(self, "Error", f"Failed to update case: {exc}")
            return

        self.set_case_context(refreshed)
        QMessageBox.information(
            self, "Success", f"Case '{context.case_id_str}' updated successfully"
        )

    def set_case_context(self, context: CaseContext):
        self._case_context = context
        # Case-scoped services own long-lived sessions. Inject them before the
        # pages load, otherwise the Evidence page cannot persist registrations
        # and the Examination page renders empty selectors and tables.
        self._ensure_case_services()
        self.header.set_case_context(
            context.case_id_str, context.title, context.status,
            context.priority, context.investigator
        )
        self.context_label.setText(
            f"Case: {context.case_id_str}\n{context.title}\n"
            f"Status: {context.status}  |  Priority: {context.priority}"
        )
        self.context_label.setToolTip(self.context_label.text())
        # Pass context to all pages
        for page in self._pages_by_key.values():
            if hasattr(page, "set_case_context"):
                page.set_case_context(context)

        # Wire up search service for artifacts page
        if self.artifacts_page and hasattr(self.artifacts_page, "set_search_service"):
            from app.db.session import session_scope
            with session_scope() as session:
                from app.artifacts.service import SearchService
                search_service = SearchService(session)
                self.artifacts_page.set_search_service(search_service)

        # Wire up finding service for findings page
        if self.findings_page and hasattr(self.findings_page, "set_finding_service"):
            from app.db.session import session_scope
            with session_scope() as session:
                from app.findings.service import FindingService
                finding_service = FindingService(session)
                self.findings_page.set_finding_service(finding_service)

        # Start the analysis queue for this case. It runs one job at a time in
        # the background and waits whenever an examination is running.
        runner = getattr(self, "_analysis_runner", None)
        if runner is not None and getattr(context, "case_id", 0):
            runner.set_case(context.case_id)
            runner.start()

    def _ensure_case_services(self):
        """Create the case-scoped services once and hand them to the pages.

        These sessions stay open for the life of the case shell: a session
        closed by a ``with`` block releases uncommitted writes, which is how
        evidence registrations and examination results used to disappear.
        """
        if getattr(self, "_case_services_ready", False):
            return
        try:
            from app.audit.service import AuditService
            from app.cases.service import CaseService
            from app.db.session import get_session_factory
            from app.evidence.service import EvidenceService
            from app.examination.service import ExaminationService

            factory = get_session_factory()
            self._evidence_service = EvidenceService(factory())
            self._exam_service = ExaminationService(factory())
            self._audit_service = AuditService(factory())
            self._case_overview_service = CaseService(factory())
        except Exception:
            return

        if hasattr(self.evidence_page, "set_evidence_service"):
            self.evidence_page.set_evidence_service(self._evidence_service)
        if hasattr(self.overview_page, "set_case_service"):
            self.overview_page.set_case_service(self._case_overview_service)
        if hasattr(self.examination_page, "set_exam_service"):
            self.examination_page.set_exam_service(self._exam_service)
        if hasattr(self.examination_page, "set_evidence_service"):
            self.examination_page.set_evidence_service(self._evidence_service)
        if self.audit_page and hasattr(self.audit_page, "set_audit_service"):
            self.audit_page.set_audit_service(self._audit_service)

        # Reports need a long-lived session too: generation runs on a worker
        # thread with its own session, while listing/opening reports uses this
        # one.  A session closed by a ``with`` block used to make the page show
        # an empty table and fail with "report service not available".
        if self.reports_page and hasattr(self.reports_page, "set_report_service"):
            try:
                from app.reports.service import ReportService

                self._report_service = ReportService(factory())
                user = None
                get_user = getattr(self.nav, "get_current_user", None)
                if callable(get_user):
                    user = get_user()
                if user is None:
                    from types import SimpleNamespace
                    user = SimpleNamespace(id=1, full_name="Administrator")
                self.reports_page.set_report_service(self._report_service, user)
            except Exception:
                self._report_service = None

        # Entities, relationships and the timeline are produced by a background
        # queue. It gets its own session and runner: the page reads, the runner
        # writes, and neither blocks the window.
        if self.entities_page is not None:
            try:
                from app.analysis.runner import AnalysisRunner
                from app.analysis.service import AnalysisService

                self._analysis_service = AnalysisService(factory())
                if hasattr(self.entities_page, "set_analysis_service"):
                    self.entities_page.set_analysis_service(self._analysis_service)
                if getattr(self, "_analysis_runner", None) is None:
                    self._analysis_runner = AnalysisRunner(self)
                if hasattr(self.entities_page, "set_runner"):
                    self.entities_page.set_runner(self._analysis_runner)
            except Exception:
                self._analysis_runner = None

        self._case_services_ready = True


class NavigationController(QObject):
    """Controls navigation between global and case shells."""

    logged_out = Signal()  # emitted after the user confirmed log out and state was reset

    def __init__(self, main_window: QMainWindow):
        super().__init__(main_window)
        self.main_window = main_window
        self.sidebar_collapsed = False
        self._stack = QStackedWidget()
        self.main_window.setCentralWidget(self._stack)

        self.global_shell = GlobalShell(self)
        self.case_shell = CaseShell(self)

        self._stack.addWidget(self.global_shell)
        self._stack.addWidget(self.case_shell)

        # Connect signals
        self.global_shell.open_case_requested.connect(self.open_case)
        self.global_shell.logout_requested.connect(self.logout)
        self.case_shell.back_requested.connect(self.show_global)

        self._current_user: User | None = None

    def set_user(self, user: User):
        self._current_user = user
        self.global_shell.case_mgmt_page.set_user(user)
        self.global_shell.header.set_user(user)
        # Filter the sidebar for the role and return to the landing page.
        self.global_shell.set_user(user)
        self.show_global()
        self.global_shell.case_mgmt_page.refresh()
        try:
            username = getattr(user, "username", "")
        except Exception:  # detached/expired ORM instance
            username = ""
        if username:
            self.main_window.statusBar().showMessage(f"Signed in as {username}")

    def notify(self, title: str, message: str = "", level: str = "info") -> None:
        """Add an entry to the header's notification bell."""
        self.global_shell.header.add_notification(title, message, level)

    def open_case(self, case_id: int, title: str, status: str, priority: str, investigator: str):
        context = CaseContext(case_id, f"CASE-{case_id:04d}", title, status, priority, investigator)
        self.case_shell.set_case_context(context)
        self._stack.setCurrentWidget(self.case_shell)
        self.main_window.statusBar().showMessage(f"Case: {title} ({context.case_id_str})")
        self.notify("Case opened", f"{context.case_id_str} - {title}", "info")

    def show_global(self):
        self._stack.setCurrentWidget(self.global_shell)
        # The page title already says "Case Management" in the header, sidebar
        # and page body, so the status bar shows a neutral message instead.
        self.main_window.statusBar().showMessage(tr("Ready"))

    def logout(self):
        reply = QMessageBox.question(
            self.main_window,
            "Log out",
            "Log out of IDFA?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self._current_user = None
        # The runner lives on the case shell; without this it kept polling for
        # the signed-out case every four seconds.
        runner = getattr(self.case_shell, "_analysis_runner", None)
        if runner is not None:
            runner.stop()
        self.global_shell.header.set_user(None)
        self.global_shell.header.clear_notifications()
        # Rebuild the sidebar for the signed-out state (no admin pages).
        self.global_shell.set_user(None)
        # Clear case context
        self.case_shell.set_case_context(CaseContext(0, "", "", "", "", ""))
        self.show_global()
        self.logged_out.emit()

    def get_current_user(self) -> User | None:
        return self._current_user

    def shutdown(self) -> None:
        """Stop every page-owned thread before the window goes away.

        Qt aborts the process if a ``QThread`` is destroyed while it is still
        running, which is what closing IDFA during a status check, a search or
        an export used to do. Each page stops its own threads; anything left
        over is reported so the entry point can avoid the abort.
        """
        from app.ui import qt_threads

        for shell in (self.global_shell, self.case_shell):
            # The runner belongs to the case shell, which is where it was built.
            runner = getattr(shell, "_analysis_runner", None)
            if runner is not None:
                runner.stop()
            pages = getattr(shell, "_pages_by_key", {})
            for page in pages.values():
                stop_page = getattr(page, "shutdown", None)
                if callable(stop_page):
                    try:
                        stop_page()
                    except Exception:  # noqa: BLE001 - closing must not raise
                        logging.getLogger(__name__).warning(
                            "A page failed to shut down cleanly", exc_info=True
                        )
        leftover = qt_threads.stop_all(wait_ms=3000)
        if leftover:
            logging.getLogger(__name__).warning(
                "Closing with %d background thread(s) still running", len(leftover)
            )

    def current_page(self) -> QWidget | None:
        """The page the investigator is actually looking at."""
        shell = self._stack.currentWidget()
        stack = getattr(shell, "pages_stack", None)
        if not isinstance(stack, QStackedWidget):
            return None
        return stack.currentWidget()

    def retranslate(self) -> None:
        """Re-apply the active language to both shells."""
        self.global_shell.retranslate()
        self.case_shell.retranslate()


class MainWindow(QMainWindow):
    """Main application window - Professional Forensic Analysis."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("IDFA — Intelligent Digital Forensic Analysis")
        self._relogin_handler: Callable[[], User | None] | None = None
        self._fit_to_screen()

        ThemeManager().apply()

        # Status bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage(tr("Ready"))

        # Navigation controller
        self.nav_controller = NavigationController(self)
        self.nav_controller.logged_out.connect(self._on_logged_out)

        # Background refresh: reloads whatever page is open on the interval
        # chosen in Settings instead of leaving the value unused.
        self.auto_refresh = AutoRefreshController(
            self.nav_controller.current_page, self
        )
        self._apply_ui_settings()
        self.nav_controller.global_shell.settings_page.settings_applied.connect(
            self._apply_ui_settings
        )
        # Language switches rewrite labels in place, but the sidebar rows are
        # model data rather than widget text, so they are rebuilt explicitly.
        LanguageManager().on_change(lambda _language: self.nav_controller.retranslate())
        # Widgets are built in English, so a non-default language has to be
        # applied to them once they exist.
        self.nav_controller.retranslate()

    def _apply_ui_settings(self) -> None:
        """Push the saved General settings into the live UI."""
        config = get_config()
        self.auto_refresh.configure(
            config.ui.auto_refresh, config.ui.refresh_interval_seconds
        )
        # Shut down only an Ollama process IDFA owns. If either chat or
        # embeddings still use Ollama, keep/start it for that local feature.
        # Health probing and process launch take seconds, so they run off the
        # GUI thread; any resulting status is picked up by the AI page refresh.
        uses_local_ollama = (
            config.ollama.provider != "openai"
            or config.embeddings.provider != "openai"
        )
        threading.Thread(
            target=(
                ensure_ollama_running if uses_local_ollama else stop_managed_ollama
            ),
            name="idfa-ollama-lifecycle",
            daemon=True,
        ).start()

    def set_relogin_handler(self, handler: Callable[[], User | None]) -> None:
        """Register a function that shows the login dialog again.

        It must return the authenticated User, or None if the person cancelled.
        """
        self._relogin_handler = handler

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        """Stop page threads before the window is destroyed.

        Without this, a thread that is still running when the window closes is
        destroyed with it and Qt aborts the process instead of exiting.
        """
        try:
            self.nav_controller.shutdown()
        except Exception:  # noqa: BLE001 - closing must not raise
            logging.getLogger(__name__).warning("Shutdown failed", exc_info=True)
        super().closeEvent(event)

    def _on_logged_out(self) -> None:
        if self._relogin_handler is None:
            # Nothing can bring the login screen back, so exit cleanly rather
            # than leaving a signed-out window that still shows data.
            self.close()
            return
        self.hide()
        user = self._relogin_handler()
        if user is not None:
            self.nav_controller.set_user(user)
            self.show()
        else:
            QApplication.quit()

    def _fit_to_screen(self) -> None:
        """Size the window to the usable screen area (excludes the taskbar).

        A fixed 1600x1000 window is taller than the usable area on 1080p
        displays, which pushes the status bar below the taskbar and clips it.
        """
        screen = self.screen() or QApplication.primaryScreen()
        avail = screen.availableGeometry()

        width = min(1600, int(avail.width() * 0.94))
        height = min(1000, int(avail.height() * 0.94))

        self.setMinimumSize(min(1200, avail.width()), min(760, avail.height()))
        self.resize(width, height)
        self.move(
            avail.x() + (avail.width() - width) // 2,
            avail.y() + (avail.height() - height) // 2,
        )

    def get_nav_controller(self) -> NavigationController:
        return self.nav_controller
