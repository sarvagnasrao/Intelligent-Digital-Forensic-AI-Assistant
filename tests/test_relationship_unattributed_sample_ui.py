import json
from types import SimpleNamespace

from app.analysis.models import RelationshipStatus
from app.ui.pages.entities_timeline_page import EntitiesTimelinePage


class Widget:
    def __init__(self):
        self.text = ""

    def setText(self, text):
        self.text = text

    def setPlainText(self, text):
        self.text = text

    def show(self):
        pass

    def setVisible(self, visible):
        self.visible = visible


def test_shared_entity_sample_is_not_attributed_to_a_specific_artifact():
    relationship = SimpleNamespace(
        details_json=json.dumps({"sample": "source excerpt"}),
        artifact_ids_json="[1, 2]",
        evidence_ids_json="[]",
        kind=SimpleNamespace(value="shared_entity"),
        left_type="email", left_value="a@example.test",
        right_type="email", right_value="b@example.test",
        shared_count=2, score=0.5, status=RelationshipStatus.PENDING,
    )
    page = SimpleNamespace(
        _selected_relationship=lambda: relationship,
        _artifact_labels=lambda ids: ["first artifact", "second artifact"],
        _evidence_labels=lambda ids: [],
        rel_detail=Widget(), rel_evidence=Widget(), rel_detail_panel=Widget(),
        rel_review_controls=Widget(), rel_review_note=Widget(),
        confirm_btn=Widget(), reject_btn=Widget(), reset_btn=Widget(),
    )

    EntitiesTimelinePage._on_relationship_selected(page)

    assert "Unattributed sample" in page.rel_detail.text
    assert "source artifact not recorded" in page.rel_detail.text
    assert "verify against supporting artifacts" in page.rel_detail.text
    assert "source excerpt" in page.rel_detail.text
    assert "first artifact" in page.rel_evidence.text
    assert "second artifact" in page.rel_evidence.text
    assert page.confirm_btn.visible and page.reject_btn.visible
    assert not page.reset_btn.visible
