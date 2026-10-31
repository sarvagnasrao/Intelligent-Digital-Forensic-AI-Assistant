"""Synthetic ambiguous leads retain their source context in the review UI."""

from test_entities_page import analyse, page, seeded, service, session  # noqa: F401


def test_copied_address_warning_is_visible_in_relationship_review(page, session, service, seeded):
    from app.artifacts.models import Artifact

    artifacts = session.query(Artifact).order_by(Artifact.id).all()
    artifacts[0].content_text = "Contact alice@example.org about the parcel."
    artifacts[1].content_text = "Do not contact alice@example.org: copied from a phishing warning."
    session.commit()
    analyse(service, seeded)
    page.refresh()

    for row, relationship in enumerate(page._relationships):
        if relationship.kind.value == "related_artifacts":
            page.rel_table.selectRow(row)
            page._on_relationship_selected()
            detail = page.rel_evidence.toPlainText()
            if "alice@example.org" in detail:
                assert "copied from a phishing warning" in detail
                assert "Contact alice@example.org about the parcel" in detail
                assert "does not establish identity or ownership" in page.rel_detail.text()
                return
    assert False, "Expected a reviewable relationship for the shared address"
