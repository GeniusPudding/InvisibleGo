"""Resolver chain helpers and the EngineUnavailable signal.

A resolver that depends on an external binary (KataGo, GNU Go, ...) raises
`EngineUnavailable` when the binary is missing or fails to start. The
`chained` wrapper catches it and tries the next resolver. Anything else
propagates — a misbehaving engine should not silently fall through.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Awaitable, Callable

if TYPE_CHECKING:
    from core.board import Point
    from transport.session import GameSession

Resolver = Callable[["GameSession"], Awaitable["set[Point] | None"]]


class EngineUnavailable(RuntimeError):
    """Raised by an engine-backed resolver when its dependency is missing.
    Treated as 'fall through to next resolver' by `chained`."""


def chained(*resolvers: Resolver) -> Resolver:
    """Try resolvers in order. First one that doesn't raise wins.

    Resolver returning None (resolver-handled disconnect) short-circuits
    the chain and propagates None — we don't try a fallback after the
    session has already broadcast game_end.
    """
    if not resolvers:
        raise ValueError("chained() needs at least one resolver")

    async def run(session: "GameSession") -> "set[Point] | None":
        last_error: Exception | None = None
        for r in resolvers:
            try:
                return await r(session)
            except EngineUnavailable as e:
                last_error = e
                continue
        # Every resolver was unavailable. Surface the last cause; the
        # caller (transport.session) will fall back to the interactive
        # marker/approver flow if it catches this.
        raise EngineUnavailable(
            f"no resolver in the chain was available; last error: {last_error}"
        )

    return run
