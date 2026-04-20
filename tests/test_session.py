"""Integration tests for GameSession via in-memory Connection stubs."""
import asyncio
from typing import Any

import pytest

from core.board import BOARD_SIZE, Color
from transport.session import Connection, GameSession


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
