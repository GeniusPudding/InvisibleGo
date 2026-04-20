from core.board import (
    BOARD_SIZE,
    Board,
    Color,
    group_and_liberties,
    neighbors,
)


def test_empty_board_is_all_empty():
    b = Board.empty()
    for p in b.all_points():
        assert b.at(p) is Color.EMPTY


def test_opponent_pairing():
    assert Color.BLACK.opponent() is Color.WHITE
    assert Color.WHITE.opponent() is Color.BLACK


def test_with_stone_is_immutable():
    b = Board.empty()
    b2 = b.with_stone((4, 4), Color.BLACK)
    assert b.at((4, 4)) is Color.EMPTY
    assert b2.at((4, 4)) is Color.BLACK


def test_neighbors_corner_has_two():
    assert set(neighbors((0, 0))) == {(0, 1), (1, 0)}


def test_neighbors_center_has_four():
    assert len(list(neighbors((4, 4)))) == 4


def test_single_stone_center_has_four_liberties():
    b = Board.empty().with_stone((4, 4), Color.BLACK)
    group, libs = group_and_liberties(b, (4, 4))
    assert group == {(4, 4)}
    assert len(libs) == 4


def test_single_stone_corner_has_two_liberties():
    b = Board.empty().with_stone((0, 0), Color.BLACK)
    group, libs = group_and_liberties(b, (0, 0))
    assert group == {(0, 0)}
    assert libs == {(0, 1), (1, 0)}


def test_connected_group_shares_liberties():
    b = Board.empty()
    b = b.with_stone((4, 4), Color.BLACK)
    b = b.with_stone((4, 5), Color.BLACK)
    group, libs = group_and_liberties(b, (4, 4))
    assert group == {(4, 4), (4, 5)}
    # Two adjacent stones in center: 3+3 liberties but the shared edge
    # is no longer a liberty, so 6 total.
    assert len(libs) == 6


def test_surrounded_stone_has_zero_liberties():
    b = Board.empty()
    b = b.with_stone((4, 4), Color.BLACK)
    for n in [(3, 4), (5, 4), (4, 3), (4, 5)]:
        b = b.with_stone(n, Color.WHITE)
    _, libs = group_and_liberties(b, (4, 4))
    assert libs == set()
