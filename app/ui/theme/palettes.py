"""Semantic colour palettes for the IDFA interface.

One stylesheet (``professional.qss``) is shared by every theme. It refers to
colours by token (``@bg-primary``, ``@text-muted``, ...) and this module supplies
the value each token takes in a given theme. Adding a theme therefore means
adding a ``Palette`` here rather than forking 850 lines of QSS.

Token names map to field names by replacing ``-`` with ``_``, so ``@bg-primary``
resolves to ``Palette.bg_primary``.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Palette:
    """Every colour the interface uses, named for its role rather than its hue."""

    # --- surfaces ---------------------------------------------------------
    bg_primary: str  # application background, sidebar
    bg_secondary: str  # header bars, menus, status bar
    bg_tertiary: str  # hover states, progress tracks, separators
    bg_card: str  # cards, table headers
    bg_input: str  # text fields, combo boxes
    bg_disabled: str  # disabled controls
    bg_elevated: str  # raised hints

    # --- text -------------------------------------------------------------
    text_primary: str
    text_secondary: str
    text_muted: str
    text_strong: str
    text_value: str
    text_hint: str
    text_disabled: str
    text_link: str
    text_link_hover: str
    text_inverse: str
    on_accent: str

    # --- borders ----------------------------------------------------------
    border_subtle: str
    border_default: str
    border_strong: str
    scrollbar: str

    # --- accent -----------------------------------------------------------
    accent: str  # focus rings, active indicators, progress
    accent_strong: str  # selected rows, badges, chat bubbles
    accent_check: str  # checked checkbox/radio fill (must suit a white mark)
    accent_hover: str
    accent_pressed: str
    calendar_selection: str
    button_bg: str
    button_text: str

    # --- status -----------------------------------------------------------
    danger: str
    danger_hover: str
    danger_pressed: str
    success_solid: str
    success_solid_hover: str
    success_text: str

    success_bg: str
    success_fg: str
    error_bg: str
    error_fg: str
    warning_bg: str
    warning_fg: str
    info_bg: str
    info: str

    # --- AI service banner ------------------------------------------------
    ai_bg: str
    ai_border: str
    ai_ok_bg: str
    ai_ok_border: str
    ai_ok_fg: str
    ai_error_bg: str
    ai_error_border: str
    ai_error_fg: str
    ai_partial_bg: str
    ai_partial_border: str
    ai_partial_fg: str

    def tokens(self) -> dict[str, str]:
        """Token name (as written in QSS) to colour value."""
        return {key.replace("_", "-"): value for key, value in asdict(self).items()}


DARK = Palette(
    bg_primary="#0b1220",
    bg_secondary="#111827",
    bg_tertiary="#1e293b",
    bg_card="#152036",
    bg_input="#0f172a",
    bg_disabled="#0a1120",
    bg_elevated="#334155",
    text_primary="#f1f5f9",
    text_secondary="#94a3b8",
    text_muted="#8291a8",
    text_strong="#e2e8f0",
    text_value="#cbd5e1",
    text_hint="#8b9cb6",
    text_disabled="#475569",
    text_link="#60a5fa",
    text_link_hover="#93c5fd",
    text_inverse="#0b1220",
    on_accent="#ffffff",
    border_subtle="#1e293b",
    border_default="#2d3d59",
    border_strong="#334155",
    scrollbar="#2d3d59",
    accent="#3b82f6",
    accent_strong="#1e3a5f",
    accent_check="#1e3a5f",
    accent_hover="#255a9c",
    accent_pressed="#1a3d6e",
    calendar_selection="#1d4ed8",
    button_bg="#1e3a5f",
    button_text="#f1f5f9",
    danger="#dc2626",
    danger_hover="#ef4444",
    danger_pressed="#b91c1c",
    success_solid="#0d9488",
    success_solid_hover="#0f766e",
    success_text="#14b8a6",
    success_bg="#064e3b",
    success_fg="#34d399",
    error_bg="#7f1d1d",
    error_fg="#f87171",
    warning_bg="#78350f",
    warning_fg="#fbbf24",
    info_bg="#164e63",
    info="#0891b2",
    ai_bg="#26354d",
    ai_border="#26354d",
    ai_ok_bg="#10251f",
    ai_ok_border="#176b58",
    ai_ok_fg="#34d399",
    ai_error_bg="#29151d",
    ai_error_border="#713343",
    ai_error_fg="#fb7185",
    ai_partial_bg="#251f12",
    ai_partial_border="#70551c",
    ai_partial_fg="#fbbf24",
)

LIGHT = Palette(
    bg_primary="#eef2f7",
    bg_secondary="#ffffff",
    bg_tertiary="#e2e8f0",
    bg_card="#ffffff",
    bg_input="#ffffff",
    bg_disabled="#f1f5f9",
    bg_elevated="#f1f5f9",
    text_primary="#0f172a",
    text_secondary="#475569",
    text_muted="#64748b",
    text_strong="#1e293b",
    text_value="#334155",
    text_hint="#475569",
    text_disabled="#94a3b8",
    text_link="#1d4ed8",
    text_link_hover="#1e40af",
    text_inverse="#ffffff",
    on_accent="#ffffff",
    border_subtle="#e2e8f0",
    border_default="#cbd5e1",
    border_strong="#cbd5e1",
    scrollbar="#cbd5e1",
    accent="#2563eb",
    accent_strong="#dbeafe",
    accent_check="#2563eb",
    accent_hover="#1d4ed8",
    accent_pressed="#1e40af",
    calendar_selection="#1d4ed8",
    button_bg="#2563eb",
    button_text="#ffffff",
    danger="#dc2626",
    danger_hover="#b91c1c",
    danger_pressed="#991b1b",
    success_solid="#0f766e",
    success_solid_hover="#115e59",
    success_text="#0f766e",
    success_bg="#d1fae5",
    success_fg="#047857",
    error_bg="#fee2e2",
    error_fg="#b91c1c",
    warning_bg="#fef3c7",
    warning_fg="#b45309",
    info_bg="#dbeafe",
    info="#0369a1",
    ai_bg="#f1f5f9",
    ai_border="#d8e0ea",
    ai_ok_bg="#ecfdf5",
    ai_ok_border="#6ee7b7",
    ai_ok_fg="#047857",
    ai_error_bg="#fef2f2",
    ai_error_border="#fca5a5",
    ai_error_fg="#b91c1c",
    ai_partial_bg="#fffbeb",
    ai_partial_border="#fcd34d",
    ai_partial_fg="#b45309",
)

THEMES: dict[str, Palette] = {"dark": DARK, "light": LIGHT}

# The theme currently rendered. Stored here rather than in ThemeManager so that
# tokens.py can resolve ``Color.X`` without importing the widget layer.
_current: str = "dark"


def current_theme() -> str:
    return _current


def set_current_theme(name: str) -> str:
    """Point the process at a theme, falling back to dark for unknown names."""
    global _current
    _current = name if name in THEMES else "dark"
    return _current


def current_palette() -> Palette:
    return THEMES[_current]
