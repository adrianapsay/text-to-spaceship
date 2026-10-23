"""Extreme-point best-fit-length decoder over certified compound boxes (protocol §D.2, A1/A2).

Geometry-only and weight-independent: a chromosome (order, orientation, placement rule) decodes to the same
layout whatever the slider weights or masses are, so slider and mass edits only re-score cached layouts.
Every emitted layout is box-feasible: proxy boxes, inflated by half the required gap on every side, are pairwise
disjoint and inside the container. Because certified boxes contain their parts, the layout is exact-feasible.
Stage 1 places parts 5 µm apart (contact policy); Stage 2 uses the clearance arithmetic of U4.

The whole decode runs in one compiled kernel over preallocated arrays: placed boxes are grouped per part (group
AABBs give a broad phase), extreme points are deduplicated and pruned as boxes are added.

Bracket-aware placement (V2 Stage 2, `mount` spec): a part carries its 3 mm mounting-layer box, and every candidate
position is charged by whether a bracket could hold it there — the wall or end plate the layer faces, or a target
obstacle (corner rail, PC/104 stack deck) overlapping the layer's footprint, within reach, with a clear corridor
(1.2 mm from placed parts, keep-outs and other corridors). A position without a bracket costs more than any
mountable one; an end plate only (the COM shift may carry the part away from it) costs as much as 50 mm of length.
The chosen corridor is reserved for the rest of the decode, so later parts do not block the bracket. When the
keyed orientation cannot be mounted anywhere, every allowed orientation is tried. The exact bracket check (reserve
box, cheapest option, clearances) still runs after decoding; this only steers the placement.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..core.rotations import ROTATIONS_F

PLACEMENT_GAP_STAGE1 = 0.005     # mm (5 µm placement gap, contact policy)
TOL = 1e-9
PEN_END = 5e4                    # bracket to an end plate only: worth 50 mm of length (merit is 1e3 per mm)
PEN_END_SHIFTED = 1e7            # … when a COM shift follows: a last resort, still better than no bracket
PEN_NONE = 1e8                   # no bracket reachable: worse than any mountable position
MAX_MOUNT_CHECKS = 48            # bracket checks per orientation, most compact candidates first (bounds the cost)
GKIND_STATIC, GKIND_TARGET, GKIND_PART, GKIND_CORRIDOR = 0, 1, 2, 3

try:
    from numba import njit
except Exception:  # noqa: BLE001
    njit = None


def _jit(fn):
    return njit(cache=True, nogil=True, fastmath=False)(fn) if njit else fn


@_jit
def _try_candidate(c0, c1, c2, tb, off, m, alo, ahi, amaxlo, obs, gs, ge, gb, n_grp, lo, hi, top, rule, t, pin=-1):
    """Clamp a candidate translation into the container, drop it along -z, -y, -x (up to 3 rounds) onto the
    container walls or placed boxes, check feasibility and return its merit (inf when infeasible). pin: an axis
    along which the candidate is not dropped (kept against the wall it was put on)."""
    t[0] = min(max(c0, lo[0] - alo[0]), hi[0] - ahi[0])
    t[1] = min(max(c1, lo[1] - alo[1]), hi[1] - ahi[1])
    t[2] = min(max(c2, lo[2] - alo[2]), hi[2] - ahi[2])
    for _rnd in range(3):
        moved = False
        for ax in (2, 1, 0):
            if ax == pin:
                continue
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
def _corridor_blocked(box, skip_g, obs, gs, ge, gb, gkind, n_grp, cg_part, cg_other):
    """True if the corridor box comes within the bracket clearance of a placed part (boxes inflated by half the part
    gap: grow cg_part), a keep-out or another corridor (grow cg_other), the target group skip_g excepted."""
    for g in range(n_grp):
        if g == skip_g:
            continue
        cg = cg_part if gkind[g] == GKIND_PART else cg_other
        if not (box[0] - cg < gb[g, 3] - TOL and box[3] + cg > gb[g, 0] + TOL and
                box[1] - cg < gb[g, 4] - TOL and box[4] + cg > gb[g, 1] + TOL and
                box[2] - cg < gb[g, 5] - TOL and box[5] + cg > gb[g, 2] + TOL):
            continue
        for j in range(gs[g], ge[g]):
            if (box[0] - cg < obs[j, 3] - TOL and box[3] + cg > obs[j, 0] + TOL and
                    box[1] - cg < obs[j, 4] - TOL and box[4] + cg > obs[j, 1] + TOL and
                    box[2] - cg < obs[j, 5] - TOL and box[5] + cg > obs[j, 2] + TOL):
                return True
    return False


@_jit
def _mount_cost(t, prel, d, walls, mp, obs, gs, ge, gb, gkind, n_grp, cg_part, cg_other, corr):
    """Cost of the cheapest bracket for a part at translation t whose mounting layer (prel, relative to t) faces
    direction d (2·axis + 1 if negative), with the part's mp = (reach, narrowest flange on a rail or deck, end-plate
    cost, side walls only): 0 (+10 per mm of gap) for a wall, rail or deck, the end-plate cost for an end plate,
    PEN_NONE when nothing is reachable through a clear corridor. The corridor (the layer's footprint, clipped to a
    box target, from the part side to the target plane) is written to corr[:6]; corr[6] = 1 for a wall, rail or deck,
    2 for an end plate, 0 if none was found."""
    corr[6] = 0.0
    reach, min_w, pen_end, walls_only = mp[0], mp[1], mp[2], mp[3] > 0.5
    ax = d // 2
    if walls_only and ax == 2:              # edge-on board standoffs: side walls only
        return PEN_NONE
    neg = d % 2 == 1
    b = 1 if ax == 0 else 0
    c = 2 if ax != 2 else 1
    plo = np.empty(3)
    phi = np.empty(3)
    for a in range(3):
        plo[a] = prel[a] + t[a]
        phi[a] = prel[3 + a] + t[a]
    side = phi[ax] if neg else plo[ax]
    box = np.empty(6)
    best = PEN_NONE
    for k in range(-1, n_grp):              # -1: the wall / end plate the layer faces
        if k == -1:
            plane = walls[2 * ax] if neg else walls[2 * ax + 1]
            lb, hb, lc, hc = plo[b], phi[b], plo[c], phi[c]
            cost0 = pen_end if ax == 2 else 0.0
        else:
            if walls_only or gkind[k] != GKIND_TARGET:
                continue
            if not (gb[k, b] < phi[b] and gb[k, 3 + b] > plo[b] and gb[k, c] < phi[c] and gb[k, 3 + c] > plo[c]):
                continue
            plane = gb[k, 3 + ax] if neg else gb[k, ax]
            lb, hb = max(plo[b], gb[k, b]), min(phi[b], gb[k, 3 + b])
            lc, hc = max(plo[c], gb[k, c]), min(phi[c], gb[k, 3 + c])
            # the flange clipped to the target must stay at least min_w wide (as the exact bracket check needs)
            if hb - lb < min(min_w, phi[b] - plo[b]) - TOL or hc - lc < min(min_w, phi[c] - plo[c]) - TOL:
                continue
            cost0 = 0.0
        dist = side - plane if neg else plane - side
        if dist < -TOL or dist > reach + TOL:
            continue
        cost = cost0 + 10.0 * dist
        if cost >= best:
            continue
        if neg:
            box[ax], box[3 + ax] = plane, side
        else:
            box[ax], box[3 + ax] = side, plane
        box[b], box[3 + b], box[c], box[3 + c] = lb, hb, lc, hc
        if _corridor_blocked(box, k, obs, gs, ge, gb, gkind, n_grp, cg_part, cg_other):
            continue
        best = cost
        for a in range(6):
            corr[a] = box[a]
        corr[6] = 2.0 if (k == -1 and ax == 2) else 1.0
    return best


@_jit
def _consider(mr, best, t, best_t, mnt, cbuf, mbuf, nc):
    """Geometry only: keep candidate t if its merit beats best. Bracket-aware: queue every feasible candidate in
    (cbuf, mbuf) for the best-first bracket pass. Returns (best, nc)."""
    if mr == np.inf:
        return best, nc
    if mnt:
        cbuf[nc, 0], cbuf[nc, 1], cbuf[nc, 2] = t[0], t[1], t[2]
        mbuf[nc] = mr
        return best, nc + 1
    if mr < best:
        best_t[0], best_t[1], best_t[2] = t[0], t[1], t[2]
        return mr, nc
    return best, nc


@_jit
def _place_one(tb, off, m, aabb, obs, gs, ge, gb, n_grp, eps, n_eps, zs, lo, hi, top, rule, t, best_t, mixed,
               mnt, prel, d, walls, mp, gkind, cg_part, cg_other, corr, best_corr, cbuf, mbuf):
    """Best candidate over all extreme points (part min corner at the EP) and the centred column at each EP z.
    mixed: also try 'against the EP in one axis, centred in the other' (useful between corner rails).
    mnt: charge candidates by their bracket (_mount_cost), best-first by geometric merit — bracket costs are never
    negative, so the pass stops at the first candidate whose merit alone cannot win (the same winner as charging
    every candidate), and after MAX_MOUNT_CHECKS candidates. The winner's corridor is written to best_corr. Without
    a feasible candidate the result is inf; without a mountable one it carries PEN_NONE."""
    nc = 0
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
        best, nc = _consider(mr, best, t, best_t, mnt, cbuf, mbuf, nc)
    for e in range(n_eps):
        zs[e] = eps[e, 2]
    zsort = np.sort(zs[:n_eps])
    cx, cy = -0.5 * (alo[0] + ahi[0]), -0.5 * (alo[1] + ahi[1])
    if mixed:
        for e in range(n_eps):
            for which in range(2):
                c0 = eps[e, 0] - alo[0] if which == 0 else cx
                c1 = cy if which == 0 else eps[e, 1] - alo[1]
                mr = _try_candidate(c0, c1, eps[e, 2] - alo[2], tb, off, m, alo, ahi, amaxlo, obs, gs, ge, gb, n_grp,
                                    lo, hi, top, rule, t)
                best, nc = _consider(mr, best, t, best_t, mnt, cbuf, mbuf, nc)
    for e in range(n_eps):
        if e > 0 and zsort[e] - zsort[e - 1] <= TOL:
            continue
        mr = _try_candidate(cx, cy, zsort[e] - alo[2], tb, off, m, alo, ahi, amaxlo, obs, gs, ge, gb, n_grp, lo, hi,
                            top, rule, t)
        best, nc = _consider(mr, best, t, best_t, mnt, cbuf, mbuf, nc)
    n_reg = nc
    if mnt and d < 4:                        # layer facing a side wall: each EP also pinned against that wall
        ax_p = d // 2
        for e in range(n_eps):
            c0, c1 = eps[e, 0] - alo[0], eps[e, 1] - alo[1]
            w = (lo[ax_p] - alo[ax_p]) if d % 2 == 1 else (hi[ax_p] - ahi[ax_p])
            if ax_p == 0:
                c0 = w
            else:
                c1 = w
            mr = _try_candidate(c0, c1, eps[e, 2] - alo[2], tb, off, m, alo, ahi, amaxlo, obs, gs, ge, gb, n_grp, lo,
                                hi, top, rule, t, ax_p)
            best, nc = _consider(mr, best, t, best_t, mnt, cbuf, mbuf, nc)
    if mnt and nc > 0:                       # best-first bracket passes (stable: ties keep the evaluation order):
        for ps in range(2):                  # the wall-pinned candidates in full, then the others (capped)
            i0, i1 = (n_reg, nc) if ps == 0 else (0, n_reg)
            if i1 <= i0:
                continue
            order = np.argsort(mbuf[i0:i1], kind="mergesort")
            cap = i1 - i0 if ps == 0 else min(i1 - i0, MAX_MOUNT_CHECKS)
            for q in range(cap):
                i = i0 + order[q]
                if not mbuf[i] < best:
                    break
                for a in range(3):
                    t[a] = cbuf[i, a]
                mr = mbuf[i] + _mount_cost(t, prel, d, walls, mp, obs, gs, ge, gb, gkind, n_grp, cg_part, cg_other,
                                           corr)
                if mr < best:
                    best = mr
                    best_t[0], best_t[1], best_t[2] = t[0], t[1], t[2]
                    for a in range(7):
                        best_corr[a] = corr[a]
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
def _add_group(obs, gs, ge, gb, gkind, n_obs, n_grp, eps, n_eps, kind):
    """Register boxes obs[gs[n_grp]:n_obs] as group n_grp (AABB, kind) and update the extreme points: drop those now
    strictly inside the group, add three per new box. Returns (n_grp + 1, n_eps)."""
    g = n_grp
    ge[g] = n_obs
    for a in range(3):
        v_lo, v_hi = np.inf, -np.inf
        for j in range(gs[g], ge[g]):
            v_lo = min(v_lo, obs[j, a])
            v_hi = max(v_hi, obs[j, 3 + a])
        gb[g, a], gb[g, 3 + a] = v_lo, v_hi
    gkind[g] = kind
    n_grp += 1
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
    return n_grp, n_eps


@_jit
def _decode_kernel(seq, okeys, rules, all_orient, allowed, n_allowed, tb, toff, tcnt, taabb, lo_p, hi_p,
                   obs, gs, ge, gb, gkind, n_obs, n_grp, eps, n_eps, top, out_t, out_o, mixed,
                   pad_rel, pad_dir, walls, mp, cg_part, cg_other, is_corr):
    """lo_p / hi_p: (n, 3) per-part containment bounds (parts may keep different wall gaps).
    pad_rel / pad_dir: (n, 24, 6) mounting-layer box per orientation (relative to the translation) and its
    direction (2·axis + 1 if negative; -1: no bracket needed); mp: (n, 4) per-part mount parameters (_mount_cost).
    is_corr marks the obs rows that are corridors."""
    zs = np.empty(eps.shape[0])
    t = np.zeros(3)
    cand_t = np.zeros(3)
    best_t = np.zeros(3)
    corr = np.zeros(7)
    cand_corr = np.zeros(7)
    best_corr = np.zeros(7)
    cbuf = np.empty((5 * eps.shape[0], 3))   # candidates of one placement (EP, 2 mixed, centred column, wall-pinned)
    mbuf = np.empty(5 * eps.shape[0])
    tried = np.zeros(6, np.int64)
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
        best_corr[6] = 0.0
        for rnd in range(2):                # round 1: other orientations, if the keyed one cannot be mounted to a
            if rnd == 1:                    # wall, rail or deck (no bracket, or an end plate only)
                if all_orient or best_o < 0 or pad_dir[p, best_o] < 0 or abs(best_corr[6] - 1.0) < 0.5:
                    break
                tried[:] = 0
                tried[pad_dir[p, best_o]] = 2   # the keyed direction failed already
            for jj in range(0 if rnd == 1 else j0, na if rnd == 1 else j1):
                o = allowed[p, jj]
                if rnd == 1:
                    if jj == j0 or tried[pad_dir[p, o]] >= 2:     # at most two orientations per facing direction
                        continue
                    tried[pad_dir[p, o]] += 1
                mnt = pad_dir[p, o] >= 0
                cand_corr[6] = 0.0
                mr = _place_one(tb, toff[p, o], tcnt[p, o], taabb[p, o], obs, gs, ge, gb, n_grp, eps, n_eps, zs,
                                lo_p[p], hi_p[p], top, rules[p], t, cand_t, mixed, mnt, pad_rel[p, o],
                                max(pad_dir[p, o], 0), walls, mp[p], gkind, cg_part, cg_other, corr, cand_corr, cbuf,
                                mbuf)
                if mr < best_merit:
                    best_merit, best_o = mr, o
                    best_t[0], best_t[1], best_t[2] = cand_t[0], cand_t[1], cand_t[2]
                    for a in range(7):
                        best_corr[a] = cand_corr[a]
        if best_o < 0:
            continue
        out_o[p] = best_o
        out_t[p, 0], out_t[p, 1], out_t[p, 2] = best_t[0], best_t[1], best_t[2]
        off, m = toff[p, best_o], tcnt[p, best_o]
        gs[n_grp] = n_obs
        for i in range(m):
            for a in range(3):
                obs[n_obs, a] = tb[off + i, a] + best_t[a]
                obs[n_obs, 3 + a] = tb[off + i, 3 + a] + best_t[a]
            is_corr[n_obs] = False
            n_obs += 1
        n_grp, n_eps = _add_group(obs, gs, ge, gb, gkind, n_obs, n_grp, eps, n_eps, GKIND_PART)
        if gb[n_grp - 1, 5] > top:
            top = gb[n_grp - 1, 5]
        if pad_dir[p, best_o] >= 0 and best_corr[6] > 0.5:     # reserve the bracket's corridor
            gs[n_grp] = n_obs
            for a in range(3):
                obs[n_obs, a] = best_corr[a] - cg_part
                obs[n_obs, 3 + a] = best_corr[3 + a] + cg_part
            is_corr[n_obs] = True
            n_obs += 1
            n_grp, n_eps = _add_group(obs, gs, ge, gb, gkind, n_obs, n_grp, eps, n_eps, GKIND_CORRIDOR)
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


@dataclass
class MountSpec:
    """Bracket-aware placement (module docstring). pads: part_id -> (canonical layer box (6,), canonical axis,
    sign) for the parts that need a bracket; walls: (6,) inner-wall planes x−, x+, y−, y+, z− (end plate), z+;
    reach: longest bracket (mm); clearance: bracket clearance (mm); targets: per decoder obstacle, True if a bracket
    may land on it (corner rails, the stack deck); min_width: narrowest flange clipped to such a target (mm);
    end_plate_cost: merit added for a bracket to an end plate (PEN_END = 50 mm of length; PEN_END_SHIFTED when the
    layout will be shifted along z afterwards, which would carry the part away from the plate). part_reach: per-part
    reach overriding `reach`; walls_only: parts whose mount lands on a side wall only (edge-on boards: standoffs)."""
    pads: dict
    walls: np.ndarray
    reach: float
    clearance: float
    targets: list
    min_width: float = 6.0
    end_plate_cost: float = 5e4
    part_reach: dict = field(default_factory=dict)
    walls_only: frozenset = frozenset()


class BoxDecoder:
    def __init__(self, parts: list[ProxyPart], lo: np.ndarray, hi: np.ndarray, gap_pp: float,
                 wall_gap: float = 0.0, obstacles: np.ndarray | None = None, obstacle_gap: float = 0.0,
                 fixed: list[tuple[str, int, np.ndarray]] | None = None, part_wall_gap: dict | None = None,
                 mixed_candidates: bool = False, mount: MountSpec | None = None):
        """part_wall_gap: part_id -> wall gap overriding `wall_gap` for that part.
        mixed_candidates: also try positions against an extreme point in X and centred in Y (and vice versa).
        mount: bracket-aware placement (MountSpec); None = geometry only."""
        self.mixed = bool(mixed_candidates)
        self.mount = mount
        self.parts = {p.id: p for p in parts}
        self.order_ids = [p.id for p in parts]
        self.index = {pid: i for i, pid in enumerate(self.order_ids)}
        self.half = gap_pp / 2.0
        lo, hi = np.asarray(lo, float), np.asarray(hi, float)
        gaps = np.array([(part_wall_gap or {}).get(pid, wall_gap) for pid in self.order_ids], float)
        self.lo_p = np.ascontiguousarray(lo[None, :] + gaps[:, None]) if len(gaps) else np.zeros((0, 3))
        self.hi_p = np.ascontiguousarray(hi[None, :] - gaps[:, None]) if len(gaps) else np.zeros((0, 3))
        g0 = float(gaps.min()) if len(gaps) else wall_gap
        self.lo = lo + g0
        self.hi = hi - g0
        # obstacles are inflated so that part boxes inflated by `half` keep `obstacle_gap` from them
        obs = np.zeros((0, 6)) if obstacles is None else np.asarray(obstacles, float)
        grow = max(obstacle_gap - self.half, 0.0)
        self.obstacles = np.concatenate([obs[:, :3] - grow, obs[:, 3:] + grow], axis=1) if len(obs) else obs
        self.fixed = fixed or []
        self._grow_static = grow
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
        # bracket-aware placement: each part's mounting layer per orientation and the direction it faces
        self.pad_rel = np.zeros((n, 24, 6))
        self.pad_dir = np.full((n, 24), -1, np.int64)
        mt = self.mount
        for p_i, part in enumerate(parts):
            if mt is None or part.id not in mt.pads:
                continue
            pad, a, sgn = mt.pads[part.id]
            pad = np.asarray(pad, float)
            for o in part.allowed:
                r = ROTATIONS_F[o]
                lo_, hi_ = pad[:3] @ r.T, pad[3:] @ r.T
                self.pad_rel[p_i, o] = np.concatenate([np.minimum(lo_, hi_), np.maximum(lo_, hi_)])
                d = sgn * r[:, a]
                ax = int(np.argmax(np.abs(d)))
                self.pad_dir[p_i, o] = 2 * ax + (1 if d[ax] < 0 else 0)
        self.walls = np.asarray(mt.walls, float) if mt is not None else np.zeros(6)
        # per part: (reach, narrowest flange on a rail or deck, end-plate cost, 1 = side walls only)
        self.mp = np.zeros((n, 4))
        if mt is not None:
            for p_i, part in enumerate(parts):
                self.mp[p_i] = (float(mt.part_reach.get(part.id, mt.reach)), float(mt.min_width),
                                float(mt.end_plate_cost), 1.0 if part.id in mt.walls_only else 0.0)
        # corridors keep the bracket clearance: from part boxes (inflated by half the part gap) and from keep-outs
        # and other corridors (inflated by the static growth / stored grown by cg_part)
        clr = float(mt.clearance) if mt is not None else 0.0
        self.cg_part = max(clr - self.half, 0.0)
        self.cg_other = max(clr - max(self.cg_part, 0.0), 0.0)

    def _build_initial_state(self) -> None:
        st = self._initial_state(self.obstacles, self.fixed)
        self._obs0, self._gb0, self._eps0, self._top0, self._ge0, self._gs0, self._fixed_poses = st
        self._gk0 = self._group_kinds(self.mount.targets if self.mount is not None else [], len(self.obstacles))
        self._fixed_idx = {self.index[f[0]] for f in self.fixed if f[0] in self.index}

    def _group_kinds(self, targets, n_obstacles: int) -> np.ndarray:
        """Kinds of the initial groups: one per obstacle (target or plain keep-out), then the fixed parts."""
        k = [GKIND_TARGET if (i < len(targets) and targets[i]) else GKIND_STATIC for i in range(n_obstacles)]
        return np.array(k + [GKIND_PART] * len(self.fixed), np.int64)

    def _initial_state(self, obstacles: np.ndarray, fixed: list):
        groups = [b[None, :] for b in obstacles]
        top = self.lo[2]
        fixed_poses = []
        for pid, o, t in fixed:
            b = self._world(self.parts[pid], o, t)
            groups.append(b)
            fixed_poses.append((pid, o, np.asarray(t, float)))
            top = max(top, b[:, 5].max())
        obs = np.vstack(groups) if groups else np.zeros((0, 6))
        ends = np.cumsum([len(g) for g in groups]).astype(np.int64)
        gb = np.array([np.concatenate([g[:, :3].min(axis=0), g[:, 3:].max(axis=0)]) for g in groups]).reshape(-1, 6)
        eps = [self.lo.copy()]
        # extreme points from fixed parts, and from the top face of every obstacle (a deck parts can stand on)
        for g in groups[len(obstacles):]:
            for x in g:
                eps += [np.array([x[3], x[1], x[2]]), np.array([x[0], x[4], x[2]]), np.array([x[0], x[1], x[5]])]
        for x in obstacles:
            # beside an obstacle (e.g. next to a corner rail) and on top of it
            eps += [np.array([x[3], max(x[1], self.lo[1]), max(x[2], self.lo[2])]),
                    np.array([max(x[0], self.lo[0]), x[4], max(x[2], self.lo[2])]),
                    np.array([max(x[0], self.lo[0]), max(x[1], self.lo[1]), x[5]])]
        pts = np.unique(np.round(np.array(eps), 9), axis=0)
        if len(obs):
            inside = np.any(np.all((pts[:, None, :] > obs[None, :, :3] + TOL) & (pts[:, None, :] < obs[None, :, 3:] - TOL),
                                   axis=2), axis=1)
            pts = pts[~inside]
        gs = np.concatenate([[0], ends[:-1]]).astype(np.int64) if len(ends) else ends
        return obs, gb, pts, float(top), ends, gs, fixed_poses

    def inflate_obstacles(self, obstacles: np.ndarray, gap: float) -> np.ndarray:
        """Obstacle boxes grown so that part boxes (inflated by half the part gap) keep `gap` from them."""
        obs = np.asarray(obstacles, float).reshape(-1, 6)
        grow = max(gap - self.half, 0.0)
        return np.concatenate([obs[:, :3] - grow, obs[:, 3:] + grow], axis=1) if len(obs) else obs

    # ------------------------------------------------------------------------------------- decode
    def decode(self, order: list[int], orient_keys: np.ndarray, rule_keys: np.ndarray,
               extra_obstacles: np.ndarray | None = None, skip: set[int] = frozenset(),
               extra_targets: list | None = None) -> DecodeResult:
        """extra_obstacles: boxes already inflated (see inflate_obstacles) for this decode only; extra_targets: per
        extra obstacle, True if a bracket may land on it (mount spec). skip: part indices that are not placed by this
        decode (e.g. a macro placed by the caller)."""
        return self._run(order, np.asarray(orient_keys, float), np.asarray(rule_keys, float), False, extra_obstacles,
                         skip, extra_targets)

    def best_fit_all_orientations(self, order: list[int], rule: float = 0.0,
                                  extra_obstacles: np.ndarray | None = None, skip: set[int] = frozenset(),
                                  extra_targets: list | None = None) -> DecodeResult:
        """Constructive heuristic: every part tries every allowed orientation (initialiser / Stage 2 baseline)."""
        n = len(self.order_ids)
        return self._run(order, np.zeros(n), np.full(n, float(rule)), True, extra_obstacles, skip, extra_targets)

    def _run(self, order, okeys, rules, all_orient: bool, extra_obstacles=None, skip=frozenset(),
             extra_targets=None) -> DecodeResult:
        n = len(self.order_ids)
        if extra_obstacles is not None and len(extra_obstacles):
            extra = np.asarray(extra_obstacles, float).reshape(-1, 6)
            obs0, gb0, eps0, top0, ge0, gs0, fixed_poses = self._initial_state(
                np.vstack([self.obstacles.reshape(-1, 6), extra]), self.fixed)
            base = list(self.mount.targets) if self.mount is not None else []
            base += [False] * (len(self.obstacles) - len(base))
            gk0 = self._group_kinds(base + list(extra_targets or [False] * len(extra)), len(self.obstacles) + len(extra))
        else:
            obs0, gb0, eps0, top0, ge0, gs0, fixed_poses = (self._obs0, self._gb0, self._eps0, self._top0, self._ge0,
                                                            self._gs0, self._fixed_poses)
            gk0 = self._gk0
        seq = np.array([-1 if (i in self._fixed_idx or i in skip) else int(i) for i in order], np.int64)
        n_obs0, n_grp0, n_eps0 = len(obs0), len(gb0), len(eps0)
        n_obs_max = n_obs0 + self.max_boxes + n                 # + one reserved corridor per part
        obs = np.empty((n_obs_max, 6))
        obs[:n_obs0] = obs0
        is_corr = np.zeros(n_obs_max, np.bool_)
        gs = np.empty(n_grp0 + 2 * n, np.int64)
        ge = np.empty(n_grp0 + 2 * n, np.int64)
        gb = np.empty((n_grp0 + 2 * n, 6))
        gkind = np.empty(n_grp0 + 2 * n, np.int64)
        gs[:n_grp0], ge[:n_grp0], gb[:n_grp0], gkind[:n_grp0] = gs0, ge0, gb0, gk0
        eps = np.empty((n_eps0 + 3 * (self.max_boxes + n), 3))
        eps[:n_eps0] = eps0
        out_t = np.zeros((n, 3))
        out_o = np.full(n, -2, np.int64)
        top, n_obs = _decode_kernel(seq, np.ascontiguousarray(okeys), np.ascontiguousarray(rules), all_orient,
                                    self.allowed, self.n_allowed, self.tb, self.toff, self.tcnt, self.taabb,
                                    self.lo_p, self.hi_p, obs, gs, ge, gb, gkind, n_obs0, n_grp0, eps, n_eps0, top0,
                                    out_t, out_o, self.mixed, self.pad_rel, self.pad_dir, self.walls, self.mp,
                                    self.cg_part, self.cg_other, is_corr)
        poses = list(fixed_poses)
        unplaced = []
        for i in seq:
            if i < 0:
                continue
            pid = self.order_ids[i]
            if out_o[i] >= 0:
                poses.append((pid, int(out_o[i]), out_t[i].copy()))
            else:
                unplaced.append(pid)
        out = DecodeResult(poses, obs[:n_obs][~is_corr[:n_obs]], unplaced, float(top - self.lo[2]))
        out.corridors = obs[:n_obs][is_corr[:n_obs]]
        return out

    # ------------------------------------------------------------------------------------- internals
    def _world(self, part: ProxyPart, o: int, t) -> np.ndarray:
        b = part.oriented(o)
        h = self.half
        return np.concatenate([b[:, :3] + t - h, b[:, 3:] + t + h], axis=1)
