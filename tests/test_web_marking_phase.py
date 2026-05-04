"""Real-WebSocket reproduction of the marking-phase + rematch flow.

Spins up the actual FastAPI app via `httpx`-style ASGI, opens two
WebSocket clients, plays a game to the marking phase, approves the
dead-stone proposal, then attempts a rematch. Catches the kind of
ws/asyncio bugs that the in-memory FakeConn-based session tests
can't see.
"""
from __future__ import annotations

import asyncio
import json

import pytest
from starlette.testclient import TestClient

from transport.web.server import app


def _ws_send(ws, payload: dict) -> None:
    ws.send_text(json.dumps(payload))


def _ws_recv(ws) -> dict:
    return json.loads(ws.receive_text())


def _drain_until(ws, msg_type: str, max_messages: int = 30) -> dict:
    """Read messages until one of the given type is seen; return it.
    Raises AssertionError if `max_messages` go by without seeing it."""
    for _ in range(max_messages):
        m = _ws_recv(ws)
        if m.get("type") == msg_type:
            return m
    raise AssertionError(f"never saw {msg_type!r}")


@pytest.mark.timeout(15)
def test_marking_phase_approve_then_game_end_via_websocket():
    """Full flow over the real ws layer:
       - both players join_random
       - both pass-pass
       - marker sends mark_dead, approver approves
       - both must receive game_end with dead_stones honored
    """
    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws_a, client.websocket_connect("/ws") as ws_b:
            _ws_send(ws_a, {"type": "join_random", "name": "Alice"})
            _ws_send(ws_b, {"type": "join_random", "name": "Bob"})

            welcome_a = _drain_until(ws_a, "welcome")
            welcome_b = _drain_until(ws_b, "welcome")
            black_ws, white_ws = (ws_a, ws_b) if welcome_a["color"] == "BLACK" else (ws_b, ws_a)

            # Black gets your_turn first, plays at (0,0), then both pass.
            _drain_until(black_ws, "your_turn")
            _ws_send(black_ws, {"type": "play", "row": 0, "col": 0})
            _drain_until(black_ws, "played")
            _drain_until(white_ws, "your_turn")
            _ws_send(white_ws, {"type": "pass"})
            _drain_until(white_ws, "passed")
            _drain_until(black_ws, "your_turn")
            _ws_send(black_ws, {"type": "pass"})

            # Marking phase: black is the marker, white is approver.
            marker_msg = _drain_until(black_ws, "dead_marking_started")
            approver_msg = _drain_until(white_ws, "dead_marking_started")
            assert marker_msg["your_role"] == "marker"
            assert approver_msg["your_role"] == "approver"

            # Marker proposes nothing; approver approves immediately.
            _ws_send(black_ws, {"type": "mark_dead", "points": []})
            _drain_until(white_ws, "dead_marking_proposal")
            _ws_send(white_ws, {"type": "mark_decision", "approve": True})

            # BOTH sides must receive game_end. THIS is the regression
            # the user reported as "Approved. Computing final score..."
            # never resolving.
            end_b = _drain_until(black_ws, "game_end")
            end_w = _drain_until(white_ws, "game_end")
            assert end_b["dead_stones"] == []
            assert end_w["dead_stones"] == []
            assert end_b["winner"] in ("BLACK", "WHITE", None)


@pytest.mark.timeout(15)
def test_chat_forwarded_both_directions_during_game():
    """A chat message sent by either player must be echoed to BOTH
    sides (sender for confirmation, opponent for delivery), regardless
    of whose turn it is."""
    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws_a, client.websocket_connect("/ws") as ws_b:
            _ws_send(ws_a, {"type": "join_random", "name": "Alice"})
            _ws_send(ws_b, {"type": "join_random", "name": "Bob"})
            welcome_a = _drain_until(ws_a, "welcome")
            welcome_b = _drain_until(ws_b, "welcome")
            black_ws, white_ws = (ws_a, ws_b) if welcome_a["color"] == "BLACK" else (ws_b, ws_a)

            # Black gets first your_turn. Send a chat from white BEFORE
            # white's turn — this exercises the async path (chat from
            # the side that isn't currently expected to act).
            _drain_until(black_ws, "your_turn")
            _ws_send(white_ws, {"type": "chat", "text": "good luck!"})
            chat_b = _drain_until(black_ws, "chat")
            chat_w = _drain_until(white_ws, "chat")
            assert chat_b["from"] == "WHITE"
            assert chat_b["text"] == "good luck!"
            assert chat_w == chat_b  # both ends see identical payload

            # Resign to terminate cleanly.
            _ws_send(black_ws, {"type": "resign"})
            _drain_until(black_ws, "game_end")
            _drain_until(white_ws, "game_end")


@pytest.mark.timeout(15)
def test_chat_clamped_and_dropped_when_blank():
    """Server must clamp to MAX_CHAT_LEN and drop empty/whitespace text."""
    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws_a, client.websocket_connect("/ws") as ws_b:
            _ws_send(ws_a, {"type": "join_random", "name": "A"})
            _ws_send(ws_b, {"type": "join_random", "name": "B"})
            welcome_a = _drain_until(ws_a, "welcome")
            _drain_until(ws_b, "welcome")
            black_ws, white_ws = (ws_a, ws_b) if welcome_a["color"] == "BLACK" else (ws_b, ws_a)
            _drain_until(black_ws, "your_turn")

            # Empty chat should NOT broadcast.
            _ws_send(white_ws, {"type": "chat", "text": "   "})

            # Long chat should be clamped to 200 chars.
            long_text = "x" * 1000
            _ws_send(white_ws, {"type": "chat", "text": long_text})
            chat = _drain_until(black_ws, "chat")
            assert len(chat["text"]) == 200
            assert chat["text"] == "x" * 200

            _ws_send(black_ws, {"type": "resign"})
            _drain_until(black_ws, "game_end")
            _drain_until(white_ws, "game_end")


