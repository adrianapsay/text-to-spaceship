"""Turn a generator's density field into a certified-ready solid and check it with two FEA solvers under a launch
environment (gd.environment; default: GEVS with the qualification check).

1. Passives are imposed (void 0, fixed/contact/bosses 1); the solid (density ≥ 0.5) keeps only the voxel islands that
   join the bolted layer to the part (6-connected); a design with no such island fails.
2. Surface: marching cubes on the density (iso 0.5). The voxel grid lies inside the reserved box and starts on the
   target plane, so the solid is inside the box the fit proof certifies and its bolted face lies exactly on the
   plane, meshed with ordinary marching-cubes triangles (a boolean cut there would leave a few huge triangles and a
   coarse mesh at the bracket root, where bending stress peaks). The held part is subtracted as a safety net.
3. Quadratic tets on exactly that surface; the bolted face is fixed; the faces within the contact zone of the part
   carry the part's inertia load at the 68 g reference level (each axis separately) acting at the part's centre of
   mass — force plus moment as a linear traction (RBE3-like); the bracket carries its own body load. Three pure
   torques on the same faces add trial shapes in which the part twists. The modes follow by Rayleigh–Ritz on all six
   deflections (consistent bracket mass; the part a rigid mass and inertia at its centre of mass); f1 is the lowest.
4. CalculiX and NGSolve solve the same problem. Per solver: the voxel-averaged stress tensors of all six trial cases
   (voxel_tensors), modal stress tensors S⁽ᵏ⁾ = Σᵢ Cᵢₖ Sᵢ, the per-node support reactions given to the bolts
   (gd.bolts), and the random (CQC, Segalman RMS von Mises), sine and shock (ESTIMATE) responses for every preset
   (gd.vibration). Margins use the larger of the two solvers' stresses and loads and the lower first frequency.
5. score() applies the design policy of gd.environment: (a) the limit level × the preset's factors, (b) the
   qualification test level against yield (no extra factor) and ultimate (1.25); the quasi-static MAC case and the
   random case are separate checks, never added; bolts with the fitting factor 1.15.

Voxel-averaged stress: nodal peaks at the sharp corners of a voxel-built solid are singular and do not converge
(voxel_tensors); the raw nodal peak is reported only.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

import numpy as np

from . import bolts as _bolts
from . import environment as _env
from .domain import CONTACT_GAP, F1_PASS, LIMIT_G, DesignDomain, GenResult
from .vibration import (
    G0,
    miles_3sigma_g,
    modal_covariance,
    pseudo_accel,
    shock_response,
    sine_response,
    vector_cov,
    vm_rms,
    voigt,
    von_mises_voigt,
)


@dataclass
class Evaluation:
    name: str
    generator: str
    ok: bool                              # a solid exists, joins wall and part, both solvers ran
    passed: bool = False                  # ok, every gating margin ≥ 0 and f1 ≥ F1_PASS
    reason: str = ""
    mass_g: float | None = None
    volume_cm3: float | None = None
    sigma_mpa: float | None = None        # max over axes and solvers of the voxel-averaged von Mises at 68 g
    sigma_peak_mpa: float | None = None   # max nodal von Mises (bolted face excluded): mesh-dependent at corners
    ms_yield: float | None = None         # bracket body, the governing gating check (score)
    ms_ult: float | None = None
    ms_bolt: float | None = None          # bolts and flange, the governing gating check
    f1_hz: float | None = None            # lowest natural frequency (Rayleigh–Ritz, part at its CG), lower solver
    modes: list = field(default_factory=list)  # Ritz modes of the lower solver: f, effective-mass fractions, motion
    axes: list = field(default_factory=list)   # per axis: σ at 68 g, frequency, random 3σ (CQC, Miles), margins
    checks: list = field(default_factory=list)       # per case and axis: stress, factors, margins, gating
    bolt_checks: list = field(default_factory=list)  # per case and axis: the worst bolt / flange margin
    margins: dict = field(default_factory=dict)      # per case (static, random limit, …, bolt: …): the worst axis
    factor_sources: dict = field(default_factory=dict)   # per case: where its factors come from
    governing: dict | None = None         # the gating check with the smallest margin
    flags: list = field(default_factory=list)        # reported, not analysed (sine, shock, fatigue, mass share)
    environment: str | None = None
    environment_name: str | None = None
    material: str | None = None
    max_disp_mm: float | None = None
    solvers: dict = field(default_factory=dict)   # per solver: cases, f1, seconds, modes, dynamics
    agreement: dict = field(default_factory=dict)
    gen_seconds: float | None = None
    fea_seconds: float | None = None
    n_nodes: int | None = None
    overhang_fraction: float | None = None
    mesh: tuple | None = field(default=None, repr=False)
    fields: dict | None = field(default=None, repr=False)   # display_fields: per surface vertex, for the colour maps
    field_info: dict | None = field(default=None, repr=False)

    def summary(self) -> dict:
        d = {k: v for k, v in self.__dict__.items() if k not in ("mesh", "fields", "field_info")}
        return d


def _box(lo, hi):
    import manifold3d
    return manifold3d.Manifold.cube(list(np.asarray(hi, float) - np.asarray(lo, float))).translate(list(lo))


def _to_manifold(v, f):
    import manifold3d
    m = manifold3d.Manifold(manifold3d.Mesh(np.asarray(v, np.float32), np.asarray(f, np.uint32)))
    return m


def solid_from_density(dom: DesignDomain, density: np.ndarray):
    """(v, f) of the solid, or (None, reason)."""
    from scipy import ndimage
    from skimage.measure import marching_cubes
    d = np.clip(np.asarray(density, float), 0.0, 1.0).copy()
    if d.shape != tuple(dom.shape):
        return None, f"density shape {d.shape} ≠ grid {tuple(dom.shape)}"
    d[dom.void] = 0.0
    d[dom.passive_solid()] = 1.0
    lab, n = ndimage.label(d >= 0.5)
    keep = sorted(set(np.unique(lab[dom.fixed & (lab > 0)])) & set(np.unique(lab[dom.contact & (lab > 0)])))
    if not keep:
        return None, "no solid path from the bolted layer to the part"
    loose = dom.contact & ~np.isin(lab, keep)
    if loose.any():          # the whole contact layer must hang on the wall: a loose piece cannot hold the part
        return None, f"{int(loose.sum())} contact voxels are not joined to the bolted layer"
    d = np.where(np.isin(lab, keep) | (d < 0.5), d, 0.0)         # drop islands
    # one empty layer closes the surface; the bolted layer (density 1) next to it puts the iso-surface exactly on the
    # grid face, i.e. on the target plane, with ordinary marching-cubes triangles (no boolean cut there)
    P = np.pad(d, 1)
    ax = dom.axis
    verts, faces, _, _ = marching_cubes(P, level=0.5, spacing=(dom.h,) * 3, allow_degenerate=False)
    verts = verts + dom.origin - 0.5 * dom.h                         # padded index i ↔ centre origin + (i − ½) h
    tv = verts[faces]
    vol = np.einsum("ij,ij->i", tv[:, 0], np.cross(tv[:, 1], tv[:, 2])).sum() / 6.0
    if vol < 0:
        faces = faces[:, ::-1]
    try:
        man = _to_manifold(verts, faces)
        if man.is_empty():
            raise ValueError("empty")
    except Exception as exc:  # noqa: BLE001
        return None, f"marching-cubes surface is not a closed manifold ({exc!r})"
    r = dom.reserve
    if np.any(verts < r[:3] - 1e-6) or np.any(verts > r[3:] + 1e-6):    # the grid lies in the box: only a safety net
        man = man ^ _box(r[:3], r[3:])
    if dom.part_v is not None:
        try:
            man = man - _to_manifold(dom.part_v, dom.part_f)
        except Exception:  # noqa: BLE001
            pass
    pieces = [p for p in man.decompose() if p.volume() > 1e-3]
    plane = dom.plane_mm
    good = []
    for p in pieces:
        b = p.bounding_box()
        lo_ax, hi_ax = b[ax], b[3 + ax]
        if (abs(lo_ax - plane) < 1e-4) if dom.neg else (abs(hi_ax - plane) < 1e-4):
            good.append(p)
    if not good:
        return None, "the solid does not reach the bolted face"
    import manifold3d
    sol = manifold3d.Manifold.batch_boolean(good, manifold3d.OpType.Add) if len(good) > 1 else good[0]
    mesh = sol.to_mesh()
    return (_in_box(np.asarray(mesh.vert_properties)[:, :3], r), np.asarray(mesh.tri_verts).astype(np.int64)), ""


def _in_box(v, r):
    """Manifold stores float32 vertices: a vertex on a box face can land ~1e-6 mm outside it. Clamp (the geometry is
    inside by construction), so the certificate's vertex-in-box check holds exactly."""
    return np.clip(np.asarray(v, float), r[:3], r[3:])


