"""Check a bracket that holds several parts (gd.multi) with two FEA solvers under a launch environment.

Same method as gd.evaluate (one part), extended to several parts:

1. Solid: passives imposed; the user's rule first — every held part's contact voxels must lie in a 6-connected piece
   of solid that contains bolted voxels (gd.multi.load_path); islands without bolted voxels are dropped; marching
   cubes (iso 0.5) on the voxel grid. Where a triangle cuts a held part (FCL; a cut voxel corner can reach into a void
   voxel next to the part), the void corners of its cube are lowered until it no longer does (the surface moves back
   into the solid voxels; up to PULL_ROUNDS times), else the part is subtracted. Combined brackets: every triangle is
   assigned to one certified box (gd.multi: the region is eroded so that this holds) and its vertices clamped into it
   (1 µm at most, float rounding). The minimum distance to each held part is recorded (FCL, numeric).
2. FE problem on exactly that surface (gmsh, quadratic tets): bolted faces = the faces on the bolted plane (combined)
   or on each part's target plane under its own footprint (one piece); per part its load faces = the faces next to its
   surface inside its own reserved box. Cases: the three 68 g cases with every part loaded at once at its centre of
   mass (force plus moment, RBE3-like) and the bracket's own weight; then the Ritz trial cases — per part the three
   68 g forces and three torques alone, and the three self-weight cases alone.
3. NGSolve solves every case with one factorisation (back-substitutions; the fields are reduced to voxel tensors as
   they come). CalculiX solves the three 68 g cases (no rigid-body or rotary-inertia elements are used anywhere: the
   parts are rigid masses only in the Ritz mass matrix, as for one part). The two are compared on those cases.
4. Modes: Rayleigh–Ritz on the 6 n + 3 trial shapes, each part a rigid mass with its inertia at its centre of mass,
   moving with its own contact faces' RBE3 average. Dynamics (random CQC / Segalman, sine, shock ESTIMATE) as for one
   part, per held part its acceleration; bolts per bolted face (forces in the face's own frame: tension along its
   normal, shear in it).
5. score() of gd.evaluate for the whole bracket and for each held part's own region (the voxels and bolts in its
   reserved box): margins, governing check. The quasi-static level is the preset's for the LIGHTEST held part (the
   largest MAC load factor, applied to all parts at once: conservative, ASSUMED).
"""
from __future__ import annotations

import time

import numpy as np

from . import bolts as _bolts
from . import environment as _env
from .domain import CONTACT_GAP, LIMIT_G
from .evaluate import _body_weights, _load_vector, _tensor, refine_long_edges, score
from .multi import MultiDomain, load_path
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

BOX_TOL = 1e-6           # mm: a marching-cubes vertex "on" a box face (float rounding of grid arithmetic)


# =================================================================================================== solid
def _components(f: np.ndarray, nv: int) -> tuple[int, np.ndarray]:
    """Connected components of a triangle mesh (faces sharing a vertex): (count, label per face)."""
    import scipy.sparse as sp
    from scipy.sparse.csgraph import connected_components
    nf = len(f)
    rows = np.repeat(np.arange(nf), 3)
    A = sp.csr_matrix((np.ones(3 * nf), (rows, f.ravel())), shape=(nf, nv))
    n, lab = connected_components(A @ A.T, directed=False)
    return n, lab


def closed_mesh(f: np.ndarray) -> bool:
    """Every undirected edge in exactly two triangles, used once in each direction (a closed, oriented 2-manifold
    surface as far as edges tell)."""
    e = np.concatenate([f[:, [0, 1]], f[:, [1, 2]], f[:, [2, 0]]])
    key = np.sort(e, axis=1)
    _, cnt = np.unique(key, axis=0, return_counts=True)
    if not np.all(cnt == 2):
        return False
    _, cnt_d = np.unique(e, axis=0, return_counts=True)
    return bool(np.all(cnt_d == 1))


def assign_boxes(dom: MultiDomain, v: np.ndarray, f: np.ndarray):
    """Combined brackets: the certified box of every triangle (all three vertices in it, BOX_TOL), and the vertices
    clamped into the boxes of all their triangles. Returns (v, box index per face) or raises ValueError."""
    boxes = np.array([b["box"] for b in dom.boxes], float)
    nb = len(boxes)
    inside = np.stack([np.all((v >= boxes[k, :3] - BOX_TOL) & (v <= boxes[k, 3:] + BOX_TOL), axis=1)
                       for k in range(nb)])                       # (nb, nv)
    tri_in = inside[:, f].all(axis=2)                             # (nb, nf)
    if not tri_in.any(axis=0).all():
        bad = int((~tri_in.any(axis=0)).sum())
        raise ValueError(f"{bad} triangles lie in no certified box of {dom.name}")
    which = np.argmax(tri_in, axis=0)
    lo = np.full(v.shape, -np.inf)
    hi = np.full(v.shape, np.inf)
    for k in range(nb):
        vs = np.unique(f[which == k])
        if len(vs):
            lo[vs] = np.maximum(lo[vs], boxes[k, :3])
            hi[vs] = np.minimum(hi[vs], boxes[k, 3:])
    if np.any(lo > hi + BOX_TOL):
        raise ValueError("a vertex lies in no common part of its triangles' boxes")
    out = np.clip(v, lo, np.maximum(lo, hi))
    return out, which


