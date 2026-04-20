"""Smoke tests for the desktop client.

We can't run a real GUI in CI, but we can validate the modules import and
that widgets instantiate under Qt's offscreen platform plugin. This catches
syntax errors, broken imports, and basic widget construction bugs.
"""
import os
import sys

import pytest

# Force Qt to use the offscreen plugin so these tests don't require a display.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PySide6 = pytest.importorskip("PySide6")


def _qapp():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication(sys.argv)


def test_widgets_module_imports():
    from frontend.desktop import widgets  # noqa: F401


def test_network_module_imports():
    from frontend.desktop import network  # noqa: F401


def test_app_module_imports():
    from frontend.desktop import app  # noqa: F401


def test_board_widget_constructs():
    _qapp()
    from frontend.desktop.widgets import BoardWidget

    bw = BoardWidget()
    assert bw.size().width() == BoardWidget.SIZE
    assert bw.size().height() == BoardWidget.SIZE


def test_side_panel_constructs():
    _qapp()
    from frontend.desktop.widgets import SidePanel

    sp = SidePanel()
    sp.set_color("BLACK")
    sp.set_state(attempts=3, captured=0, lost=0)
    sp.append_log("hello", "ok")


def test_connect_dialog_constructs():
    _qapp()
    from frontend.desktop.widgets import ConnectDialog

    dlg = ConnectDialog()
    host, port, host_mode = dlg.values()
    assert host == "127.0.0.1"
    assert port == 5555
    assert host_mode is False


def test_main_window_constructs_without_display():
    _qapp()
    from frontend.desktop.app import MainWindow

    w = MainWindow()
    assert w.windowTitle() == "InvisibleGo"
    # Drive a few signals manually to verify wiring doesn't crash
    w._on_welcome("BLACK")
    w._on_your_turn(
        {
            "your_stones": [0] * 81,
            "attempts_remaining": 3,
            "total_captured_by_me": 0,
            "total_lost_by_me": 0,
        },
        0,
    )
    w._on_illegal(2)
    w._on_played(0)
    w._on_passed()
    w._on_game_end(
        {
            "full_board": [0] * 81,
            "black_score": 0,
            "white_score": 0,
            "winner": None,
            "ended_by": "pass",
            "resigner": None,
        }
    )
