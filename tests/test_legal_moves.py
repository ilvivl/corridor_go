from game import GameState, MovePawn, legal_moves


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


def test_initial_legal_moves_count():
    moves = legal_moves(GameState.initial())
    pawn_moves = [m for m in moves if isinstance(m, MovePawn)]
    assert len(pawn_moves) == 3            # влево, вправо, вперёд
    # 3 хода фишкой + 128 легальных стен (8×8×2) на пустой доске
    assert len(moves) == 131


def test_legal_moves_include_jump():
    moves = legal_moves(_state(pawns=((4, 4), (4, 5)), turn=1))
    assert MovePawn((4, 6)) in moves


def test_no_legal_moves_after_win():
    assert legal_moves(_state(winner=2)) == []
