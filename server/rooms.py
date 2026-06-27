"""Комнаты и токены (этап 3): создание партии, назначение стороны, публичное состояние.

Здесь сосредоточена логика «кто есть кто» в партии. Импорта Flask нет: на вход
приходит dict-подобная сессия (плоские ключи ``{str(game_id): str(token)}``),
которую ``resolve_side`` мутирует напрямую. Так роуты остаются тонкими, а правила
членства — тестируемыми.

Заметка на будущее (этап 5): здесь же поселится единый код-путь записи хода под
``SELECT ... FOR UPDATE`` (PLAN этап 5). Сейчас не реализуем.
"""
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from game import (
    GameState, IllegalMove, action_from_json, action_to_json, apply, legal_moves,
)
from server.models import Game, Move


class ActionRejected(Exception):
    """Ход отклонён слоем комнаты/ядром. ``reason`` — машиночитаемый код:
    ``game_not_found|not_active|not_your_turn|stale_ply|bad_action`` либо проброшенный
    ``IllegalMove.reason`` (``off_board|cell_occupied|blocked_by_wall|no_walls_left|
    wall_out_of_bounds|wall_overlap|wall_blocks_path|game_over``)."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def create_game(db: Session) -> Game:
    """Создать новую партию (статус ``waiting``, начальное состояние ядра).

    ``id`` и ``player1_token`` сгенерируются дефолтами модели при вставке;
    ``refresh`` подтягивает их на объект, чтобы сразу отдать ссылку и токен.
    """
    game = Game(state=GameState.initial().to_json())
    db.add(game)
    db.commit()
    db.refresh(game)
    return game


def side_from_session(game: Game, sess) -> int | None:
    """Read-only: сторона клиента по токену из сессии, без мутаций и БД.

    Общий код-путь аутентификации для HTTP (``resolve_side``) и сокета
    (``realtime._resolve``). Возвращает ``1``/``2`` при совпадении токена, иначе ``None``.

    Токены сравниваются строками: колонки ``*_token`` — ``uuid.UUID``, сессия же
    JSON-сериализуется, поэтому везде ``str(...)``.
    """
    tok = sess.get(str(game.id))
    if tok == str(game.player1_token):
        return 1
    if game.player2_token is not None and tok == str(game.player2_token):
        return 2
    return None


def resolve_side(game: Game, sess, db: Session) -> int | None:
    """Определить сторону клиента в партии по токену из сессии.

    ``sess`` — dict-подобная сессия Flask (плоские ключи ``str(game_id) -> str(token)``);
    при занятии стороны 2 мутируется напрямую. Возвращает:

    - ``1`` / ``2`` — токен из сессии совпал с игроком 1/2;
    - ``2`` — свободная партия: клиент занял сторону 2 (токен в колонку и в сессию,
      ``status='active'``, commit);
    - ``None`` — посторонний (партия заполнена, его токена в ней нет).
    """
    side = side_from_session(game, sess)
    if side is not None:
        return side

    key = str(game.id)
    if game.status == "waiting" and game.player2_token is None:
        game.player2_token = uuid.uuid4()
        game.status = "active"
        db.commit()
        sess[key] = str(game.player2_token)
        return 2

    return None


def public_view(game: Game) -> dict:
    """Санитизированное состояние партии для шаблона — БЕЗ токенов.

    ``game.state`` уже есть ``GameState.to_json()`` и токенов не содержит (они —
    отдельные колонки), поэтому достаточно дополнить его безопасными колонками.
    Единственный риск утечки — отдать в шаблон сам объект ``Game``; здесь его нет.
    """
    return {
        **game.state,
        "status": game.status,
        "ply": game.ply,
        "winner": game.winner,
    }


def legal_hints(state_json: dict, side: int) -> dict:
    """Подсказки легальных ходов для конкретной ``side`` (этап 4: рендер/хит-тест).

    ``state_json`` — dict состояния партии: ``game.state`` ЛИБО ``public_view(game)``
    (обе формы несут ``pawns/walls/walls_left/turn/winner``, которые читает
    ``GameState.from_json``). Так realtime считает hints из готового view без объекта ``Game``.

    В отличие от ``public_view`` функция знает сторону, но токенов не раскрывает.
    Сопернику не на ходу и в завершённой партии отдаём пустой список — клиент не
    должен видеть варианты, которые сейчас недоступны (контракт изоляции).

    Формат элементов ``moves`` совпадает с ``game.action_to_json``:
    ``{"type":"move","to":[c,r]}`` и ``{"type":"wall","c":..,"r":..,"o":"H|V"}``.
    Нагрузка (на старте ~3 хода + до 128 кандидатов-стен с BFS) — единицы мс,
    пересчёт на каждый рендер/ход допустим.
    """
    state = GameState.from_json(state_json)
    if state.winner is not None or side != state.turn:
        return {"your_turn": False, "moves": []}
    return {
        "your_turn": True,
        "moves": [action_to_json(a) for a in legal_moves(state)],
    }


def commit_action(
    db: Session, game_id, side: int, action_json: dict, expected_ply: int | None = None,
) -> dict:
    """Единый код-путь записи хода (этап 5). Чистый — без Flask/сокетов.

    Сервер — источник истины: блокируем строку партии ``SELECT ... FOR UPDATE``,
    перевалидируем ход ядром ``game/`` против состояния из БД и атомарно фиксируем
    новое состояние + запись в ``moves``. На любой отказ — ``ActionRejected(reason)``,
    без записи. Возвращает свежий ``public_view`` (без токенов).

    Защита от гонок: второй одновременный ход ждёт на ``FOR UPDATE`` до коммита
    первого, затем видит уже перевёрнутый ``turn`` → ``not_your_turn``;
    ``UNIQUE(game_id, ply)`` — финальный бэкстоп.
    """
    game = db.execute(
        select(Game).where(Game.id == game_id).with_for_update()
    ).scalar_one_or_none()
    if game is None:
        raise ActionRejected("game_not_found")
    if game.status != "active":
        raise ActionRejected("not_active")

    state = GameState.from_json(game.state)
    if side != state.turn:
        raise ActionRejected("not_your_turn")
    if expected_ply is not None and expected_ply != game.ply:
        raise ActionRejected("stale_ply")

    try:
        action = action_from_json(action_json)
    except (ValueError, KeyError, TypeError):
        raise ActionRejected("bad_action")
    try:
        new = apply(state, action)
    except IllegalMove as e:
        raise ActionRejected(e.reason)

    # КОНТРАКТ БД: state переприсваиваем ЦЕЛИКОМ (SQLAlchemy не трекает мутации JSONB).
    game.state = new.to_json()
    game.ply += 1
    game.winner = new.winner
    if new.winner is not None:
        game.status = "finished"
    db.add(Move(
        game_id=game.id, ply=game.ply, player=side, action=action_to_json(action),
    ))
    db.commit()
    # expire_on_commit=False → поля game доступны без refresh.
    return public_view(game)