def subdivide(v, f):
    """Split every triangle into four at its edge midpoints (same surface, half the element size); shared edges
    share their midpoint, so the surface stays closed."""
    v = np.asarray(v, float)
    f = np.asarray(f, np.int64)
    e = np.sort(np.concatenate([f[:, [0, 1]], f[:, [1, 2]], f[:, [2, 0]]]), axis=1)
    uniq, inv = np.unique(e, axis=0, return_inverse=True)
    mid = len(v) + inv.reshape(3, -1).T                  # midpoint index of edges (01, 12, 20) per face
    v2 = np.vstack([v, 0.5 * (v[uniq[:, 0]] + v[uniq[:, 1]])])
    a, b, c = f.T
    ab, bc, ca = mid.T
    f2 = np.vstack([np.stack([a, ab, ca], 1), np.stack([ab, b, bc], 1), np.stack([ca, bc, c], 1),
                    np.stack([ab, bc, ca], 1)])
    return v2, f2


def refine_long_edges(v, f, lmax: float, max_iter: int = 16):
    """Split surface edges longer than `lmax` at their midpoints until none is left (the surface is unchanged).
    Flat cut faces (the bolted face, box-clipped sides) come out of the boolean as a few large triangles; meshed as
    they are, the elements at the bracket root — where bending stress peaks — would be far coarser than elsewhere.
    Conforming (every split edge is split in both triangles that share it): a triangle with one long edge becomes
    two triangles, with two long edges three, with three four."""
    v = np.asarray(v, float)
    f = np.asarray(f, np.int64)
    for _ in range(max_iter):
        e = np.sort(np.concatenate([f[:, [0, 1]], f[:, [1, 2]], f[:, [2, 0]]]), axis=1)
        uniq, inv = np.unique(e, axis=0, return_inverse=True)
        inv = inv.reshape(3, -1).T                               # edge id of (01, 12, 20) per face
        mark = np.linalg.norm(v[uniq[:, 0]] - v[uniq[:, 1]], axis=1) > lmax
        if not mark.any():
            break
        ids = np.flatnonzero(mark)
        mid = np.full(len(uniq), -1, np.int64)
        mid[ids] = len(v) + np.arange(len(ids))
        v = np.vstack([v, 0.5 * (v[uniq[ids, 0]] + v[uniq[ids, 1]])])
        m = mid[inv]                                             # midpoint index per face edge (−1 = not split)
        k = (m >= 0).sum(axis=1)
        out = [f[k == 0]]
        one = np.flatnonzero(k == 1)
        if len(one):
            j = np.argmax(m[one] >= 0, axis=1)                    # which edge: 0 (a,b), 1 (b,c), 2 (c,a)
            fa = f[one]
            p = fa[np.arange(len(one)), j]
            q = fa[np.arange(len(one)), (j + 1) % 3]
            r = fa[np.arange(len(one)), (j + 2) % 3]
            mm = m[one, j]
            out += [np.stack([p, mm, r], 1), np.stack([mm, q, r], 1)]
        two = np.flatnonzero(k == 2)
        if len(two):
            u = np.argmin(m[two] >= 0, axis=1)                    # the edge that stays: (c, a) after rotation
            rows = np.arange(len(two))
            fa, ma = f[two], m[two]
            a, b, c = fa[rows, (u + 1) % 3], fa[rows, (u + 2) % 3], fa[rows, u]
            mab, mbc = ma[rows, (u + 1) % 3], ma[rows, (u + 2) % 3]
            out += [np.stack([mab, b, mbc], 1), np.stack([a, mab, mbc], 1), np.stack([a, mbc, c], 1)]
        three = np.flatnonzero(k == 3)
        if len(three):
            a, b, c = f[three].T
            ab, bc, ca = m[three].T
            out += [np.stack([a, ab, ca], 1), np.stack([ab, b, bc], 1), np.stack([ca, bc, c], 1),
                    np.stack([ab, bc, ca], 1)]
        f = np.vstack(out)
    return v, f


def overhang_fraction(v, f) -> float:
    """Share of the surface steeper than 45° downward for the best of the six build directions (supports needed)."""
    tv = v[f]
    n = np.cross(tv[:, 1] - tv[:, 0], tv[:, 2] - tv[:, 0])
    area = 0.5 * np.linalg.norm(n, axis=1)
    nn = n / np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-30)
    best = 1.0
    for k in range(3):
        for sg in (1.0, -1.0):
            down = -sg * nn[:, k]
            best = min(best, float(area[down > np.cos(np.radians(45.0))].sum() / area.sum()))
    return best


def fea_problem(dom: DesignDomain, v, f, h_fea: float | None = None, n_modes: int = 0, torsion: bool = True):
    """FE problem of a designed solid: the domain's three 68 g cases (force at the part's CG + self-weight), then —
    with `torsion` — three pure torques about x, y, z on the contact faces (no body load). The torque cases only
    supply trial shapes for the frequencies (ritz_modes): without them a mode in which the part twists (no
    translational load deflects it that way) is missed."""
    from scipy.spatial import cKDTree

    from ..fea.mesh import boundary_faces, mesh_surface
    from ..fea.problem import FeaProblem, LoadCase, Material, SurfaceLoad
    from ..geometry.voxel import surface_samples
    h_fea = h_fea or max(1.5, dom.h)
    # the tets keep the certified surface (gmsh cannot re-parametrise marching-cubes surfaces); long edges of flat
    # cut faces are split first so the root of the bracket is meshed as finely as the rest; h_fea sets the interior
    v, f = refine_long_edges(v, f, 2.0 * h_fea)
    nodes, tets = mesh_surface(v, f, h_fea, remesh=False)
    faces = boundary_faces(tets)
    p = nodes[faces[:, :3]]
    ax = dom.axis
    fixed_mask = np.all(np.abs(p[:, :, ax] - dom.plane_mm) < 1e-4, axis=1)
    fixed = faces[fixed_mask]
    if dom.part_v is not None:
        tree = cKDTree(surface_samples(dom.part_v, dom.part_f, dom.h / 4))
        dist, _ = tree.query(p.mean(axis=1))
        load_mask = (dist < CONTACT_GAP + 1.0 * dom.h + 1e-6) & ~fixed_mask
    else:
        load_mask = np.zeros(len(faces), bool)
    load = faces[load_mask]
    if not len(fixed) or not len(load):
        raise ValueError(f"no {'bolted' if not len(fixed) else 'contact'} faces on the meshed solid")
    m = dom.material
    mat = Material(m["name"], m["E_mpa"], m["nu"], m["rho_t_mm3"], m.get("yield_mpa"), m.get("ultimate_mpa"))
    # the part's inertia force acts at its centre of mass: force + moment about the contact faces' centroid
    # (linear traction, RBE3-like; research note §2: the component as a mass at its CG tied by an RBE3)
    from ..fea.mesh import face_set_moments
    _, c_load, _ = face_set_moments(nodes, load)
    cases = []
    for c in dom.load_cases():
        F = np.asarray(c["contact_force_n"], float)
        M = np.cross(np.asarray(dom.part_com, float) - c_load, F) if dom.part_com is not None else None
        cases.append(LoadCase(c["name"], [SurfaceLoad(load, F, M)], np.asarray(c["body_accel_mm_s2"], float)))
    if torsion:
        # torque scale ~ the 68 g force times its lever arm (the shapes, not the size, matter)
        arm = max(float(np.linalg.norm(np.asarray(dom.part_com, float) - c_load)) if dom.part_com is not None else 0.0,
                  10.0)
        T = float(np.linalg.norm(cases[0].surface_loads[0].total_force_n)) * arm
        for k, ax in enumerate("xyz"):
            cases.append(LoadCase(f"torque {ax}", [SurfaceLoad(load, np.zeros(3), T * np.eye(3)[k])], np.zeros(3)))
    prob = FeaProblem(nodes, tets, mat, fixed, cases, n_modes=n_modes, exclude_nodes=np.unique(fixed.ravel()),
                      label=dom.name)
    prob.load_faces = load
    return prob


