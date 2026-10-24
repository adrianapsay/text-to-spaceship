"""The bracket design problem every generator (contest entrant) receives.

A bracket is designed inside its reserved box (the V2 Stage 2 packing reserved it and the fit proof certifies it).
The box is cut into cubic voxels of size `h` (the grid is centred in the box and never leaves it). Per voxel:

* `void`    — passive empty: inside the held part, or closer to its surface than the contact gap (the part itself);
* `fixed`   — passive solid, bolted: the voxel layer on the target plane (wall, end plate or corner rail — chassis
              structure only since v2.5);
* `contact` — passive solid, loaded: the voxel layer that touches the part (its mounting side, or its surface where
              the bracket wraps it). The part's inertia load enters here;
* `boss`    — passive solid around each bolt of the bolt pattern (gd.bolts), 2 mm deep from the bolted face;
* everything else is design space.

Load cases: the FE cases are run at the 68 g reference level (the GSFC MAC at ≤ 1 kg) in +X, +Y and +Z separately —
the part's mass × 68 g acting at the part's CENTRE OF MASS, brought onto the contact layer as a force plus the moment
about the layer's centroid (RBE3-like: `contact_voxel_forces`), and 68 g body acceleration on the bracket itself. The
launch environment (gd.environment: quasi-static by mass, random, sine, shock, factors) scales and combines them in
gd.evaluate. Material: gd.materials (default AlSi10Mg L-PBF stress-relieved: E 65 GPa lower value, ν 0.33,
ρ 2680 kg/m³, Fty 170 MPa, Ftu 280 MPa — vendor values, not design allowables). A generator returns a density field on
the grid (1 = solid); `gd.evaluate` turns it into a solid, meshes it and checks it with CalculiX and NGSolve.

Grid indexing: `grid[i, j, k]` is the voxel with centre `origin + (i + 0.5, j + 0.5, k + 0.5) * h` (world mm). The
grid lies inside the reserved box and starts exactly on the target plane, so the bolted face of a design is a face
of the voxel grid.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from . import environment as _env
from .materials import fea_material

# Kept for the modules and tests that import them; the values come from gd.environment (GEVS preset) and
# gd.materials, where every number carries its source.
G0 = _env.G0                                         # mm/s²
LIMIT_G = _env.MAC_TABLE[0][1]                       # 68 g: the FE reference level (GSFC MAC at ≤ 1 kg)
CONTACT_GAP = 0.3                                    # mm: the bracket follows the part surface at this gap
FOS_YIELD, FOS_ULT = _env.GEVS_FACTORS["static"].yield_, _env.GEVS_FACTORS["static"].ult      # 1.25, 1.4
RANDOM_FOS_YIELD, RANDOM_FOS_ULT = _env.GEVS_FACTORS["random"].yield_, _env.GEVS_FACTORS["random"].ult   # 1.6, 1.8
F1_PASS = _env.F1_GUIDANCE                           # 100 Hz (GEVS App. B guidance, the project's pass rule)
F1_TARGET = 200.0                                    # Hz, target (research note §1; octave rule UNVERIFIED)
Q_MILES = _env.Q_DEFAULT


def gevs_acceptance_asd(f_hz: float) -> float:
    """GEVS component acceptance ASD (g²/Hz), Table 2.4-3: +6 dB/oct from 20 Hz to 0.08 at 50 Hz, flat to 800 Hz,
    −6 dB/oct to 2000 Hz (10.0 Grms) — and 0 outside 20–2000 Hz: the spectrum is defined there only (the old
    continuation at −6 dB/oct above 2 kHz was unconservative for stiff modes)."""
    return float(_env.GEVS_ACCEPTANCE.asd(float(f_hz)))


def miles_3sigma_g(f_hz: float) -> float:
    """3σ quasi-static equivalent (g) of the GEVS acceptance input at a single-degree-of-freedom frequency f (Miles,
    Q = 10) — a cross-check only: the random check is the modal superposition of gd.vibration."""
    from .vibration import miles_3sigma_g as miles
    return miles(f_hz, _env.GEVS_ACCEPTANCE, Q_MILES)


MATERIAL = fea_material("AlSi10Mg")


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
    plane_mm: float                  # target plane (wall / end plate / rail; the PC/104 deck only before v2.5)
    reserve: np.ndarray              # (6,) the reserved box (lo, hi) — the solid must stay inside it
    part_mass_kg: float
    vol_frac: float = 0.25           # target solid share of the design space (generators that take one)
    part_v: np.ndarray | None = field(default=None, repr=False)    # held part surface, world mm (for evaluation)
    part_f: np.ndarray | None = field(default=None, repr=False)
    material: dict = field(default_factory=lambda: dict(MATERIAL))
    part_com: np.ndarray | None = None          # world mm: where the part's inertia load acts
    part_inertia_kgm2: np.ndarray | None = None  # (3, 3) about the part's centre of mass (for the frequency)
    bolts: np.ndarray | None = None             # (n, 3) world mm, bolt centres on the target plane (gd.bolts)
    boss: np.ndarray | None = None              # bool (nx, ny, nz): passive solid around the bolts
    plate: np.ndarray | None = None             # bool: passive layers behind the bolted one (thicken_plate)
    skin: np.ndarray | None = None              # bool: passive layers behind the contact one (thicken_skin)

    def passive_solid(self) -> np.ndarray:
        """Voxels that are solid whatever the generator does: the bolted layer (and the plate layers behind it), the
        contact layer (and the skin layers behind it), the bosses."""
        out = self.fixed | self.contact
        for extra in (self.boss, self.plate, self.skin):
            if extra is not None:
                out = out | extra
        return out

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
        return ~(self.void | self.passive_solid())

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
    bolted layer within the reserved box (e.g. under a wedge-shaped part; seen on a PC/104-deck bracket before v2.5,
    possible on any wall whose part's shape overhangs its mounting side). Such voxels can carry
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


DEFAULT_FASTENERS = 3     # a metal-AM bracket's fasteners when the bracket dict has none (mfg.rules, ASSUMED)


def _layers_behind(dom: DesignDomain, layer: np.ndarray, n: int, toward_wall: bool) -> np.ndarray:
    """The n − 1 voxel layers next to `layer` along the bracket axis — away from the wall (toward the part) or
    toward it — clipped to the grid (np.roll wraps around) and never in the part's void."""
    ax = dom.axis
    up = dom.neg != toward_wall                       # toward higher indices along the axis
    out = np.zeros(dom.shape, bool)
    for k in range(1, min(n, dom.shape[ax])):
        shifted = np.roll(layer, k if up else -k, axis=ax)
        idx = [slice(None)] * 3
        idx[ax] = slice(0, k) if up else slice(dom.shape[ax] - k, None)
        shifted[tuple(idx)] = False
        out |= shifted
    return out & ~dom.void


