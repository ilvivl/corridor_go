# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Current state

**Этап 1 (`game/` ядро) реализован и оттестирован** (39 тестов зелёные). **Этап 2 (слой БД) реализован**: Postgres 16 в Docker (`docker-compose.yml`), модели `server/models.py` (`Game`, `Move`) на SQLAlchemy 2.0, миграции Alembic (`migrations/`, head применён), смоук `scripts/smoke_db.py` зелёный. **Этап 3 (HTTP-скелет) реализован**: фабрика `server/app.py` (`create_app`), комнаты/токены `server/rooms.py` (`create_game`/`resolve_side`/`public_view`), точка входа `app.py` (`python app.py`), шаблоны `templates/` (`base`/`index`/`game`), `static/style.css`. Идентификация — `player_token` в подписанной сессии Flask (плоские ключи `{str(game_id): str(token)}`). **Этап 4 (Canvas-рендер) реализован**: `server/rooms.py` `legal_hints(game, side)` (side-aware подсказки ходов, без токенов), `server/app.py` отдаёт инлайн-JSON `client_state={view,hints,my_side}` в `<script id="game-data">`, `static/board.js` (ES-модуль) рисует доску 9×9 с эгоцентриком (поворот 180° для P1), HUD/палитра Blueprint в `static/style.css` + `templates/game.html`, hover-хит-тест по hints (отправки хода ещё нет — пустой шов `commitAction`). Тесты `tests/test_http.py` + `tests/test_rooms_hints.py` + смоук `scripts/smoke_http.py` (`--seed <game_id>` для визуальной проверки не-начальной позиции) зелёные. **Этап 5 (realtime) реализован**: транспорт `server/realtime.py` (Flask-SocketIO, `async_mode="threading"`, без eventlet/gevent; `simple-websocket` для WS на Werkzeug), единый код-путь записи хода `server/rooms.py` `commit_action(db, game_id, side, action_json, expected_ply)` под `SELECT ... FOR UPDATE` (исключение `ActionRejected(reason)`), read-only хелпер `side_from_session` (общий с `resolve_side`), `legal_hints` теперь принимает `state_json` (а не объект `Game`). Доставка: `state` (public_view) broadcast в комнату + `hints` персонально на каждый sid (изоляция). `client_state` получил `game_id`; `static/board.js` шлёт `move` по сокету (lock ввода до ответа) и живьём обновляет доску/HUD (`renderHud`) на `state`/`hints`/`rejected`; завендоренный клиент `static/socket.io.min.js` (socket.io 4.7.5). Точка входа `app.py` — `socketio.run(...)`. Тесты `tests/test_rooms_commit.py` + `tests/test_realtime.py` (через `socketio.test_client`, делит сессию с HTTP) зелёные (всего 63 теста). Дисконнект/реконнект/`abandoned` — этап 6, ещё не сделан. Конфиг — `.env` (gitignored, шаблон `.env.example`). Архитектура/этапы и правила игры зафиксированы в auto-memory: `corridor-go-plan` (источник истины по архитектуре и этапам), `corridor-go-rules` (геометрия, ходы, прыжки, стены, BFS), `corridor-go-canvas-decisions` (решения этапа 4), `corridor-go-realtime-decisions` (решения этапа 5) — читать при любой работе с `game/`/рендером/realtime. (Папка `docs/` удалена из репозитория.)

Communication with the user is in **Russian**.

## What this is

"Коридор" — a web implementation of Quoridor (9×9 board, move your pawn to the opposite edge while placing walls to block the opponent). Target: **online human-vs-human play via invite link**, no accounts. Play-vs-AI is explicitly **out of MVP scope** (added later).

## Commands

```bash
# Setup (once)
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Run/test (Postgres must be up: `docker compose up -d`, миграции на head):
- Local run: `python app.py` (Flask-SocketIO dev server on `:5000`, `async_mode="threading"`).
- Tests: `pytest` (ядро `game/` юнит-тестировано независимо от web/DB; HTTP-тесты требуют поднятого Postgres).
- Смоук-скрипты: `python scripts/smoke_db.py`, `python scripts/smoke_http.py` (`--keep` оставит партию в БД).

## Planned architecture (from `corridor-go-plan` memory)

Four backend layers, kept separable:

1. **`game/`** — pure Python game core (board, move/wall legality, BFS check that a wall never fully blocks a player's path, win detection). No Flask, no DB dependency. This is the foundation and is built first (stage 1).
2. **HTTP layer (Flask)** — pages, create game, join by room link/code, serve static.
3. **Realtime layer (Flask-SocketIO)** — room join, receiving moves, validating via `game/`, broadcasting updated state to both players, disconnect/win notifications.
4. **Data layer (PostgreSQL)** — game persistence via SQLAlchemy + Alembic migrations (or psycopg). Schema sketch (`games`, `moves` tables) is in the `corridor-go-plan` memory.

Frontend: HTML + Canvas + vanilla JS (no React). The JS client holds a WebSocket, sends moves, receives state, redraws.

## Key design constraints

- **Server holds the truth.** The client is never trusted; every move is re-validated server-side by the `game/` core against state loaded from the DB.
- **No accounts.** Player identity is a secret `player_token` (HttpOnly cookie / URL), mapping a client to side 1 or 2. The opponent's token must never leak to the client (not in lobby, not in public game state).
- **Race protection.** Two players share one DB row of state. Use `moves.ply` (half-move number) and/or `SELECT ... FOR UPDATE` to reject stale/duplicate moves (stage 5/6).
- **Build a thin vertical slice early** — get the move→state→broadcast loop working (even text-only) before investing in Canvas rendering.
- `eventlet` is flagged as risky with modern Python; consider `gevent` + `gevent-websocket` for the SocketIO worker (decide at stage 5/7).

## Build order

Follow the 7 stages in the `corridor-go-plan` memory: (1) `game/` core + tests, (2) DB infra, (3) HTTP skeleton, (4) Canvas render, (5) realtime, (6) full online cycle (reconnect/disconnect/win), (7) deploy (gunicorn + eventlet/gevent, managed Postgres, env config via `DATABASE_URL`/`SECRET_KEY`).
