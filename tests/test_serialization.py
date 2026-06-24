from game import (
    GameState, MovePawn, PlaceWall, action_from_json, action_to_json,
)
from game.board import Wall


def test_initial_round_trip():
    s = GameState.initial()
    assert GameState.from_json(s.to_json()) == s


def test_complex_round_trip():
    s = GameState(
        pawns=((3, 5), (6, 2)),
        walls=frozenset({Wall(3, 4, "H"), Wall(1, 0, "V")}),
        walls_left=(7, 9),
        turn=2,
        winner=None,
    )
    assert GameState.from_json(s.to_json()) == s


def test_to_json_shape():
    data = GameState.initial().to_json()
    assert data["pawns"] == {"1": [4, 0], "2": [4, 8]}
    assert data["walls"] == []
    assert data["walls_left"] == {"1": 10, "2": 10}
    assert data["turn"] == 1
    assert data["winner"] is None


def test_action_move_round_trip():
    a = MovePawn((4, 1))
    assert action_from_json({"type": "move", "to": [4, 1]}) == a
    assert action_to_json(a) == {"type": "move", "to": [4, 1]}


def test_action_wall_round_trip():
    a = PlaceWall(3, 4, "H")
    assert action_from_json({"type": "wall", "c": 3, "r": 4, "o": "H"}) == a
    assert action_to_json(a) == {"type": "wall", "c": 3, "r": 4, "o": "H"}
