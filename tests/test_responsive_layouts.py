"""Shared responsive sizing for evidence/detail split views."""
from __future__ import annotations

from PySide6.QtWidgets import QFrame, QSizePolicy, QSplitter, QWidget

from app.ui.header_bar import AppHeaderBar
from app.ui.layouts import (
    DETAIL_PANE_MAX_WIDTH,
    DETAIL_PANE_MIN_WIDTH,
    configure_detail_pane,
    configure_detail_splitter,
)


def test_detail_panes_share_responsive_width_bounds(qt_app):
    pane = QFrame()

    configure_detail_pane(pane)

    assert pane.minimumWidth() == DETAIL_PANE_MIN_WIDTH == 280
    assert pane.maximumWidth() == DETAIL_PANE_MAX_WIDTH == 460
    assert pane.sizePolicy().horizontalPolicy() == QSizePolicy.Policy.Preferred
    assert pane.sizePolicy().verticalPolicy() == QSizePolicy.Policy.Expanding


def test_detail_splitter_has_consistent_resizable_handle(qt_app):
    splitter = QSplitter()
    splitter.addWidget(QWidget())
    splitter.addWidget(QFrame())

    configure_detail_splitter(splitter, preferred_detail_width=360)

    assert splitter.handleWidth() == 6
    assert splitter.childrenCollapsible() is False
    assert splitter.sizes()[1] == 360


def test_global_search_can_shrink_on_narrow_windows(qt_app):
    header = AppHeaderBar()

    assert header._search_edit.minimumWidth() == 160
    assert header._search_edit.maximumWidth() == 340
