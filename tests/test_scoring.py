from core.board import BOARD_SIZE, Board, Color
from core.scoring import Score, area_score


def test_empty_board_scores_zero():
    s = area_score(Board.empty())
    assert s == Score(black=0, white=0)


def test_single_black_stone_owns_whole_board():
    b = Board.empty().with_stone((4, 4), Color.BLACK)
    s = area_score(b)
    assert s.black == BOARD_SIZE * BOARD_SIZE
    assert s.white == 0
    assert s.winner is Color.BLACK


def test_split_board_dame_unscored():
    b = Board.empty()
    for r in range(BOARD_SIZE):
        b = b.with_stone((r, 3), Color.BLACK)
        b = b.with_stone((r, 5), Color.WHITE)
    s = area_score(b)
    # Black owns cols 0-2 (3 stones each row) plus col 3 (wall) = 9 + 9 = wait
    # Col 0,1,2 empty = 27 territory; col 3 black stones = 9; total black = 36
    # Col 4 empty bordered by both = dame; col 5 white stones = 9; col 6,7,8 empty = 27
    # total white = 36
    assert s.black == 36
    assert s.white == 36
    assert s.winner is None


def test_winner_tiebreak_is_none():
    assert Score(black=10, white=10).winner is None
