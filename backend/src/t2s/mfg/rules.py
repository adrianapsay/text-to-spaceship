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
            "face_mm": (float(hi[b] - lo[b]), float(hi[c] - lo[c])), "extent_mm": float(hi[a] - lo[a])}


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


# ================================================================================================================
# V2 Stage 2: modelled brackets, part of the packing. Each bracket owns a RESERVED BOX from its target surface (wall,
# end plate, rail or PC/104 deck) to the part's mounting side, reaching `depth` mm into the part's bounding box where
# the bracket has to wrap the part. The box must keep BRACKET_CLEARANCE from every part it does not hold, from every
# other bracket's box and from every keep-out except its own target. All values below are ASSUMED.
# ================================================================================================================
BRACKET_CLEARANCE = 1.2                       # mm (U4 part-to-frame clearance)
CRADLE_DEPTH_FRAC, CRADLE_DEPTH_MAX = 0.3, 15.0   # machined cradle wraps this share of the part's depth (≤ 15 mm)
CLAMP_DEPTH_FRAC, CLAMP_DEPTH_MAX = 0.5, 15.0     # tube-clamp band
AM_DEPTH = 4.0                                # metal-AM bracket hugs the part this far into its bounding box
AM_FOOTPRINT = 0.8                            # share of the mounting-side footprint a metal-AM bracket uses
CRADLE_5AXIS = 3.0                            # relative cost surcharge: cradle machined to the part's shape
BRACKET_MIN_W = 6.0                           # mm: narrowest flange where a bracket is clipped to a rail or deck
# estimated solid share of the reserved box: (between part and target, wrap region inside the part's bounding box)
FILL = {"cradle": (0.6, 0.3), "metal_am": (0.25, 0.15)}
# v2.2: bracket-aware placement, PC/104 rods scaled with the boards, the bracket budget's metal-AM preference steps
BRACKET_MODEL_VERSION = "v2.2"                # part of the search signature: layouts decoded under other rules differ
# bracket budget step → how much more a metal-AM bracket may cost than the cheapest simple bracket that fits and
# still be chosen (am_level)
AM_FACTOR = {1: 1.0, 2: 2.0, 3: 10.0, 4: float("inf")}


def am_level(budget: float) -> int:
    """The V2 bracket budget (0–100) in steps — "0 = simple, 100 = 3D printed":
    0: simple brackets only; 1 (1–33): metal AM only where no simple bracket fits; 2 (34–66): metal AM also where
    it costs at most 2× the cheapest simple bracket that fits (it replaces machined cradles); 3 (67–99): at most 10×
    (also blocks, sheet brackets, clamps); 4 (100): metal AM wherever it fits. A part bolted straight to its wall
    (direct mount) keeps its fasteners. Steps, so that the search restarts only when the slider crosses one."""
    b = float(budget)
    return 0 if b <= 0 else 1 if b < 34 else 2 if b < 67 else 3 if b < 100 else 4


@dataclass
class BracketOption:
    kind: str                     # direct | machined | sheet | clamp | cradle | metal_am
    mount_type: str
    process: str                  # direct | machined | sheet | catalogue | metal_am
    fasteners: int
    lateral: tuple                # footprint shares of the mounting side the reserved box covers (longer, shorter side)
    depth: float                  # mm the reserved box reaches into the part's bounding box


