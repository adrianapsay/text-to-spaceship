"""Extreme-point best-fit-length decoder over certified compound boxes (protocol §D.2, A1/A2).

Geometry-only and weight-independent: a chromosome (order, orientation, placement rule) decodes to the same
layout whatever the slider weights or masses are, so slider and mass edits only re-score cached layouts.
Every emitted layout is box-feasible: proxy boxes, inflated by half the required gap on every side, are pairwise
disjoint and inside the container. Because certified boxes contain their parts, the layout is exact-feasible.
Stage 1 places parts 5 µm apart (contact policy); Stage 2 uses the clearance arithmetic of U4.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..core.rotations import ROTATIONS_F

PLACEMENT_GAP_STAGE1 = 0.005     # mm (5 µm placement gap, contact policy)

try:
    from numba import njit
except Exception:  # noqa: BLE001
    njit = None


def _place_kernel_py(rel, obs, cands, lo, hi, top, rule):
    m, n_obs, n_c = rel.shape[0], obs.shape[0], cands.shape[0]
    alo = np.empty(3)
    ahi = np.empty(3)
    for a in range(3):
        alo[a] = rel[:, a].min()
        ahi[a] = rel[:, 3 + a].max()
    best_k, best_merit = -1, np.inf
    best_t = np.zeros(3)
    t = np.zeros(3)
    for k in range(n_c):
        for a in range(3):
            t[a] = min(max(cands[k, a], lo[a] - alo[a]), hi[a] - ahi[a])
        for _rnd in range(3):
            for ax in (2, 1, 0):
                b = 1 if ax == 0 else 0
                c = 2 if ax != 2 else 1
                floor = lo[ax] - alo[ax]
                for i in range(m):
                    slo_ax = rel[i, ax] + t[ax]
                    slo_b, shi_b = rel[i, b] + t[b], rel[i, 3 + b] + t[b]
                    slo_c, shi_c = rel[i, c] + t[c], rel[i, 3 + c] + t[c]
                    for j in range(n_obs):
                        if slo_b < obs[j, 3 + b] and shi_b > obs[j, b] and slo_c < obs[j, 3 + c] and shi_c > obs[j, c]:
                            if obs[j, 3 + ax] <= slo_ax + 1e-9:
                                v = obs[j, 3 + ax] - rel[i, ax]
                                if v > floor:
                                    floor = v
                if floor < t[ax]:
                    t[ax] = floor
        ok = True
        for a in range(3):
            if t[a] + alo[a] < lo[a] - 1e-9 or t[a] + ahi[a] > hi[a] + 1e-9:
                ok = False
        if ok:
            for i in range(m):
                if not ok:
                    break
                for j in range(n_obs):
                    if (rel[i, 0] + t[0] < obs[j, 3] - 1e-9 and rel[i, 3] + t[0] > obs[j, 0] + 1e-9 and
                            rel[i, 1] + t[1] < obs[j, 4] - 1e-9 and rel[i, 4] + t[1] > obs[j, 1] + 1e-9 and
                            rel[i, 2] + t[2] < obs[j, 5] - 1e-9 and rel[i, 5] + t[2] > obs[j, 2] + 1e-9):
                        ok = False
                        break
        if not ok:
            continue
        top_new = max(top, t[2] + ahi[2])
        cx = t[0] + 0.5 * (alo[0] + ahi[0])
        cy = t[1] + 0.5 * (alo[1] + ahi[1])
        wall = (t[0] + alo[0] - lo[0]) + (t[1] + alo[1] - lo[1])
        axis_d = np.sqrt(cx * cx + cy * cy)
        merit = top_new * 1e3 + (t[2] + alo[2]) + 1e-3 * ((1 - rule) * wall + rule * axis_d)
        if merit < best_merit:
            best_merit = merit
            best_k = k
            for a in range(3):
                best_t[a] = t[a]
    return best_k, best_t, best_merit


_place_kernel = njit(cache=True, nogil=True, fastmath=False)(_place_kernel_py) if njit else _place_kernel_py


@dataclass
class ProxyPart:
    id: str
    boxes: np.ndarray                       # (m, 6) canonical-frame compound boxes
    allowed: list[int]
    rot_boxes: dict[int, np.ndarray] = field(default_factory=dict)

    def oriented(self, o: int) -> np.ndarray:
        if o not in self.rot_boxes:
            r = ROTATIONS_F[o]
            lo = self.boxes[:, :3] @ r.T
            hi = self.boxes[:, 3:] @ r.T
            self.rot_boxes[o] = np.concatenate([np.minimum(lo, hi), np.maximum(lo, hi)], axis=1)
        return self.rot_boxes[o]


@dataclass
class DecodeResult:
    poses: list[tuple[str, int, np.ndarray]]
    placed_boxes: np.ndarray
    unplaced: list[str]
    length_top: float


class BoxDecoder:
    def __init__(self, parts: list[ProxyPart], lo: np.ndarray, hi: np.ndarray, gap_pp: float,
                 wall_gap: float = 0.0, obstacles: np.ndarray | None = None, obstacle_gap: float = 0.0,
                 fixed: list[tuple[str, int, np.ndarray]] | None = None):
        self.parts = {p.id: p for p in parts}
        self.order_ids = [p.id for p in parts]
        self.half = gap_pp / 2.0
        self.lo = np.asarray(lo, float) + wall_gap
        self.hi = np.asarray(hi, float) - wall_gap
        # obstacles are inflated so that part boxes inflated by `half` keep `obstacle_gap` from them
        obs = np.zeros((0, 6)) if obstacles is None else np.asarray(obstacles, float)
        grow = max(obstacle_gap - self.half, 0.0)
        self.obstacles = np.concatenate([obs[:, :3] - grow, obs[:, 3:] + grow], axis=1) if len(obs) else obs
        self.fixed = fixed or []

    # ------------------------------------------------------------------------------------- decode
    def decode(self, order: list[int], orient_keys: np.ndarray, rule_keys: np.ndarray) -> DecodeResult:
        placed = [self.obstacles] if len(self.obstacles) else []
        poses, unplaced = [], []
        eps = [self.lo.copy()]
        top = self.lo[2]
        for pid, o, t in self.fixed:
            b = self._world(self.parts[pid], o, t)
            placed.append(b)
            poses.append((pid, o, np.asarray(t, float)))
            top = max(top, b[:, 5].max())
            eps.extend(self._eps_from(b))
        fixed_ids = {f[0] for f in self.fixed}
        for idx in order:
            pid = self.order_ids[idx]
            if pid in fixed_ids:
                continue
            part = self.parts[pid]
            allowed = part.allowed
            o = allowed[min(int(orient_keys[idx] * len(allowed)), len(allowed) - 1)]
            res = self._place(part, o, placed, eps, top, float(rule_keys[idx]))
            if res is None:
                unplaced.append(pid)
                continue
            t, boxes = res
            placed.append(boxes)
            poses.append((pid, o, t))
            top = max(top, boxes[:, 5].max())
            eps.extend(self._eps_from(boxes))
        pb = np.vstack(placed) if placed else np.zeros((0, 6))
        return DecodeResult(poses, pb, unplaced, float(top - self.lo[2]))

    def best_fit_all_orientations(self, order: list[int], rule: float = 0.0) -> DecodeResult:
        """Constructive heuristic: every part tries every allowed orientation (initialiser / Stage 2 baseline)."""
        placed = [self.obstacles] if len(self.obstacles) else []
        poses, unplaced, eps, top = [], [], [self.lo.copy()], self.lo[2]
        for idx in order:
            part = self.parts[self.order_ids[idx]]
            best = None
            for o in part.allowed:
                res = self._place(part, o, placed, eps, top, rule, return_merit=True)
                if res is not None and (best is None or res[2] < best[3]):
                    best = (o, res[0], res[1], res[2])
            if best is None:
                unplaced.append(part.id)
                continue
            o, t, boxes, _ = best
            placed.append(boxes)
            poses.append((part.id, o, t))
            top = max(top, boxes[:, 5].max())
            eps.extend(self._eps_from(boxes))
        pb = np.vstack(placed) if placed else np.zeros((0, 6))
        return DecodeResult(poses, pb, unplaced, float(top - self.lo[2]))

    # ------------------------------------------------------------------------------------- internals
    def _world(self, part: ProxyPart, o: int, t) -> np.ndarray:
        b = part.oriented(o)
        h = self.half
        return np.concatenate([b[:, :3] + t - h, b[:, 3:] + t + h], axis=1)

    @staticmethod
    def _eps_from(b: np.ndarray):
        return [np.array([x[3], x[1], x[2]]) for x in b] + [np.array([x[0], x[4], x[2]]) for x in b] + \
            [np.array([x[0], x[1], x[5]]) for x in b]

    def _place(self, part: ProxyPart, o: int, placed: list[np.ndarray], eps, top, rule, return_merit=False):
        rel = part.oriented(o)
        h = self.half
        rel = np.concatenate([rel[:, :3] - h, rel[:, 3:] + h], axis=1)        # inflated, relative to translation
        alo, ahi = rel[:, :3].min(axis=0), rel[:, 3:].max(axis=0)
        size = ahi - alo
        if np.any(size > self.hi - self.lo + 1e-9):
            return None
        obs = np.vstack(placed) if placed else np.zeros((0, 6))
        pts = np.unique(np.round(np.array(eps), 9), axis=0)
        if len(obs) and len(pts) > 1:
            # prune extreme points strictly inside a placed box (nothing can start there)
            inside = np.any(np.all((pts[:, None, :] > obs[None, :, :3] + 1e-9) & (pts[:, None, :] < obs[None, :, 3:] - 1e-9),
                                   axis=2), axis=1)
            pts = pts[~inside]
        cands = pts - alo                                           # put the part's AABB min corner at the EP
        centred = cands.copy()
        centred[:, 0] = -(alo[0] + ahi[0]) / 2
        centred[:, 1] = -(alo[1] + ahi[1]) / 2
        cands = np.ascontiguousarray(np.vstack([cands, centred]))
        k, tk, merit = _place_kernel(np.ascontiguousarray(rel), np.ascontiguousarray(obs), cands, self.lo, self.hi,
                                     float(top), float(rule))
        if k < 0:
            return None
        tk = np.array(tk)
        boxes = rel + np.concatenate([tk, tk])
        if return_merit:
            return tk, boxes, float(merit)
        return tk, boxes

    def _drop(self, t: np.ndarray, rel: np.ndarray, obs: np.ndarray, ax: int) -> np.ndarray:
        """Move each candidate toward -ax until a part box rests on an obstacle box or the container wall."""
        b, c = [a for a in range(3) if a != ax]
        floor = np.full(len(t), self.lo[ax] - rel[:, ax].min())
        if len(obs):
            # (K, m, O) overlap in the other two axes
            slo = rel[None, :, :3] + t[:, None, :]
            shi = rel[None, :, 3:] + t[:, None, :]
            ov = ((slo[:, :, None, b] < obs[None, None, :, 3 + b]) & (shi[:, :, None, b] > obs[None, None, :, b]) &
                  (slo[:, :, None, c] < obs[None, None, :, 3 + c]) & (shi[:, :, None, c] > obs[None, None, :, c]))
            below = obs[None, None, :, 3 + ax] <= slo[:, :, None, ax] + 1e-9
            cand = np.where(ov & below, obs[None, None, :, 3 + ax] - rel[None, :, None, ax], -np.inf)
            floor = np.maximum(floor, cand.max(axis=(1, 2)))
        out = t.copy()
        out[:, ax] = np.minimum(t[:, ax], np.maximum(floor, self.lo[ax] - rel[:, ax].min()))
        return out

    def _feasible(self, t: np.ndarray, rel: np.ndarray, obs: np.ndarray) -> np.ndarray:
        slo = rel[None, :, :3] + t[:, None, :]
        shi = rel[None, :, 3:] + t[:, None, :]
        inside = np.all(slo >= self.lo - 1e-9, axis=(1, 2)) & np.all(shi <= self.hi + 1e-9, axis=(1, 2))
        if not len(obs):
            return inside
        ov = np.all((slo[:, :, None, :] < obs[None, None, :, 3:] - 1e-9) &
                    (shi[:, :, None, :] > obs[None, None, :, :3] + 1e-9), axis=3)
        return inside & ~ov.any(axis=(1, 2))
