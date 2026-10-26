"""CubeSat sizes and how components fit (conceptual).

The outer envelope of each size is the CubeSat Design Specification's rail envelope (refs.CDS_SIZE_MM). The inner
space is V2's frame model (core/formfactor.py, constraints/stage2.py): 2 mm walls and four 8.5 mm square corner rails,
applied to every size (ASSUMED there, and here). A component's bounding box
* "fits" when it fits the inner space in some axis-aligned orientation,
* "tight" when it fits only the outer rail envelope (a structure with thinner walls, or an opening, is needed),
* "too_big" otherwise.
The corner rails are left out of that comparison (PC/104 boards are notched around them by their standard). The
optimiser keeps 1.2 mm from every wall and rail (V2's rule), which `packing_fit` applies.
"""
from __future__ import annotations

import itertools
import re

from . import refs as R
from .calc import calc, inp

SIZES = (1, 1.5, 2, 3, 6, 12)
PACKED_SIZES = (3, 6, 12)                 # the sizes V2's optimiser packs
WALL = 2.0                                # mm, V2 frame model (constraints/stage2.py, ASSUMED)
RAIL = 8.5                                # mm, CDS rail width (V2 frame model)
C_WALL = 1.2                              # mm, V2's part-to-wall clearance
FILL_MAX = 0.70                           # largest share of the usable volume the components may fill (ASSUMED)
PACK_SLACK = 0.01                         # mm: the optimiser keeps parts strictly inside (its boxes are inflated a
                                          # hair, geometry.proxies): a side equal to the room never fits
_PC104 = re.compile(r"pc\s*[-/]?\s*104", re.IGNORECASE)


def label(size) -> str:
    return f"{size:g}U"


def outer(size) -> tuple:
    return tuple(R.CDS_SIZE_MM[size])


def inner(size) -> tuple:
    return tuple(d - 2.0 * WALL for d in outer(size))


def usable_volume_cm3(size) -> float:
    """Inner box less the rails inside the walls (the rails run along the long axis)."""
    a, b, c = inner(size)
    rails = 4.0 * (RAIL - WALL) ** 2 * c
    return (a * b * c - rails) / 1000.0


def is_pc104(c: dict) -> bool:
    return bool(_PC104.search(str(c.get("fits") or "")))


def fit(dims: tuple | None, size) -> str | None:
    """"fits", "tight" or "too_big" for a bounding box (mm); None when its dimensions are not published."""
    if dims is None:
        return None
    perms = set(itertools.permutations(dims))

    def inside(box):
        return any(all(p[i] <= box[i] + 1e-9 for i in range(3)) for p in perms)
    if inside(inner(size)):
        return "fits"
    if inside(outer(size)):
        return "tight"
    return "too_big"


def packing_fit(dims: tuple | None, size) -> str | None:
    """Where V2's optimiser can place this bounding box: "stage2" — its engineering stage too (the frame model: 1.2 mm
    from every wall; corner rails kept out unless one cross-section side stays clear of them); "stage1" — only its
    idealized stage (the rail envelope); "too_big". None: unknown size, or not a size the optimiser packs."""
    if dims is None or size not in PACKED_SIZES:
        return None
    a, b, c = inner(size)
    room = (a - 2 * C_WALL, b - 2 * C_WALL, c - 2 * C_WALL)
    clear = 2 * (RAIL - WALL + C_WALL)                    # a side this much shorter than the room clears the rails
    perms = set(itertools.permutations(dims))
    for p in perms:
        if all(p[i] <= room[i] - PACK_SLACK for i in range(3)) and \
                (p[0] <= room[0] - clear or p[1] <= room[1] - clear):
            return "stage2"
    o = outer(size)
    if any(all(p[i] <= o[i] - PACK_SLACK for i in range(3)) for p in perms):
        return "stage1"
    return "too_big"


def structure_calcs(ctx: dict) -> dict:
    """ctx: size_u, mass_kg (total), volume_cm3 (components inside), largest (name, dims, fit)."""
    out = {}
    size = ctx["size_u"]
    limit = R.CDS_MASS_KG[size]
    m = ctx["mass_kg"]
    out["structure.mass"] = calc(
        "structure.mass", "Total mass against the CubeSat limit", m, "kg", "Σ components + structure + allowances",
        {"limit": inp(limit, "kg", f"CubeSat Design Specification Rev 14.1, {label(size)}")}, refs=["cds"],
        extra={"limit_kg": limit, "ok": m <= limit},
        explain=(f"Within the {limit:g} kg limit for a {label(size)} CubeSat." if m <= limit else
                 f"Over the {limit:g} kg limit for a {label(size)} CubeSat."))
    v_use = usable_volume_cm3(size)
    fill = ctx["volume_cm3"] / v_use
    out["structure.volume"] = calc(
        "structure.volume", "Share of the inner volume used", 100.0 * fill, "%", "fill = Σ V_box / V_usable",
        {"components": inp(ctx["volume_cm3"], "cm³", "bounding boxes of the internal components"),
         "usable": inp(v_use, "cm³", f"{label(size)}: inner box of the frame model less its corner rails")},
        [(f"2 mm walls and 8.5 mm corner rails (V2 frame model, ASSUMED); at most {FILL_MAX:.0%} filled to leave "
          "room for harness, brackets and access (ASSUMED)")], refs=["cds", "nasa_soa_struct"],
        extra={"usable_cm3": v_use, "fill_max": FILL_MAX, "ok": fill <= FILL_MAX})
    return out


def area_m2(size) -> dict:
    """Face areas (m²) of the outer envelope: the end face and the largest side face."""
    a, b, c = (d / 1000.0 for d in outer(size))
    return {"end": a * b, "side": max(a, b) * c, "side_small": min(a, b) * c, "total": 2 * (a * b + a * c + b * c),
            "mean_drag": (a * b + a * c + b * c) / 2.0}


def mean_cross_section_m2(size, deploy_m2: float = 0.0) -> float:
    """Mean projected area of a randomly oriented convex body = surface area / 4 (Cauchy), plus deployables at half
    their one-side area (ASSUMED average orientation)."""
    return area_m2(size)["total"] / 4.0 + 0.5 * deploy_m2


def size_note(size) -> str:
    o = outer(size)
    return f"{label(size)} ({o[0]:g} × {o[1]:g} × {o[2]:g} mm)"
