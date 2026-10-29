"""Opt-in restyling for widgets that set their own stylesheet.

Most of the interface is themed by ``professional.qss``, which the theme manager
can simply re-apply. A few chrome widgets (sidebar, header bars, stat cards)
build a per-widget stylesheet in their constructor because they need selectors
that are awkward to express globally. Those strings bake in the colours of
whichever theme was active at the time, so they have to be rebuilt when the
theme changes.

Subclass :class:`ThemedWidget` and return the stylesheet from
``theme_stylesheet()``; the manager calls :meth:`restyle` on every theme change.
"""
from __future__ import annotations

import weakref
from typing import Any

_registry: weakref.WeakSet[ThemedWidget] = weakref.WeakSet()


def refresh_themed_widgets(theme: str) -> None:
    """Rebuild the stylesheets of every live themed widget."""
    for widget in list(_registry):
        try:
            widget.restyle(theme)
        except RuntimeError:
            # The underlying C++ object is gone; WeakSet will drop it.
            continue


class ThemedWidget:
    """Mixin that rebuilds a widget's own stylesheet on theme change.

    Subclasses register themselves here and call :meth:`restyle` at the end of
    their own constructor, once the child widgets it needs exist.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        _registry.add(self)

    def theme_stylesheet(self) -> str:
        """Override: return the stylesheet this widget needs for the theme."""
        return ""

    def restyle(self, theme: str | None = None) -> None:
        """Apply ``theme_stylesheet()``. Override to style child widgets too."""
        sheet = self.theme_stylesheet()
        if sheet:
            self.setStyleSheet(sheet)
