"""Grouped case navigation retains every existing page route."""
from PySide6.QtWidgets import QStackedWidget, QWidget

from app.ui.base import NavList
from app.ui.main_window import _CASE_GROUPS, _CASE_PAGES, CaseShell


class Page(QWidget):
    def __init__(self):
        super().__init__()
        self.shown = 0

    def on_page_shown(self):
        self.shown += 1


def make_shell():
    # Exercise navigation without constructing real pages or starting services.
    shell = CaseShell.__new__(CaseShell)
    QWidget.__init__(shell)
    shell.nav_list = NavList([])
    shell.pages_stack = QStackedWidget()
    shell._pages_by_key = {key: Page() for key, _ in _CASE_PAGES}
    for page in shell._pages_by_key.values():
        shell.pages_stack.addWidget(page)
    shell._current_key = "overview"
    shell._expanded_group = None
    shell._refresh_nav()
    return shell


def test_groups_cover_all_routes_and_programmatic_navigation(qt_app):
    shell = make_shell()
    keys = [key for _, group, _ in _CASE_GROUPS for key in group]
    assert sorted(keys) == sorted(key for key, _ in _CASE_PAGES)
    assert len(keys) == len(set(keys))
    for key in keys:
        shell.show_page_by_key(key)
        assert shell.pages_stack.currentWidget() is shell._pages_by_key[key]
        assert shell._pages_by_key[key].shown == 1
        row = shell.nav_list.currentIndex().row()
        kind, value = shell._nav_rows[row]
        assert value == key if kind == "page" else value == "Overview"
        shell._refresh_nav()
        assert shell.nav_list.currentIndex().row() == row
    shell.show_page_by_key("unknown")
    assert shell._current_key == keys[-1]


def test_group_clicks_expose_pages_in_compact_mode(qt_app):
    shell = make_shell()
    shell.nav_list.set_collapsed(True)
    assert [value for _, value in shell._nav_rows] == [
        "Overview", "Evidence", "Explore", "Investigation", "Report & History"
    ]
    for title, keys, _ in _CASE_GROUPS[1:]:
        row = shell._nav_rows.index(("group", title))
        shell._on_nav_clicked(shell.nav_list.model.index(row, 0))
        for key in keys:
            row = shell._nav_rows.index(("page", key))
            assert shell.nav_list.model.item(row).toolTip().strip()
            shell._on_nav_clicked(shell.nav_list.model.index(row, 0))
            assert shell.pages_stack.currentWidget() is shell._pages_by_key[key]
        row = shell._nav_rows.index(("group", title))
        shell._on_nav_clicked(shell.nav_list.model.index(row, 0))
        assert ("page", keys[0]) not in shell._nav_rows
        assert shell._nav_rows[shell.nav_list.currentIndex().row()] == ("group", title)
