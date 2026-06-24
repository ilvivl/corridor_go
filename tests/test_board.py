from game.board import (
    Wall, edge, wall_edges, wall_conflicts, has_path, in_bounds,
)


def test_in_bounds():
    assert in_bounds((0, 0))
    assert in_bounds((8, 8))
    assert not in_bounds((-1, 0))
    assert not in_bounds((9, 0))
    assert not in_bounds((0, 9))


def test_wall_edges_horizontal():
    assert wall_edges(Wall(3, 4, "H")) == frozenset({
        edge((3, 4), (3, 5)),
        edge((4, 4), (4, 5)),
    })


def test_wall_edges_vertical():
    assert wall_edges(Wall(3, 4, "V")) == frozenset({
        edge((3, 4), (4, 4)),
        edge((3, 5), (4, 5)),
    })


def test_wall_conflicts_duplicate():
    assert wall_conflicts(Wall(3, 4, "H"), frozenset({Wall(3, 4, "H")}))


def test_wall_conflicts_cross():
    assert wall_conflicts(Wall(3, 4, "V"), frozenset({Wall(3, 4, "H")}))


def test_wall_conflicts_collinear_horizontal():
    walls = frozenset({Wall(3, 4, "H")})
    assert wall_conflicts(Wall(4, 4, "H"), walls)
    assert wall_conflicts(Wall(2, 4, "H"), walls)


def test_wall_conflicts_collinear_vertical():
    walls = frozenset({Wall(3, 4, "V")})
    assert wall_conflicts(Wall(3, 5, "V"), walls)
    assert wall_conflicts(Wall(3, 3, "V"), walls)


def test_wall_no_conflict_gap_and_junctions():
    walls = frozenset({Wall(3, 4, "H")})
    assert not wall_conflicts(Wall(5, 4, "H"), walls)   # коллинеар с зазором
    assert not wall_conflicts(Wall(1, 4, "H"), walls)
    assert not wall_conflicts(Wall(3, 5, "H"), walls)   # параллель в соседнем ряду
    assert not wall_conflicts(Wall(3, 5, "V"), walls)   # T-стык на другом якоре


def test_has_path_open_board():
    assert has_path(frozenset(), (4, 0), 8)
    assert has_path(frozenset(), (4, 8), 0)


def test_has_path_blocked_corner():
    # клетка (0,0) полностью заперта (стены пересекаются — для has_path не важно)
    walls = frozenset({Wall(0, 0, "H"), Wall(0, 0, "V")})
    assert not has_path(walls, (0, 0), 8)


def test_has_path_detour():
    # стена удлиняет путь, но не запирает его
    assert has_path(frozenset({Wall(3, 0, "H")}), (4, 0), 8)
