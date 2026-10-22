"""Layout metrics and raw objectives (protocol §F.3): L, D, I (trace + products), G; displayed quantities.

Positions mm, masses kg, inertia kg·m² (tensor convention). Every number here is computed, never assumed.
"""
from __future__ import annotations

import numpy as np

from ..collision.geom import to_world
from ..physics.assembly import PartPhys, assembly, com_box_check, inertia_metrics

ENCLOSURE_LO = np.array([-50.0, -50.0, -170.25])
ENCLOSURE_HI = np.array([50.0, 50.0, 170.25])


def part_phys(rec) -> PartPhys | None:
    if not rec.has_mass and rec.mass_override_kg is None:
        return None
    if rec.com_can_mm is None:
        return None
    return PartPhys(rec.mass_kg, rec.com_can_mm, rec.inertia_com_kgm2())


def layout_metrics(records: dict, geoms: dict, poses, z0: float = ENCLOSURE_LO[2],
                   target=(0.0, 0.0, 0.0), extras: list[tuple] = (), min_clearance: float | None = None,
                   required_clearance: float = 0.0, enclosure_volume: float | None = None) -> dict:
    tops, bottoms = [], []
    for pid, o, t in poses:
        hw = to_world(geoms[pid].hull_pts, o, np.asarray(t, float))
        tops.append(hw[:, 2].max())
        bottoms.append(hw[:, 2].min())
    phys, orients, ts, excluded = [], [], [], []
    for pid, o, t in poses:
        pp = part_phys(records[pid])
        if pp is None:
            excluded.append(pid)
            continue
        phys.append(pp)
        orients.append(o)
        ts.append(np.asarray(t, float))
    a = assembly(phys, orients, np.array(ts) if ts else np.zeros((0, 3)), list(extras)) if phys else None
    vol = sum(records[pid].volume_mm3 or 0.0 for pid, _, _ in poses)
    encl = enclosure_volume or float(np.prod(ENCLOSURE_HI - ENCLOSURE_LO))
    m = {
        "length_used_mm": float(max(tops) - z0) if tops else 0.0,
        "span_mm": float(max(tops) - min(bottoms)) if tops else 0.0,
        "space_used": float(vol / encl),
        "parts_placed": len(poses),
        "mass_excluded_parts": excluded,
    }
    if a is not None:
        im = inertia_metrics(a.inertia_kgm2)
        cb = com_box_check(a.com_mm, target)
        m.update({"mass_kg": a.mass_kg, "com_mm": a.com_mm.tolist(), "inertia_kgm2": a.inertia_kgm2.tolist(), **im, **cb})
    if min_clearance is not None:
        m["min_clearance_mm"] = float(min_clearance)
        slack = max(0.0, min_clearance - required_clearance)
        m["margin_objective"] = float(1.0 - min(1.0, slack / 5.0))
    return m


def raw_objectives(m: dict, alpha: float = 0.5) -> dict:
    """Raw objective values (minimise). I combines trace T and products P after normalisation (done elsewhere)."""
    return {"L": m["length_used_mm"], "D": m.get("com_error_mm", np.nan), "T": m.get("trace_kgm2", np.nan),
            "P": m.get("products_norm_kgm2", np.nan), "G": m.get("margin_objective", np.nan),
            "lambda_max": m.get("lambda_max_kgm2", np.nan), "kappa": m.get("kappa", np.nan)}
