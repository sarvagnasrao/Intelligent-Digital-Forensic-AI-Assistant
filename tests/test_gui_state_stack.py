"""Reusable GUI state widgets must show current messages and actions."""
from __future__ import annotations


def _message(widget):
    from PySide6.QtWidgets import QLabel

    label = next(
        (child for child in widget.findChildren(QLabel) if child.property("stateMessage")),
        None,
    )
    assert label is not None
    return label.text()


def test_state_stack_reuses_widgets_but_refreshes_messages(qt_app):
    from PySide6.QtWidgets import QWidget

    from app.ui.base import StateStackedWidget

    stack = StateStackedWidget()
    content = QWidget()
    stack.addWidget(content)

    stack.set_state(stack.STATE_LOADING, "Reading disk")
    loading_widget = stack.currentWidget()
    assert _message(loading_widget) == "Reading disk"
    previous_count = stack.count()
    stack.set_state(stack.STATE_LOADING, "Indexing extracted text")
    assert stack.count() == previous_count
    assert stack.currentWidget() is loading_widget
    assert _message(loading_widget) == "Indexing extracted text"

    stack.set_state(stack.STATE_EMPTY, "No matching artifacts")
    empty_widget = stack.currentWidget()
    assert _message(empty_widget) == "No matching artifacts"
    stack.set_state(stack.STATE_EMPTY, "No saved findings")
    assert stack.currentWidget() is empty_widget
    assert _message(empty_widget) == "No saved findings"

    stack.set_state(stack.STATE_UNAVAILABLE, "Local AI service offline")
    assert _message(stack.currentWidget()) == "Local AI service offline"
    stack.set_state(stack.STATE_CONTENT)
    assert stack.currentWidget() is content
    stack.close()


def test_error_state_uses_latest_retry_callback_and_can_hide_button(qt_app):
    from PySide6.QtWidgets import QPushButton, QWidget

    from app.ui.base import StateStackedWidget

    stack = StateStackedWidget()
    stack.addWidget(QWidget())
    calls = []
    stack.set_state(stack.STATE_ERROR, "First error", retry_callback=lambda: calls.append(1))
    error_widget = stack.currentWidget()
    btn = error_widget.findChild(QPushButton, "StateRetry")
    assert btn is not None
    assert not btn.isHidden()
    btn.click()
    assert calls == [1]

    stack.set_state(stack.STATE_ERROR, "Second error", retry_callback=lambda: calls.append(2))
    assert stack.currentWidget() is error_widget
    assert _message(error_widget) == "Second error"
    btn.click()
    assert calls == [1, 2]

    stack.set_state(stack.STATE_ERROR, "No retry", retry_callback=None)
    assert btn.isHidden()
    assert _message(error_widget) == "No retry"
    stack.close()