def _body_weights(prob) -> np.ndarray:
    """Per node: ∫ Nᵢ dV (straight tet10: −V/20 at corners, V/5 at mid-side nodes) — the consistent body load of a
    unit acceleration and density, = the row sums of the consistent mass matrix."""
    vol = _tet_volumes(prob)
    w = np.zeros(len(prob.nodes))
    np.add.at(w, prob.tets[:, :4].ravel(), np.repeat(-vol / 20.0, 4))
    np.add.at(w, prob.tets[:, 4:].ravel(), np.repeat(vol / 5.0, 6))
    return w


def _mass_products(dom: DesignDomain, prob, U: list) -> tuple[np.ndarray, np.ndarray, list]:
    """(M (k, k) Gram matrix of the shapes in the consistent bracket mass + the part as a rigid mass and inertia at
    its CG moving with the contact faces' RBE3 average, L (k, 3) = Φᵀ M r — the work of the shapes under a unit
    base acceleration along x, y, z, the same body load the solvers apply —, part motions [(u_cg, θ)] per shape)."""
    from ..fea.mesh import tet10_mass_gram
    rho = float(dom.material["rho_t_mm3"])
    m_p = dom.part_mass_kg * 1e-3                                # t
    I_p = np.asarray(dom.part_inertia_kgm2, float) * 1e3         # kg·m² → t·mm²
    Phi = [np.asarray(u, float) for u in U]
    mot = [_part_motion(dom, prob, u) for u in Phi]
    M = tet10_mass_gram(prob.nodes, prob.tets, rho, Phi)
    M = M + np.array([[m_p * (mi[0] @ mj[0]) + mi[1] @ I_p @ mj[1] for mj in mot] for mi in mot])
    w = rho * _body_weights(prob)
    L = np.array([[float(w @ u[:, j] + m_p * mi[0][j]) for j in range(3)] for u, mi in zip(Phi, mot)])
    return 0.5 * (M + M.T), L, mot


def rayleigh_frequency(dom: DesignDomain, prob, u: np.ndarray, accel) -> tuple[float, np.ndarray]:
    """First natural frequency (Hz) along one axis by Rayleigh's quotient on the static deflection u under that
    axis's inertia load (bracket self-weight + the part's force at its centre of mass): ω² = uᵀf / uᵀMu, M the
    consistent bracket mass plus the part as a rigid mass at its centre of mass with its inertia, moving with the
    contact faces' RBE3 average (translation u_c and rotation θ from an area-weighted least-squares fit). Rayleigh's
    quotient is an upper bound; with the part's mass dominating it is close. Returns (f, displacement of the part's
    centre of mass)."""
    M, L, mot = _mass_products(dom, prob, [u])
    num = float(L[0] @ np.asarray(accel, float))                  # uᵀ f  (N·mm)
    den = float(M[0, 0])                                         # uᵀ M u (t·mm²)
    return float(np.sqrt(max(num, 0.0) / den) / (2 * np.pi)) if den > 0 else float("nan"), mot[0][0]


def _tet_volumes(prob) -> np.ndarray:
    pt = prob.nodes[prob.tets[:, :4]]
    return np.abs(np.einsum("ij,ij->i", pt[:, 1] - pt[:, 0], np.cross(pt[:, 2] - pt[:, 0], pt[:, 3] - pt[:, 0]))) / 6.0


