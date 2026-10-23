"""The bracket design problem every generator (contest entrant) receives.

A bracket is designed inside its reserved box (the V2 Stage 2 packing reserved it and the fit proof certifies it).
The box is cut into cubic voxels of size `h` (the grid is centred in the box and never leaves it). Per voxel:

* `void`    — passive empty: inside the held part, or closer to its surface than the contact gap (the part itself);
* `fixed`   — passive solid, bolted: the voxel layer on the target plane (wall, end plate, rail or deck);
* `contact` — passive solid, loaded: the voxel layer that touches the part (its mounting side, or its surface where
              the bracket wraps it). The part's inertia load enters here;
* everything else is design space.

Load cases (all ASSUMED, docs/research/v2-bracket-loads-materials.md): 68 g quasi-static in +X, +Y and +Z
separately — the part's mass × 68 g as a total force on the contact layer, and 68 g body acceleration on the bracket
itself. Material: AlSi10Mg L-PBF, stress-relieved (E = 65 GPa lower bound, ν = 0.33, ρ = 2680 kg/m³, Fty 170 MPa,
Ftu 280 MPa). A generator returns a density field on the grid (1 = solid); `gd.evaluate` turns it into a solid,
meshes it and checks it with CalculiX and NGSolve.

Grid indexing: `grid[i, j, k]` is the voxel with centre `origin + (i + 0.5, j + 0.5, k + 0.5) * h` (world mm).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

G0 = 9806.65                         # mm/s²
LIMIT_G = 68.0                       # quasi-static limit load, each axis separately (ASSUMED, GSFC MAC envelope)
CONTACT_GAP = 0.3                    # mm: the bracket follows the part surface at this gap where it wraps it
FOS_YIELD, FOS_ULT = 1.25, 1.4       # tested at CubeSat level (GEVS-B Table 2.2-3)
F1_PASS, F1_TARGET = 100.0, 200.0    # Hz, bracket + part, hard-mounted
MATERIAL = {"name": "AlSi10Mg L-PBF stress-relieved (ASSUMED)", "E_mpa": 65000.0, "nu": 0.33, "rho_t_mm3": 2.68e-9,
            "yield_mpa": 170.0, "ultimate_mpa": 280.0}


@dataclass
class DesignDomain:
    name: str
    origin: np.ndarray               # world mm of the grid corner (voxel (0,0,0) low corner)
    h: float                         # voxel size (mm)
    shape: tuple                     # (nx, ny, nz)
    void: np.ndarray                 # bool (nx, ny, nz)
    fixed: np.ndarray                # bool
    contact: np.ndarray              # bool
    axis: int                        # world axis from the target plane to the part
    neg: bool                        # True: target plane at the low end of `axis`
    plane_mm: float                  # target plane (wall / end plate / rail / deck)
    reserve: np.ndarray              # (6,) the reserved box (lo, hi) — the solid must stay inside it
    part_mass_kg: float
    vol_frac: float = 0.25           # target solid share of the design space (generators that take one)
    part_v: np.ndarray | None = field(default=None, repr=False)    # held part surface, world mm (for evaluation)
    part_f: np.ndarray | None = field(default=None, repr=False)
    material: dict = field(default_factory=lambda: dict(MATERIAL))

    def centres(self) -> np.ndarray:
        """(nx, ny, nz, 3) voxel centres, world mm."""
        idx = np.stack(np.meshgrid(*[np.arange(n) for n in self.shape], indexing="ij"), axis=-1)
        return self.origin + (idx + 0.5) * self.h

    def design(self) -> np.ndarray:
        """Voxels the generator may choose (not void, not passive solid)."""
        return ~(self.void | self.fixed | self.contact)

    def load_cases(self) -> list[dict]:
        """[{name, contact_force_n (3,), body_accel_mm_s2 (3,)}] — total force on the contact layer and acceleration
        of the bracket's own mass (generators that ignore self-weight may drop the latter)."""
        out = []
        for k, ax in enumerate("xyz"):
            e = np.eye(3)[k]
            out.append({"name": f"{LIMIT_G:.0f} g {ax}", "contact_force_n": -self.part_mass_kg * LIMIT_G * G0 * 1e-3 * e,
                        "body_accel_mm_s2": -LIMIT_G * G0 * e})
        return out


