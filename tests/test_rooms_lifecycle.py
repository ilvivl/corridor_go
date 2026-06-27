"""Тесты жизненного цикла партии (этап 6): форфейт и ленивый TTL.

Чистые код-пути rooms.end_by_forfeit / rooms.maybe_expire против Postgres (как
остальные DB-тесты). Партии создаём через rooms.create_game; autouse-фикстура
cleanup_games из conftest подчистит их.
"""
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, text

from game import GameState
from server import rooms
from server.db import SessionLocal
from server.models import Game


def _active_game(db, state: GameState | None = None) -> Game:
    """Партия в статусе active (опц. с заданным состоянием ядра)."""
    game = rooms.create_game(db)
    game.status = "active"
    if state is not None:
        game.state = state.to_json()
    db.commit()
    return game


def _backdate(db, game_id, age: timedelta) -> None:
    """Состарить updated_at сырым SQL: ORM onupdate=func.now() перебил бы значение
    при flush, поэтому пишем колонку напрямую."""
    ts = datetime.now(timezone.utc) - age
    db.execute(
        text("UPDATE games SET updated_at = :ts WHERE id = :id"),
        {"ts": ts, "id": game_id},
    )
    db.commit()


# --- end_by_forfeit -------------------------------------------------

def test_forfeit_active_sets_winner_and_locks_board():
    with SessionLocal() as db:
        gid = _active_game(db).id
        view = rooms.end_by_forfeit(db, gid, 2)

    assert view is not None
    assert view["winner"] == 2
    assert view["status"] == "finished"
    # Доска заперта: победителю на «его» ходу подсказок нет (winner != None).
    assert rooms.legal_hints(view, 2)["moves"] == []

    # В БД исход зафиксирован, state JSONB не тронут (стартовая позиция цела).
    with SessionLocal() as db:
        g = db.get(Game, gid)
        assert g.status == "finished" and g.winner == 2
        assert g.state == GameState.initial().to_json()


def test_forfeit_is_idempotent_on_finished():
    with SessionLocal() as db:
        gid = _active_game(db).id
        first = rooms.end_by_forfeit(db, gid, 1)
        assert first is not None
        # Повтор (напр. resign после таймаута) — None, исход НЕ перетёрт.
        second = rooms.end_by_forfeit(db, gid, 2)
        assert second is None

    with SessionLocal() as db:
        assert db.get(Game, gid).winner == 1


def test_forfeit_waiting_and_abandoned_return_none():
    with SessionLocal() as db:
        waiting = rooms.create_game(db)  # status waiting
        assert rooms.end_by_forfeit(db, waiting.id, 1) is None
        assert db.get(Game, waiting.id).status == "waiting"

        ab = _active_game(db)
        ab.status = "abandoned"
        db.commit()
        assert rooms.end_by_forfeit(db, ab.id, 1) is None
        assert db.get(Game, ab.id).winner is None


def test_forfeit_missing_game_returns_none():
    with SessionLocal() as db:
        assert rooms.end_by_forfeit(db, uuid.uuid4(), 1) is None


# --- maybe_expire ---------------------------------------------------

def test_expire_stale_waiting():
    with SessionLocal() as db:
        gid = rooms.create_game(db).id  # waiting
        _backdate(db, gid, rooms.ABANDON_AFTER + timedelta(hours=1))
        game = db.get(Game, gid)
        assert rooms.maybe_expire(db, game) is True
        assert game.status == "abandoned"
        assert game.winner is None  # TTL — аннулирование, не победа


def test_expire_stale_active():
    with SessionLocal() as db:
        gid = _active_game(db).id
        _backdate(db, gid, rooms.ABANDON_AFTER + timedelta(hours=1))
        game = db.get(Game, gid)
        assert rooms.maybe_expire(db, game) is True
        assert game.status == "abandoned"


def test_expire_fresh_is_noop():
    with SessionLocal() as db:
        waiting = rooms.create_game(db)
        active = _active_game(db)
        assert rooms.maybe_expire(db, waiting) is False
        assert rooms.maybe_expire(db, active) is False
        assert waiting.status == "waiting" and active.status == "active"


def test_expire_finished_is_noop_even_if_old():
    with SessionLocal() as db:
        gid = _active_game(db).id
        rooms.end_by_forfeit(db, gid, 1)  # → finished
        _backdate(db, gid, rooms.ABANDON_AFTER + timedelta(days=2))
        game = db.get(Game, gid)
        assert rooms.maybe_expire(db, game) is False
        assert game.status == "finished" and game.winner == 1
