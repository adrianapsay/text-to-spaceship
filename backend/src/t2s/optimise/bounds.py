"""Lower bounds on the used length L (protocol §F.9). Each bound states what it is valid for."""
import numpy as np


def lower_bounds(records: list, cross_section_mm2: float | None = None, z_cap: float | None = None,
                 width_mm: float | None = None) -> list[dict]:
    """Defaults: the active form factor's envelope (3U 100 × 100 × 340.5 mm)."""
    from ..core.formfactor import ENVELOPE
    cross_section_mm2 = float(ENVELOPE[0] * ENVELOPE[1]) if cross_section_mm2 is None else cross_section_mm2
    z_cap = float(ENVELOPE[2]) if z_cap is None else z_cap
    solid = sum(r.volume_mm3 or 0.0 for r in records)
    boxes = sum(float(np.prod(r.boxes[:, 3:] - r.boxes[:, :3], axis=1).sum()) for r in records)
    hulls = sum(r.hull_volume_mm3 or 0.0 for r in records)
    mins = [float(np.min(r.obb_extents_mm)) for r in records]
    out = [
        {"name": "solid volume", "value_mm": solid / cross_section_mm2, "valid_for": "true geometry",
         "why": f"the parts' solid volume {solid / 1e3:.1f} cm³ cannot fit in less than volume ÷ cross-section"},
        {"name": "largest smallest-dimension", "value_mm": max(mins), "valid_for": "true geometry",
         "why": "every part spans at least its smallest extent along Z, whichever way it is turned"},
        {"name": "convex-hull volume", "value_mm": hulls / cross_section_mm2, "valid_for": "hull proxies only",
         "why": "valid only if every part were packed as its convex hull"},
        {"name": "compound-box volume", "value_mm": boxes / cross_section_mm2, "valid_for": "box proxies only",
         "why": "valid only for the box-proxy problem the decoder solves"},
    ]
    # clique bound (box proxies): parts whose smallest dimensions pairwise sum to more than the widest side of the
    # cross-section cannot share a Z slab (3U: 100 mm)
    width = float(max(ENVELOPE[:2])) if width_mm is None else width_mm
    order = np.argsort(mins)[::-1]
    clique = []
    for i in order:
        if all(mins[i] + mins[j] > width for j in clique):
            clique.append(i)
    if len(clique) >= 2:
        out.append({"name": "clique of large parts", "value_mm": float(sum(mins[i] for i in clique)),
                    "valid_for": "box proxies only",
                    "why": f"{len(clique)} parts each too wide to share a Z slab with another as boxes"})
    for b in out:
        b["fits_cubesat"] = b["value_mm"] <= z_cap
    return out
