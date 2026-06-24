import pytest

from game import GameState, MovePawn, IllegalMove, apply, pawn_destinations
from game.board import Wall


def _state(**kw) -> GameState:
    base = dict(
        pawns=((4, 0), (4, 8)),
        walls=frozenset(),
        walls_left=(10, 10),
        turn=1,
        winner=None,
    )
    base.update(kw)
    return GameState(**base)


def test_basic_destinations_from_start():
    assert pawn_destinations(GameState.initial()) == {(3, 0), (5, 0), (4, 1)}


def test_apply_move_switches_turn():
    s2 = apply(GameState.initial(), MovePawn((4, 1)))
    assert s2.pawns[0] == (4, 1)
    assert s2.turn == 2


def test_move_off_board():
    with pytest.raises(IllegalMove) as e:
        apply(GameState.initial(), MovePawn((4, -1)))
    assert e.value.reason == "off_board"


def test_move_through_wall_blocked():
    s = _state(walls=frozenset({Wall(4, 0, "H")}))  # стена над фишкой в (4,0)
    assert (4, 1) not in pawn_destinations(s)
    with pytest.raises(IllegalMove) as e:
        apply(s, MovePawn((4, 1)))
    assert e.value.reason == "blocked_by_wall"


def test_move_onto_occupied_cell():
    s = _state(pawns=((4, 4), (4, 5)), turn=1)
    with pytest.raises(IllegalMove) as e:
        apply(s, MovePawn((4, 5)))
    assert e.value.reason == "cell_occupied"
