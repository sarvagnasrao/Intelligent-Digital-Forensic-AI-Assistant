"""Case sidebar headings are distinct from their navigable child pages."""
from PySide6.QtWidgets import QStackedWidget, QWidget

from app.ui.base import NavList
from app.ui.main_window import CaseShell, _CASE_PAGES, _CaseNavDelegate


def test_evidence_group_and_child_are_distinct(qt_app):
    shell = CaseShell.__new__(CaseShell)
    QWidget.__init__(shell)
    shell.nav_list = NavList([])
    shell.pages_stack = QStackedWidget()
    shell._pages_by_key = {key: QWidget() for key, _ in _CASE_PAGES}
    for page in shell._pages_by_key.values():
        shell.pages_stack.addWidget(page)
    shell._current_key = "overview"
    shell._expanded_group = None
    shell._refresh_nav()

    row = shell._nav_rows.index(("group", "Evidence"))
    shell._on_nav_clicked(shell.nav_list.model.index(row, 0))
    labels = [shell.nav_list.model.item(i).text() for i in range(shell.nav_list.model.rowCount())]
    assert labels.count("Evidence") == 1
    assert labels[row] == "Evidence & Examination"
    assert isinstance(shell.nav_list.itemDelegate(), _CaseNavDelegate)
    child = shell._nav_rows.index(("page", "evidence"))
    shell._on_nav_clicked(shell.nav_list.model.index(child, 0))
    assert shell.pages_stack.currentWidget() is shell._pages_by_key["evidence"]
