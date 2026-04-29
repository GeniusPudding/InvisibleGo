"""Web server: FastAPI + WebSocket with matchmaking for multiple concurrent games.

Lobby protocol (before the game begins):

Client -> Server (first message after ws accept):
  {"type": "join_random", "name": "Alice"}
  {"type": "create_room", "name": "Alice"}
  {"type": "join_room",   "name": "Alice", "code": "ABCD"}

Server -> Client (lobby replies):
  {"type": "room_created", "code": "ABCD"}     # from create_room
  {"type": "room_error",   "reason": "not_found"}  # bad code

After pairing, both clients transition into the normal game protocol
(welcome, your_turn, illegal, played, passed, game_end) exactly as in
the single-game transport.

Run: uvicorn transport.web.server:app --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from transport.session import Connection, run_match_series
from transport.web.matchmaker import Matchmaker, RoomNotFound

log = logging.getLogger("invisiblego.web")

_STATIC_DIR = Path(__file__).resolve().parents[2] / "frontend" / "web"

app = FastAPI(title="InvisibleGo")
app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(_STATIC_DIR / "index.html")


class WsConnection(Connection):
    def __init__(self, ws: WebSocket) -> None:
        self.ws = ws
        self._closed = False

    async def send(self, msg: dict[str, Any]) -> None:
        if self._closed:
            return
        try:
            await self.ws.send_json(msg)
        except Exception:
            self._closed = True

    async def recv(self) -> dict[str, Any] | None:
        if self._closed:
            return None
        try:
            return await self.ws.receive_json()
        except (WebSocketDisconnect, RuntimeError):
            self._closed = True
            return None


async def _run_game_session(
    black_ws: WebSocket,
    black_name: str,
    white_ws: WebSocket,
    white_name: str,
) -> None:
    await run_match_series(
        black=WsConnection(black_ws),
        white=WsConnection(white_ws),
        black_name=black_name,
        white_name=white_name,
    )


matchmaker = Matchmaker(session_runner=_run_game_session)


@app.get("/stats")
async def stats() -> dict[str, Any]:
    return matchmaker.pending_counts()


@app.websocket("/ws")
async def ws_handler(ws: WebSocket) -> None:
    await ws.accept()
    try:
        raw = await ws.receive_json()
    except (WebSocketDisconnect, RuntimeError):
        return

    msg_type = raw.get("type")
    name = (raw.get("name") or "anon").strip()[:32] or "anon"

    done: asyncio.Event | None = None
    try:
        if msg_type == "join_random":
            log.info("join_random name=%s", name)
            done = await matchmaker.join_random(ws, name)

        elif msg_type == "create_room":
            code, fut = await matchmaker.create_room(ws, name)
            log.info("create_room name=%s code=%s", name, code)
            try:
                await ws.send_json({"type": "room_created", "code": code})
            except Exception:
                return
            done = await fut

        elif msg_type == "join_room":
            code = (raw.get("code") or "").strip().upper()
            log.info("join_room name=%s code=%s", name, code)
            try:
                done = await matchmaker.join_room(code, ws, name)
            except RoomNotFound:
                try:
                    await ws.send_json(
                        {"type": "room_error", "reason": "not_found"}
                    )
                except Exception:
                    pass
                return

        else:
            try:
                await ws.send_json(
                    {
                        "type": "error",
                        "message": f"First message must be a join_* command, got {msg_type!r}",
                    }
                )
            except Exception:
                pass
            return
    except WebSocketDisconnect:
        return

    if done is not None:
        try:
            await done.wait()
        except Exception:
            pass
