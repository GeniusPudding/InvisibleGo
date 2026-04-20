from dataclasses import fields

from core.board import Color
from core.game import GameState, MoveOutcome, MoveResult


def test_black_plays_first():
    g = GameState()
    assert g.to_move is Color.BLACK


def test_legal_move_advances_turn():
    g = GameState()
    r = g.play(Color.BLACK, (4, 4))
    assert r.outcome is MoveOutcome.OK
    assert r.turn_ended
    assert g.to_move is Color.WHITE
    assert g.attempts_remaining == 3


def test_wrong_player_is_illegal_but_does_not_decrement_attempts():
    g = GameState()
    r = g.play(Color.WHITE, (4, 4))
    assert r.outcome is MoveOutcome.ILLEGAL
    # It wasn't their turn; attempts counter belongs to the player whose turn it IS
    assert g.to_move is Color.BLACK
    assert g.attempts_remaining == 3


def test_own_occupied_is_illegal_and_decrements():
    g = GameState()
    g.play(Color.BLACK, (4, 4))
    g.play(Color.WHITE, (0, 0))
    r = g.play(Color.BLACK, (4, 4))  # Black tries own stone
    assert r.outcome is MoveOutcome.ILLEGAL
    assert r.attempts_remaining == 2
    assert not r.turn_ended


def test_opponent_occupied_is_illegal_with_no_distinguishing_field():
    g = GameState()
    g.play(Color.BLACK, (4, 4))
    # White tries to play on Black's stone
    r = g.play(Color.WHITE, (4, 4))
    assert r.outcome is MoveOutcome.ILLEGAL
    assert r.attempts_remaining == 2
    # Invariant: the MoveResult schema has no 'reason' field. Enumerate fields
    # to prove this structurally.
    field_names = {f.name for f in fields(MoveResult)}
    assert "reason" not in field_names
    assert "illegal_reason" not in field_names


def test_three_illegal_attempts_auto_skip_turn():
    g = GameState()
    g.play(Color.BLACK, (4, 4))
    # White tries 3 illegal moves on Black's stone
    r1 = g.play(Color.WHITE, (4, 4))
    r2 = g.play(Color.WHITE, (4, 4))
    r3 = g.play(Color.WHITE, (4, 4))
    assert r1.attempts_remaining == 2 and not r1.turn_ended
    assert r2.attempts_remaining == 1 and not r2.turn_ended
    assert r3.attempts_remaining == 0 and r3.turn_ended
    assert r3.outcome is MoveOutcome.ILLEGAL
    assert g.to_move is Color.BLACK
    assert g.attempts_remaining == 3


def test_suicide_is_illegal():
    g = GameState()
    # Surround (0,0) with white, then Black tries suicide at (0,0)
    g.play(Color.BLACK, (4, 4))  # filler
    g.play(Color.WHITE, (0, 1))
    g.play(Color.BLACK, (5, 5))  # filler
    g.play(Color.WHITE, (1, 0))
    r = g.play(Color.BLACK, (0, 0))
    assert r.outcome is MoveOutcome.ILLEGAL


def test_capture_removes_opponent_stones():
    g = GameState()
    # White in corner, Black surrounds
    g.play(Color.BLACK, (0, 1))
    g.play(Color.WHITE, (0, 0))
    r = g.play(Color.BLACK, (1, 0))
    assert r.outcome is MoveOutcome.OK
    assert r.captured_count == 1
    assert g.board.at((0, 0)) is Color.EMPTY
    assert g.captured_by[Color.BLACK] == 1
    assert g.pending_losses[Color.WHITE] == 1


def test_capture_before_suicide_is_legal():
    g = GameState()
    # Classic last-liberty capture: White stone at (0,0) with libs (0,1),(1,0)
    # Black plays (1,0) which would be suicide normally, but it captures white at (0,0)
    # Setup: white (0,0), black (0,1). Black plays (1,0) - captures white.
    g.play(Color.BLACK, (4, 4))  # filler to give white first real move
    g.play(Color.WHITE, (0, 0))
    g.play(Color.BLACK, (0, 1))
    g.play(Color.WHITE, (8, 8))  # filler
    r = g.play(Color.BLACK, (1, 0))
    assert r.outcome is MoveOutcome.OK
    assert r.captured_count == 1


