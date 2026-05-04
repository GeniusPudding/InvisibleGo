"""GNU Go-backed resolver.

GNU Go has been the reference open-source life/death engine for two
decades. We talk to it over GTP and ask `final_status_list dead`.

Usage:
    from core.resolvers import gnugo_resolver, benson_safety_filter
    resolver = benson_safety_filter(gnugo_resolver())
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from core.board import Point
from core.resolvers.chain import EngineUnavailable, Resolver
from core.resolvers.gtp import GtpEngine, GtpProtocolError, gtp_to_point

if TYPE_CHECKING:
    from transport.session import GameSession


def gnugo_resolver(
    binary: str = "gnugo",
    *,
    extra_args: tuple[str, ...] = ("--mode", "gtp", "--level", "10"),
    komi: float = 7.5,
) -> Resolver:
    async def run(session: "GameSession") -> "set[Point] | None":
        try:
            async with GtpEngine([binary, *extra_args]) as engine:
                await engine.setup_board(session.game.board, komi=komi)
                response = await engine.command("final_status_list dead")
        except GtpProtocolError as e:
            raise EngineUnavailable(f"gnugo protocol error: {e}") from e
        return _parse_dead_list(response)

    return run


def _parse_dead_list(body: str) -> set[Point]:
    dead: set[Point] = set()
    for token in body.split():
        try:
            dead.add(gtp_to_point(token))
        except (ValueError, IndexError):
            continue
    return dead
