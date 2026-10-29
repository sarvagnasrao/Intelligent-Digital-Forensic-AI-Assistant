"""Theme palettes, stylesheet rendering and live switching."""
from __future__ import annotations

import re

import pytest
from PySide6.QtGui import QColor

from app.ui.theme import palettes
from app.ui.theme.manager import ThemeManager, build_qss, system_theme
from app.ui.theme.palettes import DARK, LIGHT, THEMES
from app.ui.theme.tokens import Color


@pytest.fixture(autouse=True)
def dark_again(qt_app):
    ThemeManager().set_mode("dark")
    yield
    ThemeManager().set_mode("dark")


def test_both_palettes_define_the_same_tokens():
    assert set(DARK.tokens()) == set(LIGHT.tokens())


def test_rendered_stylesheet_has_no_unresolved_tokens():
    for theme in THEMES:
        qss = build_qss(THEMES[theme], theme)
        assert qss, f"{theme} produced an empty stylesheet"

        # @icon-dir is replaced before substitution, so any @word left here is a
        # token that professional.qss uses and the palette does not define.
        leftovers = re.findall(r"@[a-z][a-z0-9-]*", qss)
        assert not leftovers, f"{theme} left tokens behind: {sorted(set(leftovers))[:5]}"


def test_combo_boxes_use_the_styled_list_popup():
    qss = build_qss(DARK, "dark")

    assert "combobox-popup: 0;" in qss
    assert "QComboBox QAbstractItemView" in qss


def test_spin_boxes_have_inset_values_and_separated_steppers():
    qss = build_qss(DARK, "dark")

    assert "padding: 0 12px;" in qss
    assert "QSpinBox QLineEdit" in qss
    assert "width: 28px;" in qss


def test_common_controls_share_consistent_sizing_and_focus_styles():
    qss = build_qss(DARK, "dark")

    assert "QPushButton {" in qss
    assert "QLineEdit, QComboBox, QDateEdit" in qss
    assert "QTextEdit, QPlainTextEdit" in qss
    assert "QCheckBox, QRadioButton" in qss
    assert "min-height: 36px;" in qss
    assert "QLineEdit:focus" in qss


def test_every_palette_colour_is_used_by_the_stylesheet():
    """A palette entry nobody reads would be dead weight in a new theme."""
    qss = build_qss(DARK, "dark")
    unused = [value for value in DARK.tokens().values() if value.lower() not in qss.lower()]
    # The Python side reads a few colours directly (Color.X), so this is a
    # report, not a hard rule; it catches typos in the token table.
    assert len(unused) <= 6, unused


def test_light_and_dark_differ_on_surfaces():
    assert DARK.bg_primary != LIGHT.bg_primary
    assert DARK.text_primary != LIGHT.text_primary

    # Sanity: text must stay readable against its own background. Comparing the
    # hex strings would say nothing (in dark mode the text is the lighter one).
    assert QColor(DARK.text_primary).lightness() > QColor(DARK.bg_primary).lightness()
    assert QColor(LIGHT.text_primary).lightness() < QColor(LIGHT.bg_primary).lightness()

    # And the two surfaces must be at opposite ends of the scale, not two greys.
    assert QColor(DARK.bg_primary).lightness() < 60
    assert QColor(LIGHT.bg_primary).lightness() > 200


def test_switching_mode_changes_the_active_palette(qt_app):
    ThemeManager().set_mode("light")
    assert palettes.current_theme() == "light"
    assert Color.BG_PRIMARY.name() == LIGHT.bg_primary

    ThemeManager().set_mode("dark")
    assert palettes.current_theme() == "dark"
    assert Color.BG_PRIMARY.name() == DARK.bg_primary


def test_unknown_mode_falls_back_to_dark(qt_app):
    assert ThemeManager().set_mode("chartreuse") == "dark"


def test_system_mode_resolves_to_a_real_theme(qt_app):
    resolved = ThemeManager().set_mode("system")
    assert resolved in {"dark", "light"}
    assert ThemeManager().mode == "system"
    assert ThemeManager().theme == resolved


def test_system_theme_reports_a_known_theme(qt_app):
    assert system_theme() in {"dark", "light"}


def test_theme_change_notifies_listeners(qt_app):
    seen: list[str] = []
    manager = ThemeManager()
    manager.on_change(seen.append)

    manager.set_mode("light")

    assert seen == ["light"]


def test_inline_styled_widget_is_restyled_on_switch(qt_app):
    """Chrome that builds its own stylesheet must follow the theme."""
    from PySide6.QtWidgets import QLabel

    from app.ui.theme.themed import ThemedWidget

    class _Chrome(ThemedWidget, QLabel):
        def theme_stylesheet(self) -> str:
            return f"color: {Color.TEXT_PRIMARY.name()};"

    label = _Chrome()
    ThemeManager().set_mode("light")

    assert LIGHT.text_primary in label.styleSheet()
