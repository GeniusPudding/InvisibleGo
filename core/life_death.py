"""Benson's algorithm: find unconditionally-alive chains.

A chain is unconditionally alive if it has at least two distinct
"X-enclosed regions" each of which is "vital" to the chain — meaning
every empty point in the region is adjacent to a stone of the chain.
Such a chain cannot be killed even if the opponent is given infinitely
many consecutive moves and the chain's owner only passes.

This module produces *guarantees of life*, not death. It cannot tell
you whether a stone is dead — only whether it is provably alive. We
use it as a safety filter on top of less-rigorous detectors (Monte
Carlo playouts, neural-net ownership maps): if a detector wants to
mark a chain dead but Benson proves it alive, we override the
detector. This catches the well-known KataGo failure mode where the
ownership map occasionally flags a pass-alive group as dead.

Reference: Benson 1976, "Life in the Game of Go".
"""
from __future__ import annotations

from core.board import Board, Color, Point, group_and_liberties, neighbors


def benson_alive_stones(board: Board, color: Color) -> set[Point]:
    """All stones of `color` that are unconditionally alive (Benson)."""
    chains, point_to_chain = _find_chains(board, color)
    if not chains:
        return set()
    regions = _find_enclosed_regions(board, color, point_to_chain)

    alive: set[int] = set(range(len(chains)))
    while True:
        vital_count: dict[int, int] = {c: 0 for c in alive}
        for region in regions:
            # Drop regions whose boundary touches a chain we already
            # rejected — they no longer count toward anyone.
            if not region.boundary_chains.issubset(alive):
                continue
            for c in region.boundary_chains:
                if _region_is_vital_to(region, c, point_to_chain):
                    vital_count[c] += 1
        next_alive = {c for c in alive if vital_count[c] >= 2}
        if next_alive == alive:
            break
        alive = next_alive

    result: set[Point] = set()
    for c in alive:
        result |= chains[c]
    return result


def benson_alive_all(board: Board) -> set[Point]:
    """Union of unconditionally-alive stones for both colors."""
    return benson_alive_stones(board, Color.BLACK) | benson_alive_stones(
        board, Color.WHITE
    )


# Internal -------------------------------------------------------------------


class _Region:
    __slots__ = ("points", "empties", "boundary_chains")

    def __init__(
        self,
        points: frozenset[Point],
        empties: frozenset[Point],
        boundary_chains: frozenset[int],
    ) -> None:
        self.points = points
        self.empties = empties
        self.boundary_chains = boundary_chains


def _find_chains(
    board: Board, color: Color
) -> tuple[list[frozenset[Point]], dict[Point, int]]:
    chains: list[frozenset[Point]] = []
    point_to_chain: dict[Point, int] = {}
    for p in board.all_points():
        if board.at(p) is not color or p in point_to_chain:
            continue
        grp, _ = group_and_liberties(board, p)
        idx = len(chains)
        frozen = frozenset(grp)
        chains.append(frozen)
        for q in frozen:
            point_to_chain[q] = idx
    return chains, point_to_chain


def _find_enclosed_regions(
    board: Board, color: Color, point_to_chain: dict[Point, int]
) -> list[_Region]:
    """Maximal connected components of (empty + opponent) points.

    By construction every such region is X-enclosed: any neighbor of
    a region point that lies outside the region is a stone of `color`.
    The board edge counts as a closure too — Benson treats the edge
    as if it were a wall of the surrounding color. Region "boundary
    chains" is the set of `color` chain indices touching the region.
    """
    regions: list[_Region] = []
    visited: set[Point] = set()
    for p in board.all_points():
        if board.at(p) is color or p in visited:
            continue
        region_points: set[Point] = set()
        boundary: set[int] = set()
        stack = [p]
        while stack:
            q = stack.pop()
            if q in region_points:
                continue
            region_points.add(q)
            for n in neighbors(q):
                nc = board.at(n)
                if nc is color:
                    boundary.add(point_to_chain[n])
                elif n not in region_points:
                    stack.append(n)
        visited |= region_points
        empties = frozenset(q for q in region_points if board.at(q) is Color.EMPTY)
        regions.append(
            _Region(
                points=frozenset(region_points),
                empties=empties,
                boundary_chains=frozenset(boundary),
            )
        )
    return regions


def _region_is_vital_to(
    region: _Region, chain_idx: int, point_to_chain: dict[Point, int]
) -> bool:
    """Vital = every empty point in the region is adjacent to a stone
    belonging to chain `chain_idx`."""
    for e in region.empties:
        if not any(point_to_chain.get(n) == chain_idx for n in neighbors(e)):
            return False
    return True
