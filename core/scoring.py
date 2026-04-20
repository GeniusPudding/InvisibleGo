"""Chinese area scoring: own stones + empty regions surrounded only by own color."""
from __future__ import annotations

from dataclasses import dataclass

from core.board import Board, Color, Point, neighbors


@dataclass(frozen=True)
class Score:
    black: int
    white: int

    @property
    def winner(self) -> Color | None:
        if self.black > self.white:
            return Color.BLACK
        if self.white > self.black:
            return Color.WHITE
        return None


def area_score(board: Board) -> Score:
    """Chinese area scoring, no komi.

    Empty regions bordered by a single color count as that color's territory.
    Regions bordered by both colors (dame) are unscored.
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
    return Score(black=black, white=white)
