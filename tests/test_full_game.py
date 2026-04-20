"""End-to-end games played to the scoring phase via GameSession.

Each test scripts a full game (both colors' inputs pre-loaded into fake
connections) and asserts on the final game_end payload. The final referee
board, each player's view, and the score breakdown are printed via
`print()` so a human running `pytest -s tests/test_full_game.py` can
visually verify the endgame position alongside the asserted numbers.

The tests drive the transport-agnostic GameSession directly, bypassing
TCP / WebSocket / Qt. This is the cheapest and highest-coverage layer at
which scoring can be validated: it exercises the same rule engine,
view-projection, and game-end broadcast code that every real transport
uses.
"""
from __future__ import annotations

import asyncio
from typing import Any, Iterable

from core.board import BOARD_SIZE, Board, Color
from core.scoring import area_score
from transport.session import Connection, GameSession


# --- fake connection + helpers --------------------------------------------


class FakeConn(Connection):
    """In-memory connection. Scripts push moves into `inbox`; sent messages
    land in `outbox` for assertions."""

    def __init__(self) -> None:
        self.outbox: list[dict[str, Any]] = []
        self.inbox: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

    async def send(self, msg: dict[str, Any]) -> None:
        self.outbox.append(msg)

    async def recv(self) -> dict[str, Any] | None:
        return await self.inbox.get()


def play(r: int, c: int) -> dict[str, Any]:
    return {"type": "play", "row": r, "col": c}


def pass_() -> dict[str, Any]:
    return {"type": "pass"}


def resign() -> dict[str, Any]:
    return {"type": "resign"}


async def run_scripted(
    black_moves: Iterable[dict[str, Any]],
    white_moves: Iterable[dict[str, Any]],
    timeout: float = 5.0,
) -> tuple[GameSession, FakeConn, FakeConn]:
    black, white = FakeConn(), FakeConn()
    for m in black_moves:
        await black.inbox.put(m)
    for m in white_moves:
        await white.inbox.put(m)
    session = GameSession(black=black, white=white)
    # Fast-fail if a script under-supplies moves (session would otherwise
    # await indefinitely on an empty queue).
    await asyncio.wait_for(session.run(), timeout=timeout)
    return session, black, white


def game_end_of(conn: FakeConn) -> dict[str, Any]:
    for m in conn.outbox:
        if m["type"] == "game_end":
            return m
    raise AssertionError("no game_end message in outbox")


# --- ASCII renderers (visible only with `pytest -s`) ----------------------


_REF_GLYPH = {Color.EMPTY: ".", Color.BLACK: "X", Color.WHITE: "O"}


def render_referee(board: Board, title: str = "referee") -> str:
    lines = [f"--- {title} ---", "   " + " ".join(str(c) for c in range(BOARD_SIZE))]
    for r in range(BOARD_SIZE):
        row = [_REF_GLYPH[board.at((r, c))] for c in range(BOARD_SIZE)]
        lines.append(f" {r} " + " ".join(row))
    return "\n".join(lines)


def render_view(board: Board, perspective: Color) -> str:
    """A player's view: own stones visible, opponent stones as '.'.
    Matches the visibility contract enforced by core.view.build_view."""
    glyph = "X" if perspective is Color.BLACK else "O"
    lines = [
        f"--- {perspective.name} view ---",
        "   " + " ".join(str(c) for c in range(BOARD_SIZE)),
    ]
    for r in range(BOARD_SIZE):
        row = [glyph if board.at((r, c)) is perspective else "." for c in range(BOARD_SIZE)]
        lines.append(f" {r} " + " ".join(row))
    return "\n".join(lines)


def dump_endgame(session: GameSession, end_msg: dict[str, Any]) -> str:
    s = area_score(session.game.board)
    return "\n".join(
        [
            "",
            render_referee(session.game.board, title="final referee board"),
            "",
            render_view(session.game.board, Color.BLACK),
            "",
            render_view(session.game.board, Color.WHITE),
            "",
            f"score  -> BLACK: {s.black}   WHITE: {s.white}",
            f"result -> winner: {end_msg['winner']}   "
            f"ended_by: {end_msg['ended_by']}   "
            f"resigner: {end_msg['resigner']}",
            "",
        ]
    )


# --- tests ----------------------------------------------------------------


async def test_territory_split_white_wins_by_9():
    """Two vertical walls, dame column in between.

    Board at end:
      cols 0,1     empty, bordered only by black col 2  -> 18 black territory
      col  2       9 black stones
      cols 3,4     empty, bordered by both              -> dame
      col  5       9 white stones
      cols 6,7,8   empty, bordered only by white col 5  -> 27 white territory

    Black: 9 + 18 = 27. White: 9 + 27 = 36. White wins by 9.
    """
    black_script = [play(r, 2) for r in range(BOARD_SIZE)] + [pass_()]
    white_script = [play(r, 5) for r in range(BOARD_SIZE)] + [pass_()]
    session, black, white = await run_scripted(black_script, white_script)
    end = game_end_of(black)
    print(dump_endgame(session, end))

    assert session.game.is_over
    assert end["black_score"] == 27
    assert end["white_score"] == 36
    assert end["winner"] == "WHITE"
    assert end["ended_by"] == "pass"
    assert game_end_of(white) == end  # both sides see the same payload


