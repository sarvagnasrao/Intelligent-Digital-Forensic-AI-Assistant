"""Background refresh of the visible page."""
from __future__ import annotations

import pytest
from PySide6.QtWidgets import QWidget

from app.ui.auto_refresh import MIN_INTERVAL_SECONDS, AutoRefreshController


class _Page(QWidget):
    def __init__(self):
        super().__init__()
        self.refreshes = 0

    def refresh(self) -> None:
        self.refreshes += 1


class _PageWithoutRefresh(QWidget):
    pass


class _Current:
    """Stands in for NavigationController.current_page()."""

    def __init__(self, page):
        self.page = page

    def __call__(self):
        return self.page


@pytest.fixture
def shown(qt_app):
    """Show widgets, because the controller only refreshes visible pages.

    In the application the current page always sits inside a shown window; an
    offscreen widget is invisible until ``show()`` is called.
    """
    created = []

    def show(widget):
        widget.show()
        created.append(widget)
        return widget

    yield show

    for widget in created:
        widget.close()
        widget.deleteLater()


def test_disabled_timer_does_not_run(qt_app):
    page = _Page()
    controller = AutoRefreshController(_Current(page))

    controller.configure(False, 30)

    assert controller.enabled is False
    assert controller.interval_seconds == 30


def test_enabling_starts_the_timer_with_the_configured_interval(qt_app):
    controller = AutoRefreshController(_Current(_Page()))

    controller.configure(True, 45)

    assert controller.enabled is True
    assert controller.interval_seconds == 45


def test_interval_is_clamped_to_the_minimum(qt_app):
    controller = AutoRefreshController(_Current(_Page()))

    controller.configure(True, 1)

    assert controller.interval_seconds == MIN_INTERVAL_SECONDS


def test_refresh_now_reloads_the_current_page(qt_app, shown):
    page = shown(_Page())
    controller = AutoRefreshController(_Current(page))

    controller.refresh_now()

    assert page.refreshes == 1


def test_a_hidden_page_is_not_refreshed(qt_app):
    """Switching to another page must not reload the one left behind."""
    page = _Page()
    controller = AutoRefreshController(_Current(page))

    controller.refresh_now()

    assert page.refreshes == 0


def test_page_without_refresh_is_ignored(qt_app):
    controller = AutoRefreshController(_Current(_PageWithoutRefresh()))

    controller.refresh_now()  # must not raise


def test_no_current_page_is_ignored(qt_app):
    controller = AutoRefreshController(_Current(None))

    controller.refresh_now()  # must not raise


def test_reconfigure_stops_the_timer(qt_app):
    controller = AutoRefreshController(_Current(_Page()))
    controller.configure(True, 30)

    controller.configure(False, 30)

    assert controller.enabled is False


def test_a_failing_page_stops_the_timer_instead_of_spamming(qt_app, shown):
    class _Broken(QWidget):
        def refresh(self) -> None:
            raise RuntimeError("database is gone")

    controller = AutoRefreshController(_Current(shown(_Broken())))
    controller.configure(True, 30)
    assert controller.enabled is True

    controller.refresh_now()

    assert controller.enabled is False
