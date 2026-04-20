"""JSON message protocol shared by LAN and Web transports.

Wire format (LAN): length-prefixed JSON. 4-byte big-endian unsigned length
followed by UTF-8 encoded JSON. For WebSockets the length is implicit in
the frame and messages are sent as JSON text.

Message types (all objects carry a 'type' field):

Client -> Server:
  {"type": "play", "row": int, "col": int}
  {"type": "pass"}
  {"type": "resign"}

Server -> Client:
  {"type": "welcome", "color": "BLACK"|"WHITE"}
  {"type": "your_turn", "view": <view_dict>, "losses_since_last_turn": int}
  {"type": "illegal", "attempts_remaining": int}   # 0 means auto-skip
  {"type": "played", "captured": int}              # legal move, turn ended
  {"type": "passed"}                               # voluntary pass, turn ended
  {"type": "game_end", "full_board": [...81...],
                       "black_score": int, "white_score": int,
                       "winner": "BLACK"|"WHITE"|null,
                       "ended_by": "pass"|"resign"|"disconnect",
                       "resigner": "BLACK"|"WHITE"|null}
  {"type": "error", "message": str}

view_dict:
  {"your_stones": [...81 ints; opponent stones zeroed by the server...],
   "attempts_remaining": int,
   "total_captured_by_me": int,
   "total_lost_by_me": int}

Invariant: no message distinguishes among the four illegal-move reasons
(opponent-occupied, own-occupied, suicide, ko). The `illegal` message
carries only `attempts_remaining`. This is a deliberate guarantee of the
hidden-information design and is asserted in tests.
"""
from __future__ import annotations

import asyncio
import json
import struct
from typing import Any

from core.view import PlayerView

FRAME_HEADER = struct.Struct("!I")
MAX_FRAME_BYTES = 64 * 1024


def encode(obj: dict[str, Any]) -> bytes:
    body = json.dumps(obj, separators=(",", ":")).encode("utf-8")
    if len(body) > MAX_FRAME_BYTES:
        raise ValueError(f"Message too large: {len(body)} bytes")
    return FRAME_HEADER.pack(len(body)) + body


def decode(body: bytes) -> dict[str, Any]:
    return json.loads(body.decode("utf-8"))


async def read_frame(reader: asyncio.StreamReader) -> dict[str, Any] | None:
    """Read one length-prefixed frame. Returns None on clean EOF."""
    try:
        header = await reader.readexactly(4)
    except asyncio.IncompleteReadError:
        return None
    (length,) = FRAME_HEADER.unpack(header)
    if length > MAX_FRAME_BYTES:
        raise ValueError(f"Incoming frame too large: {length}")
    try:
        body = await reader.readexactly(length)
    except asyncio.IncompleteReadError:
        return None
    return decode(body)


async def write_frame(writer: asyncio.StreamWriter, obj: dict[str, Any]) -> None:
    writer.write(encode(obj))
    await writer.drain()


def view_to_dict(view: PlayerView) -> dict[str, Any]:
    return {
        "your_stones": list(view.own_stones),
        "attempts_remaining": view.attempts_remaining,
        "total_captured_by_me": view.total_captured_by_me,
        "total_lost_by_me": view.total_lost_by_me,
    }
