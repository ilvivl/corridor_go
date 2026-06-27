"""Тесты rooms.commit_action (этап 5): единый код-путь записи хода.

Требует поднятого Postgres (как и остальные DB-тесты). Партии создаём через
rooms.create_game; autouse-фикстура cleanup_games из conftest подчистит их.
"""
import uuid
from dataclasses import replace

import pytest
from sqlalchemy import select

from game import GameState
from server import rooms
from server.rooms import ActionRejected, commit_action
from server.db import SessionLocal
from server.models import Game, Move


def _active_game(db, state: GameState | None = None) -> Game:
    """Партия в статусе active (опц. с заданным состоянием ядра)."""
    game = rooms.create_game(db)
    game.status = "active"
    if state is not None:
        game.state = state.to_json()
    db.commit()
    return game


def test_legal_move_advances_ply_and_writes_move():
    with SessionLocal() as db:
        gid = _active_game(db).id
        view = commit_action(db, gid, 1, {"type": "move", "to": [4, 1]}, expected_ply=0)

    assert view["ply"] == 1
    assert view["turn"] == 2
    assert view["pawns"]["1"] == [4, 1]
    assert view["winner"] is None
    assert view["status"] == "active"

    with SessionLocal() as db:
        g = db.get(Game, gid)
        assert g.ply == 1
        moves = db.execute(
            select(Move).where(Move.game_id == gid)
        ).scalars().all()
        assert len(moves) == 1
        assert (moves[0].ply, moves[0].player) == (1, 1)
        assert moves[0].action == {"type": "move", "to": [4, 1]}


def test_winning_move_sets_winner_and_finished():
    near = replace(GameState.initial(), pawns=((4, 7), (4, 0)), turn=1)
    with SessionLocal() as db:
        gid = _active_game(db, near).id
        view = commit_action(db, gid, 1, {"type": "move", "to": [4, 8]}, expected_ply=0)

    assert view["winner"] == 1
    assert view["status"] == "finished"
    with SessionLocal() as db:
        g = db.get(Game, gid)
        assert g.winner == 1 and g.status == "finished" and g.ply == 1


def test_not_your_turn():
    with SessionLocal() as db:
        gid = _active_game(db).id  # turn=1
        with pytest.raises(ActionRejected) as ei:
            commit_action(db, gid, 2, {"type": "move", "to": [4, 7]}, expected_ply=0)
        assert ei.value.reason == "not_your_turn"


def test_illegal_move_propagates_core_reason():
    with SessionLocal() as db:
        gid = _active_game(db).id
        with pytest.raises(ActionRejected) as ei:
            commit_action(db, gid, 1, {"type": "move", "to": [0, 0]}, expected_ply=0)
        assert ei.value.reason == "blocked_by_wall"


def test_stale_ply():
    with SessionLocal() as db:
        gid = _active_game(db).id
        with pytest.raises(ActionRejected) as ei:
            commit_action(db, gid, 1, {"type": "move", "to": [4, 1]}, expected_ply=5)
        assert ei.value.reason == "stale_ply"


def test_bad_action():
    with SessionLocal() as db:
        gid = _active_game(db).id
        with pytest.raises(ActionRejected) as ei:
            commit_action(db, gid, 1, {"type": "frobnicate"}, expected_ply=0)
        assert ei.value.reason == "bad_action"


def test_not_active():
    with SessionLocal() as db:
        gid = rooms.create_game(db).id  # status waiting
        with pytest.raises(ActionRejected) as ei:
            commit_action(db, gid, 1, {"type": "move", "to": [4, 1]}, expected_ply=0)
        assert ei.value.reason == "not_active"


def test_game_not_found():
    with SessionLocal() as db:
        with pytest.raises(ActionRejected) as ei:
            commit_action(db, uuid.uuid4(), 1, {"type": "move", "to": [4, 1]})
        assert ei.value.reason == "game_not_found"
