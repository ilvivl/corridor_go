# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Current state

**Этап 1 (`game/` ядро) реализован и оттестирован** (39 тестов зелёные). **Этап 2 (слой БД) реализован**: Postgres 16 в Docker (`docker-compose.yml`), модели `server/models.py` (`Game`, `Move`) на SQLAlchemy 2.0, миграции Alembic (`migrations/`, head применён), смоук `scripts/smoke_db.py` зелёный. Конфиг — `.env` (gitignored, шаблон `.env.example`). `docs/PLAN.md` — источник истины по архитектуре и этапам. `docs/RULES.md` — зафиксированные правила игры (геометрия, ходы, прыжки, стены, BFS) — читать при любой работе с `game/`.

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

There is no run/test command yet — the app code does not exist. When added per the plan:
- Local run: `python app.py` (Flask-SocketIO dev server), Postgres in Docker.
- Tests: `pytest` (the `game/` core must be fully unit-tested, independent of web/DB).

## Planned architecture (from docs/PLAN.md)

Four backend layers, kept separable:

1. **`game/`** — pure Python game core (board, move/wall legality, BFS check that a wall never fully blocks a player's path, win detection). No Flask, no DB dependency. This is the foundation and is built first (stage 1).
2. **HTTP layer (Flask)** — pages, create game, join by room link/code, serve static.
3. **Realtime layer (Flask-SocketIO)** — room join, receiving moves, validating via `game/`, broadcasting updated state to both players, disconnect/win notifications.
4. **Data layer (PostgreSQL)** — game persistence via SQLAlchemy + Alembic migrations (or psycopg). Schema sketch (`games`, `moves` tables) is in `docs/PLAN.md`.

Frontend: HTML + Canvas + vanilla JS (no React). The JS client holds a WebSocket, sends moves, receives state, redraws.

## Key design constraints

- **Server holds the truth.** The client is never trusted; every move is re-validated server-side by the `game/` core against state loaded from the DB.
- **No accounts.** Player identity is a secret `player_token` (HttpOnly cookie / URL), mapping a client to side 1 or 2. The opponent's token must never leak to the client (not in lobby, not in public game state).
- **Race protection.** Two players share one DB row of state. Use `moves.ply` (half-move number) and/or `SELECT ... FOR UPDATE` to reject stale/duplicate moves (stage 5/6).
- **Build a thin vertical slice early** — get the move→state→broadcast loop working (even text-only) before investing in Canvas rendering.
- `eventlet` is flagged as risky with modern Python; consider `gevent` + `gevent-websocket` for the SocketIO worker (decide at stage 5/7).

## Build order

Follow the 7 stages in `docs/PLAN.md`: (1) `game/` core + tests, (2) DB infra, (3) HTTP skeleton, (4) Canvas render, (5) realtime, (6) full online cycle (reconnect/disconnect/win), (7) deploy (gunicorn + eventlet/gevent, managed Postgres, env config via `DATABASE_URL`/`SECRET_KEY`).
