"""Canonical frame selection (protocol §D.5 as revised by the cross-check).

Candidates: authored, minimum-volume OBB, principal-inertia (only if eigen-gaps > 1e-3), largest planar face.
Score: volume of the certified compound-box proxy in that frame; ties -> authored, then the fixed order above.
A candidate within 1e-9 of a signed permutation is snapped to it so axis-aligned parts keep exact coordinates.
"""
import numpy as np

from ..core.rotations import ROTATIONS_F
from .hull_obb import HullInfo, _extents, _rot_pair
from .proxies import compound_boxes

ORDER = ("authored", "min_obb", "principal", "largest_face")


def _proper(r: np.ndarray) -> np.ndarray:
    r = np.asarray(r, float).copy()
    if np.linalg.det(r) < 0:
        r[:, 2] = -r[:, 2]
    # snap to a signed permutation when numerically identical (keeps exact float32 coordinates)
    for p in ROTATIONS_F:
        if np.max(np.abs(r - p)) < 1e-9:
            return p.copy()
    return r


def _largest_face_frame(v: np.ndarray, hull: HullInfo) -> np.ndarray:
    tri = v[hull.simplices]
    areas = 0.5 * np.linalg.norm(np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]), axis=1)
    normals = hull.equations[:, :3]
    keys = np.round(normals, 4)
    uniq, inv = np.unique(keys, axis=0, return_inverse=True)
    sums = np.bincount(inv.ravel(), weights=areas)
    n = uniq[int(np.argmax(sums))]
    n = n / np.linalg.norm(n)
    a = np.array([1.0, 0, 0]) if abs(n[0]) < 0.9 else np.array([0, 1.0, 0])
    u = np.cross(n, a)
    u /= np.linalg.norm(u)
    base = np.column_stack([u, np.cross(n, u), n])
    pts = v[hull.vertex_ids]
    best = min((_rot_pair(base, 0, 1, 0.5 * k) for k in range(180)), key=lambda ax: float(np.prod(_extents(pts, ax))))
    return best


def candidate_frames(v, hull, obb_axes, principal_axes, principal_ok) -> dict[str, np.ndarray]:
    c = {"authored": np.eye(3), "min_obb": _proper(obb_axes)}
    if principal_ok:
        c["principal"] = _proper(principal_axes)
    if hull is not None:
        c["largest_face"] = _proper(_largest_face_frame(v, hull))
    return c


def choose_frame(v, f, hull, obb_axes, principal_axes, principal_ok):
    """Return (name, R with canonical axes as columns, origin in authored coords, scores dict)."""
    cands = candidate_frames(v, hull, obb_axes, principal_axes, principal_ok)
    scores = {}
    seen = []
    for name in ORDER:
        if name not in cands:
            continue
        r = cands[name]
        if any(np.max(np.abs(r - s)) < 1e-9 for s in seen):
            continue
        seen.append(r)
        vc = v @ r
        boxes, _ = compound_boxes(vc, f)
        scores[name] = float(np.prod(boxes[:, 3:] - boxes[:, :3], axis=1).sum())
    best = min(scores, key=lambda k: (round(scores[k] * 1e6) / 1e6, ORDER.index(k)))
    # ties within 1e-9 relative go to the earlier name in ORDER
    ref = scores[best]
    for name in ORDER:
        if name in scores and abs(scores[name] - ref) <= 1e-9 * max(ref, 1.0):
            best = name
            break
    r = cands[best]
    vc = v @ r
    centre_c = 0.5 * (vc.min(axis=0) + vc.max(axis=0))
    origin = r @ centre_c
    return best, r, origin, scores
