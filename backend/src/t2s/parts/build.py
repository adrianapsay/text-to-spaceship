"""Part pipeline: STL bytes -> validated, repaired, analysed part with mass properties and proxies (§B, §C, §E)."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

import numpy as np

from ..core.rotations import ROTATIONS_F
from ..geometry import classify, mesh as meshmod
from ..geometry.canonical import choose_frame
from ..geometry.hull_obb import HullInfo, convex_hull, min_obb
from ..geometry.proxies import Cover, certify_boxes, compound_boxes, planar_cut_cover
from ..geometry.stl_io import UNIT_TO_MM, read_stl_bytes
from ..massprops import core as mp
from ..massprops.ref import unit_mass_props_ref

PIPELINE_VERSION = "1.0"
DEFAULT_DENSITY = 2700.0


@dataclass
class PartRecord:
    id: str
    name: str
    file: str
    sha256: str
    units: str
    units_confirmed: bool
    status: str                       # VALID | REPAIRED | WITHHELD | NEEDS_UNITS
    status_detail: str
    repairs: list[str]
    triangles_in: int
    v: np.ndarray                     # canonical-frame vertices (mm)
    f: np.ndarray
    frame_name: str
    r_auth_to_can: np.ndarray         # canonical axes as columns, in authored coordinates
    origin_auth: np.ndarray           # canonical origin in authored coordinates (mm)
    topology: meshmod.Topology
    volume_mm3: float | None
    com_can_mm: np.ndarray | None
    j_unit_mm5: np.ndarray | None     # unit-density inertia about COM, canonical frame
    ref_check: dict
    hull: HullInfo | None
    hull_volume_mm3: float | None
    obb_extents_mm: np.ndarray
    desc: dict
    labels: list[str]
    subsystem: str
    boxes: np.ndarray                 # G1 compound boxes (m, 6), canonical frame
    boxes_method: str
    boxes_certified: bool
    boxes_detail: str
    cover: Cover
    allowed_orients: list[int]
    orient_bounds: np.ndarray         # (24, 6) AABB [min, max] of R_k v (canonical origin), mm
    density_kg_m3: float = DEFAULT_DENSITY
    mass_override_kg: float | None = None
    mass_source: str = "ASSUMED"
    locked: bool = False
    lock_pose: dict | None = None
    tags: list[str] = field(default_factory=list)
    suggested_units: str | None = None

    # ------------------------------------------------------------------ physics accessors
    @property
    def has_mass(self) -> bool:
        return self.volume_mm3 is not None and self.status != "WITHHELD"

    @property
    def mass_kg(self) -> float | None:
        if not self.has_mass:
            return self.mass_override_kg
        if self.mass_override_kg is not None:
            return self.mass_override_kg
        return self.volume_mm3 * 1e-9 * self.density_kg_m3

    @property
    def effective_density(self) -> float | None:
        if not self.has_mass:
            return None
        return self.mass_kg / (self.volume_mm3 * 1e-9)

    def inertia_com_kgm2(self) -> np.ndarray | None:
        """Inertia about the part COM in the canonical frame: m * (J/V) mm^2 -> kg m^2."""
        if not self.has_mass:
            return None
        return self.mass_kg * (self.j_unit_mm5 / self.volume_mm3) * 1e-6


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def suggest_units(raw_extent_max: float) -> str:
    """Suggest the unit whose interpretation gives a plausible CubeSat part size (5 to 340.5 mm)."""
    for unit in ("mm", "in", "cm", "m"):
        e = raw_extent_max * UNIT_TO_MM[unit]
        if 5.0 <= e <= 340.5:
            return unit
    return "mm"


def _orient_tables(v: np.ndarray, hull: HullInfo | None):
    pts = v[hull.vertex_ids] if hull is not None else v
    bounds = np.zeros((24, 6))
    keys = {}
    allowed = []
    rounded = np.round(v, 4)          # 0.1 µm: symmetric within float32 noise counts as symmetric
    for k, r in enumerate(ROTATIONS_F):
        q = pts @ r.T
        bounds[k, :3] = q.min(axis=0)
        bounds[k, 3:] = q.max(axis=0)
        rv = np.round(rounded @ r.T, 4) + 0.0
        key = hashlib.sha1(np.ascontiguousarray(rv[np.lexsort(rv.T[::-1])]).tobytes()).hexdigest()
        if key not in keys:
            keys[key] = k
            allowed.append(k)
    return allowed, bounds


def build_part(data: bytes, name: str, part_id: str, units: str = "mm", units_confirmed: bool = True,
               file: str | None = None) -> PartRecord:
    sha = sha256_bytes(data)
    tri, _fmt = read_stl_bytes(data)
    raw_ext = float(np.max(tri.reshape(-1, 3).max(axis=0) - tri.reshape(-1, 3).min(axis=0)))
    suggested = suggest_units(raw_ext)
    tri = tri * UNIT_TO_MM[units]
    v_auth, f = meshmod.weld(tri)
    rep = meshmod.repair(v_auth, f)
    v_auth, f = rep.vertices, rep.faces
    status = rep.status
    topo = meshmod.topology(v_auth, f)
    hull = convex_hull(v_auth)
    unit_props = None
    principal_axes = np.eye(3)
    principal_ok = False
    if status != "WITHHELD":
        try:
            unit_props = mp.integrate(v_auth, f)
            w, axes, degenerate = mp.principal(unit_props.j_mm5)
            principal_axes, principal_ok = axes, not degenerate
        except ValueError as exc:
            status, rep.detail = "WITHHELD", f"mass properties unavailable: {exc}"
    obb_ext, obb_axes, _ = min_obb(v_auth, hull, principal_axes if principal_ok else None)
    frame_name, r, origin, _scores = choose_frame(v_auth, f, hull, obb_axes, principal_axes, principal_ok)
    v = (v_auth - origin) @ r
    hull_c = convex_hull(v)
    volume = com = j = None
    ref = {}
    if status != "WITHHELD":
        up = mp.integrate(v, f)
        volume, com, j = up.volume_mm3, up.com_mm, up.j_mm5
        rv, rc, rj = unit_mass_props_ref(v, f)
        scale = max(np.abs(j).max(), 1e-300)
        ref = {"volume_rel": abs(rv - volume) / volume,
               "com_mm": float(np.linalg.norm(rc - com)),
               "inertia_rel": float(np.abs(rj - j).max() / scale)}
        ref["agree"] = ref["volume_rel"] < 1e-9 and ref["com_mm"] < 1e-6 * max(1.0, float(np.abs(v).max())) \
            and ref["inertia_rel"] < 1e-8
    hull_vol = hull_c.volume if hull_c is not None else None
    if volume is not None:
        w = np.linalg.eigvalsh(j)
        d = classify.descriptors(v, f, volume, hull_vol or volume, np.sort(v.max(0) - v.min(0))[::-1] if frame_name
                                 else obb_ext, w, topo.genus_total, topo.components)
        d["obb_fill"] = float(volume / np.prod(obb_ext)) if np.prod(obb_ext) > 0 else None
        lab = classify.labels(d)
    else:
        d = {"components": topo.components}
        lab = ["mass properties withheld"]
    if volume is not None:
        boxes, method = compound_boxes(v, f)
        ok, detail = certify_boxes(v, f, boxes)
        axis_hint = None
        if (topo.genus_total or 0) > 0:
            wv, vecs = np.linalg.eigh(j)
            gaps = [abs(wv[1] - wv[0]), abs(wv[2] - wv[1])]
            axis_hint = vecs[:, 2] if gaps[0] < gaps[1] else vecs[:, 0]
        from ..geometry.proxies import is_rectilinear
        rect = is_rectilinear(v, f)
        hull_exact = (hull_vol or 0) - volume <= 1e-6 * volume        # float32 noise on rotated parts ~1e-8
        if not hull_exact and (rect or (hull_vol or 0) > volume * 1.02):
            # rectilinear parts are cut until exact (e.g. PCB notches must stay open); others to <= 2 % overhead
            cover = planar_cut_cover(v, f, volume, axis_hint=axis_hint,
                                     target_overhead=1e-9 if rect else 0.02)
        else:
            cover = Cover(certified=True, detail="single convex hull")
            from ..geometry.proxies import CoverPiece
            cover.pieces.append(CoverPiece(planes=[], vertices=v[hull_c.vertex_ids], hull_volume=hull_vol))
            cover.total_hull_volume = hull_vol
    else:
        boxes = np.concatenate([v.min(0), v.max(0)])[None]
        method, ok, detail = "envelope-aabb", True, "AABB envelope of a withheld part"
        cover = Cover(certified=hull_c is not None, detail="convex-hull envelope (withheld part)")
        if hull_c is not None:
            from ..geometry.proxies import CoverPiece
            cover.pieces.append(CoverPiece(planes=[], vertices=v[hull_c.vertex_ids], hull_volume=hull_vol))
            cover.total_hull_volume = hull_vol
    allowed, bounds = _orient_tables(v, hull_c)
    if not units_confirmed:
        status_out, detail_out = "NEEDS_UNITS", f"confirm units (suggested: {suggested}); " + rep.detail
    else:
        status_out, detail_out = status, rep.detail
    return PartRecord(
        id=part_id, name=name, file=file or f"{name}.stl", sha256=sha, units=units, units_confirmed=units_confirmed,
        status=status_out, status_detail=detail_out, repairs=rep.repairs, triangles_in=len(tri), v=v, f=f,
        frame_name=frame_name, r_auth_to_can=r, origin_auth=origin, topology=topo, volume_mm3=volume,
        com_can_mm=com, j_unit_mm5=j, ref_check=ref, hull=hull_c, hull_volume_mm3=hull_vol,
        obb_extents_mm=np.sort(v.max(0) - v.min(0))[::-1], desc=d, labels=lab,
        subsystem=classify.suggest_subsystem(name), boxes=boxes, boxes_method=method, boxes_certified=ok,
        boxes_detail=detail, cover=cover, allowed_orients=allowed, orient_bounds=bounds,
        suggested_units=suggested,
        mass_source="ASSUMED" if status != "WITHHELD" else "WITHHELD")
