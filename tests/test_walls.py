import pytest

from game import GameState, PlaceWall, IllegalMove, apply
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


def test_place_wall_valid():
    s2 = apply(GameState.initial(), PlaceWall(3, 4, "H"))
    assert Wall(3, 4, "H") in s2.walls
    assert s2.walls_left == (9, 10)
    assert s2.turn == 2


def test_wall_overlap_variants():
    s = _state(walls=frozenset({Wall(3, 4, "H")}))
    for bad in (PlaceWall(3, 4, "H"), PlaceWall(3, 4, "V"), PlaceWall(4, 4, "H")):
        with pytest.raises(IllegalMove) as e:
            apply(s, bad)
        assert e.value.reason == "wall_overlap"


def test_wall_out_of_bounds():
    s = GameState.initial()
    for bad in (PlaceWall(8, 0, "H"), PlaceWall(0, 8, "V"), PlaceWall(0, 0, "X")):
        with pytest.raises(IllegalMove) as e:
            apply(s, bad)
        assert e.value.reason == "wall_out_of_bounds"


def test_no_walls_left():
    with pytest.raises(IllegalMove) as e:
        apply(_state(walls_left=(0, 10)), PlaceWall(3, 4, "H"))
    assert e.value.reason == "no_walls_left"


def test_wall_blocks_path_rejected():
    # P1 в углу (0,0); Wall(1,0,"V") уже стоит; Wall(0,0,"H") запирает карман {(0,0),(1,0)}
    s = _state(pawns=((0, 0), (4, 8)), walls=frozenset({Wall(1, 0, "V")}))
    with pytest.raises(IllegalMove) as e:
        apply(s, PlaceWall(0, 0, "H"))
    assert e.value.reason == "wall_blocks_path"


def test_wall_only_lengthens_path_is_legal():
    s = _state(walls=frozenset({Wall(1, 0, "V")}))
    s2 = apply(s, PlaceWall(3, 0, "H"))  # удлиняет путь, но не запирает
    assert Wall(3, 0, "H") in s2.walls
