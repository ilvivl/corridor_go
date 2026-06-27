"""Тесты дисконнект-цикла (этап 6): фоновый grace-watcher детерминированно.

Watcher _forfeit_watch зовём НАПРЯМУЮ (без реальных потоков/таймеров): патчим
socketio.sleep → no-op и socketio.emit → коллектор. Модульные реестры _members /
_disc_token заполняем руками и чистим в фикстуре. Партии — против Postgres,
cleanup_games из conftest подчистит их.
"""
import uuid

import pytest

from game import GameState
from server import realtime, rooms
from server.db import SessionLocal
from server.models import Game


@pytest.fixture
def collected(monkeypatch):
    """socketio.sleep → no-op, socketio.emit → список (event, data, to)."""
    events: list[tuple] = []
    monkeypatch.setattr(realtime.socketio, "sleep", lambda *a, **k: None)
    monkeypatch.setattr(
        realtime.socketio, "emit",
        lambda event, data=None, to=None, **k: events.append((event, data, to)),
    )
    return events


@pytest.fixture(autouse=True)
def clean_registries():
    """Изолировать модульные реестры между тестами."""
    realtime._members.clear()
    realtime._disc_token.clear()
    yield
    realtime._members.clear()
    realtime._disc_token.clear()


def _active_game() -> str:
    with SessionLocal() as db:
        g = rooms.create_game(db)
        g.status = "active"
        db.commit()
        return str(g.id)


def _status(room: str):
    with SessionLocal() as db:
        g = db.get(Game, uuid.UUID(room))
        return g.status, g.winner


def test_watcher_forfeits_when_side_stays_offline(collected):
    room = _active_game()
    # P1 офлайн (нет sid), P2 онлайн; токен актуален.
    realtime._members[room] = {"sidP2": 2}
    realtime._disc_token[(room, 1)] = 1

    realtime._forfeit_watch(room, 1, 1)

    assert _status(room) == ("finished", 2)
    names = [e[0] for e in collected]
    assert "presence" in names  # фаза NOTIFY + финальный сброс
    state = next(d for (n, d, _) in collected if n == "state")
    assert state["winner"] == 2 and state["status"] == "finished"
    # hints разосланы персонально оставшемуся sid и пусты (партия завершена).
    hints = [d for (n, d, to) in collected if n == "hints"]
    assert hints and all(h["moves"] == [] for h in hints)


def test_reconnect_cancels_forfeit(collected):
    room = _active_game()
    realtime._members[room] = {"sidP2": 2}
    realtime._disc_token[(room, 1)] = 1
    # Реконнект P1 до срабатывания: сторона снова онлайн (любого из условий хватит).
    realtime._members[room]["sidP1"] = 1

    realtime._forfeit_watch(room, 1, 1)

    assert _status(room) == ("active", None)
    assert collected == []  # ни одного emit — вышли на первой проверке


def test_stale_token_cancels_forfeit(collected):
    room = _active_game()
    realtime._members[room] = {"sidP2": 2}
    # Новый дисконнект-цикл перебил поколение → старый watcher с token=1 неактуален.
    realtime._disc_token[(room, 1)] = 2

    realtime._forfeit_watch(room, 1, 1)

    assert _status(room) == ("active", None)
    assert collected == []


def test_watcher_idempotent_when_already_finished(collected):
    room = _active_game()
    with SessionLocal() as db:  # партию завершил resign/победный ход раньше
        rooms.end_by_forfeit(db, uuid.UUID(room), 2)
    realtime._members[room] = {"sidP2": 2}
    realtime._disc_token[(room, 1)] = 1

    # Не падает; end_by_forfeit вернёт None → state не рассылается.
    realtime._forfeit_watch(room, 1, 1)

    assert _status(room) == ("finished", 2)
    assert not any(n == "state" for (n, _, _) in collected)
