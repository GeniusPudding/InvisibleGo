"""LAN game server: accepts two TCP connections and runs one game.

The first client to connect is assigned BLACK, the second WHITE. After
the second connects the server begins the game and runs it to completion,
then closes both sockets and exits.

Run: python -m transport.lan.server [--host HOST] [--port PORT]
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from typing import Any

from protocol.messages import read_frame, write_frame
from transport.session import Connection, GameSession


class TcpConnection(Connection):
    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.reader = reader
        self.writer = writer

    async def send(self, msg: dict[str, Any]) -> None:
        await write_frame(self.writer, msg)

    async def recv(self) -> dict[str, Any] | None:
        try:
            return await read_frame(self.reader)
        except (ConnectionResetError, BrokenPipeError):
            return None

    async def close(self) -> None:
        try:
            self.writer.close()
            await self.writer.wait_closed()
        except Exception:
            pass


async def run_server(host: str, port: int) -> int:
    pending: list[TcpConnection] = []
    ready = asyncio.Event()

    async def on_connect(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        if len(pending) >= 2:
            try:
                await write_frame(
                    writer, {"type": "error", "message": "Game already has two players."}
                )
            finally:
                writer.close()
            return
        pending.append(TcpConnection(reader, writer))
        peer = writer.get_extra_info("peername")
        logging.info("Client %d/2 connected from %s", len(pending), peer)
        if len(pending) == 2:
            ready.set()

    server = await asyncio.start_server(on_connect, host, port)
    sockets = server.sockets or ()
    bound = ", ".join(str(s.getsockname()) for s in sockets)
    logging.info("Listening on %s", bound)

    async with server:
        await ready.wait()
        session = GameSession(black=pending[0], white=pending[1])
        try:
            await session.run()
        finally:
            for conn in pending:
                await conn.close()
    logging.info("Game finished; server exiting.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=5555)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    return asyncio.run(run_server(args.host, args.port))


if __name__ == "__main__":
    sys.exit(main())
