"""Matchmaker: pairs web clients into GameSessions.

Two modes:
  - Random queue: first arrival parks, second pairs with the first.
  - Private rooms: first arrival gets a short code to share, second joins
    by that code.

The first-to-arrive of each pair plays BLACK (arrived earlier, so they
"waited" for the opponent); the second arrival plays WHITE.

The matchmaker is transport-agnostic: it doesn't import FastAPI or
WebSocket. Callers hand it opaque "connection objects" plus a
`session_runner` callable that knows how to run a game given the two
connections. This keeps the matchmaker testable without spinning up a
web server.

MVP limitations (deliberately deferred):
  - No timeout on abandoned rooms / queues. If a creator disconnects
    before their room fills, the entry stays until the process restarts.
  - No reconnect mid-game.
"""
from __future__ import annotations

import asyncio
import secrets
import string
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no I, O, 0, 1
_CODE_LENGTH = 4


def _gen_code() -> str:
    return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(_CODE_LENGTH))


SessionRunner = Callable[[Any, str, Any, str], Awaitable[None]]
# Signature: (black_conn, black_name, white_conn, white_name) -> awaitable


class RoomNotFound(Exception):
    pass


@dataclass
class _Waiter:
    conn: Any
    name: str
    future: "asyncio.Future[asyncio.Event]"


class Matchmaker:
    def __init__(self, session_runner: SessionRunner) -> None:
        self._run = session_runner
        self._lock = asyncio.Lock()
        self._random: _Waiter | None = None
        self._rooms: dict[str, _Waiter] = {}

    async def join_random(self, conn: Any, name: str) -> asyncio.Event:
        """Pair into the random-queue. Returns the game-done event."""
        loop = asyncio.get_running_loop()
        async with self._lock:
            if self._random is None:
                fut: asyncio.Future[asyncio.Event] = loop.create_future()
                self._random = _Waiter(conn=conn, name=name, future=fut)
                mode = "wait"
            else:
                first = self._random
                self._random = None
                mode = "pair"

        if mode == "wait":
            return await fut

        done = asyncio.Event()
        first.future.set_result(done)
        self._spawn_session(
            black=first.conn,
            black_name=first.name,
            white=conn,
            white_name=name,
            done=done,
        )
        return done

    async def create_room(
        self, conn: Any, name: str
    ) -> tuple[str, "asyncio.Future[asyncio.Event]"]:
        """Open a private room and return (code, future-of-done-event).

        The caller is expected to send the code back to the client
        immediately, then `await` the future to get the done event, then
        `await done.wait()` to block until the game ends.
        """
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[asyncio.Event] = loop.create_future()
        async with self._lock:
            while True:
                code = _gen_code()
                if code not in self._rooms:
                    break
            self._rooms[code] = _Waiter(conn=conn, name=name, future=fut)
        return code, fut

    async def join_room(
        self, code: str, conn: Any, name: str
    ) -> asyncio.Event:
        """Join an existing room. Raises RoomNotFound if the code is unknown."""
        async with self._lock:
            waiter = self._rooms.pop(code, None)
        if waiter is None:
            raise RoomNotFound(code)
        done = asyncio.Event()
        waiter.future.set_result(done)
        self._spawn_session(
            black=waiter.conn,
            black_name=waiter.name,
            white=conn,
            white_name=name,
            done=done,
        )
        return done

    def _spawn_session(
        self,
        black: Any,
        black_name: str,
        white: Any,
        white_name: str,
        done: asyncio.Event,
    ) -> None:
        async def _run() -> None:
            try:
                await self._run(black, black_name, white, white_name)
            except Exception:
                # Swallow so the done event still fires; both ws_handler
                # coroutines can return gracefully.
                pass
            finally:
                done.set()

        asyncio.create_task(_run())

    # Exposed for diagnostics / tests
    def pending_counts(self) -> dict[str, int]:
        return {
            "random": 1 if self._random is not None else 0,
            "rooms": len(self._rooms),
        }