@dataclass
class GenResult:
    density: np.ndarray              # (nx, ny, nz) in [0, 1]; ≥ 0.5 is solid
    seconds: float
    generator: str
    notes: list = field(default_factory=list)
    iterations: int | None = None
    history: list = field(default_factory=list)   # optional objective history
    mesh: tuple | None = None        # optional (v, f) world-mm solid instead of a density (reference entrants)


def domain_from_bracket(b: dict, rec, orient: int, t, h: float = 1.0, part_mass_kg: float | None = None,
                        vol_frac: float = 0.25, name: str | None = None) -> DesignDomain:
    """Design domain of one V2 bracket (`b` from Stage2Model.brackets) holding part `rec` at pose (orient, t)."""
    from scipy.spatial import cKDTree

    from ..core.rotations import ROTATIONS_F
    from ..geometry.mesh import ray_parity_inside
    from ..geometry.voxel import surface_samples
    r = np.asarray(b["reserve"], float)
    lo, hi = r[:3], r[3:]
    ext = hi - lo
    shape = tuple(int(max(2, np.floor(e / h + 1e-9))) for e in ext)
    origin = lo + 0.5 * (ext - np.array(shape) * h)            # centred: the grid never leaves the box
    R = ROTATIONS_F[orient]
    vw = rec.v @ R.T + np.asarray(t, float)
    dom = DesignDomain(name or b["name"], origin, h, shape, np.zeros(shape, bool), np.zeros(shape, bool),
                       np.zeros(shape, bool), int(b["axis"]), bool(b["neg"]), float(b["plane_mm"]), r,
                       float(part_mass_kg if part_mass_kg is not None else (rec.mass_kg or 0.2)), vol_frac,
                       vw, np.asarray(rec.f))
    c = dom.centres().reshape(-1, 3)
    samples = surface_samples(vw, rec.f, h / 4)
    dist, _ = cKDTree(samples).query(c)
    plo, phi = vw.min(0), vw.max(0)
    inside = np.zeros(len(c), bool)
    cand = np.all((c >= plo) & (c <= phi), axis=1)
    if cand.any():
        inside[cand] = ray_parity_inside((c[cand] - t) @ R, rec.v, rec.f) > 0.5
    void = inside | (dist < CONTACT_GAP + 0.5 * h)
    contact = ~void & (dist < CONTACT_GAP + 1.5 * h)
    ax = dom.axis
    k = np.arange(shape[ax])
    first = (k == 0) if dom.neg else (k == shape[ax] - 1)       # the layer on the target plane
    sl = [None, None, None]
    sl[ax] = slice(None)
    fixed = np.broadcast_to(first[tuple(sl)], shape).copy() & ~void.reshape(shape)
    dom.void = void.reshape(shape)
    dom.contact = contact.reshape(shape) & ~fixed
    dom.fixed = fixed
    return dom


def box_part_domain(gap: float = 20.0, foot=(36.0, 24.0), part=(60.0, 40.0, 30.0), mass_kg: float = 0.35,
                    h: float = 1.0, vol_frac: float = 0.25, name: str = "flat box, 20 mm gap") -> DesignDomain:
    """Self-contained test domain: a box-shaped part whose −X side is `gap` mm from a wall at x = 0; the bracket's
    reserved box is the gap × `foot` (centred on the part side)."""
    from types import SimpleNamespace

    import manifold3d
    m = manifold3d.Manifold.cube(list(part)).translate([gap, -part[1] / 2, -part[2] / 2])
    mesh = m.to_mesh()
    v = np.asarray(mesh.vert_properties)[:, :3].astype(float)
    f = np.asarray(mesh.tri_verts).astype(np.int64)
    rec = SimpleNamespace(v=v, f=f, mass_kg=mass_kg)
    b = {"name": name, "reserve": [0.0, -foot[0] / 2, -foot[1] / 2, gap, foot[0] / 2, foot[1] / 2], "axis": 0,
         "neg": True, "plane_mm": 0.0}
    return domain_from_bracket(b, rec, 0, np.zeros(3), h, mass_kg, vol_frac, name)
