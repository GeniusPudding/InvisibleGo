"""Benson safety filter.

Wraps another resolver and removes from its dead-stone proposal any
stone belonging to a Benson-unconditionally-alive chain. The whole
chain is veto'd, not just the proposed point — if a NN flags one stone
of a 12-stone alive dragon, we don't want to kill 11 friends and keep
1 enemy mistake.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from core.board import Color, Point, group_and_liberties
from core.life_death import benson_alive_all
from core.resolvers.chain import Resolver

if TYPE_CHECKING:
    from transport.session import GameSession


def benson_safety_filter(inner: Resolver) -> Resolver:
    """Return a resolver that runs `inner` and then strips out any
    point belonging to a Benson-alive chain."""

    async def run(session: "GameSession") -> "set[Point] | None":
        proposal = await inner(session)
        if proposal is None or not proposal:
            return proposal
        board = session.game.board
        alive = benson_alive_all(board)
        # Kill an entire group only if no stone of that group is Benson-alive.
        # If any stone of the group is alive, drop the whole group from the
        # dead set.
        safe_to_kill: set[Point] = set()
        seen: set[Point] = set()
        for p in proposal:
            if p in seen:
                continue
            color = board.at(p)
            if color is Color.EMPTY:
                continue
            group, _ = group_and_liberties(board, p)
            seen |= group
            if group & alive:
                # Some stone in this group is provably alive — veto.
                continue
            # Only mark stones that the inner resolver actually proposed.
            safe_to_kill |= group & proposal
        return safe_to_kill

    return run
