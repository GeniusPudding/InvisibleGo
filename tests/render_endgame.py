"""PNG renderer for endgame review images.

Each scenario in `tests/test_endgame_scenarios.py` calls `render_endgame()`
which produces a side-by-side image:

    [ position before resolver ]    [ position after dead-stone removal ]

Marked-dead stones are highlighted with a red X in the BEFORE panel; the
AFTER panel shows the scoring board with shaded territory in each color.
"""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.patches as patches
import matplotlib.pyplot as plt
from matplotlib.figure import Figure

from core.board import BOARD_SIZE, Board, Color, Point, neighbors
from core.scoring import area_score

OUTPUT_DIR = Path(__file__).parent / "endgame_images"

_BOARD_BG = "#dcb16a"
_LINE = "#1a1a1a"
_BLACK = "#0a0a0a"
_WHITE = "#fafafa"
_DEAD_MARK = "#d23636"
_BLACK_TERR = "#0a0a0a22"
_WHITE_TERR = "#ffffff66"


def _territory_owners(board: Board) -> dict[Point, Color]:
    """For each empty point, the bordering color (or EMPTY for dame)."""
    out: dict[Point, Color] = {}
    visited: set[Point] = set()
    for p in board.all_points():
        if board.at(p) is not Color.EMPTY or p in visited:
            continue
        region: set[Point] = set()
        borders: set[Color] = set()
        stack = [p]
        while stack:
            q = stack.pop()
            if q in region:
                continue
            region.add(q)
            for n in neighbors(q):
                nc = board.at(n)
                if nc is Color.EMPTY:
                    if n not in region:
                        stack.append(n)
                else:
                    borders.add(nc)
        visited |= region
        owner = (
            Color.BLACK
            if borders == {Color.BLACK}
            else Color.WHITE
            if borders == {Color.WHITE}
            else Color.EMPTY
        )
        for q in region:
            out[q] = owner
    return out


def _draw_board_panel(
    ax,
    board: Board,
    *,
    title: str,
    dead: set[Point] | None = None,
    show_territory: bool = False,
) -> None:
    ax.set_aspect("equal")
    ax.set_xlim(-0.6, BOARD_SIZE - 0.4)
    ax.set_ylim(-0.6, BOARD_SIZE - 0.4)
    ax.invert_yaxis()
    ax.set_xticks([])
    ax.set_yticks([])
    ax.set_title(title, fontsize=11)

    # Wood background.
    ax.add_patch(
        patches.Rectangle(
            (-0.6, -0.6),
            BOARD_SIZE - 0.4 + 0.6,
            BOARD_SIZE - 0.4 + 0.6,
            facecolor=_BOARD_BG,
            edgecolor="none",
            zorder=0,
        )
    )
    # Grid.
    for i in range(BOARD_SIZE):
        ax.plot([0, BOARD_SIZE - 1], [i, i], color=_LINE, lw=0.8, zorder=1)
        ax.plot([i, i], [0, BOARD_SIZE - 1], color=_LINE, lw=0.8, zorder=1)
    # Star points (5 hoshi for 9x9: corners 2/2 + center).
    for r, c in ((2, 2), (2, 6), (4, 4), (6, 2), (6, 6)):
        ax.plot(c, r, marker="o", markersize=4, color=_LINE, zorder=2)

    if show_territory:
        owners = _territory_owners(board)
        for (r, c), owner in owners.items():
            if owner is Color.BLACK:
                ax.add_patch(
                    patches.Rectangle(
                        (c - 0.5, r - 0.5),
                        1,
                        1,
                        facecolor=_BLACK_TERR,
                        edgecolor="none",
                        zorder=1.5,
                    )
                )
            elif owner is Color.WHITE:
                ax.add_patch(
                    patches.Rectangle(
                        (c - 0.5, r - 0.5),
                        1,
                        1,
                        facecolor=_WHITE_TERR,
                        edgecolor="none",
                        zorder=1.5,
                    )
                )

    # Stones.
    for r in range(BOARD_SIZE):
        for c in range(BOARD_SIZE):
            color = board.at((r, c))
            if color is Color.EMPTY:
                continue
            face = _BLACK if color is Color.BLACK else _WHITE
            edge = "#000" if color is Color.BLACK else "#666"
            ax.add_patch(
                patches.Circle(
                    (c, r),
                    0.42,
                    facecolor=face,
                    edgecolor=edge,
                    lw=0.8,
                    zorder=3,
                )
            )

    # Dead-stone mark (red X overlay).
    if dead:
        for r, c in dead:
            ax.plot(
                [c - 0.25, c + 0.25],
                [r - 0.25, r + 0.25],
                color=_DEAD_MARK,
                lw=2.5,
                zorder=5,
            )
            ax.plot(
                [c - 0.25, c + 0.25],
                [r + 0.25, r - 0.25],
                color=_DEAD_MARK,
                lw=2.5,
                zorder=5,
            )

    # Coordinate labels (column letters across top, row numbers along left).
    cols = "ABCDEFGHJ"
    for c in range(BOARD_SIZE):
        ax.text(c, -0.55, cols[c], ha="center", va="bottom", fontsize=8, color="#333")
    for r in range(BOARD_SIZE):
        ax.text(-0.55, r, str(BOARD_SIZE - r), ha="right", va="center", fontsize=8, color="#333")


def render_endgame(
    *,
    name: str,
    title: str,
    before_board: Board,
    dead: set[Point],
    after_board: Board,
    description: str = "",
) -> Path:
    """Render a side-by-side PNG: before (with dead marks) | after (territory + score)."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    score = area_score(after_board)
    winner = score.winner
    if winner is None:
        winner_text = "TIE"
    else:
        winner_text = winner.name

    fig: Figure = plt.figure(figsize=(11, 5.4))
    fig.suptitle(title, fontsize=13, fontweight="bold")

    ax1 = fig.add_subplot(1, 2, 1)
    _draw_board_panel(
        ax1,
        before_board,
        title="Before — proposed dead stones marked",
        dead=dead,
    )

    ax2 = fig.add_subplot(1, 2, 2)
    _draw_board_panel(
        ax2,
        after_board,
        title=f"After — Chinese area scoring",
        show_territory=True,
    )

    score_line = (
        f"BLACK = {score.black}    WHITE = {score.white}    →  winner: {winner_text}"
    )
    fig.text(0.5, 0.06, score_line, ha="center", fontsize=11, family="monospace")
    if description:
        fig.text(
            0.5,
            0.015,
            description,
            ha="center",
            fontsize=8.5,
            color="#444",
            style="italic",
        )

    fig.subplots_adjust(top=0.88, bottom=0.13, left=0.04, right=0.97, wspace=0.10)
    out = OUTPUT_DIR / f"{name}.png"
    fig.savefig(out, dpi=130)
    plt.close(fig)
    return out
