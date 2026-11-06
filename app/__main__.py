"""IDFA Application Entry Point."""
from __future__ import annotations

import logging
import os
import sys
import traceback

from PySide6.QtWidgets import QApplication, QInputDialog, QLineEdit, QMessageBox

from app.db import load_all_models
from app.db.session import get_session_factory, init_db
from app.logging_config import setup_logging

# Load all models to register relationships
load_all_models()
from app.auth.models import User, UserRole
from app.auth.service import AuthService
from app.cases.service import CaseService
from app.i18n import LanguageManager
from app.ui.dialogs.data_folder_dialog import resolve_startup
from app.ui.login_dialog import LoginDialog
from app.ui.main_window import MainWindow
from app.ui.theme.manager import ThemeManager


def create_default_user() -> bool:
    """Provision a password chosen by the operator on the very first run.

    Existing installations never receive an automatic replacement admin
    account. In particular, deleting or renaming the old 'admin' user must
    not silently recreate that account with a known default password.
    """
    session_factory = get_session_factory()
    with session_factory() as session:
        if session.query(User.id).first() is not None:
            return True

    QMessageBox.information(
        None,
        "First-run administrator setup",
        "No user accounts exist yet. Set an administrator password to secure "
        "this installation. The password will not be displayed again.",
    )
    while True:
        password, accepted = QInputDialog.getText(
            None, "Create administrator", "Administrator password (12+ characters):",
            QLineEdit.EchoMode.Password,
        )
        if not accepted:
            return False
        if len(password) < 12:
            QMessageBox.warning(
                None, "Password too short", "Use a password of at least 12 characters.",
            )
            continue
        confirmation, accepted = QInputDialog.getText(
            None, "Confirm administrator password", "Enter the same password again:",
            QLineEdit.EchoMode.Password,
        )
        if not accepted:
            return False
        if password != confirmation:
            QMessageBox.warning(
                None, "Passwords do not match", "Please choose and confirm the password again.",
            )
            continue
        break

    with session_factory() as session:
        # A second application process may have provisioned an account while
        # the operator was viewing the dialog. Never add a default admin then.
        if session.query(User.id).first() is not None:
            return True
        auth_service = AuthService(session)
        auth_service.create_user(
            username="admin",
            email="admin@idfa.local",
            password=password,
            full_name="Administrator",
            role=UserRole.ADMIN,
        )
        session.commit()
    return True


def recover_interrupted_jobs() -> int:
    """Close out jobs that were running when the application last exited.

    The worker is a separate process, so a job can outlive the GUI only if it
    was orphaned. Either way no progress is being tracked any more, and a
    ``RUNNING`` row would block retries forever.
    """
    from app.examination.service import ExaminationService

    session_factory = get_session_factory()
    with session_factory() as session:
        try:
            count = ExaminationService(session).mark_interrupted_jobs()
            session.commit()
        except Exception:
            session.rollback()
            logging.getLogger(__name__).warning(
                "Could not close out interrupted examination jobs", exc_info=True
            )
            return 0

    if count:
        logging.getLogger(__name__).info(
            "Marked %s examination job(s) as interrupted", count
        )
    return count


def show_login(session_factory) -> User | None:
    """Show login dialog and return authenticated User or None if cancelled."""
    authenticated_user: User | None = None

    def login_callback(username: str, password: str) -> tuple[bool, User | None]:
        nonlocal authenticated_user
        with session_factory() as session:
            auth_service = AuthService(session)
            user = auth_service.authenticate_user(username, password)
            if user:
                auth_service.update_last_login(user.id)
                session.commit()
                authenticated_user = user
                return True, user
        return False, None

    login_dialog = LoginDialog()
    login_dialog.set_login_callback(login_callback)

    if login_dialog.exec() != LoginDialog.DialogCode.Accepted:
        return None
    return authenticated_user


def _leave_if_threads_are_still_running() -> None:
    """Exit immediately when a background thread refused to stop.

    Qt aborts the process when a ``QThread`` is destroyed while it is still
    running, and Windows reports that as a crash. ``MainWindow.closeEvent`` has
    already asked every page to stop; if something is still busy (a large copy,
    for example), leaving here is better than letting interpreter shutdown kill
    the process after the window has closed.
    """
    from app.ui import qt_threads

    remaining = qt_threads.alive()
    if not remaining:
        return
    logging.getLogger(__name__).warning(
        "Exiting with %d background thread(s) still running", len(remaining)
    )
    logging.shutdown()
    os._exit(0)


def main() -> int:
    """Main application entry point."""
    # Qt must exist before the startup dialogs: the data folder is chosen
    # before logging is configured or a database connection is opened, so a
    # missing folder can be reported and fixed instead of crashing.
    app = QApplication(sys.argv)
    app.setApplicationName("IDFA")
    app.setApplicationVersion("0.1.0")
    app.setOrganizationName("KSIT")

    config = resolve_startup()
    if config is None:
        return 0

    # Apply the saved theme before any window is built, so the login dialog and
    # the main window agree and nothing flashes the wrong colours.
    from app.config import get_config

    ThemeManager().set_mode(get_config().ui.theme)
    # Same reasoning for language: the login dialog is built next and should
    # already be in the configured language.
    LanguageManager().set_language(get_config().ui.language, retranslate=False)

    # Setup logging
    setup_logging()
    # Initialize database
    init_db()
    if not create_default_user():
        return 0  # Setup cancelled; no insecure credentials are created.
    # A job cannot still be running: the previous GUI process is gone.
    recover_interrupted_jobs()

    # Create main window
    window = MainWindow()

    # Get services
    session_factory = get_session_factory()

    # Create a session for initial auth check (services for global shell)
    with session_factory() as session:
        auth_service = AuthService(session)
        case_service = CaseService(session)

        # Wire up global shell
        global_shell = window.nav_controller.global_shell
        global_shell.case_mgmt_page.set_case_service(case_service)

    # Register login handler for re-login after logout
    window.set_relogin_handler(lambda: show_login(session_factory))

    # Show login first
    user = show_login(session_factory)
    if user is None:
        return 0

    # User authenticated: set user in nav controller and show main window
    window.nav_controller.set_user(user)

    window.show()
    code = app.exec()
    _leave_if_threads_are_still_running()
    return code


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        traceback.print_exc()
        QMessageBox.critical(None, "Fatal Error", f"Application failed to start:\n{e}")
        sys.exit(1)
