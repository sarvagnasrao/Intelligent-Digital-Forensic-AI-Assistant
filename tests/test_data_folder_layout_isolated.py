"""Offscreen data-folder previews, without accessing real case storage."""
from pathlib import Path

import pytest
from PySide6.QtWidgets import QLineEdit

from app.config import Config
from app.ui.dialogs import data_folder_dialog as dialogs
from app.ui.theme.manager import build_qss
from app.ui.theme.palettes import THEMES


@pytest.mark.parametrize("theme", ["dark", "light"])
@pytest.mark.parametrize("kind", ["first", "change"])
def test_folder_dialog_narrow_long_path(qt_app, monkeypatch, theme, kind):
    monkeypatch.setattr(dialogs, "default_data_dir", lambda: Path(r"C:\Synthetic\Cases"))
    monkeypatch.setattr(dialogs, "free_space_bytes", lambda _: 1000000)
    monkeypatch.setattr(dialogs, "folder_size_bytes", lambda _: 1000)
    config = Config()
    config.app.data_dir = r"C:\Synthetic\Cases"
    dialog = dialogs.FirstRunDialog() if kind == "first" else dialogs.ChangeDataFolderDialog(config)
    dialog.setStyleSheet(build_qss(palette=THEMES[theme], theme=theme))
    dialog.resize(650, 650)
    dialog.show()
    dialog.picker.path_edit.setText("C:\\" + "long_component" * 20)
    qt_app.processEvents()

    assert dialog.width() == 650
    assert dialog.minimumSizeHint().width() <= 650
    for row in range(4):
        preview = dialog.picker.details.itemAtPosition(row, 1).widget()
        assert isinstance(preview, QLineEdit) and preview.isReadOnly()
        assert preview.toolTip() == preview.text()
        assert dialog.rect().contains(preview.mapTo(dialog, preview.rect().bottomRight()))
    if kind == "change":
        for radio, mode in ((dialog.move_radio, "move"), (dialog.adopt_radio, "adopt"),
                            (dialog.fresh_radio, "fresh")):
            assert radio.width() >= radio.sizeHint().width()
            radio.setChecked(True)
            assert dialog.selected_mode() == mode
    dialog.close()
