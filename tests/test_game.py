import pytest

from game import GameState, MovePawn, IllegalMove, apply


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


def test_player1_wins_on_last_row():
    s2 = apply(_state(pawns=((4, 7), (0, 8)), turn=1), MovePawn((4, 8)))
    assert s2.winner == 1


def test_player2_wins_on_first_row():
    s2 = apply(_state(pawns=((0, 0), (4, 1)), turn=2), MovePawn((4, 0)))
    assert s2.winner == 2


def test_turn_alternation():
    s = GameState.initial()
    s = apply(s, MovePawn((4, 1)))
    assert s.turn == 2
    s = apply(s, MovePawn((4, 7)))
    assert s.turn == 1


def test_state_is_immutable():
    s = GameState.initial()
    apply(s, MovePawn((4, 1)))
    assert s.pawns[0] == (4, 0)  # исходное состояние не изменилось
    assert s.turn == 1


def test_no_moves_after_win():
    with pytest.raises(IllegalMove) as e:
        apply(_state(winner=1), MovePawn((4, 1)))
    assert e.value.reason == "game_over"
