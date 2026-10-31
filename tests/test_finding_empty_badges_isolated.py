"""The empty findings inspector must not claim an origin or status."""


def test_empty_inspector_hides_finding_badges(qt_app):
    from app.ui.pages.findings_page import FindingDetailPane

    pane = FindingDetailPane()
    assert pane.status_badge.isHidden()
    assert pane.origin_badge.isHidden()
    pane.deleteLater()