def solid_from_density(dom: MultiDomain, density: np.ndarray, joined: np.ndarray | None = None):
    """((v, f), info) of the solid, or (None, info with the reason). `joined`: a solid mask that replaces the
    thresholded density (one piece, after gd.multi.join): voxels in it get density max(d, 1)."""
    from scipy import ndimage
    d = np.clip(np.asarray(density, float), 0.0, 1.0).copy()
    if d.shape != tuple(dom.shape):
        return None, {"reason": f"density shape {d.shape} ≠ grid {tuple(dom.shape)}"}
    if joined is not None:
        d[np.asarray(joined, bool)] = 1.0
    d[dom.void] = 0.0
    d[dom.passive_solid()] = 1.0
    solid = d >= 0.5
    lp = load_path(dom, solid)
    info = {"load_path": lp}
    bad = [p for p, x in lp.items() if not x["ok"]]
    if bad:
        info["reason"] = ("refused (a part must be held by the bracket, never only by another part): "
                          + "; ".join(f"{p}: {lp[p]['loose']} of {lp[p]['contact']} contact voxels not joined to "
                                      "the bolted layer" for p in bad))
        return None, info
    lab, _ = ndimage.label(solid)
    keep = np.unique(lab[dom.fixed & solid])
    keep = keep[keep > 0]
    d = np.where(np.isin(lab, keep) | (d < 0.5), d, 0.0)
    info["islands_dropped_voxels"] = int((solid & ~np.isin(lab, keep)).sum())
    P = np.pad(d, 1)
    planes = _bolted_planes(dom)
    v, f, good = _surface(dom, P, planes)
    if not good:
        info["reason"] = "the solid does not reach the bolted face"
        return None, info
    if not closed_mesh(f):
        info["reason"] = "the marching-cubes surface is not closed"
        return None, info
    # a marching-cubes surface can reach into a void voxel next to a part (the cut corners of a voxel). Where it cuts
    # a held part, the void corners of those cubes are lowered (the vertices on their edges move towards the solid
    # voxel's centre; no voxel changes side) until it no longer does; failing that the part is subtracted (as the
    # per-part designs do, gd.evaluate)
    rounds = corners = 0
    while rounds < PULL_ROUNDS:
        hit = _part_hit_triangles(dom, v, f)
        if not len(hit):
            break
        rounds += 1
        corners += _pull_back(dom, P, v, f, hit)
        v, f, good = _surface(dom, P, planes)
        if not good or not closed_mesh(f):
            info["reason"] = "the marching-cubes surface is not closed after pulling it back from a held part"
            return None, info
    if rounds:
        info["pulled_back"] = {"rounds": rounds, "voxel_corners": corners}
    touching = [p for p in dom.parts if held_part_distances(dom, v, f, [p])[p.pid]["intersects"]]
    if touching:
        try:
            v, f = _subtract(v, f, touching)
        except Exception as exc:  # noqa: BLE001 - a boolean that fails is that design's result
            info["reason"] = f"the solid touches held part(s) {', '.join(p.pid for p in touching)} and subtracting " \
                             f"them failed ({exc!r})"
            return None, info
        info["subtracted_parts"] = [p.pid for p in touching]
        n, labf = _components(f, len(v))
        good = [c for c in range(n) if any(np.any(np.abs(v[np.unique(f[labf == c])][:, ax] - pl) < 1e-6)
                                           for ax, pl in planes)]
        f = f[np.isin(labf, good)]
        used, inv = np.unique(f, return_inverse=True)
        v, f = v[used], inv.reshape(-1, 3).astype(np.int64)
        if not good or not closed_mesh(f):
            info["reason"] = "the solid with the held parts subtracted is not a closed solid on the bolted face"
            return None, info
    info["surface_pieces"] = len(good)
    if len(good) > 1:                             # one print: the bracket must be one connected solid
        info["reason"] = (f"not one piece: {len(good)} separate solids (the region between them does not connect "
                          "them)")
        return None, info
    if dom.kind == "combined":
        try:
            v, which = assign_boxes(dom, v, f)
        except ValueError as exc:
            info["reason"] = str(exc)
            return None, info
        info["triangles_per_box"] = {dom.boxes[k]["name"]: int((which == k).sum()) for k in range(len(dom.boxes))}
    else:
        lo, hi = dom.origin, dom.origin + np.asarray(dom.shape) * dom.h
        v = np.clip(v, lo, hi)                                    # the grid lies on the inner planes
    hits = held_part_distances(dom, v, f)
    info["held_part_distance_mm"] = {p: (0.0 if x["intersects"] else x["distance_mm"]) for p, x in hits.items()}
    return (v, f), info


PULL_ROUNDS = 6          # times the void corners of the cubes whose triangles cut a held part are lowered (0 → −1 →
#                          −3 …: the vertex on a solid–void edge moves to 1/4, 1/8 … of the edge from the solid centre)
_CUBE = np.array([[i, j, k] for i in (0, 1) for j in (0, 1) for k in (0, 1)])


