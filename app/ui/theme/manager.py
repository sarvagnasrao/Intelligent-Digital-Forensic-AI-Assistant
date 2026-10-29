"""Theme manager for IDFA UI.

A theme is two things: a palette (see :mod:`app.ui.theme.palettes`) and the
shared stylesheet, which refers to palette entries as ``@token``. Swapping
themes rewrites the stylesheet from the new palette and re-applies it, so
nothing has to be duplicated per theme.

``dark_mode``/``set_mode`` accept ``"dark"``, ``"light"`` or ``"system"``.
``"system"`` follows the Windows app appearance and keeps following it.
"""
from __future__ import annotations

import contextlib
import logging
import re
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPalette
from PySide6.QtWidgets import QApplication, QStyleFactory, QWidget

from app.ui.theme import palettes
from app.ui.theme.palettes import Palette
from app.ui.theme.tokens import Typography

logger = logging.getLogger(__name__)

MODES = ("dark", "light", "system")

_TOKEN = re.compile(r"@([a-z][a-z0-9-]*)")


def theme_dir() -> Path:
    return Path(__file__).parent


def build_qss(palette: Palette | None = None, theme: str | None = None) -> str:
    """Render the stylesheet for a palette.

    ``@icon-dir`` points at the per-theme image folder because a chevron drawn
    for a near-black background is unreadable on white.
    """
    palette = palette or palettes.current_palette()
    theme = theme or palettes.current_theme()

    qss_path = theme_dir() / "professional.qss"
    if not qss_path.exists():
        return ""
    qss = qss_path.read_text(encoding="utf-8")

    qss = qss.replace("@icon-dir", (theme_dir() / "icons" / theme).as_posix())

    tokens = palette.tokens()

    def substitute(match: re.Match) -> str:
        name = match.group(1)
        value = tokens.get(name)
        if value is None:
            # A typo in the stylesheet should be visible, not silently ignored.
            logger.warning("Unknown theme token %r in professional.qss", name)
            return match.group(0)
        return value

    return _TOKEN.sub(substitute, qss)


def system_theme() -> str:
    """The appearance Windows is currently using."""
    hints = QGuiApplication.styleHints()
    scheme = getattr(hints, "colorScheme", lambda: None)()
    if scheme == Qt.ColorScheme.Light:
        return "light"
    if scheme == Qt.ColorScheme.Dark:
        return "dark"
    return "dark"  # unknown/unsupported: the forensic default


class ThemeManager:
    """Owns the active theme and re-applies it when it changes."""

    _instance: ThemeManager | None = None

    def __new__(cls) -> ThemeManager:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if getattr(self, "_initialized", False):
            return
        self._initialized = True
        self._mode = "dark"
        self._listeners: list[Callable[[str], None]] = []
        self._following_system = False

    # ----------------------------------------------------------- properties
    @property
    def mode(self) -> str:
        """The configured preference: ``dark``, ``light`` or ``system``."""
        return self._mode

    @property
    def theme(self) -> str:
        """The theme actually rendered, with ``system`` resolved."""
        return palettes.current_theme()

    @property
    def palette(self) -> Palette:
        return palettes.current_palette()

    @property
    def dark_mode(self) -> bool:
        return self.theme == "dark"

    # -------------------------------------------------------------- control
    def on_change(self, listener: Callable[[str], None]) -> None:
        """Register a callback invoked with the new theme name."""
        if listener not in self._listeners:
            self._listeners.append(listener)

    def set_mode(self, mode: str, *, apply_now: bool = True) -> str:
        """Switch theme. Returns the resolved theme (``dark`` or ``light``)."""
        mode = (mode or "dark").strip().lower()
        if mode not in MODES:
            mode = "dark"
        self._mode = mode
        self._follow_system(mode == "system")
        resolved = system_theme() if mode == "system" else mode
        palettes.set_current_theme(resolved)
        if apply_now:
            self.apply()
        return resolved

    def _follow_system(self, enabled: bool) -> None:
        hints = QGuiApplication.styleHints()
        signal = getattr(hints, "colorSchemeChanged", None)
        if signal is None:  # Qt < 6.5 has no colour-scheme API
            return
        if enabled and not self._following_system:
            signal.connect(self._on_system_scheme_changed)
            self._following_system = True
        elif not enabled and self._following_system:
            with contextlib.suppress(RuntimeError, TypeError):
                signal.disconnect(self._on_system_scheme_changed)
            self._following_system = False

    def _on_system_scheme_changed(self, _scheme) -> None:
        if self._mode != "system":
            return
        resolved = system_theme()
        if resolved == palettes.current_theme():
            return
        palettes.set_current_theme(resolved)
        self.apply()

    # -------------------------------------------------------------- apply
    def apply(self, target: QWidget | QApplication | None = None) -> None:
        """Apply the active theme to the application.

        The stylesheet goes on the QApplication rather than on a window: a
        window-level sheet wins over the application-level one for its whole
        subtree, which would pin the interface to the theme it started with.
        """
        app = QApplication.instance()
        palette = palettes.current_palette()
        if app is None:
            return

        app.setStyle(QStyleFactory.create("Fusion"))
        app.setPalette(self._build_qpalette(palette))
        app.setFont(self._build_font())
        app.setStyleSheet(build_qss(palette, palettes.current_theme()))

        self._repolish(app)
        self._notify()

    def _notify(self) -> None:
        theme = palettes.current_theme()
        for listener in list(self._listeners):
            try:
                listener(theme)
            except Exception:
                logger.warning("Theme listener failed", exc_info=True)

        from app.ui.theme.themed import refresh_themed_widgets

        refresh_themed_widgets(theme)

    def _repolish(self, app: QApplication | None) -> None:
        """Re-evaluate stylesheet rules for widgets that do not own a sheet."""
        if app is None:
            return
        for widget in app.allWidgets():
            if widget.styleSheet():
                continue
            style = widget.style()
            style.unpolish(widget)
            style.polish(widget)
            # Some Qt subclasses expose an ``update`` overload that requires
            # arguments (for example QListView.update(QModelIndex)). Invoke the
            # QWidget repaint method directly after repolishing instead.
            QWidget.update(widget)

    # ------------------------------------------------------------ internals
    @staticmethod
    def _build_qpalette(palette: Palette) -> QPalette:
        pal = QPalette()
        roles = {
            QPalette.ColorRole.Window: palette.bg_primary,
            QPalette.ColorRole.WindowText: palette.text_primary,
            QPalette.ColorRole.Base: palette.bg_input,
            QPalette.ColorRole.AlternateBase: palette.bg_tertiary,
            QPalette.ColorRole.ToolTipBase: palette.bg_card,
            QPalette.ColorRole.ToolTipText: palette.text_primary,
            QPalette.ColorRole.Text: palette.text_primary,
            QPalette.ColorRole.Button: palette.bg_secondary,
            QPalette.ColorRole.ButtonText: palette.text_primary,
            QPalette.ColorRole.BrightText: palette.text_inverse,
            QPalette.ColorRole.Highlight: palette.accent,
            QPalette.ColorRole.HighlightedText: palette.on_accent,
            QPalette.ColorRole.Link: palette.text_link,
            QPalette.ColorRole.PlaceholderText: palette.text_muted,
        }
        for role, value in roles.items():
            pal.setColor(role, QColor(value))
        pal.setColor(QPalette.ColorRole.LinkVisited, QColor(palette.accent_pressed))
        return pal

    @staticmethod
    def _build_font() -> QFont:
        font = QFont(Typography.FONT_FAMILY)
        font.setHintingPreference(QFont.HintingPreference.PreferFullHinting)
        return font
