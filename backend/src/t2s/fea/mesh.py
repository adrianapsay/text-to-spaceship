"""Shared quadratic tetrahedral meshing (gmsh) and consistent surface loads for the FEA solvers.

Every solver gets the same `nodes` / `tets` (10-node, gmsh ordering, straight edges: `Mesh.SecondOrderLinear = 1`),
so mid-side nodes are exact edge midpoints; `check_tet10` verifies the ordering instead of trusting documentation.
Meshing runs single-threaded with a fixed seed by default: multi-threaded gmsh gave a different mesh on every call.
"""
from __future__ import annotations

import threading

import numpy as np

from .problem import GMSH_TET10_EDGES

_LOCK = threading.Lock()          # gmsh keeps global state: one model at a time per process


def _start(h: float, threads: int):
    import gmsh
    if not gmsh.isInitialized():
        gmsh.initialize(interruptible=False)
    gmsh.clear()
    gmsh.option.setNumber("General.Terminal", 0)
    gmsh.option.setNumber("General.NumThreads", threads)   # 1 (default): the same input gives the same mesh
    gmsh.option.setNumber("Mesh.RandomSeed", 1)
    gmsh.option.setNumber("Mesh.CharacteristicLengthMin", h * 0.5)
    gmsh.option.setNumber("Mesh.CharacteristicLengthMax", h)
    gmsh.option.setNumber("Mesh.SecondOrderLinear", 1)
    gmsh.option.setNumber("Mesh.Algorithm3D", 1)       # Delaunay
    return gmsh


def _extract_tet10(gmsh) -> tuple[np.ndarray, np.ndarray]:
    gmsh.model.mesh.generate(3)
    gmsh.model.mesh.setOrder(2)
    tags, xyz, _ = gmsh.model.mesh.getNodes()
    nodes = xyz.reshape(-1, 3)
    index = {int(t): i for i, t in enumerate(tags)}
    etypes, _, enodes = gmsh.model.mesh.getElements(3)
    tets = []
    for et, en in zip(etypes, enodes):
        if et == 11:                                        # 10-node tetrahedron
            tets.append(np.array([index[int(t)] for t in en], dtype=np.int64).reshape(-1, 10))
    if not tets:
        raise ValueError("gmsh produced no quadratic tetrahedra")
    tets = np.vstack(tets)
    used = np.unique(tets)                                  # drop nodes of lower-dimensional entities not in tets
    remap = -np.ones(len(nodes), dtype=np.int64)
    remap[used] = np.arange(len(used))
    nodes, tets = nodes[used], remap[tets]
    _orient(nodes, tets)
    check_tet10(nodes, tets)
    return nodes.astype(float), tets


def _orient(nodes, tets) -> None:
    """Make every tet positively oriented (swap corners 1 and 2 with their edge nodes where needed)."""
    p = nodes[tets[:, :4]]
    vol = np.einsum("ij,ij->i", p[:, 1] - p[:, 0], np.cross(p[:, 2] - p[:, 0], p[:, 3] - p[:, 0]))
    neg = vol < 0
    if neg.any():
        t = tets[neg]
        # swapping corners 1<->2 maps edges (0,1)<->(2,0) [4<->6], (1,2) stays [5], (3,1)<->(3,2) [9<->8]
        tets[neg] = t[:, [0, 2, 1, 3, 6, 5, 4, 7, 9, 8]]


def check_tet10(nodes: np.ndarray, tets: np.ndarray, tol: float = 1e-6) -> None:
    """Mid-side nodes must be the midpoints of the edges GMSH_TET10_EDGES names (straight-sided quadratic tets)."""
    for k, (a, b) in enumerate(GMSH_TET10_EDGES):
        mid = 0.5 * (nodes[tets[:, a]] + nodes[tets[:, b]])
        err = np.abs(nodes[tets[:, 4 + k]] - mid).max()
        if err > tol * max(1.0, float(np.abs(nodes).max())):
            raise ValueError(f"tet10 node {4 + k} is not the midpoint of edge {a}-{b} (error {err:.3g} mm)")


def mesh_box(lo, hi, h: float, threads: int = 1):
    with _LOCK:
        gmsh = _start(h, threads)
        lo, hi = np.asarray(lo, float), np.asarray(hi, float)
        gmsh.model.occ.addBox(*lo, *(hi - lo))
        gmsh.model.occ.synchronize()
        return _extract_tet10(gmsh)


def mesh_hollow_cylinder(ri: float, ro: float, length: float, h: float, threads: int = 1):
    """Axis along +z from z = 0 to z = length."""
    with _LOCK:
        gmsh = _start(h, threads)
        outer = gmsh.model.occ.addCylinder(0, 0, 0, 0, 0, length, ro)
        inner = gmsh.model.occ.addCylinder(0, 0, 0, 0, 0, length, ri)
        gmsh.model.occ.cut([(3, outer)], [(3, inner)])
        gmsh.model.occ.synchronize()
        return _extract_tet10(gmsh)


