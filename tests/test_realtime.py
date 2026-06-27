"""Тесты realtime-слоя (этап 5): транспорт ходов и изоляция подсказок.

Требует поднятого Postgres. Socket.IO-клиент делит cookie/сессию с HTTP-клиентом
через ``flask_test_client`` — так сторона аутентифицируется тем же токеном, что и на
HTTP. Партии чистит autouse-фикстура cleanup_games из conftest.
"""
import uuid

import pytest

from server import realtime
from server.db import SessionLocal
from server.models import Game
from server.realtime import socketio


@pytest.fixture(autouse=True)
def fast_grace(monkeypatch):
    """Grace-таймеры → 0: watcher, спавнящийся на teardown-дисконнекте сокет-клиента,
    завершится мгновенно и не задержит pytest ~30с."""
    monkeypatch.setattr(realtime, "GRACE_NOTIFY_SECONDS", 0)
    monkeypatch.setattr(realtime, "GRACE_FORFEIT_SECONDS", 0)


def _create_game(client) -> str:
    return client.post("/game").headers["Location"].rsplit("/", 1)[-1]


def _last(received, name):
    """Аргумент последнего события ``name`` из get_received(), либо None."""
    hits = [r["args"][0] for r in received if r["name"] == name]
    return hits[-1] if hits else None


def _two_joined(app, client, game_id):
    """P2 заходит по HTTP (активирует партию); оба подключают сокеты и join'ятся."""
    p2 = app.test_client()
    p2.get(f"/game/{game_id}")  # resolve_side -> side 2, status active

    sc1 = socketio.test_client(app, flask_test_client=client)
    sc2 = socketio.test_client(app, flask_test_client=p2)
    sc1.get_received(); sc2.get_received()        # сбросить connect
    sc1.emit("join", {"game_id": game_id})
    sc2.emit("join", {"game_id": game_id})
    sc1.get_received(); sc2.get_received()        # сбросить state/hints от join
    return sc1, sc2


def test_move_broadcasts_state_and_isolated_hints(app, client):
    game_id = _create_game(client)
    sc1, sc2 = _two_joined(app, client, game_id)

    sc1.emit("move", {"game_id": game_id,
                      "action": {"type": "move", "to": [4, 1]}, "ply": 0})
    r1, r2 = sc1.get_received(), sc2.get_received()

    # Оба получают одинаковый публичный state.
    s1, s2 = _last(r1, "state"), _last(r2, "state")
    assert s1 is not None and s1 == s2
    assert s1["ply"] == 1 and s1["turn"] == 2 and s1["pawns"]["1"] == [4, 1]

    # Подсказки персональны: ход теперь у P2 → у P2 ходы есть, у P1 (не на ходу) пусто.
    h1, h2 = _last(r1, "hints"), _last(r2, "hints")
    assert h1["your_turn"] is False and h1["moves"] == []
    assert h2["your_turn"] is True and h2["moves"]


def test_move_off_turn_rejected(app, client):
    game_id = _create_game(client)
    sc1, sc2 = _two_joined(app, client, game_id)

    # На старте ход у P1; P2 пытается сходить.
    sc2.emit("move", {"game_id": game_id,
                      "action": {"type": "move", "to": [4, 7]}, "ply": 0})
    rej = _last(sc2.get_received(), "rejected")
    assert rej is not None and rej["reason"] == "not_your_turn"
    # Соперник P1 ничего не получил (ход не состоялся).
    assert _last(sc1.get_received(), "state") is None


def test_winning_move_broadcasts_winner(app, client):
    game_id = _create_game(client)
    sc1, sc2 = _two_joined(app, client, game_id)

    # Засеять почти выигрышное состояние P1 (пешка на (4,7), ход P1).
    from dataclasses import replace
    from game import GameState
    with SessionLocal() as db:
        g = db.get(Game, uuid.UUID(game_id))
        g.state = replace(GameState.initial(), pawns=((4, 7), (4, 0)), turn=1).to_json()
        db.commit()

    sc1.emit("move", {"game_id": game_id,
                      "action": {"type": "move", "to": [4, 8]}, "ply": 0})
    s = _last(sc2.get_received(), "state")
    assert s is not None and s["winner"] == 1 and s["status"] == "finished"


def test_presence_on_join_shows_both_online(app, client):
    game_id = _create_game(client)
    sc1, sc2 = _two_joined(app, client, game_id)
    # _two_joined уже сбросил полученное; дёрнем ещё join, чтобы прийти presence.
    sc1.emit("join", {"game_id": game_id})
    p = _last(sc1.get_received(), "presence")
    assert p is not None and p["online"] == {"1": True, "2": True}
    assert p["grace_seconds"] is None


def test_resign_finishes_game_for_opponent(app, client):
    game_id = _create_game(client)
    sc1, sc2 = _two_joined(app, client, game_id)

    sc1.emit("resign", {"game_id": game_id})  # P1 сдаётся → побеждает P2
    r1, r2 = sc1.get_received(), sc2.get_received()

    s1, s2 = _last(r1, "state"), _last(r2, "state")
    assert s1 is not None and s1 == s2
    assert s1["winner"] == 2 and s1["status"] == "finished"
    # Доска заперта у обоих.
    h1, h2 = _last(r1, "hints"), _last(r2, "hints")
    assert h1["moves"] == [] and h2["moves"] == []


def test_resign_before_active_rejected(app, client):
    """Партия ещё waiting (P2 не зашёл) → resign отклоняется."""
    game_id = _create_game(client)
    sc1 = socketio.test_client(app, flask_test_client=client)
    sc1.get_received()
    sc1.emit("join", {"game_id": game_id})
    sc1.get_received()

    sc1.emit("resign", {"game_id": game_id})
    rej = _last(sc1.get_received(), "rejected")
    assert rej is not None and rej["reason"] == "not_active"


def test_join_without_session_is_forbidden(app, client):
    """Посторонний (нет токена партии в сессии) не входит в комнату."""
    game_id = _create_game(client)
    stranger = app.test_client()  # не заходил на страницу партии — токена нет
    sc = socketio.test_client(app, flask_test_client=stranger)
    sc.get_received()
    sc.emit("join", {"game_id": game_id})
    rej = _last(sc.get_received(), "rejected")
    assert rej is not None and rej["reason"] == "forbidden"
