"""Turn a generator's density field into a certified-ready solid and check it with two FEA solvers.

1. Passives are imposed (void 0, fixed/contact 1); the solid (density ≥ 0.5) keeps only the voxel islands that join
   the bolted layer to the part (6-connected); a design with no such island fails.
2. Surface: marching cubes on the density (iso 0.5). The voxel grid lies inside the reserved box and starts on the
   target plane, so the solid is inside the box the fit proof certifies and its bolted face lies exactly on the
   plane, meshed with ordinary marching-cubes triangles (a boolean cut there would leave a few huge triangles and a
   coarse mesh at the bracket root, where bending stress peaks). The held part is subtracted as a safety net.
3. Quadratic tets on exactly that surface; the bolted face is fixed; the faces within the contact zone of the part
   carry the part's 68 g inertia load (each axis separately) acting at the part's centre of mass — force plus moment
   as a linear traction (RBE3-like); the bracket carries its own 68 g body load. Three pure torques on the same faces
   add trial shapes in which the part twists. The modes follow by Rayleigh–Ritz on all six deflections with the part
   as a rigid mass (and inertia) at its centre of mass; f1 is the lowest. Per axis the random-vibration load
   (Miles, GEVS acceptance, Q = 10) is the largest over the modes carrying a real share of the effective mass along
   that axis; it sets the design factor when it exceeds the quasi-static one (research note §2; see score).
4. CalculiX and NGSolve solve the same problem. Margins use the larger of the two solvers' peak VOXEL-AVERAGED von
   Mises (the stress averaged over each design voxel — nodal peaks at the sharp corners of a voxel-built solid are
   singular and do not converge, see voxel_stress) and the lower first frequency; the raw nodal peak is reported.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

import numpy as np

from .domain import (
    CONTACT_GAP,
    F1_PASS,
    FOS_ULT,
    FOS_YIELD,
    LIMIT_G,
    RANDOM_FOS_ULT,
    RANDOM_FOS_YIELD,
    DesignDomain,
    GenResult,
    miles_3sigma_g,
)


@dataclass
class Evaluation:
    name: str
    generator: str
    ok: bool                              # a solid exists, joins wall and part, both solvers ran
    passed: bool = False                  # ok, margins ≥ 0 and f1 ≥ F1_PASS
    reason: str = ""
    mass_g: float | None = None
    volume_cm3: float | None = None
    sigma_mpa: float | None = None        # max over cases and solvers of the voxel-averaged von Mises (margins)
    sigma_peak_mpa: float | None = None   # max nodal von Mises (bolted face excluded): mesh-dependent at corners
    ms_yield: float | None = None         # governing axis: quasi-static 68 g or random vibration (research note §2)
    ms_ult: float | None = None
    f1_hz: float | None = None            # lowest natural frequency (Rayleigh–Ritz, part at its CG), lower solver
    modes: list = field(default_factory=list)  # Ritz modes of the lower solver: f, effective-mass fractions, motion
    axes: list = field(default_factory=list)   # per axis: σ at 68 g, frequency, random 3σ load, factors, margins
    max_disp_mm: float | None = None
    solvers: dict = field(default_factory=dict)   # per solver: cases, f1, seconds
    agreement: dict = field(default_factory=dict)
    gen_seconds: float | None = None
    fea_seconds: float | None = None
    n_nodes: int | None = None
    overhang_fraction: float | None = None
    mesh: tuple | None = field(default=None, repr=False)

    def summary(self) -> dict:
        d = {k: v for k, v in self.__dict__.items() if k != "mesh"}
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
    d[dom.fixed | dom.contact] = 1.0
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


def rayleigh_frequency(dom: DesignDomain, prob, u: np.ndarray, accel) -> tuple[float, np.ndarray]:
    """First natural frequency (Hz) along one axis by Rayleigh's quotient on the static deflection u under that
    axis's inertia load (bracket self-weight + the part's force at its centre of mass): ω² = uᵀf / uᵀMu. The bracket
    mass is lumped to the nodes; the part is a rigid mass at its centre of mass with its inertia, moving with the
    contact faces' RBE3 average (translation u_c and rotation θ from an area-weighted least-squares fit). Rayleigh's
    quotient is an upper bound; with the part's mass dominating it is close. Returns (f, displacement of the part's
    centre of mass)."""
    m_node = _node_masses(dom, prob)
    u_p, theta = _part_motion(dom, prob, u)
    m_p = dom.part_mass_kg * 1e-3                                # t
    I_p = np.asarray(dom.part_inertia_kgm2, float) * 1e3         # kg·m² → t·mm²
    acc = np.asarray(accel, float)
    num = float(m_node @ (u @ acc) + m_p * (u_p @ acc))          # uᵀ f  (N·mm)
    den = float(m_node @ np.sum(u * u, axis=1) + m_p * (u_p @ u_p) + theta @ I_p @ theta)   # uᵀ M u (t·mm²)
    return float(np.sqrt(max(num, 0.0) / den) / (2 * np.pi)) if den > 0 else float("nan"), u_p


def _tet_volumes(prob) -> np.ndarray:
    pt = prob.nodes[prob.tets[:, :4]]
    return np.abs(np.einsum("ij,ij->i", pt[:, 1] - pt[:, 0], np.cross(pt[:, 2] - pt[:, 0], pt[:, 3] - pt[:, 0]))) / 6.0


def _node_masses(dom: DesignDomain, prob) -> np.ndarray:
    """Bracket mass lumped to the nodes (each tet's mass shared equally by its 10 nodes), t."""
    m_node = np.zeros(len(prob.nodes))
    np.add.at(m_node, prob.tets.ravel(), np.repeat(float(dom.material["rho_t_mm3"]) * _tet_volumes(prob) / 10.0, 10))
    return m_node


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


def ritz_modes(dom: DesignDomain, prob, U: list) -> list[dict]:
    """Natural modes of bracket + part by Rayleigh–Ritz on the static deflections U of all load cases (three
    translations, three torques): stiffness Kᵢⱼ = uᵢᵀ fⱼ (exact — K uⱼ = fⱼ), mass Mᵢⱼ = bracket (lumped) + the part
    as a rigid mass and inertia at its centre of mass moving with the contact faces' RBE3 average. Each Ritz
    frequency is an upper bound of the corresponding true one (Poincaré). Per mode: frequency, effective-mass
    fraction along x, y, z (base excitation; of bracket + part) and the dominant motion of the part. Sorted by
    frequency."""
    rho = float(dom.material["rho_t_mm3"])
    vol = _tet_volumes(prob)
    w_body = np.zeros(len(prob.nodes))
    np.add.at(w_body, prob.tets[:, :4].ravel(), np.repeat(-vol / 20.0, 4))
    np.add.at(w_body, prob.tets[:, 4:].ravel(), np.repeat(vol / 5.0, 6))
    m_node = _node_masses(dom, prob)
    m_p = dom.part_mass_kg * 1e-3
    I_p = np.asarray(dom.part_inertia_kgm2, float) * 1e3
    Phi = [np.asarray(u, float) for u in U]
    mot = [_part_motion(dom, prob, u) for u in Phi]
    F = [_load_vector(prob, c, rho, w_body) for c in prob.load_cases]
    n = len(Phi)
    K = np.array([[float(np.sum(Phi[i] * F[j])) for j in range(n)] for i in range(n)])
    M = np.array([[float(m_node @ np.sum(Phi[i] * Phi[j], axis=1) + m_p * (mot[i][0] @ mot[j][0])
                         + mot[i][1] @ I_p @ mot[j][1]) for j in range(n)] for i in range(n)])
    L = np.array([[float(m_node @ Phi[i][:, k] + m_p * mot[i][0][k]) for k in range(3)] for i in range(n)])  # Φᵀ M r
    K, M = 0.5 * (K + K.T), 0.5 * (M + M.T)
    s, V = np.linalg.eigh(M)                       # M-orthonormal basis of the trial space (drops dependent shapes)
    keep = s > 1e-10 * s.max()
    T = V[:, keep] / np.sqrt(s[keep])
    lam, W = np.linalg.eigh(T.T @ K @ T)
    C = T @ W                                      # columns: modes as combinations of the trial shapes, Cᵀ M C = I
    m_tot = float(m_node.sum() + m_p)
    sq = np.sqrt(np.diag(I_p))
    modes = []
    for k in range(C.shape[1]):
        c = C[:, k]
        up = sum(ci * mi[0] for ci, mi in zip(c, mot))
        th = sum(ci * mi[1] for ci, mi in zip(c, mot))
        rot = float(th @ I_p @ th) > m_p * float(up @ up)
        kind = (f"part rotates about {'xyz'[int(np.argmax(np.abs(th) * sq))]}" if rot
                else f"part moves along {'xyz'[int(np.argmax(np.abs(up)))]}")
        modes.append({"f_hz": float(np.sqrt(max(lam[k], 0.0)) / (2 * np.pi)),
                      "eff_mass_frac": ((c @ L) ** 2 / m_tot).tolist(), "motion": kind})
    return modes


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


def voxel_stress(dom: DesignDomain, prob, S: np.ndarray) -> float:
    """Peak von Mises of the stress averaged over each design voxel (cube of side h, the resolution of the design).
    Nodal peaks of voxel-built solids sit at sharp corners — the staircase of the voxels, the edge of the clamped face,
    the edge of the uniform load patch — and grow without bound as the mesh is refined (linear-elastic corner
    singularities, measured +30 … +70 % per refinement). The voxel average is a fixed physical volume, so it converges
    with the mesh and is what a design resolved to h can claim; features finer than h (fillets) are for the detailed
    design. Volume-weighted average of the nodal tensors (each tet's volume shared over its 10 nodes), then von
    Mises; nodes on the bolted face are excluded as before."""
    nodes, tets = prob.nodes, prob.tets
    p = nodes[tets[:, :4]]
    vol = np.abs(np.einsum("ij,ij->i", p[:, 1] - p[:, 0], np.cross(p[:, 2] - p[:, 0], p[:, 3] - p[:, 0]))) / 6.0
    w = np.zeros(len(nodes))
    np.add.at(w, tets.ravel(), np.repeat(vol / 10.0, 10))
    if prob.exclude_nodes is not None and len(prob.exclude_nodes):
        w[np.asarray(prob.exclude_nodes)] = 0.0
    idx = np.floor((nodes - dom.origin) / dom.h).astype(np.int64)
    idx = np.clip(idx, 0, np.array(dom.shape) - 1)
    key = np.ravel_multi_index(idx.T, dom.shape)
    n = int(np.prod(dom.shape))
    W = np.bincount(key, weights=w, minlength=n)
    acc = np.zeros((n, 9))
    np.add.at(acc, key, (S.reshape(-1, 9) * w[:, None]))
    ok = W > 0
    return float(_vm((acc[ok] / W[ok, None]).reshape(-1, 3, 3)).max())


def evaluate(dom: DesignDomain, gen: GenResult, solvers=("ccx", "ngs"), threads: int = 2,
             h_fea: float | None = None) -> Evaluation:
    from ..fea import ccx, ngs
    ev = Evaluation(dom.name, gen.generator, False, gen_seconds=gen.seconds)
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
    res, vox, freq, modes = {}, {}, {}, {}
    n_ax = len(dom.load_cases())                     # the 68 g cases; the torque cases after them are trial shapes
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
        vox[s] = [voxel_stress(dom, prob, _tensor(S)) for S in fields.stress[:n_ax]]
        freq[s] = [rayleigh_frequency(dom, prob, np.asarray(U, float), c.body_accel_mm_s2)
                   for U, c in zip(fields.displacement[:n_ax], prob.load_cases[:n_ax])]
        modes[s] = ritz_modes(dom, prob, fields.displacement)
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
                         "notes": list(r.notes)}
    for k, v in score(ev.solvers, dom.material).items():
        setattr(ev, k, v)
    ev.sigma_peak_mpa = max(c.max_vm_filtered_mpa for r in res.values() for c in r.cases)
    ev.max_disp_mm = max(c.max_disp_mm for r in res.values() for c in r.cases)
    if len(res) == 2:
        a, b = res["ccx"], res["ngs"]
        ev.agreement = {
            "disp_rel": max(abs(x.max_disp_mm - y.max_disp_mm) / max(y.max_disp_mm, 1e-30) for x, y in zip(a.cases, b.cases)),
            "sigma_rel": max(abs(x - y) / max(y, 1e-30) for x, y in zip(vox["ccx"], vox["ngs"])),
            "sigma_peak_rel": max(abs(x.max_vm_filtered_mpa - y.max_vm_filtered_mpa) / max(y.max_vm_filtered_mpa, 1e-30)
                                  for x, y in zip(a.cases, b.cases)),
            "f1_rel": max(abs(x["f_hz"] - y["f_hz"]) / max(y["f_hz"], 1e-30) for x, y in zip(modes["ccx"], modes["ngs"]))}
    ev.ok = True
    return ev