@pytest.mark.timeout(15)
def test_rematch_invite_flow_first_clicker_then_invitee_accepts():
    """First side to click Rematch makes the OTHER side receive a
    rematch_invite. The invitee's response (accept/reject) decides
    whether a new game begins."""
    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws_a, client.websocket_connect("/ws") as ws_b:
            _ws_send(ws_a, {"type": "join_random", "name": "Alice"})
            _ws_send(ws_b, {"type": "join_random", "name": "Bob"})
            welcome_a = _drain_until(ws_a, "welcome")
            welcome_b = _drain_until(ws_b, "welcome")
            black_ws, white_ws = (ws_a, ws_b) if welcome_a["color"] == "BLACK" else (ws_b, ws_a)
            black_first_color = welcome_a["color"] == "BLACK"

            # Quickest game: pass-pass + empty marking + approve.
            _drain_until(black_ws, "your_turn")
            _ws_send(black_ws, {"type": "pass"})
            _drain_until(white_ws, "your_turn")
            _ws_send(white_ws, {"type": "pass"})
            _drain_until(black_ws, "dead_marking_started")
            _drain_until(white_ws, "dead_marking_started")
            _ws_send(black_ws, {"type": "mark_dead", "points": []})
            _drain_until(white_ws, "dead_marking_proposal")
            _ws_send(white_ws, {"type": "mark_decision", "approve": True})
            _drain_until(black_ws, "game_end")
            _drain_until(white_ws, "game_end")

            # Black clicks Rematch first. Server should forward
            # `rematch_invite` to white (only).
            _ws_send(black_ws, {"type": "rematch", "agree": True})
            invite = _drain_until(white_ws, "rematch_invite")
            assert invite["from"] == "BLACK"

            # White accepts the invite. Both should get a fresh welcome
            # with swapped colors.
            _ws_send(white_ws, {"type": "rematch", "agree": True})
            new_welcome_a = _drain_until(ws_a, "welcome")
            new_welcome_b = _drain_until(ws_b, "welcome")
            assert new_welcome_a["color"] != welcome_a["color"]
            assert new_welcome_b["color"] != welcome_b["color"]


@pytest.mark.timeout(15)
def test_rematch_invite_flow_invitee_rejects_notifies_inviter():
    """When the invitee rejects, the inviter receives `rematch_declined`
    and no new welcome is sent."""
    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws_a, client.websocket_connect("/ws") as ws_b:
            _ws_send(ws_a, {"type": "join_random", "name": "A"})
            _ws_send(ws_b, {"type": "join_random", "name": "B"})
            welcome_a = _drain_until(ws_a, "welcome")
            welcome_b = _drain_until(ws_b, "welcome")
            black_ws, white_ws = (ws_a, ws_b) if welcome_a["color"] == "BLACK" else (ws_b, ws_a)

            _drain_until(black_ws, "your_turn")
            _ws_send(black_ws, {"type": "pass"})
            _drain_until(white_ws, "your_turn")
            _ws_send(white_ws, {"type": "pass"})
            _drain_until(black_ws, "dead_marking_started")
            _drain_until(white_ws, "dead_marking_started")
            _ws_send(black_ws, {"type": "mark_dead", "points": []})
            _drain_until(white_ws, "dead_marking_proposal")
            _ws_send(white_ws, {"type": "mark_decision", "approve": True})
            _drain_until(black_ws, "game_end")
            _drain_until(white_ws, "game_end")

            # Black sends rematch agree, white sees invite, white rejects.
            _ws_send(black_ws, {"type": "rematch", "agree": True})
            _drain_until(white_ws, "rematch_invite")
            _ws_send(white_ws, {"type": "rematch", "agree": False})

            declined = _drain_until(black_ws, "rematch_declined")
            assert declined["type"] == "rematch_declined"


@pytest.mark.timeout(20)
def test_rematch_both_agree_starts_second_game():
    """After game_end, both clicking rematch should yield a second
    welcome with swapped colors."""
    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws_a, client.websocket_connect("/ws") as ws_b:
            _ws_send(ws_a, {"type": "join_random", "name": "Alice"})
            _ws_send(ws_b, {"type": "join_random", "name": "Bob"})

            welcome_a = _drain_until(ws_a, "welcome")
            welcome_b = _drain_until(ws_b, "welcome")
            black_ws, white_ws = (ws_a, ws_b) if welcome_a["color"] == "BLACK" else (ws_b, ws_a)

            # Quickest game: pass-pass, no marking, approve empty proposal.
            _drain_until(black_ws, "your_turn")
            _ws_send(black_ws, {"type": "pass"})
            _drain_until(white_ws, "your_turn")
            _ws_send(white_ws, {"type": "pass"})
            _drain_until(black_ws, "dead_marking_started")
            _drain_until(white_ws, "dead_marking_started")
            _ws_send(black_ws, {"type": "mark_dead", "points": []})
            _drain_until(white_ws, "dead_marking_proposal")
            _ws_send(white_ws, {"type": "mark_decision", "approve": True})
            _drain_until(black_ws, "game_end")
            _drain_until(white_ws, "game_end")

            # Both request rematch.
            _ws_send(ws_a, {"type": "rematch", "agree": True})
            _ws_send(ws_b, {"type": "rematch", "agree": True})

            # Second welcome should arrive on each connection. Original
            # BLACK should now play WHITE and vice versa.
            welcome2_a = _drain_until(ws_a, "welcome")
            welcome2_b = _drain_until(ws_b, "welcome")
            assert welcome2_a["color"] != welcome_a["color"]
            assert welcome2_b["color"] != welcome_b["color"]
