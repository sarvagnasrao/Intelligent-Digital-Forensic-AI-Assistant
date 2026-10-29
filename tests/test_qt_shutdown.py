"""Shutdown of page-owned threads.

Qt aborts the process when a ``QThread`` is destroyed while its thread is still
running, which is why closing IDFA during a status check used to crash. These
tests cover the helper that prevents it; the page hooks are checked by building
the pages and calling ``shutdown()`` on them.
"""
from __future__ import annotations

import threading
import time

import pytest


def test_stop_waits_for_a_short_thread():
    from PySide6.QtCore import QThread

    from app.ui import qt_threads

    class Short(QThread):
        def run(self):
            time.sleep(0.05)

    thread = qt_threads.track(Short())
    thread.start()

    assert qt_threads.stop(thread, wait_ms=3000) is True
    assert not thread.isRunning()


def test_stop_reports_a_thread_that_ignores_quit():
    """``quit()`` does nothing for a ``run()`` override, so the wait decides."""
    from PySide6.QtCore import QThread

    from app.ui import qt_threads

    release = threading.Event()

    class Stubborn(QThread):
        def run(self):
            release.wait(10)

    thread = qt_threads.track(Stubborn())
    thread.start()
    try:
        assert qt_threads.stop(thread, wait_ms=100) is False
        assert thread in qt_threads.alive()
    finally:
        # Never leave a running thread behind: that is the abort this module
        # exists to prevent, and it would take the test process down.
        release.set()
        thread.wait(3000)
    assert not thread.isRunning()


def test_alive_forgets_threads_that_have_finished():
    from PySide6.QtCore import QThread

    from app.ui import qt_threads

    class Immediate(QThread):
        def run(self):
            return

    thread = qt_threads.track(Immediate())
    thread.start()
    thread.wait(3000)

    assert thread not in qt_threads.alive()


@pytest.mark.parametrize(
    ("module_name", "class_name"),
    [
        ("app.ui.pages.ai_analysis_page", "AIAnalysisPage"),
        ("app.ui.pages.artifacts_search_page", "ArtifactsSearchPage"),
        ("app.ui.pages.evidence_page", "EvidencePage"),
        ("app.ui.pages.reports_page", "ReportsPage"),
    ],
)
def test_case_pages_stop_their_threads_on_shutdown(
    config_home, qt_app, module_name, class_name
):
    """Every page that owns a QThread must expose an idempotent shutdown."""
    import importlib

    page_class = getattr(importlib.import_module(module_name), class_name)
    page = page_class()
    try:
        page.shutdown()
        page.shutdown()
    finally:
        page.close()


def test_the_main_window_has_a_close_hook():
    """A missing closeEvent is exactly how the crash reached the user."""
    from app.ui.main_window import MainWindow, NavigationController

    assert callable(getattr(MainWindow, "closeEvent", None))
    assert callable(getattr(NavigationController, "shutdown", None))


def test_logout_stops_the_case_analysis_runner(config_home, data_dir, qt_app, monkeypatch):
    """The runner belongs to the case shell, not the navigation controller."""
    from PySide6.QtWidgets import QMessageBox

    from app.auth.models import Case, User
    from app.config import Config, save_config, set_data_dir
    from app.db import Base, load_all_models
    from app.db.session import get_engine, get_session_factory
    from app.ui import main_window as main_window_module

    # `main_window` imported these names directly, so patching the module they
    # come from would not stop the lifecycle thread from launching a real
    # Ollama server on the test machine.
    monkeypatch.setattr(main_window_module, "ensure_ollama_running", lambda: True)
    monkeypatch.setattr(main_window_module, "stop_managed_ollama", lambda: False)

    save_config(set_data_dir(Config(), data_dir))
    load_all_models()
    Base.metadata.create_all(get_engine())
    session = get_session_factory()()
    try:
        user = User(
            username="runner", email="r@example.test", password_hash="x", full_name="R"
        )
        session.add(user)
        session.commit()
        case = Case(case_id="C-RUN", title="Runner", created_by_id=user.id)
        session.add(case)
        session.commit()
        case_id, case_title = case.id, case.title
    finally:
        session.close()

    from app.ui.main_window import MainWindow

    monkeypatch.setattr(
        QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Yes
    )
    window = MainWindow()
    try:
        window.nav_controller.open_case(case_id, case_title, "Open", "Normal", "A")
        runner = window.nav_controller.case_shell._analysis_runner
        assert runner is not None
        assert runner._timer.isActive()

        window.nav_controller.logout()

        assert not runner._timer.isActive()
    finally:
        window.close()

    from app.ui import qt_threads

    assert not qt_threads.alive(), "closing the window must not leave a thread running"