def _surface(dom: MultiDomain, P: np.ndarray, planes):
    """Marching cubes (iso 0.5) on the padded field P; the pieces that touch a bolted plane (islands at voxel-edge
    contacts can remain). Returns (v, f, list of the pieces kept)."""
    from skimage.measure import marching_cubes
    verts, faces, _, _ = marching_cubes(P, level=0.5, spacing=tuple(float(x) for x in dom.h), allow_degenerate=False)
    v = np.asarray(verts, float) + dom.origin - 0.5 * dom.h
    f = np.asarray(faces, np.int64)
    tv = v[f]
    if np.einsum("ij,ij->i", tv[:, 0], np.cross(tv[:, 1], tv[:, 2])).sum() < 0:
        f = f[:, ::-1]
    n, labf = _components(f, len(v))
    good = [c for c in range(n) if any(np.any(np.abs(v[np.unique(f[labf == c])][:, ax] - pl) < 1e-6)
                                       for ax, pl in planes)]
    f = f[np.isin(labf, good)]
    used, inv = np.unique(f, return_inverse=True)
    return v[used], inv.reshape(-1, 3).astype(np.int64), good


def _part_hit_triangles(dom: MultiDomain, v, f) -> np.ndarray:
    """Indices of the surface triangles that cut a held part (FCL triangle–triangle contacts)."""
    import fcl
    s = _fcl_object(v, f)
    lo, hi = v.min(0), v.max(0)
    req = fcl.CollisionRequest(num_max_contacts=10 ** 6, enable_contact=True)
    hit = set()
    for p in dom.parts:
        if np.any(p.v.min(0) > hi + 1.0) or np.any(p.v.max(0) < lo - 1.0):
            continue
        res = fcl.CollisionResult()
        if fcl.collide(s, _fcl_object(p.v, p.f), req, res):
            hit.update(int(c.b1) for c in res.contacts)
    return np.array(sorted(hit), np.int64)


def _pull_back(dom: MultiDomain, P: np.ndarray, v, f, tris) -> int:
    """Lower the void corners (value < 0.5) of the grid cubes holding the given triangles: 0 → −1, −1 → −3 … (in
    place). Returns the number of corners lowered."""
    h = np.asarray(dom.h, float).reshape(3)
    q = (v[f[tris]].mean(axis=1) - dom.origin) / h + 0.5            # padded index coordinates of the centroids
    cube = np.floor(q).astype(np.int64)
    c = np.unique((cube[:, None, :] + _CUBE[None]).reshape(-1, 3), axis=0)
    c = c[np.all((c >= 0) & (c < np.array(P.shape)), axis=1)]
    val = P[tuple(c.T)]
    low = val < 0.5
    P[tuple(c[low].T)] = 2.0 * np.minimum(val[low], 0.0) - 1.0
    return int(low.sum())


def _subtract(v, f, parts):
    """The solid minus the given held parts (manifold3d, float64 meshes). The last resort when pulling the surface
    back did not clear a part: the cut can leave slivers that the tetrahedral mesher then refuses (said so)."""
    import manifold3d as m3

    def man(vv, ff):
        return m3.Manifold(m3.Mesh64(np.ascontiguousarray(vv, np.float64), np.ascontiguousarray(ff, np.uint64)))
    s = man(v, f)
    for p in parts:
        s = s - man(p.v, p.f)
    mesh = s.to_mesh64()
    return np.asarray(mesh.vert_properties, float)[:, :3].copy(), np.asarray(mesh.tri_verts).astype(np.int64)


def _fcl_object(vv, ff):
    import fcl
    m = fcl.BVHModel()
    m.beginModel(len(vv), len(ff))
    m.addSubModel(np.ascontiguousarray(vv, float), np.ascontiguousarray(ff, np.int32))
    m.endModel()
    return fcl.CollisionObject(m, fcl.Transform())


def _bolted_planes(dom: MultiDomain) -> list[tuple[int, float]]:
    if dom.kind == "combined":
        return [(int(dom.axis), float(dom.plane_mm))]
    return sorted({(p.axis, p.plane) for p in dom.parts})


def held_part_distances(dom: MultiDomain, v, f, parts=None) -> dict:
    """Per held part (all, or `parts`): does the solid intersect or touch it (FCL), and the minimum distance (FCL;
    numeric, not a proof)."""
    import fcl
    s = _fcl_object(v, f)
    out = {}
    lo, hi = v.min(0), v.max(0)
    for p in (dom.parts if parts is None else parts):
        plo, phi = p.v.min(0), p.v.max(0)
        if np.any(plo > hi + 5.0) or np.any(phi < lo - 5.0):
            out[p.pid] = {"intersects": False, "distance_mm": None}
            continue
        o = _fcl_object(p.v, p.f)
        hit = fcl.collide(s, o, fcl.CollisionRequest(), fcl.CollisionResult()) > 0
        d = None if hit else float(fcl.distance(s, o, fcl.DistanceRequest(), fcl.DistanceResult()))
        out[p.pid] = {"intersects": bool(hit), "distance_mm": d}
    return out


