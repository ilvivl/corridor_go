"""Ручной смоук HTTP-слоя (этап 3): создать партию → войти вторым → прочитать.

Запуск (после docker compose up -d и alembic upgrade head):
    python scripts/smoke_http.py             # смоук, партию удаляет за собой
    python scripts/smoke_http.py --keep      # оставить партию в БД
    python scripts/smoke_http.py --seed ID   # засеять не-начальный state в свою
                                             # партию ID (создать её в браузере как
                                             # P1, затем перезагрузить страницу) —
                                             # визуальная проверка рендера стен/прыжков

Не юнит-тест: гоняет настоящие запросы через app.test_client() и пишет реальную
строку в games.
"""
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # корень проекта

from game import MovePawn, PlaceWall, replay  # noqa: E402
from server.app import create_app  # noqa: E402
from server.db import SessionLocal  # noqa: E402
from server.models import Game  # noqa: E402


def main(keep: bool = False) -> None:
    app = create_app()

    creator = app.test_client()
    resp = creator.post("/game")
    game_id = resp.headers["Location"].rsplit("/", 1)[-1]
    print(f"создано: /game/{game_id}")

    page1 = creator.get(f"/game/{game_id}").get_data(as_text=True)
    role1 = "игрок 1" if "Вы — игрок 1" in page1 else "??"
    print(f"  создатель опознан как: {role1}")

    second = app.test_client()
    page2 = second.get(f"/game/{game_id}").get_data(as_text=True)
    role2 = "игрок 2" if "Вы — игрок 2" in page2 else "??"
    print(f"  второй клиент: {role2}")

    third = app.test_client()
    resp3 = third.get(f"/game/{game_id}")
    print(f"  третий клиент: HTTP {resp3.status_code} "
          f"({'партия заполнена' if resp3.status_code == 403 else '??'})")

    with SessionLocal() as db:
        game = db.get(Game, uuid.UUID(game_id))
        assert game is not None, "партия не найдена в БД"
        assert game.status == "active", f"ожидался active, получено {game.status}"
        tokens = [str(game.player1_token), str(game.player2_token)]
        assert all(t not in page1 and t not in page2 for t in tokens), \
            "токен утёк в HTML!"
        print(f"  статус в БД: {game.status}; токены в HTML не утекли")

        if not keep:
            db.delete(game)  # каскадом удалит и moves
            db.commit()
            print("партия удалена (--keep чтобы оставить)")

    print("СМОУК OK")


def seed_demo(game_id: str) -> None:
    """Перезаписать state УЖЕ существующей партии ``game_id`` демо-позицией.

    Создай партию в браузере как P1, передай её id сюда и перезагрузи страницу —
    своя сессия (а значит сторона) сохранится. Демо: пара стен (H и V) и
    продвинутые пешки, чтобы глазами сверить геометрию с game/board.py wall_edges.
    """
    # Легальная демо-последовательность (порядок ходов 1,2,1,2):
    state = replay([
        PlaceWall(3, 3, "H"),   # P1: горизонтальная стена
        MovePawn((4, 7)),       # P2: шаг вперёд
        MovePawn((4, 1)),       # P1: шаг вперёд
        PlaceWall(2, 5, "V"),   # P2: вертикальная стена
    ])

    with SessionLocal() as db:
        game = db.get(Game, uuid.UUID(game_id))
        assert game is not None, f"партия {game_id} не найдена"
        game.state = state.to_json()
        db.commit()

    print(f"засеяно: /game/{game_id}")
    print(f"  стены: H(3,3), V(2,5); пешки P1=(4,1) P2=(4,7); ход игрока {state.turn}")
    print("  перезагрузи страницу как P1 и сверь геометрию H/V глазами")


if __name__ == "__main__":
    if "--seed" in sys.argv:
        i = sys.argv.index("--seed")
        if i + 1 >= len(sys.argv):
            sys.exit("usage: python scripts/smoke_http.py --seed <game_id>")
        seed_demo(sys.argv[i + 1])
    else:
        main(keep="--keep" in sys.argv)
