"""Offscreen tests for the role-scoped, keyboard-operated page switcher."""
from __future__ import annotations

import pytest


def test_quick_switcher_filters_only_supplied_routes(qt_app):
    from PySide6.QtCore import Qt

    from app.ui.quick_switcher import QuickSwitcher

    dialog = QuickSwitcher([
        ("global:cases", "Case Management", "Find all cases"),
        ("case:ai", "AI Analysis", "Current investigation workspace"),
        ("case:reports", "Reports", "Generate evidence-based reports"),
    ])
    assert dialog.results.count() == 3
    dialog.search.setText("analysis")
    assert dialog.results.count() == 1
    assert dialog.results.item(0).data(Qt.ItemDataRole.UserRole) == "case:ai"
    dialog.search.setText("case")
    assert dialog.results.count() == 1
    dialog.search.setText("nothing matches")
    assert dialog.results.count() == 0
    assert dialog.selected_route is None
    dialog.close()


def test_quick_switcher_enter_activates_selected_page(qt_app):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from app.ui.quick_switcher import QuickSwitcher

    dialog = QuickSwitcher([
        ("global:cases", "Cases", "All cases"),
        ("global:audit", "Global Audit", "Audit history"),
    ])
    dialog.show()
    qt_app.processEvents()
    dialog.search.setText("audit")
    QTest.keyClick(dialog.search, Qt.Key.Key_Return)
    assert dialog.selected_route == "global:audit"
    assert dialog.result() == dialog.DialogCode.Accepted
    dialog.close()


def test_quick_switcher_arrow_navigation_keeps_search_focus(qt_app):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from app.ui.quick_switcher import QuickSwitcher

    dialog = QuickSwitcher([
        ("case:overview", "Overview", "Case details"),
        ("case:evidence", "Evidence", "Evidence and integrity"),
        ("case:reports", "Reports", "Forensic reports"),
    ])
    dialog.show()
    qt_app.processEvents()
    assert dialog.results.currentRow() == 0
    QTest.keyClick(dialog.search, Qt.Key.Key_Down)
    assert dialog.results.currentRow() == 1
    QTest.keyClick(dialog.search, Qt.Key.Key_Up)
    assert dialog.results.currentRow() == 0
    assert dialog.search.hasFocus()
    dialog.close()


def test_quick_switcher_empty_enter_does_not_choose_hidden_destination(qt_app):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from app.ui.quick_switcher import QuickSwitcher

    dialog = QuickSwitcher([("global:cases", "Cases", "All cases")])
    dialog.show()
    dialog.search.setText("no matching case")
    QTest.keyClick(dialog.search, Qt.Key.Key_Return)
    assert dialog.selected_route is None
    dialog.close()
