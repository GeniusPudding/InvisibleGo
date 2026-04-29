"""End-to-end tests over real TCP loopback.

The other test files drive `GameSession` / `run_match_series` via in-memory
`FakeConn` objects, which exercise the rules and orchestration but skip
the entire transport layer — JSON framing, socket buffering, asyncio
scheduling across real reader/writer pairs, clean/dirty disconnects.

These tests stand up an asyncio TCP server on a random loopback port,
wrap two genuine client sockets, and drive full game flows through
them.
"""
import asyncio

from core.board import BOARD_SIZE
from protocol.messages import read_frame, write_frame
from transport.lan.server import TcpConnection
from transport.session import no_dead_stones, run_match_series


async def _spin_up_server():
    pending = []
    ready = asyncio.Event()

    async def on_connect(r, w):
        pending.append(TcpConnection(r, w))
        if len(pending) == 2:
            ready.set()

    server = await asyncio.start_server(on_connect, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    return server, port, pending, ready


async def _read_until(reader, msg_type, limit=30):
    for _ in range(limit):
        m = await asyncio.wait_for(read_frame(reader), timeout=2.0)
        if m is None:
            raise AssertionError(f"connection closed before {msg_type!r}")
        if m.get("type") == msg_type:
            return m
    raise AssertionError(f"did not see {msg_type!r} within {limit} frames")


async def _shutdown(server, writers, task=None):
    """Best-effort teardown. Avoids `await w.wait_closed()` and
    `await server.wait_closed()` because both can deadlock on Windows
    ProactorEventLoop when sockets were closed abruptly."""
    for w in writers:
        try:
            w.close()
        except Exception:
            pass
    if task is not None:
        try:
            await asyncio.wait_for(task, timeout=3.0)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
    server.close()


async def test_tcp_loopback_full_game_reaches_scored_game_end():
    """BLACK plays col 2, WHITE plays col 5, both pass. game_end on the
    wire shows the same scores to both clients (BLACK 27 / WHITE 36)."""
    server, port, pending, ready = await _spin_up_server()
    r1, w1 = await asyncio.open_connection("127.0.0.1", port)
    r2, w2 = await asyncio.open_connection("127.0.0.1", port)
    await asyncio.wait_for(ready.wait(), timeout=2.0)
    task = asyncio.create_task(run_match_series(black=pending[0], white=pending[1], dead_stone_resolver=no_dead_stones))

    await _read_until(r1, "welcome")
    await _read_until(r2, "welcome")
    for row in range(BOARD_SIZE):
        await _read_until(r1, "your_turn")
        await write_frame(w1, {"type": "play", "row": row, "col": 2})
        await _read_until(r1, "played")
        await _read_until(r2, "your_turn")
        await write_frame(w2, {"type": "play", "row": row, "col": 5})
        await _read_until(r2, "played")
    await _read_until(r1, "your_turn")
    await write_frame(w1, {"type": "pass"})
    await _read_until(r1, "passed")
    await _read_until(r2, "your_turn")
    await write_frame(w2, {"type": "pass"})
    g1 = await _read_until(r1, "game_end")
    g2 = await _read_until(r2, "game_end")
    assert g1 == g2
    assert g1["black_score"] == 27
    assert g1["white_score"] == 36
    assert g1["winner"] == "WHITE"

    await write_frame(w1, {"type": "rematch", "agree": False})
    await write_frame(w2, {"type": "rematch", "agree": False})
    await _shutdown(server, [w1, w2], task)


async def test_tcp_loopback_rematch_accept_starts_second_game():
    """Both agree to rematch; server swaps colors and sends fresh
    welcomes over the same TCP connection."""
    server, port, pending, ready = await _spin_up_server()
    r1, w1 = await asyncio.open_connection("127.0.0.1", port)
    r2, w2 = await asyncio.open_connection("127.0.0.1", port)
    await asyncio.wait_for(ready.wait(), timeout=2.0)
    task = asyncio.create_task(run_match_series(black=pending[0], white=pending[1], dead_stone_resolver=no_dead_stones))

    # Game 1: pass-pass.
    await _read_until(r1, "welcome")
    await _read_until(r2, "welcome")
    await _read_until(r1, "your_turn")
    await write_frame(w1, {"type": "pass"})
    await _read_until(r2, "your_turn")
    await write_frame(w2, {"type": "pass"})
    await _read_until(r1, "game_end")
    await _read_until(r2, "game_end")

    # Both agree → fresh welcomes with swapped colors.
    await write_frame(w1, {"type": "rematch", "agree": True})
    await write_frame(w2, {"type": "rematch", "agree": True})
    m1 = await _read_until(r1, "welcome")
    m2 = await _read_until(r2, "welcome")
    assert m1["color"] == "WHITE"
    assert m2["color"] == "BLACK"

    # Game 2: r2 now BLACK, plays first.
    await _read_until(r2, "your_turn")
    await write_frame(w2, {"type": "pass"})
    await _read_until(r1, "your_turn")
    await write_frame(w1, {"type": "pass"})
    await _read_until(r1, "game_end")
    await _read_until(r2, "game_end")

    await write_frame(w1, {"type": "rematch", "agree": False})
    await write_frame(w2, {"type": "rematch", "agree": False})
    await _shutdown(server, [w1, w2], task)


async def test_tcp_illegal_move_response_has_no_reason_field():
    """Protocol invariant on the wire: illegal replies are exactly
    {type, attempts_remaining} — nothing distinguishes the four
    rejection reasons (opponent-occupied, own-occupied, suicide, ko)."""
    server, port, pending, ready = await _spin_up_server()
    r1, w1 = await asyncio.open_connection("127.0.0.1", port)
    r2, w2 = await asyncio.open_connection("127.0.0.1", port)
    await asyncio.wait_for(ready.wait(), timeout=2.0)
    task = asyncio.create_task(run_match_series(black=pending[0], white=pending[1], dead_stone_resolver=no_dead_stones))

    await _read_until(r1, "welcome")
    await _read_until(r2, "welcome")
    await _read_until(r1, "your_turn")
    await write_frame(w1, {"type": "play", "row": 4, "col": 4})
    await _read_until(r1, "played")
    await _read_until(r2, "your_turn")
    # Try the same point — opponent-occupied; the server must reject
    # without leaking why.
    await write_frame(w2, {"type": "play", "row": 4, "col": 4})
    m = await _read_until(r2, "illegal")
    assert set(m.keys()) == {"type", "attempts_remaining"}
    assert m["attempts_remaining"] == 2

    # Resign so the test exits cleanly.
    await write_frame(w2, {"type": "resign"})
    await _read_until(r1, "game_end")
    await _read_until(r2, "game_end")
    await write_frame(w1, {"type": "rematch", "agree": False})
    await write_frame(w2, {"type": "rematch", "agree": False})
    await _shutdown(server, [w1, w2], task)


async def test_tcp_dead_marking_round_trip():
    """Run the full pass-pass → marking → approve → score flow over a
    real TCP connection so any frame-level regressions surface."""
    server, port, pending, ready = await _spin_up_server()
    r1, w1 = await asyncio.open_connection("127.0.0.1", port)
    r2, w2 = await asyncio.open_connection("127.0.0.1", port)
    await asyncio.wait_for(ready.wait(), timeout=2.0)
    # No resolver override — exercise the interactive default.
    task = asyncio.create_task(run_match_series(black=pending[0], white=pending[1]))

    await _read_until(r1, "welcome")
    await _read_until(r2, "welcome")
    # BLACK plays (0,0), WHITE plays (8,8), both pass.
    await _read_until(r1, "your_turn")
    await write_frame(w1, {"type": "play", "row": 0, "col": 0})
    await _read_until(r1, "played")
    await _read_until(r2, "your_turn")
    await write_frame(w2, {"type": "play", "row": 8, "col": 8})
    await _read_until(r2, "played")
    await _read_until(r1, "your_turn")
    await write_frame(w1, {"type": "pass"})
    await _read_until(r1, "passed")
    await _read_until(r2, "your_turn")
    await write_frame(w2, {"type": "pass"})

    # Both should now see dead_marking_started.
    m1 = await _read_until(r1, "dead_marking_started")
    m2 = await _read_until(r2, "dead_marking_started")
    assert m1["your_role"] == "marker"
    assert m2["your_role"] == "approver"

    # BLACK proposes WHITE's stone is dead, WHITE approves.
    await write_frame(w1, {"type": "mark_dead", "points": [[8, 8]]})
    proposal = await _read_until(r2, "dead_marking_proposal")
    assert proposal["points"] == [[8, 8]]
    await write_frame(w2, {"type": "mark_decision", "approve": True})

    # Both see game_end with WHITE's stone removed.
    g1 = await _read_until(r1, "game_end")
    g2 = await _read_until(r2, "game_end")
    assert g1 == g2
    assert g1["dead_stones"] == [[8, 8]]
    assert g1["full_board"][8 * BOARD_SIZE + 8] == 0
    assert g1["winner"] == "BLACK"

    await write_frame(w1, {"type": "rematch", "agree": False})
    await write_frame(w2, {"type": "rematch", "agree": False})
    await _shutdown(server, [w1, w2], task)


async def test_tcp_client_disconnect_mid_game_ends_series():
    """If a client drops mid-turn, the survivor receives a disconnect
    game_end and the match series terminates without offering a
    rematch."""
    server, port, pending, ready = await _spin_up_server()
    r1, w1 = await asyncio.open_connection("127.0.0.1", port)
    r2, w2 = await asyncio.open_connection("127.0.0.1", port)
    await asyncio.wait_for(ready.wait(), timeout=2.0)
    task = asyncio.create_task(run_match_series(black=pending[0], white=pending[1], dead_stone_resolver=no_dead_stones))

    await _read_until(r1, "welcome")
    await _read_until(r2, "welcome")
    await _read_until(r1, "your_turn")

    # BLACK hangs up. wait_closed is intentionally skipped; on Windows
    # ProactorEventLoop it can block on abruptly-closed sockets.
    w1.close()

    g = await _read_until(r2, "game_end")
    assert g["ended_by"] == "disconnect"
    assert g["resigner"] == "BLACK"
    assert g["winner"] == "WHITE"

    await _shutdown(server, [w2], task)
