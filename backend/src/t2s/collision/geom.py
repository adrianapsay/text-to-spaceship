"""Per-part collision geometry cache and world-frame helpers (kernel units: millimetres, float64)."""
from dataclasses import dataclass, field

import numpy as np

from ..core.rotations import ROTATIONS_F
from ..geometry.proxies import COVER_DELTA


@dataclass
class PartGeom:
    """Everything the collision ladder needs for one part, in its canonical frame."""
    part_id: str
    v: np.ndarray
    f: np.ndarray
    hull_pts: np.ndarray                 # convex hull vertices (contain the part)
    hull_exact: bool                     # part is (numerically) its own hull
    boxes: np.ndarray                    # G1 boxes (m, 6), certified containment
    boxes_ok: bool
    pieces: list[np.ndarray]             # G3 cover piece vertex sets
    pieces_ok: bool
    orient_bounds: np.ndarray            # (24, 6) AABB of R_k · hull
    comp_probe: np.ndarray               # one vertex per connected component (containment test)
    _fcl: object = field(default=None, repr=False)
    _hull_bvh: object = field(default=None, repr=False)
    _piece_bvh: dict = field(default_factory=dict, repr=False)

    def hull_bvh(self):
        if self._hull_bvh is None:
            self._hull_bvh = _convex_bvh(self.hull_pts)
        return self._hull_bvh

    def piece_bvh(self, i: int):
        if i not in self._piece_bvh:
            self._piece_bvh[i] = _convex_bvh(self.pieces[i])
        return self._piece_bvh[i]

    def fcl_model(self):
        if self._fcl is None:
            import fcl
            m = fcl.BVHModel()
            m.beginModel(len(self.v), len(self.f))
            m.addSubModel(np.ascontiguousarray(self.v, dtype=np.float64), np.ascontiguousarray(self.f, dtype=np.int32))
            m.endModel()
            self._fcl = m
        return self._fcl


def _convex_bvh(points: np.ndarray):
    """FCL BVH of a point set's convex hull surface (used only to find witness directions)."""
    import fcl
    from scipy.spatial import ConvexHull
    try:
        h = ConvexHull(points)
    except Exception:  # noqa: BLE001
        return None
    m = fcl.BVHModel()
    m.beginModel(len(points), len(h.simplices))
    m.addSubModel(np.ascontiguousarray(points, dtype=np.float64), np.ascontiguousarray(h.simplices, dtype=np.int32))
    m.endModel()
    return m


def part_geom_from_record(rec) -> "PartGeom":
    from ..geometry.mesh import face_components
    hull_pts = rec.v[rec.hull.vertex_ids] if rec.hull is not None else rec.v
    exact = rec.volume_mm3 is not None and rec.hull_volume_mm3 is not None and \
        rec.hull_volume_mm3 - rec.volume_mm3 <= 1e-9 * rec.volume_mm3
    _, labels = face_components(rec.f)
    probes = []
    for c in np.unique(labels):
        probes.append(rec.v[rec.f[np.flatnonzero(labels == c)[0], 0]])
    return PartGeom(rec.id, rec.v, rec.f, hull_pts, bool(exact), rec.boxes, bool(rec.boxes_certified),
                    [p.vertices for p in rec.cover.pieces], bool(rec.cover.certified), rec.orient_bounds,
                    np.array(probes))


def to_world(points: np.ndarray, orient: int, t_mm: np.ndarray) -> np.ndarray:
    return points @ ROTATIONS_F[orient].T + t_mm


def world_aabb(g: PartGeom, orient: int, t_mm: np.ndarray) -> np.ndarray:
    b = g.orient_bounds[orient]
    return np.concatenate([b[:3] + t_mm, b[3:] + t_mm])


def boxes_world(boxes: np.ndarray, orient: int, t_mm: np.ndarray) -> np.ndarray:
    """Rotate axis-aligned boxes by a signed permutation (exact: stays axis-aligned)."""
    r = ROTATIONS_F[orient]
    lo = boxes[:, :3] @ r.T
    hi = boxes[:, 3:] @ r.T
    return np.concatenate([np.minimum(lo, hi) + t_mm, np.maximum(lo, hi) + t_mm], axis=1)


def aabb_gap(a: np.ndarray, b: np.ndarray) -> float:
    """Largest axis separation between two AABBs (a lower bound on Euclidean distance); negative = overlap."""
    return float(np.max(np.maximum(b[:3] - a[3:], a[:3] - b[3:])))


def aabb_distance(a: np.ndarray, b: np.ndarray) -> float:
    d = np.maximum(0.0, np.maximum(b[:3] - a[3:], a[:3] - b[3:]))
    return float(np.linalg.norm(d))


PIECE_MARGIN = 2 * COVER_DELTA
