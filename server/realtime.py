"""Realtime-слой «Коридор» (этап 5): WebSocket-транспорт ходов поверх Flask-SocketIO.

Тонкий транспорт над чистым код-путём ``rooms.commit_action``: принять ``move`` по
сокету, перевалидировать ядром против состояния из БД, разослать новое состояние обоим
игрокам комнаты. Сервер — источник истины; сторона клиента берётся из подписанной сессии
Flask (``rooms.side_from_session``), а НЕ из payload.

Доставка состояния: ``state`` (public_view, без токенов) — broadcast в комнату; ``hints``
(side-specific подсказки) — персонально на каждый sid (контракт изоляции этапа 4).

async_mode="threading" — без eventlet/gevent (Py 3.x + синхронный SQLAlchemy/psycopg3);
``simple-websocket`` даёт Werkzeug настоящий WS-транспорт. Прод-воркер — этап 7.
Дисконнект/реконнект/``abandoned`` — этап 6 (здесь лишь минимальная уборка реестра).
"""
import uuid
from collections import defaultdict

from flask import request, session
from flask_socketio import SocketIO, emit, join_room

from server.db import SessionLocal
from server.models import Game
from server import rooms

# Модульный синглтон: создаётся без app, привязывается в init_app (паттерн Flask-SocketIO).
socketio = SocketIO(async_mode="threading")

# Реестр участников комнаты для персональной рассылки hints.
# room (str game_id) -> {sid: side}. Один процесс/threading — модульного dict достаточно.
_members: dict[str, dict[str, int]] = defaultdict(dict)


def init_app(app) -> None:
    """Привязать сокеты к приложению. Хендлеры регистрируются декораторами при импорте
    модуля (на синглтоне), поэтому повторные вызовы из ``create_app`` безопасны."""
    socketio.init_app(app)


def _resolve(game_id: str):
    """``(view, side)`` для клиента по сессии, либо ``None`` (чужой/нет партии/битый id).

    Read-only: сторону НЕ доверяем клиенту, аутентифицируем токен из ``flask.session``
    (занятие стороны 2 остаётся на HTTP ``resolve_side``)."""
    try:
        gid = uuid.UUID(str(game_id))
    except (ValueError, TypeError, AttributeError):
        return None
    with SessionLocal() as db:
        game = db.get(Game, gid)
        if game is None:
            return None
        side = rooms.side_from_session(game, session)
        if side is None:
            return None
        return rooms.public_view(game), side


@socketio.on("join")
def on_join(payload):
    """Войти в комнату партии. payload: ``{game_id}``."""
    game_id = str((payload or {}).get("game_id", ""))
    resolved = _resolve(game_id)
    if resolved is None:
        emit("rejected", {"reason": "forbidden"})
        return
    view, side = resolved
    join_room(game_id)
    _members[game_id][request.sid] = side
    # lite-присутствие: если зашёл P2 и партия уже active — P1 получит свежий state и
    # его waiting-экран сам сменится на active.
    emit("state", view, to=game_id)
    emit("hints", rooms.legal_hints(view, side), to=request.sid)


@socketio.on("move")
def on_move(payload):
    """Сходить. payload: ``{game_id, action, ply}``."""
    payload = payload or {}
    game_id = str(payload.get("game_id", ""))
    resolved = _resolve(game_id)
    if resolved is None:
        emit("rejected", {"reason": "forbidden"})
        return
    _, side = resolved

    db = SessionLocal()
    try:
        view = rooms.commit_action(
            db, uuid.UUID(game_id), side, payload.get("action"), payload.get("ply"),
        )
    except rooms.ActionRejected as e:
        emit("rejected", {"reason": e.reason})
        return
    finally:
        db.close()

    # Новое состояние — всем в комнате; подсказки — персонально по стороне каждого sid.
    emit("state", view, to=game_id)
    for sid, member_side in _members[game_id].items():
        emit("hints", rooms.legal_hints(view, member_side), to=sid)


@socketio.on("disconnect")
def on_disconnect():
    """Минимальная уборка реестра (полный disconnect-цикл — этап 6)."""
    sid = request.sid
    for members in _members.values():
        members.pop(sid, None)
