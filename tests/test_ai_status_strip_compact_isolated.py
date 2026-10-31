"""The status strip is compact without hiding service state or actions."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app.ui.pages.ai_analysis_page import STATUS_COLORS, StatusStrip


def test_status_strip_states_and_actions():
    app = QApplication.instance() or QApplication([])
    strip = StatusStrip()
    states = ("ok", "error", "partial", "checking", "unknown")
    for service, state in zip(strip.SERVICES, states):
        strip.set_status(service, state, tooltip="Synthetic detail")
        label = strip.services[service]
        assert label.property("status") == state
        assert STATUS_COLORS[state] in label.text()
        assert service in label.accessibleName()
        assert "Synthetic detail" in label.toolTip()

    strip.set_status("Index", "partial", "2 < 4", "Index detail")
    assert "2 < 4" in strip.services["Index"].accessibleName()
    assert "2 &lt; 4" in strip.services["Index"].text()
    calls = []
    strip.refresh_requested.connect(lambda: calls.append(True))
    strip.refresh_btn.click()
    assert calls == [True]
    strip.set_all_checking()
    assert all(label.property("status") == "checking" for label in strip.services.values())
    strip.set_all_unknown()
    assert all(label.property("status") == "unknown" for label in strip.services.values())

    strip.resize(800, 200)
    strip.show()
    app.processEvents()
    assert strip._status_columns == 4
    assert strip.refresh_btn.height() == 28
    strip.close()
