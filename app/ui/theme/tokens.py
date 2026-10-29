"""Design tokens for IDFA UI.

``Color`` is a live view over the active palette rather than a table of
constants: widgets read ``Color.TEXT_PRIMARY`` when they build their styles, and
that lookup returns whatever the current theme says. Widgets that only apply a
stylesheet once still need :class:`app.ui.theme.mixins.ThemedWidget` to restyle
themselves when the theme changes.
"""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtGui import QColor, QFont

from app.ui.theme import palettes
from app.ui.theme.palettes import Palette

# Legacy attribute name -> palette field. Existing call sites keep working.
_COLOR_FIELDS: dict[str, str] = {
    "PRIMARY": "accent_strong",
    "PRIMARY_HOVER": "accent_hover",
    "PRIMARY_PRESSED": "accent_pressed",
    "PRIMARY_LIGHT": "accent",
    "SUCCESS": "success_solid",
    "WARNING": "warning_fg",
    "ERROR": "danger",
    "INFO": "info",
    "BG_PRIMARY": "bg_primary",
    "BG_SECONDARY": "bg_secondary",
    "BG_TERTIARY": "bg_tertiary",
    "BG_HOVER": "accent_strong",
    "BG_INPUT": "bg_input",
    "BG_DISABLED": "bg_disabled",
    "BG_CARD": "bg_card",
    "TEXT_PRIMARY": "text_primary",
    "TEXT_SECONDARY": "text_secondary",
    "TEXT_MUTED": "text_muted",
    "TEXT_INVERSE": "text_inverse",
    "TEXT_LINK": "text_link",
    "BORDER_SUBTLE": "border_subtle",
    "BORDER_LIGHT": "border_default",
    "BORDER_DEFAULT": "border_default",
    "BORDER_FOCUS": "accent",
    "BORDER_ERROR": "danger",
    "BORDER_SUCCESS": "success_solid",
    "SIDEBAR_BG": "bg_primary",
    "SIDEBAR_BORDER": "border_subtle",
    "SIDEBAR_ITEM": "text_secondary",
    "SIDEBAR_ITEM_ACTIVE": "text_primary",
    "SIDEBAR_ITEM_ACTIVE_BG": "accent_strong",
    "SIDEBAR_ACCENT": "accent",
    "STATUS_SUCCESS_BG": "success_bg",
    "STATUS_WARNING_BG": "warning_bg",
    "STATUS_ERROR_BG": "error_bg",
    "STATUS_INFO_BG": "info_bg",
}


class _ColorProxy:
    """Resolves ``Color.NAME`` against the palette that is active right now.

    Legacy names (the ones the interface already used) win; a name that is not
    in that table is matched against the palette directly, so new tokens can be
    read as ``Color.TEXT_LINK_HOVER`` without touching this file.
    """

    _palette_fields = frozenset(Palette.__dataclass_fields__)

    def __getattr__(self, name: str) -> QColor:
        field = _COLOR_FIELDS.get(name)
        if field is None:
            candidate = name.lower()
            if candidate in self._palette_fields:
                field = candidate
        if field is None:
            raise AttributeError(f"Color has no token {name!r}")
        return QColor(getattr(palettes.current_palette(), field))

    def __dir__(self) -> list[str]:
        return sorted(set(_COLOR_FIELDS) | {f.upper() for f in self._palette_fields})


Color = _ColorProxy()


@dataclass(frozen=True)
class Spacing:
    XS = 4
    SM = 8
    MD = 16
    LG = 24
    XL = 32
    XXL = 48


@dataclass(frozen=True)
class Radius:
    SM = 4
    MD = 6
    LG = 8
    XL = 12
    FULL = 9999


@dataclass(frozen=True)
class Typography:
    # QFont expects one family name; CSS fallback lists are only valid in QSS.
    FONT_FAMILY = "Segoe UI"
    DISPLAY_LG = (32, QFont.Weight.Medium, 1.2, -0.02)
    DISPLAY_MD = (24, QFont.Weight.Medium, 1.3, -0.01)
    HEADING_LG = (20, QFont.Weight.DemiBold, 1.3, 0)
    HEADING_MD = (16, QFont.Weight.DemiBold, 1.4, 0)
    HEADING_SM = (14, QFont.Weight.DemiBold, 1.4, 0.01)
    BODY_LG = (16, QFont.Weight.Normal, 1.5, 0)
    BODY_MD = (13, QFont.Weight.Normal, 1.5, 0)
    BODY_SM = (12, QFont.Weight.Normal, 1.4, 0)
    LABEL = (11, QFont.Weight.DemiBold, 1.4, 0.05)
    MONO_SM = (11, QFont.Weight.Normal, 1.4, 0)
    MONO_MD = (12, QFont.Weight.Normal, 1.4, 0)


@dataclass(frozen=True)
class Elevation:
    LEVEL_0 = "none"
    LEVEL_1 = "0 1px 2px rgba(0,0,0,0.3)"
    LEVEL_2 = "0 4px 6px -1px rgba(0,0,0,0.4), 0 2px 4px -2px rgba(0,0,0,0.3)"
    LEVEL_3 = "0 10px 15px -3px rgba(0,0,0,0.4), 0 4px 6px -4px rgba(0,0,0,0.3)"
    LEVEL_4 = "0 20px 25px -5px rgba(0,0,0,0.4), 0 8px 10px -6px rgba(0,0,0,0.3)"


@dataclass(frozen=True)
class Motion:
    FAST = 100
    NORMAL = 200
    SLOW = 300
    EASING = "cubic-bezier(0.4, 0, 0.2, 1)"
