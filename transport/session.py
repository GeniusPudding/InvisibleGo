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
from typing import Any, Awaitable, Callable

from core.board import BOARD_SIZE, Color, Point
from core.game import GameState, MoveOutcome
from core.scoring import area_score
from protocol.messages import view_to_dict

DEFAULT_TURN_TIMEOUT_SECONDS = 20.0
DEFAULT_REMATCH_DECISION_SECONDS = 30.0

# Returns the set of points to remove as dead, or None if the resolver
# aborted via disconnect (in which case the resolver itself is expected
# to have already broadcast game_end). Receives the GameSession so it
# can inspect the board, talk to either Connection, or look up names.
# The default implementation is interactive (BLACK proposes, WHITE
# approves); future implementations may plug in automatic life/death
# detection (Benson's algorithm, neural-net inference, etc).
DeadStoneResolver = Callable[["GameSession"], Awaitable["set[Point] | None"]]


async def no_dead_stones(_session: "GameSession") -> set[Point]:
    """Resolver that always returns an empty set — used by tests and
    by transports that don't (yet) implement a marking UI. Production
    transports get the interactive default."""
    return set()


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
        dead_stone_resolver: DeadStoneResolver | None = None,
    ) -> None:
        self.conns: dict[Color, Connection] = {Color.BLACK: black, Color.WHITE: white}
        self.names: dict[Color, str] = {
            Color.BLACK: black_name,
            Color.WHITE: white_name,
        }
        self.game = GameState()
        self.turn_timeout_seconds = turn_timeout_seconds
        # If None, the built-in interactive marker/approver flow runs.
        self.dead_stone_resolver = dead_stone_resolver
        # Set by _broadcast_game_end so callers (e.g. run_match_series) can
        # tell whether a rematch is even possible.
        self.ended_by: str | None = None
        # Populated by the dead-stone marking phase, exposed in game_end
        # so clients can render the removed groups distinctly.
        self.removed_dead: set[Point] = set()

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

        # Loop only exits naturally on two consecutive passes — resign
        # and disconnect already returned early after broadcasting. Now
        # negotiate dead stones before we score.
        if self.dead_stone_resolver is None:
            dead = await self._interactive_dead_resolver()
        else:
            dead = await self.dead_stone_resolver(self)
        if dead is None:
            # Resolver broadcast game_end itself (disconnect during
            # marking). Nothing more for us to do.
            return
        if dead:
            self.removed_dead = set(dead)
            self.game.board = self.game.board.with_stones_removed(self.removed_dead)
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

    async def _interactive_dead_resolver(self) -> set[Point] | None:
        """Default marking flow: BLACK proposes which groups are dead;
        WHITE approves or rejects. On reject, BLACK marks again. Roles
        are stable for now — future iterations could swap on reject or
        accept consensus from either side.

        Returns the set of dead points to remove, or None if either side
        disconnected (game_end already broadcast as 'disconnect').
        """
        marker_color = Color.BLACK
        approver_color = Color.WHITE
        marker = self.conns[marker_color]
        approver = self.conns[approver_color]
        revealed_board = list(self.game.board.stones)

        await marker.send(
            {
                "type": "dead_marking_started",
                "your_role": "marker",
                "full_board": revealed_board,
            }
        )
        await approver.send(
            {
                "type": "dead_marking_started",
                "your_role": "approver",
                "full_board": revealed_board,
            }
        )

        while True:
            msg = await marker.recv()
            if msg is None:
                await self._broadcast_game_end(
                    ended_by="disconnect", resigner=marker_color
                )
                return None
            if msg.get("type") == "mark_dead":
                proposal = self._sanitize_dead_points(msg.get("points") or [])
            else:
                # Defensive — anything other than mark_dead is treated
                # as an empty proposal so the approver can still react.
                proposal = []
            await approver.send(
                {"type": "dead_marking_proposal", "points": proposal}
            )

            decision = await approver.recv()
            if decision is None:
                await self._broadcast_game_end(
                    ended_by="disconnect", resigner=approver_color
                )
                return None
            if (
                decision.get("type") == "mark_decision"
                and decision.get("approve") is True
            ):
                return {(int(r), int(c)) for r, c in proposal}
            # Reject (any other shape is treated as a reject too).
            await marker.send({"type": "dead_marking_rejected"})

    def _sanitize_dead_points(self, raw: Any) -> list[list[int]]:
        """Filter incoming dead-stone proposal: only on-board points
        currently occupied by a stone, deduplicated, in stable order."""
        result: list[list[int]] = []
        seen: set[tuple[int, int]] = set()
        if not isinstance(raw, list):
            return result
        for entry in raw:
            if not isinstance(entry, (list, tuple)) or len(entry) != 2:
                continue
            r, c = entry
            if not (isinstance(r, int) and isinstance(c, int)):
                continue
            if not (0 <= r < BOARD_SIZE and 0 <= c < BOARD_SIZE):
                continue
            if self.game.board.at((r, c)) is Color.EMPTY:
                continue
            if (r, c) in seen:
                continue
            seen.add((r, c))
            result.append([r, c])
        return result

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
            # Full ordered move list — only revealed at game end since the
            # opponent's positions are no longer secret. Each entry is
            # [color_name, row, col].
            "move_history": [
                [c.name, r, col] for (c, (r, col)) in self.game.move_history
            ],
            # Stones agreed-dead during the marking phase (already removed
            # from full_board for scoring). Empty when no stones were
            # marked or when game ended via resign/disconnect.
            "dead_stones": [list(p) for p in sorted(self.removed_dead)],
        }
        self.ended_by = ended_by
        for conn in self.conns.values():
            try:
                await conn.send(payload)
            except Exception:
                pass


async def _await_rematch(conn: Connection, timeout: float) -> bool:
    """Return True iff the client sent a rematch-agree within the timeout.

    Any other message, a decline, a timeout, or a disconnect counts as 'no'.
    """
    try:
        msg = await asyncio.wait_for(conn.recv(), timeout=timeout)
    except asyncio.TimeoutError:
        return False
    if msg is None:
        return False
    return msg.get("type") == "rematch" and bool(msg.get("agree", True))


async def run_match_series(
    black: Connection,
    white: Connection,
    black_name: str = "",
    white_name: str = "",
    turn_timeout_seconds: float = DEFAULT_TURN_TIMEOUT_SECONDS,
    rematch_timeout_seconds: float = DEFAULT_REMATCH_DECISION_SECONDS,
    dead_stone_resolver: DeadStoneResolver | None = None,
) -> None:
    """Play a series of games; after each, offer both sides a rematch.

    When both sides agree, colors are swapped for fairness and a fresh
    GameSession runs. Any other outcome (one declines, one disconnects,
    either times out) ends the series.
    """
    while True:
        session = GameSession(
            black=black,
            white=white,
            black_name=black_name,
            white_name=white_name,
            turn_timeout_seconds=turn_timeout_seconds,
            dead_stone_resolver=dead_stone_resolver,
        )
        await session.run()
        if session.ended_by == "disconnect":
            return
        decisions = await asyncio.gather(
            _await_rematch(black, rematch_timeout_seconds),
            _await_rematch(white, rematch_timeout_seconds),
        )
        if all(decisions):
            # Swap colors so the prior WHITE plays first next round.
            black, white = white, black
            black_name, white_name = white_name, black_name
            continue
        # Notify any side that agreed that the rematch won't happen.
        for conn, agreed in zip((black, white), decisions):
            if agreed:
                try:
                    await conn.send({"type": "rematch_declined"})
                except Exception:
                    pass
        return
