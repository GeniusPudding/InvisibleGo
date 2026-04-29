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
    last_own_move: tuple[int, int] | None = None
    # Tuple of (row, col, move_ordinal) entries, one per currently-visible
    # own stone. Move ordinals are 1-indexed across both colors. Passes
    # are not numbered.
    own_move_numbers: tuple[tuple[int, int, int], ...] = ()

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
    last_own_move: tuple[int, int] | None = None,
    own_move_numbers: dict[tuple[int, int], int] | None = None,
) -> PlayerView:
    own = tuple(
        v if v == perspective.value else Color.EMPTY.value
        for v in board.stones
    )
    # Only surface the marker if the stone is still on the board from the
    # player's perspective (it may have been captured since — in which case
    # showing a marker on an empty point would leak info).
    if last_own_move is not None:
        r, c = last_own_move
        if own[r * BOARD_SIZE + c] != perspective.value:
            last_own_move = None
    numbers_tuple: tuple[tuple[int, int, int], ...] = ()
    if own_move_numbers:
        numbers_tuple = tuple(
            (r, c, n) for (r, c), n in sorted(own_move_numbers.items())
        )
    return PlayerView(
        perspective=perspective,
        to_move=to_move,
        attempts_remaining=attempts_remaining,
        total_captured_by_me=total_captured_by_me,
        total_lost_by_me=total_lost_by_me,
        is_over=is_over,
        own_stones=own,
        last_own_move=last_own_move,
        own_move_numbers=numbers_tuple,
    )