# =================================================================================================== FE problem
def fea_problem(dom: MultiDomain, v, f, h_fea: float | None = None):
    """FE problem of a designed multi-part solid. Returns (problem with every NGSolve case, meta) — meta: the case
    layout (3 global cases, then per part 3 forces and 3 torques, then 3 self-weight cases), the load faces per part."""
    from scipy.spatial import cKDTree

    from ..fea.mesh import boundary_faces, face_set_moments, mesh_surface
    from ..fea.problem import FeaProblem, LoadCase, Material, SurfaceLoad
    from ..geometry.voxel import surface_samples
    h = float(np.max(dom.h))
    h_fea = h_fea or max(1.5, h)
    v, f = refine_long_edges(v, f, 2.0 * h_fea)
    nodes, tets = mesh_surface(v, f, h_fea, remesh=False)
    faces = boundary_faces(tets)
    p3 = nodes[faces[:, :3]]
    cen = p3.mean(axis=1)
    fixed_mask = np.zeros(len(faces), bool)
    if dom.kind == "combined":
        fixed_mask = np.all(np.abs(p3[:, :, dom.axis] - dom.plane_mm) < 1e-4, axis=1)
    else:
        for p in dom.parts:
            lat = [a for a in range(3) if a != p.axis]
            on = np.all(np.abs(p3[:, :, p.axis] - p.plane) < 1e-4, axis=1)
            foot = np.all((cen[:, lat] >= p.box[lat] - 1e-6) & (cen[:, lat] <= p.box[[3 + a for a in lat]] + 1e-6),
                          axis=1)
            fixed_mask |= on & foot
    load_sets = []
    for p in dom.parts:
        tree = cKDTree(surface_samples(p.v, p.f, float(np.min(dom.h)) / 4))
        dist, _ = tree.query(cen)
        grow = float(np.max(dom.h))
        inbox = np.all((cen >= p.box[:3] - grow) & (cen <= p.box[3:] + grow), axis=1)
        m = (dist < CONTACT_GAP + 1.0 * h + 1e-6) & inbox & ~fixed_mask
        load_sets.append(faces[m])
    fixed = faces[fixed_mask]
    if not len(fixed):
        raise ValueError("no bolted faces on the meshed solid")
    empty = [p.pid for p, ls in zip(dom.parts, load_sets) if not len(ls)]
    if empty:
        raise ValueError(f"no contact faces on the meshed solid for {', '.join(empty)}")
    m = dom.material
    mat = Material(m["name"], m["E_mpa"], m["nu"], m["rho_t_mm3"], m.get("yield_mpa"), m.get("ultimate_mpa"))
    cases = []
    cl = [face_set_moments(nodes, ls)[1] for ls in load_sets]
    gl = dom.load_cases()
    for c in gl:                                                    # 1. the three 68 g cases, every part at once
        sls = [SurfaceLoad(ls, np.asarray(F, float), np.cross(np.asarray(p.com, float) - cc, np.asarray(F, float)))
               for p, ls, cc, F in zip(dom.parts, load_sets, cl, c["part_forces_n"])]
        cases.append(LoadCase(c["name"], sls, np.asarray(c["body_accel_mm_s2"], float)))
    for i, (p, ls, cc) in enumerate(zip(dom.parts, load_sets, cl)):   # 2. per part: forces, then torques
        for k, ax in enumerate("xyz"):
            F = np.asarray(gl[k]["part_forces_n"][i], float)
            cases.append(LoadCase(f"{p.pid} {LIMIT_G:.0f} g {ax}", [SurfaceLoad(ls, F, np.cross(p.com - cc, F))],
                                  None))
        arm = max(float(np.linalg.norm(p.com - cc)), 10.0)
        T = p.mass_kg * LIMIT_G * G0 * 1e-3 * arm
        for k, ax in enumerate("xyz"):
            cases.append(LoadCase(f"{p.pid} torque {ax}", [SurfaceLoad(ls, np.zeros(3), T * np.eye(3)[k])], None))
    for k, ax in enumerate("xyz"):                                   # 3. the bracket's own weight alone
        cases.append(LoadCase(f"self-weight {ax}", [], np.asarray(gl[k]["body_accel_mm_s2"], float)))
    prob = FeaProblem(nodes, tets, mat, fixed, cases, n_modes=0, exclude_nodes=np.unique(fixed.ravel()),
                      label=dom.name)
    n = len(dom.parts)
    meta = {"n_global": 3, "trial": list(range(3, 3 + 6 * n + 3)), "load_sets": load_sets,
            "part_force": [[3 + 6 * i + k for k in range(3)] for i in range(n)],
            "part_torque": [[3 + 6 * i + 3 + k for k in range(3)] for i in range(n)],
            "body": [3 + 6 * n + k for k in range(3)]}
    return prob, meta


def global_problem(prob, n_global: int = 3):
    """The same mesh with only the three 68 g cases (CalculiX: one static step per case)."""
    from ..fea.problem import FeaProblem
    return FeaProblem(prob.nodes, prob.tets, prob.material, prob.fixed_faces, prob.load_cases[:n_global], n_modes=0,
                      exclude_nodes=prob.exclude_nodes, label=prob.label)


# =================================================================================================== reductions
class VoxelBins:
    """Volume-weighted voxel averages of nodal stress tensors (gd.evaluate.voxel_tensors, streamed case by case)."""

    def __init__(self, dom: MultiDomain, prob):
        from ..fea.mesh import _tet_geometry
        nodes, tets = prob.nodes, prob.tets
        vol, _ = _tet_geometry(np.asarray(nodes, float), np.asarray(tets, np.int64))
        w = np.zeros(len(nodes))
        np.add.at(w, tets.ravel(), np.repeat(vol / 10.0, 10))
        if prob.exclude_nodes is not None and len(prob.exclude_nodes):
            w[np.asarray(prob.exclude_nodes)] = 0.0
        idx = np.floor((nodes - dom.origin) / dom.h).astype(np.int64)
        idx = np.clip(idx, 0, np.array(dom.shape) - 1)
        self.key = np.ravel_multi_index(idx.T, dom.shape)
        n = int(np.prod(dom.shape))
        W = np.bincount(self.key, weights=w, minlength=n)
        self.ok = W > 0
        self.W = W[self.ok]
        self.w = w
        self.n = n
        self.centres = dom.origin + (np.argwhere(self.ok.reshape(dom.shape)) + 0.5) * dom.h

    def __call__(self, S) -> np.ndarray:
        T = _tensor(S).reshape(-1, 9) * self.w[:, None]
        acc = np.stack([np.bincount(self.key, weights=T[:, c], minlength=self.n) for c in range(9)], axis=1)
        return voigt((acc[self.ok] / self.W[:, None]).reshape(-1, 3, 3))


