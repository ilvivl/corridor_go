from game import GameState, pawn_destinations
from game.board import Wall


def _state(**kw) -> GameState:
    base = dict(
        pawns=((4, 4), (4, 5)),  # фишки смежны по вертикали
        walls=frozenset(),
        walls_left=(10, 10),
        turn=1,
        winner=None,
    )
    base.update(kw)
    return GameState(**base)


def test_straight_jump():
    d = pawn_destinations(_state())
    assert (4, 6) in d        # прыжок через соперника
    assert (4, 5) not in d    # на клетку соперника нельзя


def test_diagonal_jump_wall_behind():
    s = _state(walls=frozenset({Wall(4, 5, "H")}))  # стена позади соперника
    d = pawn_destinations(s)
    assert (4, 6) not in d                 # прямой прыжок закрыт
    assert (3, 5) in d and (5, 5) in d     # обе диагонали доступны


def test_diagonal_jump_edge_behind():
    s = _state(pawns=((4, 7), (4, 8)))     # соперник у верхнего края
    d = pawn_destinations(s)
    assert (3, 8) in d and (5, 8) in d
    assert (4, 9) not in d                 # за доской


def test_diagonal_blocked_on_one_side():
    # позади соперника стена (прямой прыжок закрыт) + одна диагональ перекрыта
    s = _state(walls=frozenset({Wall(4, 5, "H"), Wall(4, 4, "V")}))
    d = pawn_destinations(s)
    assert (3, 5) in d         # свободная диагональ
    assert (5, 5) not in d     # перекрыта стеной
    assert (4, 6) not in d     # прямой прыжок закрыт
