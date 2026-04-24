"""Desktop app entry.

The GUI uses a plain Qt event loop. Networking — both the optional
embedded server and the client's reader — runs on background threads. Qt
signals are thread-safe, so the reader thread emits them directly; Qt
marshals them back onto the main thread before slots are invoked.

Command-line modes:
  python -m frontend.desktop                  # interactive connect dialog
  python -m frontend.desktop --host 1.2.3.4   # connect directly
  python -m frontend.desktop --serve          # also start a local server
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import threading

from PySide6.QtCore import Slot
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QMainWindow,
    QMessageBox,
    QWidget,
)

from frontend.desktop.network import NetworkClient
from frontend.desktop.widgets import (
    BLACK,
    BoardWidget,
    ConnectDialog,
    SidePanel,
    WHITE,
)
from transport.lan.server import run_server


def _start_server_thread(host: str, port: int) -> threading.Thread:
    """Run `run_server` on a background thread with its own asyncio loop.

    Returns the Thread. It's a daemon, so it dies with the process; we
    don't try to signal it to shut down cleanly — when the GUI closes,
    the OS will tear the socket down.
    """
    def _worker() -> None:
        try:
            asyncio.run(run_server(host, port))
        except Exception as e:
            print(f"[server thread] exited: {e}", file=sys.stderr)

    t = threading.Thread(target=_worker, daemon=True, name="invisiblego-lan-server")
    t.start()
    return t


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("InvisibleGo")
        central = QWidget()
        layout = QHBoxLayout(central)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(12)

        self.board = BoardWidget()
        self.panel = SidePanel()
        layout.addWidget(self.board, 0)
        layout.addWidget(self.panel, 1)
        self.setCentralWidget(central)
        self.statusBar().showMessage("Not connected")

        self.client = NetworkClient()
        self.my_color: int | None = None
        self._captured = 0
        self._lost = 0
        # Remembered while a play message is in flight to the server, so we
        # can render the stone locally the instant the server acknowledges.
        self._pending_play: tuple[int, int] | None = None

        self.board.intersection_clicked.connect(self._on_play)
        self.panel.pass_clicked.connect(self._on_pass)
        self.panel.resign_clicked.connect(self._on_resign)

        self.client.connected.connect(self._on_connected)
        self.client.welcome.connect(self._on_welcome)
        self.client.your_turn.connect(self._on_your_turn)
        self.client.illegal.connect(self._on_illegal)
        self.client.played.connect(self._on_played)
        self.client.passed.connect(self._on_passed)
        self.client.turn_timeout.connect(self._on_turn_timeout)
        self.client.game_end.connect(self._on_game_end)
        self.client.error.connect(self._on_error)
        self.client.disconnected.connect(self._on_disconnected)

    def start_session(self, host: str, port: int, host_mode: bool) -> None:
        if host_mode:
            self.statusBar().showMessage(
                f"Hosting on {host}:{port} — waiting for opponent..."
            )
            self.panel.append_log(
                f"Hosting local server on {host}:{port}.", "ok"
            )
            _start_server_thread(host, port)
        self.statusBar().showMessage(f"Connecting to {host}:{port}...")
        self.panel.append_log(f"Connecting to {host}:{port}...", "ok")
        self.client.connect_to(host, port)

    @Slot()
    def _on_connected(self) -> None:
        self.statusBar().showMessage("Connected. Waiting for game to start...")
        self.panel.append_log("Connected.", "ok")

    @Slot(str)
    def _on_welcome(self, color: str) -> None:
        self.my_color = BLACK if color == "BLACK" else WHITE
        self.panel.set_color(color)
        self.panel.set_status("Waiting for opponent / your turn...")
        self.panel.append_log(f"You are {color}.", "ok")

    @Slot(dict, int)
    def _on_your_turn(self, view: dict, losses: int) -> None:
        self.board.set_stones(view.get("your_stones", []))
        self.board.set_my_turn(True)
        self.panel.set_my_turn(True)
        self._captured = int(view.get("total_captured_by_me", 0))
        self._lost = int(view.get("total_lost_by_me", 0))
        self.panel.set_state(
            attempts=int(view.get("attempts_remaining", 0)),
            captured=self._captured,
            lost=self._lost,
        )
        self.panel.set_status("Your turn — click an intersection.")
        if losses > 0:
            self.panel.append_log(
                f"You lost {losses} stone(s) since your last turn.", "warn"
            )
        self.statusBar().showMessage("Your turn.")

    @Slot(int)
    def _on_illegal(self, attempts: int) -> None:
        self._pending_play = None
        if attempts > 0:
            # Re-enable input so the player can try another point
            self.board.set_my_turn(True)
            self.panel.set_my_turn(True)
            self.panel.set_state(attempts, self._captured, self._lost)
            self.panel.append_log(
                f"ILLEGAL. {attempts} attempt(s) remaining.", "error"
            )
        else:
            self.panel.append_log(
                "Three illegal attempts. Turn auto-skipped.", "error"
            )
            self.board.set_my_turn(False)
            self.panel.set_my_turn(False)
            self.panel.set_status("Waiting for opponent...")
            self.statusBar().showMessage("Waiting for opponent...")

    @Slot(int)
    def _on_played(self, captured: int) -> None:
        if self._pending_play is not None and self.my_color is not None:
            r, c = self._pending_play
            self.board.place_stone(r, c, self.my_color)
        self._pending_play = None
        if captured > 0:
            self._captured += captured
            self.panel.set_state(0, self._captured, self._lost)
            self.panel.append_log(
                f"Move played. You captured {captured} stone(s).", "ok"
            )
        else:
            self.panel.append_log("Move played.", "ok")
        self.board.set_my_turn(False)
        self.panel.set_my_turn(False)
        self.panel.set_status("Waiting for opponent...")
        self.statusBar().showMessage("Waiting for opponent...")

    @Slot()
    def _on_passed(self) -> None:
        self.panel.append_log("You passed.", "ok")
        self.board.set_my_turn(False)
        self.panel.set_my_turn(False)
        self.panel.set_status("Waiting for opponent...")
        self.statusBar().showMessage("Waiting for opponent...")

    @Slot()
    def _on_turn_timeout(self) -> None:
        self._pending_play = None
        self.panel.append_log("Turn timed out — auto-passed.", "warn")
        self.board.set_my_turn(False)
        self.panel.set_my_turn(False)
        self.panel.set_status("Waiting for opponent...")
        self.statusBar().showMessage("Waiting for opponent...")

    @Slot(dict)
    def _on_game_end(self, msg: dict) -> None:
        self.board.set_stones(msg.get("full_board", []))
        self.board.set_my_turn(False)
        self.panel.set_my_turn(False)
        winner = msg.get("winner")
        ended_by = msg.get("ended_by")
        self.panel.append_log("=== GAME OVER ===", "ok")
        self.panel.append_log(f"BLACK score: {msg.get('black_score')}", "ok")
        self.panel.append_log(f"WHITE score: {msg.get('white_score')}", "ok")
        if winner is None:
            self.panel.append_log("Draw.", "ok")
        else:
            self.panel.append_log(f"{winner} wins.", "ok")
        if ended_by == "resign":
            self.panel.append_log(f"({msg.get('resigner')} resigned.)", "warn")
        elif ended_by == "disconnect":
            self.panel.append_log(
                f"({msg.get('resigner')} disconnected.)", "warn"
            )
        self.panel.set_status("Game over. Full board revealed.")
        self.statusBar().showMessage("Game over.")

    @Slot(str)
    def _on_error(self, message: str) -> None:
        self.panel.append_log(f"Error: {message}", "error")

    @Slot()
    def _on_disconnected(self) -> None:
        self.panel.append_log("Disconnected from server.", "error")
        self.board.set_my_turn(False)
        self.panel.set_my_turn(False)
        self.statusBar().showMessage("Disconnected.")

    @Slot(int, int)
    def _on_play(self, r: int, c: int) -> None:
        # Lock input immediately so rapid double-clicks don't send multiple
        # plays for the same turn. The server response (played / illegal)
        # will re-enable the board as appropriate.
        self.board.set_my_turn(False)
        self.panel.set_my_turn(False)
        self._pending_play = (r, c)
        self.client.send_play(r, c)

    @Slot()
    def _on_pass(self) -> None:
        self.client.send_pass()

    @Slot()
    def _on_resign(self) -> None:
        reply = QMessageBox.question(
            self,
            "Resign",
            "Resign the game?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self.client.send_resign()

    def closeEvent(self, ev) -> None:  # noqa: N802
        self.client.close()
        super().closeEvent(ev)


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="invisiblego-desktop")
    parser.add_argument("--host", help="Server host (skip dialog if given)")
    parser.add_argument("--port", type=int, default=5555)
    parser.add_argument(
        "--serve",
        action="store_true",
        help="Also start a local LAN server on the given host/port.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)

    app = QApplication.instance() or QApplication(sys.argv)
    window = MainWindow()

    if args.host is None:
        dlg = ConnectDialog(window)
        if dlg.exec() != QDialog.Accepted:
            return 0
        host, port, host_mode = dlg.values()
    else:
        host, port, host_mode = args.host, args.port, args.serve

    window.show()
    window.start_session(host, port, host_mode)

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
