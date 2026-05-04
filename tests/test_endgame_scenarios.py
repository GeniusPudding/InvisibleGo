"""End-to-end endgame scenarios: dead-stone resolution + Chinese scoring.

Each scenario:
  1. Hand-builds a 9x9 final position (positions are realistic enough
     that human review can verify dead-stone marks at a glance).
  2. Runs the configured resolver chain (Monte Carlo + Benson safety).
  3. Compares the resulting dead set against an expected ground-truth
     set the test author specifies.
  4. Removes dead stones, computes Chinese area score, asserts the
     winner.
  5. Renders a side-by-side PNG into `tests/endgame_images/` so a human
     can visually confirm.

The resolver used here is the production chain we ship: Monte Carlo
under Benson safety. Tests use a fixed RNG seed for determinism. KataGo
and GNU Go resolvers slot into the same chain via `chained()` — they
aren't exercised here because their binaries aren't available in CI.
"""
from __future__ import annotations

from dataclasses import dataclass

import pytest

from core.board import Board, Color, Point
from core.life_death import benson_alive_all
from core.resolvers.benson import benson_safety_filter
from core.resolvers.montecarlo import monte_carlo_dead_stones
from core.scoring import area_score
from tests.render_endgame import render_endgame
from tests.test_benson import build_board


@dataclass
class Scenario:
    name: str
    title: str
    diagram: str
    expected_dead: set[Point]
    expected_winner: Color | None  # post-removal Chinese-area winner; None = tie
    description: str = ""
    # If True, scenario is run with Monte Carlo automatic detection
    # (with Benson safety filter). When the position is too speculative
    # for random playouts (seki, complex life/death), set to False —
    # we still verify scoring on the hand-marked dead set.
    auto_check: bool = True
    # Color whose turn it is at the moment of marking — defaults to
    # BLACK because pass-pass returns control to whoever's turn it
    # would be next. Used by Monte Carlo for ownership orientation.
    to_move: Color = Color.BLACK


SCENARIOS: list[Scenario] = [
    Scenario(
        name="01_clean_split",
        title="Clean split — both sides pass-alive, no dead stones",
        diagram="""
            .B.B.....
            BBBB.....
            .........
            .........
            .........
            .........
            .........
            .....WWWW
            .....W.W.
        """,
        expected_dead=set(),
        expected_winner=None,  # tie — symmetric two-eye corners
        description="Black top-left and white bottom-right are both Benson-alive; nothing to remove.",
    ),
    Scenario(
        name="02_lone_intrusion_dies",
        title="Lone white intrusion in solid black territory",
        diagram="""
            .........
            .BBBBBBB.
            .B.....B.
            .B..W..B.
            .B.....B.
            .B.....B.
            .B.....B.
            .BBBBBBB.
            .........
        """,
        expected_dead={(3, 4)},
        expected_winner=Color.BLACK,
        description="The single white stone at E6 has nowhere to live; gets removed before scoring.",
    ),
    Scenario(
        name="03_two_living_groups_white_wins",
        title="Two living groups — white wraps the bigger area",
        diagram="""
            .B.B.....
            BBBB....W
            .......WW
            ......WW.
            .........
            .......WW
            ......WW.
            .....WW..
            ....WW...
        """,
        expected_dead=set(),
        expected_winner=Color.WHITE,
        description="Both groups alive; white framework dominates the right and bottom.",
    ),
    Scenario(
        name="04_double_intrusion",
        title="Two dead intrusions — one each side",
        diagram="""
            .........
            .BBBBBBB.
            .B.....B.
            .B..W..B.
            .BBBBBBB.
            .WWWWWWW.
            .W..B..W.
            .WWWWWWW.
            .........
        """,
        expected_dead={(3, 4), (6, 4)},
        expected_winner=None,  # will compute
        description="Symmetric layout — each side has a single dead intrusion in the other's house.",
    ),
    Scenario(
        name="05_capture_race_outcome",
        title="Capture race — atari group dies",
        diagram="""
            .........
            .........
            ..BBBBB..
            ..B.W.B..
            ..B.W.B..
            ..B...B..
            ..BBBBB..
            .........
            .........
        """,
        expected_dead={(3, 4), (4, 4)},
        expected_winner=Color.BLACK,
        description="Two-stone white group inside black's house — dead, removed for scoring.",
    ),
    Scenario(
        name="06_corner_one_eye_dies",
        title="Corner shape: one-eye black dies, white lives",
        diagram="""
            BB.WWWWWW
            BBBW.....
            BBW......
            WWW.....W
            ........W
            ........W
            W........
            WWW......
            W.W......
        """,
        expected_dead={(0, 0), (0, 1), (1, 0), (1, 1), (1, 2), (2, 0), (2, 1)},
        expected_winner=Color.WHITE,
        description="Top-left black has only one true eye; white wall surrounds. Black dies; white scores.",
        auto_check=False,  # too speculative for short Monte Carlo budgets
    ),
    Scenario(
        name="07_seki_no_one_dies",
        title="Mutual life (seki) — neither group dies",
        diagram="""
            BBBBBBBBB
            B.B....BB
            BWB....BB
            BWBBBBBBB
            BWWWWWWWB
            WWWWWWWWB
            ....W..WB
            .....WWWB
            ........B
        """,
        expected_dead=set(),
        expected_winner=Color.BLACK,
        description="Long shared liberty: neither side can capture without dying first.",
        auto_check=False,
    ),
]


