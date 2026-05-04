"""Tests for Benson's unconditional-life algorithm.

Each scenario builds a 9x9 board from a string diagram and asserts
exactly which stones the algorithm proves alive.

Diagram syntax (one row per line, no spaces):
    .  empty
    B  black stone
    W  white stone
"""
from __future__ import annotations

import pytest

from core.board import BOARD_SIZE, Board, Color, Point
from core.life_death import benson_alive_all, benson_alive_stones


def build_board(diagram: str) -> Board:
    rows = [row.strip() for row in diagram.strip().splitlines()]
    assert len(rows) == BOARD_SIZE, f"need {BOARD_SIZE} rows, got {len(rows)}"
    stones = []
    for r, row in enumerate(rows):
        assert len(row) == BOARD_SIZE, f"row {r} has {len(row)} cols"
        for ch in row:
            if ch == ".":
                stones.append(Color.EMPTY.value)
            elif ch == "B":
                stones.append(Color.BLACK.value)
            elif ch == "W":
                stones.append(Color.WHITE.value)
            else:
                raise ValueError(f"unknown cell {ch!r}")
    return Board(stones=tuple(stones))


def stones_of(board: Board, color: Color) -> set[Point]:
    return {p for p in board.all_points() if board.at(p) is color}


def test_two_eyed_black_group_is_alive():
    """Classic two-eye shape: a black wall with two empty interior
    points each surrounded only by the same black chain."""
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
    alive = benson_alive_stones(board, Color.BLACK)
    assert alive == stones_of(board, Color.BLACK)


def test_one_eye_group_is_not_proven_alive():
    """A single-eye group cannot be Benson-alive — only one vital region."""
    board = build_board(
        """
        .........
        .........
        .........
        .........
        .........
        ..BBBBB..
        ..B...B..
        ..BBBBB..
        .........
        """
    )
    alive = benson_alive_stones(board, Color.BLACK)
    # Single region has 3 empty points, but every one of them has at
    # least one neighbor that is also empty (not adjacent to chain) —
    # so the region isn't "vital". Strict Benson: not alive.
    assert alive == set()


def test_no_eye_group_is_not_alive():
    board = build_board(
        """
        .........
        .........
        .........
        .........
        .........
        ..BBBBB..
        ..BBBBB..
        ..BBBBB..
        .........
        """
    )
    assert benson_alive_stones(board, Color.BLACK) == set()


def test_two_eyes_in_corner():
    """Tiny corner group with two real eyes — cheapest possible alive shape."""
    board = build_board(
        """
        .B.B.....
        BBBB.....
        .........
        .........
        .........
        .........
        .........
        .........
        .........
        """
    )
    alive = benson_alive_stones(board, Color.BLACK)
    assert alive == stones_of(board, Color.BLACK)


def test_dead_white_inside_living_black():
    """A black wall enclosing a single white intrusion stone:
    black is alive, white is not (white has only 1 surrounded liberty
    inside black's territory). Benson proves black; white is just not
    in black's alive set."""
    board = build_board(
        """
        .........
        .........
        .........
        .BBBBBBB.
        .B.....B.
        .B..W..B.
        .B.....B.
        .BBBBBBB.
        .........
        """
    )
    alive_black = benson_alive_stones(board, Color.BLACK)
    alive_white = benson_alive_stones(board, Color.WHITE)
    # Black has a single big region with many empties. Every empty is
    # adjacent to the black chain → vital. But Benson needs TWO vital
    # regions, and there's only one connected enclosed region. So
    # strict Benson cannot prove this big single-eye shape alive.
    # That's the textbook behavior — Benson is conservative.
    assert alive_black == set()
    # White is just one stone with empty neighbors all inside the
    # opponent's territory; obviously not Benson-alive either.
    assert alive_white == set()


def test_two_separate_two_eyed_groups_both_alive():
    """Two independent black groups, each two-eyed — both alive."""
    board = build_board(
        """
        .B.B.....
        BBBB.....
        .........
        .........
        .........
        .........
        .........
        .....BBBB
        .....B.B.
        """
    )
    # Top-left: eyes at (0,0) and (0,2). Bottom-right mirrors it —
    # row 7 BBBB at cols 5..8, row 8 B at 5 and 7, eyes at (8,6) and (8,8).
    alive = benson_alive_stones(board, Color.BLACK)
    assert alive == stones_of(board, Color.BLACK)


def test_both_colors_alive_split_board():
    """Black two-eye top-left + white two-eye bottom-right."""
    board = build_board(
        """
        .B.B.....
        BBBB.....
        .........
        .........
        .........
        .........
        .........
        .....WWWW
        .....W.W.
        """
    )
    alive = benson_alive_all(board)
    assert alive == stones_of(board, Color.BLACK) | stones_of(board, Color.WHITE)


def test_empty_board():
    board = Board.empty()
    assert benson_alive_all(board) == set()


def test_chain_with_two_eyes_carved_out_of_one_region():
    """Single connected black chain, single enclosed region with TWO
    'vital' sub-cavities created by interior black stones — should be
    alive only if the algorithm correctly counts each isolated empty
    cavity as its own region.

    Layout: a 3x5 black block with two single-point eyes carved.
    """
    board = build_board(
        """
        .........
        .........
        .........
        .BBBBB...
        .B.B.B...
        .BBBBB...
        .........
        .........
        .........
        """
    )
    # Eyes at (4,2) and (4,4); each is its own region (separated by
    # the (4,3) black stone that bridges across).
    alive = benson_alive_stones(board, Color.BLACK)
    assert alive == stones_of(board, Color.BLACK)


def test_alive_with_dead_opponent_inside_one_eye():
    """Two-eye black chain where one eye contains an inert white stone.
    Benson considers only empty intersections when checking vitality —
    an opponent stone inside the cavity is ignored (treated as filler).
    Both regions remain vital, so the chain is still alive.
    """
    board = build_board(
        """
        .........
        ..BBBBB..
        ..B...B..
        ..BBBBB..
        ..B.W.B..
        ..BBBBB..
        .........
        .........
        .........
        """
    )
    alive = benson_alive_stones(board, Color.BLACK)
    assert alive == stones_of(board, Color.BLACK)
