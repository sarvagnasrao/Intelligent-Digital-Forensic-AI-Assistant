"""Translation of the IDFA interface.

``translator.tr`` translates a string; ``LanguageManager`` owns the active
language. See :mod:`app.i18n.translator` for how the catalogues are stored.
"""
from __future__ import annotations

from app.i18n.translator import (
    DEFAULT_LANGUAGE,
    LANGUAGES,
    LanguageManager,
    available_languages,
    current_language,
    install,
    retranslate_widgets,
    tr,
)

__all__ = [
    "DEFAULT_LANGUAGE",
    "LANGUAGES",
    "LanguageManager",
    "available_languages",
    "current_language",
    "install",
    "retranslate_widgets",
    "tr",
]