def mass_gram(nodes, tets, rho: float, U: list, chunk: int = 4000) -> np.ndarray:
    """Gᵢⱼ = ∫ ρ uᵢ·uⱼ dV with the consistent tet10 mass (fea.mesh.tet10_mass_gram), in element chunks (memory)."""
    from ..fea.mesh import _tet10_mass_pattern, _tet_geometry
    k = len(U)
    vol, _ = _tet_geometry(np.asarray(nodes, float), np.asarray(tets, np.int64))
    m = _tet10_mass_pattern()
    G = np.zeros((k, k))
    for s in range(0, len(tets), chunk):
        t = tets[s:s + chunk]
        rv = rho * vol[s:s + chunk]
        for comp in range(3):
            X = np.stack([np.asarray(u, float)[t, comp] for u in U], axis=-1)      # (c, 10, k)
            MX = np.einsum("ab,ebk->eak", m, X)
            G += np.einsum("e,eai,eaj->ij", rv, X, MX)
    return 0.5 * (G + G.T)


def part_motion(nodes, faces, com, u):
    """(translation of the part's centre of mass, rotation) for a displacement field: the RBE3 average of its contact
    faces (gd.evaluate._part_motion with the part's own faces and centre of mass)."""
    from ..fea.mesh import _tri_rule, face_set_moments
    faces = np.asarray(faces)
    A, c, J = face_set_moments(nodes, faces)
    L, wq = _tri_rule()
    N = np.stack([L[:, 0] * (2 * L[:, 0] - 1), L[:, 1] * (2 * L[:, 1] - 1), L[:, 2] * (2 * L[:, 2] - 1),
                  4 * L[:, 0] * L[:, 1], 4 * L[:, 1] * L[:, 2], 4 * L[:, 2] * L[:, 0]], axis=1)
    P = nodes[faces[:, :3]].astype(float)
    area = 0.5 * np.linalg.norm(np.cross(P[:, 1] - P[:, 0], P[:, 2] - P[:, 0]), axis=1)
    X = np.einsum("qk,fkj->fqj", L, P)
    Uq = np.einsum("qk,fkj->fqj", N, np.asarray(u, float)[faces])
    w = area[:, None] * wq[None, :]
    u_c = np.einsum("fq,fqj->j", w, Uq) / A
    theta = np.linalg.solve(J, np.einsum("fq,fqj->j", w, np.cross(X - c, Uq)))
    return u_c + np.cross(theta, np.asarray(com, float) - c), theta


class RitzMulti:
    """Rayleigh–Ritz modes of bracket + several rigid parts (gd.evaluate.Ritz with part motions per part)."""

    def __init__(self, modes, C, f_hz, gamma, part_t, part_r, m_tot, kept):
        self.modes, self.C, self.f_hz, self.gamma = modes, C, f_hz, gamma
        self.part_t, self.part_r, self.m_tot, self.kept = part_t, part_r, m_tot, kept

    @property
    def omega(self):
        return 2.0 * np.pi * self.f_hz

    def eff_mass_sum(self):
        return (self.gamma ** 2).sum(axis=0) / self.m_tot


def ritz_multi(dom: MultiDomain, prob, U: list, F: list, motions: list, cutoff: float = 1e-10) -> RitzMulti:
    """U: trial displacements; F: their load vectors (K uᵢ = Fᵢ); motions[i][p] = (u_cg, θ) of part p in shape i."""
    from .evaluate import _tet_volumes
    rho = float(dom.material["rho_t_mm3"])
    n = len(U)
    M = mass_gram(prob.nodes, prob.tets, rho, U)
    for p_i, p in enumerate(dom.parts):
        m_p = p.mass_kg * 1e-3
        I_p = np.asarray(p.inertia, float) * 1e3
        ut = np.array([mo[p_i][0] for mo in motions])
        th = np.array([mo[p_i][1] for mo in motions])
        M += m_p * ut @ ut.T + th @ I_p @ th.T
    M = 0.5 * (M + M.T)
    w = rho * _body_weights(prob)
    L = np.zeros((n, 3))
    for i, u in enumerate(U):
        L[i] = w @ np.asarray(u, float) + sum(p.mass_kg * 1e-3 * motions[i][k][0] for k, p in enumerate(dom.parts))
    K = np.array([[float(np.sum(np.asarray(U[i], float) * F[j])) for j in range(n)] for i in range(n)])
    K = 0.5 * (K + K.T)
    d = 1.0 / np.sqrt(np.maximum(np.diag(M), 1e-300))
    Ms, Ks = d[:, None] * M * d[None, :], d[:, None] * K * d[None, :]
    s, V = np.linalg.eigh(Ms)
    keep = s > cutoff * s.max()
    T = V[:, keep] / np.sqrt(s[keep])
    lam, W = np.linalg.eigh(T.T @ Ks @ T)
    C = d[:, None] * (T @ W)
    m_tot = float(rho * _tet_volumes(prob).sum() + sum(p.mass_kg for p in dom.parts) * 1e-3)
    part_t = [C.T @ np.array([mo[k][0] for mo in motions]) for k in range(len(dom.parts))]
    part_r = [C.T @ np.array([mo[k][1] for mo in motions]) for k in range(len(dom.parts))]
    gamma = C.T @ L
    modes = []
    for j in range(C.shape[1]):
        ke = []
        for k, p in enumerate(dom.parts):
            I_p = np.asarray(p.inertia, float) * 1e3
            ke.append((p.mass_kg * 1e-3 * float(part_t[k][j] @ part_t[k][j]), float(part_r[k][j] @ I_p @ part_r[k][j]),
                       k))
        tr, rot, k = max(ke, key=lambda x: x[0] + x[1])
        p = dom.parts[k]
        sq = np.sqrt(np.diag(np.asarray(p.inertia, float) * 1e3))
        motion = (f"{p.pid} rotates about {'xyz'[int(np.argmax(np.abs(part_r[k][j]) * sq))]}" if rot > tr
                  else f"{p.pid} moves along {'xyz'[int(np.argmax(np.abs(part_t[k][j])))]}")
        modes.append({"f_hz": float(np.sqrt(max(lam[j], 0.0)) / (2 * np.pi)),
                      "eff_mass_frac": (gamma[j] ** 2 / m_tot).tolist(), "motion": motion})
    return RitzMulti(modes, C, np.array([m["f_hz"] for m in modes]), gamma, part_t, part_r, m_tot, int(keep.sum()))


