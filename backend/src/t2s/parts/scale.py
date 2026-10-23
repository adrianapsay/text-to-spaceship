"""Uniform part scaling: the V2 part-size slider (Stage 2) and the Size Study."""
from __future__ import annotations

import copy
from dataclasses import replace

PART_SCALE_MIN, PART_SCALE_MAX = 0.5, 1.0


def scale_part(rec, s: float, keep_user_mass: bool = True):
    """Copy of a part record scaled by s in all three axes about its canonical origin.

    Geometry ×s, volume ×s³, unit-density inertia ×s⁵; cover pieces scale with it (vertices ×s, cut planes
    n·x + d ≤ 0 become n·x + s·d ≤ 0), so the certified cover still covers the scaled part. Densities stay, so
    computed masses scale ×s³. A mass the user entered is kept as entered (keep_user_mass; the part-size slider)
    or scaled ×s³ (the Size Study: the same parts, built smaller).
    """
    if s == 1.0:
        return rec
    from ..geometry.proxies import COVER_DELTA
    r = copy.copy(rec)
    r.v = rec.v * s
    r.boxes = rec.boxes * s
    r.orient_bounds = rec.orient_bounds * s
    r.obb_extents_mm = rec.obb_extents_mm * s
    if rec.volume_mm3 is not None:
        r.volume_mm3 = rec.volume_mm3 * s ** 3
        r.com_can_mm = rec.com_can_mm * s
        r.j_unit_mm5 = rec.j_unit_mm5 * s ** 5
    if rec.hull_volume_mm3 is not None:
        r.hull_volume_mm3 = rec.hull_volume_mm3 * s ** 3
    if rec.mass_override_kg is not None and not keep_user_mass:
        r.mass_override_kg = rec.mass_override_kg * s ** 3
    cov = copy.copy(rec.cover)
    cov.pieces = [replace(p, planes=[(n, d * s) for n, d in p.planes], vertices=p.vertices * s,
                          hull_volume=p.hull_volume * s ** 3) for p in rec.cover.pieces]
    cov.total_hull_volume = rec.cover.total_hull_volume * s ** 3
    r.cover = cov
    r.cover_delta = getattr(rec, "cover_delta", COVER_DELTA) * max(1.0, s)
    r.part_scale = getattr(rec, "part_scale", 1.0) * s
    return r
