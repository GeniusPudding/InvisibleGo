"""Integration tests for GameSession via in-memory Connection stubs."""
import asyncio
from typing import Any

import pytest

from core.board import BOARD_SIZE, Color
from transport.session import Connection, GameSession, run_match_series


class FakeConn(Connection):
    """In-memory connection. Tests push inputs into `inbox` and inspect `outbox`."""

    def __init__(self) -> None:
        self.outbox: list[dict[str, Any]] = []
        self.inbox: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

    async def send(self, msg: dict[str, Any]) -> None:
        self.outbox.append(msg)

    async def recv(self) -> dict[str, Any] | None:
        return await self.inbox.get()


def _types(conn: FakeConn) -> list[str]:
    return [m["type"] for m in conn.outbox]


@pytest.mark.asyncio
async def test_welcome_then_your_turn_to_black():
    black, white = FakeConn(), FakeConn()
    session = GameSession(black=black, white=white)
    # Pre-load a pass to end the game quickly: black passes, white passes.
    await black.inbox.put({"type": "pass"})
    await white.inbox.put({"type": "pass"})
    await session.run()
    assert _types(black)[:2] == ["welcome", "your_turn"]
    assert _types(white)[:1] == ["welcome"]
    # After both passes, both get game_end
    assert "game_end" in _types(black)
    assert "game_end" in _types(white)


@pytest.mark.asyncio
async def test_illegal_response_carries_no_reason():
    black, white = FakeConn(), FakeConn()
    session = GameSession(black=black, white=white)
    # Black plays at (4,4); White tries to play on Black's stone => illegal
    await black.inbox.put({"type": "play", "row": 4, "col": 4})
    await white.inbox.put({"type": "play", "row": 4, "col": 4})  # opponent-occupied
    # White then resigns to end the game
    await white.inbox.put({"type": "resign"})
    await session.run()

    illegal_msgs = [m for m in white.outbox if m["type"] == "illegal"]
    assert len(illegal_msgs) >= 1
    # The illegal message must NOT have any field that distinguishes the reason.
    for m in illegal_msgs:
        assert set(m.keys()) == {"type", "attempts_remaining"}


@pytest.mark.asyncio
async def test_three_illegal_attempts_auto_skip():
    black, white = FakeConn(), FakeConn()
    session = GameSession(black=black, white=white)
    await black.inbox.put({"type": "play", "row": 4, "col": 4})
    # White makes 3 illegal attempts at the same opponent-occupied point
    for _ in range(3):
        await white.inbox.put({"type": "play", "row": 4, "col": 4})
    # Now it should be Black's turn again. Black passes, White passes => game over.
    await black.inbox.put({"type": "pass"})
    await white.inbox.put({"type": "pass"})
    await session.run()
    illegal_msgs = [m for m in white.outbox if m["type"] == "illegal"]
    assert len(illegal_msgs) == 3
    assert illegal_msgs[-1]["attempts_remaining"] == 0


@pytest.mark.asyncio
async def test_view_hides_opponent_stones_in_protocol():
    black, white = FakeConn(), FakeConn()
    session = GameSession(black=black, white=white)
    # Black plays (4,4). White then receives your_turn — that view must NOT
    # contain the black stone.
    await black.inbox.put({"type": "play", "row": 4, "col": 4})
    await white.inbox.put({"type": "pass"})
    await black.inbox.put({"type": "pass"})
    await session.run()
    your_turns_white = [m for m in white.outbox if m["type"] == "your_turn"]
    first = your_turns_white[0]
    stones = first["view"]["your_stones"]
    assert stones[4 * BOARD_SIZE + 4] == Color.EMPTY.value


@pytest.mark.asyncio
async def test_turn_timeout_auto_passes():
    black, white = FakeConn(), FakeConn()
    session = GameSession(black=black, white=white, turn_timeout_seconds=0.05)
    # Black does not send anything → times out and gets auto-passed
    # White then passes voluntarily → two consecutive passes, game ends
    await white.inbox.put({"type": "pass"})
    await session.run()

    # Black should have received the turn_timeout notice
    assert any(m["type"] == "turn_timeout" for m in black.outbox)
    # White's pass ended the game (2 consecutive passes), so both receive game_end
    # (no per-pass confirmation is sent when the pass happens to close the game)
    assert any(m["type"] == "game_end" for m in black.outbox)
    assert any(m["type"] == "game_end" for m in white.outbox)