def _bolt_frames(dom: MultiDomain) -> tuple[np.ndarray, list]:
    """Per bolt: the rotation taking its bolted face's outward normal (wall → bracket) to +z, and its part index."""
    R, owner = [], []
    for k, p in enumerate(dom.parts):
        if p.bolts is None:
            continue
        n = _bolts.outward(p.axis, p.neg)
        a = np.eye(3)[(p.axis + 1) % 3]
        b = np.cross(n, a)
        for _ in range(len(p.bolts)):
            R.append(np.stack([a, b, n]))
            owner.append(k)
    return np.array(R).reshape(-1, 3, 3), owner


def dynamics_multi(dom: MultiDomain, rz: RitzMulti, vox_c, vox_t, B_trial, static_react, thick, envs=None,
                   vox_sel=None, bolt_sel=None, parts_sel=None) -> dict:
    """gd.evaluate.dynamics for several parts, restricted to the voxels vox_sel and bolts bolt_sel (a held part's
    region, or everything). vox_t: (n_v, n_trial, 6) voxel stresses of the trial cases; B_trial: (n_b, n_trial, 3)
    bolt forces (K u, in the bolt's face frame); static_react: (3, n_b, 3) bolt reactions of the 68 g cases (face
    frame); thick: (n_b,) flange thickness at each bolt."""
    envs = list(_env.ENVIRONMENTS.values()) if envs is None else [_env.get(e) for e in envs]
    envs = [e for e in envs if e.response_of is None]
    sel = slice(None) if vox_sel is None else vox_sel
    vt, vc = vox_t[sel], vox_c[sel]
    S_modal = np.einsum("vic,ik->vck", vt, rz.C)
    parts = list(range(len(dom.parts))) if parts_sel is None else list(parts_sel)
    m_light = min(dom.parts[k].mass_kg for k in parts)
    out = {"part_mass_kg": float(m_light), "n_modes": int(rz.C.shape[1]), "trial_kept": rz.kept,
           "eff_mass_sum": rz.eff_mass_sum().tolist(), "presets": {}, "parts": [dom.parts[k].pid for k in parts]}
    B_modal = None
    if B_trial is not None and len(B_trial):
        bs = np.arange(B_trial.shape[0]) if bolt_sel is None else np.asarray(bolt_sel, int)
        if len(bs):
            B_modal = np.einsum("bic,ik->bck", B_trial[bs], rz.C)
            out["bolts"] = {"positions_mm": dom.bolts[bs].tolist(), "n_out": [0.0, 0.0, 1.0],
                            "nodes_per_bolt": [], "static_68g_n": [np.asarray(s)[bs].tolist() for s in static_react],
                            "thickness_mm": np.asarray(thick, float)[bs].tolist(), "frame": "bolted face (normal = z)"}
    n_out = np.array([0.0, 0.0, 1.0])
    P = [pseudo_accel(rz.part_t[k], rz.omega) for k in parts]
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
                acc = [3.0 * float(np.sqrt(max(Pk[j] @ I @ Pk[j], 0.0))) / G0 for Pk in P]
                r = {"sigma3_mpa": 3.0 * float(vm[v]), "voxel_mm": vc[v].tolist(), "accel3_g": max(acc),
                     "accel3_g_parts": dict(zip(out["parts"], acc)), "grms_in": spec.grms()}
                if B_modal is not None:
                    t3, s3 = _bolts.tension_shear_3sigma(vector_cov(B_modal, I), n_out)
                    r["bolt_tension3_n"], r["bolt_shear3_n"] = t3.tolist(), s3.tolist()
                rnd[lvl] = r
            ax["random"] = rnd
            dk = int(np.argmax(g ** 2))
            ax["dominant_f_hz"] = float(rz.f_hz[dk])
            ax["dominant_eff_mass_frac"] = float(g[dk] ** 2 / rz.m_tot)
            ax["miles_g"] = miles_3sigma_g(rz.f_hz[dk], E.random_limit, E.q)
            ax["miles_qual_g"] = miles_3sigma_g(rz.f_hz[dk], E.random_qual, E.q)
            if E.sine is not None:
                sr = sine_response(S_modal, g, rz.f_hz, z, E.sine.f_lo, E.sine.f_hi, E.sine.level_g,
                                   rz.part_t[parts[0]], j, B_modal)
                sr["voxel_mm"] = vc[sr.pop("voxel")].tolist()
                if B_modal is not None:
                    amp = np.asarray(sr.pop("bolt_force_amp_n"))
                    sr["bolt_tension_n"] = np.abs(amp @ n_out).tolist()
                    sr["bolt_shear_n"] = np.linalg.norm(amp - np.outer(amp @ n_out, n_out), axis=1).tolist()
                ax["sine"] = sr
            if E.shock is not None:
                sh = {}
                for lvl, srs in (("limit", E.shock), ("qual", E.shock.scaled_db(E.shock_qual_db))):
                    r = shock_response(S_modal, g, rz.f_hz, z, srs, rz.part_t[parts[0]], j, B_modal)
                    r["voxel_mm"] = vc[r.pop("voxel")].tolist()
                    if B_modal is not None:
                        t3, s3 = _bolts.tension_shear_3sigma(r.pop("bolt_force_cov"), n_out)
                        r["bolt_tension_n"], r["bolt_shear_n"] = (t3 / 3.0).tolist(), (s3 / 3.0).tolist()
                    sh[lvl] = r
                ax["shock"] = sh
            axes.append(ax)
        out["presets"][E.id] = {"axes": axes}
    return out


