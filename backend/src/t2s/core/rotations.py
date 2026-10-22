"""The 24 proper axis-aligned rotations (signed permutation matrices with det = +1).

Index 0 is the identity. The order is fixed and deterministic; the same table is sent to the
front end in the project snapshot, so no other component may build its own.
"""
from itertools import permutations, product

import numpy as np


def _build() -> np.ndarray:
    mats = []
    for perm in permutations(range(3)):
        for signs in product((1, -1), repeat=3):
            m = np.zeros((3, 3), dtype=np.int64)
            for row, (col, s) in enumerate(zip(perm, signs)):
                m[row, col] = s
            if round(np.linalg.det(m)) == 1:
                mats.append(m)
    mats.sort(key=lambda m: (0 if np.array_equal(m, np.eye(3, dtype=np.int64)) else 1, tuple(m.ravel())))
    return np.array(mats, dtype=np.int64)


ROTATIONS: np.ndarray = _build()          # shape (24, 3, 3), integer entries
ROTATIONS_F: np.ndarray = ROTATIONS.astype(np.float64)
assert ROTATIONS.shape == (24, 3, 3)


def rotate_tensor(index: int, tensor: np.ndarray) -> np.ndarray:
    """R I R^T for a signed permutation: exact (only index permutation and sign flips)."""
    r = ROTATIONS_F[index]
    return r @ tensor @ r.T


def as_lists() -> list[list[int]]:
    return [m.ravel().tolist() for m in ROTATIONS]
