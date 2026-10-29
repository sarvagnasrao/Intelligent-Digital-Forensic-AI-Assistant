"""Shared Markdown rendering helpers for AI-generated text.

Models answer either as prose or as a Markdown report, and both appear in more
than one place (the AI chat and a saved finding). Detection is deliberately
conservative: text with no Markdown syntax keeps its literal line breaks
instead of being re-flowed by the Markdown importer.
"""
from __future__ import annotations

import math
import re

import shiboken6
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame,
    QSizePolicy,
    QTextBrowser,
    QWidget,
)

from app.ui.theme.tokens import Color, Typography

# Markdown syntax the models actually emit. Each pattern is unambiguous on its
# own, so one hit is enough to treat the text as Markdown. Emphasis is checked
# separately (only paired ``**`` counts, never ``__``, so snake_case
# identifiers stay literal), and bullet/numbered lists need at least two items
# because a lone "- " line appears in ordinary prose.
_MARKDOWN_SIGNALS = (
    re.compile(r"(?m)^[ \t]{0,3}#{1,6}[ \t]+\S"),                 # # heading
    re.compile(r"```|~~~"),                                        # code fence
    re.compile(r"(?m)^[ \t]{0,3}>[ \t]+\S"),                       # > quote
    re.compile(r"!?\[[^\]\n]{1,300}\]\([^)\s]{1,500}\)"),          # [text](url)
    re.compile(r"(?m)^[ \t]*\|?[ \t:|-]*-{3,}[ \t:|-]*\|?[ \t]*$"),  # table |---
    re.compile(r"\*\*(?=\S)(?:[^*\n]|\*(?!\*))+?(?<=\S)\*\*"),      # **bold**
    re.compile(r"`[^`\n]{1,300}`"),                                # `code`
    re.compile(r"~~(?=\S).+?(?<=\S)~~"),                           # ~~strike~~
    re.compile(r"(?m)^[ \t]{0,3}([-*_])[ \t]*(?:\1[ \t]*){2}$"),    # --- rule
)
_MARKDOWN_BULLETS = re.compile(r"(?m)^[ \t]{0,3}[-*+][ \t]+\S")
_MARKDOWN_NUMBERED = re.compile(r"(?m)^[ \t]{0,3}\d+[.)][ \t]+\S")


def looks_like_markdown(text: str) -> bool:
    """True when an AI answer uses Markdown syntax worth rendering.

    Plain prose stays plain: a single stray asterisk or hyphen is not enough,
    so a response written as ordinary sentences keeps its line breaks.
    """
    if not text or not text.strip():
        return False
    if any(pattern.search(text) for pattern in _MARKDOWN_SIGNALS):
        return True
    if len(_MARKDOWN_BULLETS.findall(text)) >= 2:
        return True
    return len(_MARKDOWN_NUMBERED.findall(text)) >= 2


class MarkdownView(QTextBrowser):
    """Read-only Markdown view that grows to fit its document.

    The chat lives in a scroll area, so this widget never scrolls itself: it
    re-flows the document to its own width and pins its height to the rendered
    result. That keeps one scrollbar for the transcript instead of one per
    message.
    """

    def __init__(self, text: str, parent: QWidget | None = None):
        super().__init__(parent)
        self._fitting = False
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setOpenExternalLinks(True)
        self.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.LinksAccessibleByMouse
        )
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self.setMinimumSize(0, 0)
        self.setStyleSheet("QTextBrowser { background: transparent; border: none; }")

        document = self.document()
        document.setDocumentMargin(0)
        font = QFont(Typography.FONT_FAMILY, Typography.BODY_MD[0])
        document.setDefaultFont(font)
        # QTextDocument ignores the widget palette in some themes, so the base
        # colours are pinned here; tables and code blocks get a readable frame.
        document.setDefaultStyleSheet(
            f"body {{ color: {Color.TEXT_PRIMARY.name()}; }}"
            f"a {{ color: {Color.TEXT_LINK.name()}; }}"
            f"pre, code {{ font-family: Consolas, 'Courier New', monospace; }}"
            f"pre {{ background: {Color.BG_SECONDARY.name()}; }}"
            f"table {{ border-collapse: collapse; }}"
            f"th, td {{ border: 1px solid {Color.BORDER_LIGHT.name()};"
            f" padding: 3px 6px; }}"
            "h1, h2, h3, h4, h5, h6 { margin-top: 8px; margin-bottom: 4px; }"
            "p { margin-top: 0; margin-bottom: 6px; }"
        )
        self.setMarkdown(text)
        document.documentLayout().documentSizeChanged.connect(self._fit_height)
        QTimer.singleShot(0, self._fit_height)

    def _fit_height(self, *_args):
        # documentSizeChanged and the zero-delay timer can fire after the
        # containing chat bubble has deleted this child widget.
        if not shiboken6.isValid(self):
            return
        if self._fitting:
            return
        self._fitting = True
        try:
            document = self.document()
            width = self.viewport().width()
            if width > 0 and int(document.textWidth()) != width:
                document.setTextWidth(width)
            height = math.ceil(document.size().height())
            if height > 0 and self.height() != height:
                self.setFixedHeight(height)
        finally:
            self._fitting = False

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_height()
