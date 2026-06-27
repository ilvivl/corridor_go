"""HTTP-слой «Коридор» (этап 3): фабрика Flask + роуты.

Тонкий вертикальный срез: создать партию → войти по ссылке-приглашению →
получить сторону (токен в подписанной сессии) → увидеть текстовое состояние.
Ходов (realtime, этап 5) и Canvas (этап 4) здесь нет.

Сервер — источник истины: страница доски всегда рендерится из состояния в БД
через ``rooms.public_view`` (без токенов).
"""
import os

import uuid

from flask import (
    Flask, abort, g, redirect, render_template, session, url_for,
)
from sqlalchemy.orm import Session

from server.db import SessionLocal  # импорт тянет load_dotenv()
from server.models import Game
from server import rooms


def create_app(config: dict | None = None) -> Flask:
    app = Flask(
        __name__,
        template_folder="../templates",
        static_folder="../static",
    )
    app.secret_key = os.getenv("SECRET_KEY")
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=False,  # dev: HTTP; в проде включить через config
    )
    if config:
        app.config.update(config)

    # --- сессия БД на запрос ---
    def get_db() -> Session:
        if "db" not in g:
            g.db = SessionLocal()
        return g.db

    @app.teardown_appcontext
    def close_db(exc):  # noqa: ANN001 — сигнатура teardown
        db = g.pop("db", None)
        if db is not None:
            db.close()

    # --- роуты ---
    @app.get("/")
    def index():
        return render_template("index.html")

    @app.post("/game")
    def create():
        game = rooms.create_game(get_db())
        # плоский ключ верхнего уровня — Flask сам пометит сессию изменённой.
        session[str(game.id)] = str(game.player1_token)
        return redirect(url_for("game_page", game_id=game.id))

    @app.get("/game/<uuid:game_id>")
    def game_page(game_id: uuid.UUID):
        db = get_db()
        game = db.get(Game, game_id)
        if game is None:
            abort(404)

        side = rooms.resolve_side(game, session, db)
        if side is None:
            # посторонний в заполненной партии — зрителей нет.
            return render_template("game.html", full=True), 403

        invite_url = url_for("game_page", game_id=game.id, _external=True)
        return render_template(
            "game.html",
            view=rooms.public_view(game),
            my_side=side,
            game_id=game.id,
            invite_url=invite_url,
        )

    return app
