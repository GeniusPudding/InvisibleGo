"""Resolver chain + Benson safety filter + Monte Carlo tests."""
from __future__ import annotations

import asyncio
from typing import Any

import pytest

from core.board import Color, Point
from core.life_death import benson_alive_all
from core.resolvers import (
    EngineUnavailable,
    benson_safety_filter,
    chained,
    montecarlo_resolver,
)
from core.resolvers.gtp import gtp_to_point, point_to_gtp
from core.resolvers.gnugo import _parse_dead_list
from core.resolvers.katago import _parse_ownership
from core.resolvers.montecarlo import monte_carlo_dead_stones
from tests.test_benson import build_board, stones_of


class _SessionStub:
    """Minimal stand-in for GameSession.dead_stone_resolver consumers.

    A real session also exposes connections; resolvers used in this
    suite never touch them, so we only carry `game` (with `board` and
    `to_move`)."""

    def __init__(self, board, to_move=Color.BLACK):
        from core.game import GameState

        self.game = GameState(board=board, to_move=to_move)


# --- chained ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_chained_falls_through_on_engine_unavailable():
    async def first(_session) -> set[Point]:
        raise EngineUnavailable("first missing")

    async def second(_session) -> set[Point]:
        return {(0, 0)}

    resolver = chained(first, second)
    result = await resolver(_SessionStub(build_board("\n".join(["." * 9] * 9))))
    assert result == {(0, 0)}


@pytest.mark.asyncio
async def test_chained_propagates_unrelated_errors():
    async def boom(_session) -> set[Point]:
        raise RuntimeError("not an EngineUnavailable")

    async def fallback(_session) -> set[Point]:
        return set()

    resolver = chained(boom, fallback)
    with pytest.raises(RuntimeError):
        await resolver(_SessionStub(build_board("\n".join(["." * 9] * 9))))


@pytest.mark.asyncio
async def test_chained_raises_when_all_unavailable():
    async def a(_session):
        raise EngineUnavailable("a")

    async def b(_session):
        raise EngineUnavailable("b")

    resolver = chained(a, b)
    with pytest.raises(EngineUnavailable):
        await resolver(_SessionStub(build_board("\n".join(["." * 9] * 9))))


@pytest.mark.asyncio
async def test_chained_short_circuits_on_none():
    """Resolver returning None means it handled disconnect; don't try
    fallbacks after game_end has been broadcast."""

    async def hit(_session):
        return None

    async def never_called(_session):
        raise AssertionError("should not run after None")

    resolver = chained(hit, never_called)
    result = await resolver(_SessionStub(build_board("\n".join(["." * 9] * 9))))
    assert result is None


# --- benson_safety_filter --------------------------------------------------


@pytest.mark.asyncio
async def test_benson_filter_vetoes_alive_group():
    """A NN-style resolver mistakenly proposes a stone of a clearly
    pass-alive black group as dead. The filter must drop it."""
    board = build_board(
        """
        .........
        .........
        .........
        .........
        .........
        ..BBBBB..
        ..B.B.B..
        ..BBBBB..
        .........
        """
    )

    async def buggy(_session) -> set[Point]:
        # Single stone of the alive group.
        return {(5, 2)}

    filtered = benson_safety_filter(buggy)
    result = await filtered(_SessionStub(board))
    assert result == set()


@pytest.mark.asyncio
async def test_benson_filter_passes_through_truly_dead_proposal():
    """Filter should NOT veto a proposal that targets a stone in a
    chain Benson cannot prove alive."""
    board = build_board(
        """
        .........
        .BBBBBBB.
        .B.....B.
        .B..W..B.
        .B.....B.
        .B.....B.
        .B.....B.
        .BBBBBBB.
        .........
        """
    )
    # Black is *not* Benson-alive (single big region, only 1 vital). White
    # is just a lone intrusion stone, also not alive. So Benson's alive
    # set is empty and any proposal passes through unchanged.
    assert benson_alive_all(board) == set()

    async def kill_white(_session) -> set[Point]:
        return {(3, 4)}

    filtered = benson_safety_filter(kill_white)
    result = await filtered(_SessionStub(board))
    assert result == {(3, 4)}