@pytest.mark.asyncio
async def test_your_turn_includes_turn_deadline():
    black, white = FakeConn(), FakeConn()
    session = GameSession(black=black, white=white, turn_timeout_seconds=42.0)
    await black.inbox.put({"type": "pass"})
    await white.inbox.put({"type": "pass"})
    await session.run()
    yt = [m for m in black.outbox if m["type"] == "your_turn"][0]
    assert yt["turn_deadline_seconds"] == 42.0


@pytest.mark.asyncio
async def test_your_turn_includes_last_own_move():
    black, white = FakeConn(), FakeConn()
    session = GameSession(black=black, white=white)
    # Black plays (4,4), White passes, so Black's next your_turn should
    # carry last_own_move=[4,4]. End the game to conclude.
    await black.inbox.put({"type": "play", "row": 4, "col": 4})
    await white.inbox.put({"type": "pass"})
    await black.inbox.put({"type": "pass"})
    await white.inbox.put({"type": "pass"})
    await session.run()

    black_yts = [m for m in black.outbox if m["type"] == "your_turn"]
    # First black turn has no prior move; second should remember (4,4).
    assert black_yts[0]["view"]["last_own_move"] is None
    assert black_yts[1]["view"]["last_own_move"] == [4, 4]
    # White never played, so their last_own_move is always null.
    for yt in (m for m in white.outbox if m["type"] == "your_turn"):
        assert yt["view"]["last_own_move"] is None


@pytest.mark.asyncio
async def test_rematch_both_agree_swaps_colors():
    black, white = FakeConn(), FakeConn()
    # Inbox ordering matters: each FakeConn sees one message per role it's
    # asked for. Game 1: both pass. Both agree to rematch. Game 2 (colors
    # swapped): now the *white* FakeConn plays BLACK first, then the
    # *black* FakeConn plays WHITE. Both decline and the series ends.
    await black.inbox.put({"type": "pass"})                     # game 1 as BLACK
    await white.inbox.put({"type": "pass"})                     # game 1 as WHITE
    await black.inbox.put({"type": "rematch", "agree": True})
    await white.inbox.put({"type": "rematch", "agree": True})
    await white.inbox.put({"type": "pass"})                     # game 2 as BLACK
    await black.inbox.put({"type": "pass"})                     # game 2 as WHITE
    await black.inbox.put({"type": "rematch", "agree": False})
    await white.inbox.put({"type": "rematch", "agree": False})

    await run_match_series(
        black=black, white=white,
        black_name="Alice", white_name="Bob",
        rematch_timeout_seconds=1.0,
    )

    black_welcomes = [m for m in black.outbox if m["type"] == "welcome"]
    white_welcomes = [m for m in white.outbox if m["type"] == "welcome"]
    # Two games total → two welcomes each.
    assert len(black_welcomes) == 2
    assert len(white_welcomes) == 2
    # Colors swap between games: the `black` FakeConn starts as BLACK and
    # becomes WHITE in the rematch.
    assert black_welcomes[0]["color"] == "BLACK"
    assert black_welcomes[1]["color"] == "WHITE"
    assert white_welcomes[0]["color"] == "WHITE"
    assert white_welcomes[1]["color"] == "BLACK"


@pytest.mark.asyncio
async def test_rematch_one_declines_notifies_the_other():
    black, white = FakeConn(), FakeConn()
    await black.inbox.put({"type": "pass"})
    await white.inbox.put({"type": "pass"})
    await black.inbox.put({"type": "rematch", "agree": True})
    await white.inbox.put({"type": "rematch", "agree": False})

    await run_match_series(
        black=black, white=white, rematch_timeout_seconds=1.0,
    )

    # Only one game played.
    assert sum(1 for m in black.outbox if m["type"] == "welcome") == 1
    # The one who agreed gets a rematch_declined notice; the one who
    # declined does not (they already know).
    assert any(m["type"] == "rematch_declined" for m in black.outbox)
    assert not any(m["type"] == "rematch_declined" for m in white.outbox)


@pytest.mark.asyncio
async def test_rematch_not_offered_after_disconnect():
    black, white = FakeConn(), FakeConn()
    # Black disconnects mid-game: recv() returns None.
    await black.inbox.put(None)

    await run_match_series(
        black=black, white=white, rematch_timeout_seconds=1.0,
    )
    # Single game, no rematch prompt consumed from either side.
    assert sum(1 for m in black.outbox if m["type"] == "welcome") == 1
    assert not any(m["type"] == "rematch_declined" for m in white.outbox)


