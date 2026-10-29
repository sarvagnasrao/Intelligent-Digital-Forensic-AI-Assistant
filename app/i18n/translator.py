"""Language support for the IDFA interface.

The interface is written in English. Each language is a JSON file holding
English -> translated pairs, so adding a language is a data change rather than a
code change. Nothing here depends on Qt's ``.ts``/``lrelease`` toolchain: the
catalogues ship as plain JSON next to this module, which keeps the offline
install to a copy of the files.

Two things translate text:

``tr(text)``
    Called from code that has just built a string.

:func:`retranslate_widgets`
    Walks an already-built widget tree and rewrites every text it recognises.
    Switching language at runtime therefore does not rebuild (and lose the state
    of) the interface; it rewrites the labels in place. Text that is set later,
    such as a result count or a status message, goes through :func:`tr` at the
    point where it is built.

A string the catalogue does not contain is left exactly as it was, so partial
coverage degrades to English rather than to blank labels.
"""
from __future__ import annotations

import json
import logging
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path

from PySide6.QtWidgets import (
    QAbstractButton,
    QComboBox,
    QGroupBox,
    QLabel,
    QLineEdit,
    QMenu,
    QSpinBox,
    QStatusBar,
    QTableWidget,
    QTabWidget,
    QWidget,
)

logger = logging.getLogger(__name__)

LOCALES_DIR = Path(__file__).parent / "locales"

# Display name -> file stem. The display name is what Settings stores, so these
# strings appear in config.yaml and should not be renamed casually.
LANGUAGES: dict[str, str] = {
    "English": "en",
    "Spanish": "es",
    "French": "fr",
    "German": "de",
}

DEFAULT_LANGUAGE = "English"


def _load_catalog(language: str) -> dict[str, str]:
    return dict(_catalog_for(language))


@lru_cache(maxsize=None)
def _catalog_for(language: str) -> dict[str, str]:
    """Read one catalogue once and keep it in memory."""
    code = LANGUAGES.get(language)
    if code is None or code == "en":
        return {}
    path = LOCALES_DIR / f"{code}.json"
    if not path.exists():
        logger.warning("No translation catalogue for %s at %s", language, path)
        return {}
    try:
        # utf-8-sig: Notepad writes a BOM when a translator edits a catalogue,
        # and json.loads rejects it.
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        logger.warning("Could not read %s", path, exc_info=True)
        return {}
    if not isinstance(data, dict):
        logger.warning("%s is not an object of string pairs", path)
        return {}
    return {str(key): str(value) for key, value in data.items()}


@lru_cache(maxsize=1)
def _reverse_index() -> dict[str, str]:
    """Translated text -> English source, across every catalogue.

    Built from all languages rather than only the active one, so retranslating
    works no matter which language the widgets are currently showing.
    """
    index: dict[str, str] = {}
    for language in LANGUAGES:
        for english, translated in _catalog_for(language).items():
            existing = index.setdefault(translated, english)
            if existing != english:
                logger.debug(
                    "Ambiguous translation %r: %r vs %r", translated, existing, english
                )
    return index


class LanguageManager:
    """Owns the active language, its catalogue and the reverse lookup."""

    _instance: LanguageManager | None = None

    def __new__(cls) -> LanguageManager:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        if getattr(self, "_initialized", False):
            return
        self._initialized = True
        self._language = DEFAULT_LANGUAGE
        self._catalog: dict[str, str] = {}

        self._listeners: list[Callable[[str], None]] = []

    # ------------------------------------------------------------------ state
    @property
    def language(self) -> str:
        return self._language

    @property
    def catalog(self) -> dict[str, str]:
        return dict(self._catalog)

    def available(self) -> list[str]:
        return list(LANGUAGES)

    def on_change(self, listener: Callable[[str], None]) -> None:
        if listener not in self._listeners:
            self._listeners.append(listener)

    # -------------------------------------------------------------- translate
    def translate(self, text: str) -> str:
        """Translate an English string into the active language."""
        if not text:
            return text
        return self._catalog.get(text, text)

    def to_english(self, text: str) -> str:
        """Recover the English source of a string on screen, if known."""
        if not text:
            return text
        return _reverse_index().get(text, text)

    # ----------------------------------------------------------------- switch
    def set_language(self, language: str, *, retranslate: bool = True) -> str:
        """Activate a language and rewrite the interface to match.

        Returns the language that ended up active; an unknown name falls back to
        English rather than raising, because the value comes from a config file
        a person can edit.
        """
        language = (language or DEFAULT_LANGUAGE).strip()
        if language not in LANGUAGES:
            language = DEFAULT_LANGUAGE

        self._language = language
        self._catalog = dict(_catalog_for(language))

        if retranslate:
            from PySide6.QtWidgets import QApplication

            app = QApplication.instance()
            if app is not None:
                for widget in app.topLevelWidgets():
                    retranslate_widgets(widget)

        for listener in list(self._listeners):
            try:
                listener(language)
            except Exception:
                logger.warning("Language listener failed", exc_info=True)
        return language


