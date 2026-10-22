"""Free-rotation experiment (Stage 1, research): reported separately, never used by the main search.

Recorded deviation from the protocol (quasi-phi penalty with L-BFGS-B and CMA-ES restarts): a greedy rotate-and-drop
local search. It starts from the shortest validated axis-aligned Stage 1 layout and, for the parts that set the used
length, proposes arbitrary rotations (random axis and angle, turns about the vertical axis, occasional uniformly
random orientations) with small lateral shifts, drops the part to the lowest valid height and keeps the move only if
the part's top comes down. Every pose it keeps passes an exact check on the meshes:
  - envelope: every convex-hull vertex inside the 3U envelope (exact, the envelope is convex);
  - every nearby pair: no FCL mesh-mesh intersection, FCL distance ≥ GAP, and the containment trap (one vertex per
    connected component of each part must not lie inside the other, ray parity).
The final layout is re-checked on every pair from scratch.
"""
from __future__ import annotations

import json
import pickle
import time
from pathlib import Path

import numpy as np

from ..core.fileio import atomic_write_text
from ..core.rotations import ROTATIONS_F
from ..geometry.mesh import ray_parity_inside
from ..objectives.metrics import ENCLOSURE_HI, ENCLOSURE_LO

GAP = 0.001          # mm between parts (Stage 1 has no clearance rule; 1 µm above floating-point noise)
LABEL = "Free-rotation experiment (Stage 1, research) — reported separately, not used by the main search"
METHOD = ("greedy rotate-and-drop local search from the shortest validated axis-aligned layout, every kept pose "
          "checked exactly on the meshes (FCL + containment trap); deviation: the protocol's quasi-phi / L-BFGS-B / "
          "CMA-ES method is not implemented")


def _rot(axis, angle: float) -> np.ndarray:
    from scipy.spatial.transform import Rotation
    a = np.asarray(axis, float)
    return Rotation.from_rotvec(a / np.linalg.norm(a) * angle).as_matrix()


def angle_from_axis_aligned(R: np.ndarray) -> float:
    """Smallest rotation angle (degrees) from R to any of the 24 axis-aligned orientations."""
    best = 180.0
    for Q in ROTATIONS_F:
        c = (np.trace(R @ Q.T) - 1.0) / 2.0
        best = min(best, float(np.degrees(np.arccos(np.clip(c, -1.0, 1.0)))))
    return best


