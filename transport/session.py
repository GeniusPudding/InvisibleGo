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
import logging
from abc import ABC, abstractmethod
from typing import Any, Awaitable, Callable

from core.board import BOARD_SIZE, Color, Point
from core.game import GameState, MoveOutcome
from core.resolvers.chain import EngineUnavailable
from core.scoring import DEFAULT_KOMI, area_score
from protocol.messages import view_to_dict

log = logging.getLogger("invisiblego.session")

# Free-form chat: clamped server-side; never trusted from client.
MAX_CHAT_LEN = 200

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


class _BufferedConnection(Connection):
    """Wraps another Connection with a single-ended pushback list.

    GameSession's inbound reader task is greedy — it can consume a
    rematch message off the wire before the per-game loop is done.
    Wrapping the underlying connection in this buffered layer lets the
    session push any unread messages back onto the front of the read
    stream before tearing down, so the next recv() (e.g. from
    `_await_rematch`) sees them in their original order.
    """

    def __init__(self, inner: Connection) -> None:
        self._inner = inner
        self._pushback: list[dict[str, Any] | None] = []

    async def send(self, msg: dict[str, Any]) -> None:
        await self._inner.send(msg)

    async def recv(self) -> dict[str, Any] | None:
        if self._pushback:
            return self._pushback.pop(0)
        return await self._inner.recv()

    def push_front(self, msgs: list[dict[str, Any] | None]) -> None:
        # Maintain original order: items earlier in `msgs` should be
        # returned first. Insert in reverse so the first one ends up
        # at index 0.
        for m in reversed(msgs):
            self._pushback.insert(0, m)


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
        # Inbound message queues — populated by per-connection reader
        # tasks that transparently filter out chat messages and forward
        # them to the opponent. The main game loop reads from these
        # queues instead of conn.recv() directly so chat works
        # asynchronously, regardless of whose turn it is.
        self._inbound: dict[Color, asyncio.Queue[dict[str, Any] | None]] = {}
        self._reader_tasks: dict[Color, asyncio.Task[None]] = {}

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
        self._start_inbound_readers()
        try:
            await self._run_inner()
        finally:
            await self._stop_inbound_readers()

    async def _run_inner(self) -> None:
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
            try:
                dead = await self.dead_stone_resolver(self)
            except EngineUnavailable:
                # Every automatic resolver in the chain was unavailable
                # (no katago binary, no gnugo, etc). Fall back to the
                # interactive marker/approver flow so the game can still
                # finish without a hard crash.
                dead = await self._interactive_dead_resolver()
        if dead is None:
            # Resolver broadcast game_end itself (disconnect during
            # marking). Nothing more for us to do.
            return
        if dead:
            self.removed_dead = set(dead)
            self.game.board = self.game.board.with_stones_removed(self.removed_dead)
        await self._broadcast_game_end(ended_by="pass", resigner=None)

    # Inbound message plumbing -----------------------------------------

    def _start_inbound_readers(self) -> None:
        """Spawn one reader task per side. Each reads from its
        connection forever, forwards `chat` messages to both players,
        and queues all other messages for the main game loop."""
        for color, conn in self.conns.items():
            q: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
            self._inbound[color] = q
            self._reader_tasks[color] = asyncio.create_task(
                self._inbound_reader(color, conn, q)
            )

    async def _stop_inbound_readers(self) -> None:
        for t in self._reader_tasks.values():
            t.cancel()
        for t in self._reader_tasks.values():
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass
        # Drain anything the reader had put on the queue but the main
        # loop never consumed (e.g. a rematch message that arrived
        # right at end-of-game), and push it back onto the underlying
        # connection if it's a buffered one. Without this, post-game
        # callers like `_await_rematch` would never see those messages.
        for color, q in self._inbound.items():
            leftover: list[dict[str, Any] | None] = []
            while True:
                try:
                    leftover.append(q.get_nowait())
                except asyncio.QueueEmpty:
                    break
            if leftover:
                conn = self.conns[color]
                if isinstance(conn, _BufferedConnection):
                    conn.push_front(leftover)
        self._reader_tasks.clear()
        self._inbound.clear()

    async def _inbound_reader(
        self,
        color: Color,
        conn: Connection,
        q: "asyncio.Queue[dict[str, Any] | None]",
    ) -> None:
        try:
            while True:
                msg = await conn.recv()
                if msg is None:
                    await q.put(None)
                    return
                if msg.get("type") == "chat":
                    await self._forward_chat(color, msg.get("text"))
                    continue
                await q.put(msg)
        except asyncio.CancelledError:
            return
        except Exception:
            log.exception("inbound reader for %s crashed", color.name)
            await q.put(None)

    async def _forward_chat(self, sender: Color, text: Any) -> None:
        if not isinstance(text, str):
            return
        clean = text.strip()[:MAX_CHAT_LEN]
        if not clean:
            return
        payload = {"type": "chat", "from": sender.name, "text": clean}
        # Echo to BOTH players so the sender sees a confirmed copy and
        # the order of chat lines is identical on both ends.
        for c in self.conns.values():
            try:
                await c.send(payload)
            except Exception:
                pass

    async def _recv_game_message(
        self, color: Color, *, timeout: float | None = None
    ) -> dict[str, Any] | None:
        q = self._inbound[color]
        if timeout is None:
            return await q.get()
        return await asyncio.wait_for(q.get(), timeout=timeout)

    # ------------------------------------------------------------------

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
                msg = await self._recv_game_message(current, timeout=remaining)
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
            log.debug("marking: awaiting mark_dead from %s", marker_color.name)
            msg = await self._recv_game_message(marker_color)
            if msg is None:
                log.info("marking: marker %s disconnected", marker_color.name)
                await self._broadcast_game_end(
                    ended_by="disconnect", resigner=marker_color
                )
                return None
            if msg.get("type") == "mark_dead":
                proposal = self._sanitize_dead_points(msg.get("points") or [])
            else:
                log.warning(
                    "marking: marker sent %r, treating as empty proposal",
                    msg.get("type"),
                )
                proposal = []
            log.debug("marking: forwarding proposal of %d points", len(proposal))
            await approver.send(
                {"type": "dead_marking_proposal", "points": proposal}
            )

            log.debug("marking: awaiting mark_decision from %s", approver_color.name)
            decision = await self._recv_game_message(approver_color)
            if decision is None:
                log.info(
                    "marking: approver %s disconnected", approver_color.name
                )
                await self._broadcast_game_end(
                    ended_by="disconnect", resigner=approver_color
                )
                return None
            if (
                decision.get("type") == "mark_decision"
                and decision.get("approve") is True
            ):
                log.info("marking: approved with %d dead stones", len(proposal))
                return {(int(r), int(c)) for r, c in proposal}
            # Reject (any other shape is treated as a reject too).
            log.debug("marking: rejected (msg=%r), looping back to marker", decision)
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
        score = area_score(self.game.board, komi=DEFAULT_KOMI)
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
            "komi": score.komi,
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