def mesh_surface(v: np.ndarray, f: np.ndarray, h: float, threads: int = 1, remesh: bool = True,
                 algorithms=(10, 4, 1)):
    """Tetrahedralise a closed, consistently oriented triangle mesh (a bracket STL). remesh=False keeps the given
    surface triangles as the boundary of the tet mesh (the solid meshed is exactly the solid given — used for designed
    brackets, whose surface is the certified one). gmsh 3D algorithms are tried in turn until no tetrahedron is
    degenerate: HXT (10) first — on marching-cubes surfaces gmsh's Delaunay (1) left zero-volume slivers that
    CalculiX rejects — then Frontal (4), then Delaunay. A mesh whose worst tetrahedron has quality ≥ 1e-3 is taken at
    once; otherwise the best one, if its worst element is still ≥ 1e-5 (CalculiX rejected elements near 1e-6)."""
    best, err = None, None
    for alg in algorithms:
        try:
            nodes, tets = _mesh_surface_once(v, f, h, threads, remesh, alg)
        except (OSError, RuntimeError, ValueError) as exc:     # gmsh can crash on a surface (access violation):
            err = exc                                           # start it afresh and try the next algorithm
            _reset_gmsh()
            continue
        q = float(tet_quality(nodes, tets).min())
        if q >= 1e-3:
            return nodes, tets
        if best is None or q > best[0]:
            best = (q, nodes, tets)
    if best is None:
        raise ValueError(f"gmsh failed with every algorithm ({err!r})")
    if best[0] >= 1e-5:
        return best[1], best[2]
    raise ValueError(f"degenerate tetrahedra with every gmsh algorithm (best min quality {best[0]:.2e})")


def _reset_gmsh():
    import gmsh
    try:
        if gmsh.isInitialized():
            gmsh.finalize()
    except Exception:  # noqa: BLE001 - a crashed gmsh may not finalise cleanly
        pass


def _mesh_surface_once(v, f, h, threads, remesh, algorithm3d):
    import os
    import tempfile
    from ..geometry.stl_io import write_binary_stl
    with _LOCK:
        gmsh = _start(h, threads)
        gmsh.option.setNumber("Mesh.Algorithm3D", algorithm3d)
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "surface.stl")
            write_binary_stl(p, np.asarray(v, float), np.asarray(f, np.int64))
            gmsh.merge(p)
        if remesh:
            gmsh.model.mesh.classifySurfaces(40 * np.pi / 180, True, True, np.pi)
            gmsh.model.mesh.createGeometry()
        surfaces = [s[1] for s in gmsh.model.getEntities(2)]
        loop = gmsh.model.geo.addSurfaceLoop(surfaces)
        gmsh.model.geo.addVolume([loop])
        gmsh.model.geo.synchronize()
        out = _extract_tet10(gmsh)
        gmsh.clear()                          # the arrays are copies: free gmsh's own model (memory, M4)
        return out