def test_ko_recapture_is_illegal():
    g = GameState()
    # Build a ko shape:
    # . B W .
    # B . B W
    # . B W .
    # Focus on square (1,1) and (1,2).
    # Black: (0,1), (1,0), (2,1)
    # White: (0,2), (1,3), (2,2)
    # Black plays (1,2) captures white at (1,... wait let me rethink
    # Standard ko: B captures W at X, W can't immediately play X back.
    # Simpler: use positions (3,3)..(4,4) region.
    # Black stones: (3,4), (4,3), (5,4)
    # White stones: (3,5), (4,6), (5,5)
    # Black plays (4,5) — captures white at (4,6)? No, (4,6) only bordered by (4,5) and (4,7) empty and (3,6),(5,6) empty.
    # Let me set up a clean ko:
    # Place black and white in pattern where each fills the other's eye.
    # Row r=4: . B W .
    # Row r=3: B . . W
    # Row r=5: . B W .
    # Actually the classic ko:
    #   . B W .
    #   B W . W
    #   . B W .
    # Black plays in the gap, captures the middle W.
    # Positions with center at (4,5):
    # Black: (3,4), (5,4), (4,3)
    # White: (3,5), (5,5), (4,6)
    # Middle white: (4,5) — captured when all its libs taken
    # Hmm let me redesign. The classic ko fight:
    # . a b .
    # a X Y b
    # . a b .
    # Black at positions 'a', white at positions 'b', X is white, Y is empty (eye for black capture).
    # Wait actually ko fight:
    # . B W .
    # B W . W
    # . B W .
    # Here W at (center) has liberties only at the empty point in row middle.
    # Black plays the empty point => captures middle W. Result:
    # . B W .
    # B . B W
    # . B W .
    # Now White wants to recapture the Black stone just placed. If White plays
    # back at the W position, it would capture Black's new stone, but that
    # recreates the previous board state => superko violation.
    plays = [
        (Color.BLACK, (3, 4)),
        (Color.WHITE, (3, 5)),
        (Color.BLACK, (4, 3)),
        (Color.WHITE, (4, 4)),  # middle white
        (Color.BLACK, (5, 4)),
        (Color.WHITE, (5, 5)),
        (Color.BLACK, (8, 8)),  # filler to give white move
        (Color.WHITE, (4, 6)),  # right edge white, completes surround
    ]
    for color, pt in plays:
        r = g.play(color, pt)
        assert r.outcome is MoveOutcome.OK, f"Setup move {color} at {pt} should be legal"

    # Now Black captures middle white at (4,4) by playing (4,5)
    r = g.play(Color.BLACK, (4, 5))
    assert r.outcome is MoveOutcome.OK
    assert r.captured_count == 1
    assert g.board.at((4, 4)) is Color.EMPTY

    # White immediately tries to recapture at (4,4) — would restore previous position
    r = g.play(Color.WHITE, (4, 4))
    assert r.outcome is MoveOutcome.ILLEGAL  # ko


def test_two_consecutive_passes_end_game():
    g = GameState()
    g.pass_turn(Color.BLACK)
    r = g.pass_turn(Color.WHITE)
    assert r.outcome is MoveOutcome.GAME_OVER
    assert g.is_over


def test_auto_skip_counts_as_pass_toward_end():
    g = GameState()
    g.play(Color.BLACK, (4, 4))
    # White auto-skips via 3 illegal attempts
    for _ in range(3):
        g.play(Color.WHITE, (4, 4))
    assert g.to_move is Color.BLACK
    # Black passes; that's one pass. Now White auto-skip again.
    g.pass_turn(Color.BLACK)
    for _ in range(3):
        g.play(Color.WHITE, (4, 4))
    # Black's pass + White's auto-skip = two consecutive passes -> game over
    assert g.is_over


def test_view_hides_opponent_stones():
    g = GameState()
    g.play(Color.BLACK, (4, 4))
    g.play(Color.WHITE, (4, 5))
    v_black = g.view(Color.BLACK)
    assert v_black.at((4, 4)) is Color.BLACK
    assert v_black.at((4, 5)) is None  # white stone hidden from black


def test_consume_pending_losses_once():
    g = GameState()
    # Set up capture
    g.play(Color.BLACK, (0, 1))
    g.play(Color.WHITE, (0, 0))
    g.play(Color.BLACK, (1, 0))  # captures white at (0,0)
    # It's now white's turn. White should see losses=1 once.
    assert g.consume_pending_losses(Color.WHITE) == 1
    assert g.consume_pending_losses(Color.WHITE) == 0
