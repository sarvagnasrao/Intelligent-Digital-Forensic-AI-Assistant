"""Compact sidebar keeps navigation discoverable and functional."""
from __future__ import annotations

from PySide6.QtWidgets import QVBoxLayout

from app.ui.base import BrandingHeader, NavList, SidebarWidget


def test_sidebar_can_switch_between_full_and_icon_only_modes(qt_app):
    sidebar = SidebarWidget()
    branding = BrandingHeader()
    nav = NavList([])
    nav.set_entries([("Overview", "📊"), ("Evidence", "📁")])

    sidebar.collapsed = True
    branding.set_collapsed(True)
    nav.set_collapsed(True)

    assert sidebar.width() == 68
    assert nav._collapsed is True
    assert branding.brand.isHidden()
    assert branding.subtitle.isHidden()
    assert not branding.toggle_button.icon().isNull()
    assert branding.toggle_button.accessibleName() == "Expand navigation"
    assert branding.logo.isHidden()
    assert nav.model.item(0).toolTip() == "Overview"

    sidebar.collapsed = False
    branding.set_collapsed(False)
    nav.set_collapsed(False)

    assert sidebar.minimumWidth() == 240
    assert not branding.brand.isHidden()
    assert branding.toggle_button.accessibleName() == "Collapse navigation"

    sidebar.deleteLater()
    branding.deleteLater()
    nav.deleteLater()


def test_navigation_icons_are_consistent_vectors():
    from app.ui.base import NavItemDelegate
    from app.ui.icons import PATHS

    assert set(NavItemDelegate.ICONS.values()) <= set(PATHS)


def test_compact_branding_keeps_toggle_inside_sidebar(qt_app):
    sidebar = SidebarWidget()
    layout = QVBoxLayout(sidebar)
    layout.setContentsMargins(0, 0, 0, 0)
    branding = BrandingHeader()
    layout.addWidget(branding)
    sidebar.collapsed = True
    branding.set_collapsed(True)
    sidebar.show()
    qt_app.processEvents()
    position = branding.toggle_button.mapTo(sidebar, branding.toggle_button.rect().topLeft())
    assert position.x() >= 0
    assert position.x() + branding.toggle_button.width() <= sidebar.width()
    sidebar.close()
    sidebar.deleteLater()


def test_every_navigation_icon_renders_valid_svg(qt_app):
    from app.ui.icons import PATHS, _renderer

    for name in PATHS:
        assert _renderer(name, "#94a3b8").isValid(), name