# =================================================================================================== evaluate
def evaluate(dom: MultiDomain, density: np.ndarray, threads: int = 4, env: str | None = None,
             h_fea: float | None = None, joined: np.ndarray | None = None, run_ccx: bool = True,
             mem_guard=None, ccx_solver: str | None = None) -> dict:
    """The full check of a multi-part design (module docstring). Returns a JSON-ready record (plus "mesh": (v, f) and
    "region scores" per part). `mem_guard(n_dofs, what)`: raises MemoryError when a solve would not fit: the design is
    then "not solved" (NGSolve: its direct factorisation is the leanest NGSolve solver here, measured), CalculiX
    solves with its iterative Cholesky-preconditioned solver if that fits (measured: 441 instead of 742 MB on 201 k
    dofs, within 9e-6 of the direct solution there — but 3.8e-3 on a slender test cantilever: its stopping rule is
    looser on ill-conditioned problems; the agreement with NGSolve is recorded, and the static stress is the larger of
    the two solvers' either way), else it is skipped and said so. ccx_solver forces a choice."""
    from ..fea import ccx, ngs
    t0 = time.perf_counter()
    out = {"name": dom.name, "kind": dom.kind, "ok": False, "passed": False, "material": dom.material.get("id"),
           "parts": [p.pid for p in dom.parts]}
    sol, info = solid_from_density(dom, density, joined)
    out.update({k: v for k, v in info.items() if k != "reason"})
    if sol is None:
        out["reason"] = info.get("reason", "no solid")
        return out
    v, f = sol
    out["mesh"] = (v, f)
    try:
        prob, meta = fea_problem(dom, v, f, h_fea)
    except Exception as exc:  # noqa: BLE001
        out["reason"] = f"meshing failed: {exc}"
        return out
    out["n_nodes"] = len(prob.nodes)
    out["n_tets"] = len(prob.tets)
    out["volume_cm3"] = prob.volume_mm3() / 1e3
    out["mass_g"] = prob.mass_t() * 1e6
    out["mesh_seconds"] = time.perf_counter() - t0
    ndof = 3 * len(prob.nodes)
    if mem_guard is not None:
        try:
            mem_guard(ndof, "NGSolve")
        except MemoryError as exc:
            out["reason"] = f"not solved: {exc}"
            return out
    bins = VoxelBins(dom, prob)
    n_case = len(prob.load_cases)
    vox = [None] * n_case
    U = [None] * n_case

    def keep(k, disp, S):
        vox[k] = bins(S)
        U[k] = np.nan_to_num(disp)
    t1 = time.perf_counter()
    res_ngs, _ = ngs.solve_with_fields(prob, threads=threads, on_case=keep, keep_fields=False)
    out["ngs_seconds"] = time.perf_counter() - t1
    rho = float(dom.material["rho_t_mm3"])
    w_body = _body_weights(prob)
    trial = meta["trial"]
    # load vectors of the trial cases and part motions
    F = [_load_vector(prob, prob.load_cases[k], rho, w_body) for k in trial]
    motions = [[part_motion(prob.nodes, ls, p.com, U[k]) for p, ls in zip(dom.parts, meta["load_sets"])]
               for k in trial]
    rz = ritz_multi(dom, prob, [U[k] for k in trial], F, motions)
    del F
    # CalculiX on the three 68 g cases
    ccx_vm, agreement, res_ccx = None, {}, None
    if run_ccx and ccx.available():
        try:
            solver = ccx_solver or "SPOOLES"
            if mem_guard is not None and ccx_solver is None:
                try:
                    mem_guard(ndof, "CalculiX")
                except MemoryError:
                    mem_guard(ndof, "CalculiX-iterative")
                    solver = "ITERATIVE CHOLESKY"
            out["ccx_solver"] = solver
            gp = global_problem(prob)
            t2 = time.perf_counter()
            for attempt in (1, 2):
                try:
                    res_ccx, fc = ccx.run(gp, threads=threads, solver=solver)
                    break
                except Exception as exc:    # ccx occasionally exits early; the same deck solves when run again
                    if attempt == 2:
                        raise
                    out.setdefault("retries", []).append(str(exc)[:200])
            out["ccx_seconds"] = time.perf_counter() - t2
            ccx_vt = [bins(S) for S in fc.stress]
            ccx_vm = ccx_vt
            agreement = {
                "disp_rel": max(float(np.abs(fc.displacement[k] - U[k]).max() / max(np.abs(U[k]).max(), 1e-30))
                                for k in range(3)),
                "sigma_rel": max(float(np.abs(von_mises_voigt(ccx_vt[k]) - von_mises_voigt(vox[k])).max()
                                       / max(von_mises_voigt(vox[k]).max(), 1e-30)) for k in range(3))}
        except MemoryError as exc:
            out["ccx_skipped"] = str(exc)
        except Exception as exc:  # noqa: BLE001
            out["ccx_failed"] = repr(exc)[:300]
    out["agreement"] = agreement
    # bolts: per-node K u at the bolted nodes of every trial case → nearest bolt, in its face frame
    bolts = dom.bolts
    Rb, bolt_part = _bolt_frames(dom)
    fixed_nodes = prob.fixed_nodes()
    B_trial, static_react, thick = None, None, None
    if len(bolts) and all(res_ngs.cases[k].support_forces_n is not None for k in range(n_case)):
        pos = prob.nodes[fixed_nodes]
        owner = np.argmin(((pos[:, None, :] - bolts[None, :, :]) ** 2).sum(-1), axis=1)
        nb = len(bolts)

        def per_bolt(fn):
            b = np.zeros((nb, 3))
            np.add.at(b, owner, np.asarray(fn, float))
            return np.einsum("bij,bj->bi", Rb, b)
        Fg = [_load_vector(prob, prob.load_cases[k], rho, w_body) for k in range(3)]
        B_trial = np.stack([per_bolt(res_ngs.cases[k].support_forces_n) for k in trial], axis=1)
        static_react = [per_bolt(res_ngs.cases[k].support_forces_n - Fg[k][fixed_nodes]) for k in range(3)]
        thick = np.full(nb, _bolts.FLANGE_T)
        for k, p in enumerate(dom.parts):
            if p.bolts is not None and len(p.bolts):
                ix = [i for i, o in enumerate(bolt_part) if o == k]
                thick[ix] = _bolts.thickness_at(v, f, p.bolts, p.axis, p.neg)
    vox_t = np.stack([vox[k] for k in trial], axis=1)                 # (n_v, n_trial, 6)
    vox_c = bins.centres
    E = _env.get(env)
    # static stress of the 68 g cases: the larger solver's voxel von Mises, per region
    vm_g = [von_mises_voigt(vox[k]) for k in range(3)]
    if ccx_vm is not None:
        vm_g = [np.maximum(a, von_mises_voigt(b)) for a, b in zip(vm_g, ccx_vm)]

    def region_score(vsel, bsel, psel, label):
        dyn = dynamics_multi(dom, rz, vox_c, vox_t, B_trial, static_react, thick, vox_sel=vsel, bolt_sel=bsel,
                             parts_sel=psel)
        cases = [{"name": prob.load_cases[k].name, "voxel_vm_mpa": float(vm_g[k][vsel].max()) if
                  (vsel is None or np.any(vsel)) else 0.0, "f_rayleigh_hz": None} for k in range(3)]
        sv = {"ngs": {"modes": rz.modes, "cases": cases, "dynamics": dyn}}
        r = score(sv, dom.material, E.id)
        r["region"] = label
        return r, dyn
    whole, dyn_all = region_score(None, None, None, "whole bracket")
    regions = {}
    for k, p in enumerate(dom.parts):
        vsel = np.all((vox_c >= p.box[:3]) & (vox_c <= p.box[3:]), axis=1)
        bsel = [i for i, o in enumerate(bolt_part) if o == k]
        if not vsel.any():
            continue
        r, d = region_score(vsel, bsel, [k], p.pid)
        regions[p.pid] = {key: r[key] for key in ("ms_yield", "ms_ult", "ms_bolt", "governing", "passed", "reason",
                                                  "margins")}
        regions[p.pid]["accel3_g"] = [ax["random"]["limit"]["accel3_g"] for ax in d["presets"][E.response_id]["axes"]]
    for key, val in whole.items():
        out[key] = val
    out["parts_detail"] = regions
    out["f1_hz"] = rz.modes[0]["f_hz"] if rz.modes else None
    out["modes"] = rz.modes[:12]
    out["trial_cases"] = len(trial)
    out["solvers"] = {"ngs": {"solver": res_ngs.solver, "seconds": res_ngs.seconds, "cases": n_case,
                              "f1_hz": out["f1_hz"]}}
    if res_ccx is not None:
        out["solvers"]["ccx"] = {"solver": res_ccx.solver, "seconds": res_ccx.seconds, "cases": 3}
    out["accel3_g_parts"] = {p.pid: [ax["random"]["limit"]["accel3_g_parts"][p.pid]
                                     for ax in dyn_all["presets"][E.response_id]["axes"]] for p in dom.parts}
    out["fea_seconds"] = time.perf_counter() - t1
    out["ok"] = True
    out["environment"] = E.id
    return out
