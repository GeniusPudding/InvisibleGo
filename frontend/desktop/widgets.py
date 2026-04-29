"""Qt widgets: BoardWidget, SidePanel, ConnectDialog.

The board is custom-painted with QPainter. Stones are drawn with a radial
gradient and a soft drop shadow so they read as 3D, in the same spirit as
KaTrain's board (https://github.com/sanderland/katrain) without bundling
any image assets.
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QMouseEvent,
    QPainter,
    QPen,
    QRadialGradient,
)
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core.board import BOARD_SIZE

EMPTY = 0
BLACK = 1
WHITE = 2

BOARD_BG = QColor("#d9b26a")
BOARD_BG_DARK = QColor("#bf9550")
LINE_COLOR = QColor("#1c1208")
COLS = "ABCDEFGHJ"
STAR_POINTS = [(2, 2), (2, 6), (4, 4), (6, 2), (6, 6)]


class BoardWidget(QWidget):
    intersection_clicked = Signal(int, int)
    dead_group_toggled = Signal(int, int)  # marker mode click

    CELL = 60
    PAD = 36
    SIZE = PAD * 2 + (BOARD_SIZE - 1) * CELL

    def __init__(self) -> None:
        super().__init__()
        self.setFixedSize(self.SIZE, self.SIZE)
        self.setMouseTracking(True)
        self._stones = [EMPTY] * (BOARD_SIZE * BOARD_SIZE)
        self._my_turn = False
        self._hover: tuple[int, int] | None = None
        self._last_own_move: tuple[int, int] | None = None
        self._my_color: int = EMPTY
        # Numbered overlay state. _own_numbers maps surviving own stone
        # positions to their absolute move ordinal (during play). At game
        # end _full_history holds (color_name, r, c) for every play; the
        # widget folds it into a per-position map at paint time.
        self._show_numbers: bool = False
        self._own_numbers: dict[tuple[int, int], int] = {}
        self._full_history: list[tuple[str, int, int]] = []
        # Dead-marking phase state. _marking_mode = "marker" | "approver" | "".
        self._marking_mode: str = ""
        self._proposed_dead: set[tuple[int, int]] = set()

    def set_stones(self, stones) -> None:
        self._stones = list(stones)
        self.update()

    def set_last_own_move(self, pos: tuple[int, int] | None) -> None:
        self._last_own_move = pos
        self.update()

    def set_my_color(self, color: int) -> None:
        self._my_color = color
        self.update()

    def set_own_move_numbers(self, entries) -> None:
        """entries: iterable of [r, c, n] from server during play."""
        self._own_numbers = {(int(r), int(c)): int(n) for r, c, n in (entries or [])}
        self.update()

    def set_full_move_history(self, entries) -> None:
        """entries: iterable of [color_name, r, c] from game_end."""
        self._full_history = [
            (str(name), int(r), int(c)) for name, r, c in (entries or [])
        ]
        self.update()

    def set_show_numbers(self, on: bool) -> None:
        self._show_numbers = bool(on)
        self.update()

    def reset_for_new_game(self) -> None:
        self._own_numbers = {}
        self._full_history = []
        self._last_own_move = None
        self._marking_mode = ""
        self._proposed_dead = set()
        self.update()

    def enter_marking_mode(self, role: str) -> None:
        self._marking_mode = role
        self._proposed_dead = set()
        self.update()

    def exit_marking_mode(self) -> None:
        self._marking_mode = ""
        self._proposed_dead = set()
        self.update()

    def set_proposed_dead(self, points) -> None:
        self._proposed_dead = {(int(r), int(c)) for r, c in (points or [])}
        self.update()

    def proposed_dead(self) -> set[tuple[int, int]]:
        return set(self._proposed_dead)

    def clear_proposed_dead(self) -> None:
        self._proposed_dead = set()
        self.update()

    def place_stone(self, r: int, c: int, color: int) -> None:
        """Locally add a stone to the displayed board.

        Used for optimistic rendering of the player's own move the moment
        the server acknowledges it, so the stone shows up without waiting
        for the next `your_turn` view.
        """
        self._stones[r * BOARD_SIZE + c] = color
        self._last_own_move = (r, c)
        self.update()

    def set_my_turn(self, on: bool) -> None:
        self._my_turn = on
        if not on:
            self._hover = None
        self.update()

    def _intersection_xy(self, r: int, c: int) -> tuple[int, int]:
        return (self.PAD + c * self.CELL, self.PAD + r * self.CELL)

    def _pixel_to_intersection(self, p) -> tuple[int, int] | None:
        x, y = p.x(), p.y()
        c = round((x - self.PAD) / self.CELL)
        r = round((y - self.PAD) / self.CELL)
        if not (0 <= r < BOARD_SIZE and 0 <= c < BOARD_SIZE):
            return None
        cx, cy = self._intersection_xy(r, c)
        if (x - cx) ** 2 + (y - cy) ** 2 > (self.CELL * 0.45) ** 2:
            return None
        return (r, c)

    def paintEvent(self, _ev) -> None:  # noqa: N802 (Qt naming)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        # Wood-tone background using a soft radial highlight for depth.
        bg_grad = QRadialGradient(
            QPointF(self.SIZE * 0.5, self.SIZE * 0.5),
            self.SIZE * 0.7,
        )
        bg_grad.setColorAt(0.0, BOARD_BG)
        bg_grad.setColorAt(1.0, BOARD_BG_DARK)
        p.fillRect(self.rect(), QBrush(bg_grad))

        # Grid lines
        p.setPen(QPen(LINE_COLOR, 1.2))
        for i in range(BOARD_SIZE):
            x = self.PAD + i * self.CELL
            y = self.PAD + i * self.CELL
            p.drawLine(self.PAD, y, self.PAD + (BOARD_SIZE - 1) * self.CELL, y)
            p.drawLine(x, self.PAD, x, self.PAD + (BOARD_SIZE - 1) * self.CELL)

        # Star points (hoshi)
        p.setBrush(QBrush(LINE_COLOR))
        p.setPen(Qt.NoPen)
        for r, c in STAR_POINTS:
            cx, cy = self._intersection_xy(r, c)
            p.drawEllipse(QPointF(cx, cy), 3.5, 3.5)

        # Coordinate labels
        p.setPen(QPen(LINE_COLOR))
        font = QFont()
        font.setPointSize(10)
        p.setFont(font)
        for c in range(BOARD_SIZE):
            cx, _ = self._intersection_xy(0, c)
            p.drawText(cx - 8, self.PAD - 22, 16, 16, Qt.AlignCenter, COLS[c])
            p.drawText(
                cx - 8,
                self.SIZE - self.PAD + 6,
                16,
                16,
                Qt.AlignCenter,
                COLS[c],
            )
        for r in range(BOARD_SIZE):
            _, cy = self._intersection_xy(r, 0)
            label = str(BOARD_SIZE - r)
            p.drawText(self.PAD - 30, cy - 8, 22, 16, Qt.AlignCenter, label)
            p.drawText(
                self.SIZE - self.PAD + 6,
                cy - 8,
                22,
                16,
                Qt.AlignCenter,
                label,
            )

        # Stones
        for r in range(BOARD_SIZE):
            for c in range(BOARD_SIZE):
                v = self._stones[r * BOARD_SIZE + c]
                if v != EMPTY:
                    self._draw_stone(p, r, c, v)

        # Last-own-move marker: a small colored dot on top of the stone,
        # so the player can immediately tell which one was theirs.
        if self._last_own_move is not None and self._my_color != EMPTY:
            r, c = self._last_own_move
            idx = r * BOARD_SIZE + c
            if 0 <= idx < len(self._stones) and self._stones[idx] == self._my_color:
                cx, cy = self._intersection_xy(r, c)
                p.setBrush(QColor("#ff5a38"))
                p.setPen(QPen(QColor("#7a2010"), 1))
                p.drawEllipse(QPointF(cx, cy), self.CELL * 0.12, self.CELL * 0.12)

        # Move-number overlay (toggle).
        if self._show_numbers:
            self._draw_move_numbers(p)

        # Dead-marking overlay: red X on every proposed dead stone.
        if self._marking_mode and self._proposed_dead:
            self._draw_dead_markers(p)

        # Hover indicator on empty intersections during your turn
        if self._hover is not None and self._my_turn:
            r, c = self._hover
            if self._stones[r * BOARD_SIZE + c] == EMPTY:
                cx, cy = self._intersection_xy(r, c)
                p.setBrush(QColor(0, 0, 0, 60))
                p.setPen(Qt.NoPen)
                p.drawEllipse(
                    QPointF(cx, cy),
                    self.CELL * 0.42,
                    self.CELL * 0.42,
                )

    def _draw_dead_markers(self, p: QPainter) -> None:
        size = self.CELL * 0.22
        pen = QPen(QColor("#ff2020"))
        pen.setWidth(3)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        for r, c in self._proposed_dead:
            cx, cy = self._intersection_xy(r, c)
            p.drawLine(int(cx - size), int(cy - size), int(cx + size), int(cy + size))
            p.drawLine(int(cx + size), int(cy - size), int(cx - size), int(cy + size))

    def _bfs_group(self, r0: int, c0: int) -> list[tuple[int, int]]:
        """Connected same-color group containing (r0, c0). Empty if start is empty."""
        v0 = self._stones[r0 * BOARD_SIZE + c0]
        if v0 == EMPTY:
            return []
        seen: set[tuple[int, int]] = set()
        out: list[tuple[int, int]] = []
        stack = [(r0, c0)]
        while stack:
            r, c = stack.pop()
            if (r, c) in seen:
                continue
            seen.add((r, c))
            if self._stones[r * BOARD_SIZE + c] != v0:
                continue
            out.append((r, c))
            for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                nr, nc = r + dr, c + dc
                if 0 <= nr < BOARD_SIZE and 0 <= nc < BOARD_SIZE:
                    stack.append((nr, nc))
        return out

    def _toggle_dead_group_at(self, r: int, c: int) -> None:
        group = self._bfs_group(r, c)
        if not group:
            return
        any_marked = any(point in self._proposed_dead for point in group)
        if any_marked:
            self._proposed_dead -= set(group)
        else:
            self._proposed_dead |= set(group)
        self.update()

    def _draw_move_numbers(self, p: QPainter) -> None:
        # Build (r, c) -> (ordinal, expected_color_int).
        #   - During play: server sends our own moves in `_own_numbers`.
        #   - At game end: server sends `_full_history` covering both colors.
        # Capture-and-replay shapes: later entries overwrite earlier ones,
        # so the dict ends up with whichever stone is currently visible.
        numbered: dict[tuple[int, int], tuple[int, int]] = {}
        if self._full_history:
            for i, (name, r, c) in enumerate(self._full_history, start=1):
                expected = BLACK if name == "BLACK" else WHITE
                numbered[(r, c)] = (i, expected)
        elif self._own_numbers and self._my_color != EMPTY:
            for (r, c), n in self._own_numbers.items():
                numbered[(r, c)] = (n, self._my_color)

        if not numbered:
            return
        font = QFont()
        font.setPointSize(11)
        font.setBold(True)
        p.setFont(font)
        from PySide6.QtCore import QRectF
        size = self.CELL * 0.7
        for (r, c), (n, expected) in numbered.items():
            idx = r * BOARD_SIZE + c
            if not (0 <= idx < len(self._stones)):
                continue
            v = self._stones[idx]
            if v == EMPTY or v != expected:
                # Stone gone (capture) or replaced by other color: stale.
                continue
            cx, cy = self._intersection_xy(r, c)
            text_color = QColor("#fff") if v == BLACK else QColor("#000")
            p.setPen(QPen(text_color))
            rect = QRectF(cx - size / 2, cy - size / 2, size, size)
            p.drawText(rect, Qt.AlignCenter, str(n))

    def _draw_stone(self, p: QPainter, r: int, c: int, color: int) -> None:
        cx, cy = self._intersection_xy(r, c)
        radius = self.CELL * 0.45

        # Soft drop shadow
        p.setBrush(QColor(0, 0, 0, 80))
        p.setPen(Qt.NoPen)
        p.drawEllipse(QPointF(cx + 2, cy + 3), radius, radius)

        # Radial gradient stone
        light_off = radius * 0.4
        grad = QRadialGradient(
            QPointF(cx - light_off, cy - light_off),
            radius * 1.6,
        )
        if color == BLACK:
            grad.setColorAt(0.0, QColor("#5a5a5a"))
            grad.setColorAt(0.6, QColor("#1a1a1a"))
            grad.setColorAt(1.0, QColor("#000"))
            edge = QColor("#000")
        else:
            grad.setColorAt(0.0, QColor("#ffffff"))
            grad.setColorAt(0.6, QColor("#e6e6e6"))
            grad.setColorAt(1.0, QColor("#bcbcbc"))
            edge = QColor("#666")
        p.setBrush(QBrush(grad))
        p.setPen(QPen(edge, 1))
        p.drawEllipse(QPointF(cx, cy), radius, radius)

    def mouseMoveEvent(self, ev: QMouseEvent) -> None:  # noqa: N802
        new_hover = self._pixel_to_intersection(ev.position())
        if new_hover != self._hover:
            self._hover = new_hover
            self.update()

    def leaveEvent(self, _ev) -> None:  # noqa: N802
        if self._hover is not None:
            self._hover = None
            self.update()

    def mousePressEvent(self, ev: QMouseEvent) -> None:  # noqa: N802
        if ev.button() != Qt.LeftButton:
            return
        pos = self._pixel_to_intersection(ev.position())
        if pos is None:
            return
        if self._marking_mode == "marker":
            self._toggle_dead_group_at(*pos)
            self.dead_group_toggled.emit(*pos)
            return
        if self._my_turn:
            self.intersection_clicked.emit(*pos)


class SidePanel(QWidget):
    pass_clicked = Signal()
    resign_clicked = Signal()
    rematch_clicked = Signal()
    show_numbers_toggled = Signal(bool)
    submit_dead_clicked = Signal()
    clear_dead_clicked = Signal()
    approve_dead_clicked = Signal()
    reject_dead_clicked = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumWidth(280)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        self.color_label = QLabel("Connecting...")
        font = self.color_label.font()
        font.setPointSize(14)
        font.setBold(True)
        self.color_label.setFont(font)
        self.color_label.setAlignment(Qt.AlignCenter)
        self.color_label.setStyleSheet(
            "padding: 6px 10px; border-radius: 4px; background: #ddd;"
        )
        layout.addWidget(self.color_label)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #444; font-style: italic;")
        layout.addWidget(self.status_label)

        info = QGroupBox("Game state")
        form = QFormLayout(info)
        self.attempts_label = QLabel("-")
        self.captured_label = QLabel("0")
        self.lost_label = QLabel("0")
        form.addRow("Attempts left:", self.attempts_label)
        form.addRow("Captured by me:", self.captured_label)
        form.addRow("Lost by me:", self.lost_label)
        layout.addWidget(info)

        button_row = QHBoxLayout()
        self.pass_btn = QPushButton("Pass")
        self.pass_btn.setEnabled(False)
        self.pass_btn.clicked.connect(self.pass_clicked.emit)
        self.resign_btn = QPushButton("Resign")
        self.resign_btn.setEnabled(False)
        self.resign_btn.clicked.connect(self.resign_clicked.emit)
        self.rematch_btn = QPushButton("Rematch")
        self.rematch_btn.setVisible(False)
        self.rematch_btn.clicked.connect(self.rematch_clicked.emit)
        self.show_numbers_btn = QPushButton("Show #")
        self.show_numbers_btn.setCheckable(True)
        self.show_numbers_btn.toggled.connect(self._on_numbers_toggled)
        self.submit_dead_btn = QPushButton("Submit dead")
        self.submit_dead_btn.setVisible(False)
        self.submit_dead_btn.clicked.connect(self.submit_dead_clicked.emit)
        self.clear_dead_btn = QPushButton("Clear")
        self.clear_dead_btn.setVisible(False)
        self.clear_dead_btn.clicked.connect(self.clear_dead_clicked.emit)
        self.approve_dead_btn = QPushButton("Approve")
        self.approve_dead_btn.setVisible(False)
        self.approve_dead_btn.clicked.connect(self.approve_dead_clicked.emit)
        self.reject_dead_btn = QPushButton("Reject")
        self.reject_dead_btn.setVisible(False)
        self.reject_dead_btn.clicked.connect(self.reject_dead_clicked.emit)
        button_row.addWidget(self.pass_btn)
        button_row.addWidget(self.resign_btn)
        button_row.addWidget(self.show_numbers_btn)
        button_row.addWidget(self.submit_dead_btn)
        button_row.addWidget(self.clear_dead_btn)
        button_row.addWidget(self.approve_dead_btn)
        button_row.addWidget(self.reject_dead_btn)
        button_row.addWidget(self.rematch_btn)
        button_row.addStretch()
        layout.addLayout(button_row)

        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setMinimumHeight(180)
        self.log.setStyleSheet(
            "QTextEdit { background: #fdf6e3; border: 1px solid #aaa;"
            " font-family: 'Consolas', 'Menlo', monospace; }"
        )
        layout.addWidget(self.log, 1)

    def _on_numbers_toggled(self, on: bool) -> None:
        self.show_numbers_btn.setText("Hide #" if on else "Show #")
        self.show_numbers_toggled.emit(on)

    def append_log(self, text: str, kind: str = "") -> None:
        color = {"error": "#c33", "ok": "#286f2c", "warn": "#a66100"}.get(
            kind, "#222"
        )
        self.log.append(f'<span style="color:{color};">{text}</span>')

    def set_color(self, color_name: str) -> None:
        self.color_label.setText(f"You are {color_name}")
        if color_name == "BLACK":
            bg, fg = "#222", "#eee"
        else:
            bg, fg = "#fafafa", "#222"
        self.color_label.setStyleSheet(
            f"background: {bg}; color: {fg};"
            " padding: 6px 10px; border-radius: 4px;"
            f" border: 1px solid #999;"
        )

    def set_status(self, text: str) -> None:
        self.status_label.setText(text)

    def set_my_turn(self, on: bool) -> None:
        self.pass_btn.setEnabled(on)
        self.resign_btn.setEnabled(on)

    def set_rematch_visible(self, visible: bool, enabled: bool = True) -> None:
        self.rematch_btn.setVisible(visible)
        self.rematch_btn.setEnabled(enabled)

    def set_marker_controls_visible(self, visible: bool, submit_enabled: bool = True) -> None:
        self.submit_dead_btn.setVisible(visible)
        self.submit_dead_btn.setEnabled(submit_enabled)
        self.clear_dead_btn.setVisible(visible)

    def set_approver_controls_visible(self, visible: bool) -> None:
        self.approve_dead_btn.setVisible(visible)
        self.reject_dead_btn.setVisible(visible)

    def set_play_controls_visible(self, visible: bool) -> None:
        # During the marking phase the normal play buttons are hidden.
        self.pass_btn.setVisible(visible)
        self.resign_btn.setVisible(visible)

    def set_state(self, attempts: int, captured: int, lost: int) -> None:
        self.attempts_label.setText(str(attempts))
        self.captured_label.setText(str(captured))
        self.lost_label.setText(str(lost))

    def attempts_value(self) -> int:
        try:
            return int(self.attempts_label.text())
        except ValueError:
            return 0


class ConnectDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("InvisibleGo - Connect")
        self.setModal(True)
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("Connect to a game server:"))
        form = QFormLayout()
        self.host_edit = QLineEdit("127.0.0.1")
        self.port_edit = QSpinBox()
        self.port_edit.setRange(1, 65535)
        self.port_edit.setValue(5555)
        form.addRow("Host:", self.host_edit)
        form.addRow("Port:", self.port_edit)
        layout.addLayout(form)

        self.host_check = QCheckBox(
            "Also start a local server here (host mode)"
        )
        layout.addWidget(self.host_check)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def values(self) -> tuple[str, int, bool]:
        return (
            self.host_edit.text().strip(),
            self.port_edit.value(),
            self.host_check.isChecked(),
        )
