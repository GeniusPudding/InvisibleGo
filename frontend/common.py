"""Shared CLI utilities used by the hotseat and LAN clients.

Move parsing, rendering, colour names, and the help text live here so both
the single-process hotseat and the networked LAN client stay byte-identical
in their user-facing strings.
"""
from __future__ import annotations

from typing import Sequence

from core.board import BOARD_SIZE, Color, Point

COLS = "ABCDEFGHJ"  # skip I per Go convention

HELP_TEXT = """
Commands:
  E5 (or any column A-J + row 1-9)  play a stone at that point
  pass                              pass this turn
  resign                            resign the game
  quit                              exit without scoring
  help                              show this text

Rules reminders:
  - You see only your own stones. Empty-looking points may hide an opponent stone.
  - You may try up to 3 moves per turn. Every illegal attempt looks identical:
    the system says ILLEGAL but never tells you why.
  - 3 illegal attempts auto-skip your turn (counts as a pass).
  - Two consecutive passes end the game; Chinese area scoring decides.
""".rstrip()


def parse_command(s: str) -> tuple[str, Point | None]:
    """Parse a user input string.

    Returns (kind, point) where kind is one of: play, pass, resign, quit, help.
    Raises ValueError on malformed input.
    """
    raw = s.strip().lower()
    if raw in ("pass", "p"):
        return ("pass", None)
    if raw in ("resign",):
        return ("resign", None)
    if raw in ("quit", "exit"):
        return ("quit", None)
    if raw in ("help", "h", "?"):
        return ("help", None)
    up = raw.upper()
    if len(up) < 2 or len(up) > 3:
        raise ValueError("Unrecognized input. Type 'help' for commands.")
    col_char = up[0]
    if col_char not in COLS:
        raise ValueError(f"Invalid column '{col_char}'. Use A-J (no I).")
    try:
        row_num = int(up[1:])
    except ValueError:
        raise ValueError(f"Invalid row '{up[1:]}'. Use 1-9.")
    if not (1 <= row_num <= 9):
        raise ValueError(f"Row {row_num} out of range 1-9.")
    col = COLS.index(col_char)
    row = BOARD_SIZE - row_num
    return ("play", (row, col))


def format_point(p: Point) -> str:
    r, c = p
    return f"{COLS[c]}{BOARD_SIZE - r}"


def color_name(c: Color) -> str:
    return "BLACK (X)" if c is Color.BLACK else "WHITE (O)"


def render_board_stones(stones: Sequence[int]) -> str:
    """Render a 9x9 board from a raw stones array (0=empty, 1=black, 2=white).

    The caller pre-filters the array for per-player views (e.g. by zeroing
    out opponent stones). This function renders whatever it is given.
    """
    lines = []
    header = "    " + " ".join(COLS)
    lines.append(header)
    for r in range(BOARD_SIZE):
        row_num = BOARD_SIZE - r
        cells = []
        for c in range(BOARD_SIZE):
            v = stones[r * BOARD_SIZE + c]
            if v == Color.BLACK.value:
                cells.append("X")
            elif v == Color.WHITE.value:
                cells.append("O")
            else:
                cells.append(".")
        lines.append(f" {row_num:>2} " + " ".join(cells) + f"  {row_num}")
    lines.append(header)
    return "\n".join(lines)
