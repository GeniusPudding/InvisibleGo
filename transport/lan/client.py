"""LAN client: connects to a server and plays one side of the game.

Run: python -m transport.lan.client [--host HOST] [--port PORT]
"""
from __future__ import annotations

import argparse
import asyncio
import sys

from core.board import Color
from core.board import BOARD_SIZE
from frontend.common import (
    HELP_TEXT,
    COLS,
    color_name,
    format_point,
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


def _bfs_group(stones: list[int], r0: int, c0: int) -> list[tuple[int, int]]:
    v = stones[r0 * BOARD_SIZE + c0]
    if v == 0:
        return []
    seen: set[tuple[int, int]] = set()
    out: list[tuple[int, int]] = []
    stack = [(r0, c0)]
    while stack:
        r, c = stack.pop()
        if (r, c) in seen:
            continue
        seen.add((r, c))
        if stones[r * BOARD_SIZE + c] != v:
            continue
        out.append((r, c))
        for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            nr, nc = r + dr, c + dc
            if 0 <= nr < BOARD_SIZE and 0 <= nc < BOARD_SIZE:
                stack.append((nr, nc))
    return out


async def _marker_mark_loop(writer, board: list[int]) -> None:
    """Prompt the marker for representative stones; expand each click to
    its connected group. Blank line submits. 'reset' clears."""
    print()
    print("  Enter coordinates of stones in dead groups, one per line.")
    print("  Each entry expands to the whole connected group. Toggle by")
    print("  re-entering. Blank line = submit. Type 'reset' to clear.")
    dead: set[tuple[int, int]] = set()
    while True:
        try:
            line = (await ainput("    > ")).strip()
        except EOFError:
            break
        if not line:
            break
        if line.lower() == "reset":
            dead.clear()
            print("    cleared.")
            continue
        try:
            kind, point = parse_command(line)
        except ValueError as e:
            print(f"    {e}")
            continue
        if kind != "play" or point is None:
            print("    Use a coordinate like B5.")
            continue
        group = _bfs_group(board, point[0], point[1])
        if not group:
            print("    No stone at that point.")
            continue
        if any(p in dead for p in group):
            for p in group:
                dead.discard(p)
            print(f"    Unmarked {len(group)} stone(s).")
        else:
            for p in group:
                dead.add(p)
            print(f"    Marked {len(group)} stone(s) as dead.")
    points = [list(p) for p in sorted(dead)]
    await write_frame(writer, {"type": "mark_dead", "points": points})
    print(f"  Submitted {len(points)} dead point(s). Waiting for opponent...")


async def _approver_decide(writer, board: list[int], points: list) -> None:
    print()
    print(f"  Opponent proposed {len(points)} dead stone(s):")
    if not points:
        print("    (none — opponent claims nothing is dead)")
    else:
        coords = ", ".join(format_point((int(r), int(c))) for r, c in points)
        print(f"    {coords}")
    while True:
        try:
            ans = (await ainput("  Approve? [y/n]: ")).strip().lower()
        except EOFError:
            ans = "n"
        if ans in ("y", "yes"):
            await write_frame(writer, {"type": "mark_decision", "approve": True})
            print("  Approved. Computing final score...")
            return
        if ans in ("n", "no"):
            await write_frame(writer, {"type": "mark_decision", "approve": False})
            print("  Rejected. Opponent will mark again.")
            return


async def run_client(host: str, port: int) -> int:
    try:
        reader, writer = await asyncio.open_connection(host, port)
    except OSError as e:
        print(f"Could not connect to {host}:{port} ({e}).")
        return 1
    print(f"Connected to {host}:{port}. Waiting for game to start...")

    my_color: Color | None = None
    marking_role: str | None = None
    revealed_board: list[int] = []
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

            if t == "dead_marking_started":
                marking_role = msg.get("your_role")
                revealed_board = list(msg.get("full_board", []))
                print()
                print("=" * 60)
                print("  DEAD-STONE MARKING PHASE")
                print("=" * 60)
                print(render_board_stones(revealed_board))
                if marking_role == "marker":
                    print("  You are the MARKER.")
                    await _marker_mark_loop(writer, revealed_board)
                else:
                    print("  You are the APPROVER. Wait for opponent's proposal.")
                continue

            if t == "dead_marking_proposal":
                await _approver_decide(writer, revealed_board, msg.get("points", []))
                continue

            if t == "dead_marking_rejected":
                print("  Opponent rejected your marks. Mark again.")
                if revealed_board:
                    await _marker_mark_loop(writer, revealed_board)
                continue

            if t == "game_end":
                _print_game_end(msg)
                if msg.get("ended_by") == "disconnect":
                    return 0
                try:
                    ans = await ainput("  Rematch? [y/n]: ")
                except EOFError:
                    ans = "n"
                agree = ans.strip().lower().startswith("y")
                await write_frame(writer, {"type": "rematch", "agree": agree})
                if not agree:
                    return 0
                print("  Waiting for opponent's answer...")
                continue

            if t == "rematch_declined":
                print("  Opponent declined the rematch.")
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
        if rt == "turn_timeout":
            print("  Turn timed out — auto-passed.")
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
