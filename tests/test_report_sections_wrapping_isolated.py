"""The report section picker remains readable and selectable at narrow widths."""
from dataclasses import replace

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QScrollArea


def test_section_picker_wraps_and_preserves_selection(qt_app):
    from app.reports.templates import SECTION_LABELS, get_default_template
    from app.ui.pages.reports_page import ReportGenerateDialog, _SectionLabel
    from app.ui.theme.manager import build_qss

    template = get_default_template()
    long_key = "A very long custom section name " * 8
    custom = replace(template, template_id="custom", name="Custom", sections=["cover", long_key])
    dialog = ReportGenerateDialog([template, custom])
    dialog.setStyleSheet(build_qss(theme="dark"))
    dialog.resize(650, 800)
    dialog.show()
    qt_app.processEvents()
    scroll = dialog.findChild(QScrollArea)
    assert scroll.horizontalScrollBar().maximum() == 0
    assert list(dialog.sections) == template.sections
    assert [label.text() for label in dialog.sections_host.findChildren(_SectionLabel)] == [
        SECTION_LABELS.get(key, key) for key in template.sections
    ]
    assert not dialog.sections["cover"].isEnabled()

    dialog.template_combo.setCurrentIndex(1)
    dialog.resize(350, 800)
    qt_app.processEvents()
    assert scroll.horizontalScrollBar().maximum() == 0
    label = next(label for label in dialog.sections_host.findChildren(_SectionLabel)
                 if label.text() == long_key and label.isVisible())
    assert label.height() > label.fontMetrics().height() * 2
    QTest.mouseClick(label, Qt.MouseButton.LeftButton)
    assert dialog.get_data()["sections"] == ["cover"]
    dialog.close()
