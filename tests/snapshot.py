"""SVG board snapshot renderer for full-game tests.

Each scripted test in `tests/test_full_game.py` calls `write_snapshot()`
on success, producing `tests/snapshots/<test_name>.svg` — a static image
of the final position with stones numbered by play order.

This is a debugging aid, not a test in itself: open any `.svg` file in a
browser to see the endgame the engine actually produced (own + opponent
stones, since by the time game_end fires the full board is revealed).
The output is deliberately self-contained — no external CSS, no fonts
beyond the system default — so the file works opened in any browser
without the project's web frontend.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable

from core.board import BOARD_SIZE, Color

SNAPSHOTS_DIR = Path(__file__).parent / "snapshots"

_CELL = 56
_PAD = 28
_SVG_SIZE = _PAD * 2 + (BOARD_SIZE - 1) * _CELL
_STONE_R = _CELL * 0.45
_STAR_POINTS = ((2, 2), (2, 6), (4, 4), (6, 2), (6, 6))
_COLS = "ABCDEFGHJ"


def _xy(r: int, c: int) -> tuple[float, float]:
    return (_PAD + c * _CELL, _PAD + r * _CELL)


def render_board_svg(
    stones: Iterable[int],
    move_history: Iterable[tuple[Color, tuple[int, int]]],
    title: str = "",
    score_line: str = "",
) -> str:
    """Build an SVG string showing every stone with its move ordinal.

    `stones`: 81-int iterable matching `Board.stones` (0/1/2 = empty/black/white).
    `move_history`: iterable of (color, (row, col)) entries in play order.
                    Captured-and-replayed positions correctly show the
                    latest ordinal because dict assignment overwrites.
    """
    stones = list(stones)
    # Map currently-occupied points to their latest move number.
    numbers: dict[tuple[int, int], int] = {}
    for i, (c, p) in enumerate(move_history, start=1):
        idx = p[0] * BOARD_SIZE + p[1]
        if 0 <= idx < len(stones) and stones[idx] == c.value:
            numbers[p] = i

    parts: list[str] = []
    parts.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{_SVG_SIZE}" height="{_SVG_SIZE + 60}" '
        f'viewBox="0 0 {_SVG_SIZE} {_SVG_SIZE + 60}" '
        f'font-family="Consolas, Menlo, monospace">'
    )
    parts.append(f'<rect width="{_SVG_SIZE}" height="{_SVG_SIZE}" fill="#d9b26a"/>')

    # Grid + star points.
    for i in range(BOARD_SIZE):
        x = _PAD + i * _CELL
        y = _PAD + i * _CELL
        end = _PAD + (BOARD_SIZE - 1) * _CELL
        parts.append(
            f'<line x1="{_PAD}" y1="{y}" x2="{end}" y2="{y}" stroke="#1a1a1a" stroke-width="1.2"/>'
        )
        parts.append(
            f'<line x1="{x}" y1="{_PAD}" x2="{x}" y2="{end}" stroke="#1a1a1a" stroke-width="1.2"/>'
        )
    for r, c in _STAR_POINTS:
        x, y = _xy(r, c)
        parts.append(f'<circle cx="{x}" cy="{y}" r="3" fill="#1a1a1a"/>')

    # Coordinate labels.
    for c in range(BOARD_SIZE):
        x, _ = _xy(0, c)
        parts.append(
            f'<text x="{x}" y="{_PAD - 10}" text-anchor="middle" '
            f'font-size="11" fill="#444">{_COLS[c]}</text>'
        )
    for r in range(BOARD_SIZE):
        _, y = _xy(r, 0)
        parts.append(
            f'<text x="{_PAD - 14}" y="{y + 4}" text-anchor="middle" '
            f'font-size="11" fill="#444">{BOARD_SIZE - r}</text>'
        )

    # Stones + move numbers.
    for r in range(BOARD_SIZE):
        for c in range(BOARD_SIZE):
            v = stones[r * BOARD_SIZE + c]
            if v == 0:
                continue
            x, y = _xy(r, c)
            fill = "#111" if v == Color.BLACK.value else "#f8f8f8"
            stroke = "#000" if v == Color.BLACK.value else "#666"
            parts.append(
                f'<circle cx="{x}" cy="{y}" r="{_STONE_R}" fill="{fill}" '
                f'stroke="{stroke}" stroke-width="1"/>'
            )
            n = numbers.get((r, c))
            if n is not None:
                text_color = "#fff" if v == Color.BLACK.value else "#000"
                parts.append(
                    f'<text x="{x}" y="{y + 4}" text-anchor="middle" '
                    f'font-size="14" font-weight="bold" '
                    f'fill="{text_color}">{n}</text>'
                )

    # Title + score footer.
    footer_y = _SVG_SIZE + 20
    if title:
        parts.append(
            f'<text x="{_PAD}" y="{footer_y}" font-size="12" fill="#222" '
            f'font-weight="bold">{_xml_escape(title)}</text>'
        )
    if score_line:
        parts.append(
            f'<text x="{_PAD}" y="{footer_y + 22}" font-size="11" '
            f'fill="#444">{_xml_escape(score_line)}</text>'
        )

    parts.append("</svg>")
    return "\n".join(parts)


def _xml_escape(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def write_snapshot(
    name: str,
    stones: Iterable[int],
    move_history: Iterable[tuple[Color, tuple[int, int]]],
    score_line: str = "",
) -> Path:
    """Render `stones` to `tests/snapshots/<name>.svg` and return the path."""
    SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    svg = render_board_svg(stones, move_history, title=name, score_line=score_line)
    path = SNAPSHOTS_DIR / f"{name}.svg"
    path.write_text(svg, encoding="utf-8")
    return path
