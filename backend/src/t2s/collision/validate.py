"""Layout validator: the only component allowed to mark a layout VALIDATED (protocol §D.3, §F.2).

Collision ladder per pair; each level either proves the required separation or passes the pair on:
  G0  axis gap between world AABBs (AABBs are built from hull vertices, so an axis plane separates the hulls)
  G1  certified compound boxes, all box pairs separated
  G2  convex hulls: separating plane found by Gilbert's min-norm iteration, gap checked over ALL hull vertices
  G3  certified convex-cover pieces: every piece pair separated by >= c + 2·COVER_DELTA
  G4  exact meshes: FCL BVH collision + distance, winding-number containment test, manifold3d min_gap cross-check
Separation proofs never trust a solver: a plane is accepted only after its gap is evaluated in float64 over
every vertex of both point sets.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

import numpy as np

from ..core.rotations import ROTATIONS_F
from ..geometry.mesh import ray_parity_inside
from .geom import PIECE_MARGIN, PartGeom, aabb_gap, boxes_world, to_world, world_aabb

VALIDATOR_VERSION = "1.0"
G4_TOL = 1e-3          # mm: required agreement of exact distances (1 µm accuracy rule)
TIGHT_BAND = 5.0       # mm: within this band above the requirement, report tight certified gaps (margin objective)


@dataclass
class StaticItem:
    name: str
    corners: np.ndarray            # (8, 3) world box corners
    kind: str = "keepout"          # rail | rod | harness | keepout | frame


@dataclass
class StageSpec:
    stage: int
    lo: np.ndarray                 # containment bounds for part vertices (clearance already applied)
    hi: np.ndarray
    c_pp: float                    # required part-part separation (mm); Stage 1: 0
    c_static: float                # required part-static separation (mm)
    statics: list[StaticItem] = field(default_factory=list)
    exempt: set = field(default_factory=set)      # {(part_id, static_name)} pairs exempt by design
    # V2: clearances between static boxes (bracket reserves vs each other and vs keep-outs): (name_a, name_b, mm)
    static_pairs: list = field(default_factory=list)


@dataclass
class PairResult:
    a: str
    b: str
    level: str                     # G0..G4 | OVERLAP | INDETERMINATE
    gap_lb_mm: float               # certified lower bound (G0-G3) or exact distance (G4)
    required_mm: float
    ok: bool
    planes: list = field(default_factory=list)    # [(normal(3), offset_a, offset_b, gap)] for proofs
    detail: str = ""


@dataclass
class ValidationReport:
    valid: bool
    stage: int
    containment: list[dict]
    pairs: list[PairResult]
    statics: list[PairResult]
    levels: dict
    min_clearance_mm: float
    seconds: float
    violations: list[str]
    validator_version: str = VALIDATOR_VERSION
    static_pairs: list = field(default_factory=list)   # PairResult per spec.static_pairs entry (box arithmetic)


def box_gap(ca: np.ndarray, cb: np.ndarray) -> float:
    """Largest axis separation between the axis-aligned boxes spanned by two corner sets (≤ their distance)."""
    la, ha, lb, hb = ca.min(0), ca.max(0), cb.min(0), cb.max(0)
    return float(np.max(np.maximum(lb - ha, la - hb)))


def separating_direction(a: np.ndarray, b: np.ndarray, iters: int = 80):
    """Gilbert / Frank-Wolfe min-norm point of conv(A) − conv(B). Returns (unit normal from A to B, gap)."""
    x = a.mean(axis=0) - b.mean(axis=0)
    best_n, best_gap = None, -np.inf
    for _ in range(iters):
        if not np.any(x):
            break
        s = a[np.argmin(a @ x)] - b[np.argmax(b @ x)]
        d = x - s
        dd = d @ d
        if dd <= 0:
            break
        t = min(1.0, max(0.0, (x @ d) / dd))
        x = x - t * d
        n = -x / (np.linalg.norm(x) + 1e-300)
        gap = float((b @ n).min() - (a @ n).max())
        if gap > best_gap:
            best_n, best_gap = n, gap
        if t < 1e-12:
            break
    return best_n, best_gap


def fcl_witness(bvh_a, oa, ta, bvh_b, ob, tb):
    """Direction from A's to B's closest points between two convex-hull BVHs (None if overlapping)."""
    if bvh_a is None or bvh_b is None:
        return None
    import fcl
    xa = fcl.CollisionObject(bvh_a, fcl.Transform(ROTATIONS_F[oa], np.asarray(ta, float)))
    xb = fcl.CollisionObject(bvh_b, fcl.Transform(ROTATIONS_F[ob], np.asarray(tb, float)))
    res = fcl.DistanceResult()
    d = fcl.distance(xa, xb, fcl.DistanceRequest(enable_nearest_points=True), res)
    if d <= 0:
        return None
    p, q = np.asarray(res.nearest_points[0]), np.asarray(res.nearest_points[1])
    v = q - p
    nv = np.linalg.norm(v)
    return v / nv if nv > 0 else None


def plane_certificate(a: np.ndarray, b: np.ndarray, extra_normals=()):
    """Best certified separating plane between point sets a and b (all vertices evaluated)."""
    cands = [np.eye(3)[k] * s for k in range(3) for s in (1.0, -1.0)]
    cands.extend(n for n in extra_normals if n is not None)
    n_g, _ = separating_direction(a, b)
    if n_g is not None:
        cands.append(n_g)
    best = (None, -np.inf, 0.0, 0.0)
    for n in cands:
        n = np.asarray(n, float)
        n = n / np.linalg.norm(n)
        hi_a = float((a @ n).max())
        lo_b = float((b @ n).min())
        gap = lo_b - hi_a
        if gap > best[1]:
            best = (n, gap, hi_a, lo_b)
    return best


class Validator:
    def __init__(self, geoms: dict[str, PartGeom], tight_band: float = TIGHT_BAND):
        self.geoms = geoms
        self.tight_band = tight_band

    def validate(self, poses: list[tuple[str, int, np.ndarray]], spec: StageSpec, want_planes: bool = True,
                 stop_on_failure: bool = False) -> ValidationReport:
        t0 = time.perf_counter()
        violations, containment = [], []
        world = []
        for pid, orient, t in poses:
            g = self.geoms[pid]
            t = np.asarray(t, float)
            hull_w = to_world(g.hull_pts, orient, t)
            lo, hi = hull_w.min(axis=0), hull_w.max(axis=0)
            m_lo, m_hi = lo - spec.lo, spec.hi - hi
            ok = bool(np.all(m_lo >= -1e-9) and np.all(m_hi >= -1e-9))
            containment.append({"part": pid, "ok": ok, "margin_lo_mm": m_lo.tolist(), "margin_hi_mm": m_hi.tolist()})
            if not ok:
                violations.append(f"{pid} outside the enclosure by {float(-min(m_lo.min(), m_hi.min())):.4f} mm")
            world.append((pid, orient, t, g, hull_w, world_aabb(g, orient, t)))
            if stop_on_failure and violations:
                break
        levels = {k: 0 for k in ("G0", "G1", "G2", "G3", "G4", "OVERLAP", "INDETERMINATE")}
        pairs: list[PairResult] = []
        for i in range(len(world)):
            for j in range(i + 1, len(world)):
                r = self._pair(world[i], world[j], spec.c_pp, want_planes)
                levels[r.level] = levels.get(r.level, 0) + 1
                pairs.append(r)
                if not r.ok:
                    violations.append(f"{r.a} – {r.b}: {r.detail}")
                    if stop_on_failure:
                        break
            if stop_on_failure and violations:
                break
        statics: list[PairResult] = []
        for w in world:
            for s in spec.statics:
                if (w[0], s.name) in spec.exempt:
                    continue
                r = self._static(w, s, spec.c_static)
                statics.append(r)
                if not r.ok:
                    violations.append(f"{r.a} – {r.b}: {r.detail}")
        named = {s.name: s for s in spec.statics}
        static_pairs: list[PairResult] = []
        for a, b, req in spec.static_pairs:
            g = box_gap(named[a].corners, named[b].corners)
            ok = g >= req - 1e-9
            static_pairs.append(PairResult(a, b, "AABB", g, req, ok,
                                           detail="" if ok else f"box gap {g:.4f} mm < required {req:.4f} mm"))
            if not ok:
                violations.append(f"{a} – {b}: box gap {g:.4f} mm < required {req:.4f} mm")
        gaps = [p.gap_lb_mm for p in pairs] + [p.gap_lb_mm for p in statics]
        return ValidationReport(valid=not violations, stage=spec.stage, containment=containment, pairs=pairs,
                                statics=statics, levels=levels, min_clearance_mm=float(min(gaps)) if gaps else np.inf,
                                seconds=time.perf_counter() - t0, violations=violations, static_pairs=static_pairs)

    # ----------------------------------------------------------------------------------------- pairs
    def _pair(self, wa, wb, c: float, want_planes: bool) -> PairResult:
        pa, oa, ta, ga, ha, ba = wa
        pb, ob, tb, gb, hb, bb = wb
        gap0 = aabb_gap(ba, bb)
        k = int(np.argmax(np.maximum(bb[:3] - ba[3:], ba[:3] - bb[3:])))
        n0 = np.zeros(3)
        n0[k] = 1.0 if bb[k] - ba[3 + k] >= ba[k] - bb[3 + k] else -1.0
        plane0 = (n0.tolist(), float((ha @ n0).max()), float((hb @ n0).min()), gap0)
        if gap0 >= c + self.tight_band:
            # far apart: the AABB axis plane proves it; tightness does not matter beyond the margin band
            return PairResult(pa, pb, "G0", gap0, c, True, [plane0] if want_planes else [])
        wdir = fcl_witness(ga.hull_bvh(), oa, ta, gb.hull_bvh(), ob, tb)
        n, gap, hi_a, lo_b = plane_certificate(ha, hb, [wdir])
        if gap0 > gap:
            n, gap, hi_a, lo_b = n0, gap0, plane0[1], plane0[2]
        if gap >= c:
            return PairResult(pa, pb, "G2" if gap > gap0 else "G0", gap, c, True, [(np.asarray(n).tolist(), hi_a, lo_b, gap)])
        if ga.pieces_ok and gb.pieces_ok and (len(ga.pieces) > 1 or len(gb.pieces) > 1 or not (ga.hull_exact and gb.hull_exact)):
            margin = max(PIECE_MARGIN, ga.piece_delta + gb.piece_delta)
            ok, worst, planes = self._pieces(wa, wb, c + margin)
            if ok:
                return PairResult(pa, pb, "G3", worst - margin, c, True, planes)
        if ga.boxes_ok and gb.boxes_ok:
            bxa, bxb = boxes_world(ga.boxes, oa, ta), boxes_world(gb.boxes, ob, tb)
            g = np.max(np.maximum(bxb[None, :, :3] - bxa[:, None, 3:], bxa[:, None, :3] - bxb[None, :, 3:]), axis=2)
            if g.min() >= c:
                return PairResult(pa, pb, "G1", float(g.min()), c, True, detail="certified compound boxes")
        return self._exact(wa, wb, c)

    def _attach_planes(self, res: PairResult, wa, wb, c):
        n, gap, hi_a, lo_b = plane_certificate(wa[4], wb[4])
        if gap >= c:
            res.planes = [(n.tolist(), hi_a, lo_b, gap)]
            return
        ok, worst, planes = self._pieces(wa, wb, c + max(PIECE_MARGIN, wa[3].piece_delta + wb[3].piece_delta))
        if ok:
            res.planes = planes

    def _pieces(self, wa, wb, c_req: float):
        pa, oa, ta, ga, _, _ = wa
        pb, ob, tb, gb, _, _ = wb
        worst = np.inf
        planes = []
        wpa = [to_world(p, oa, ta) for p in ga.pieces]
        wpb = [to_world(p, ob, tb) for p in gb.pieces]
        boxa = [np.concatenate([p.min(0), p.max(0)]) for p in wpa]
        boxb = [np.concatenate([p.min(0), p.max(0)]) for p in wpb]
        for i, (xa, ba) in enumerate(zip(wpa, boxa)):
            for j, (xb, bb) in enumerate(zip(wpb, boxb)):
                g0 = aabb_gap(ba, bb)
                if g0 >= c_req + self.tight_band:
                    k = int(np.argmax(np.maximum(bb[:3] - ba[3:], ba[:3] - bb[3:])))
                    n = np.zeros(3)
                    n[k] = 1.0 if bb[k] - ba[3 + k] >= ba[k] - bb[3 + k] else -1.0
                    planes.append({"piece_a": i, "piece_b": j, "n": n.tolist(), "hi_a": float((xa @ n).max()),
                                   "lo_b": float((xb @ n).min()), "gap": g0})
                    worst = min(worst, g0)
                    continue
                wdir = fcl_witness(ga.piece_bvh(i), oa, ta, gb.piece_bvh(j), ob, tb)
                n, gap, hi_a, lo_b = plane_certificate(xa, xb, [wdir])
                if g0 > gap:              # the AABB axis plane is itself a valid (better) certificate
                    k = int(np.argmax(np.maximum(bb[:3] - ba[3:], ba[:3] - bb[3:])))
                    n = np.zeros(3)
                    n[k] = 1.0 if bb[k] - ba[3 + k] >= ba[k] - bb[3 + k] else -1.0
                    gap, hi_a, lo_b = g0, float((xa @ n).max()), float((xb @ n).min())
                if gap < c_req:
                    return False, gap, []
                planes.append({"piece_a": i, "piece_b": j, "n": n.tolist(), "hi_a": hi_a, "lo_b": lo_b, "gap": gap})
                worst = min(worst, gap)
        return True, worst, planes

    def _exact(self, wa, wb, c: float) -> PairResult:
        import fcl
        pa, oa, ta, ga, _, _ = wa
        pb, ob, tb, gb, _, _ = wb
        oa_ = fcl.CollisionObject(ga.fcl_model(), fcl.Transform(ROTATIONS_F[oa], ta))
        ob_ = fcl.CollisionObject(gb.fcl_model(), fcl.Transform(ROTATIONS_F[ob], tb))
        cres = fcl.CollisionResult()
        if fcl.collide(oa_, ob_, fcl.CollisionRequest(), cres) > 0:
            return PairResult(pa, pb, "OVERLAP", -1.0, c, False, detail="surfaces intersect")
        dres = fcl.DistanceResult()
        d = float(fcl.distance(oa_, ob_, fcl.DistanceRequest(enable_nearest_points=True), dres))
        # containment trap: FCL sees surfaces only; test one vertex per component of each part inside the other
        va = to_world(ga.comp_probe, oa, ta)
        vb = to_world(gb.comp_probe, ob, tb)
        # world -> canonical frame of the other part: p_can = R^T (p - t), i.e. (p - t) @ R for row vectors
        a_in_b = ray_parity_inside((va - tb) @ ROTATIONS_F[ob], gb.v, gb.f) > 0.5
        b_in_a = ray_parity_inside((vb - ta) @ ROTATIONS_F[oa], ga.v, ga.f) > 0.5
        if a_in_b.any() or b_in_a.any():
            return PairResult(pa, pb, "OVERLAP", -1.0, c, False, detail="one part lies inside the other")
        if d < c + 0.5:
            cross = _manifold_gap(ga, oa, ta, gb, ob, tb, c + 1.0)
            if cross is not None and abs(cross - d) > G4_TOL and not (cross >= c + 1.0 and d >= c + 1.0):
                return PairResult(pa, pb, "INDETERMINATE", min(d, cross), c, False,
                                  detail=f"exact distances disagree: FCL {d:.6f} vs manifold {cross:.6f} mm")
        ok = d >= c - G4_TOL if c > 0 else d >= 0.0
        return PairResult(pa, pb, "G4", d, c, ok, detail="" if ok else f"distance {d:.4f} mm < required {c:.4f} mm")

    def _static(self, w, s: StaticItem, c: float) -> PairResult:
        pid, orient, t, g, hull_w, box = w
        sbox = np.concatenate([s.corners.min(0), s.corners.max(0)])
        gap0 = aabb_gap(box, sbox)
        if gap0 >= c:
            return PairResult(pid, s.name, "G0", gap0, c, True)
        n, gap, hi_a, lo_b = plane_certificate(hull_w, s.corners)
        if gap >= c:
            return PairResult(pid, s.name, "G2", gap, c, True, [(n.tolist(), hi_a, lo_b, gap)])
        if g.pieces_ok:
            margin = max(PIECE_MARGIN, 2 * g.piece_delta)
            worst = np.inf
            planes = []
            for i, piece in enumerate(g.pieces):
                xp = to_world(piece, orient, t)
                n, gp, ha, lb = plane_certificate(xp, s.corners)
                if gp < c + margin:
                    worst = None
                    break
                worst = min(worst, gp)
                planes.append({"piece_a": i, "piece_b": 0, "n": n.tolist(), "hi_a": ha, "lo_b": lb, "gap": gp})
            if worst is not None:
                return PairResult(pid, s.name, "G3", worst - margin, c, True, planes)
        if g.boxes_ok:
            # statics are axis-aligned boxes: certified compound boxes separate by an axis gap per box
            bx = boxes_world(g.boxes, orient, t)
            gb = np.max(np.maximum(sbox[None, :3] - bx[:, 3:], bx[:, :3] - sbox[None, 3:]), axis=1)
            if gb.min() >= c:
                return PairResult(pid, s.name, "G1", float(gb.min()), c, True, detail="certified compound boxes")
        d = self._static_exact(w, s)
        if d is not None and d >= c - G4_TOL:
            return PairResult(pid, s.name, "G4", d, c, True, detail="exact mesh distance")
        worst_gap = gap if d is None else d
        return PairResult(pid, s.name, "OVERLAP" if worst_gap < 0 else "G4", worst_gap, c, False,
                          detail=f"clearance to {s.kind} {worst_gap:.3f} mm < required {c:.3f} mm")

    def _static_exact(self, w, s: StaticItem) -> float | None:
        """Exact distance between the part mesh and a static box (FCL), with the containment trap checked."""
        import fcl
        pid, orient, t, g, _, _ = w
        lo, hi = s.corners.min(0), s.corners.max(0)
        probe = to_world(g.comp_probe, orient, t)
        if np.any(np.all((probe > lo) & (probe < hi), axis=1)):
            return -1.0                                     # a part component lies inside the keep-out
        centre = (0.5 * (lo + hi) - np.asarray(t, float)) @ ROTATIONS_F[orient]
        if ray_parity_inside(centre[None], g.v, g.f)[0] > 0.5:
            return -1.0                                     # the keep-out lies inside the part
        try:
            part = fcl.CollisionObject(g.fcl_model(), fcl.Transform(ROTATIONS_F[orient], np.asarray(t, float)))
            box = fcl.CollisionObject(fcl.Box(*(hi - lo)), fcl.Transform(0.5 * (lo + hi)))
            if fcl.collide(part, box, fcl.CollisionRequest(), fcl.CollisionResult()) > 0:
                return -1.0
            return float(fcl.distance(part, box, fcl.DistanceRequest(), fcl.DistanceResult()))
        except Exception:  # noqa: BLE001
            return None


def _manifold_gap(ga, oa, ta, gb, ob, tb, search: float):
    try:
        from ..geometry.proxies import _to_manifold
        ma = _to_manifold(to_world(ga.v, oa, ta), ga.f)        # proper rotations keep the winding
        mb = _to_manifold(to_world(gb.v, ob, tb), gb.f)
        return float(ma.min_gap(mb, search))
    except Exception:  # noqa: BLE001
        return None
