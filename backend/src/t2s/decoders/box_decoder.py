"""Extreme-point best-fit-length decoder over certified compound boxes (protocol §D.2, A1/A2).

Geometry-only and weight-independent: a chromosome (order, orientation, placement rule) decodes to the same
layout whatever the slider weights or masses are, so slider and mass edits only re-score cached layouts.
Every emitted layout is box-feasible: proxy boxes, inflated by half the required gap on every side, are pairwise
disjoint and inside the container. Because certified boxes contain their parts, the layout is exact-feasible.
Stage 1 places parts 5 µm apart (contact policy); Stage 2 uses the clearance arithmetic of U4.

The whole decode runs in one compiled kernel over preallocated arrays: placed boxes are grouped per part (group
AABBs give a broad phase), extreme points are deduplicated and pruned as boxes are added.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..core.rotations import ROTATIONS_F

PLACEMENT_GAP_STAGE1 = 0.005     # mm (5 µm placement gap, contact policy)
TOL = 1e-9

try:
    from numba import njit
except Exception:  # noqa: BLE001
    njit = None


def _jit(fn):
    return njit(cache=True, nogil=True, fastmath=False)(fn) if njit else fn


@_jit
def _try_candidate(c0, c1, c2, tb, off, m, alo, ahi, amaxlo, obs, gs, ge, gb, n_grp, lo, hi, top, rule, t):
    """Clamp a candidate translation into the container, drop it along -z, -y, -x (up to 3 rounds) onto the
    container walls or placed boxes, check feasibility and return its merit (inf when infeasible)."""
    t[0] = min(max(c0, lo[0] - alo[0]), hi[0] - ahi[0])
    t[1] = min(max(c1, lo[1] - alo[1]), hi[1] - ahi[1])
    t[2] = min(max(c2, lo[2] - alo[2]), hi[2] - ahi[2])
    for _rnd in range(3):
        moved = False
        for ax in (2, 1, 0):
            b = 1 if ax == 0 else 0
            c = 2 if ax != 2 else 1
            floor = lo[ax] - alo[ax]
            if t[ax] <= floor:
                continue
            for g in range(n_grp):
                if not (alo[b] + t[b] < gb[g, 3 + b] and ahi[b] + t[b] > gb[g, b] and
                        alo[c] + t[c] < gb[g, 3 + c] and ahi[c] + t[c] > gb[g, c]):
                    continue
                if gb[g, 3 + ax] - alo[ax] <= floor or gb[g, ax] > amaxlo[ax] + t[ax] + TOL:
                    continue
                for i in range(m):
                    slo_ax = tb[off + i, ax] + t[ax]
                    slo_b, shi_b = tb[off + i, b] + t[b], tb[off + i, 3 + b] + t[b]
                    slo_c, shi_c = tb[off + i, c] + t[c], tb[off + i, 3 + c] + t[c]
                    if not (slo_b < gb[g, 3 + b] and shi_b > gb[g, b] and slo_c < gb[g, 3 + c] and shi_c > gb[g, c]):
                        continue
                    for j in range(gs[g], ge[g]):
                        if slo_b < obs[j, 3 + b] and shi_b > obs[j, b] and slo_c < obs[j, 3 + c] and shi_c > obs[j, c]:
                            if obs[j, 3 + ax] <= slo_ax + TOL:
                                v = obs[j, 3 + ax] - tb[off + i, ax]
                                if v > floor:
                                    floor = v
            if floor < t[ax]:
                t[ax] = floor
                moved = True
        if not moved:
            break
    for a in range(3):
        if t[a] + alo[a] < lo[a] - TOL or t[a] + ahi[a] > hi[a] + TOL:
            return np.inf
    for g in range(n_grp):
        if not (alo[0] + t[0] < gb[g, 3] - TOL and ahi[0] + t[0] > gb[g, 0] + TOL and
                alo[1] + t[1] < gb[g, 4] - TOL and ahi[1] + t[1] > gb[g, 1] + TOL and
                alo[2] + t[2] < gb[g, 5] - TOL and ahi[2] + t[2] > gb[g, 2] + TOL):
            continue
        for i in range(m):
            for j in range(gs[g], ge[g]):
                if (tb[off + i, 0] + t[0] < obs[j, 3] - TOL and tb[off + i, 3] + t[0] > obs[j, 0] + TOL and
                        tb[off + i, 1] + t[1] < obs[j, 4] - TOL and tb[off + i, 4] + t[1] > obs[j, 1] + TOL and
                        tb[off + i, 2] + t[2] < obs[j, 5] - TOL and tb[off + i, 5] + t[2] > obs[j, 2] + TOL):
                    return np.inf
    top_new = max(top, t[2] + ahi[2])
    cx = t[0] + 0.5 * (alo[0] + ahi[0])
    cy = t[1] + 0.5 * (alo[1] + ahi[1])
    wall = (t[0] + alo[0] - lo[0]) + (t[1] + alo[1] - lo[1])
    axis_d = np.sqrt(cx * cx + cy * cy)
    return top_new * 1e3 + (t[2] + alo[2]) + 1e-3 * ((1 - rule) * wall + rule * axis_d)


@_jit
def _place_one(tb, off, m, aabb, obs, gs, ge, gb, n_grp, eps, n_eps, zs, lo, hi, top, rule, t, best_t):
    """Best candidate over all extreme points (part min corner at the EP) and the centred column at each EP z."""
    alo = aabb[:3]
    ahi = aabb[3:]
    for a in range(3):
        if ahi[a] - alo[a] > hi[a] - lo[a] + TOL:
            return np.inf
    amaxlo = np.empty(3)
    for a in range(3):
        v = -np.inf
        for i in range(m):
            if tb[off + i, a] > v:
                v = tb[off + i, a]
        amaxlo[a] = v
    best = np.inf
    for e in range(n_eps):
        mr = _try_candidate(eps[e, 0] - alo[0], eps[e, 1] - alo[1], eps[e, 2] - alo[2], tb, off, m, alo, ahi, amaxlo,
                            obs, gs, ge, gb, n_grp, lo, hi, top, rule, t)
        if mr < best:
            best = mr
            best_t[0], best_t[1], best_t[2] = t[0], t[1], t[2]
    for e in range(n_eps):
        zs[e] = eps[e, 2]
    zsort = np.sort(zs[:n_eps])
    cx, cy = -0.5 * (alo[0] + ahi[0]), -0.5 * (alo[1] + ahi[1])
    for e in range(n_eps):
        if e > 0 and zsort[e] - zsort[e - 1] <= TOL:
            continue
        mr = _try_candidate(cx, cy, zsort[e] - alo[2], tb, off, m, alo, ahi, amaxlo, obs, gs, ge, gb, n_grp, lo, hi,
                            top, rule, t)
        if mr < best:
            best = mr
            best_t[0], best_t[1], best_t[2] = t[0], t[1], t[2]
    return best


@_jit
def _point_blocked(px, py, pz, obs, gs, ge, gb, n_grp):
    for g in range(n_grp):
        if not (gb[g, 0] + TOL < px < gb[g, 3] - TOL and gb[g, 1] + TOL < py < gb[g, 4] - TOL and
                gb[g, 2] + TOL < pz < gb[g, 5] - TOL):
            continue
        for j in range(gs[g], ge[g]):
            if (obs[j, 0] + TOL < px < obs[j, 3] - TOL and obs[j, 1] + TOL < py < obs[j, 4] - TOL and
                    obs[j, 2] + TOL < pz < obs[j, 5] - TOL):
                return True
    return False


@_jit
def _decode_kernel(seq, okeys, rules, all_orient, allowed, n_allowed, tb, toff, tcnt, taabb, lo, hi,
                   obs, gs, ge, gb, n_obs, n_grp, eps, n_eps, top, out_t, out_o):
    zs = np.empty(eps.shape[0])
    t = np.zeros(3)
    cand_t = np.zeros(3)
    best_t = np.zeros(3)
    for s in range(seq.shape[0]):
        p = seq[s]
        if p < 0:
            continue
        na = n_allowed[p]
        out_o[p] = -1
        if na == 0:
            continue
        if all_orient:
            j0, j1 = 0, na
        else:
            j0 = min(int(okeys[p] * na), na - 1)
            j1 = j0 + 1
        best_merit, best_o = np.inf, -1
        for jj in range(j0, j1):
            o = allowed[p, jj]
            mr = _place_one(tb, toff[p, o], tcnt[p, o], taabb[p, o], obs, gs, ge, gb, n_grp, eps, n_eps, zs, lo, hi,
                            top, rules[p], t, cand_t)
            if mr < best_merit:
                best_merit, best_o = mr, o
                best_t[0], best_t[1], best_t[2] = cand_t[0], cand_t[1], cand_t[2]
        if best_o < 0:
            continue
        out_o[p] = best_o
        out_t[p, 0], out_t[p, 1], out_t[p, 2] = best_t[0], best_t[1], best_t[2]
        off, m = toff[p, best_o], tcnt[p, best_o]
        g = n_grp
        gs[g] = n_obs
        for i in range(m):
            for a in range(3):
                obs[n_obs, a] = tb[off + i, a] + best_t[a]
                obs[n_obs, 3 + a] = tb[off + i, 3 + a] + best_t[a]
            n_obs += 1
        ge[g] = n_obs
        for a in range(3):
            gb[g, a] = taabb[p, best_o, a] + best_t[a]
            gb[g, 3 + a] = taabb[p, best_o, 3 + a] + best_t[a]
        n_grp += 1
        if gb[g, 5] > top:
            top = gb[g, 5]
        k = 0                                   # drop extreme points that are now strictly inside a box
        for e in range(n_eps):
            if not _point_blocked(eps[e, 0], eps[e, 1], eps[e, 2], obs, gs[g:g + 1], ge[g:g + 1], gb[g:g + 1], 1):
                eps[k, 0], eps[k, 1], eps[k, 2] = eps[e, 0], eps[e, 1], eps[e, 2]
                k += 1
        n_eps = k
        for j in range(gs[g], ge[g]):           # three new extreme points per box
            for which in range(3):
                px = obs[j, 3] if which == 0 else obs[j, 0]
                py = obs[j, 4] if which == 1 else obs[j, 1]
                pz = obs[j, 5] if which == 2 else obs[j, 2]
                dup = False
                for e in range(n_eps):
                    if abs(eps[e, 0] - px) <= TOL and abs(eps[e, 1] - py) <= TOL and abs(eps[e, 2] - pz) <= TOL:
                        dup = True
                        break
                if dup or _point_blocked(px, py, pz, obs, gs, ge, gb, n_grp):
                    continue
                eps[n_eps, 0], eps[n_eps, 1], eps[n_eps, 2] = px, py, pz
                n_eps += 1
    return top, n_obs


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
        self.index = {pid: i for i, pid in enumerate(self.order_ids)}
        self.half = gap_pp / 2.0
        self.lo = np.asarray(lo, float) + wall_gap
        self.hi = np.asarray(hi, float) - wall_gap
        # obstacles are inflated so that part boxes inflated by `half` keep `obstacle_gap` from them
        obs = np.zeros((0, 6)) if obstacles is None else np.asarray(obstacles, float)
        grow = max(obstacle_gap - self.half, 0.0)
        self.obstacles = np.concatenate([obs[:, :3] - grow, obs[:, 3:] + grow], axis=1) if len(obs) else obs
        self.fixed = fixed or []
        self._build_tables(parts)
        self._build_initial_state()

    # ------------------------------------------------------------------------------------- set-up
    def _build_tables(self, parts: list[ProxyPart]) -> None:
        n = len(parts)
        h = self.half
        self.allowed = np.full((n, 24), -1, np.int64)
        self.n_allowed = np.zeros(n, np.int64)
        self.toff = np.zeros((n, 24), np.int64)
        self.tcnt = np.zeros((n, 24), np.int64)
        self.taabb = np.zeros((n, 24, 6))
        rows = []
        k = 0
        for p_i, part in enumerate(parts):
            self.n_allowed[p_i] = len(part.allowed)
            self.allowed[p_i, :len(part.allowed)] = part.allowed
            for o in part.allowed:
                b = part.oriented(o)
                rel = np.concatenate([b[:, :3] - h, b[:, 3:] + h], axis=1)        # inflated, relative to translation
                rows.append(rel)
                self.toff[p_i, o], self.tcnt[p_i, o] = k, len(rel)
                self.taabb[p_i, o] = np.concatenate([rel[:, :3].min(axis=0), rel[:, 3:].max(axis=0)])
                k += len(rel)
        self.tb = np.ascontiguousarray(np.vstack(rows)) if rows else np.zeros((0, 6))
        self.max_boxes = int(sum(len(p.boxes) for p in parts))

    def _build_initial_state(self) -> None:
        groups = [b[None, :] for b in self.obstacles]
        top = self.lo[2]
        fixed_poses = []
        for pid, o, t in self.fixed:
            b = self._world(self.parts[pid], o, t)
            groups.append(b)
            fixed_poses.append((pid, o, np.asarray(t, float)))
            top = max(top, b[:, 5].max())
        obs = np.vstack(groups) if groups else np.zeros((0, 6))
        ends = np.cumsum([len(g) for g in groups]).astype(np.int64)
        gb = np.array([np.concatenate([g[:, :3].min(axis=0), g[:, 3:].max(axis=0)]) for g in groups]).reshape(-1, 6)
        eps = [self.lo.copy()]
        for g in groups[len(self.obstacles):]:
            for x in g:
                eps += [np.array([x[3], x[1], x[2]]), np.array([x[0], x[4], x[2]]), np.array([x[0], x[1], x[5]])]
        pts = np.unique(np.round(np.array(eps), 9), axis=0)
        if len(obs):
            inside = np.any(np.all((pts[:, None, :] > obs[None, :, :3] + TOL) & (pts[:, None, :] < obs[None, :, 3:] - TOL),
                                   axis=2), axis=1)
            pts = pts[~inside]
        self._obs0, self._gb0, self._eps0, self._top0 = obs, gb, pts, float(top)
        self._ge0 = ends
        self._gs0 = np.concatenate([[0], ends[:-1]]).astype(np.int64) if len(ends) else ends
        self._fixed_poses = fixed_poses
        self._fixed_idx = {self.index[f[0]] for f in self.fixed if f[0] in self.index}

    # ------------------------------------------------------------------------------------- decode
    def decode(self, order: list[int], orient_keys: np.ndarray, rule_keys: np.ndarray) -> DecodeResult:
        return self._run(order, np.asarray(orient_keys, float), np.asarray(rule_keys, float), False)

    def best_fit_all_orientations(self, order: list[int], rule: float = 0.0) -> DecodeResult:
        """Constructive heuristic: every part tries every allowed orientation (initialiser / Stage 2 baseline)."""
        n = len(self.order_ids)
        return self._run(order, np.zeros(n), np.full(n, float(rule)), True)

    def _run(self, order, okeys, rules, all_orient: bool) -> DecodeResult:
        n = len(self.order_ids)
        seq = np.array([-1 if i in self._fixed_idx else int(i) for i in order], np.int64)
        n_obs0, n_grp0, n_eps0 = len(self._obs0), len(self._gb0), len(self._eps0)
        obs = np.empty((n_obs0 + self.max_boxes, 6))
        obs[:n_obs0] = self._obs0
        gs = np.empty(n_grp0 + n, np.int64)
        ge = np.empty(n_grp0 + n, np.int64)
        gb = np.empty((n_grp0 + n, 6))
        gs[:n_grp0], ge[:n_grp0], gb[:n_grp0] = self._gs0, self._ge0, self._gb0
        eps = np.empty((n_eps0 + 3 * self.max_boxes, 3))
        eps[:n_eps0] = self._eps0
        out_t = np.zeros((n, 3))
        out_o = np.full(n, -2, np.int64)
        top, n_obs = _decode_kernel(seq, np.ascontiguousarray(okeys), np.ascontiguousarray(rules), all_orient,
                                    self.allowed, self.n_allowed, self.tb, self.toff, self.tcnt, self.taabb,
                                    self.lo, self.hi, obs, gs, ge, gb, n_obs0, n_grp0, eps, n_eps0, self._top0,
                                    out_t, out_o)
        poses = list(self._fixed_poses)
        unplaced = []
        for i in seq:
            if i < 0:
                continue
            pid = self.order_ids[i]
            if out_o[i] >= 0:
                poses.append((pid, int(out_o[i]), out_t[i].copy()))
            else:
                unplaced.append(pid)
        return DecodeResult(poses, obs[:n_obs], unplaced, float(top - self.lo[2]))

    # ------------------------------------------------------------------------------------- internals
    def _world(self, part: ProxyPart, o: int, t) -> np.ndarray:
        b = part.oriented(o)
        h = self.half
        return np.concatenate([b[:, :3] + t - h, b[:, 3:] + t + h], axis=1)
