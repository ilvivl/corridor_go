"""Правила, состояние и сериализация партии «Коридор».

Состояние иммутабельно: ``apply(state, action)`` возвращает НОВЫЙ ``GameState``.
Нелегальный ход — исключение ``IllegalMove(reason)`` с машиночитаемым кодом.
Сериализация ``to_json``/``from_json`` — контракт с jsonb-колонкой на этапе 2.
"""
from dataclasses import dataclass, replace

from .board import (
    WALL_SLOTS, DIRECTIONS, Pos, Wall,
    in_bounds, edge, blocked_edges, wall_conflicts, has_path,
)

INITIAL_WALLS = 10
START: dict[int, Pos] = {1: (4, 0), 2: (4, 8)}
GOAL_ROW: dict[int, int] = {1: 8, 2: 0}


class IllegalMove(Exception):
    """Ход отклонён правилами. ``reason`` — машиночитаемый код причины."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class MovePawn:
    to: Pos


@dataclass(frozen=True)
class PlaceWall:
    c: int
    r: int
    o: str


Action = MovePawn | PlaceWall


@dataclass(frozen=True)
class GameState:
    pawns: tuple[Pos, Pos]        # позиции игроков 1 и 2
    walls: frozenset[Wall]
    walls_left: tuple[int, int]   # остаток стен у игроков 1 и 2
    turn: int                     # чей ход: 1 | 2
    winner: int | None = None

    @classmethod
    def initial(cls) -> "GameState":
        return cls(
            pawns=(START[1], START[2]),
            walls=frozenset(),
            walls_left=(INITIAL_WALLS, INITIAL_WALLS),
            turn=1,
            winner=None,
        )

    # --- сериализация (контракт с jsonb на этапе 2) ---
    def to_json(self) -> dict:
        return {
            "pawns": {"1": list(self.pawns[0]), "2": list(self.pawns[1])},
            "walls": [{"c": w.c, "r": w.r, "o": w.o} for w in sorted(self.walls)],
            "walls_left": {"1": self.walls_left[0], "2": self.walls_left[1]},
            "turn": self.turn,
            "winner": self.winner,
        }

    @classmethod
    def from_json(cls, data: dict) -> "GameState":
        return cls(
            pawns=(tuple(data["pawns"]["1"]), tuple(data["pawns"]["2"])),
            walls=frozenset(Wall(w["c"], w["r"], w["o"]) for w in data["walls"]),
            walls_left=(data["walls_left"]["1"], data["walls_left"]["2"]),
            turn=data["turn"],
            winner=data["winner"],
        )


def _other(turn: int) -> int:
    return 2 if turn == 1 else 1


def _perpendicular(d: tuple[int, int]) -> tuple[tuple[int, int], tuple[int, int]]:
    dc, _ = d
    return ((0, 1), (0, -1)) if dc != 0 else ((1, 0), (-1, 0))


def pawn_destinations(state: GameState) -> set[Pos]:
    """Клетки, куда сторона ``state.turn`` может пойти фишкой.

    Полный стандарт прыжков: при смежном сопернике — прямой прыжок через него,
    а если позади него стена/край доски — диагональный шаг вбок.
    """
    player = state.turn
    me = state.pawns[player - 1]
    opp = state.pawns[2 - player]          # фишка соперника
    blocked = blocked_edges(state.walls)
    dests: set[Pos] = set()
    for d in DIRECTIONS:
        n1 = (me[0] + d[0], me[1] + d[1])
        if not in_bounds(n1) or edge(me, n1) in blocked:
            continue
        if n1 != opp:
            dests.add(n1)
            continue
        # соперник прямо по курсу — пробуем прыжок
        n2 = (opp[0] + d[0], opp[1] + d[1])
        if in_bounds(n2) and edge(opp, n2) not in blocked:
            dests.add(n2)                  # прямой прыжок
        else:
            for p in _perpendicular(d):    # позади стена/край — по диагонали
                diag = (opp[0] + p[0], opp[1] + p[1])
                if in_bounds(diag) and edge(opp, diag) not in blocked:
                    dests.add(diag)
    return dests


def _validate_move(state: GameState, action: MovePawn) -> None:
    to = action.to
    if not in_bounds(to):
        raise IllegalMove("off_board")
    if to in state.pawns:
        raise IllegalMove("cell_occupied")
    if to not in pawn_destinations(state):
        raise IllegalMove("blocked_by_wall")


def _validate_wall(state: GameState, action: PlaceWall) -> None:
    if state.walls_left[state.turn - 1] <= 0:
        raise IllegalMove("no_walls_left")
    if action.o not in ("H", "V") or not (
        0 <= action.c < WALL_SLOTS and 0 <= action.r < WALL_SLOTS
    ):
        raise IllegalMove("wall_out_of_bounds")
    wall = Wall(action.c, action.r, action.o)
    if wall_conflicts(wall, state.walls):
        raise IllegalMove("wall_overlap")
    new_walls = state.walls | {wall}
    # путь к цели должен остаться у ОБОИХ игроков
    for player in (1, 2):
        if not has_path(new_walls, state.pawns[player - 1], GOAL_ROW[player]):
            raise IllegalMove("wall_blocks_path")


def apply(state: GameState, action: Action) -> GameState:
    """Проверить и применить ход, вернув новое состояние. Исходное не меняется."""
    if state.winner is not None:
        raise IllegalMove("game_over")

    if isinstance(action, MovePawn):
        _validate_move(state, action)
        player = state.turn
        pawns = list(state.pawns)
        pawns[player - 1] = action.to
        won = action.to[1] == GOAL_ROW[player]
        return replace(
            state,
            pawns=(pawns[0], pawns[1]),
            winner=player if won else None,
            turn=state.turn if won else _other(state.turn),
        )

    if isinstance(action, PlaceWall):
        _validate_wall(state, action)
        player = state.turn
        wl = list(state.walls_left)
        wl[player - 1] -= 1
        return replace(
            state,
            walls=state.walls | {Wall(action.c, action.r, action.o)},
            walls_left=(wl[0], wl[1]),
            turn=_other(state.turn),
        )

    raise IllegalMove("unknown_action")


def is_legal(state: GameState, action: Action) -> bool:
    try:
        apply(state, action)
        return True
    except IllegalMove:
        return False


def legal_moves(state: GameState) -> list[Action]:
    """Все легальные действия стороны, чей ход. Пуст только при завершённой партии
    (тупика «нет хода» в «Коридоре» не бывает — всегда можно перепрыгнуть фишку)."""
    if state.winner is not None:
        return []
    moves: list[Action] = [MovePawn(to) for to in pawn_destinations(state)]
    if state.walls_left[state.turn - 1] > 0:
        for c in range(WALL_SLOTS):
            for r in range(WALL_SLOTS):
                for o in ("H", "V"):
                    action = PlaceWall(c, r, o)
                    if is_legal(state, action):
                        moves.append(action)
    return moves


def replay(actions: list[Action]) -> GameState:
    """Пересобрать состояние, применяя действия от начальной позиции (для тестов)."""
    state = GameState.initial()
    for action in actions:
        state = apply(state, action)
    return state


# --- сериализация действий ---
def action_from_json(data: dict) -> Action:
    t = data.get("type")
    if t == "move":
        return MovePawn(tuple(data["to"]))
    if t == "wall":
        return PlaceWall(data["c"], data["r"], data["o"])
    raise ValueError(f"unknown action type: {t!r}")


def action_to_json(action: Action) -> dict:
    if isinstance(action, MovePawn):
        return {"type": "move", "to": list(action.to)}
    if isinstance(action, PlaceWall):
        return {"type": "wall", "c": action.c, "r": action.r, "o": action.o}
    raise ValueError(f"unknown action: {action!r}")
