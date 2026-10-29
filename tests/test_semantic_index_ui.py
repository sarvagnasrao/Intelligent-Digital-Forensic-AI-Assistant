"""Live semantic indexing state is visible on Artifacts & Search."""
from __future__ import annotations


def test_index_progress_updates_visible_status_and_bar(qt_app):
    from app.ui.pages.artifacts_search_page import ArtifactsSearchPage

    page = ArtifactsSearchPage()
    page._on_index_progress("Embedding passages", 50, 100, 20, 2)

    assert page.index_progress_bar.value() == 500
    assert page.index_progress_bar.format() == "50/100 artifacts · 50%"
    assert "Embedding passages" in page.index_status_label.text()
    assert "20 indexed" in page.index_status_label.text()
    assert "2 failed" in page.index_status_label.text()

    page.deleteLater()
