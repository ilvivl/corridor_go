"""Чистая геометрия и граф доски «Коридор» (Quoridor) 9×9.

Без понятия об игроках, ходах и состоянии партии — только клетки, стены,
проверки наложения стен и BFS-достижимость. Координаты: (col, row), 0..8.
"""
from collections import deque
from typing import Iterable, Iterator, NamedTuple

SIZE = 9            # клеток по стороне
WALL_SLOTS = 8      # пазов под стену по стороне (между клетками)

# 4 ортогональных направления (dcol, drow)
DIRECTIONS = ((0, 1), (0, -1), (1, 0), (-1, 0))

Pos = tuple[int, int]
Edge = tuple[Pos, Pos]


class Wall(NamedTuple):
    c: int   # якорь: столбец, 0..7
    r: int   # якорь: ряд, 0..7
    o: str   # ориентация: "H" (горизонтальная) | "V" (вертикальная)


def in_bounds(pos: Pos) -> bool:
    c, r = pos
    return 0 <= c < SIZE and 0 <= r < SIZE


def edge(a: Pos, b: Pos) -> Edge:
    """Канонический ключ ребра между двумя клетками (порядок не важен)."""
    return (a, b) if a <= b else (b, a)


def wall_edges(wall: Wall) -> frozenset[Edge]:
    """Два ребра графа, перекрываемых стеной."""
    c, r, o = wall
    if o == "H":
        return frozenset({
            edge((c, r), (c, r + 1)),
            edge((c + 1, r), (c + 1, r + 1)),
        })
    return frozenset({
        edge((c, r), (c + 1, r)),
        edge((c, r + 1), (c + 1, r + 1)),
    })


def blocked_edges(walls: Iterable[Wall]) -> set[Edge]:
    """Множество всех перекрытых рёбер для набора стен."""
    result: set[Edge] = set()
    for w in walls:
        result |= wall_edges(w)
    return result


def wall_conflicts(wall: Wall, walls: Iterable[Wall]) -> bool:
    """True, если стену нельзя поставить из-за геометрии уже стоящих стен:
    дубль / пересечение «крестом» (тот же якорь) или коллинеарное наложение.
    T- и L-стыки разрешены.
    """
    c, r, o = wall
    # тот же якорь занят — дубль или крест H×V
    if Wall(c, r, "H") in walls or Wall(c, r, "V") in walls:
        return True
    # коллинеарное наложение сегмента
    if o == "H":
        if Wall(c - 1, r, "H") in walls or Wall(c + 1, r, "H") in walls:
            return True
    else:
        if Wall(c, r - 1, "V") in walls or Wall(c, r + 1, "V") in walls:
            return True
    return False


def passable_neighbors(pos: Pos, blocked: set[Edge]) -> Iterator[Pos]:
    """Соседние клетки на доске, ребро к которым не перекрыто стеной."""
    for dc, dr in DIRECTIONS:
        n = (pos[0] + dc, pos[1] + dr)
        if in_bounds(n) and edge(pos, n) not in blocked:
            yield n


def has_path(walls: Iterable[Wall], start: Pos, goal_row: int) -> bool:
    """BFS: достижима ли любая клетка ряда goal_row из start с учётом стен.

    Игнорирует фишки и прыжки — соперник двигается и навсегда путь не блокирует,
    поэтому путь ищется только по клеткам и рёбрам, перекрытым стенами.
    """
    blocked = blocked_edges(walls)
    seen = {start}
    queue: deque[Pos] = deque([start])
    while queue:
        cur = queue.popleft()
        if cur[1] == goal_row:
            return True
        for n in passable_neighbors(cur, blocked):
            if n not in seen:
                seen.add(n)
                queue.append(n)
    return False
