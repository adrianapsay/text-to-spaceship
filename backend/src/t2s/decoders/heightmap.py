"""Height-map decoder: a 2.5-D voxel placement engine (protocol §D.1 "voxel" family, simplified to columns).

The enclosure's cross-section is a grid of h × h mm columns. For every part and orientation we store, per column,
a conservative z-interval [bottom, top] of the part inside that column: each triangle is clipped to the column
(expanded by half the required gap) and the clipped polygon's z-range taken (exact for a planar triangle), then
widened by half the gap. Any vertical line through the solid meets its surface above and below, so the solid's
part in a column lies in the union of these ranges.

Placement drops a part onto the current skyline H (the top of everything already placed, per column):
z = max over its columns of (H − bottom). Columns are disjoint unless separated in z, so placed parts are at least
the required gap apart (L∞ inflation ⇒ Euclidean). Space under overhangs is treated as filled (2.5-D), so the
decoder is conservative; bores open to the top (a vertical tube) and curved tops (spheres, domes) are used.
Every layout is still certified by the validator before it can be VALIDATED.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..core.rotations import ROTATIONS_F
from .box_decoder import DecodeResult

try:
    from numba import njit
except Exception:  # noqa: BLE001
    njit = None


def _jit(fn):
    return njit(cache=True, nogil=True)(fn) if njit else fn


@_jit
def _clip_z_range(p, x0, x1, y0, y1):
    """z-range of triangle p (3x3) clipped to the column [x0,x1]x[y0,y1]; (inf, -inf) when empty."""
    poly = np.empty((16, 3))
    tmp = np.empty((16, 3))
    n = 3
    for k in range(3):
        poly[k, 0], poly[k, 1], poly[k, 2] = p[k, 0], p[k, 1], p[k, 2]
    for side in range(4):
        ax = 0 if side < 2 else 1
        bound = x0 if side == 0 else (x1 if side == 1 else (y0 if side == 2 else y1))
        keep_ge = side == 0 or side == 2
        m = 0
        for k in range(n):
            a0, a1, a2 = poly[k, 0], poly[k, 1], poly[k, 2]
            b0, b1, b2 = poly[(k + 1) % n, 0], poly[(k + 1) % n, 1], poly[(k + 1) % n, 2]
            sa = (a0 if ax == 0 else a1) - bound
            sb = (b0 if ax == 0 else b1) - bound
            if not keep_ge:
                sa, sb = -sa, -sb
            ina, inb = sa >= 0.0, sb >= 0.0
            if ina:
                tmp[m, 0], tmp[m, 1], tmp[m, 2] = a0, a1, a2
                m += 1
            if ina != inb:
                t = sa / (sa - sb)
                tmp[m, 0] = a0 + t * (b0 - a0)
                tmp[m, 1] = a1 + t * (b1 - a1)
                tmp[m, 2] = a2 + t * (b2 - a2)
                m += 1
        n = m
        if n == 0:
            return np.inf, -np.inf
        for k in range(n):
            poly[k, 0], poly[k, 1], poly[k, 2] = tmp[k, 0], tmp[k, 1], tmp[k, 2]
    lo, hi = np.inf, -np.inf
    for k in range(n):
        if poly[k, 2] < lo:
            lo = poly[k, 2]
        if poly[k, 2] > hi:
            hi = poly[k, 2]
    return lo, hi


@_jit
def _rasterise(tri, x_min, y_min, h, w, d, infl, bot, top):
    """tri: (T, 3, 3) oriented triangles. Fills bot/top (w x d) with conservative per-column z-ranges."""
    for a in range(w):
        for b in range(d):
            bot[a, b] = np.inf
            top[a, b] = -np.inf
    for t in range(tri.shape[0]):
        p = tri[t]
        tx0 = min(p[0, 0], p[1, 0], p[2, 0]) - infl
        tx1 = max(p[0, 0], p[1, 0], p[2, 0]) + infl
        ty0 = min(p[0, 1], p[1, 1], p[2, 1]) - infl
        ty1 = max(p[0, 1], p[1, 1], p[2, 1]) + infl
        i0 = max(0, int(np.floor((tx0 - x_min) / h)))
        i1 = min(w - 1, int(np.floor((tx1 - x_min) / h)))
        j0 = max(0, int(np.floor((ty0 - y_min) / h)))
        j1 = min(d - 1, int(np.floor((ty1 - y_min) / h)))
        for i in range(i0, i1 + 1):
            cx0 = x_min + i * h - infl
            cx1 = x_min + (i + 1) * h + infl
            for j in range(j0, j1 + 1):
                cy0 = y_min + j * h - infl
                cy1 = y_min + (j + 1) * h + infl
                lo, hi = _clip_z_range(p, cx0, cx1, cy0, cy1)
                if lo <= hi:
                    if lo - infl < bot[i, j]:
                        bot[i, j] = lo - infl
                    if hi + infl > top[i, j]:
                        top[i, j] = hi + infl


@_jit
def _best_position(H, bot, top, w, d, nx, ny, zcap, rule, h, top_all):
    """Scan all column offsets; return (merit, ox, oy, z) of the best drop (merit inf if nothing fits).
    Merit as in the box decoder: resulting overall top first, then the lowest bottom, then the placement rule."""
    best = np.inf
    bx, by, bz = -1, -1, 0.0
    for ox in range(nx - w + 1):
        for oy in range(ny - d + 1):
            z = -np.inf
            for i in range(w):
                for j in range(d):
                    if bot[i, j] < np.inf:
                        v = H[ox + i, oy + j] - bot[i, j]
                        if v > z:
                            z = v
            ztop = -np.inf
            for i in range(w):
                for j in range(d):
                    if top[i, j] > -np.inf:
                        v = z + top[i, j]
                        if v > ztop:
                            ztop = v
            if ztop > zcap:
                continue
            cx = (ox + 0.5 * w) * h - 0.5 * nx * h
            cy = (oy + 0.5 * d) * h - 0.5 * ny * h
            wall = (ox + oy) * h
            axis_d = np.sqrt(cx * cx + cy * cy)
            merit = max(ztop, top_all) * 1e3 + z + 1e-3 * ((1 - rule) * wall + rule * axis_d)
            if merit < best:
                best, bx, by, bz = merit, ox, oy, z
    return best, bx, by, bz


@_jit
def _stamp(H, top, w, d, ox, oy, z):
    for i in range(w):
        for j in range(d):
            if top[i, j] > -np.inf:
                v = z + top[i, j]
                if v > H[ox + i, oy + j]:
                    H[ox + i, oy + j] = v


@dataclass
class Footprint:
    w: int
    d: int
    bot: np.ndarray            # (w, d) relative to the part's canonical origin after rotation
    top: np.ndarray
    x_min: float               # grid origin of the part (oriented AABB minimum, minus inflation)
    y_min: float


class HeightmapDecoder:
    """Same chromosome as the box decoder (order, orientation, rule); see module docstring."""

    def __init__(self, parts: dict, lo: np.ndarray, hi: np.ndarray, h: float = 2.0, gap: float = 0.005,
                 blocked: np.ndarray | None = None):
        """parts: part_id -> (v, f, allowed orientations) in the canonical frame."""
        self.lo = np.asarray(lo, float)
        self.hi = np.asarray(hi, float)
        self.h = float(h)
        self.nx = int(np.floor((self.hi[0] - self.lo[0]) / h + 1e-9))
        self.ny = int(np.floor((self.hi[1] - self.lo[1]) / h + 1e-9))
        self.infl = gap / 2.0
        self.order_ids = list(parts)
        self.parts = {pid: _Allowed(a) for pid, (_, _, a) in parts.items()}
        self.fp: dict[tuple[str, int], Footprint] = {}
        self.H0 = np.full((self.nx, self.ny), self.lo[2])
        if blocked is not None:
            self.H0[blocked] = np.inf
        for pid, (v, f, allowed) in parts.items():
            tri0 = np.ascontiguousarray(v[f], float)
            for o in allowed:
                tri = tri0 @ ROTATIONS_F[o].T
                pts = tri.reshape(-1, 3)
                x_min = float(pts[:, 0].min()) - self.infl
                y_min = float(pts[:, 1].min()) - self.infl
                w = int(np.floor((pts[:, 0].max() + self.infl - x_min) / h)) + 1
                d = int(np.floor((pts[:, 1].max() + self.infl - y_min) / h)) + 1
                bot = np.empty((w, d))
                top = np.empty((w, d))
                _rasterise(np.ascontiguousarray(tri), x_min, y_min, self.h, w, d, self.infl, bot, top)
                self.fp[(pid, o)] = Footprint(w, d, bot, top, x_min, y_min)

    def decode(self, order: list[int], orient_keys: np.ndarray, rule_keys: np.ndarray) -> DecodeResult:
        H = self.H0.copy()
        poses, unplaced = [], []
        top_all = self.lo[2]
        for idx in order:
            pid = self.order_ids[idx]
            allowed = self.parts[pid].allowed
            o = allowed[min(int(orient_keys[idx] * len(allowed)), len(allowed) - 1)]
            fp = self.fp[(pid, o)]
            if fp.w > self.nx or fp.d > self.ny:
                unplaced.append(pid)
                continue
            merit, ox, oy, z = _best_position(H, fp.bot, fp.top, fp.w, fp.d, self.nx, self.ny, self.hi[2],
                                              float(rule_keys[idx]), self.h, top_all)
            if ox < 0:
                unplaced.append(pid)
                continue
            _stamp(H, fp.top, fp.w, fp.d, ox, oy, z)
            # world translation: grid cell (ox, oy) holds the part's local cell (0, 0)
            t = np.array([self.lo[0] + ox * self.h - fp.x_min, self.lo[1] + oy * self.h - fp.y_min, z])
            # integer-µm pose, rounded upward in z (never closer to what lies below than the certified drop)
            t = np.array([np.round(t[0] * 1000.0), np.round(t[1] * 1000.0), np.ceil(t[2] * 1000.0 - 1e-6)]) / 1000.0
            poses.append((pid, o, t))
            top_all = max(top_all, z + float(fp.top[fp.top > -np.inf].max()))
        return DecodeResult(poses, np.zeros((0, 6)), unplaced, float(top_all - self.lo[2]))

    def best_fit_all_orientations(self, order: list[int], rule: float = 0.0) -> DecodeResult:
        H = self.H0.copy()
        poses, unplaced = [], []
        top_all = self.lo[2]
        for idx in order:
            pid = self.order_ids[idx]
            best = None
            for o in self.parts[pid].allowed:
                fp = self.fp[(pid, o)]
                if fp.w > self.nx or fp.d > self.ny:
                    continue
                r = _best_position(H, fp.bot, fp.top, fp.w, fp.d, self.nx, self.ny, self.hi[2], rule, self.h, top_all)
                if r[1] >= 0 and (best is None or r[0] < best[0]):
                    best = (r[0], o, r[1], r[2], r[3])
            if best is None:
                unplaced.append(pid)
                continue
            _, o, ox, oy, z = best
            fp = self.fp[(pid, o)]
            _stamp(H, fp.top, fp.w, fp.d, ox, oy, z)
            t = np.array([self.lo[0] + ox * self.h - fp.x_min, self.lo[1] + oy * self.h - fp.y_min, z])
            t = np.array([np.round(t[0] * 1000.0), np.round(t[1] * 1000.0), np.ceil(t[2] * 1000.0 - 1e-6)]) / 1000.0
            poses.append((pid, o, t))
            top_all = max(top_all, z + float(fp.top[fp.top > -np.inf].max()))
        return DecodeResult(poses, np.zeros((0, 6)), unplaced, float(top_all - self.lo[2]))


@dataclass
class _Allowed:
    allowed: list[int]
