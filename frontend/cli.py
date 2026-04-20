"""Hotseat CLI for two local players on one terminal.

Between turns the screen is cleared and a "hand over the device" prompt
blocks until the next player confirms they are ready. Each player only
ever sees their own stones.

Run: python -m frontend.cli
"""
from __future__ import annotations

import os
import sys

from core.board import Color
from core.game import GameState, MoveOutcome
from core.scoring import area_score
from frontend.common import (
    HELP_TEXT,
    color_name,
    parse_command,
    render_board_stones,
)


def clear_screen() -> None:
    os.system("cls" if os.name == "nt" else "clear")


def handoff(next_color: Color) -> None:
    clear_screen()
    print("=" * 60)
    print(f"  Next turn: {color_name(next_color)}")
    print("=" * 60)
    print()
    print(f"  Hand the device to {color_name(next_color)}.")
    print("  The other player should look away.")
    print()
    try:
        input("  Press Enter when ready... ")
    except EOFError:
        sys.exit(0)
    clear_screen()


def end_game(game: GameState) -> None:
    clear_screen()
    print("=" * 60)
    print("  GAME OVER  -  Full board revealed")
    print("=" * 60)
    print()
    print(render_board_stones(game.board.stones))
    print()
    score = area_score(game.board)
    print("  Chinese area scoring (no komi):")
    print(f"    BLACK (X): {score.black}")
    print(f"    WHITE (O): {score.white}")
    print()
    winner = score.winner
    if winner is Color.BLACK:
        print("  BLACK wins.")
    elif winner is Color.WHITE:
        print("  WHITE wins.")
    else:
        print("  Draw.")
    print()
    print(f"  Total stones captured by BLACK: {game.captured_by[Color.BLACK]}")
    print(f"  Total stones captured by WHITE: {game.captured_by[Color.WHITE]}")
    print()


def run_turn(game: GameState) -> bool:
    color = game.to_move
    handoff(color)
    losses = game.consume_pending_losses(color)
    shown_losses = False
    while True:
        view = game.view(color)
        print(render_board_stones(view.own_stones))
        print()
        if losses > 0 and not shown_losses:
            print(f"  ! Since your last turn, you lost {losses} stone(s).")
            shown_losses = True
        print(f"  You have captured {view.total_captured_by_me} opponent stone(s) total.")
        print(f"  Opponent has captured {view.total_lost_by_me} of your stones total.")
        print(f"  Attempts remaining this turn: {view.attempts_remaining}")
        print()
        try:
            raw = input(f"  {color_name(color)} move: ")
        except EOFError:
            return False

        try:
            kind, point = parse_command(raw)
        except ValueError as e:
            print(f"  {e}")
            print()
            continue

        if kind == "help":
            print(HELP_TEXT)
            print()
            continue
        if kind == "quit":
            print("  Quitting without scoring.")
            return False
        if kind == "resign":
            other = color.opponent()
            print(f"  {color_name(color)} resigns. {color_name(other)} wins.")
            return False

        if kind == "pass":
            result = game.pass_turn(color)
        else:
            assert point is not None
            result = game.play(color, point)

        if result.outcome is MoveOutcome.ILLEGAL and not result.turn_ended:
            print(f"  ILLEGAL. ({result.attempts_remaining} attempt(s) remaining.)")
            print()
            continue

        if result.turn_ended:
            if result.outcome is MoveOutcome.ILLEGAL:
                print("  Three illegal attempts. Turn auto-skipped.")
            elif kind == "pass":
                print("  You passed.")
            elif result.captured_count > 0:
                print(f"  Move played. You captured {result.captured_count} stone(s).")
            else:
                print("  Move played.")
            try:
                input("  Press Enter to end your turn... ")
            except EOFError:
                return False
            return True

        if result.outcome is MoveOutcome.GAME_OVER:
            return True


def main() -> int:
    game = GameState()
    clear_screen()
    print("InvisibleGo  -  hotseat 2-player")
    print()
    print("You will take turns on one device. Between turns the screen clears")
    print("and you hand it to the other player. Neither of you sees the other's stones.")
    print()
    print("Type 'help' during your turn for commands.")
    print()
    try:
        input("Press Enter to start... ")
    except EOFError:
        return 0

    while not game.is_over:
        if not run_turn(game):
            return 0

    end_game(game)
    return 0


if __name__ == "__main__":
    sys.exit(main())
