"""Окружение Alembic.

URL и метаданные берём из приложения, а не из alembic.ini:
- ``DATABASE_URL`` — из ``.env`` (через ``server.db``);
- ``target_metadata`` — из ``server.db.Base`` (таблицы регистрирует import моделей).
"""
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from server.db import Base, DATABASE_URL
import server.models  # noqa: F401 — регистрирует Game/Move в Base.metadata

config = context.config

# Экранируем % (на случай спецсимволов в пароле) для ConfigParser-интерполяции.
config.set_main_option("sqlalchemy.url", DATABASE_URL.replace("%", "%%"))

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Генерация SQL без подключения к БД (alembic upgrade --sql)."""
    context.configure(
        url=DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Обычный режим: подключаемся к БД и применяем миграции."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