def random_load_g(modes: list[dict], k: int) -> tuple[float, dict, float, float]:
    """Random-vibration 3σ load factor (g) along axis k for the whole mass: the larger of
    * Miles at the dominant mode (the one with the largest effective mass along k) — the usual practice, applied to
      the full mass although that mode carries only part of it, and
    * the SRSS of the modal base forces, √Σ (mₑ,ᵢ/m · 3σ(fᵢ))² — every mode with its own Miles response; it exceeds
      the first only when modes share the axis, e.g. above 800 Hz, where the GEVS spectrum rolls off and a lower
      mode with much of the mass responds more strongly.
    Returns (load, dominant mode, Miles at it, SRSS)."""
    top = max(modes, key=lambda md: md["eff_mass_frac"][k])
    n_dom = miles_3sigma_g(top["f_hz"])
    n_srss = float(np.sqrt(sum((md["eff_mass_frac"][k] * miles_3sigma_g(md["f_hz"])) ** 2 for md in modes)))
    return max(n_dom, n_srss), top, n_dom, n_srss


def score(solvers: dict, material: dict) -> dict:
    """Margins and pass/fail from the solver results (Evaluation.solvers: per solver its 68 g cases with the
    voxel-averaged stress, and its Ritz modes), so a saved evaluation can be scored again without the FE runs.

    Per axis: σ is the larger solver's voxel average at 68 g; the random-vibration load (research note §2;
    random_load_g) is the larger of the two solvers'. Design factors: yield max(1.25·68 g, 1.6·3σ), ultimate
    max(1.4·68 g, 1.8·3σ); stresses scale linearly from the 68 g analysis. f1 is the lowest mode of any kind (lower
    solver)."""
    sv = {s: d for s, d in solvers.items() if isinstance(d, dict) and d.get("modes")}
    names = [c["name"] for c in next(iter(sv.values()))["cases"] if c.get("voxel_vm_mpa") is not None]
    axes = []
    for k, name in enumerate(names):
        sig = max(d["cases"][k]["voxel_vm_mpa"] for d in sv.values())
        n3, md, n_dom, n_srss = max((random_load_g(d["modes"], k) for d in sv.values()), key=lambda x: x[0])
        ny, nu = max(FOS_YIELD * LIMIT_G, RANDOM_FOS_YIELD * n3), max(FOS_ULT * LIMIT_G, RANDOM_FOS_ULT * n3)
        axes.append({"case": name, "sigma_68g_mpa": sig, "f_hz": md["f_hz"], "eff_mass_frac": md["eff_mass_frac"][k],
                     "random_dominant_g": n_dom, "random_srss_g": n_srss,
                     "f_rayleigh_hz": min((d["cases"][k]["f_rayleigh_hz"] for d in sv.values()
                                           if d["cases"][k].get("f_rayleigh_hz")), default=None),
                     "random_3sigma_g": n3, "yield_factor_g": ny, "ult_factor_g": nu,
                     "governs": "random" if RANDOM_FOS_YIELD * n3 > FOS_YIELD * LIMIT_G else "quasi-static",
                     "ms_yield": material["yield_mpa"] / (sig * ny / LIMIT_G) - 1.0,
                     "ms_ult": material["ultimate_mpa"] / (sig * nu / LIMIT_G) - 1.0})
    low = min(sv, key=lambda s: sv[s]["modes"][0]["f_hz"])
    out = {"axes": axes, "sigma_mpa": max(a["sigma_68g_mpa"] for a in axes),
           "f1_hz": sv[low]["modes"][0]["f_hz"], "modes": sv[low]["modes"],
           "ms_yield": min(a["ms_yield"] for a in axes), "ms_ult": min(a["ms_ult"] for a in axes)}
    fails = []
    if out["ms_yield"] < 0:
        fails.append(f"MS yield {out['ms_yield']:+.2f}")
    if out["ms_ult"] < 0:
        fails.append(f"MS ultimate {out['ms_ult']:+.2f}")
    if out["f1_hz"] < F1_PASS:
        fails.append(f"f1 {out['f1_hz']:.0f} Hz < {F1_PASS:.0f}")
    out["passed"], out["reason"] = not fails, "; ".join(fails)
    return out
