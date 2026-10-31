"""Synthetic dialog layout checks; no evidence is registered or deleted."""
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QDialogButtonBox, QLabel, QLineEdit, QPlainTextEdit

from app.ui.pages.evidence_page import DeleteEvidenceDialog, ReferenceHashDialog, RemoveEvidenceDialog
from app.ui.theme.manager import build_qss
from app.ui.theme.palettes import THEMES


@pytest.mark.parametrize("theme", ["dark", "light"])
@pytest.mark.parametrize("kind", ["remove", "delete", "blocked", "hash"])
def test_dialogs_with_long_synthetic_paths(qt_app, theme, kind):
    path = "C:\\synthetic\\" + "long_directory_name\\" * 12 + "acquisition.E01"
    evidence = SimpleNamespace(evidence_id="EV-001", name="Synthetic image", source_path=path, hashes=[])
    files = [Path(path[:-3] + f"E{i:02d}") for i in range(1, 13)]
    if kind == "remove":
        dialog = RemoveEvidenceDialog(evidence)
    elif kind == "hash":
        dialog = ReferenceHashDialog(evidence)
    else:
        dialog = DeleteEvidenceDialog(evidence, files, ["An examination refers to this item."] if kind == "blocked" else [], impact={"jobs": 2, "artifacts": 123})
    dialog.setStyleSheet(build_qss(palette=THEMES[theme], theme=theme))
    dialog.resize(650, 650)
    dialog.show()
    qt_app.processEvents()
    assert dialog.width() == 650 and dialog.height() == 650
    for widget in dialog.findChildren(QLineEdit) + dialog.findChildren(QDialogButtonBox):
        assert widget.isVisible()
        assert dialog.rect().contains(widget.mapTo(dialog, widget.rect().bottomRight()))
    if kind in ("delete", "blocked"):
        listing = dialog.findChild(QPlainTextEdit)
        assert listing.toPlainText() == "\n".join(map(str, files))
        assert listing.isReadOnly() and listing.verticalScrollBar().maximum() > 0
        assert any(edit.text() == path and edit.isReadOnly() for edit in dialog.findChildren(QLineEdit))
        assert any("permanently deletes 2" in label.text() for label in dialog.findChildren(QLabel))
        assert dialog.buttons.button(QDialogButtonBox.StandardButton.Ok).isEnabled() is False
        if kind == "delete":
            dialog.confirm_edit.setText("EV-001")
            assert dialog.buttons.button(QDialogButtonBox.StandardButton.Ok).isEnabled()
    screenshot_dir = os.environ.get("IDFA_DIALOG_SCREENSHOTS")
    if screenshot_dir:
        Path(screenshot_dir).mkdir(parents=True, exist_ok=True)
        dialog.grab().save(str(Path(screenshot_dir) / f"{kind}-{theme}.png"))
    dialog.close()
