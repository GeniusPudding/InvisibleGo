"""Pure-Python Monte Carlo dead-stone resolver.

Simulates K random eye-respecting playouts from the current position
and labels each stone by majority territorial outcome:
    own-color ownership rate < `threshold`  →  dead.

Inspired by SabakiHQ/deadstones (which uses the same idea in Rust).
Slower than a real engine but has zero external dependencies and is
deterministic given a seed — useful as a CI-friendly fallback and for
testing the resolver pipeline.

Wrap with `benson_safety_filter` to prevent the rare case where a
random playout fails to defend an unconditionally-alive group within
its move budget and labels it dead.
"""
from __future__ import annotations

import random
from typing import TYPE_CHECKING

from core.board import BOARD_SIZE, Board, Color, Point, neighbors
from core.game import GameState, MoveOutcome
from core.resolvers.chain import Resolver
from core.scoring import area_score

if TYPE_CHECKING:
    from transport.session import GameSession


def montecarlo_resolver(
    *,
    playouts: int = 80,
    max_moves_per_playout: int | None = None,
    seed: int | None = None,
    dead_threshold: float = 0.5,
) -> Resolver:
    async def run(session: "GameSession") -> "set[Point] | None":
        return monte_carlo_dead_stones(
            session.game.board,
            to_move=session.game.to_move,
            playouts=playouts,
            max_moves_per_playout=max_moves_per_playout,
            seed=seed,
            dead_threshold=dead_threshold,
        )

    return run


def monte_carlo_dead_stones(
    board: Board,
    *,
    to_move: Color = Color.BLACK,
    playouts: int = 80,
    max_moves_per_playout: int | None = None,
    seed: int | None = None,
    dead_threshold: float = 0.5,
) -> set[Point]:
    """Sync, board-only entry point for tests."""
    rng = random.Random(seed)
    if max_moves_per_playout is None:
        max_moves_per_playout = BOARD_SIZE * BOARD_SIZE * 3

    # Per-point counts: black_owned[i], white_owned[i].
    n_points = BOARD_SIZE * BOARD_SIZE
    black_owned = [0] * n_points
    white_owned = [0] * n_points

    for _ in range(playouts):
        final = _run_playout(
            board, to_move, max_moves_per_playout, rng
        )
        score_board_per_point(final, black_owned, white_owned)

    dead: set[Point] = set()
    for r in range(BOARD_SIZE):
        for c in range(BOARD_SIZE):
            i = r * BOARD_SIZE + c
            color = board.at((r, c))
            if color is Color.EMPTY:
                continue
            own = black_owned[i] if color is Color.BLACK else white_owned[i]
            opp = white_owned[i] if color is Color.BLACK else black_owned[i]
            total = own + opp
            if total == 0:
                continue
            # If the stone's own color held this point in fewer than
            # `dead_threshold` of decisive playouts, call it dead.
            if own / max(1, total) < dead_threshold:
                dead.add((r, c))
    return dead


def _run_playout(
    start: Board, to_move: Color, max_moves: int, rng: random.Random
) -> Board:
    state = GameState(board=start, to_move=to_move)
    consecutive_passes = 0
    moves = 0
    while moves < max_moves and consecutive_passes < 2:
        color = state.to_move
        candidates = _legal_non_eye_candidates(state, color, rng)
        played = False
        for p in candidates:
            res = state.play(color, p)
            if res.outcome is MoveOutcome.OK:
                played = True
                consecutive_passes = 0
                break
        if not played:
            state.pass_turn(color)
            consecutive_passes += 1
        moves += 1
    return state.board


def _legal_non_eye_candidates(
    state: GameState, color: Color, rng: random.Random
) -> list[Point]:
    """Empty points that are NOT obvious own-color eyes, shuffled."""
    points: list[Point] = []
    for r in range(BOARD_SIZE):
        for c in range(BOARD_SIZE):
            p = (r, c)
            if state.board.at(p) is not Color.EMPTY:
                continue
            if _is_simple_eye(state.board, p, color):
                continue
            points.append(p)
    rng.shuffle(points)
    return points


def _is_simple_eye(board: Board, p: Point, color: Color) -> bool:
    """Crude 'true eye' test: all orthogonal neighbors are own color,
    and at most one diagonal is opponent-or-edge.

    Conservative — never flags non-eyes, may miss some real eyes. That
    bias is fine: occasional eye-fills only add noise to the playout
    averages, which we're already averaging over."""
    for n in neighbors(p):
        if board.at(n) is not color:
            return False
    r, c = p
    diag_off = 0
    diag_total = 0
    for dr, dc in ((-1, -1), (-1, 1), (1, -1), (1, 1)):
        nr, nc = r + dr, c + dc
        if not (0 <= nr < BOARD_SIZE and 0 <= nc < BOARD_SIZE):
            diag_off += 1
            continue
        diag_total += 1
        if board.at((nr, nc)) is not color:
            diag_off += 1
    # Corner / edge get a discount: any off-board diagonal is "as bad" as
    # an opponent diagonal. Threshold: at most 1 bad diagonal for an eye
    # interior, 0 for an edge or corner.
    if diag_total == 4:
        return diag_off <= 1
    return diag_off == (4 - diag_total)


def score_board_per_point(
    board: Board, black_counts: list[int], white_counts: list[int]
) -> None:
    """Mutates the count arrays in place: +1 for the owner of each point.

    Empty points surrounded by a single color count as that color's;
    dame and stones count straightforwardly. Mirrors `core.scoring`.
    """
    visited: set[Point] = set()
    for p in board.all_points():
        idx = p[0] * BOARD_SIZE + p[1]
        color = board.at(p)
        if color is Color.BLACK:
            black_counts[idx] += 1
            continue
        if color is Color.WHITE:
            white_counts[idx] += 1
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
            for q in region:
                black_counts[q[0] * BOARD_SIZE + q[1]] += 1
        elif borders == {Color.WHITE}:
            for q in region:
                white_counts[q[0] * BOARD_SIZE + q[1]] += 1
