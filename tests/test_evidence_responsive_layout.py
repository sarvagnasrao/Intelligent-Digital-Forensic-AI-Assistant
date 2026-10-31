"""Evidence controls remain accessible when the case workspace is narrow."""
from types import SimpleNamespace

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QPushButton


def test_evidence_reflows_with_selected_record(qt_app):
    from app.evidence.models import EvidenceStatus, EvidenceType
    from app.evidence.service import EvidenceService
    from app.ui.pages.evidence_page import EvidencePage
    from app.ui.theme.manager import build_qss

    page = EvidencePage()
    page.setStyleSheet(build_qss(theme="dark"))
    evidence = SimpleNamespace(
        id=1, evidence_id="EV-001", name="Synthetic image", status=EvidenceStatus.REGISTERED,
        evidence_type=EvidenceType.IMAGE, mime_type="application/x-raw-disk-image",
        size_bytes=2048, registered_at=None, description="Test evidence",
        source_path="C:\\synthetic\\image.dd", stored_path=None, is_removed=False,
        hashes=[], custody_events=[],
    )
    page.detail_pane.set_evidence(evidence, EvidenceService.STORED_PRESENT)
    page.resize(500, 900)
    page.show()
    qt_app.processEvents()

    assert page._splitter.orientation() == Qt.Orientation.Vertical
    assert page._tools_grid.getItemPosition(page._tools_grid.indexOf(page.manifest_btn))[:2] == (1, 1)
    for control in (page.devices_btn, page.register_btn, page.search_edit, page.status_filter,
                    page.show_archived_check, page.show_removed_check, page.select_all_btn,
                    page.clear_selection_btn, page.check_files_btn, page.manifest_btn):
        assert control.isVisible()
        assert control.mapTo(page, control.rect().topRight()).x() < page.width()
    buttons = {button.text(): button for button in page.detail_pane.findChildren(QPushButton)}
    assert "Verify integrity" in buttons and "More actions" in buttons
    assert {action.text() for action in buttons["More actions"].menu().actions()} >= {
        "Export copy…", "Set reference hash…", "Edit details…",
        "Remove from case…", "Delete permanently…",
    }
    page.resize(1100, 900)
    qt_app.processEvents()
    assert page._splitter.orientation() == Qt.Orientation.Horizontal
    assert page._tools_grid.getItemPosition(page._tools_grid.indexOf(page.manifest_btn))[:2] == (0, 3)
    page.close()
    page.deleteLater()
