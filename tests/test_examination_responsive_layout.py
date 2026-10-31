"""Responsive examination controls stay available without forensic services."""
from __future__ import annotations


def test_actions_reflow_and_tables_remain_scrollable(qt_app):
    from app.ui.pages.examination_page import ExaminationPage, JobTableModel
    from app.ui.theme.manager import build_qss
    from app.ui.theme.palettes import DARK

    page = ExaminationPage()
    page.setStyleSheet(build_qss(DARK, "dark"))
    page.resize(450, 550)
    page.show()
    qt_app.processEvents()

    assert not page.grab().isNull()
    assert page.width() == 450
    assert page._action_columns < len(page._action_buttons)
    assert page.scroll_area.horizontalScrollBar().maximum() == 0
    assert page.scroll_area.verticalScrollBar().maximum() > 0
    assert all(not button.isHidden() for button in page._action_buttons)
    assert page.jobs_model.columnCount() == len(JobTableModel.HEADERS)
    assert all(not page.jobs_table.isColumnHidden(i) for i in range(page.jobs_model.columnCount()))
    assert page.jobs_table.horizontalScrollBar().maximum() > 0
    positions = [page._action_layout.getItemPosition(page._action_layout.indexOf(button))[:2]
                 for button in page._action_buttons]
    assert positions == sorted(positions)
    page.resize(1600, 800)
    qt_app.processEvents()
    assert page._action_columns == len(page._action_buttons)
    assert all(not button.isHidden() for button in page._action_buttons)
    page.close()
    page.deleteLater()
