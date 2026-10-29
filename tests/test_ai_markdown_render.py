"""Adaptive rendering of AI answers: Markdown when the model writes Markdown,
plain text when it does not.

The models answer either as prose or as a Markdown report. Both must be
readable in the same chat, so the detection is deliberately conservative: a
plain sentence keeps its literal line breaks instead of being re-flowed.
"""
from __future__ import annotations

import pytest
from PySide6.QtWidgets import QLabel

from app.ui.markdown import MarkdownView, looks_like_markdown
from app.ui.pages.ai_analysis_page import ChatMessageWidget

MARKDOWN_ANSWERS = [
    "# Forensic Analysis Report\n\n**Case Reference:** ART-2026-001",
    "## 1. Executive Summary\n\nThe artifacts came from Windows XP.",
    "```\nSHA-256: abc123\n```",
    "See [the evidence](https://example.invalid/case/1).",
    "| Source | Path | Type |\n|---|---|---|\n| a | /x | File |",
    "Notes:\n\n- first finding\n- second finding",
    "Steps:\n\n1. Hash the image\n2. Mount it read-only",
    "Key finding **confirmed** by two artifacts.",
    "Run `sha256sum image.001` to verify.",
    "> Quoted artifact content.",
    "---\n\n## Artifact Inventory",
    "Removed by ~~suspect~~ analyst.",
]

PLAIN_ANSWERS = [
    "The file was created on 12 March.\nIt has no owner recorded.",
    "Ticket #12 was reviewed and closed.",
    "Use 2 * 3 * 4 for the size check.",
    "The user_name_field is populated.",
    "Path: C:\\Users\\Public\\Documents\\notes.txt",
    "Evidence collected - chain of custody intact.",
    "The hash matches the bagged value.",
    "",
]


@pytest.mark.parametrize("text", MARKDOWN_ANSWERS)
def test_markdown_answers_are_detected(text):
    assert looks_like_markdown(text) is True


@pytest.mark.parametrize("text", PLAIN_ANSWERS)
def test_plain_answers_stay_plain(text):
    assert looks_like_markdown(text) is False


def test_ai_disclaimer_keeps_its_characters(qt_app):
    """Guards against an encoding round-trip mangling the warning emoji."""
    widget = ChatMessageWidget("plain answer", is_user=False)

    labels = [label.text() for label in widget.findChildren(QLabel)]
    assert "⚠️ AI-generated, unverified" in labels
    assert not any("\ufffd" in text for text in labels)


def test_plain_answer_renders_as_selectable_plain_text(qt_app):
    text = "Line one has the finding.\nLine two keeps its break."
    widget = ChatMessageWidget(text, is_user=False)

    assert widget.findChildren(MarkdownView) == []
    labels = [label.text() for label in widget.findChildren(QLabel)]
    assert text in labels


def test_markdown_answer_renders_processed_markdown(qt_app):
    text = "# Forensic Analysis Report\n\n**Case Reference:** ART-2026-001"
    widget = ChatMessageWidget(text, is_user=False)

    views = widget.findChildren(MarkdownView)
    assert len(views) == 1
    html = views[0].toHtml().lower()
    assert "<h1" in html
    assert "forensic analysis report" in html
    # The markers themselves must be consumed, not shown as raw characters.
    assert "**case reference:**" not in views[0].toPlainText().lower()


def test_markdown_table_is_rendered_as_a_table(qt_app):
    text = "| Source | Path |\n|---|---|\n| a | /x |"
    widget = ChatMessageWidget(text, is_user=False)

    view = widget.findChildren(MarkdownView)[0]
    assert "<table" in view.toHtml().lower()


def test_saved_finding_detail_renders_ai_markdown(qt_app):
    from PySide6.QtWidgets import QTextEdit

    from app.ui.pages.findings_page import _set_rich_text

    editor = QTextEdit()
    _set_rich_text(editor, "## Key Finding\n\n**Confirmed** by two artifacts.")
    assert "**" not in editor.toPlainText()
    assert "<h2" in editor.toHtml().lower()

    plain = "Line one has the finding.\nLine two keeps its break."
    _set_rich_text(editor, plain)
    assert editor.toPlainText() == plain


def test_markdown_view_fits_its_document_without_own_scrollbar(qt_app):
    text = "# Report\n\n" + "\n\n".join(
        f"Paragraph {i} with enough words to wrap across the bubble width."
        for i in range(12)
    )
    widget = ChatMessageWidget(text, is_user=False)
    widget.resize(520, 200)
    widget.show()
    qt_app.processEvents()

    view = widget.findChildren(MarkdownView)[0]
    assert view.verticalScrollBarPolicy().name == "ScrollBarAlwaysOff"
    document_height = round(view.document().size().height())
    assert abs(view.height() - document_height) <= 2
    assert view.height() > 200
    widget.close()
