import asyncio

from core.board import BOARD_SIZE, Color
from core.game import GameState
from protocol.messages import (
    FRAME_HEADER,
    decode,
    encode,
    read_frame,
    view_to_dict,
    write_frame,
)


def test_encode_prepends_length_header():
    msg = {"type": "play", "row": 4, "col": 4}
    body = encode(msg)
    assert len(body) >= 4
    (declared,) = FRAME_HEADER.unpack(body[:4])
    assert declared == len(body) - 4


def test_decode_roundtrip():
    msg = {"type": "play", "row": 4, "col": 4}
    body = encode(msg)
    decoded = decode(body[4:])
    assert decoded == msg


def test_view_to_dict_hides_opponent():
    g = GameState()
    g.play(Color.BLACK, (4, 4))
    g.play(Color.WHITE, (4, 5))
    d = view_to_dict(g.view(Color.BLACK))
    assert d["your_stones"][4 * BOARD_SIZE + 4] == Color.BLACK.value
    assert d["your_stones"][4 * BOARD_SIZE + 5] == Color.EMPTY.value


async def test_async_frame_roundtrip_over_loopback():
    """Spin up a tiny TCP echo server and round-trip one frame through it."""
    received: list[dict] = []
    server_done = asyncio.Event()

    async def handle(reader, writer):
        msg = await read_frame(reader)
        if msg is not None:
            received.append(msg)
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        server_done.set()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    payload = {"type": "welcome", "color": "BLACK"}

    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    await write_frame(writer, payload)
    writer.close()
    try:
        await writer.wait_closed()
    except Exception:
        pass
    await server_done.wait()
    server.close()
    await server.wait_closed()

    assert received == [payload]