def tet_quality(nodes: np.ndarray, tets: np.ndarray) -> np.ndarray:
    """Shape quality of the corner tetrahedra: 6√2·V / l_rms³ (1 = regular, 0 = flat)."""
    p = nodes[tets[:, :4]]
    vol = np.einsum("ij,ij->i", p[:, 1] - p[:, 0], np.cross(p[:, 2] - p[:, 0], p[:, 3] - p[:, 0])) / 6.0
    l2 = sum(np.sum((p[:, a] - p[:, b]) ** 2, axis=1) for a, b in ((0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (2, 3)))
    return 6.0 * np.sqrt(2.0) * vol / np.sqrt(l2 / 6.0) ** 3


def boundary_faces(tets: np.ndarray) -> np.ndarray:
    """Boundary 6-node triangles as (k, 6): corners (a, b, c) outward-ordered, then mid-nodes (ab, bc, ca)."""
    corner = {0: (1, 2, 3), 1: (0, 3, 2), 2: (0, 1, 3), 3: (0, 2, 1)}       # face opposite each vertex, outward
    edge_node = {}
    for k, (a, b) in enumerate(GMSH_TET10_EDGES):
        edge_node[(a, b)] = 4 + k
        edge_node[(b, a)] = 4 + k
    faces = {}
    for opp, (a, b, c) in corner.items():
        tri = tets[:, [a, b, c, edge_node[(a, b)], edge_node[(b, c)], edge_node[(c, a)]]]
        for row in tri:
            key = tuple(sorted(row[:3].tolist()))
            if key in faces:
                del faces[key]
            else:
                faces[key] = row
    return np.array(list(faces.values()), dtype=np.int64).reshape(-1, 6)


def face_set_moments(nodes: np.ndarray, faces: np.ndarray):
    """(area A, area centroid c, J) of a set of straight triangles, J = ∫ (|r|² I − r rᵀ) dA with r = x − c (exact:
    ∫_T x xᵀ dA = A/12 · (Σ pᵢ pᵢᵀ + s sᵀ), s = Σ pᵢ)."""
    p = nodes[np.asarray(faces)[:, :3]].astype(float)
    a = 0.5 * np.linalg.norm(np.cross(p[:, 1] - p[:, 0], p[:, 2] - p[:, 0]), axis=1)
    A = float(a.sum())
    c = (a[:, None] * p.mean(axis=1)).sum(0) / A
    q = p - c
    s = q.sum(axis=1)
    S = (a[:, None, None] / 12.0 * (np.einsum("fki,fkj->fij", q, q) + np.einsum("fi,fj->fij", s, s))).sum(0)
    return A, c, np.trace(S) * np.eye(3) - S


def traction_field(nodes, faces, total_force, moment=None):
    """(a, ω, c) of the traction t(x) = a + ω × (x − c) carrying `total_force` and `moment` (about the area
    centroid c) on the faces (see problem.SurfaceLoad)."""
    A, c, J = face_set_moments(nodes, faces)
    a = np.asarray(total_force, float) / A
    w = np.zeros(3) if moment is None else np.linalg.solve(J, np.asarray(moment, float))
    return a, w, c


def _tri_rule():
    """Dunavant's degree-5, 7-point rule on the triangle (barycentric points, weights summing to 1)."""
    pts, wts = [(1 / 3, 1 / 3, 1 / 3)], [0.225]
    for a, b, w in ((0.059715871789770, 0.470142064105115, 0.132394152788506),
                    (0.797426985353087, 0.101286507323456, 0.125939180544827)):
        for perm in ((a, b, b), (b, a, b), (b, b, a)):
            pts.append(perm)
            wts.append(w)
    return np.array(pts), np.array(wts)


def consistent_surface_load(nodes: np.ndarray, faces: np.ndarray, total_force, moment=None) -> dict[int, np.ndarray]:
    """Spread a total force over the given 6-node boundary triangles as a traction. Uniform (no moment): for a
    straight-sided quadratic triangle the consistent nodal loads are 0 at the corners and 1/3 of the face's share at
    each mid-side node. With a moment (about the faces' area centroid) the traction is linear (traction_field) and
    the consistent loads ∫ Nᵢ t dA are integrated exactly (degree-5 rule; the integrand is cubic)."""
    total_force = np.asarray(total_force, float)
    if moment is not None and np.any(np.asarray(moment, float)):
        a, w, c = traction_field(nodes, faces, total_force, moment)
        L, wq = _tri_rule()
        P = nodes[faces[:, :3]].astype(float)                                 # (F, 3, 3)
        area = 0.5 * np.linalg.norm(np.cross(P[:, 1] - P[:, 0], P[:, 2] - P[:, 0]), axis=1)
        N = np.stack([L[:, 0] * (2 * L[:, 0] - 1), L[:, 1] * (2 * L[:, 1] - 1), L[:, 2] * (2 * L[:, 2] - 1),
                      4 * L[:, 0] * L[:, 1], 4 * L[:, 1] * L[:, 2], 4 * L[:, 2] * L[:, 0]], axis=1)   # (Q, 6)
        X = np.einsum("qk,fkj->fqj", L, P)                                    # (F, Q, 3) quadrature points
        T = a + np.cross(w, X - c)                                            # (F, Q, 3) traction
        Fn = np.einsum("f,q,qi,fqj->fij", area, wq, N, T)                     # (F, 6, 3) nodal forces
        out: dict[int, np.ndarray] = {}
        for fi in range(len(faces)):
            for k, nidx in enumerate(faces[fi]):
                out[int(nidx)] = out.get(int(nidx), np.zeros(3)) + Fn[fi, k]
        return out
    p = nodes[faces[:, :3]]
    area = 0.5 * np.linalg.norm(np.cross(p[:, 1] - p[:, 0], p[:, 2] - p[:, 0]), axis=1)
    out: dict[int, np.ndarray] = {}
    share = area / area.sum()
    for fi in range(len(faces)):
        for n in faces[fi, 3:]:
            out[int(n)] = out.get(int(n), np.zeros(3)) + total_force * share[fi] / 3.0
    return out


def nodes_where(nodes: np.ndarray, mask_fn) -> np.ndarray:
    return np.flatnonzero(mask_fn(nodes))


# ------------------------------------------------------------------------------------- straight 10-node tetrahedra
# Barycentric shape functions in gmsh order: corners N_a = L_a (2 L_a − 1), mid-side nodes of GMSH_TET10_EDGES
# N_ab = 4 L_a L_b. Both helpers below are exact for straight-sided elements.
_GAUSS4_A, _GAUSS4_B = 0.5854101966249685, 0.1381966011250105      # 4-point rule, degree 2, weights V/4


def _tet_geometry(nodes: np.ndarray, tets: np.ndarray):
    """(volume (m,), barycentric gradients (m, 4, 3)) of the corner tetrahedra."""
    p = nodes[tets[:, :4]].astype(float)
    J = np.stack([p[:, 1] - p[:, 0], p[:, 2] - p[:, 0], p[:, 3] - p[:, 0]], axis=2)    # columns: edge vectors
    vol = np.linalg.det(J) / 6.0
    Ji = np.linalg.inv(J)                                       # rows: ∇L1, ∇L2, ∇L3
    g = np.concatenate([-Ji.sum(axis=1, keepdims=True), Ji], axis=1)
    return np.abs(vol), g


def tet10_shape_gradients(L: np.ndarray, g: np.ndarray) -> np.ndarray:
    """∇N (m, 10, 3) at one barycentric point L (4,) for elements with barycentric gradients g (m, 4, 3)."""
    out = [(4.0 * L[a] - 1.0) * g[:, a] for a in range(4)]
    out += [4.0 * (L[b] * g[:, a] + L[a] * g[:, b]) for a, b in GMSH_TET10_EDGES]
    return np.stack(out, axis=1)


def tet10_internal_forces(nodes: np.ndarray, tets: np.ndarray, u: np.ndarray, E: float, nu: float,
                          elems: np.ndarray | None = None) -> np.ndarray:
    """Nodal internal forces f = K u (n, 3) of linear-elastic isotropic tet10 elements — the force each node needs
    for the displacement u; at a supported node it is the support's (internal) reaction, CalculiX's RF. Assembled
    over `elems` only (default all): the element stresses are linear, so the 4-point rule is exact."""
    nodes, tets = np.asarray(nodes, float), np.asarray(tets, np.int64)
    sel = tets if elems is None else tets[np.asarray(elems, np.int64)]
    vol, g = _tet_geometry(nodes, sel)
    lam, mu = E * nu / ((1 + nu) * (1 - 2 * nu)), E / (2 * (1 + nu))
    ue = np.asarray(u, float)[sel]                              # (m, 10, 3)
    fe = np.zeros_like(ue)
    for q in range(4):
        L = np.full(4, _GAUSS4_B)
        L[q] = _GAUSS4_A
        dN = tet10_shape_gradients(L, g)                        # (m, 10, 3)
        grad = np.einsum("mai,maj->mij", ue, dN)                # ∂u_i/∂x_j
        eps = 0.5 * (grad + np.swapaxes(grad, 1, 2))
        sig = lam * np.trace(eps, axis1=1, axis2=2)[:, None, None] * np.eye(3) + 2 * mu * eps
        fe += (vol / 4.0)[:, None, None] * np.einsum("mij,maj->mai", sig, dN)
    f = np.zeros((len(nodes), 3))
    np.add.at(f, sel.ravel(), fe.reshape(-1, 3))
    return f


def _tet10_mass_pattern() -> np.ndarray:
    """Consistent scalar mass matrix of a straight tet10 / (ρ V): ∫ N_a N_b dV / V (exact; × 1/420)."""
    m = np.zeros((10, 10))
    edges = [set(e) for e in GMSH_TET10_EDGES]
    for a in range(4):
        for b in range(4):
            m[a, b] = 6.0 if a == b else 1.0
        for k, e in enumerate(edges):
            m[a, 4 + k] = m[4 + k, a] = -4.0 if a in e else -6.0
    for i, ei in enumerate(edges):
        for j, ej in enumerate(edges):
            m[4 + i, 4 + j] = 32.0 if i == j else (16.0 if ei & ej else 8.0)
    return m / 420.0


def tet10_mass_gram(nodes: np.ndarray, tets: np.ndarray, rho: float, fields: list) -> np.ndarray:
    """Gram matrix Gᵢⱼ = ∫ ρ uᵢ·uⱼ dV (consistent mass) of nodal vector fields (each (n, 3)) over the mesh."""
    vol, _ = _tet_geometry(np.asarray(nodes, float), np.asarray(tets, np.int64))
    m = _tet10_mass_pattern()
    U = np.stack([np.asarray(u, float)[tets] for u in fields], axis=-1)        # (m, 10, 3, k)
    U = U.reshape(len(tets), 10, -1)                                           # (m, 10, 3k)
    MU = np.einsum("ab,ebk->eak", m, U)
    G = np.einsum("e,eai,eaj->ij", rho * vol, U, MU)                          # (3k, 3k): (node comp, field)
    k = len(fields)
    return G.reshape(3, k, 3, k).trace(axis1=0, axis2=2)