def tr(text: str) -> str:
    """Translate ``text`` for the active language."""
    return LanguageManager().translate(text)


def current_language() -> str:
    return LanguageManager().language


def available_languages() -> list[str]:
    return LanguageManager().available()


# ---------------------------------------------------------------------------
# Widget-tree retranslation
# ---------------------------------------------------------------------------

def _swap(text: str, manager: LanguageManager) -> str:
    """English source of ``text`` rendered in the new language."""
    if not text:
        return text
    english = manager.to_english(text)
    return manager.translate(english)


def retranslate_widgets(root: QWidget) -> None:
    """Rewrite every translatable text under ``root``.

    Only exact catalogue matches change, and only inside widgets whose text is
    chrome: labels, buttons, group titles, tab titles, combo items, table
    headers, placeholders and menu entries. Table cells, list items and line
    edit contents are data, so they are never touched.
    """
    manager = LanguageManager()
    widgets = [root, *root.findChildren(QWidget)]

    for widget in widgets:
        if isinstance(widget, QLabel):
            widget.setText(_swap(widget.text(), manager))
        elif isinstance(widget, QAbstractButton):
            text = widget.text()
            swapped = _swap(text, manager)
            if swapped != text:
                widget.setText(swapped)
        elif isinstance(widget, QGroupBox):
            widget.setTitle(_swap(widget.title(), manager))
        elif isinstance(widget, QTabWidget):
            for index in range(widget.count()):
                widget.setTabText(index, _swap(widget.tabText(index), manager))
        elif isinstance(widget, QComboBox):
            for index in range(widget.count()):
                item = widget.itemText(index)
                swapped = _swap(item, manager)
                if swapped != item:
                    widget.setItemText(index, swapped)
        elif isinstance(widget, QTableWidget):
            for column in range(widget.columnCount()):
                item = widget.horizontalHeaderItem(column)
                if item is not None:
                    item.setText(_swap(item.text(), manager))
            for row in range(widget.rowCount()):
                item = widget.verticalHeaderItem(row)
                if item is not None:
                    item.setText(_swap(item.text(), manager))
        elif isinstance(widget, QSpinBox):
            widget.setSuffix(_swap(widget.suffix(), manager))
            widget.setPrefix(_swap(widget.prefix(), manager))
        elif isinstance(widget, (QLineEdit,)):
            placeholder = widget.placeholderText()
            swapped = _swap(placeholder, manager)
            if swapped != placeholder:
                widget.setPlaceholderText(swapped)
        elif isinstance(widget, QStatusBar):
            message = widget.currentMessage()
            if message:
                widget.showMessage(_swap(message, manager))

        title = widget.windowTitle()
        if title and widget.isWindow():
            swapped = _swap(title, manager)
            if swapped != title:
                widget.setWindowTitle(swapped)

        # Pages that build text from more than one piece (a path, a size, a
        # count) cannot be fixed up text-for-text. They expose retranslate().
        hook = getattr(widget, "retranslate", None)
        if callable(hook) and widget is not root:
            try:
                hook()
            except Exception:
                logger.warning(
                    "retranslate() failed on %s", type(widget).__name__, exc_info=True
                )

    for menu in root.findChildren(QMenu):
        for action in menu.actions():
            swapped = _swap(action.text(), manager)
            if swapped != action.text():
                action.setText(swapped)


def install(language: str) -> str:
    """Apply a language at startup, before any window is built."""
    return LanguageManager().set_language(language, retranslate=False)
