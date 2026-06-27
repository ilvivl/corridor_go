"""Комнаты и токены (этап 3): создание партии, назначение стороны, публичное состояние.

Здесь сосредоточена логика «кто есть кто» в партии. Импорта Flask нет: на вход
приходит dict-подобная сессия (плоские ключи ``{str(game_id): str(token)}``),
которую ``resolve_side`` мутирует напрямую. Так роуты остаются тонкими, а правила
членства — тестируемыми.

Заметка на будущее (этап 5): здесь же поселится единый код-путь записи хода под
``SELECT ... FOR UPDATE`` (PLAN этап 5). Сейчас не реализуем.
"""
import uuid

from sqlalchemy.orm import Session

from game import GameState, action_to_json, legal_moves
from server.models import Game


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


def resolve_side(game: Game, sess, db: Session) -> int | None:
    """Определить сторону клиента в партии по токену из сессии.

    ``sess`` — dict-подобная сессия Flask (плоские ключи ``str(game_id) -> str(token)``);
    при занятии стороны 2 мутируется напрямую. Возвращает:

    - ``1`` / ``2`` — токен из сессии совпал с игроком 1/2;
    - ``2`` — свободная партия: клиент занял сторону 2 (токен в колонку и в сессию,
      ``status='active'``, commit);
    - ``None`` — посторонний (партия заполнена, его токена в ней нет).

    Токены сравниваются строками: колонки ``*_token`` — ``uuid.UUID``, сессия же
    JSON-сериализуется, поэтому везде ``str(...)``.
    """
    key = str(game.id)
    tok = sess.get(key)
    if tok == str(game.player1_token):
        return 1
    if game.player2_token is not None and tok == str(game.player2_token):
        return 2

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


def legal_hints(game: Game, side: int) -> dict:
    """Подсказки легальных ходов для конкретной ``side`` (этап 4: рендер/хит-тест).

    В отличие от ``public_view`` функция знает сторону, но токенов не раскрывает.
    Сопернику не на ходу и в завершённой партии отдаём пустой список — клиент не
    должен видеть варианты, которые сейчас недоступны (контракт изоляции).

    Формат элементов ``moves`` совпадает с ``game.action_to_json``:
    ``{"type":"move","to":[c,r]}`` и ``{"type":"wall","c":..,"r":..,"o":"H|V"}``.
    Нагрузка (на старте ~3 хода + до 128 кандидатов-стен с BFS) — единицы мс,
    пересчёт на каждый рендер страницы допустим.
    """
    state = GameState.from_json(game.state)
    if state.winner is not None or side != state.turn:
        return {"your_turn": False, "moves": []}
    return {
        "your_turn": True,
        "moves": [action_to_json(a) for a in legal_moves(state)],
    }