async def _listen_for_rematch_decision(
    conn: Connection, deadline: float
) -> bool | None:
    """Read one rematch decision from `conn`, ignoring chat / unknown
    messages. Returns True for `agree:true`, False for `agree:false`,
    None on disconnect or deadline elapsed.

    Used by `_negotiate_rematch` for both the initial "did anyone want
    a rematch?" listen and the post-invite "did the invitee accept?"
    response read.
    """
    loop = asyncio.get_running_loop()
    while True:
        remaining = deadline - loop.time()
        if remaining <= 0:
            return None
        try:
            msg = await asyncio.wait_for(conn.recv(), timeout=remaining)
        except asyncio.TimeoutError:
            return None
        if msg is None:
            return None
        if msg.get("type") == "rematch":
            return msg.get("agree") is True
        # Chat or unknown — silently ignore and keep listening.


async def _negotiate_rematch(
    conns: dict[Color, Connection], timeout: float
) -> bool:
    """Implement the invite/respond rematch flow.

    1. Listen on BOTH sides concurrently. The first side to send
       `rematch agree=true` becomes the inviter.
    2. Server forwards `{type: "rematch_invite", from: COLOR}` to the
       OTHER side, which gets a popup with [Accept] [Reject] in the UI.
    3. Server awaits the invitee's `rematch agree=...` response.
       - True  → both sides agreed, return True (start new game)
       - False → notify the inviter via `rematch_declined`, return False
       - timeout / disconnect → notify the inviter, return False
    4. Edge cases:
       - Both sides click Rematch (almost) simultaneously: both
         listeners return True, no invite needed, return True.
       - One side preemptively declines (sends agree=false): cannot
         actually happen in the new UI, but we still handle it — if
         the OTHER side did agree we notify them; otherwise just end.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    listeners = {
        color: asyncio.create_task(
            _listen_for_rematch_decision(conn, deadline)
        )
        for color, conn in conns.items()
    }
    try:
        done, _ = await asyncio.wait(
            listeners.values(), return_when=asyncio.FIRST_COMPLETED
        )
    except BaseException:
        for t in listeners.values():
            t.cancel()
        raise
    # Cancel any still-listening task — we'll re-read directly below
    # if we need the other side's response.
    for color, task in listeners.items():
        if task not in done:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

    results: dict[Color, bool | None] = {}
    for color, task in listeners.items():
        if task in done:
            results[color] = task.result()

    true_sides = [c for c, r in results.items() if r is True]
    false_sides = [c for c, r in results.items() if r is False]

    # Both sides happened to send agree=true at once: skip the invite
    # round-trip and start the next game.
    if len(true_sides) == 2:
        return True

    # One agreed, one preemptively declined → notify the agreer.
    if true_sides and false_sides:
        agreer = true_sides[0]
        try:
            await conns[agreer].send({"type": "rematch_declined"})
        except Exception:
            pass
        return False

    # Exactly one side agreed; the other is still pending. Send the
    # invite and wait for their explicit response.
    if len(true_sides) == 1:
        first = true_sides[0]
        other = first.opponent()
        try:
            await conns[other].send(
                {"type": "rematch_invite", "from": first.name}
            )
        except Exception:
            return False
        remaining_deadline = loop.time() + max(0.0, deadline - loop.time())
        other_resp = await _listen_for_rematch_decision(
            conns[other], remaining_deadline
        )
        if other_resp is True:
            return True
        try:
            await conns[first].send({"type": "rematch_declined"})
        except Exception:
            pass
        return False

    # Nobody agreed (timeouts / disconnects / both declined preemptively).
    return False


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
    # Wrap each connection so the session's inbound reader can push
    # leftover messages (e.g. a rematch message that arrived during
    # game 1's late phase) back into the read stream for the next
    # `_await_rematch` to consume.
    black = _BufferedConnection(black) if not isinstance(black, _BufferedConnection) else black
    white = _BufferedConnection(white) if not isinstance(white, _BufferedConnection) else white
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
        agreed = await _negotiate_rematch(
            {Color.BLACK: black, Color.WHITE: white},
            rematch_timeout_seconds,
        )
        if agreed:
            # Swap colors so the prior WHITE plays first next round.
            black, white = white, black
            black_name, white_name = white_name, black_name
            continue
        return
