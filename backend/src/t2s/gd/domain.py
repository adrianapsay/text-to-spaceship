"""The bracket design problem every generator (contest entrant) receives.

A bracket is designed inside its reserved box (the V2 Stage 2 packing reserved it and the fit proof certifies it).
The box is cut into cubic voxels of size `h` (the grid is centred in the box and never leaves it). Per voxel:

* `void`    — passive empty: inside the held part, or closer to its surface than the contact gap (the part itself);
* `fixed`   — passive solid, bolted: the voxel layer on the target plane (wall, end plate, rail or deck);
* `contact` — passive solid, loaded: the voxel layer that touches the part (its mounting side, or its surface where
              the bracket wraps it). The part's inertia load enters here;
* everything else is design space.

Load cases (all ASSUMED, docs/research/v2-bracket-loads-materials.md): 68 g quasi-static in +X, +Y and +Z
separately — the part's mass × 68 g acting at the part's CENTRE OF MASS, brought onto the contact layer as a force
plus the moment about the layer's centroid (RBE3-like: `contact_voxel_forces`), and 68 g body acceleration on the
bracket itself. Material: AlSi10Mg L-PBF, stress-relieved (E = 65 GPa lower bound, ν = 0.33, ρ = 2680 kg/m³, Fty 170 MPa,
Ftu 280 MPa). A generator returns a density field on the grid (1 = solid); `gd.evaluate` turns it into a solid,
meshes it and checks it with CalculiX and NGSolve.

Grid indexing: `grid[i, j, k]` is the voxel with centre `origin + (i + 0.5, j + 0.5, k + 0.5) * h` (world mm). The
grid lies inside the reserved box and starts exactly on the target plane, so the bolted face of a design is a face
of the voxel grid.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

G0 = 9806.65                         # mm/s²
LIMIT_G = 68.0                       # quasi-static limit load, each axis separately (ASSUMED, GSFC MAC envelope)
CONTACT_GAP = 0.3                    # mm: the bracket follows the part surface at this gap where it wraps it
FOS_YIELD, FOS_ULT = 1.25, 1.4       # tested at CubeSat level (GEVS-B Table 2.2-3)
F1_PASS, F1_TARGET = 100.0, 200.0    # Hz, bracket + part, hard-mounted
# random vibration (research note §2 LC4–LC6): Miles 3σ load at the bracket's own frequency on the GEVS acceptance
# spectrum, Q = 10; design factors 1.6 (yield) / 1.8 (ultimate) on it, against 1.25 / 1.4 on the 68 g quasi-static
Q_MILES = 10.0
RANDOM_FOS_YIELD, RANDOM_FOS_ULT = 1.6, 1.8


def gevs_acceptance_asd(f_hz: float) -> float:
    """GEVS component acceptance ASD (g²/Hz): +6 dB/oct from 20 Hz to 0.08 at 50 Hz, flat to 800 Hz, −6 dB/oct to
    2000 Hz (10.0 grms); continued at −6 dB/oct above 2000 Hz (conservative: the spectrum ends there)."""
    f = float(f_hz)
    if f < 50.0:
        return 0.08 * (max(f, 20.0) / 50.0) ** 2
    if f <= 800.0:
        return 0.08
    return 0.08 * (800.0 / f) ** 2


def miles_3sigma_g(f_hz: float) -> float:
    """3σ quasi-static equivalent (g) of the random input at a single-degree-of-freedom frequency f (Miles)."""
    import math
    return 3.0 * math.sqrt(math.pi / 2.0 * f_hz * Q_MILES * gevs_acceptance_asd(f_hz))
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
    part_com: np.ndarray | None = None          # world mm: where the part's inertia load acts
    part_inertia_kgm2: np.ndarray | None = None  # (3, 3) about the part's centre of mass (for the frequency)

    def contact_voxel_forces(self, case: dict) -> np.ndarray:
        """(nx, ny, nz, 3) N on the contact voxels for one load case: the part's force acting at its centre of mass,
        distributed RBE3-like (equal voxel weights) as f_v = F/n + ω × (x_v − c), ω = J⁻¹ M, M = (p − c) × F —
        resultant F, moment about the layer centroid c equal to that of F at the part's centre of mass p."""
        out = np.zeros(tuple(self.shape) + (3,))
        idx = np.argwhere(self.contact)
        if not len(idx):
            return out
        x = self.origin + (idx + 0.5) * self.h
        F = np.asarray(case["contact_force_n"], float)
        c = x.mean(axis=0)
        r = x - c
        f = np.repeat(F[None] / len(x), len(x), axis=0)
        if self.part_com is not None:
            J = np.trace(r.T @ r) * np.eye(3) - r.T @ r
            M = np.cross(np.asarray(self.part_com, float) - c, F)
            f += np.cross(np.linalg.lstsq(J, M, rcond=None)[0], r)
        out[tuple(idx.T)] = f
        return out

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


def drop_unreachable_contact(dom: DesignDomain) -> int:
    """Remove contact voxels that no solid can reach: those in a pocket the part's own shape cuts off from the
    bolted layer within the reserved box (e.g. under a wedge-shaped part on the PC/104 deck). Such voxels can carry
    no load, and a design must join every contact voxel to the wall (evaluate.solid_from_density), so with them no
    design — not even the solid block — could pass. 6-connected, as the solid check. Returns how many were dropped."""
    from scipy import ndimage
    free = ~dom.void
    lab, _ = ndimage.label(free)
    reach = np.unique(lab[dom.fixed & free])
    reach = reach[reach > 0]
    keep = dom.contact & np.isin(lab, reach)
    n = int(dom.contact.sum() - keep.sum())
    dom.contact = keep
    return n


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
    origin = lo + 0.5 * (ext - np.array(shape) * h)            # centred: the grid never leaves the box …
    ax = int(b["axis"])                                        # … and along the bracket axis it starts exactly
    origin[ax] = float(b["plane_mm"]) if b["neg"] else float(b["plane_mm"]) - shape[ax] * h   # on the target plane
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
    # contact layer about 1.5 voxels deep: one voxel deep, a curved surface broke it into pieces that touched only at
    # voxel edges, and the pieces could fall off the solid (found by the independent verification)
    contact = ~void & (dist < CONTACT_GAP + 2.0 * h)
    k = np.arange(shape[ax])
    first = (k == 0) if dom.neg else (k == shape[ax] - 1)       # the layer on the target plane
    sl = [None, None, None]
    sl[ax] = slice(None)
    fixed = np.broadcast_to(first[tuple(sl)], shape).copy() & ~void.reshape(shape)
    dom.void = void.reshape(shape)
    dom.contact = contact.reshape(shape) & ~fixed
    dom.fixed = fixed
    drop_unreachable_contact(dom)
    # where the part's inertia acts: its centre of mass, and its inertia about it (uniform density)
    from ..massprops.core import integrate
    up = integrate(np.asarray(vw, float), np.asarray(rec.f, np.int64))
    dom.part_com = np.asarray(up.com_mm, float)
    dom.part_inertia_kgm2 = dom.part_mass_kg * (np.asarray(up.j_mm5, float) / up.volume_mm3) * 1e-6
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
