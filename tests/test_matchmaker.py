"""Matchmaker unit tests — no WebSockets, just paired async futures."""
import asyncio

import pytest

from transport.web.matchmaker import Matchmaker, RoomNotFound


@pytest.fixture
def pairs_seen():
    """Per-test list that the injected session_runner appends to."""
    return []


@pytest.fixture
def matchmaker(pairs_seen):
    async def fake_runner(black, black_name, white, white_name):
        pairs_seen.append((black, black_name, white, white_name))
        # Simulate a brief game
        await asyncio.sleep(0)

    return Matchmaker(session_runner=fake_runner)


async def test_random_pairs_two_arrivals(matchmaker, pairs_seen):
    a_done_task = asyncio.create_task(matchmaker.join_random("A", "Alice"))
    await asyncio.sleep(0)  # let it register
    assert not a_done_task.done()
    b_done = await matchmaker.join_random("B", "Bob")
    a_done = await a_done_task
    # Both sides should be watching the same done event
    assert a_done is b_done
    await a_done.wait()
    # Alice arrived first → BLACK; Bob → WHITE
    assert pairs_seen == [("A", "Alice", "B", "Bob")]


async def test_two_pairs_play_concurrently(matchmaker, pairs_seen):
    # 4 random arrivals should produce 2 concurrent sessions
    a = asyncio.create_task(matchmaker.join_random("A", "Alice"))
    b = asyncio.create_task(matchmaker.join_random("B", "Bob"))
    c = asyncio.create_task(matchmaker.join_random("C", "Carol"))
    d = asyncio.create_task(matchmaker.join_random("D", "Dan"))
    done_events = await asyncio.gather(a, b, c, d)
    for ev in done_events:
        await ev.wait()
    # Two sessions, consistent pairing (first-to-arrive = black)
    assert sorted(pairs_seen) == sorted([
        ("A", "Alice", "B", "Bob"),
        ("C", "Carol", "D", "Dan"),
    ])


async def test_create_and_join_room(matchmaker, pairs_seen):
    code, fut = await matchmaker.create_room("host_conn", "Alice")
    assert len(code) == 4
    # Joiner arrives with the code
    done_b = await matchmaker.join_room(code, "joiner_conn", "Bob")
    done_a = await fut
    assert done_a is done_b
    await done_a.wait()
    assert pairs_seen == [("host_conn", "Alice", "joiner_conn", "Bob")]


async def test_join_room_unknown_code_raises(matchmaker):
    with pytest.raises(RoomNotFound):
        await matchmaker.join_room("NOPE", "c", "Bob")


async def test_room_codes_are_unique(matchmaker):
    # Create a handful of rooms, verify codes don't collide
    codes = set()
    for i in range(20):
        code, _ = await matchmaker.create_room(f"c{i}", f"P{i}")
        assert code not in codes
        codes.add(code)
    assert len(codes) == 20
