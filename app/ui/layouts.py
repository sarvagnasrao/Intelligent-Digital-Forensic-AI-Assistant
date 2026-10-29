"""Shared layout helpers for responsive page splitters."""
from __future__ import annotations

from PySide6.QtWidgets import QSizePolicy, QSplitter, QWidget

DETAIL_PANE_MIN_WIDTH = 280
DETAIL_PANE_MAX_WIDTH = 460


def configure_detail_pane(pane: QWidget) -> None:
    """Give page detail panes a consistent, resizable width range."""
    pane.setMinimumWidth(DETAIL_PANE_MIN_WIDTH)
    pane.setMaximumWidth(DETAIL_PANE_MAX_WIDTH)
    pane.setSizePolicy(
        QSizePolicy.Policy.Preferred,
        QSizePolicy.Policy.Expanding,
    )


def configure_detail_splitter(
    splitter: QSplitter,
    *,
    preferred_detail_width: int = 360,
) -> None:
    """Use a common table/detail ratio while leaving the handle user-resizable."""
    splitter.setChildrenCollapsible(False)
    splitter.setHandleWidth(6)
    splitter.setStretchFactor(0, 1)
    splitter.setStretchFactor(1, 0)
    splitter.setSizes([preferred_detail_width * 2, preferred_detail_width])
