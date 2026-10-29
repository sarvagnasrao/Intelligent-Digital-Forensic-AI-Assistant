"""Overview workflow states and recommendations are clear and actionable."""
from __future__ import annotations


def test_overview_renders_measurable_workflow_and_next_action(qt_app):
    from app.ui.pages.overview_page import OverviewPage

    page = OverviewPage()
    page.update_stats({
        "evidence": 3,
        "examinations": 1,
        "artifacts": 42,
        "indexed": 38,
        "searchable": 40,
        "findings_review": 2,
        "reports": 0,
    })
    page.update_workflow({
        "evidence": {
            "status": "in_progress", "value": "2/3",
            "detail": "2 of 3 active evidence items integrity-verified.",
        },
        "examination": {
            "status": "needs_attention", "value": "1/3",
            "detail": "One examination failed.",
        },
        "artifacts": {
            "status": "in_progress", "value": "38/40",
            "detail": "Two text-bearing artifacts remain unindexed.",
        },
        "analysis": {
            "status": "not_started", "value": "0/1",
            "detail": "Analysis becomes available after examination.",
        },
    })
    page.update_recommendation({
        "key": "examination",
        "title": "Review failed examinations",
        "detail": "One examination failed or was interrupted.",
    })

    assert page.stat_cards["examinations"].value_label.text() == "1/3"
    assert page.workflow_cards["examination"].status_label.text() == "Needs attention"
    assert page.workflow_cards["artifacts"].value_label.text() == "38/40"
    assert page.recommendation_title.text() == "Review failed examinations"
    assert page.recommendation_button.text() == "Open Examination"
    page.update_stats({"evidence": 0, "removed_artifacts": 7, "reports": 2})
    assert "7 retained artifact(s)" in page.history_note.text()
    assert "2 completed report(s)" in page.history_note.text()
    page.deleteLater()
