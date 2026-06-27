"""Тесты rooms.legal_hints (этап 4): подсказки знают сторону и не текут сопернику.

Требует поднятого Postgres (как и tests/test_http.py). Партии создаём через
rooms.create_game(db); autouse-фикстура cleanup_games из conftest подчистит их.
"""
from dataclasses import replace

from game import GameState
from server import rooms
from server.db import SessionLocal


def test_initial_hints_for_side_on_turn():
    """Начальное состояние, side=1 (на ходу): 3 хода пешкой + стены."""
    with SessionLocal() as db:
        game = rooms.create_game(db)
        hints = rooms.legal_hints(game, 1)

    assert hints["your_turn"] is True
    moves = [m for m in hints["moves"] if m["type"] == "move"]
    walls = [m for m in hints["moves"] if m["type"] == "wall"]
    assert len(moves) == 3          # из (4,0): (4,1),(3,0),(5,0)
    assert walls                    # стены на старте тоже доступны
    for m in moves:                 # структура как у action_to_json
        assert set(m) == {"type", "to"}
        assert len(m["to"]) == 2
    for w in walls:
        assert set(w) == {"type", "c", "r", "o"}
        assert w["o"] in ("H", "V")


def test_no_hints_for_side_off_turn():
    """То же состояние, но side=2 (не на ходу) — пустой список."""
    with SessionLocal() as db:
        game = rooms.create_game(db)
        hints = rooms.legal_hints(game, 2)

    assert hints["your_turn"] is False
    assert hints["moves"] == []


def test_no_hints_when_finished():
    """Завершённая партия (winner задан) — ходов нет ни для кого."""
    with SessionLocal() as db:
        game = rooms.create_game(db)
        game.state = replace(GameState.initial(), winner=1).to_json()
        db.commit()
        hints = rooms.legal_hints(game, 1)

    assert hints["your_turn"] is False
    assert hints["moves"] == []