def _part_motion(dom: DesignDomain, prob, u: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(translation of the part's centre of mass, rotation θ) for a displacement field: the contact faces' RBE3
    average — u_c = ∫u dA / A and θ = J⁻¹ ∫ (x − c) × u dA about their centroid c, the motion work-conjugate to the
    linear traction that carries the part's load (u_c·F + θ·M = ∫ t·u dA) — carried rigidly to the CG. Integrated
    exactly over the 6-node faces (degree-5 rule; a rigid motion is recovered exactly)."""
    from ..fea.mesh import _tri_rule, face_set_moments
    nodes, faces = prob.nodes, np.asarray(prob.load_faces)
    A, c, J = face_set_moments(nodes, faces)
    L, wq = _tri_rule()
    N = np.stack([L[:, 0] * (2 * L[:, 0] - 1), L[:, 1] * (2 * L[:, 1] - 1), L[:, 2] * (2 * L[:, 2] - 1),
                  4 * L[:, 0] * L[:, 1], 4 * L[:, 1] * L[:, 2], 4 * L[:, 2] * L[:, 0]], axis=1)   # (Q, 6)
    P = nodes[faces[:, :3]].astype(float)
    area = 0.5 * np.linalg.norm(np.cross(P[:, 1] - P[:, 0], P[:, 2] - P[:, 0]), axis=1)
    X = np.einsum("qk,fkj->fqj", L, P)                           # (F, Q, 3) quadrature points
    Uq = np.einsum("qk,fkj->fqj", N, u[faces])                   # (F, Q, 3) displacement there
    w = area[:, None] * wq[None, :]
    u_c = np.einsum("fq,fqj->j", w, Uq) / A
    theta = np.linalg.solve(J, np.einsum("fq,fqj->j", w, np.cross(X - c, Uq)))
    return u_c + np.cross(theta, np.asarray(dom.part_com, float) - c), theta


def _load_vector(prob, case, rho: float, w_body: np.ndarray) -> np.ndarray:
    """The nodal load vector the solvers apply for a case: consistent surface loads (mesh.consistent_surface_load,
    as CalculiX gets them; NGSolve integrates the same traction) and the consistent body load of the quadratic tets
    (corners −V/20, mid-side nodes V/5)."""
    from ..fea.mesh import consistent_surface_load
    f = np.zeros((len(prob.nodes), 3))
    for sl in case.surface_loads:
        for n, fn in consistent_surface_load(prob.nodes, np.asarray(sl.faces), sl.total_force_n,
                                             getattr(sl, "moment_nmm", None)).items():
            f[n] += fn
    if case.body_accel_mm_s2 is not None:
        f += rho * w_body[:, None] * np.asarray(case.body_accel_mm_s2, float)
    return f


RITZ_CUTOFF = 1e-10  # drop trial directions whose share of the M-normalised Gram matrix is below this (see ritz)


@dataclass
class Ritz:
    """Rayleigh–Ritz modes of bracket + part (ritz)."""
    modes: list                          # [{f_hz, eff_mass_frac (x, y, z), motion}], lowest first
    C: np.ndarray                        # (n_trial, n_m): mode k = Σᵢ C[i, k] × trial shape i, Cᵀ M C = I
    f_hz: np.ndarray                     # (n_m,)
    gamma: np.ndarray                    # (n_m, 3) participation factors Γ_kj = c_kᵀ L_j (√t)
    part_t: np.ndarray                   # (n_m, 3) part CG translation per unit modal coordinate
    part_r: np.ndarray                   # (n_m, 3) part rotation per unit modal coordinate
    m_tot: float                         # bracket + part (t)
    kept: int                            # independent trial directions kept

    @property
    def omega(self) -> np.ndarray:
        return 2.0 * np.pi * self.f_hz

    def eff_mass_sum(self) -> np.ndarray:
        """Σ_k Γ_kj² / m_tot per axis: the share of the mass the modes carry along each axis."""
        return (self.gamma ** 2).sum(axis=0) / self.m_tot


def ritz(dom: DesignDomain, prob, U: list, cutoff: float = RITZ_CUTOFF) -> Ritz:
    """Natural modes of bracket + part by Rayleigh–Ritz on the static deflections U of all load cases (three
    translations, three torques): stiffness Kᵢⱼ = uᵢᵀ fⱼ (exact — K uⱼ = fⱼ), mass Mᵢⱼ = consistent bracket mass +
    the part as a rigid mass and inertia at its centre of mass moving with the contact faces' RBE3 average
    (_mass_products). Each Ritz frequency is an upper bound of the corresponding true one (Poincaré).

    Dependent shapes: the trial shapes are first scaled to unit modal mass (before, the 1e-10 cutoff applied to the
    unscaled Gram matrix, so it depended on the arbitrary size of the torque cases), then directions whose eigenvalue
    of the scaled Gram matrix is below `cutoff` × the largest are dropped. Measured
    (test_ritz_cutoff_is_scale_free_and_above_the_noise_floor): with displacements rounded to CalculiX's 7
    significant digits, a near-dependent direction perturbs the modes by < 1e-4 down to 2e-10 and by ~1e-3 near
    5e-12 — while a cutoff of 1e-8 (planned) would drop a genuine mode found at 2e-10. So 1e-10 stays."""
    rho = float(dom.material["rho_t_mm3"])
    w_body = _body_weights(prob)
    Phi = [np.asarray(u, float) for u in U]
    M, L, mot = _mass_products(dom, prob, Phi)
    F = [_load_vector(prob, c, rho, w_body) for c in prob.load_cases[:len(Phi)]]
    n = len(Phi)
    K = np.array([[float(np.sum(Phi[i] * F[j])) for j in range(n)] for i in range(n)])
    K = 0.5 * (K + K.T)
    d = 1.0 / np.sqrt(np.maximum(np.diag(M), 1e-300))           # unit modal mass per trial shape
    Ms, Ks = d[:, None] * M * d[None, :], d[:, None] * K * d[None, :]
    s, V = np.linalg.eigh(Ms)
    keep = s > cutoff * s.max()
    T = V[:, keep] / np.sqrt(s[keep])
    lam, W = np.linalg.eigh(T.T @ Ks @ T)
    C = d[:, None] * (T @ W)                                     # columns: modes in the trial shapes, Cᵀ M C = I
    m_tot = float(rho * _tet_volumes(prob).sum() + dom.part_mass_kg * 1e-3)
    I_p = np.asarray(dom.part_inertia_kgm2, float) * 1e3
    sq = np.sqrt(np.diag(I_p))
    m_p = dom.part_mass_kg * 1e-3
    ut = np.array([mi[0] for mi in mot])                         # (n_trial, 3)
    th = np.array([mi[1] for mi in mot])
    part_t, part_r = C.T @ ut, C.T @ th
    gamma = C.T @ L
    modes = []
    for k in range(C.shape[1]):
        up, tk = part_t[k], part_r[k]
        rot = float(tk @ I_p @ tk) > m_p * float(up @ up)
        kind = (f"part rotates about {'xyz'[int(np.argmax(np.abs(tk) * sq))]}" if rot
                else f"part moves along {'xyz'[int(np.argmax(np.abs(up)))]}")
        modes.append({"f_hz": float(np.sqrt(max(lam[k], 0.0)) / (2 * np.pi)),
                      "eff_mass_frac": (gamma[k] ** 2 / m_tot).tolist(), "motion": kind})
    return Ritz(modes, C, np.array([m["f_hz"] for m in modes]), gamma, part_t, part_r, m_tot, int(keep.sum()))


def ritz_modes(dom: DesignDomain, prob, U: list, cutoff: float = RITZ_CUTOFF) -> list[dict]:
    """The modes of ritz() as dicts: frequency, effective-mass fraction along x, y, z (base excitation; of bracket +
    part) and the dominant motion of the part. Sorted by frequency."""
    return ritz(dom, prob, U, cutoff).modes


def _tensor(S) -> np.ndarray:
    """Nodal stresses as (n, 3, 3): NGSolve gives tensors, CalculiX Voigt (xx, yy, zz, xy, yz, zx)."""
    S = np.asarray(S, float)
    if S.ndim == 3:
        return S
    xx, yy, zz, xy, yz, zx = S.T
    return np.stack([np.stack([xx, xy, zx], -1), np.stack([xy, yy, yz], -1), np.stack([zx, yz, zz], -1)], -2)


def _vm(S: np.ndarray) -> np.ndarray:
    s = 0.5 * (S + np.swapaxes(S, -1, -2))
    d = s - np.trace(s, axis1=-2, axis2=-1)[..., None, None] * np.eye(3) / 3.0
    return np.sqrt(1.5 * np.sum(d * d, axis=(-2, -1)))


def voxel_tensors(dom: DesignDomain, prob, stresses: list) -> tuple[np.ndarray, np.ndarray]:
    """The stress averaged over each design voxel (cube of side h, the resolution of the design), for every given
    nodal stress field: (voxel centres (n_v, 3), tensors (n_v, n_fields, 6) in Voigt order xx, yy, zz, xy, yz, zx).
    Nodal peaks of voxel-built solids sit at sharp corners — the staircase of the voxels, the edge of the clamped face,
    the edge of the uniform load patch — and grow without bound as the mesh is refined (linear-elastic corner
    singularities, measured +30 … +70 % per refinement). The voxel average is a fixed physical volume, so it converges
    with the mesh and is what a design resolved to h can claim; features finer than h (fillets) are for the detailed
    design. Volume-weighted average of the nodal tensors (each tet's volume shared over its 10 nodes); nodes on the
    bolted face are excluded."""
    nodes, tets = prob.nodes, prob.tets
    vol = _tet_volumes(prob)
    w = np.zeros(len(nodes))
    np.add.at(w, tets.ravel(), np.repeat(vol / 10.0, 10))
    if prob.exclude_nodes is not None and len(prob.exclude_nodes):
        w[np.asarray(prob.exclude_nodes)] = 0.0
    idx = np.floor((nodes - dom.origin) / dom.h).astype(np.int64)
    idx = np.clip(idx, 0, np.array(dom.shape) - 1)
    key = np.ravel_multi_index(idx.T, dom.shape)
    n = int(np.prod(dom.shape))
    W = np.bincount(key, weights=w, minlength=n)
    ok = W > 0
    out = []
    for S in stresses:
        acc = np.zeros((n, 9))
        np.add.at(acc, key, (_tensor(S).reshape(-1, 9) * w[:, None]))
        out.append(voigt((acc[ok] / W[ok, None]).reshape(-1, 3, 3)))
    cen = dom.origin + (np.argwhere(ok.reshape(dom.shape)) + 0.5) * dom.h
    return cen, np.stack(out, axis=1)


def voxel_stress(dom: DesignDomain, prob, S: np.ndarray) -> float:
    """Peak von Mises of the voxel-averaged stress (voxel_tensors) of one nodal stress field."""
    return float(von_mises_voigt(voxel_tensors(dom, prob, [S])[1][:, 0]).max())


def support_reactions(prob, res, F: list) -> list:
    """Per load case (node ids, reaction on the part per supported node (n, 3) = the solver's internal force there
    minus the external load applied at that node, internal force K u (n, 3)); None when the solver gave no per-node
    forces."""
    out = []
    for k, c in enumerate(res.cases):
        if c.support_nodes is None or c.support_forces_n is None:
            out.append(None)
            continue
        ids = np.asarray(c.support_nodes, np.int64)
        rf = np.asarray(c.support_forces_n, float)
        out.append((ids, rf - F[k][ids], rf))
    return out


def dynamics(dom: DesignDomain, prob, rz: Ritz, vox_c: np.ndarray, vox_t: np.ndarray, supports: list,
             solid=None, envs=None) -> dict:
    """Responses of one solver's solution for every launch environment (JSON-ready): per preset and axis the random
    3σ von Mises (limit and qualification spectra; largest voxel and where), the part's 3σ pseudo-acceleration (CQC)
    and Miles' 3σ at the dominant mode (cross-check), the bolts' 3σ tension and shear, and — where the preset has
    them — the sine peak and the shock ESTIMATE (limit and qualification). Static bolt forces of the 68 g cases are
    kept for score(). vox_t: (n_v, n_trial, 6) voxel-averaged stress of every trial case."""
    envs = list(_env.ENVIRONMENTS.values()) if envs is None else [_env.get(e) for e in envs]
    envs = [e for e in envs if e.response_of is None]           # presets that differ only in factors share these
    S_modal = np.einsum("vic,ik->vck", vox_t, rz.C)            # (n_v, 6, n_m)
    out = {"part_mass_kg": float(dom.part_mass_kg), "n_modes": int(rz.C.shape[1]), "trial_kept": rz.kept,
           "eff_mass_sum": rz.eff_mass_sum().tolist(), "presets": {}}
    B_modal, bolt_info = None, None
    bolts = getattr(dom, "bolts", None)
    if bolts is not None and len(bolts) and supports and all(s is not None for s in supports):
        ids = supports[0][0]
        owner = _bolts.assign_nodes(prob.nodes[ids], np.asarray(bolts, float), dom.axis)
        nb = len(bolts)
        B = np.stack([_bolts.bolt_forces(s[2], owner, nb) for s in supports[:rz.C.shape[0]]], axis=1)  # elastic K u
        B_modal = np.einsum("bic,ik->bck", B, rz.C)                 # (n_b, 3, n_m)
        n_out = _bolts.outward(dom.axis, dom.neg)
        static = [_bolts.bolt_forces(s[1], owner, nb).tolist() for s in supports[:3]]   # reactions, 68 g cases
        thick = (_bolts.thickness_at(solid[0], solid[1], bolts, dom.axis, dom.neg) if solid is not None
                 else np.full(nb, _bolts.FLANGE_T))
        bolt_info = {"positions_mm": np.asarray(bolts, float).tolist(), "n_out": n_out.tolist(),
                     "nodes_per_bolt": np.bincount(owner, minlength=nb).tolist(), "static_68g_n": static,
                     "thickness_mm": np.asarray(thick, float).tolist()}
        out["bolts"] = bolt_info
    P = pseudo_accel(rz.part_t, rz.omega)                        # (3, n_m)
    for E in envs:
        z = E.zeta
        axes = []
        for j in range(3):
            g = rz.gamma[:, j]
            ax = {}
            rnd = {}
            for lvl, spec in (("limit", E.random_limit), ("qual", E.random_qual)):
                I = modal_covariance(rz.f_hz, g, spec, z)
                vm = vm_rms(S_modal, I)
                v = int(np.argmax(vm))
                r = {"sigma3_mpa": 3.0 * float(vm[v]), "voxel_mm": vox_c[v].tolist(),
                     "accel3_g": 3.0 * float(np.sqrt(max(P[j] @ I @ P[j], 0.0))) / G0, "grms_in": spec.grms()}
                if B_modal is not None:
                    t3, s3 = _bolts.tension_shear_3sigma(vector_cov(B_modal, I), n_out)
                    r["bolt_tension3_n"], r["bolt_shear3_n"] = t3.tolist(), s3.tolist()
                rnd[lvl] = r
            ax["random"] = rnd
            dom_k = int(np.argmax(g ** 2))
            ax["dominant_f_hz"] = float(rz.f_hz[dom_k])
            ax["dominant_eff_mass_frac"] = float(g[dom_k] ** 2 / rz.m_tot)
            ax["miles_g"] = miles_3sigma_g(rz.f_hz[dom_k], E.random_limit, E.q)
            ax["miles_qual_g"] = miles_3sigma_g(rz.f_hz[dom_k], E.random_qual, E.q)
            if E.sine is not None:
                sr = sine_response(S_modal, g, rz.f_hz, z, E.sine.f_lo, E.sine.f_hi, E.sine.level_g, rz.part_t, j,
                                   B_modal)
                sr["voxel_mm"] = vox_c[sr.pop("voxel")].tolist()
                if B_modal is not None:
                    amp = np.asarray(sr.pop("bolt_force_amp_n"))
                    sr["bolt_tension_n"] = np.abs(amp @ n_out).tolist()
                    sr["bolt_shear_n"] = np.linalg.norm(amp - np.outer(amp @ n_out, n_out), axis=1).tolist()
                ax["sine"] = sr
            if E.shock is not None:
                sh = {}
                for lvl, srs in (("limit", E.shock), ("qual", E.shock.scaled_db(E.shock_qual_db))):
                    r = shock_response(S_modal, g, rz.f_hz, z, srs, rz.part_t, j, B_modal)
                    r["voxel_mm"] = vox_c[r.pop("voxel")].tolist()
                    if B_modal is not None:
                        t3, s3 = _bolts.tension_shear_3sigma(r.pop("bolt_force_cov"), n_out)
                        r["bolt_tension_n"], r["bolt_shear_n"] = (t3 / 3.0).tolist(), (s3 / 3.0).tolist()
                    sh[lvl] = r
                ax["shock"] = sh
            axes.append(ax)
        out["presets"][E.id] = {"axes": axes}
    return out


def evaluate(dom: DesignDomain, gen: GenResult, solvers=("ccx", "ngs"), threads: int = 2,
             h_fea: float | None = None, env: str | None = None) -> Evaluation:
    from ..fea import ccx, ngs
    ev = Evaluation(dom.name, gen.generator, False, gen_seconds=gen.seconds,
                    material=(dom.material or {}).get("id"))
    if gen.mesh is not None:
        v, f = gen.mesh
        r = dom.reserve
        if np.any(np.asarray(v) < r[:3] - 1e-6) or np.any(np.asarray(v) > r[3:] + 1e-6):
            mesh = (_to_manifold(v, f) ^ _box(r[:3], r[3:])).to_mesh()
            v, f = np.asarray(mesh.vert_properties)[:, :3], np.asarray(mesh.tri_verts)
        sol = (_in_box(v, r), np.asarray(f, np.int64))
    else:
        sol, why = solid_from_density(dom, gen.density)
        if sol is None:
            ev.reason = why
            return ev
    v, f = sol
    ev.mesh = (v, f)
    ev.overhang_fraction = overhang_fraction(v, f)
    t0 = time.perf_counter()
    try:
        if h_fea is not None and h_fea < dom.h:          # refinement check: halve the surface elements too
            prob = fea_problem(dom, *subdivide(v, f), h_fea=h_fea)
        else:
            prob = fea_problem(dom, v, f, h_fea=h_fea)
    except Exception as exc:  # noqa: BLE001
        ev.reason = f"meshing failed: {exc}"
        return ev
    ev.n_nodes = len(prob.nodes)
    ev.volume_cm3 = prob.volume_mm3() / 1e3
    ev.mass_g = prob.mass_t() * 1e6
    res, vox, freq, modes, dyn, src = {}, {}, {}, {}, {}, {}
    n_ax = len(dom.load_cases())                     # the 68 g cases; the torque cases after them are trial shapes
    rho = float(dom.material["rho_t_mm3"])
    w_body = _body_weights(prob)
    F = [_load_vector(prob, c, rho, w_body) for c in prob.load_cases]
    runner = {"ccx": lambda p: ccx.run(p, threads=threads), "ngs": lambda p: ngs.solve_with_fields(p, threads=threads)}
    for s in solvers:
        if s == "ccx" and not ccx.available():
            continue
        for attempt in (1, 2):           # CalculiX on this machine occasionally exits early (seen as exit 201 and
            try:                         # 0xC0000005); the same deck solves when run again
                res[s], fields = runner[s](prob)
                break
            except Exception as exc:  # noqa: BLE001
                if attempt == 2:
                    ev.reason = f"{s} failed twice: {exc}"
                    return ev
                ev.solvers.setdefault("retries", []).append(f"{s}: {str(exc)[:200]}")
        vc, vt = voxel_tensors(dom, prob, fields.stress)
        vox[s] = [float(von_mises_voigt(vt[:, k]).max()) for k in range(n_ax)]
        freq[s] = [rayleigh_frequency(dom, prob, np.asarray(U, float), c.body_accel_mm_s2)
                   for U, c in zip(fields.displacement[:n_ax], prob.load_cases[:n_ax])]
        rz = ritz(dom, prob, fields.displacement)
        modes[s] = rz.modes
        dyn[s] = dynamics(dom, prob, rz, vc, vt, support_reactions(prob, res[s], F), solid=(v, f))
        src[s] = (vc, vt, rz, [np.asarray(u, float) for u in fields.displacement[:n_ax]])
    ev.fea_seconds = time.perf_counter() - t0
    if not res:
        ev.reason = "no solver available"
        return ev
    for s, r in res.items():
        ev.solvers[s] = {"solver": r.solver, "seconds": r.seconds, "f1_hz": modes[s][0]["f_hz"], "modes": modes[s],
                         "cases": [{"name": c.name, "max_disp_mm": c.max_disp_mm, "max_vm_mpa": c.max_vm_mpa,
                                    "max_vm_filtered_mpa": c.max_vm_filtered_mpa,
                                    "voxel_vm_mpa": vox[s][k] if k < n_ax else None,
                                    "f_rayleigh_hz": freq[s][k][0] if k < n_ax else None,
                                    "part_com_disp_mm": np.asarray(freq[s][k][1]).tolist() if k < n_ax else None,
                                    "balance": float(np.linalg.norm(c.reaction_n + c.applied_n) /
                                                     max(np.linalg.norm(c.applied_n), 1.0))}
                                   for k, c in enumerate(r.cases)],
                         "dynamics": dyn[s], "notes": list(r.notes)}
    for k, val in score(ev.solvers, dom.material, env).items():
        setattr(ev, k, val)
    try:
        ev.fields, ev.field_info = display_fields(dom, prob, v, src, env)
    except Exception as exc:  # noqa: BLE001 - the colour maps are a view of the check; the check stands without them
        ev.fields, ev.field_info = None, {"error": f"colour maps not computed: {exc!r}"[:300]}
    ev.sigma_peak_mpa = max(c.max_vm_filtered_mpa for r in res.values() for c in r.cases)
    ev.max_disp_mm = max(c.max_disp_mm for r in res.values() for c in r.cases)
    if len(res) == 2:
        a, b = res["ccx"], res["ngs"]
        E = _env.get(env)

        def q3(s):
            return max(x["random"]["qual"]["sigma3_mpa"] for x in dyn[s]["presets"][E.response_id]["axes"])
        ev.agreement = {
            "disp_rel": max(abs(x.max_disp_mm - y.max_disp_mm) / max(y.max_disp_mm, 1e-30) for x, y in zip(a.cases, b.cases)),
            "sigma_rel": max(abs(x - y) / max(y, 1e-30) for x, y in zip(vox["ccx"], vox["ngs"])),
            "sigma_peak_rel": max(abs(x.max_vm_filtered_mpa - y.max_vm_filtered_mpa) / max(y.max_vm_filtered_mpa, 1e-30)
                                  for x, y in zip(a.cases, b.cases)),
            "f1_rel": max(abs(x["f_hz"] - y["f_hz"]) / max(y["f_hz"], 1e-30) for x, y in zip(modes["ccx"], modes["ngs"])),
            "random_rel": abs(q3("ccx") - q3("ngs")) / max(q3("ngs"), 1e-30)}
    ev.ok = True
    return ev


def display_fields(dom: DesignDomain, prob, v, src: dict, env=None) -> tuple[dict, dict]:
    """Result fields on the solid's surface vertices `v` for the app's colour maps, under launch environment `env`,
    each point the larger of the solvers' values (as the margins take it): von Mises (MPa) at the quasi-static design
    load and the random limit and qualification 3σ (CQC, Segalman) per axis; the static displacement (mm) per axis;
    and the utilisation of the bracket body — at each point the largest factor × stress / allowable of those checks,
    yield and ultimate (1 = zero margin; sine, shock and the bolts are not in it). Stresses are the voxel averages
    the margins use (a surface vertex takes its nearest voxel's), displacements the nearest FE node's.
    src: {solver: (voxel centres, voxel tensors of the trial cases, Ritz, displacements of the 68 g cases)}.
    Returns ({field id: float32 (n_vertices,)}, {fields: [{id, label, unit, kind, case, axis, max, max_all}], …});
    max_all is the field's maximum over every voxel (or FE node), the value the margins use."""
    E = _env.get(env)
    g_s = E.static_g(float(dom.part_mass_kg))
    vox, disp = {}, {}

    def keep(store, key, val):
        store[key] = val if key not in store else np.maximum(store[key], val)
    for vc, vt, rz, U in src.values():
        S_modal = np.einsum("vic,ik->vck", vt, rz.C)
        for k, a in enumerate("xyz"):
            keep(vox, f"vm_static_{a}", von_mises_voigt(vt[:, k]) * g_s / LIMIT_G)
            for lvl, spec in (("limit", E.random_limit), ("qual", E.random_qual)):
                cov = modal_covariance(rz.f_hz, rz.gamma[:, k], spec, E.zeta)
                keep(vox, f"vm_random_{lvl}_{a}", 3.0 * vm_rms(S_modal, cov))
            keep(disp, f"disp_static_{a}", np.linalg.norm(U[k], axis=1) * g_s / LIMIT_G)
    note = (f"Stresses are averaged over each {dom.h:g} mm design voxel (what the margins use), the larger of the "
            "solvers at each point; each surface point shows its nearest voxel. Utilisation = factor × stress / "
            "allowable, the worst of the static and random (limit and qualification) checks, yield and ultimate: 1.00 "
            "is zero margin. Sine, shock and the bolts are checked separately.")
    return fields_on_surface(vox, disp, next(iter(src.values()))[0], prob.nodes, v, E, dom.material, g_s, list(src),
                             float(dom.h), note)


def fields_on_surface(vox: dict, disp: dict, vc, nodes, v, E, mat: dict, g_s: float, solvers: list, voxel_mm,
                      note: str) -> tuple[dict, dict]:
    """The colour-map fields on the surface vertices `v` (display_fields; gd.multi_eval for a bracket that holds
    several parts): `vox` the per-voxel stresses (MPa) at the voxel centres `vc` — vm_static_{a},
    vm_random_limit_{a}, vm_random_qual_{a} — and `disp` the per-node displacements (mm) at `nodes` —
    disp_static_{a}. Adds the utilisation of the body (the worst factor × stress / allowable of those checks, yield
    and ultimate, under environment E); each vertex takes its nearest voxel's stress and its nearest node's
    displacement. Returns (fields, info) as display_fields."""
    from scipy.spatial import cKDTree

    def util(sig, fac):
        return np.maximum(fac.yield_ * sig / mat["yield_mpa"], fac.ult * sig / mat["ultimate_mpa"])
    worst = np.zeros(len(next(iter(vox.values()))))
    for a in "xyz":
        worst = np.maximum.reduce([worst, util(vox[f"vm_static_{a}"], E.factors["static"]),
                                   util(vox[f"vm_random_limit_{a}"], E.factors["random"]),
                                   util(vox[f"vm_random_qual_{a}"], E.qual_factors)])
    vox = {"util_body": worst, **vox}
    pts = np.asarray(v, float)
    near_v = cKDTree(vc).query(pts)[1]
    near_n = cKDTree(nodes).query(pts)[1]
    out = {k: val[near_v].astype(np.float32) for k, val in vox.items()}
    out.update({k: val[near_n].astype(np.float32) for k, val in disp.items()})
    lim, qual = E.random_limit.grms(), E.random_qual.grms()
    labels = {"util_body": ("Utilisation of the bracket body (worst check)", "", "utilisation", None, None)}
    for a in "xyz":
        labels[f"vm_static_{a}"] = (f"von Mises, quasi-static {g_s:.1f} g along {a}", "MPa", "stress", "static", a)
        labels[f"vm_random_limit_{a}"] = (f"von Mises 3σ, random limit {lim:.1f} Grms along {a}", "MPa", "stress",
                                          "random limit", a)
        labels[f"vm_random_qual_{a}"] = (f"von Mises 3σ, random qualification {qual:.1f} Grms along {a}", "MPa",
                                         "stress", "random qualification", a)
        labels[f"disp_static_{a}"] = (f"Displacement, quasi-static {g_s:.1f} g along {a}", "mm", "displacement",
                                      "static", a)
    full = {**vox, **disp}
    info = {"fields": [{"id": k, "label": labels[k][0], "unit": labels[k][1], "kind": labels[k][2],
                        "case": labels[k][3], "axis": labels[k][4], "max": float(out[k].max()),
                        "max_all": float(full[k].max())} for k in out],
            "environment": E.id, "environment_name": E.name, "material": mat.get("id"),
            "yield_mpa": float(mat["yield_mpa"]), "ultimate_mpa": float(mat["ultimate_mpa"]),
            "solvers": list(solvers), "n_vertices": len(pts), "voxel_mm": voxel_mm, "note": note}
    return out, info


# =================================================================================================== scoring
def _row(case, axis, sigma, fac, material, gates, note=""):
    s = max(float(sigma), 1e-12)
    return {"case": case, "axis": axis, "sigma_mpa": float(sigma), "factor_yield": fac.yield_, "factor_ult": fac.ult,
            "ms_yield": material["yield_mpa"] / (fac.yield_ * s) - 1.0,
            "ms_ult": material["ultimate_mpa"] / (fac.ult * s) - 1.0, "gates": bool(gates), "note": note}


def _bolt_row(case, axis, tension, shear, cap, fac, gates, note=""):
    m = _bolts.margins(tension, shear, cap, fac.yield_, fac.ult)
    return {"case": case, "axis": axis, "ms": m["ms"], "check": m["check"], "bolt": m["bolt"],
            "tension_n": np.asarray(tension, float).tolist(), "shear_n": np.asarray(shear, float).tolist(),
            "factor_yield": fac.yield_, "factor_ult": fac.ult, "fitting_factor": _bolts.FITTING_FACTOR,
            "gates": bool(gates), "note": note}


def score(solvers: dict, material: dict, env=None) -> dict:
    """Margins and pass/fail from the solver results (Evaluation.solvers: per solver its 68 g cases with the
    voxel-averaged stress, its Ritz modes and its `dynamics`), so a saved evaluation can be scored again — under
    another preset too — without the FE runs.

    Checks per axis (each gating unless noted), stress = the larger solver's:
    * static — the preset's quasi-static limit (MAC by the part's mass) × its static factors; the FE cases are run at
      the 68 g reference and scale linearly;
    * random limit — the 3σ von Mises (CQC, Segalman) on the LIMIT spectrum × the random factors;
    * random qualification — the 3σ on the QUALIFICATION spectrum × (1.0 yield, 1.25 ultimate);
    * sine — the peak over the preset's sine band × its sine factors (presets with a sine environment);
    * shock limit / qualification — ESTIMATE (modal SRS, CQC), reported, NOT gating (presets with a shock SRS that
      the random check does not cover);
    * bolts — the same cases on the per-bolt forces (fitting factor 1.15), M3 A2-70 and the flange.
    Static and random are separate load cases (never added). f1 ≥ F1_PASS (100 Hz guidance, the project's rule)
    and ≥ the preset's own requirement."""
    E = _env.get(env)
    sv = {s: d for s, d in solvers.items() if isinstance(d, dict) and d.get("modes")}
    if not sv:
        raise ValueError("no solver results to score")
    dyn = {s: d.get("dynamics") or {} for s, d in sv.items()}
    rid = E.response_id
    if any(rid not in (x.get("presets") or {}) for x in dyn.values()):
        raise ValueError(f"the saved evaluation has no {rid!r} response: evaluate the solid again")
    first = next(iter(sv.values()))
    names = [c["name"] for c in first["cases"] if c.get("voxel_vm_mpa") is not None]
    m_part = float(next(iter(dyn.values()))["part_mass_kg"])
    g_s = E.static_g(m_part)
    low = min(sv, key=lambda s: sv[s]["modes"][0]["f_hz"])
    f1 = float(sv[low]["modes"][0]["f_hz"])
    covered, shock_text = _env.shock_covered_by_random(E)
    shock_gates = False                                          # an ESTIMATE: reported, not a pass criterion
    binfo = [x.get("bolts") for x in dyn.values()]
    has_bolts = all(b is not None for b in binfo)
    cap = _bolts.capacities(material, np.min([b["thickness_mm"] for b in binfo], axis=0)) if has_bolts else None
    n_out = np.asarray(binfo[0]["n_out"], float) if has_bolts else None
    rows, brows, axes, flags = [], [], [], []
    for k, name in enumerate(names):
        a = "xyz"[k]
        sig68 = max(d["cases"][k]["voxel_vm_mpa"] for d in sv.values())
        pa = [x["presets"][rid]["axes"][k] for x in dyn.values()]
        mine = []
        mine.append(_row("static", a, sig68 * g_s / LIMIT_G, E.factors["static"], material, True,
                         f"{g_s:.1f} g quasi-static"))
        mine.append(_row("random limit", a, max(p["random"]["limit"]["sigma3_mpa"] for p in pa), E.factors["random"],
                         material, True, f"3σ, {E.random_limit.grms():.2f} Grms limit spectrum"))
        mine.append(_row("random qualification", a, max(p["random"]["qual"]["sigma3_mpa"] for p in pa),
                         E.qual_factors, material, True, f"3σ, {E.random_qual.grms():.2f} Grms qualification spectrum"))
        if E.sine is not None:
            mine.append(_row("sine", a, max(p["sine"]["sigma_peak_mpa"] for p in pa), E.factors["sine"], material, True,
                             f"{E.sine.level_g} g {E.sine.f_lo:.0f}–{E.sine.f_hi:.0f} Hz"))
        if E.shock is not None and not covered:
            mine.append(_row("shock limit (ESTIMATE)", a, max(p["shock"]["limit"]["sigma_peak_mpa"] for p in pa),
                             E.factors["shock"], material, shock_gates, "SRS × participation, CQC"))
            mine.append(_row("shock qualification (ESTIMATE)", a, max(p["shock"]["qual"]["sigma_peak_mpa"] for p in pa),
                             E.qual_factors, material, shock_gates, f"SRS + {E.shock_qual_db:g} dB"))
        rows += mine
        if has_bolts:
            st = np.max([np.abs(np.asarray(b["static_68g_n"][k], float)) for b in binfo], axis=0)   # per component
            t_s, s_s = _bolts.tension_shear_static(st * g_s / LIMIT_G, n_out)
            brows.append(_bolt_row("static", a, t_s, s_s, cap, E.factors["static"], True))
            for lvl, case, fac in (("limit", "random limit", E.factors["random"]),
                                   ("qual", "random qualification", E.qual_factors)):
                t3 = np.max([p["random"][lvl]["bolt_tension3_n"] for p in pa], axis=0)
                s3 = np.max([p["random"][lvl]["bolt_shear3_n"] for p in pa], axis=0)
                brows.append(_bolt_row(case, a, t3, s3, cap, fac, True))
            if E.sine is not None:
                brows.append(_bolt_row("sine", a, np.max([p["sine"]["bolt_tension_n"] for p in pa], axis=0),
                                       np.max([p["sine"]["bolt_shear_n"] for p in pa], axis=0), cap,
                                       E.factors["sine"], True))
            if E.shock is not None and not covered:
                for lvl, case, fac in (("limit", "shock limit (ESTIMATE)", E.factors["shock"]),
                                       ("qual", "shock qualification (ESTIMATE)", E.qual_factors)):
                    brows.append(_bolt_row(case, a, np.max([p["shock"][lvl]["bolt_tension_n"] for p in pa], axis=0),
                                           np.max([p["shock"][lvl]["bolt_shear_n"] for p in pa], axis=0), cap, fac,
                                           shock_gates))
        gate = [r for r in mine if r["gates"]]
        gy = min(gate, key=lambda r: r["ms_yield"])
        gu = min(gate, key=lambda r: r["ms_ult"])
        sy = max(r["factor_yield"] * r["sigma_mpa"] for r in gate)
        su = max(r["factor_ult"] * r["sigma_mpa"] for r in gate)
        p0 = max(pa, key=lambda p: p["random"]["limit"]["sigma3_mpa"])
        eff = min(x["eff_mass_sum"][k] for x in dyn.values())
        axes.append({"case": name, "sigma_68g_mpa": sig68, "static_g": g_s,
                     "f_hz": p0["dominant_f_hz"], "eff_mass_frac": p0["dominant_eff_mass_frac"], "eff_mass_sum": eff,
                     "f_rayleigh_hz": min((d["cases"][k]["f_rayleigh_hz"] for d in sv.values()
                                           if d["cases"][k].get("f_rayleigh_hz")), default=None),
                     "random_3sigma_g": max(p["random"]["limit"]["accel3_g"] for p in pa),
                     "random_qual_3sigma_g": max(p["random"]["qual"]["accel3_g"] for p in pa),
                     "random_miles_g": max(p["miles_g"] for p in pa),
                     "random_miles_qual_g": max(p["miles_qual_g"] for p in pa),
                     "sigma3_limit_mpa": mine[1]["sigma_mpa"], "sigma3_qual_mpa": mine[2]["sigma_mpa"],
                     "yield_factor_g": LIMIT_G * sy / max(sig68, 1e-12), "ult_factor_g": LIMIT_G * su / max(sig68, 1e-12),
                     "governs": gy["case"], "governs_ult": gu["case"],
                     "ms_yield": gy["ms_yield"], "ms_ult": gu["ms_ult"]})
        if eff < 0.9:
            flags.append({"code": "effective_mass", "axis": a,
                          "text": f"{a}: the modes carry {100 * eff:.0f} % of the mass (< 90 %): the random response of "
                                  "the rest is not amplified in this model"})
    body = [r for r in rows if r["gates"]]
    out = {"environment": E.id, "environment_name": E.name, "axes": axes, "checks": rows, "bolt_checks": brows,
           "sigma_mpa": max(x["sigma_68g_mpa"] for x in axes), "f1_hz": f1, "modes": sv[low]["modes"],
           "ms_yield": min(r["ms_yield"] for r in body), "ms_ult": min(r["ms_ult"] for r in body),
           "ms_bolt": min((r["ms"] for r in brows if r["gates"]), default=None)}
    cand = [(r["ms_yield"], r, "yield") for r in body] + [(r["ms_ult"], r, "ultimate") for r in body]
    cand += [(r["ms"], r, r["check"]) for r in brows if r["gates"]]
    ms, r, kind = min(cand, key=lambda x: x[0])
    out["governing"] = {"case": r["case"], "axis": r["axis"], "check": kind, "ms": ms,
                        "bolt": r.get("bolt"), "part": "bolt" if "check" in r else "bracket"}
    # per case: the worst axis (what the app shows as the margins table)
    margins = {}
    for r in rows:
        m = margins.get(r["case"])
        if m is None or min(r["ms_yield"], r["ms_ult"]) < min(m["ms_yield"], m["ms_ult"]):
            margins[r["case"]] = {"ms_yield": r["ms_yield"], "ms_ult": r["ms_ult"], "axis": r["axis"],
                                  "sigma_mpa": r["sigma_mpa"], "gates": r["gates"]}
    for r in brows:
        key = f"bolt: {r['case']}"
        if key not in margins or r["ms"] < margins[key]["ms"]:
            margins[key] = {"ms": r["ms"], "check": r["check"], "bolt": r["bolt"], "axis": r["axis"],
                            "gates": r["gates"]}
    out["margins"] = margins
    src = {"static": E.factors["static"].source, "random limit": E.factors["random"].source,
           "random qualification": E.qual_factors.source, "bolts": f"{_bolts.FF_SOURCE}; {_bolts.M3_A2_70['source']}"}
    if E.sine is not None:
        src["sine"] = E.factors["sine"].source
    if E.shock is not None:
        src["shock limit (ESTIMATE)"], src["shock qualification (ESTIMATE)"] = E.factors["shock"].source, \
            E.qual_factors.source
    out["factor_sources"] = src
    # flags: reported, not analysed
    if E.sine_flag_hz is not None and f1 < E.sine_flag_hz:
        flags.append({"code": "sine", "text": f"f1 {f1:.0f} Hz < {E.sine_flag_hz:.0f} Hz: a sine test or analysis is "
                                              "needed", "source": E.sine_note})
    if E.shock is None:
        from .environment import random_equivalent_srs
        srs = random_equivalent_srs(E.random_qual, [100.0, 1000.0, 2000.0], E.q)
        flags.append({"code": "shock", "text": "no shock spec in this preset: the qualification random level covers a "
                      f"shock SRS (Q = {E.q:g}) up to {srs[0]:.0f} g at 100 Hz, {srs[1]:.0f} g at 1 kHz, "
                      f"{srs[2]:.0f} g at 2 kHz", "source": E.shock_note})
    else:
        flags.append({"code": "shock", "text": shock_text, "source": E.shock_note})
        sh = [r for r in rows if r["case"].startswith("shock")] + [r for r in brows if r["case"].startswith("shock")]
        worst = min((min(r.get("ms_yield", r.get("ms")), r.get("ms_ult", r.get("ms"))) for r in sh), default=None)
        if worst is not None and worst < 0:
            flags.append({"code": "shock_estimate", "text": f"shock ESTIMATE margin {worst:+.2f} (< 0): the interface "
                          "SRS applied at the bracket base without attenuation — refine or test"})
    sig1 = max(r["sigma_mpa"] for r in rows if r["case"] == "random limit") / 3.0
    flags.append({"code": "fatigue", "text": f"random fatigue not analysed (1σ von Mises up to {sig1:.0f} MPa at the "
                                             "limit level)"})
    if E.id == "nanoracks":
        flags.append({"code": "source", "text": "NR-NRCSD-S0003 Table 4.3.1-1 note (RSS of Ny and Nz ±1.8 g) is "
                                                "inconsistent with its ±4.0 / ±4.0 g", "source": E.static_source})
    if not has_bolts:
        flags.append({"code": "bolts", "text": "no bolt pattern or per-node reactions: bolts not checked"})
    out["flags"] = flags
    fails = []
    if out["ms_yield"] < 0:
        g = min(body, key=lambda r: r["ms_yield"])
        fails.append(f"MS yield {out['ms_yield']:+.2f} ({g['case']}, {g['axis']})")
    if out["ms_ult"] < 0:
        g = min(body, key=lambda r: r["ms_ult"])
        fails.append(f"MS ultimate {out['ms_ult']:+.2f} ({g['case']}, {g['axis']})")
    if out["ms_bolt"] is not None and out["ms_bolt"] < 0:
        g = min((r for r in brows if r["gates"]), key=lambda r: r["ms"])
        fails.append(f"bolt MS {out['ms_bolt']:+.2f} ({g['check']}, {g['case']}, {g['axis']})")
    f_req = max(F1_PASS, E.f1_guidance_hz)
    if f1 < f_req:
        fails.append(f"f1 {f1:.0f} Hz < {f_req:.0f}")
    out["passed"], out["reason"] = not fails, "; ".join(fails)
    return out
