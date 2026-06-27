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
from sqlalchemy import select

from server.db import SessionLocal
from server.models import Game
from server import rooms

# Модульный синглтон: создаётся без app, привязывается в init_app (паттерн Flask-SocketIO).
socketio = SocketIO(async_mode="threading")

# Реестр участников комнаты для персональной рассылки hints.
# room (str game_id) -> {sid: side}. Один процесс/threading — модульного dict достаточно.
_members: dict[str, dict[str, int]] = defaultdict(dict)

# Дисконнект-цикл (этап 6). Двухфазный grace: обрыв → NOTIFY (дебаунс F5/морганий) →
# presence-offline сопернику → FORFEIT → победа оставшемуся. Значения монкипатчатся
# в тестах (→0), чтобы фоновый watcher не висел реальные секунды.
GRACE_NOTIFY_SECONDS = 10
GRACE_FORFEIT_SECONDS = 20

# Поколение grace-таймера на (room, side): бампается на join (реконнект) и на каждый
# новый disconnect-watch. Watcher проверяет, что его токен ещё актуален, иначе выходит —
# так реконнект отменяет висящий форфейт. На ОДИН процесс (как и _members).
_disc_token: dict[tuple[str, int], int] = defaultdict(int)


def _sides_online(room: str) -> dict[str, bool]:
    """Какие стороны сейчас в комнате (есть живой sid). Ключи — строки (JSON/шаблон)."""
    online = set(_members[room].values())
    return {"1": 1 in online, "2": 2 in online}


def _watch_valid(room: str, side: int, token: int) -> bool:
    """Актуален ли grace-watcher: его поколение не перебито И сторона всё ещё офлайн.

    Любое из двух условий, нарушенное реконнектом (бамп ``_disc_token`` в ``on_join``
    или возврат ``side`` в ``_members``), отменяет форфейт."""
    return _disc_token.get((room, side)) == token and side not in _members[room].values()


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
    # Реконнект отменяет висящий форфейт: бамп поколения делает токен watcher'а
    # неактуальным (_watch_valid → False), даже если он уже прошёл фазу NOTIFY.
    _disc_token[(game_id, side)] += 1
    # lite-присутствие: если зашёл P2 и партия уже active — P1 получит свежий state и
    # его waiting-экран сам сменится на active.
    emit("state", view, to=game_id)
    emit("hints", rooms.legal_hints(view, side), to=request.sid)
    # Presence-online рассылаем СРАЗУ всем в комнате (асимметрия: online мгновенно,
    # offline — с дебаунсом через grace-watcher).
    emit("presence", {"online": _sides_online(game_id), "grace_seconds": None}, to=game_id)


@socketio.on("move")
def on_move(payload):
    """Сходить. payload: ``{game_id, action, ply}``."""
    payload = payload or {}
    try:
        gid = uuid.UUID(str(payload.get("game_id", "")))
    except (ValueError, TypeError, AttributeError):
        emit("rejected", {"reason": "forbidden"})
        return

    db = SessionLocal()
    try:
        # Один SELECT ... FOR UPDATE: под тем же локом резолвим сторону (по сессии,
        # НЕ из payload) и пишем ход — без второго чтения строки.
        game = db.execute(
            select(Game).where(Game.id == gid).with_for_update()
        ).scalar_one_or_none()
        side = rooms.side_from_session(game, session) if game is not None else None
        if side is None:
            emit("rejected", {"reason": "forbidden"})
            return
        view = rooms.apply_action(db, game, side, payload.get("action"), payload.get("ply"))
    except rooms.ActionRejected as e:
        emit("rejected", {"reason": e.reason})
        return
    finally:
        db.close()

    # Новое состояние — всем в комнате; подсказки — персонально по стороне каждого sid.
    game_id = str(gid)
    emit("state", view, to=game_id)
    for sid, member_side in _members[game_id].items():
        emit("hints", rooms.legal_hints(view, member_side), to=sid)


@socketio.on("resign")
def on_resign(payload):
    """Сдаться. payload: ``{game_id}``. Соперник выигрывает (этап 6)."""
    game_id = str((payload or {}).get("game_id", ""))
    resolved = _resolve(game_id)
    if resolved is None:
        emit("rejected", {"reason": "forbidden"})
        return
    _, side = resolved

    db = SessionLocal()
    try:
        view = rooms.end_by_forfeit(db, uuid.UUID(game_id), 3 - side)
    finally:
        db.close()
    if view is None:                 # партия уже не active (двойной resign и т.п.)
        emit("rejected", {"reason": "not_active"})
        return

    # Исход — всем в комнате; presence сбрасывает отсчёт; hints персонально (пустые).
    emit("state", view, to=game_id)
    emit("presence", {"online": _sides_online(game_id), "grace_seconds": None}, to=game_id)
    for sid, member_side in _members[game_id].items():
        emit("hints", rooms.legal_hints(view, member_side), to=sid)


@socketio.on("disconnect")
def on_disconnect():
    """Обрыв сокета: убрать sid из реестра и, если сторона ушла офлайн при онлайн-сопернике,
    завести grace-watcher на форфейт (этап 6).

    sid принадлежит ровно одной комнате (join в on_join). Сторону/комнату фиксируем ДО
    удаления. Watcher заводим лишь когда оппонент в комнате — иначе некого уведомлять и
    некому присуждать победу (режет лишние фоновые потоки в тестах/у посторонних)."""
    sid = request.sid
    for room, members in _members.items():
        if sid not in members:
            continue
        side = members.pop(sid)
        if side not in members.values() and (3 - side) in members.values():
            _disc_token[(room, side)] += 1
            token = _disc_token[(room, side)]
            socketio.start_background_task(_forfeit_watch, room, side, token)
        break


def _forfeit_watch(room: str, side: int, token: int) -> None:
    """Фоновый двухфазный grace-таймер (этап 6). Importable — тестируется напрямую.

    Фаза 1 (NOTIFY): дебаунс F5/морганий сети. Если игрок вернулся — токен/присутствие
    делают ``_watch_valid`` False, выходим без шума. Иначе шлём сопернику presence-offline
    с отсчётом до форфейта. Фаза 2 (FORFEIT): ещё ждём; если не вернулся — ``end_by_forfeit``
    (победа оставшемуся). ``end_by_forfeit`` идемпотентен: если исход уже зафиксирован
    (resign/победный ход/другой таймер), вернёт None и watcher тихо выйдет."""
    socketio.sleep(GRACE_NOTIFY_SECONDS)
    if not _watch_valid(room, side, token):
        return
    socketio.emit(
        "presence",
        {"online": _sides_online(room), "grace_seconds": GRACE_FORFEIT_SECONDS},
        to=room,
    )

    socketio.sleep(GRACE_FORFEIT_SECONDS)
    if not _watch_valid(room, side, token):
        return
    db = SessionLocal()
    try:
        view = rooms.end_by_forfeit(db, uuid.UUID(room), 3 - side)
    finally:
        db.close()
    if view is None:                 # исход уже зафиксирован другим путём
        return

    socketio.emit("state", view, to=room)
    socketio.emit("presence", {"online": _sides_online(room), "grace_seconds": None}, to=room)
    for member_sid, member_side in list(_members[room].items()):
        socketio.emit("hints", rooms.legal_hints(view, member_side), to=member_sid)