@pytest.mark.asyncio
async def test_your_turn_includes_own_move_numbers():
    """Each `your_turn` carries `own_move_numbers` listing the absolute
    move ordinal of every surviving own stone — the basis for the
    'Show #' overlay clients render."""
    black, white = FakeConn(), FakeConn()
    session = GameSession(black=black, white=white)
    # B(0,0)=1, W(8,8)=2, B(0,1)=3, W(8,7)=4, B pass, W pass.
    await black.inbox.put({"type": "play", "row": 0, "col": 0})
    await white.inbox.put({"type": "play", "row": 8, "col": 8})
    await black.inbox.put({"type": "play", "row": 0, "col": 1})
    await white.inbox.put({"type": "play", "row": 8, "col": 7})
    await black.inbox.put({"type": "pass"})
    await white.inbox.put({"type": "pass"})
    await session.run()

    # Black's last `your_turn` (right before pass) must list own move 1 + 3
    black_turns = [m for m in black.outbox if m["type"] == "your_turn"]
    last_black_view = black_turns[-1]["view"]
    nums = sorted(last_black_view["own_move_numbers"])
    assert nums == [[0, 0, 1], [0, 1, 3]]
    # White's last `your_turn` lists own move 2 + 4 — never any of black's.
    white_turns = [m for m in white.outbox if m["type"] == "your_turn"]
    last_white_view = white_turns[-1]["view"]
    nums = sorted(last_white_view["own_move_numbers"])
    assert nums == [[8, 7, 4], [8, 8, 2]]


@pytest.mark.asyncio
async def test_game_end_carries_full_move_history():
    """game_end exposes the complete ordered move list (both colors)
    so clients can render numbers on the revealed full board."""
    black, white = FakeConn(), FakeConn()
    session = GameSession(black=black, white=white)
    await black.inbox.put({"type": "play", "row": 0, "col": 0})
    await white.inbox.put({"type": "play", "row": 8, "col": 8})
    await black.inbox.put({"type": "pass"})
    await white.inbox.put({"type": "pass"})
    await session.run()

    end = next(m for m in black.outbox if m["type"] == "game_end")
    assert end["move_history"] == [["BLACK", 0, 0], ["WHITE", 8, 8]]
    # White sees the same history.
    end_w = next(m for m in white.outbox if m["type"] == "game_end")
    assert end_w["move_history"] == end["move_history"]


@pytest.mark.asyncio
async def test_captured_stone_drops_out_of_own_move_numbers():
    """When an own stone is captured, its move ordinal must disappear
    from the view's own_move_numbers — otherwise the 'Show #' overlay
    would draw a number on an empty point and silently leak info."""
    black, white = FakeConn(), FakeConn()
    session = GameSession(black=black, white=white)
    # Set up a capture: W gets surrounded at (0,0) and dies.
    # B(0,1)=1, W(0,0)=2, B(1,0)=3 (captures W), W(8,8)=4, B/W pass.
    await black.inbox.put({"type": "play", "row": 0, "col": 1})
    await white.inbox.put({"type": "play", "row": 0, "col": 0})
    await black.inbox.put({"type": "play", "row": 1, "col": 0})
    await white.inbox.put({"type": "play", "row": 8, "col": 8})
    await black.inbox.put({"type": "pass"})
    await white.inbox.put({"type": "pass"})
    await session.run()

    # White's final `your_turn` must NOT list move 2 — that stone is gone.
    white_turns = [m for m in white.outbox if m["type"] == "your_turn"]
    last_white_view = white_turns[-1]["view"]
    nums = sorted(last_white_view["own_move_numbers"])
    assert nums == [[8, 8, 4]]


@pytest.mark.asyncio
async def test_resign_ends_game_with_opponent_winner():
    black, white = FakeConn(), FakeConn()
    session = GameSession(black=black, white=white)
    await black.inbox.put({"type": "resign"})
    await session.run()
    # Both should receive game_end indicating BLACK resigned, WHITE won
    end_msgs = [m for c in (black, white) for m in c.outbox if m["type"] == "game_end"]
    assert len(end_msgs) == 2
    for m in end_msgs:
        assert m["ended_by"] == "resign"
        assert m["resigner"] == "BLACK"
        assert m["winner"] == "WHITE"
