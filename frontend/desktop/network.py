"""Threaded, synchronous-socket protocol client for the Qt GUI.

Earlier iterations of this module used asyncio (via qasync and later
PySide6.QtAsyncio), but both bridges failed on this target environment:
qasync's internal QTimer fails to arm, and QtAsyncio's event loop does not
yet implement `create_connection` / `create_server`. The Qt main loop
handles GUI only; networking runs on a background thread with a plain
blocking socket. Incoming messages turn into Qt signals, which are
automatically marshalled to the UI thread for slot delivery.
"""
from __future__ import annotations

import json
import socket
import struct
import threading
from typing import Any

from PySide6.QtCore import QObject, Signal

FRAME_HEADER = struct.Struct("!I")
MAX_FRAME_BYTES = 64 * 1024


class NetworkClient(QObject):
    welcome = Signal(str)
    your_turn = Signal(dict, int)
    illegal = Signal(int)
    played = Signal(int)
    passed = Signal()
    turn_timeout = Signal()
    game_end = Signal(dict)
    rematch_declined = Signal()
    dead_marking_started = Signal(str, list)
    dead_marking_proposal = Signal(list)
    dead_marking_rejected = Signal()
    error = Signal(str)
    disconnected = Signal()
    connected = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._sock: socket.socket | None = None
        self._send_lock = threading.Lock()
        self._reader_thread: threading.Thread | None = None
        self._closed = False

    def connect_to(self, host: str, port: int) -> None:
        """Open a blocking TCP connection and start the reader thread.

        Called from the GUI thread. Emits `connected` or `error` when done
        (we don't block the UI thread on the DNS+TCP handshake; we spawn a
        tiny thread for it too).
        """
        def _do_connect() -> None:
            try:
                s = socket.create_connection((host, port), timeout=10)
                s.settimeout(None)
            except OSError as e:
                self.error.emit(f"Could not connect to {host}:{port} — {e}")
                return
            self._sock = s
            self._closed = False
            self._reader_thread = threading.Thread(
                target=self._read_loop, daemon=True
            )
            self._reader_thread.start()
            self.connected.emit()

        threading.Thread(target=_do_connect, daemon=True).start()

    def close(self) -> None:
        self._closed = True
        sock = self._sock
        self._sock = None
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                sock.close()
            except OSError:
                pass

    def _read_loop(self) -> None:
        try:
            while True:
                header = self._recv_exact(4)
                if header is None:
                    break
                (length,) = FRAME_HEADER.unpack(header)
                if length > MAX_FRAME_BYTES:
                    self.error.emit(f"Incoming frame too large: {length}")
                    break
                body = self._recv_exact(length)
                if body is None:
                    break
                try:
                    msg = json.loads(body.decode("utf-8"))
                except Exception as e:
                    self.error.emit(f"Bad message from server: {e}")
                    break
                self._dispatch(msg)
        finally:
            if not self._closed:
                self.disconnected.emit()

    def _recv_exact(self, n: int) -> bytes | None:
        buf = bytearray()
        while len(buf) < n:
            sock = self._sock
            if sock is None:
                return None
            try:
                chunk = sock.recv(n - len(buf))
            except OSError:
                return None
            if not chunk:
                return None
            buf.extend(chunk)
        return bytes(buf)

    def _dispatch(self, msg: dict[str, Any]) -> None:
        t = msg.get("type")
        if t == "welcome":
            self.welcome.emit(msg.get("color", ""))
        elif t == "your_turn":
            self.your_turn.emit(
                msg.get("view", {}),
                int(msg.get("losses_since_last_turn", 0)),
            )
        elif t == "illegal":
            self.illegal.emit(int(msg.get("attempts_remaining", 0)))
        elif t == "played":
            self.played.emit(int(msg.get("captured", 0)))
        elif t == "passed":
            self.passed.emit()
        elif t == "turn_timeout":
            self.turn_timeout.emit()
        elif t == "game_end":
            self.game_end.emit(msg)
        elif t == "rematch_declined":
            self.rematch_declined.emit()
        elif t == "dead_marking_started":
            self.dead_marking_started.emit(
                str(msg.get("your_role", "")),
                list(msg.get("full_board", [])),
            )
        elif t == "dead_marking_proposal":
            self.dead_marking_proposal.emit(list(msg.get("points", [])))
        elif t == "dead_marking_rejected":
            self.dead_marking_rejected.emit()
        elif t == "error":
            self.error.emit(str(msg.get("message", "")))

    def _send(self, msg: dict[str, Any]) -> None:
        sock = self._sock
        if sock is None:
            return
        body = json.dumps(msg, separators=(",", ":")).encode("utf-8")
        frame = FRAME_HEADER.pack(len(body)) + body
        with self._send_lock:
            try:
                sock.sendall(frame)
            except OSError as e:
                self.error.emit(f"Send failed: {e}")

    def send_play(self, row: int, col: int) -> None:
        self._send({"type": "play", "row": row, "col": col})

    def send_pass(self) -> None:
        self._send({"type": "pass"})

    def send_resign(self) -> None:
        self._send({"type": "resign"})

    def send_rematch(self, agree: bool) -> None:
        self._send({"type": "rematch", "agree": agree})

    def send_mark_dead(self, points: list[tuple[int, int]]) -> None:
        self._send({"type": "mark_dead", "points": [[r, c] for (r, c) in points]})

    def send_mark_decision(self, approve: bool) -> None:
        self._send({"type": "mark_decision", "approve": approve})
