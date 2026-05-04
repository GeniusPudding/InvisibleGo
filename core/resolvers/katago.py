"""KataGo-backed resolver.

We use KataGo's `kata-analyze` GTP extension to obtain a per-point
ownership map, then label any stone whose own-color ownership is
below `dead_threshold` as dead.

KataGo can occasionally label a Benson-pass-alive group as dead
(see lightvector/KataGo issue #773). Always wrap this resolver with
`benson_safety_filter` in production.

Usage:
    from core.resolvers import katago_resolver, benson_safety_filter
    resolver = benson_safety_filter(katago_resolver(
        binary="katago",
        config="default_gtp.cfg",
        model="kata1-b6c96-s175395328-d26788732.bin.gz",
    ))
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from core.board import BOARD_SIZE, Color, Point
from core.resolvers.chain import EngineUnavailable, Resolver
from core.resolvers.gtp import GtpEngine, GtpProtocolError

if TYPE_CHECKING:
    from transport.session import GameSession


def katago_resolver(
    binary: str = "katago",
    *,
    config: str | None = None,
    model: str | None = None,
    extra_args: tuple[str, ...] = (),
    visits: int = 50,
    dead_threshold: float = 0.5,
    komi: float = 7.5,
) -> Resolver:
    """Build a KataGo resolver.

    `visits` — visits per analysis call. 50 is plenty for a 9x9 final
    position; raising it doesn't materially change ownership.
    `dead_threshold` — magnitude of opponent-ownership above which a
    stone is judged dead. KataGo ownership is signed [-1, +1] from
    the perspective of the player to move; we re-sign per stone color.
    """
    argv: list[str] = [binary]
    if config is None and model is None:
        argv.append("gtp")
    else:
        argv.append("gtp")
        if config is not None:
            argv += ["-config", config]
        if model is not None:
            argv += ["-model", model]
    argv += list(extra_args)

    async def run(session: "GameSession") -> "set[Point] | None":
        board = session.game.board
        try:
            async with GtpEngine(argv, startup_timeout=15.0, command_timeout=60.0) as engine:
                await engine.setup_board(board, komi=komi)
                # Trigger a single analysis pass with ownership output.
                response = await engine.command(
                    f"kata-analyze interval 0 maxmoves 1 ownership true minmoves 1"
                    if False
                    else f"kata-analyze {visits} ownership true",
                    timeout=120.0,
                )
        except GtpProtocolError as e:
            raise EngineUnavailable(f"katago protocol error: {e}") from e
        ownership = _parse_ownership(response)
        if ownership is None:
            raise EngineUnavailable("katago response had no ownership block")
        # KataGo's ownership is from the perspective of the side to
        # move. We don't care: a positive value means "owned by player
        # to move". To classify a stone we just look at sign vs the
        # player to move.
        to_move = session.game.to_move
        dead: set[Point] = set()
        for r in range(BOARD_SIZE):
            for c in range(BOARD_SIZE):
                color = board.at((r, c))
                if color is Color.EMPTY:
                    continue
                # Positive ownership means `to_move` owns it.
                # If color == to_move and ownership < -threshold → dead.
                # If color != to_move and ownership > threshold → dead.
                own = ownership[r * BOARD_SIZE + c]
                if color is to_move and own < -dead_threshold:
                    dead.add((r, c))
                elif color is not to_move and own > dead_threshold:
                    dead.add((r, c))
        return dead

    return run


def _parse_ownership(body: str) -> list[float] | None:
    """Pull the `ownership` block out of a `kata-analyze` response.

    Format from KataGo: lines like
      info move XX visits N ... ownership o1 o2 ... oN
    The ownership values appear in board-row-major order from the
    *engine's* perspective (top-left first). We just read the first
    `ownership` we see.
    """
    needed = BOARD_SIZE * BOARD_SIZE
    for line in body.splitlines():
        idx = line.find("ownership ")
        if idx < 0:
            continue
        tail = line[idx + len("ownership ") :].strip()
        parts = tail.split()
        floats: list[float] = []
        for tok in parts:
            try:
                floats.append(float(tok))
            except ValueError:
                break
            if len(floats) >= needed:
                break
        if len(floats) >= needed:
            return floats[:needed]
    return None