@pytest.mark.asyncio
async def test_benson_filter_drops_whole_group_if_any_stone_alive():
    """If a NN flags ONE stone of an alive 12-stone dragon as dead,
    the filter drops the entire flagged-group, not just one stone —
    otherwise we'd kill 11 friends."""
    board = build_board(
        """
        .........
        .........
        .........
        .........
        .........
        ..BBBBB..
        ..B.B.B..
        ..BBBBB..
        .........
        """
    )

    async def chaos(_session) -> set[Point]:
        # Multiple stones from the alive black chain.
        return {(5, 2), (5, 6), (7, 4)}

    filtered = benson_safety_filter(chaos)
    assert await filtered(_SessionStub(board)) == set()


# --- GTP coordinate helpers ------------------------------------------------


def test_gtp_point_roundtrip():
    # 9x9 layout: (row 0, col 0) is the top-left, GTP A9; bottom-right is J1.
    assert point_to_gtp((0, 0)) == "A9"
    assert point_to_gtp((8, 8)) == "J1"
    assert point_to_gtp((4, 4)) == "E5"
    for r in range(9):
        for c in range(9):
            assert gtp_to_point(point_to_gtp((r, c))) == (r, c)


# --- GTP response parsers --------------------------------------------------


def test_parse_gnugo_dead_list_basic():
    body = "A9 J1 E5"
    assert _parse_dead_list(body) == {(0, 0), (8, 8), (4, 4)}


def test_parse_gnugo_dead_list_empty():
    assert _parse_dead_list("") == set()


def test_parse_gnugo_dead_list_ignores_garbage():
    assert _parse_dead_list("A9 something_bad J1") == {(0, 0), (8, 8)}


def test_parse_katago_ownership_picks_first_block():
    # Synthetic kata-analyze response: first 81 floats are real ownership,
    # second 81 are dummy. Parser should pick the first block.
    own1 = [0.0] * 81
    own1[0] = 0.95   # top-left strongly black
    own1[80] = -0.95  # bottom-right strongly white
    body = (
        "info move A1 visits 100 winrate 0.5 ownership "
        + " ".join(f"{v:.4f}" for v in own1)
    )
    parsed = _parse_ownership(body)
    assert parsed is not None
    assert len(parsed) == 81
    assert parsed[0] == pytest.approx(0.95)
    assert parsed[80] == pytest.approx(-0.95)


def test_parse_katago_ownership_missing_returns_none():
    assert _parse_ownership("info move A1 visits 100 winrate 0.5") is None
    assert _parse_ownership("ownership 0.1 0.2") is None  # too few


# --- Monte Carlo (deterministic with seed) ---------------------------------


def test_monte_carlo_kills_lone_intrusion_in_clear_territory():
    """A solitary white stone surrounded by living black territory
    must be flagged dead by enough random playouts.

    With max_moves=200 and 60 playouts, this position settles cleanly
    in well under the move budget and the lone white dies in nearly
    every playout."""
    board = build_board(
        """
        .........
        .BBBBBBB.
        .B.....B.
        .B..W..B.
        .B.....B.
        .B.....B.
        .B.....B.
        .BBBBBBB.
        .........
        """
    )
    dead = monte_carlo_dead_stones(
        board, to_move=Color.WHITE, playouts=60, seed=42, dead_threshold=0.5
    )
    assert (3, 4) in dead


def test_monte_carlo_does_not_kill_alive_two_eye_group():
    """A textbook two-eye group must NOT be flagged dead.

    The Benson filter would catch this anyway, but Monte Carlo by
    itself should already get this right on a clean position."""
    board = build_board(
        """
        .........
        .........
        .........
        .........
        .........
        ..BBBBB..
        ..B.B.B..
        ..BBBBB..
        .........
        """
    )
    dead = monte_carlo_dead_stones(
        board, to_move=Color.WHITE, playouts=60, seed=7, dead_threshold=0.5
    )
    alive_stones = stones_of(board, Color.BLACK)
    assert dead.isdisjoint(alive_stones)


@pytest.mark.asyncio
async def test_montecarlo_with_benson_safety_endtoend():
    """End-to-end: a flaky Monte Carlo run on top of Benson filter
    cannot kill a Benson-alive group, even with low playouts."""
    board = build_board(
        """
        .........
        .........
        .........
        .........
        .........
        ..BBBBB..
        ..B.B.B..
        ..BBBBB..
        .........
        """
    )
    resolver = benson_safety_filter(
        montecarlo_resolver(playouts=10, seed=999, dead_threshold=0.5)
    )
    result = await resolver(_SessionStub(board, to_move=Color.WHITE))
    assert result == set()
