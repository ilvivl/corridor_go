"""Тесты HTTP-слоя (этап 3): создание партии, вход по ссылке, роли, анти-утечка.

Каждый «браузер» — отдельный ``app.test_client()`` со своей банкой cookie.
Прямые проверки БД идут через ``SessionLocal`` (в conftest он привязан к тому же
внешнему соединению, что и роуты, — видит сделанные ими коммиты).
"""
import json
import uuid

from server.db import SessionLocal
from server.models import Game


def _create_game(client) -> str:
    """POST /game и вернуть game_id из Location редиректа."""
    resp = client.post("/game")
    assert resp.status_code == 302
    location = resp.headers["Location"]
    assert "/game/" in location
    return location.rsplit("/", 1)[-1]


def _game_data(html: str) -> dict:
    """Вытащить инлайн-JSON из <script id="game-data"> страницы партии."""
    marker = 'id="game-data">'
    start = html.index(marker) + len(marker)
    end = html.index("</script>", start)
    return json.loads(html[start:end])


def test_index_ok(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Создать игру" in resp.get_data(as_text=True)


def test_create_game_persists_and_sets_cookie(client):
    resp = client.post("/game")
    assert resp.status_code == 302
    assert "session=" in resp.headers.get("Set-Cookie", "")

    game_id = resp.headers["Location"].rsplit("/", 1)[-1]
    with SessionLocal() as db:
        game = db.get(Game, uuid.UUID(game_id))
        assert game is not None
        assert game.status == "waiting"
        assert game.player2_token is None


def test_creator_is_side_one(client):
    game_id = _create_game(client)
    resp = client.get(f"/game/{game_id}")
    assert resp.status_code == 200
    assert "Вы — игрок 1" in resp.get_data(as_text=True)


def test_second_client_takes_side_two_and_activates(client):
    game_id = _create_game(client)

    second = client.application.test_client()
    resp = second.get(f"/game/{game_id}")
    assert resp.status_code == 200
    assert "Вы — игрок 2" in resp.get_data(as_text=True)

    with SessionLocal() as db:
        game = db.get(Game, uuid.UUID(game_id))
        assert game.status == "active"
        assert game.player2_token is not None

    # повторный заход второго — та же сторона (токен уже в его сессии), не side 1.
    again = second.get(f"/game/{game_id}")
    assert "Вы — игрок 2" in again.get_data(as_text=True)


def test_third_client_gets_full_room(client):
    game_id = _create_game(client)
    client.application.test_client().get(f"/game/{game_id}")  # занял сторону 2

    third = client.application.test_client()
    resp = third.get(f"/game/{game_id}")
    assert resp.status_code == 403
    assert "заполнена" in resp.get_data(as_text=True)


def test_tokens_never_leak_into_html(client):
    game_id = _create_game(client)
    second = client.application.test_client()
    second.get(f"/game/{game_id}")  # активирует партию, появится player2_token

    with SessionLocal() as db:
        game = db.get(Game, uuid.UUID(game_id))
        tokens = [str(game.player1_token), str(game.player2_token)]

    for viewer in (client, second):
        html = viewer.get(f"/game/{game_id}").get_data(as_text=True)
        for token in tokens:
            assert token not in html


def test_game_page_embeds_client_state(client):
    """Страница встраивает <script id="game-data"> с ключами view/hints/my_side."""
    game_id = _create_game(client)
    data = _game_data(client.get(f"/game/{game_id}").get_data(as_text=True))

    assert set(data) == {"view", "hints", "my_side", "game_id"}
    assert data["my_side"] == 1
    assert data["game_id"] == game_id
    assert data["hints"]["your_turn"] is True
    assert any(m["type"] == "move" for m in data["hints"]["moves"])


def test_opponent_off_turn_gets_no_hints(client):
    """Контракт изоляции: сопернику не на ходу ходы не присылаются (P2 на старте)."""
    game_id = _create_game(client)
    second = client.application.test_client()
    data = _game_data(second.get(f"/game/{game_id}").get_data(as_text=True))

    assert data["my_side"] == 2
    assert data["hints"]["moves"] == []


def test_unknown_game_is_404(client):
    resp = client.get(f"/game/{uuid.uuid4()}")
    assert resp.status_code == 404
