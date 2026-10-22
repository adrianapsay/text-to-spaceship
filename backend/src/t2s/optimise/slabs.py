"""Slab post-optimiser (A1): change the COM/inertia without changing the used length.

A layout splits at guillotine planes z = c that no part crosses. Slabs can be reordered (stacked from the same
floor, keeping their internal gaps), rotated by 0/90/180/270° about the enclosure axis and flipped 180° about X.
The enclosure is symmetric about its axis and slab heights are preserved, so the length used is unchanged and the
layout stays inside; slabs never interpenetrate because they keep disjoint Z intervals. Results are re-validated.
"""
from __future__ import annotations

from itertools import permutations

import numpy as np

from ..core.rotations import ROTATIONS, ROTATIONS_F

_KEY = {tuple(r.ravel()): i for i, r in enumerate(ROTATIONS)}


def rot_index(r: np.ndarray) -> int:
    return _KEY[tuple(np.rint(r).astype(int).ravel())]


RZ = [np.array([[1, 0, 0], [0, 1, 0], [0, 0, 1]]), np.array([[0, -1, 0], [1, 0, 0], [0, 0, 1]]),
      np.array([[-1, 0, 0], [0, -1, 0], [0, 0, 1]]), np.array([[0, 1, 0], [-1, 0, 0], [0, 0, 1]])]
RX180 = np.array([[1, 0, 0], [0, -1, 0], [0, 0, -1]])


def find_slabs(z_intervals: list[tuple[float, float]]) -> list[list[int]]:
    order = np.argsort([a for a, _ in z_intervals])
    slabs, cur, cur_hi = [], [], -np.inf
    for i in order:
        a, b = z_intervals[i]
        if cur and a >= cur_hi - 1e-9:
            slabs.append(cur)
            cur, cur_hi = [], -np.inf
        cur.append(int(i))
        cur_hi = max(cur_hi, b)
    if cur:
        slabs.append(cur)
    return slabs


def transform_slab(poses, members, rot: np.ndarray, z_lo_old: float, z_hi_old: float, z_lo_new: float):
    """Apply rotation `rot` about the slab's own Z mid-plane on the enclosure axis, then move it to z_lo_new."""
    out = list(poses)
    zc_old = 0.5 * (z_lo_old + z_hi_old)
    zc_new = z_lo_new + 0.5 * (z_hi_old - z_lo_old)
    for i in members:
        pid, o, t = poses[i]
        r_new = rot @ ROTATIONS[o]
        t_rel = np.asarray(t, float) - np.array([0.0, 0.0, zc_old])
        t_new = rot.astype(float) @ t_rel + np.array([0.0, 0.0, zc_new])
        out[i] = (pid, rot_index(r_new), t_new)
    return out


def slab_candidates(poses, z_intervals, max_exhaustive: int = 5, rng=None):
    """Yield transformed pose lists: every slab order (or a random sample) x rotation/flip per slab."""
    slabs = find_slabs(z_intervals)
    spans = [(min(z_intervals[i][0] for i in s), max(z_intervals[i][1] for i in s)) for s in slabs]
    floor = spans[0][0]
    gaps = [spans[k + 1][0] - spans[k][1] for k in range(len(spans) - 1)]
    k = len(slabs)
    orders = list(permutations(range(k))) if k <= max_exhaustive else \
        [tuple(rng.permutation(k)) for _ in range(200)] + [tuple(range(k))]
    variants = [RZ[a] @ (RX180 if f else np.eye(3, dtype=int)) for a in range(4) for f in (0, 1)]
    rng = rng or np.random.default_rng(0)
    for order in orders:
        for _ in range(1 if k > 3 else 4):
            choice = [variants[rng.integers(len(variants))] for _ in range(k)]
            new = list(poses)
            z = floor
            for pos, s_idx in enumerate(order):
                lo, hi = spans[s_idx]
                new = transform_slab(new, slabs[s_idx], choice[pos], lo, hi, z)
                z = z + (hi - lo) + (gaps[pos] if pos < len(gaps) else 0.0)
            yield new