class Scene:
    """Poses (R, t) of every part with world-frame hull boxes, and the exact checks."""

    def __init__(self, geoms: dict, poses: dict):
        self.g = geoms
        self.R = {p: np.asarray(R, float) for p, (R, _) in poses.items()}
        self.t = {p: np.asarray(t, float) for p, (_, t) in poses.items()}
        self.box = {p: self._box(p, self.R[p], self.t[p]) for p in poses}
        self.checks = 0

    def _hull(self, pid, R, t):
        return self.g[pid].hull_pts @ R.T + t

    def _box(self, pid, R, t):
        h = self._hull(pid, R, t)
        return h.min(0), h.max(0)

    def top(self, pid) -> float:
        return float(self.box[pid][1][2])

    def length(self) -> float:
        return max(self.top(p) for p in self.R) - float(ENCLOSURE_LO[2])

    def pair_ok(self, a, Ra, ta, b, Rb, tb) -> tuple[bool, float]:
        import fcl
        self.checks += 1
        ga, gb = self.g[a], self.g[b]
        oa = fcl.CollisionObject(ga.fcl_model(), fcl.Transform(Ra, ta))
        ob = fcl.CollisionObject(gb.fcl_model(), fcl.Transform(Rb, tb))
        if fcl.collide(oa, ob, fcl.CollisionRequest(), fcl.CollisionResult()) > 0:
            return False, -1.0
        d = float(fcl.distance(oa, ob, fcl.DistanceRequest(), fcl.DistanceResult()))
        if d < GAP:
            return False, d
        va = ga.comp_probe @ Ra.T + ta
        vb = gb.comp_probe @ Rb.T + tb
        if (ray_parity_inside((va - tb) @ Rb, gb.v, gb.f) > 0.5).any() or \
                (ray_parity_inside((vb - ta) @ Ra, ga.v, ga.f) > 0.5).any():
            return False, -1.0
        return True, d

    def part_ok(self, pid, R, t) -> bool:
        lo, hi = self._box(pid, R, t)
        if np.any(lo < ENCLOSURE_LO - 1e-9) or np.any(hi > ENCLOSURE_HI + 1e-9):
            return False
        for q in self.R:
            if q == pid:
                continue
            qlo, qhi = self.box[q]
            if float(np.max(np.maximum(qlo - hi, lo - qhi))) > GAP:
                continue                     # hull boxes apart: the meshes are too
            if not self.pair_ok(pid, R, t, q, self.R[q], self.t[q])[0]:
                return False
        return True

    def set(self, pid, R, t) -> None:
        self.R[pid], self.t[pid] = R, t
        self.box[pid] = self._box(pid, R, t)

    def drop(self, pid, R, t) -> np.ndarray | None:
        """Lowest valid height below t (coarse descent, then halving steps); None if t itself is not valid."""
        if not self.part_ok(pid, R, t):
            return None
        floor = t[2] + float(ENCLOSURE_LO[2]) - float(self._box(pid, R, t)[0][2])
        z, step = float(t[2]), 4.0
        while step >= 0.05:
            zt = max(floor, z - step)
            if zt < z - 1e-9 and self.part_ok(pid, R, np.array([t[0], t[1], zt])):
                z = zt
            else:
                step /= 2.0
        return np.array([t[0], t[1], z])

    def full_check(self) -> tuple[bool, float]:
        ids = list(self.R)
        worst = np.inf
        for i, a in enumerate(ids):
            lo, hi = self.box[a]
            if np.any(lo < ENCLOSURE_LO - 1e-9) or np.any(hi > ENCLOSURE_HI + 1e-9):
                return False, -1.0
            for b in ids[i + 1:]:
                qlo, qhi = self.box[b]
                if float(np.max(np.maximum(qlo - hi, lo - qhi))) > GAP:
                    continue
                ok, d = self.pair_ok(a, self.R[a], self.t[a], b, self.R[b], self.t[b])
                if not ok:
                    return False, d
                worst = min(worst, d)
        return True, worst


def _propose(scene: Scene, pid, rng) -> tuple[np.ndarray, np.ndarray] | None:
    """A rotated, shifted pose of `pid` (turned about its hull-box centre), lifted until valid, then dropped."""
    R, t = scene.R[pid], scene.t[pid]
    lo, hi = scene.box[pid]
    c = 0.5 * (lo + hi)
    u = rng.random()
    if u < 0.45:
        Q = _rot(rng.normal(size=3), np.radians(rng.normal(0.0, 12.0)))
    elif u < 0.85:
        Q = _rot([0.0, 0.0, 1.0], np.radians(rng.uniform(-45.0, 45.0)))
    else:
        from scipy.spatial.transform import Rotation
        Q = Rotation.random(random_state=int(rng.integers(1 << 31))).as_matrix()
    R2 = Q @ R
    t2 = Q @ (t - c) + c
    t2[:2] += rng.normal(0.0, 2.0, size=2)
    blo, bhi = scene._box(pid, R2, t2)
    for k in range(2):                              # pull the part back inside the envelope sideways
        if bhi[k] - blo[k] > ENCLOSURE_HI[k] - ENCLOSURE_LO[k]:
            return None
        t2[k] += max(0.0, ENCLOSURE_LO[k] - blo[k]) - max(0.0, bhi[k] - ENCLOSURE_HI[k])
    if blo[2] < ENCLOSURE_LO[2]:
        t2[2] += ENCLOSURE_LO[2] - blo[2]
    limit = scene.top(pid)                          # lifting the top above its current height gains nothing
    for _ in range(12):
        if scene.part_ok(pid, R2, t2):
            break
        t2[2] += 2.0
        if scene._box(pid, R2, t2)[1][2] >= limit:
            return None
    else:
        return None
    t3 = scene.drop(pid, R2, t2)
    return None if t3 is None else (R2, t3)


