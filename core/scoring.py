"""Chinese area scoring with optional komi.

Komi is a fixed handicap added to white's score to compensate for
black's first-move advantage. On 9x9 this project uses komi 6.5 —
roughly the consensus fair value (KataGo's 9x9 evaluation puts the
black first-move advantage at ~7 points; 6.5 / 7.5 are the standard
half-integer choices that forbid ties). With komi 6.5 black needs at
least 44 area points to win on a fully-resolved board, since
2*44 - 81 = 7 > 6.5 and 2*43 - 81 = 5 < 6.5.
"""
from __future__ import annotations

from dataclasses import dataclass

from core.board import Board, Color, Point, neighbors

DEFAULT_KOMI = 6.5


@dataclass(frozen=True)
class Score:
    black: int            # raw black area (stones + black-only territory)
    white: int            # raw white area
    komi: float = 0.0     # added to white in the win comparison

    @property
    def white_with_komi(self) -> float:
        return self.white + self.komi

    @property
    def winner(self) -> Color | None:
        b = self.black
        w = self.white_with_komi
        if b > w:
            return Color.BLACK
        if w > b:
            return Color.WHITE
        return None


def area_score(board: Board, komi: float = 0.0) -> Score:
    """Chinese area scoring with optional komi.

    Empty regions bordered by a single color count as that color's territory.
    Regions bordered by both colors (dame) are unscored. Pass `komi` to
    bias the winner comparison; raw black/white area counts are unchanged.
    """
    black = 0
    white = 0
    visited: set[Point] = set()
    for p in board.all_points():
        color = board.at(p)
        if color is Color.BLACK:
            black += 1
            continue
        if color is Color.WHITE:
            white += 1
            continue
        if p in visited:
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
        if borders == {Color.BLACK}:
            black += len(region)
        elif borders == {Color.WHITE}:
            white += len(region)
    return Score(black=black, white=white, komi=komi)
