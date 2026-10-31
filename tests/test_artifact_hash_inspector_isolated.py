"""The narrow inspector must retain and expose the complete digest."""

from types import SimpleNamespace

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QHBoxLayout, QWidget

from app.ui.pages.artifacts_search_page import ArtifactDetailPane


def test_narrow_hash_is_selectable_scrollable_and_copyable(qt_app, tmp_path):
    digest = "0123456789abcdef" * 4
    artifact = SimpleNamespace(
        artifact_id="ART-1", artifact_type="document", name="report.txt",
        evidence=None, source_size=0, index_status="indexed", created_time=None,
        source_path="C:/evidence/report.txt", content_hash=digest,
        metadata_json="{}", content_text="Synthetic content",
    )
    window = QWidget()
    window.setFont(QFont("Segoe UI", 10))
    window.resize(650, 650)
    layout = QHBoxLayout(window)
    pane = ArtifactDetailPane()
    pane.setFixedWidth(300)
    layout.addWidget(pane)
    layout.addStretch()
    pane.resize(300, 650)
    pane.set_artifact(artifact)
    window.show()
    qt_app.processEvents()

    assert pane.hash_value.isReadOnly()
    assert pane.hash_value.text() == digest
    assert pane.hash_value.fontMetrics().horizontalAdvance(digest) > pane.hash_value.width()
    pane.hash_value.end(False)
    assert pane.hash_value.cursorPosition() == len(digest)
    pane.hash_value.selectAll()
    pane.hash_value.copy()
    assert QApplication.clipboard().text() == digest
    pane.copy_hash_button.click()
    assert QApplication.clipboard().text() == digest
    pane.hash_value.home(False)
    assert window.grab().save(str(tmp_path / "artifact-inspector-650.png"))

    artifact.content_hash = None
    pane.set_artifact(artifact)
    assert pane.hash_value.text() == "Not available"
    assert not pane.copy_hash_button.isEnabled()
    pane.set_artifact(None)
    assert pane.hash_value.text() == ""
    window.close()
