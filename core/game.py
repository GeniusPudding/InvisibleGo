"""Game state machine: turn tracking, move validation, capture, ko, attempt counting.

The validation order (opponent-occupied -> own-occupied -> suicide -> ko)
is deliberately hidden from clients. All four rejection cases return the
same generic `ILLEGAL` outcome with no distinguishing field. This is a
load-bearing invariant of the hidden-information design.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from core.board import (
    BOARD_SIZE,
    Board,
    Color,
    Point,
    group_and_liberties,
    neighbors,
)
from core.view import PlayerView, build_view

MAX_ATTEMPTS_PER_TURN = 3


class MoveOutcome(Enum):
    OK = "ok"
    ILLEGAL = "illegal"
    GAME_OVER = "game_over"


@dataclass
class MoveResult:
    outcome: MoveOutcome
    captured_count: int = 0
    attempts_remaining: int = 0
    turn_ended: bool = False


@dataclass
class GameState:
    board: Board = field(default_factory=Board.empty)
    to_move: Color = Color.BLACK
    attempts_remaining: int = MAX_ATTEMPTS_PER_TURN
    history: set[tuple[int, ...]] = field(default_factory=set)
    consecutive_passes: int = 0
    captured_by: dict[Color, int] = field(
        default_factory=lambda: {Color.BLACK: 0, Color.WHITE: 0}
    )
    pending_losses: dict[Color, int] = field(
        default_factory=lambda: {Color.BLACK: 0, Color.WHITE: 0}
    )
    last_move: dict[Color, Point | None] = field(
        default_factory=lambda: {Color.BLACK: None, Color.WHITE: None}
    )
    # Ordered list of every legal play, in execution order. Used to
    # number stones (move ordinals) in views and snapshots. Passes are
    # not recorded.
    move_history: list[tuple[Color, Point]] = field(default_factory=list)
    is_over: bool = False

    def __post_init__(self) -> None:
        self.history.add(self.board.stones)

    def play(self, color: Color, p: Point) -> MoveResult:
        if self.is_over:
            return MoveResult(outcome=MoveOutcome.GAME_OVER)
        if color is not self.to_move:
            return MoveResult(
                outcome=MoveOutcome.ILLEGAL,
                attempts_remaining=self.attempts_remaining,
            )

        r, c = p
        if not (0 <= r < BOARD_SIZE and 0 <= c < BOARD_SIZE):
            return self._record_illegal()
        if self.board.at(p) is not Color.EMPTY:
            return self._record_illegal()

        placed = self.board.with_stone(p, color)
        opp = color.opponent()
        captured: set[Point] = set()
        for n in neighbors(p):
            if placed.at(n) is opp and n not in captured:
                grp, libs = group_and_liberties(placed, n)
                if not libs:
                    captured |= grp
        if captured:
            placed = placed.with_stones_removed(captured)

        _, own_libs = group_and_liberties(placed, p)
        if not own_libs:
            return self._record_illegal()

        if placed.stones in self.history:
            return self._record_illegal()

        self.board = placed
        self.history.add(placed.stones)
        self.captured_by[color] += len(captured)
        self.pending_losses[opp] += len(captured)
        self.consecutive_passes = 0
        self.to_move = opp
        self.attempts_remaining = MAX_ATTEMPTS_PER_TURN
        self.last_move[color] = p
        self.move_history.append((color, p))
        return MoveResult(
            outcome=MoveOutcome.OK,
            captured_count=len(captured),
            attempts_remaining=self.attempts_remaining,
            turn_ended=True,
        )

    def pass_turn(self, color: Color) -> MoveResult:
        if self.is_over:
            return MoveResult(outcome=MoveOutcome.GAME_OVER)
        if color is not self.to_move:
            return MoveResult(
                outcome=MoveOutcome.ILLEGAL,
                attempts_remaining=self.attempts_remaining,
            )
        self._advance_via_pass()
        if self.is_over:
            return MoveResult(outcome=MoveOutcome.GAME_OVER, turn_ended=True)
        return MoveResult(
            outcome=MoveOutcome.OK,
            turn_ended=True,
            attempts_remaining=self.attempts_remaining,
        )

    def consume_pending_losses(self, color: Color) -> int:
        n = self.pending_losses[color]
        self.pending_losses[color] = 0
        return n

    def view(self, perspective: Color) -> PlayerView:
        # For each surviving own stone, the latest move ordinal at which
        # the perspective player placed it. Captures + replays mean the
        # same point can have multiple entries in move_history; later
        # iterations overwrite earlier ones, so the dict ends up holding
        # only the move number that produced the *currently* visible stone.
        own_move_numbers: dict[Point, int] = {}
        for i, (c, p) in enumerate(self.move_history, start=1):
            if c is perspective and self.board.at(p) is perspective:
                own_move_numbers[p] = i
        return build_view(
            board=self.board,
            perspective=perspective,
            to_move=self.to_move,
            attempts_remaining=self.attempts_remaining,
            total_captured_by_me=self.captured_by[perspective],
            total_lost_by_me=self.captured_by[perspective.opponent()],
            is_over=self.is_over,
            last_own_move=self.last_move[perspective],
            own_move_numbers=own_move_numbers,
        )

    def _record_illegal(self) -> MoveResult:
        self.attempts_remaining -= 1
        if self.attempts_remaining <= 0:
            self._advance_via_pass()
            return MoveResult(
                outcome=MoveOutcome.ILLEGAL,
                attempts_remaining=0,
                turn_ended=True,
            )
        return MoveResult(
            outcome=MoveOutcome.ILLEGAL,
            attempts_remaining=self.attempts_remaining,
            turn_ended=False,
        )

    def _advance_via_pass(self) -> None:
        self.history.add(self.board.stones)
        self.consecutive_passes += 1
        if self.consecutive_passes >= 2:
            self.is_over = True
            return
        self.to_move = self.to_move.opponent()
        self.attempts_remaining = MAX_ATTEMPTS_PER_TURN
