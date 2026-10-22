"""Convex hull (Qhull via SciPy) and approximate minimum-volume oriented bounding box."""
from dataclasses import dataclass

import numpy as np
from scipy.spatial import ConvexHull


@dataclass
class HullInfo:
    volume: float
    area: float
    vertex_ids: np.ndarray          # indices into the source vertex array
    equations: np.ndarray           # (m, 4): n·x + d <= 0 inside, |n| = 1
    simplices: np.ndarray           # (m, 3) indices into the source vertex array


def convex_hull(v: np.ndarray) -> HullInfo | None:
    if len(v) < 4:
        return None
    try:
        h = ConvexHull(v)
    except Exception:  # noqa: BLE001 - degenerate (flat) input
        return None
    return HullInfo(float(h.volume), float(h.area), h.vertices.copy(), h.equations.copy(), h.simplices.copy())


def _extents(points: np.ndarray, axes: np.ndarray) -> np.ndarray:
    proj = points @ axes            # axes as columns
    return proj.max(axis=0) - proj.min(axis=0)


def _rot_pair(axes: np.ndarray, i: int, j: int, deg: float) -> np.ndarray:
    c, s = np.cos(np.radians(deg)), np.sin(np.radians(deg))
    out = axes.copy()
    out[:, i] = c * axes[:, i] + s * axes[:, j]
    out[:, j] = -s * axes[:, i] + c * axes[:, j]
    return out


def _frame_from_normal(n: np.ndarray) -> np.ndarray:
    a = np.array([1.0, 0, 0]) if abs(n[0]) < 0.9 else np.array([0, 1.0, 0])
    u = np.cross(n, a)
    u /= np.linalg.norm(u)
    return np.column_stack([u, np.cross(n, u), n])


def _refine(points: np.ndarray, axes: np.ndarray):
    best = _extents(points, axes)
    best_vol = float(np.prod(best))
    for step in (5.0, 1.0, 0.2, 0.05, 0.01):
        improved = True
        while improved:
            improved = False
            for i, j in ((0, 1), (0, 2), (1, 2)):
                for sgn in (1.0, -1.0):
                    cand = _rot_pair(axes, i, j, sgn * step)
                    e = _extents(points, cand)
                    vol = float(np.prod(e))
                    if vol < best_vol * (1 - 1e-12):
                        axes, best, best_vol, improved = cand, e, vol, True
    return best, axes


def _snap_axes(axes: np.ndarray, normals: np.ndarray, max_deg: float = 0.5) -> np.ndarray:
    """Snap OBB axes onto hull facet normals within max_deg, so box-like parts get exactly flush frames."""
    cos_lim = np.cos(np.radians(max_deg))
    out = axes.copy()
    snapped = []
    for k in range(3):
        dots = normals @ out[:, k]
        j = int(np.argmax(np.abs(dots)))
        if abs(dots[j]) >= cos_lim:
            n = normals[j] * np.sign(dots[j])
            for s in snapped:
                n = n - (n @ out[:, s]) * out[:, s]
            if np.linalg.norm(n) > 0.5:
                out[:, k] = n / np.linalg.norm(n)
                snapped.append(k)
    if len(snapped) >= 2:
        a, b = snapped[0], snapped[1]
        c = 3 - a - b
        out[:, c] = np.cross(out[:, (c + 1) % 3], out[:, (c + 2) % 3])
    # re-orthonormalise (Gram-Schmidt in snapped-first order)
    order = snapped + [k for k in range(3) if k not in snapped]
    q = np.zeros((3, 3))
    for i, k in enumerate(order):
        x = out[:, k].copy()
        for j in order[:i]:
            x -= (x @ q[:, j]) * q[:, j]
        q[:, k] = x / np.linalg.norm(x)
    if np.linalg.det(q) < 0:
        q[:, order[-1]] = -q[:, order[-1]]
    return q


def min_obb(points: np.ndarray, hull: HullInfo | None, start_axes: np.ndarray | None = None):
    """Approximate minimum-volume OBB. Returns (extents, axes as columns, centre in the input frame)."""
    pts = points[hull.vertex_ids] if hull is not None else points
    sample = pts[:: max(1, len(pts) // 400)]
    starts = [np.eye(3)]
    if start_axes is not None:
        starts.append(start_axes)
    if hull is not None:
        normals = hull.equations[:, :3]
        tri = points[hull.simplices]
        areas = 0.5 * np.linalg.norm(np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]), axis=1)
        seen = set()
        for k in np.argsort(-areas):
            n = normals[k].copy()
            if n[0] < -1e-9 or (abs(n[0]) <= 1e-9 and (n[1] < -1e-9 or (abs(n[1]) <= 1e-9 and n[2] < 0))):
                n = -n
            key = tuple(np.round(n, 2) + 0.0)
            if key in seen:
                continue
            seen.add(key)
            base = _frame_from_normal(n)
            cands = [_rot_pair(base, 0, 1, 6.0 * i) for i in range(15)]
            starts.append(min(cands, key=lambda ax: float(np.prod(_extents(sample, ax)))))
            if len(seen) >= 24:
                break
    starts.sort(key=lambda ax: float(np.prod(_extents(sample, ax))))
    best = None
    for ax in starts[:4]:
        e, a = _refine(pts, ax)
        if best is None or np.prod(e) < np.prod(best[0]):
            best = (e, a)
    ext, axes = best
    if hull is not None:
        axes = _snap_axes(axes, hull.equations[:, :3])
        ext = _extents(pts, axes)
    proj = pts @ axes
    centre = axes @ (0.5 * (proj.max(axis=0) + proj.min(axis=0)))
    return ext, axes, centre
