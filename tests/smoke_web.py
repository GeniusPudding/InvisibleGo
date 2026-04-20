"""Manual smoke test: drive two WebSocket clients through a complete game.

Not run in CI (it requires a live uvicorn process) — run by hand:

  uvicorn transport.web.server:app --host 127.0.0.1 --port 8765 &
  python tests/smoke_web.py
"""
from __future__ import annotations

import asyncio
import json
import sys

import websockets

URL = "ws://127.0.0.1:8765/ws"


async def receive_until(ws, type_):
    while True:
        raw = await ws.recv()
        msg = json.loads(raw)
        if msg.get("type") == type_:
            return msg


async def player(name, moves):
    """Drive one player. `moves` is a list of dicts to send when our turn arrives."""
    async with websockets.connect(URL) as ws:
        welcome = json.loads(await ws.recv())
        assert welcome["type"] == "welcome", welcome
        assigned = welcome["color"]
        print(f"[{name}] welcome -> assigned {assigned}")
        i = 0
        while True:
            msg = json.loads(await ws.recv())
            t = msg["type"]
            if t == "your_turn":
                print(f"[{name}] your_turn (losses={msg['losses_since_last_turn']}, attempts={msg['view']['attempts_remaining']})")
                # Send the next move
                if i >= len(moves):
                    raise RuntimeError(f"[{name}] ran out of scripted moves")
                await ws.send(json.dumps(moves[i]))
                i += 1
                # Read replies until turn ends
                while True:
                    reply = json.loads(await ws.recv())
                    rt = reply["type"]
                    print(f"[{name}]   <- {rt} {reply}")
                    if rt == "illegal" and reply["attempts_remaining"] > 0:
                        await ws.send(json.dumps(moves[i]))
                        i += 1
                        continue
                    if rt in ("played", "passed", "illegal"):
                        break
                    if rt == "game_end":
                        print(f"[{name}] game_end during turn: winner={reply['winner']}")
                        return reply
            elif t == "game_end":
                print(f"[{name}] game_end: winner={msg['winner']}, score B={msg['black_score']} W={msg['white_score']}")
                return msg
            elif t == "error":
                print(f"[{name}] ERROR: {msg}")
            else:
                print(f"[{name}] unexpected: {msg}")


async def main():
    # Black plays E5 ((4,4)), then passes.
    # White plays F6 ((3,5)), then passes.
    black_moves = [
        {"type": "play", "row": 4, "col": 4},
        {"type": "pass"},
    ]
    white_moves = [
        {"type": "play", "row": 3, "col": 5},
        {"type": "pass"},
    ]
    # Stagger connects so first becomes BLACK
    black_task = asyncio.create_task(player("black", black_moves))
    await asyncio.sleep(0.2)
    white_task = asyncio.create_task(player("white", white_moves))
    results = await asyncio.gather(black_task, white_task)
    for r in results:
        assert r["type"] == "game_end"
    print("smoke test ok")


if __name__ == "__main__":
    sys.exit(asyncio.run(main()) or 0)
