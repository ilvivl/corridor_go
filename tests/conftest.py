"""Фикстуры HTTP-тестов (этап 3): приложение, клиент, очистка БД.

Изоляция — через очистку, а не вложенную транзакцию: роуты делают ``commit`` в
середине запроса и берут соединение из своей ``SessionLocal()``, поэтому
классический «join external transaction» здесь хрупок. Вместо него снимаем снимок
множества ``Game.id`` до теста и в teardown удаляем появившиеся (``db.delete``
каскадом подчистит ``moves`` через ``ondelete=CASCADE``). Требует поднятого
Postgres — как и существующий ``scripts/smoke_db.py``.
"""
import pytest
from sqlalchemy import select

from server.db import SessionLocal
from server.models import Game
from server.app import create_app


@pytest.fixture
def app():
    return create_app({"TESTING": True})


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture(autouse=True)
def cleanup_games():
    """Удалить партии, созданные тестом (снимок id до → разница после)."""
    with SessionLocal() as db:
        before = {row[0] for row in db.execute(select(Game.id)).all()}
    yield
    with SessionLocal() as db:
        for game in db.execute(select(Game)).scalars():
            if game.id not in before:
                db.delete(game)
        db.commit()
