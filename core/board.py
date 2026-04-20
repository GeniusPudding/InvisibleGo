"""Immutable 9x9 board state with group and liberty computation.

No turn tracking, no ko history, no visibility logic. Just the geometry
and the primitive operations needed to compute captures.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Iterator

BOARD_SIZE = 9


class Color(IntEnum):
    EMPTY = 0
    BLACK = 1
    WHITE = 2

    def opponent(self) -> "Color":
        if self is Color.BLACK:
            return Color.WHITE
        if self is Color.WHITE:
            return Color.BLACK
        raise ValueError("EMPTY has no opponent")


Point = tuple[int, int]


@dataclass(frozen=True)
class Board:
    """Immutable 9x9 board. Stones stored as a flat tuple so Board is hashable
    (needed for positional superko tracking)."""

    stones: tuple[int, ...]

    @classmethod
    def empty(cls) -> "Board":
        return cls(stones=tuple(Color.EMPTY.value for _ in range(BOARD_SIZE * BOARD_SIZE)))

    def at(self, p: Point) -> Color:
        r, c = p
        return Color(self.stones[r * BOARD_SIZE + c])

    def with_stone(self, p: Point, color: Color) -> "Board":
        r, c = p
        idx = r * BOARD_SIZE + c
        new = list(self.stones)
        new[idx] = color.value
        return Board(stones=tuple(new))

    def with_stones_removed(self, points: set[Point]) -> "Board":
        if not points:
            return self
        new = list(self.stones)
        for (r, c) in points:
            new[r * BOARD_SIZE + c] = Color.EMPTY.value
        return Board(stones=tuple(new))

    def all_points(self) -> Iterator[Point]:
        for r in range(BOARD_SIZE):
            for c in range(BOARD_SIZE):
                yield (r, c)


def neighbors(p: Point) -> Iterator[Point]:
    r, c = p
    for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        nr, nc = r + dr, c + dc
        if 0 <= nr < BOARD_SIZE and 0 <= nc < BOARD_SIZE:
            yield (nr, nc)


def group_and_liberties(board: Board, start: Point) -> tuple[set[Point], set[Point]]:
    """Return (group stones, liberty points) for the stone at `start`."""
    color = board.at(start)
    if color is Color.EMPTY:
        raise ValueError(f"No stone at {start}")
    group: set[Point] = set()
    liberties: set[Point] = set()
    stack = [start]
    while stack:
        p = stack.pop()
        if p in group:
            continue
        group.add(p)
        for n in neighbors(p):
            nc = board.at(n)
            if nc is Color.EMPTY:
                liberties.add(n)
            elif nc is color and n not in group:
                stack.append(n)
    return group, liberties
