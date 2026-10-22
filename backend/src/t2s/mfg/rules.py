"""Mount-type rules and the relative cost model (Addendum 1.5; decisions N1 relative units, N2 AlSi10Mg).

Everything here is ASSUMED and labelled in the app: "manufacturing concept — assumed cost model, not a quote;
brackets not stress-analysed".
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

COST = {"fastener": 0.1, "catalogue": 1.0, "sheet": 3.0, "sheet_per_bend": 0.5, "machined": 5.0,
        "machined_per_cm3": 0.5, "metal_am": 10.0, "metal_am_per_cm3": 2.0, "metal_am_support": 1.0}
MATERIAL = {"metal_am": ("AlSi10Mg (ASSUMED)", 2670.0), "sheet": ("aluminium sheet 1.5 mm (ASSUMED)", 2680.0),
            "machined": ("aluminium 6061 (ASSUMED)", 2700.0), "catalogue": ("aluminium / steel (ASSUMED)", None),
            "direct": ("M3 fasteners", None), "standoff": ("aluminium (ASSUMED)", 2700.0)}
FASTENER_MASS_KG = 0.0012        # M3 × 8 steel screw with washer (ASSUMED)
MFG_REACH = 40.0                 # brackets may bridge up to this gap between a part side and its target (ASSUMED)
DIRECT_MAX = 3.5                 # mm: the 3 mm layer itself (spacer washers) — anything larger needs a bracket
MACHINED_MAX = 15.0
CLAMP_MASS_KG = 0.015            # generic tube clamp (ASSUMED)
SPACER_SET_MASS_KG = 0.006       # 4 PC/104 spacers per board (ASSUMED)


@dataclass
class MountChoice:
    mount_type: str              # direct | machined block | sheet Z-bracket | tube clamp | metal AM bracket | ...
    process: str                 # direct | machined | sheet | catalogue | metal_am | standoff
    fasteners: int
    cost_est: float              # relative cost estimate (search objective C); final cost from the real geometry
    reason: str


def face_profile(rec, a: int, sgn: int = -1) -> dict:
    """How flat the part's mounting side (canonical face `sgn·a`) is: share of that face rectangle covered by
    triangles lying in the face plane with the outward normal."""
    v, f = rec.v, rec.f
    lo, hi = v.min(0), v.max(0)
    tri = v[f]
    n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    area2 = np.linalg.norm(n, axis=1)
    ok = area2 > 0
    nn = np.zeros_like(n)
    nn[ok] = n[ok] / area2[ok, None]
    cen = tri.mean(axis=1)
    plane = lo[a] if sgn < 0 else hi[a]
    in_plane = (np.abs(cen[:, a] - plane) < 0.25) & (nn[:, a] * sgn > 0.99)
    b, c = [k for k in range(3) if k != a]
    rect = (hi[b] - lo[b]) * (hi[c] - lo[c])
    flat = float(0.5 * area2[in_plane].sum() / rect) if rect > 0 else 0.0
    d = rec.desc or {}
    return {"flat_share": min(1.0, flat), "symmetric": bool(d.get("symmetric")),
            "elongated": "elongated" in rec.labels, "curved": "curved" in rec.labels,
            "face_mm": (float(hi[b] - lo[b]), float(hi[c] - lo[c]))}


def choose_mount(profile: dict, gap: float) -> MountChoice | None:
    """gap: distance from the part's mounting side to its target surface (mm). None if beyond reach."""
    if gap > MFG_REACH + 1e-9:
        return None
    w, h = profile["face_mm"]
    if profile["flat_share"] >= 0.6:
        if gap <= DIRECT_MAX:
            return MountChoice("direct (fasteners + spacer washers)", "direct", 4, 4 * COST["fastener"],
                               f"flat mounting side ({100 * profile['flat_share']:.0f} % planar) within {gap:.1f} mm")
        if gap <= MACHINED_MAX:
            vol = 0.6 * w * h * gap / 1e3
            return MountChoice("machined spacer block", "machined", 4,
                               COST["machined"] + COST["machined_per_cm3"] * vol + 4 * COST["fastener"],
                               f"flat side, short stiff offset {gap:.1f} mm")
        return MountChoice("sheet-metal Z-bracket (2 bends)", "sheet", 4,
                           COST["sheet"] + 2 * COST["sheet_per_bend"] + 4 * COST["fastener"],
                           f"flat side, medium offset {gap:.1f} mm")
    if profile["symmetric"] and (profile["elongated"] or profile["curved"]) and profile["flat_share"] < 0.6 and \
            min(w, h) > 0 and max(w, h) / min(w, h) > 1.3:
        extra = COST["sheet"] + 2 * COST["sheet_per_bend"] if gap > MACHINED_MAX else 0.0
        return MountChoice("tube clamp" + (" on a sheet bracket" if extra else ""), "catalogue", 2,
                           COST["catalogue"] + extra + 2 * COST["fastener"], f"cylindrical body, offset {gap:.1f} mm")
    # curved or irregular contact: conformal metal-AM bracket (volume estimated from the envelope)
    vol = 0.25 * w * h * min(gap + 5.0, 20.0) / 1e3
    return MountChoice("conformal metal-AM bracket", "metal_am", 3,
                       COST["metal_am"] + COST["metal_am_per_cm3"] * vol + COST["metal_am_support"] + 3 * COST["fastener"],
                       f"curved/irregular contact ({100 * profile['flat_share']:.0f} % planar), offset {gap:.1f} mm")
