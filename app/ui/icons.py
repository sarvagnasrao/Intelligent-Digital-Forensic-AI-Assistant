"""Small, consistent outline icons for application navigation."""
from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

# Coordinates share a 24px canvas, rounded strokes and no colour font dependency.
PATHS = {
    "folder": '<path d="M3 7V5h6l2 2h10v12H3Z"/>',
    "audit": '<rect x="5" y="4" width="14" height="17" rx="2"/>'
             '<path d="M9 4V2h6v2M9 9h6M9 13h6M9 17h4"/>',
    "tools": '<path d="m14 6 4 4M14 3a6 6 0 0 0-7 8L3 18a2 2 0 0 0 3 3l7-7'
             'a6 6 0 0 0 8-7l-5 5-4-4 5-5Z"/>',
    "users": '<circle cx="9" cy="8" r="3"/><path d="M3 21v-3a6 6 0 0 1 12 0v3'
             'M16 5a3 3 0 0 1 0 6M18 15a5 5 0 0 1 3 5"/>',
    "settings": '<circle cx="12" cy="12" r="3"/><circle cx="12" cy="12" r="8"/>'
                '<path d="M12 2v2M12 20v2M2 12h2M20 12h2M5 5l2 2M17 17l2 2'
                'M5 19l2-2M17 7l2-2"/>',
    "overview": '<rect x="3" y="3" width="7" height="7" rx="1"/>'
                '<rect x="14" y="3" width="7" height="7" rx="1"/>'
                '<rect x="3" y="14" width="7" height="7" rx="1"/>'
                '<rect x="14" y="14" width="7" height="7" rx="1"/>',
    "examine": '<path d="m8 3 7 3-4 10-7-3ZM4 13l-1 3 7 3 1-3M14 11'
               'a6 6 0 0 1 2 10M4 21h16"/>',
    "search": '<circle cx="10" cy="10" r="6"/><path d="m15 15 6 6"/>',
    "ai": '<path d="m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12'
          'l6.5-2.5ZM20 2v4M18 4h4"/>',
    "entities": '<circle cx="12" cy="5" r="3"/><circle cx="5" cy="19" r="3"/>'
                '<circle cx="19" cy="19" r="3"/><path d="m10.5 8-4 8M13.5 8'
                'l4 8M8 19h8"/>',
    "report": '<path d="M14 3H5v18h14V8ZM14 3v5h5M8 12h8M8 16h8"/>',
    "link": '<path d="m9 15 6-6M8 17l-1 1a4 4 0 0 1-6-6l5-5a4 4 0 0 1 6 0'
            'M16 7l1-1a4 4 0 0 1 6 6l-5 5a4 4 0 0 1-6 0"/>',
    "activity": '<path d="M3 12h4l3-8 4 16 3-8h4"/>',
    "pause": '<rect x="6" y="4" width="4" height="16" rx="1"/>'
             '<rect x="14" y="4" width="4" height="16" rx="1"/>',
    "check": '<circle cx="12" cy="12" r="9"/><path d="m8 12 3 3 5-6"/>',
    "alert": '<path d="m12 3 10 18H2ZM12 9v5M12 17v.5"/>',
    "bell": '<path d="M5 16h14l-2-3V9A5 5 0 0 0 7 9v4ZM10 20h4M12 2v2"/>',
    "panel-open": '<rect x="3" y="4" width="18" height="16" rx="2"/>'
                  '<path d="M9 4v16m4-11 3 3-3 3"/>',
    "panel-close": '<rect x="3" y="4" width="18" height="16" rx="2"/>'
                   '<path d="M9 4v16m7-11-3 3 3 3"/>',
}

# Retain compatibility with callers that still provide the former glyphs.
ALIASES = dict(zip(
    ("📁", "📋", "🔧", "👥", "⚙️", "📊", "🔬", "🔍", "🤖", "🕸️", "📄", "🔗"),
    ("folder", "audit", "tools", "users", "settings", "overview", "examine",
     "search", "ai", "entities", "report", "link"),
    strict=True,
))
ALIASES.update({"🟢": "activity", "🟡": "pause", "🔴": "check", "⚠️": "alert"})


@lru_cache(maxsize=128)
def _renderer(name: str, color: str) -> QSvgRenderer:
    body = PATHS.get(ALIASES.get(name, name), PATHS["overview"])
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
           f'fill="none" stroke="{color}" stroke-width="1.7" '
           f'stroke-linecap="round" stroke-linejoin="round">{body}</svg>')
    return QSvgRenderer(QByteArray(svg.encode("utf-8")))


def draw_icon(painter, rect, name: str, color: str) -> None:
    """Paint a navigation icon at the requested size and theme colour."""
    _renderer(name, color).render(painter, QRectF(rect))


def button_icon(name: str, color: str) -> QIcon:
    """Supply the same artwork to Qt buttons, including high DPI screens."""
    pixmap = QPixmap(48, 48)
    pixmap.fill(Qt.GlobalColor.transparent)
    pixmap.setDevicePixelRatio(2)
    painter = QPainter(pixmap)
    draw_icon(painter, QRectF(0, 0, 24, 24), name, color)
    painter.end()
    return QIcon(pixmap)
