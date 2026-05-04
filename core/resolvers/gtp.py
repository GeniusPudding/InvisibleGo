"""Generic GTP engine wrapper.

Talks GTP over a subprocess: send command, read until a `=` or `?` line
followed by a blank line. Used by the KataGo and GNU Go resolvers. Not
a complete GTP client — only the commands we need.
"""
from __future__ import annotations

import asyncio
import shutil
from pathlib import Path
from typing import Sequence

from core.board import BOARD_SIZE, Board, Color, Point
from core.resolvers.chain import EngineUnavailable

# 9x9 GTP coordinates: columns A..J skipping I, rows 1..9.
_GTP_COLS = "ABCDEFGHJ"


class GtpProtocolError(RuntimeError):
    """The engine returned `?` (error) or malformed output."""


def point_to_gtp(p: Point) -> str:
    r, c = p
    return f"{_GTP_COLS[c]}{BOARD_SIZE - r}"


def gtp_to_point(s: str) -> Point:
    s = s.strip().upper()
    if s in ("PASS", "RESIGN", ""):
        raise ValueError(f"not a coordinate: {s}")
    col = _GTP_COLS.index(s[0])
    row = BOARD_SIZE - int(s[1:])
    return (row, col)


class GtpEngine:
    """Async wrapper around a GTP-speaking subprocess.

    Use as an async context manager:
        async with GtpEngine(["gnugo", "--mode", "gtp"]) as engine:
            await engine.command("boardsize 9")
            ...
    """

    def __init__(
        self,
        argv: Sequence[str],
        *,
        startup_timeout: float = 5.0,
        command_timeout: float = 30.0,
    ) -> None:
        self.argv = list(argv)
        self.startup_timeout = startup_timeout
        self.command_timeout = command_timeout
        self.proc: asyncio.subprocess.Process | None = None

    async def __aenter__(self) -> "GtpEngine":
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    async def start(self) -> None:
        binary = self.argv[0]
        # Fail fast with EngineUnavailable rather than the OS-level error
        # so the chain can catch it cleanly.
        if not Path(binary).is_absolute() and shutil.which(binary) is None:
            raise EngineUnavailable(f"binary not found on PATH: {binary}")
        try:
            self.proc = await asyncio.wait_for(
                asyncio.create_subprocess_exec(
                    *self.argv,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                ),
                timeout=self.startup_timeout,
            )
        except (asyncio.TimeoutError, OSError) as e:
            raise EngineUnavailable(f"failed to start {binary}: {e}") from e

    async def close(self) -> None:
        if self.proc is None:
            return
        try:
            await self.command("quit", timeout=2.0)
        except Exception:
            pass
        try:
            self.proc.terminate()
        except ProcessLookupError:
            pass
        try:
            await asyncio.wait_for(self.proc.wait(), timeout=2.0)
        except asyncio.TimeoutError:
            try:
                self.proc.kill()
            except ProcessLookupError:
                pass
        self.proc = None

    async def command(self, cmd: str, *, timeout: float | None = None) -> str:
        """Send a GTP command, return the response body (without the
        leading `= ` or `? `, no trailing blank line)."""
        if self.proc is None or self.proc.stdin is None or self.proc.stdout is None:
            raise EngineUnavailable("engine not running")
        timeout = timeout if timeout is not None else self.command_timeout
        try:
            self.proc.stdin.write((cmd + "\n").encode("utf-8"))
            await self.proc.stdin.drain()
        except (BrokenPipeError, ConnectionResetError) as e:
            raise EngineUnavailable(f"engine pipe broken: {e}") from e

        lines: list[str] = []
        try:
            while True:
                line = await asyncio.wait_for(
                    self.proc.stdout.readline(), timeout=timeout
                )
                if not line:
                    raise EngineUnavailable("engine closed stdout unexpectedly")
                decoded = line.decode("utf-8", errors="replace").rstrip("\r\n")
                if not lines and not decoded:
                    # Some engines emit a leading blank — skip.
                    continue
                if not decoded:
                    break
                lines.append(decoded)
        except asyncio.TimeoutError as e:
            raise GtpProtocolError(f"timeout waiting for response to {cmd!r}") from e

        if not lines:
            raise GtpProtocolError(f"empty response to {cmd!r}")
        first = lines[0]
        if first.startswith("?"):
            raise GtpProtocolError(f"engine error: {first[1:].strip()}")
        if not first.startswith("="):
            raise GtpProtocolError(f"unexpected reply: {first!r}")
        # Strip leading "= " or "=N " (response id).
        rest = first[1:].lstrip()
        # Some engines split id from body; the regex isn't worth it for
        # our limited use — we never send IDs ourselves.
        head_body_split = rest.split(" ", 1) if rest and rest[0].isdigit() else None
        if head_body_split and head_body_split[0].isdigit():
            body0 = head_body_split[1] if len(head_body_split) > 1 else ""
        else:
            body0 = rest
        body = "\n".join([body0, *lines[1:]]).strip()
        return body

    async def setup_board(self, board: Board, komi: float = 7.5) -> None:
        """Reset and load a position via `clear_board` + `play` commands."""
        await self.command(f"boardsize {BOARD_SIZE}")
        await self.command("clear_board")
        await self.command(f"komi {komi}")
        for r in range(BOARD_SIZE):
            for c in range(BOARD_SIZE):
                color = board.at((r, c))
                if color is Color.BLACK:
                    await self.command(f"play B {point_to_gtp((r, c))}")
                elif color is Color.WHITE:
                    await self.command(f"play W {point_to_gtp((r, c))}")
