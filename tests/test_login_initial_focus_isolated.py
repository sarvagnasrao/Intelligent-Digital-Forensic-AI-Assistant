"""Sign-in should be ready for keyboard entry."""


def test_login_initial_focus_is_username(qt_app):
    from app.ui.login_dialog import LoginDialog

    dialog = LoginDialog()
    dialog.show()
    qt_app.processEvents()
    assert dialog.focusWidget() is dialog.username_edit
    dialog.close()
