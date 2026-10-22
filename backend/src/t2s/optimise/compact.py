"""Certified drop compaction (protocol §D.4 step 4, §F.7 "exact compaction"): recover box-proxy waste.

The box decoder packs certified compound boxes, which over-cover curved parts (a sphere fills 52 % of its box).
Compaction moves each part along a direction (−Z by default) as far as its certified convex cover allows.

Soundness: for a convex piece P translated by s·u, s ∈ [0, T], the swept set is conv(P ∪ (P + T·u)) — itself
convex. If every swept piece of the moving part keeps the required gap from every piece of every other part
(a separating plane checked over all vertices), no intermediate position collides, so nothing can tunnel through a
thin wall. Feasibility is monotone in T, so bisection finds the largest certified drop. Pieces contain their parts
with the δ inflation of the cover certificate, so the required piece gap is c + 2δ + the 5 µm placement gap.
Every compacted layout still goes through the validator before it can be shown as VALIDATED.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

import numpy as np

from ..collision.geom import to_world
from ..collision.validate import StageSpec, separating_direction
from ..geometry.proxies import COVER_DELTA

PLACEMENT_GAP = 0.005


def _gap(a: np.ndarray, b: np.ndarray) -> float:
    """Certified lower bound on dist(conv a, conv b): best of the 6 axis planes and the min-norm direction."""
    best = -np.inf
    for k in range(3):
        best = max(best, float(b[:, k].min() - a[:, k].max()), float(a[:, k].min() - b[:, k].max()))
    n, _ = separating_direction(a, b, iters=60)
    if n is not None:
        best = max(best, float((b @ n).min() - (a @ n).max()))
    return best


def _aabb(p: np.ndarray) -> np.ndarray:
    return np.concatenate([p.min(axis=0), p.max(axis=0)])


def _aabb_gap(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.max(np.maximum(b[:3] - a[3:], a[:3] - b[3:])))


@dataclass
class CompactResult:
    poses: list
    moved_mm: dict
    passes: int
    seconds: float
    checks: int


class Compactor:
    def __init__(self, pieces: dict[str, list[np.ndarray]], hulls: dict[str, np.ndarray], spec: StageSpec):
        """pieces / hulls: canonical-frame convex piece vertex sets and hull vertices per part id."""
        self.pieces = pieces
        self.hulls = hulls
        self.spec = spec
        self.req_pp = spec.c_pp + 2 * COVER_DELTA + PLACEMENT_GAP
        self.req_st = spec.c_static + COVER_DELTA + PLACEMENT_GAP
        self.statics = [(s.name, s.corners) for s in spec.statics]
        self.checks = 0

    def _feasible(self, moving: list[np.ndarray], u: np.ndarray, T: float, others, statics, pid: str) -> bool:
        swept = [np.vstack([p, p + T * u]) for p in moving]
        boxes = [_aabb(s) for s in swept]
        for s, sb in zip(swept, boxes):
            for ob, op in others:
                if _aabb_gap(sb, ob) >= self.req_pp:
                    continue
                self.checks += 1
                if _gap(s, op) < self.req_pp:
                    return False
            for name, sbox, corners in statics:
                if (pid, name) in self.spec.exempt or _aabb_gap(sb, sbox) >= self.req_st:
                    continue
                self.checks += 1
                if _gap(s, corners) < self.req_st:
                    return False
        return True

    def _limit(self, hull_w: np.ndarray, u: np.ndarray) -> float:
        """Largest move along u that keeps every hull vertex inside the containment bounds (2.5 µm kept)."""
        lim = np.inf
        keep = PLACEMENT_GAP / 2
        for k in range(3):
            if u[k] < 0:
                lim = min(lim, (hull_w[:, k].min() - self.spec.lo[k] - keep) / -u[k])
            elif u[k] > 0:
                lim = min(lim, (self.spec.hi[k] - hull_w[:, k].max() - keep) / u[k])
        return max(0.0, float(lim))

    def compact(self, poses, directions=((0.0, 0.0, -1.0),), passes: int = 3, tol: float = 0.001,
                fixed: set[str] = frozenset(), time_budget_s: float = 30.0) -> CompactResult:
        t0 = time.perf_counter()
        poses = [(pid, int(o), np.asarray(t, float).copy()) for pid, o, t in poses]
        moved = {pid: 0.0 for pid, _, _ in poses}
        statics = [(n, _aabb(c), c) for n, c in self.statics]
        done_passes = 0
        for _ in range(passes):
            done_passes += 1
            any_move = False
            for u in directions:
                u = np.asarray(u, float)
                # parts nearest the target wall move first
                order = sorted(range(len(poses)), key=lambda i: float(
                    (to_world(self.hulls[poses[i][0]], poses[i][1], poses[i][2]) @ u).max() * -1.0))
                for i in order:
                    pid, o, t = poses[i]
                    if pid in fixed:
                        continue
                    if time.perf_counter() - t0 > time_budget_s:
                        break
                    moving = [to_world(p, o, t) for p in self.pieces[pid]]
                    hull_w = to_world(self.hulls[pid], o, t)
                    hi = self._limit(hull_w, u)
                    if hi < tol:
                        continue
                    others = []
                    for j, (qid, qo, qt) in enumerate(poses):
                        if j == i:
                            continue
                        for p in self.pieces[qid]:
                            w = to_world(p, qo, qt)
                            others.append((_aabb(w), w))
                    if self._feasible(moving, u, hi, others, statics, pid):
                        best = hi
                    else:
                        lo_, hi_ = 0.0, hi
                        while hi_ - lo_ > tol / 2:
                            mid = 0.5 * (lo_ + hi_)
                            if self._feasible(moving, u, mid, others, statics, pid):
                                lo_ = mid
                            else:
                                hi_ = mid
                        best = lo_
                    best = np.floor(best * 1000.0) / 1000.0          # integer-µm poses, rounded toward safety
                    if best >= tol:
                        poses[i] = (pid, o, np.round((t + best * u) * 1000.0) / 1000.0)
                        moved[pid] += best
                        any_move = True
            if not any_move:
                break
        return CompactResult(poses, moved, done_passes, time.perf_counter() - t0, self.checks)


def compactor_from_records(records: dict, spec: StageSpec) -> Compactor:
    pieces, hulls = {}, {}
    for pid, r in records.items():
        hull = r.v[r.hull.vertex_ids] if r.hull is not None else r.v
        hulls[pid] = hull
        pieces[pid] = [p.vertices for p in r.cover.pieces] if r.cover.certified and r.cover.pieces else [hull]
    return Compactor(pieces, hulls, spec)
