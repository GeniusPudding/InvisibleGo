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

    def set_stones(self, stones) -> None:
        self._stones = list(stones)
        self.update()

    def place_stone(self, r: int, c: int, color: int) -> None:
        """Locally add a stone to the displayed board.

        Used for optimistic rendering of the player's own move the moment
        the server acknowledges it, so the stone shows up without waiting
        for the next `your_turn` view.
        """
        self._stones[r * BOARD_SIZE + c] = color
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
        if not self._my_turn or ev.button() != Qt.LeftButton:
            return
        pos = self._pixel_to_intersection(ev.position())
        if pos is not None:
            self.intersection_clicked.emit(*pos)


class SidePanel(QWidget):
    pass_clicked = Signal()
    resign_clicked = Signal()

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
        button_row.addWidget(self.pass_btn)
        button_row.addWidget(self.resign_btn)
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
