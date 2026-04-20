"""LAN client: connects to a server and plays one side of the game.

Run: python -m transport.lan.client [--host HOST] [--port PORT]
"""
from __future__ import annotations

import argparse
import asyncio
import sys

from core.board import Color
from frontend.common import (
    HELP_TEXT,
    color_name,
    parse_command,
    render_board_stones,
)
from protocol.messages import read_frame, write_frame


async def ainput(prompt: str) -> str:
    return await asyncio.to_thread(input, prompt)


def _print_view(view: dict, losses: int) -> None:
    print()
    print(render_board_stones(view["your_stones"]))
    print()
    if losses > 0:
        print(f"  ! Since your last turn, you lost {losses} stone(s).")
    print(f"  You have captured {view['total_captured_by_me']} opponent stone(s) total.")
    print(f"  Opponent has captured {view['total_lost_by_me']} of your stones total.")
    print(f"  Attempts remaining this turn: {view['attempts_remaining']}")
    print()


def _print_game_end(msg: dict) -> None:
    print()
    print("=" * 60)
    print("  GAME OVER  -  Full board revealed")
    print("=" * 60)
    print()
    print(render_board_stones(msg["full_board"]))
    print()
    print("  Chinese area scoring (no komi):")
    print(f"    BLACK (X): {msg['black_score']}")
    print(f"    WHITE (O): {msg['white_score']}")
    ended_by = msg.get("ended_by")
    if ended_by == "resign":
        print(f"  {msg.get('resigner')} resigned.")
    elif ended_by == "disconnect":
        print(f"  {msg.get('resigner')} disconnected.")
    w = msg.get("winner")
    if w is None:
        print("  Draw.")
    else:
        print(f"  {w} wins.")
    print()


async def run_client(host: str, port: int) -> int:
    try:
        reader, writer = await asyncio.open_connection(host, port)
    except OSError as e:
        print(f"Could not connect to {host}:{port} ({e}).")
        return 1
    print(f"Connected to {host}:{port}. Waiting for game to start...")

    my_color: Color | None = None
    try:
        while True:
            msg = await read_frame(reader)
            if msg is None:
                print("Server closed the connection.")
                return 1
            t = msg.get("type")

            if t == "welcome":
                my_color = Color.BLACK if msg["color"] == "BLACK" else Color.WHITE
                print(f"You are {color_name(my_color)}. Type 'help' for commands.")
                print("Waiting for opponent / your turn...")
                continue

            if t == "your_turn":
                _print_view(msg["view"], msg.get("losses_since_last_turn", 0))
                if not await _input_loop(reader, writer, my_color):
                    return 0
                continue

            if t == "game_end":
                _print_game_end(msg)
                return 0

            if t == "error":
                print(f"Server error: {msg.get('message')}")
                continue

            print(f"(unexpected message from server: {msg!r})")
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass


async def _input_loop(reader, writer, my_color: Color | None) -> bool:
    """Prompt the user for moves until the turn ends.

    Returns False if the game is over (game_end seen during this turn) or
    the user quit; True if the turn ended normally and the outer loop
    should keep waiting for messages.
    """
    while True:
        try:
            raw = await ainput(f"  {color_name(my_color)} move: ")
        except EOFError:
            return False
        try:
            kind, point = parse_command(raw)
        except ValueError as e:
            print(f"  {e}")
            continue
        if kind == "help":
            print(HELP_TEXT)
            continue
        if kind == "quit":
            print("  Quitting.")
            return False
        if kind == "resign":
            await write_frame(writer, {"type": "resign"})
        elif kind == "pass":
            await write_frame(writer, {"type": "pass"})
        else:
            assert point is not None
            await write_frame(
                writer, {"type": "play", "row": point[0], "col": point[1]}
            )

        reply = await read_frame(reader)
        if reply is None:
            print("Server closed the connection.")
            return False
        rt = reply.get("type")
        if rt == "illegal":
            attempts = reply.get("attempts_remaining", 0)
            if attempts > 0:
                print(f"  ILLEGAL. ({attempts} attempt(s) remaining.)")
                continue
            print("  Three illegal attempts. Turn auto-skipped.")
            return True
        if rt == "played":
            cap = reply.get("captured", 0)
            if cap > 0:
                print(f"  Move played. You captured {cap} stone(s).")
            else:
                print("  Move played.")
            return True
        if rt == "passed":
            print("  You passed.")
            return True
        if rt == "game_end":
            _print_game_end(reply)
            return False
        if rt == "error":
            print(f"  Server error: {reply.get('message')}")
            continue
        print(f"  (unexpected reply: {reply!r})")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5555)
    args = parser.parse_args()
    return asyncio.run(run_client(args.host, args.port))


if __name__ == "__main__":
    sys.exit(main())