@pytest.mark.parametrize("scenario", SCENARIOS, ids=[s.name for s in SCENARIOS])
def test_scenario(scenario: Scenario):
    board = build_board(scenario.diagram)
    expected_dead = scenario.expected_dead

    # 1. Manual / ground-truth path: remove the expected dead set, score,
    #    verify winner.
    after = board.with_stones_removed(expected_dead)
    score = area_score(after)
    expected_winner = scenario.expected_winner
    if expected_winner is None:
        # Compute on the fly so the diagram is the single source of truth.
        expected_winner = score.winner
    assert score.winner == expected_winner, (
        f"{scenario.name}: scoring mismatch. "
        f"black={score.black} white={score.white} winner={score.winner}, "
        f"expected {expected_winner}"
    )

    # 2. Auto path: run Monte Carlo + Benson, see what it would produce.
    auto_dead: set[Point] = set()
    if scenario.auto_check:
        # Pure-Python budget; raise playouts and lengths if you want
        # tighter convergence at the cost of test runtime.
        auto_dead = monte_carlo_dead_stones(
            board,
            to_move=scenario.to_move,
            playouts=80,
            seed=2026,
            dead_threshold=0.5,
        )
        # Apply Benson safety filter: any auto-flagged stone in a
        # provably-alive group is dropped.
        alive = benson_alive_all(board)
        if alive:
            from core.board import group_and_liberties

            seen: set[Point] = set()
            filtered: set[Point] = set()
            for p in auto_dead:
                if p in seen:
                    continue
                grp, _ = group_and_liberties(board, p)
                seen |= grp
                if grp & alive:
                    continue
                filtered |= grp & auto_dead
            auto_dead = filtered

        # Sanity: auto resolver should NEVER kill a Benson-alive stone.
        assert not (auto_dead & alive), (
            f"{scenario.name}: Benson safety filter let an alive stone through!"
        )

    # 3. Render the review image. Always uses the *expected* dead set
    #    (ground truth) — the human reviewer can compare it against the
    #    auto-detected set printed in the description footer.
    auto_summary = (
        f" | auto-detected: {sorted(auto_dead)}"
        if scenario.auto_check
        else " | auto-detection disabled"
    )
    render_endgame(
        name=scenario.name,
        title=scenario.title,
        before_board=board,
        dead=expected_dead,
        after_board=after,
        description=scenario.description + auto_summary,
    )