def _layers(dom: DesignDomain, t_mm: float) -> int:
    return int(max(1, np.ceil(float(t_mm) / dom.h - 1e-9)))


def thicken_plate(dom: DesignDomain, plate_mm: float) -> float:
    """Make the bolted plate at least `plate_mm` thick: passive solid voxel layers behind the bolted layer, over its
    footprint (never into the part's void). Returns the plate thickness it now has (whole voxels)."""
    n = _layers(dom, plate_mm)
    plate = _layers_behind(dom, dom.fixed, n, toward_wall=False)
    dom.plate = plate if plate.any() else None
    return n * dom.h


def thicken_skin(dom: DesignDomain, skin_mm: float) -> float:
    """Make the contact skin (the layer on the part's mounting side, where the part's loads go in) at least
    `skin_mm` thick: passive solid layers behind it toward the wall. Returns the skin thickness it now has."""
    n = _layers(dom, skin_mm)
    skin = _layers_behind(dom, dom.contact, n, toward_wall=True)
    dom.skin = skin if skin.any() else None
    return n * dom.h


def member_thickness_mm(dom: DesignDomain, density: np.ndarray) -> float | None:
    """Thinnest members of the generated material (not the prescribed bolted plate, contact skin or bosses), as the
    5th percentile of the local thickness (2·d − 1)·h on the members' medial ridge: d is the distance (voxels) from a
    voxel centre to the nearest empty voxel centre, so a 1-voxel plate measures h and a 3-voxel one 3h (an even
    thickness measures one voxel less: voxel resolution, ASSUMED). The ridge is the skeleton (Lee thinning) together
    with the local maxima of d, which also covers plates the thinning collapses; skeleton end voxels are left out
    (a member's free end is not its thickness), the wall continues the bolted layer (a member reaching the plate
    does not end there), and ridge voxels closer to the plate, skin or bosses than their own d (where a member joins
    them) count only when no other is left. None when the design has no generated material."""
    from scipy import ndimage
    from skimage.morphology import skeletonize
    d = np.clip(np.asarray(density, float), 0.0, 1.0).copy()
    if d.shape != tuple(dom.shape):
        return None
    d[dom.void] = 0.0
    passive = dom.passive_solid()
    d[passive] = 1.0
    solid = d >= 0.5
    region = solid & ~passive
    if not region.any():
        return None
    pad = np.pad(solid, 1)
    wall = [slice(1, -1)] * 3                          # the pad layer behind the bolted face is solid (the wall)
    wall[dom.axis] = 0 if dom.neg else -1
    pad[tuple(wall)] = solid.take(0 if dom.neg else -1, axis=dom.axis)
    dist = ndimage.distance_transform_edt(pad)[1:-1, 1:-1, 1:-1]
    ridge = solid & (dist >= ndimage.maximum_filter(dist, size=3, mode="constant", cval=0.0))
    sk = skeletonize(solid) > 0
    if sk.any():                                      # skeleton end voxels: one skeleton neighbour
        nb = ndimage.convolve(sk.astype(np.int16), np.ones((3, 3, 3), np.int16), mode="constant") - sk
        sk &= nb != 1
    pick = (ridge | sk) & region
    if not pick.any():
        return None
    inner = pick & (ndimage.distance_transform_edt(~passive) > dist)    # away from the junctions
    pick = inner if inner.any() else pick
    return float(np.percentile((2.0 * dist[pick] - 1.0) * dom.h, 5))


def domain_from_bracket(b: dict, rec, orient: int, t, h: float = 1.0, part_mass_kg: float | None = None,
                        vol_frac: float = 0.25, name: str | None = None, material: str | None = None,
                        n_bolts: int | None = None) -> DesignDomain:
    """Design domain of one V2 bracket (`b` from Stage2Model.brackets) holding part `rec` at pose (orient, t), in
    `material` (a gd.materials id; default AlSi10Mg), with `n_bolts` bolts (default: the bracket's fastener count)."""
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
    dom.material = fea_material(material)
    drop_unreachable_contact(dom)
    from .bolts import layout
    dom.bolts, dom.boss = layout(dom, int(n_bolts if n_bolts is not None else b.get("fasteners", DEFAULT_FASTENERS)))
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
