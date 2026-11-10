"""
Known (proven) packings used by the literature verification test, with their solutions.
Point packings (circles in a square, spheres in a cube) are found by maximizing the minimum separation with random restarts and checked against the proven values.
Polycube puzzles are solved by depth-first search. Everything is in unit boxes; scale as needed.
"""

import numpy as np
from scipy.optimize import minimize

# Proven minimal separations (unit square / unit cube), from the literature tables.
CIRCLES_IN_SQUARE_SEPARATION = {5: 0.7071, 10: 0.4213, 17: 0.3062}
SPHERES_IN_CUBE_SEPARATION = {8: 1.0, 9: 0.8660, 14: 0.7071}


def max_min_separation(count, dimension, restarts, seed):
    """Best arrangement of count points in the unit square (dimension 2) or cube (3) maximizing the smallest pairwise distance. Soft-min objective, then polish."""
    rng = np.random.default_rng(seed)
    pair_i, pair_j = np.triu_indices(count, 1)
    best_points = None
    best_separation = 0.0
    for restart in range(restarts):
        points = rng.uniform(0, 1, (count, dimension))
        for sharpness in (20.0, 80.0, 300.0):
            def objective(flat):
                p = flat.reshape(count, dimension)
                d = np.linalg.norm(p[pair_i] - p[pair_j], axis=1)
                return np.log(np.sum(np.exp(-sharpness * d))) / sharpness
            result = minimize(objective, points.ravel(), method="L-BFGS-B", bounds=[(0, 1)] * (count * dimension))
            points = result.x.reshape(count, dimension)
        # Polish: maximize s subject to every pairwise distance >= s (SLSQP on the active pairs).
        separation = np.linalg.norm(points[pair_i] - points[pair_j], axis=1).min()
        start = np.concatenate([points.ravel(), [separation]])
        def negative_s(variables):
            return -variables[-1]
        def constraints(variables):
            p = variables[:-1].reshape(count, dimension)
            return np.linalg.norm(p[pair_i] - p[pair_j], axis=1) - variables[-1]
        polished = minimize(negative_s, start, method="SLSQP", bounds=[(0, 1)] * (count * dimension) + [(0, 2)], constraints=[{"type": "ineq", "fun": constraints}], options={"maxiter": 300, "ftol": 1e-12})
        polished_points = polished.x[:-1].reshape(count, dimension)
        polished_separation = np.linalg.norm(polished_points[pair_i] - polished_points[pair_j], axis=1).min()
        if polished_separation > separation:
            points = polished_points
            separation = polished_separation
        if separation > best_separation:
            best_separation = separation
            best_points = points.copy()
    return best_points, best_separation


def solve_polycube(pieces, box, limit=1):
    """Exact cover by depth-first search. pieces: list of lists of (x, y, z) cells. Returns list of solutions, each a list of (piece_index, cells) in the same orientation convention (all 24 rotations tried, translations tried)."""
    def rotations(cells):
        cells = np.array(cells)
        seen = {}
        matrices = []
        for a in range(4):
            for b in range(4):
                for c in range(4):
                    rx = np.array([[1, 0, 0], [0, 0, -1], [0, 1, 0]])
                    ry = np.array([[0, 0, 1], [0, 1, 0], [-1, 0, 0]])
                    rz = np.array([[0, -1, 0], [1, 0, 0], [0, 0, 1]])
                    matrices.append(np.linalg.matrix_power(rx, a) @ np.linalg.matrix_power(ry, b) @ np.linalg.matrix_power(rz, c))
        for matrix in matrices:
            rotated = cells @ matrix.T
            rotated = rotated - rotated.min(axis=0)
            key = tuple(sorted(map(tuple, rotated)))
            seen[key] = rotated
        return list(seen.values())
    box = np.array(box)
    placements_per_piece = []
    for cells in pieces:
        options = []
        for rotated in rotations(cells):
            extent = rotated.max(axis=0) + 1
            for x in range(box[0] - extent[0] + 1):
                for y in range(box[1] - extent[1] + 1):
                    for z in range(box[2] - extent[2] + 1):
                        placed = rotated + np.array([x, y, z])
                        options.append(frozenset(int(c[0] + box[0] * (c[1] + box[1] * c[2])) for c in placed))
        placements_per_piece.append(options)
    solutions = []
    order = sorted(range(len(pieces)), key=lambda i: len(placements_per_piece[i]))
    def search(filled, depth, chosen):
        if len(solutions) >= limit:
            return
        if depth == len(order):
            solutions.append(list(chosen))
            return
        piece = order[depth]
        for option in placements_per_piece[piece]:
            if filled & option:
                continue
            chosen.append((piece, option))
            search(filled | option, depth + 1, chosen)
            chosen.pop()
            if len(solutions) >= limit:
                return
    search(frozenset(), 0, [])
    decoded = []
    for solution in solutions:
        decoded.append([(int(piece), [(int(c % box[0]), int((c // box[0]) % box[1]), int(c // (box[0] * box[1]))) for c in sorted(option)]) for piece, option in solution])
    return decoded


SOMA_PIECES = [[(0, 0, 0), (1, 0, 0), (0, 1, 0)], [(0, 0, 0), (1, 0, 0), (2, 0, 0), (0, 1, 0)], [(0, 0, 0), (1, 0, 0), (1, 1, 0), (2, 1, 0)], [(0, 0, 0), (1, 0, 0), (2, 0, 0), (1, 1, 0)], [(0, 0, 0), (1, 0, 0), (1, 1, 0), (1, 1, 1)], [(0, 0, 0), (1, 0, 0), (1, 1, 0), (1, 0, 1)], [(0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1)]]
SLOTHOUBER_GRAATSMA_PIECES = [[(0, 0, 0), (1, 0, 0), (0, 1, 0), (1, 1, 0)]] * 6 + [[(0, 0, 0)]] * 3
CONWAY_PIECES = [[(0, 0, 0), (1, 0, 0), (2, 0, 0)]] * 3 + [[(0, 0, 0), (1, 0, 0), (0, 1, 0), (1, 1, 0)]] + [[(x, y, z) for x in range(2) for y in range(2) for z in range(2)]] + [[(x, y, 0) for x in range(2) for y in range(4)]] * 13
