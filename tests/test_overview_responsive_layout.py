"""The overview remains usable without running the worker or a model."""
from __future__ import annotations


def test_overview_narrow_layout_and_workflow_navigation(qt_app):
    from app.ui.pages.overview_page import OverviewPage

    page = OverviewPage()
    page.resize(450, 700)
    page.show()
    page.update_workflow({"evidence": {
        "status": "needs_attention", "value": "1/3",
        "detail": "Verify all evidence before proceeding with the examination.",
    }})
    page.update_recommendation({
        "key": "evidence", "title": "Resolve evidence integrity issues",
        "detail": "Review the integrity results before continuing.",
    })
    qt_app.processEvents()

    assert page.cards_layout.getItemPosition(page.cards_layout.indexOf(page.stat_cards["indexed"]))[:2] == (3, 0)
    assert page.workflow_grid.getItemPosition(page.workflow_grid.indexOf(page.workflow_cards["analysis"]))[:2] == (3, 0)
    card = page.workflow_cards["evidence"]
    assert card.title_label.wordWrap() and card.detail_label.wordWrap()
    assert page.recommendation_title.wordWrap()
    assert page.scroll_area.horizontalScrollBar().maximum() == 0
    routes = []
    page.next_action_requested.connect(routes.append)
    card.open_button.click()
    page.recommendation_button.click()
    assert routes == ["evidence", "evidence"]
    page.close()
    page.deleteLater()