def bracket_options(profile: dict, gap: float, am_allowed: bool) -> list[BracketOption]:
    """Bracket candidates for a part side `gap` mm from its target, cheapest first. Without metal AM (bracket
    budget 0) only simple brackets exist; with it, a metal-AM bracket is the fallback where no simple bracket fits."""
    if gap > MFG_REACH + 1e-9:
        return []
    w, h = profile["face_mm"]
    ext = float(profile.get("extent_mm", 30.0))
    out = []
    if profile["flat_share"] >= 0.6:
        if gap <= DIRECT_MAX:
            out.append(BracketOption("direct", "direct (M3 fasteners + spacer washers)", "direct", 4, (1.0, 1.0), 0.0))
        elif gap <= MACHINED_MAX:
            out.append(BracketOption("machined", "machined spacer block", "machined", 4, (0.6, 0.6), 0.0))
        else:
            out.append(BracketOption("sheet", "sheet-metal Z-bracket (2 bends)", "sheet", 4, (0.5, 0.6), 0.0))
    elif profile["symmetric"] and (profile["elongated"] or profile["curved"]) and min(w, h) > 0 \
            and max(w, h) / min(w, h) > 1.3:
        out.append(BracketOption("clamp", "tube clamp" + (" on a sheet bracket" if gap > MACHINED_MAX else ""),
                                 "catalogue", 2, (0.35, 0.9), min(CLAMP_DEPTH_MAX, CLAMP_DEPTH_FRAC * ext)))
    else:
        out.append(BracketOption("cradle", "machined cradle (follows the part, 5-axis)", "machined", 4, (1.0, 1.0),
                                 min(CRADLE_DEPTH_MAX, CRADLE_DEPTH_FRAC * ext)))
    if am_allowed:
        out.append(BracketOption("metal_am", "conformal metal-AM bracket", "metal_am", 3, (AM_FOOTPRINT, AM_FOOTPRINT),
                                 AM_DEPTH))
    return out


def estimate_cradle_am(kind: str, reserve: np.ndarray, ax: int, gap_len: float, wrap_len: float, density: float):
    """Mass (kg), COM (mm), inertia about the COM (kg m²) and solid volume (cm³) ESTIMATES for a cradle or metal-AM
    bracket from its reserved box: `gap_len` mm between target and part side, `wrap_len` mm around the part (the
    designed solid replaces these once generated)."""
    r = np.asarray(reserve, float)
    ext = r[3:] - r[:3]
    lat = ext[[k for k in range(3) if k != ax]].prod()
    fg, fw = FILL[kind]
    vol = lat * (fg * gap_len + fw * wrap_len)                     # mm³
    m = density * vol * 1e-9
    com = 0.5 * (r[:3] + r[3:])
    inertia = m / 12 * np.diag([ext[1] ** 2 + ext[2] ** 2, ext[0] ** 2 + ext[2] ** 2, ext[0] ** 2 + ext[1] ** 2]) * 1e-6
    return float(m), com, inertia, vol / 1e3


def bracket_estimate(kind: str, reserve, ax: int, gap: float, depth: float, fasteners: int) -> tuple[float, float]:
    """Relative cost and solid volume (cm³) of a bracket from its reserved box, before its solid exists: a machined
    block fills the box between target and part; a cradle or metal-AM bracket fills the FILL shares."""
    r = np.asarray(reserve, float)
    ext = r[3:] - r[:3]
    lat = float(np.prod([ext[k] for k in range(3) if k != ax]))
    if kind == "machined":
        vol = lat * gap / 1e3
    elif kind in FILL:
        fg, fw = FILL[kind]
        vol = lat * (fg * gap + fw * depth) / 1e3
    else:
        vol = 0.0
    return bracket_cost(kind, gap, vol, fasteners), vol


def bracket_cost(kind: str, gap: float, solid_cm3: float, fasteners: int) -> float:
    if kind == "direct":
        return fasteners * COST["fastener"]
    if kind == "machined":
        return COST["machined"] + COST["machined_per_cm3"] * solid_cm3 + fasteners * COST["fastener"]
    if kind == "sheet":
        return COST["sheet"] + 2 * COST["sheet_per_bend"] + fasteners * COST["fastener"]
    if kind == "clamp":
        extra = COST["sheet"] + 2 * COST["sheet_per_bend"] if gap > MACHINED_MAX else 0.0
        return COST["catalogue"] + extra + fasteners * COST["fastener"]
    if kind == "cradle":
        return COST["machined"] + CRADLE_5AXIS + COST["machined_per_cm3"] * solid_cm3 + fasteners * COST["fastener"]
    return COST["metal_am"] + COST["metal_am_per_cm3"] * solid_cm3 + COST["metal_am_support"] + fasteners * COST["fastener"]
