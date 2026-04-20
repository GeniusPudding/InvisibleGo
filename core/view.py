"""Per-player view: the visibility-safe projection of a Board.

A PlayerView shows only the perspective player's own stones. Opponent
stones are rendered as empty points so the player cannot distinguish
"truly empty" from "opponent-occupied".
"""
from __future__ import annotations

from dataclasses import dataclass

from core.board import BOARD_SIZE, Board, Color, Point


@dataclass(frozen=True)
class PlayerView:
    perspective: Color
    to_move: Color
    attempts_remaining: int
    total_captured_by_me: int
    total_lost_by_me: int
    is_over: bool
    own_stones: tuple[int, ...]

    def at(self, p: Point) -> Color | None:
        """Own color if the player has a stone at p, else None.

        None means "empty-from-my-perspective" and deliberately conflates
        genuinely empty with opponent-occupied.
        """
        r, c = p
        v = self.own_stones[r * BOARD_SIZE + c]
        return Color(v) if v != Color.EMPTY.value else None


def build_view(
    board: Board,
    perspective: Color,
    to_move: Color,
    attempts_remaining: int,
    total_captured_by_me: int,
    total_lost_by_me: int,
    is_over: bool,
) -> PlayerView:
    own = tuple(
        v if v == perspective.value else Color.EMPTY.value
        for v in board.stones
    )
    return PlayerView(
        perspective=perspective,
        to_move=to_move,
        attempts_remaining=attempts_remaining,
        total_captured_by_me=total_captured_by_me,
        total_lost_by_me=total_lost_by_me,
        is_over=is_over,
        own_stones=own,
    )
