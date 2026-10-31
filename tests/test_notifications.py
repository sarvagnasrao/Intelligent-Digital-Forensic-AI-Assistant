from types import SimpleNamespace

from app.ui.header_bar import AppHeaderBar
from app.ui.main_window import NavigationController


def test_notification_opens_its_own_destination(qt_app):
    header = AppHeaderBar()
    visited = []
    header.add_notification("First", on_click=lambda: visited.append("first"))
    header.add_notification("Second", on_click=lambda: visited.append("second"))
    header.add_notification("Information")
    actions = header._bell_menu.actions()
    assert not actions[0].isEnabled()
    actions[1].trigger()
    actions[2].trigger()
    assert visited == ["second", "first"]
    header.clear_notifications()
    assert not header._notifications


def test_case_notification_reopens_current_case_without_new_notification():
    case = SimpleNamespace(id=7, title="Updated", status="open", priority="high", assignee=None)
    page = SimpleNamespace(refresh=lambda: None, _cases_cache=[case])
    opened = []
    pages = []
    controller = SimpleNamespace(
        global_shell=SimpleNamespace(case_mgmt_page=page),
        case_shell=SimpleNamespace(show_page_by_key=pages.append),
        open_case=lambda *args, **kwargs: opened.append((args, kwargs)),
    )
    NavigationController._open_notified_case(controller, 7)
    assert opened == [((7, "Updated", "open", "high", "Unassigned"), {"notify": False})]
    assert pages == ["overview"]
