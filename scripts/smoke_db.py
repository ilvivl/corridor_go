"""Ручной смоук слоя БД (этап 2): создать партию → прочитать обратно.

Запуск (после docker compose up -d и alembic upgrade head):
    python scripts/smoke_db.py

Не юнит-тест: пишет реальную строку в games и читает её. Партию по умолчанию
удаляет за собой (--keep оставит в БД для ручного осмотра).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # корень проекта

from game import GameState  # noqa: E402
from server.db import SessionLocal  # noqa: E402
from server.models import Game, Move  # noqa: E402


def main(keep: bool = False) -> None:
    with SessionLocal() as session:
        game = Game(state=GameState.initial().to_json())
        session.add(game)
        session.flush()  # получить сгенерённые id/таймстемпы

        # пробный первый полуход в истории
        session.add(Move(
            game_id=game.id, ply=1, player=1,
            action={"type": "move", "to": [4, 1]},
        ))
        session.commit()
        game_id = game.id
        print(f"создано: {game!r}")
        print(f"  player1_token={game.player1_token}")
        print(f"  created_at={game.created_at}  updated_at={game.updated_at}")

    # читаем в новой сессии — проверяем, что реально записалось
    with SessionLocal() as session:
        loaded = session.get(Game, game_id)
        assert loaded is not None, "партия не найдена после коммита"
        restored = GameState.from_json(loaded.state)
        assert restored == GameState.initial(), "state не сходится с ядром"
        print(f"прочитано: {loaded!r}  ходов={len(loaded.moves)}")
        print(f"  state→ядро round-trip: OK (turn={restored.turn})")

        if not keep:
            session.delete(loaded)  # каскадом удалит и moves
            session.commit()
            print("партия удалена (--keep чтобы оставить)")

    print("СМОУК OK")


if __name__ == "__main__":
    main(keep="--keep" in sys.argv)