async def test_corner_capture_then_score():
    """Black captures a white corner stone, then both pass.

    Move stream:
      B(0,1)      black at corner-adjacent
      W(0,0)      white corner stone, 1 liberty left
      B(1,0)      captures W(0,0); corner becomes empty
      W(8,8)      white drops an isolated stone far away
      B pass / W pass

    End position: B at (0,1),(1,0); W at (8,8); empty corner (0,0) is
    surrounded only by black -> 1 black territory. Everything else
    touches both colors -> dame.
    """
    black_script = [play(0, 1), play(1, 0), pass_()]
    white_script = [play(0, 0), play(8, 8), pass_()]
    session, black, white = await run_scripted(black_script, white_script)
    end = game_end_of(black)
    print(dump_endgame(session, end))

    # Sanity: white's outbox logged the capture as a pending-loss count.
    your_turns_white = [m for m in white.outbox if m["type"] == "your_turn"]
    assert any(m["losses_since_last_turn"] == 1 for m in your_turns_white)

    assert end["black_score"] == 3   # 2 stones + 1 corner territory
    assert end["white_score"] == 1   # 1 stone, no territory
    assert end["winner"] == "BLACK"
    assert end["ended_by"] == "pass"


async def test_ko_attempt_illegal_then_resolve_and_score():
    """Build a ko, try to recapture immediately (illegal x3 -> auto-skip),
    then play out and score.

    Classic ko shape centered at (4,4):
        . B W .
        B W . W
        . B W .
    After black plays (4,5), the middle white at (4,4) is captured; the
    board now matches the prior position if white plays (4,4) back ->
    superko rejection. White exhausts 3 attempts on that ko point and is
    auto-skipped. Black then plays (0,0); both sides pass; game ends.
    """
    black_script = [
        play(3, 4),   # T1
        play(4, 3),   # T3
        play(5, 4),   # T5
        play(8, 8),   # T7 filler, so white gets to play (4,6) on T8
        play(4, 5),   # T9 — captures W(4,4)
        play(0, 0),   # T11 — intervening move after white's auto-skip
        pass_(),      # T13
    ]
    white_script = [
        play(3, 5),   # T2
        play(4, 4),   # T4 middle white
        play(5, 5),   # T6
        play(4, 6),   # T8 — completes the surround
        play(4, 4),   # T10 ko attempt 1 -> illegal
        play(4, 4),   # T10 ko attempt 2 -> illegal
        play(4, 4),   # T10 ko attempt 3 -> illegal, turn auto-skipped
        pass_(),      # T12
    ]
    session, black, white = await run_scripted(black_script, white_script)
    end = game_end_of(black)
    print(dump_endgame(session, end))

    # The three ko-recap attempts should have produced exactly three
    # illegal messages, and none of them may carry a reason field.
    illegals = [m for m in white.outbox if m["type"] == "illegal"]
    assert len(illegals) == 3
    for m in illegals:
        assert set(m.keys()) == {"type", "attempts_remaining"}
    assert illegals[-1]["attempts_remaining"] == 0

    # The captured white stone really did leave the board.
    assert session.game.board.at((4, 4)) is Color.EMPTY
    assert session.game.is_over
    assert end["ended_by"] == "pass"
    # Score sanity: black has 5 stones on the board, white has 3.
    # We don't pin an exact score here because territory depends on the
    # full frontier, but black must be winning (more stones, more
    # surrounding influence and a corner stone).
    assert end["winner"] == "BLACK"


async def test_auto_skip_on_own_turn_counts_toward_double_pass():
    """After white passes (1st consecutive pass), black auto-skips by
    attempting 3 illegal own-occupied moves. That auto-skip is the 2nd
    consecutive pass -> game ends. The sole black stone owns all 81
    points under area scoring."""
    black_script = [
        play(4, 4),   # legal opener
        play(4, 4),   # own-occupied, illegal x3 -> auto-skip
        play(4, 4),
        play(4, 4),
    ]
    white_script = [pass_()]
    session, black, white = await run_scripted(black_script, white_script)
    end = game_end_of(black)
    print(dump_endgame(session, end))

    assert session.game.is_over
    assert end["black_score"] == BOARD_SIZE * BOARD_SIZE
    assert end["white_score"] == 0
    assert end["winner"] == "BLACK"
    # The auto-skip's 3rd illegal must report zero attempts remaining.
    illegals = [m for m in black.outbox if m["type"] == "illegal"]
    assert illegals[-1]["attempts_remaining"] == 0


async def test_resign_gives_opponent_the_win_even_when_behind():
    """Black builds a dominant wall then resigns. Score alone would give
    black 81-0, but resignation overrides: white wins."""
    black_script = [play(r, 2) for r in range(BOARD_SIZE)] + [resign()]
    white_script = [pass_() for _ in range(BOARD_SIZE)]
    session, black, white = await run_scripted(black_script, white_script)
    end = game_end_of(black)
    print(dump_endgame(session, end))

    assert end["ended_by"] == "resign"
    assert end["resigner"] == "BLACK"
    assert end["winner"] == "WHITE"
    # Visibility contract still holds at game end: the broadcast full_board
    # reveals everything (otherwise scoring would be unverifiable).
    revealed = end["full_board"]
    assert any(v == Color.BLACK.value for v in revealed)


async def test_symmetric_split_is_tie():
    """Symmetric walls at col 3 (black) and col 5 (white):
      cols 0-2 = 27 empty bordered only by black  -> black territory
      col  3   = 9 black stones
      col  4   = 9 empty bordered by both         -> dame
      col  5   = 9 white stones
      cols 6-8 = 27 empty bordered only by white  -> white territory

    Black 9+27 = 36. White 9+27 = 36. Tie -> winner is None."""
    black_script = [play(r, 3) for r in range(BOARD_SIZE)] + [pass_()]
    white_script = [play(r, 5) for r in range(BOARD_SIZE)] + [pass_()]
    session, black, white = await run_scripted(black_script, white_script)
    end = game_end_of(black)
    print(dump_endgame(session, end))

    assert end["black_score"] == 36
    assert end["white_score"] == 36
    assert end["winner"] is None
