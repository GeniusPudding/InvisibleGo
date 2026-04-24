"""Transport-agnostic game session orchestration.

A GameSession drives a single InvisibleGo game between two Connection
instances. Connections abstract away whether the wire is TCP or WebSocket;
the session only cares about send/recv of JSON-like dicts.

This keeps the hidden-information invariants (no reason field on illegal;
server-side view projection; 3-attempt auto-skip) in one place regardless
of transport.
"""
from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from typing import Any

from core.board import Color
from core.game import GameState, MoveOutcome
from core.scoring import area_score
from protocol.messages import view_to_dict

DEFAULT_TURN_TIMEOUT_SECONDS = 20.0


class Connection(ABC):
    @abstractmethod
    async def send(self, msg: dict[str, Any]) -> None: ...

    @abstractmethod
    async def recv(self) -> dict[str, Any] | None:
        """Return the next message, or None on clean disconnect."""


class GameSession:
    def __init__(
        self,
        black: Connection,
        white: Connection,
        black_name: str = "",
        white_name: str = "",
        turn_timeout_seconds: float = DEFAULT_TURN_TIMEOUT_SECONDS,
    ) -> None:
        self.conns: dict[Color, Connection] = {Color.BLACK: black, Color.WHITE: white}
        self.names: dict[Color, str] = {
            Color.BLACK: black_name,
            Color.WHITE: white_name,
        }
        self.game = GameState()
        self.turn_timeout_seconds = turn_timeout_seconds

    async def run(self) -> None:
        """Drive the game to completion. Sends welcome messages first."""
        await self.conns[Color.BLACK].send(
            {
                "type": "welcome",
                "color": "BLACK",
                "opponent": self.names[Color.WHITE],
            }
        )
        await self.conns[Color.WHITE].send(
            {
                "type": "welcome",
                "color": "WHITE",
                "opponent": self.names[Color.BLACK],
            }
        )

        while not self.game.is_over:
            current = self.game.to_move
            conn = self.conns[current]
            losses = self.game.consume_pending_losses(current)
            await conn.send(
                {
                    "type": "your_turn",
                    "view": view_to_dict(self.game.view(current)),
                    "losses_since_last_turn": losses,
                    "turn_deadline_seconds": self.turn_timeout_seconds,
                }
            )
            cont = await self._handle_turn(current, conn)
            if not cont:
                return

        await self._broadcast_game_end(ended_by="pass", resigner=None)

    async def _handle_turn(self, current: Color, conn: Connection) -> bool:
        """Process input from the current player until their turn ends.

        Returns False if the game must abort (disconnect/resign), True
        otherwise (including normal end-of-game via two passes).

        The 20 s budget is cumulative over all attempts in this turn — an
        opponent who floods illegal moves can't buy extra time.
        """
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.turn_timeout_seconds
        while True:
            remaining = max(0.001, deadline - loop.time())
            try:
                msg = await asyncio.wait_for(conn.recv(), timeout=remaining)
            except asyncio.TimeoutError:
                self.game.pass_turn(current)
                await conn.send({"type": "turn_timeout"})
                return True
            if msg is None:
                await self._broadcast_game_end(ended_by="disconnect", resigner=current)
                return False
            t = msg.get("type")
            if t == "resign":
                await self._broadcast_game_end(ended_by="resign", resigner=current)
                return False
            if t == "pass":
                result = self.game.pass_turn(current)
            elif t == "play":
                r, c = msg.get("row"), msg.get("col")
                if not isinstance(r, int) or not isinstance(c, int):
                    await conn.send(
                        {"type": "error", "message": "play requires integer row/col"}
                    )
                    continue
                result = self.game.play(current, (r, c))
            else:
                await conn.send(
                    {"type": "error", "message": f"unknown command: {t!r}"}
                )
                continue

            if result.outcome is MoveOutcome.ILLEGAL and not result.turn_ended:
                await conn.send(
                    {"type": "illegal", "attempts_remaining": result.attempts_remaining}
                )
                continue

            if result.outcome is MoveOutcome.OK:
                if t == "pass":
                    await conn.send({"type": "passed"})
                else:
                    await conn.send(
                        {"type": "played", "captured": result.captured_count}
                    )
            elif result.outcome is MoveOutcome.ILLEGAL:
                await conn.send({"type": "illegal", "attempts_remaining": 0})

            return True

    async def _broadcast_game_end(self, ended_by: str, resigner: Color | None) -> None:
        score = area_score(self.game.board)
        if ended_by in ("resign", "disconnect") and resigner is not None:
            winner: str | None = resigner.opponent().name
        else:
            w = score.winner
            winner = w.name if w is not None else None
        payload = {
            "type": "game_end",
            "full_board": list(self.game.board.stones),
            "black_score": score.black,
            "white_score": score.white,
            "winner": winner,
            "ended_by": ended_by,
            "resigner": resigner.name if resigner else None,
        }
        for conn in self.conns.values():
            try:
                await conn.send(payload)
            except Exception:
                pass