def run_free_rotation(geoms: dict, start_poses, budget_s: float = 120.0, seed: int = 20261022,
                      proposals: int = 12) -> dict:
    """start_poses: [(part_id, orient, t_mm)] of a validated axis-aligned Stage 1 layout."""
    t0 = time.perf_counter()
    rng = np.random.default_rng(seed)
    scene = Scene(geoms, {p: (ROTATIONS_F[o], np.asarray(t, float)) for p, o, t in start_poses})
    L0 = scene.length()
    ok0, _ = scene.full_check()
    accepted, rounds, stuck = 0, 0, set()
    history = [(0.0, L0)]
    while time.perf_counter() - t0 < budget_s:
        rounds += 1
        L = scene.length() + float(ENCLOSURE_LO[2])
        # the parts that set the length first, then the ones just below them (to make room)
        near = sorted((p for p in scene.R if scene.top(p) >= L - 25.0), key=lambda p: -scene.top(p))
        cand = [p for p in near if p not in stuck] or near
        if not cand:
            break
        pid = cand[0] if rng.random() < 0.6 else cand[int(rng.integers(len(cand)))]
        best = None
        for _ in range(proposals):
            if time.perf_counter() - t0 >= budget_s:
                break
            r = _propose(scene, pid, rng)
            if r is None:
                continue
            top = float(scene._box(pid, *r)[1][2])
            if best is None or top < best[0]:
                best = (top, r)
        if best is not None and best[0] < scene.top(pid) - 0.01:
            scene.set(pid, *best[1])
            accepted += 1
            stuck.discard(pid)
            history.append((time.perf_counter() - t0, scene.length()))
        else:
            stuck.add(pid)
            if stuck >= set(near):
                stuck.clear()                       # every candidate tried: start over with new random moves
    valid, dmin = scene.full_check()
    L1 = scene.length()
    rotated = []
    for p, o, _ in start_poses:
        a = angle_from_axis_aligned(scene.R[p])
        if a > 0.01:
            rotated.append({"part_id": p, "angle_deg": a})
    return {
        "status": "DONE", "label": LABEL, "method": METHOD, "seed": seed, "budget_s": budget_s,
        "seconds": time.perf_counter() - t0, "rounds": rounds, "accepted_moves": accepted, "exact_checks": scene.checks,
        "start_valid": bool(ok0), "start_length_mm": L0, "length_used_mm": L1 if valid else None,
        "improvement_mm": (L0 - L1) if valid else None, "valid": bool(valid),
        "min_distance_mm": None if not np.isfinite(dmin) else dmin, "gap_mm": GAP,
        "rotated": rotated, "history": [{"t_s": a, "length_mm": b} for a, b in history],
        "poses": [{"part_id": p, "R": scene.R[p].tolist(), "t_mm": scene.t[p].tolist()} for p, _, _ in start_poses],
    }


def free_rotation_job(records_path: str, start_poses, start_id: str, out_path: str, budget_s: float, seed: int) -> str:
    from ..collision.geom import part_geom_from_record
    records = pickle.loads(Path(records_path).read_bytes())
    geoms = {p: part_geom_from_record(records[p]) for p, _, _ in start_poses}
    atomic_write_text(out_path, json.dumps({"status": "RUNNING", "start_layout_id": start_id}))
    res = run_free_rotation(geoms, start_poses, budget_s, seed)
    res["start_layout_id"] = start_id
    for r in res["rotated"]:
        r["name"] = records[r["part_id"]].name
    atomic_write_text(out_path, json.dumps(res, indent=1, default=float))
    return out_path
