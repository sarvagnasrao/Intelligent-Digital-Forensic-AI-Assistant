"""Language selection, catalogs and live retranslation."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.i18n.translator import (
    LANGUAGES,
    LanguageManager,
    _load_catalog,
    tr,
)


@pytest.fixture(autouse=True)
def english_again():
    """Every test starts and ends in English, whatever it does in between."""
    manager = LanguageManager()
    manager.set_language("English", retranslate=False)
    yield
    manager.set_language("English", retranslate=False)


def test_every_language_has_a_catalog_with_the_same_keys():
    catalogs = {
        name: _load_catalog(name) for name in LANGUAGES if name != "English"
    }
    assert set(catalogs) == {"Spanish", "French", "German"}

    sizes = {name: len(catalog) for name, catalog in catalogs.items()}
    assert len(set(sizes.values())) == 1, f"catalogs differ in size: {sizes}"

    reference = set(next(iter(catalogs.values())))
    for name, catalog in catalogs.items():
        missing = reference - set(catalog)
        extra = set(catalog) - reference
        assert not missing, f"{name} is missing {sorted(missing)}"
        assert not extra, f"{name} has stray keys {sorted(extra)}"


def test_catalog_files_are_valid_utf8_json():
    """Notepad may add a BOM; the loader must still read the file."""
    folder = Path(__file__).resolve().parents[1] / "app" / "i18n" / "locales"
    for code in ("es", "fr", "de"):
        path = folder / f"{code}.json"
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        assert isinstance(payload, dict) and payload
        assert all(isinstance(v, str) and v for v in payload.values())


def test_unknown_language_falls_back_to_english():
    manager = LanguageManager()
    assert manager.set_language("Klingon", retranslate=False) == "English"
    assert manager.catalog == {}
    assert tr("Settings") == "Settings"


def test_translation_and_reverse_lookup_round_trip():
    manager = LanguageManager()
    manager.set_language("Spanish", retranslate=False)

    assert tr("Settings") == "Configuración"
    assert manager.to_english("Configuración") == "Settings"

    manager.set_language("German", retranslate=False)
    # The reverse table follows the newly active language.
    assert tr("Settings") == "Einstellungen"
    assert manager.to_english("Einstellungen") == "Settings"


def test_untranslated_string_passes_through_unchanged():
    LanguageManager().set_language("French", retranslate=False)
    assert tr("A sentence nobody translated") == "A sentence nobody translated"


def test_retranslate_widgets_switches_labels_buttons_and_placeholders(qt_app):
    from PySide6.QtWidgets import QCheckBox, QLabel, QLineEdit, QSpinBox, QWidget

    from app.i18n import retranslate_widgets

    root = QWidget()
    label = QLabel("Settings", root)
    checkbox = QCheckBox("Enable automatic updates", root)
    placeholder = QLineEdit(root)
    placeholder.setPlaceholderText("Enter your username")
    interval = QSpinBox(root)
    interval.setSuffix(" seconds")
    untouched = QLabel("CASE-0001", root)

    LanguageManager().set_language("Spanish", retranslate=False)
    retranslate_widgets(root)

    assert label.text() == "Configuración"
    assert checkbox.text() == "Activar actualizaciones automáticas"
    assert placeholder.placeholderText() == "Introduzca su usuario"
    assert interval.suffix() == " segundos"
    # Data is never rewritten, only chrome.
    assert untouched.text() == "CASE-0001"


def test_switching_back_restores_english(qt_app):
    from PySide6.QtWidgets import QLabel, QWidget

    from app.i18n import retranslate_widgets

    root = QWidget()
    label = QLabel("Settings", root)
    manager = LanguageManager()

    manager.set_language("French", retranslate=False)
    retranslate_widgets(root)
    assert label.text() == "Paramètres"

    manager.set_language("English", retranslate=False)
    retranslate_widgets(root)
    assert label.text() == "Settings"


def test_settings_page_persists_the_selected_language(config_home, qt_app):
    """The combo saves a stable identifier, not the translated label."""
    from app.config import get_config, save_config
    from app.ui.pages.settings_page import SettingsPage

    page = SettingsPage()
    index = page.language_combo.findData("German")
    assert index >= 0
    page.language_combo.setCurrentIndex(index)

    config = get_config()
    config.ui.language = page.language_combo.currentData()
    save_config(config)

    assert get_config().ui.language == "German"


def test_theme_combo_stores_a_theme_name_not_a_label(config_home, qt_app):
    from app.ui.pages.settings_page import SettingsPage

    page = SettingsPage()
    LanguageManager().set_language("Spanish", retranslate=False)

    # Labels may be translated; the stored value must not move.
    assert page.theme_combo.itemText(0) in {"Light", "Claro"}
    assert page.theme_combo.itemData(0) == "light"
    assert page.theme_combo.itemData(1) == "dark"
    assert page.theme_combo.itemData(2) == "system"
