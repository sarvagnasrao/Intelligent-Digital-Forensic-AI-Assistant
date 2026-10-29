"""Ad-hoc UI checks for the data-folder dialogs and Settings section.

Run from the project root:

    .venv\\Scripts\\python.exe tests\\manual\\test_data_folder_ui.py

Uses the offscreen Qt platform, so no window opens and nothing blocks. Verifies
that the dialogs build, that the path preview follows the chosen folder, and
that Settings shows the derived paths.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(WORKSPACE))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_SANDBOX = Path(tempfile.mkdtemp(prefix="idfa_ui_"))
os.environ["IDFA_CONFIG_DIR"] = str(_SANDBOX / "config")

from PySide6.QtWidgets import QApplication  # noqa: E402

from app.config import default_data_dir, describe_layout_paths  # noqa: E402
from app.firstrun import write_initial_config  # noqa: E402
from app.ui.dialogs.data_folder_dialog import (  # noqa: E402
    ChangeDataFolderDialog,
    FirstRunDialog,
    MissingDataFolderDialog,
)
from app.ui.pages.settings_page import SettingsPage  # noqa: E402

failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  ok   {label}")
    else:
        failures.append(f"{label} {detail}".strip())
        print(f"  FAIL {label} {detail}")


def _detail_texts(picker) -> list[str]:
    """Collect the text of every widget in the path-preview grid."""
    texts: list[str] = []
    for index in range(picker.details.count()):
        widget = picker.details.itemAt(index).widget()
        if widget is not None and hasattr(widget, "text"):
            texts.append(widget.text())
    return texts


app = QApplication.instance() or QApplication(sys.argv)

print("first-run dialog")
dialog = FirstRunDialog()
check("builds", dialog is not None)
check(
    "defaults to recommended folder",
    dialog.selected_path() == default_data_dir(),
    str(dialog.selected_path()),
)
texts = _detail_texts(dialog.picker)
check(
    "shows derived database",
    any((default_data_dir() / "idfa.db").as_posix() in text for text in texts),
    str(texts),
)

custom = _SANDBOX / "custom-root"
dialog.picker.path_edit.setText(str(custom))
texts = _detail_texts(dialog.picker)
check(
    "preview follows chosen path",
    any((custom / "idfa.db").as_posix() in text for text in texts),
    str(texts),
)
dialog.close()

print("missing-folder dialog")
missing = MissingDataFolderDialog(str(custom), "This folder does not exist.")
check("defaults to quit", missing.choice == MissingDataFolderDialog.QUIT)
missing._finish(MissingDataFolderDialog.CHANGE)
check("records change choice", missing.choice == MissingDataFolderDialog.CHANGE)
missing.close()

print("change-folder dialog")
active = write_initial_config(_SANDBOX / "active-root")
change = ChangeDataFolderDialog(active)
check("defaults to move", change.selected_mode() == "move")
change.fresh_radio.setChecked(True)
check("fresh selectable", change.selected_mode() == "fresh")
change.adopt_radio.setChecked(True)
check("adopt selectable", change.selected_mode() == "adopt")
change.close()

print("settings page")
page = SettingsPage()
check(
    "data folder shown",
    page.data_dir_display.text() == active.app.data_dir,
    page.data_dir_display.text(),
)
check("database shown", active.database.url.replace("sqlite:///", "") in page.db_path.text())
summary = page.paths_summary.text()
paths = describe_layout_paths(active)
check("summary lists logs", paths["logs"] in summary)
check("summary lists evidence", paths["evidence"] in summary)
check("summary lists vectors", paths["vectors"] in summary)
check("summary shows free space", "free" in summary.lower(), summary)
page.close()

print()
if failures:
    print(f"{len(failures)} failure(s):")
    for item in failures:
        print(f"  - {item}")
    sys.exit(1)
print("all data-folder UI checks passed")
