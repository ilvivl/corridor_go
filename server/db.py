"""Подключение к БД и базовый класс ORM-моделей (слой данных, этап 2).

SQLAlchemy 2.0 (типизированный стиль) + psycopg 3, синхронно — ложится на
gevent-модель будущего Flask-SocketIO без async. URL берётся из переменной
окружения ``DATABASE_URL`` (см. ``.env`` / ``.env.example``).
"""
import os

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL не задан. Скопируйте .env.example в .env и поднимите "
        "Postgres: docker compose up -d."
    )


class Base(DeclarativeBase):
    """Базовый класс для всех ORM-моделей (общий MetaData)."""


# create_engine не подключается к БД сразу — соединение откроется при первом
# запросе. pool_pre_ping страхует от «протухших» соединений после рестарта БД.
engine = create_engine(DATABASE_URL, echo=False, pool_pre_ping=True)

SessionLocal = sessionmaker(
    bind=engine, autoflush=False, expire_on_commit=False,
)
