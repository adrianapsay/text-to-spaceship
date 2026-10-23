"""NGSolve solver for the solver-independent FEA contract (`problem.py`).

Set-up (independent of the CalculiX module; the two are cross-checked):

* Mesh: a netgen mesh of LINEAR tetrahedra built from the 4 corner nodes of the shared tet10 mesh. The shared tets are
  straight-sided (mid-side nodes are exact edge midpoints), so VectorH1(order=2) on the linear mesh spans exactly the
  displacement space of the 10-node elements (NGSolve uses a hierarchical basis: vertex hats plus edge bubbles).
* Boundary: every boundary triangle carries a region name. The given 6-node faces are matched to the boundary
  triangles by their 3 corner nodes; `fixed_faces` regions are Dirichlet (u = 0), the faces of every SurfaceLoad
  (and of every added mass) form a region carrying the uniform traction total_force / area (the smeared mass / area),
  all other boundary triangles are the region "free".
* Statics: K u = f with NGSolve's sparse direct Cholesky ("sparsecholesky"), factorised once and reused by every load
  case; the body acceleration enters as the volume force density rho * a.
* Reactions: R_d = sum over the Dirichlet dofs of (K u - f)_i * c_d,i, with c_d the coefficient vector of the rigid
  translation e_d (the virtual work of the residual under a unit translation = the total support force; with a nodal
  basis this is the plain sum of the nodal reactions). Sign: the force exerted BY the supports ON the part, so in
  equilibrium reaction_n = -applied_n.
* Modes: K x = lambda M x on the free dofs, ARPACK (scipy eigsh) in shift-invert mode with OPinv = NGSolve's sparse
  Cholesky of K - sigma M (sigma = 0 for a supported part, reusing the static factorisation; a small negative shift
  for a free part, whose K is singular). M = rho u.v dx plus, for every `added_masses` entry, the non-structural mass
  smeared uniformly over its faces, (mass / area) u.v ds over their region (mass matrix only: the static cases and
  FeaResult.mass_t ignore it).
* Nodal stress (CaseResult docstring): every element's stress is evaluated at its 10 node positions (corners and
  mid-sides), the stress TENSOR is averaged over the elements sharing a node, von Mises is taken of the average.

Threads: threadpoolctl caps the BLAS pools (numpy/scipy OpenBLAS, NGSolve's OpenBLAS and MKL) to `threads` for the
duration of the solve; NGSolve's own TaskManager (SetNumThreads(threads)) is engaged only for meshes of at least
_TM_MIN_NODES nodes. Measured on the (shared, loaded) i5-12600K development machine with 2 threads: 200x10x6 box,
16k nodes: 2.5 s without the TaskManager vs 5.8-8.0 s with it (a tiny first solve even took 6-12 s with it, spent in
per-task thread wake-ups during the ARPACK iterations); 94k nodes: 33-37 s without vs 28-32 s with it.
"""
from __future__ import annotations

import contextlib
import time
from dataclasses import dataclass

import numpy as np

from .mesh import boundary_faces
from .problem import GMSH_TET10_EDGES, CaseResult, FeaProblem, FeaResult

# netgen's native tets are negatively oriented in the usual sense ((p1-p0).((p2-p0)x(p3-p0)) < 0, i.e. det of
# NGSolve's reference map > 0); the shared mesh is positively oriented, so corners 1 and 2 are swapped when the
# elements are handed to netgen: netgen vertex k = gmsh corner _PERM[k].
_PERM = (0, 2, 1, 3)
_REF_VERTEX = np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0], [0.0, 0.0, 0.0]])  # NGSolve ET_TET
_DIRECT = "sparsecholesky"
_TM_MIN_NODES = 50_000            # below this NGSolve runs single-threaded (faster here, see the module docstring)


def _tet10_reference_points() -> np.ndarray:
    """Reference coordinates (NGSolve's reference tet) of the 10 gmsh-ordered nodes of an element."""
    corner = np.empty((4, 3))
    for k, c in enumerate(_PERM):
        corner[c] = _REF_VERTEX[k]
    mids = [0.5 * (corner[a] + corner[b]) for a, b in GMSH_TET10_EDGES]
    return np.vstack([corner, np.array(mids)])


@dataclass
class NgsFields:
    """Nodal fields of one solve, indexed like problem.nodes (for verification and plotting)."""
    displacement: list[np.ndarray]    # per load case, (n, 3) mm
    stress: list[np.ndarray]          # per load case, (n, 3, 3) MPa, nodal average of the element stress tensors
    von_mises: list[np.ndarray]       # per load case, (n,) MPa (von Mises of the averaged tensor)
    eigenvalues: np.ndarray           # (n_modes,) raw lambda = omega^2 in (rad/s)^2 (rigid modes ~0, may be < 0)


@dataclass
class _Regions:
    dirichlet: str                    # regex of the Dirichlet regions ("" if the part is free)
    n_dirichlet_nodes: int            # distinct tet10 nodes on the fixed faces (= vertices + edges)
    set_regex: list[str]              # per distinct face set (loads, added masses): regex of the regions containing it
    set_area: list[float]             # per distinct face set: area (mm^2)
    case_sets: list[list[int]]        # per load case, per surface load: index of its face set
    mass_sets: list[tuple[int, float]]  # per added mass: (index of its face set, mass_t)
    names: list[str]                  # all boundary region names


def _build_mesh(problem: FeaProblem):
    import ngsolve as ngs
    from netgen.meshing import FaceDescriptor
    from netgen.meshing import Mesh as NGMesh

    nodes = np.asarray(problem.nodes, float)
    tets = np.asarray(problem.tets, np.int64)
    if tets.ndim != 2 or tets.shape[1] != 10:
        raise ValueError("problem.tets must be (m, 10) quadratic tetrahedra in gmsh ordering")
    corners = np.unique(tets[:, :4])
    cmap = np.full(len(nodes), -1, np.int64)
    cmap[corners] = np.arange(len(corners))

    bfaces = boundary_faces(tets)
    nb = len(bfaces)
    index = {k: i for i, k in enumerate(map(tuple, np.sort(bfaces[:, :3], axis=1).tolist()))}

    def lookup(faces, what: str) -> np.ndarray:
        faces = np.asarray(faces, np.int64).reshape(-1, 6)
        ids = []
        for k in map(tuple, np.sort(faces[:, :3], axis=1).tolist()):
            i = index.get(k)
            if i is None:
                raise ValueError(f"{what}: the face with corner nodes {k} is not a boundary face of the mesh")
            ids.append(i)
        return np.unique(np.array(ids, np.int64))

    fixed_ids = lookup(problem.fixed_faces, "fixed_faces")
    set_ids: dict[tuple, int] = {}
    face_sets: list[np.ndarray] = []

    def face_set(faces, what: str) -> int:
        fid = lookup(faces, what)
        key = tuple(fid.tolist())
        if key not in set_ids:
            set_ids[key] = len(face_sets)
            face_sets.append(fid)
        return set_ids[key]

    case_sets = [[face_set(sl.faces, f"load case {case.name!r}, surface load {j}")
                  for j, sl in enumerate(case.surface_loads)] for case in problem.load_cases]
    mass_sets = [(face_set(faces, f"added mass {j}"), float(m))
                 for j, (faces, m) in enumerate(problem.added_masses)]

    # one region per distinct membership signature (fixed?, which load / added-mass face sets), so overlapping sets
    # stay exact
    member = np.zeros((nb, 1 + len(face_sets)), bool)
    member[fixed_ids, 0] = True
    for s, fid in enumerate(face_sets):
        member[fid, 1 + s] = True
    sigs, which = np.unique(member, axis=0, return_inverse=True)
    which = np.asarray(which).ravel()

    ngm = NGMesh(dim=3)
    ngm.AddPoints(np.ascontiguousarray(nodes[corners]))
    ngm.SetMaterial(1, "solid")
    ngm.AddElements(dim=3, index=1, data=np.ascontiguousarray(cmap[tets[:, list(_PERM)]].astype(np.int32)), base=0)
    names: list[str] = []
    for r, sig in enumerate(sigs):
        parts = (["fixed"] if sig[0] else []) + [f"set{s}" for s in np.flatnonzero(sig[1:])]
        name = "_".join(parts) if parts else "free"
        names.append(name)
        ngm.Add(FaceDescriptor(surfnr=r + 1, domin=1, domout=0, bc=r + 1))
        ngm.SetBCName(r, name)
        tri = bfaces[which == r, :3]                      # outward-ordered corners (netgen: normal points out of domin)
        ngm.AddElements(dim=2, index=r + 1, data=np.ascontiguousarray(cmap[tri].astype(np.int32)), base=0)
    mesh = ngs.Mesh(ngm)
    if mesh.ne != len(tets) or mesh.nv != len(corners):
        raise RuntimeError(f"netgen mesh has {mesh.ne} elements / {mesh.nv} vertices, expected "
                           f"{len(tets)} / {len(corners)}")

    p = nodes[bfaces[:, :3]]
    tri_area = 0.5 * np.linalg.norm(np.cross(p[:, 1] - p[:, 0], p[:, 2] - p[:, 0]), axis=1)
    set_regex = ["|".join(names[r] for r in range(len(sigs)) if sigs[r, 1 + s]) for s in range(len(face_sets))]
    regions = _Regions(
        dirichlet="|".join(names[r] for r in range(len(sigs)) if sigs[r, 0]),
        n_dirichlet_nodes=len(np.unique(bfaces[fixed_ids].ravel())),
        set_regex=set_regex,
        set_area=[float(tri_area[fid].sum()) for fid in face_sets],
        case_sets=case_sets,
        mass_sets=mass_sets,
        names=names,
    )
    return mesh, regions


def _nodal_average(tets: np.ndarray, n: int, values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """values (m, 10, c) per element node -> (n, c) average over the elements sharing each node, and counts."""
    flat = tets.ravel()
    cnt = np.bincount(flat, minlength=n).astype(float)
    v = values.reshape(len(flat), -1)
    out = np.column_stack([np.bincount(flat, weights=v[:, c], minlength=n) for c in range(v.shape[1])])
    with np.errstate(invalid="ignore", divide="ignore"):
        out = out / cnt[:, None]
    return out, cnt


def _von_mises(s: np.ndarray) -> np.ndarray:
    """s (n, 3, 3) -> (n,)"""
    sxx, syy, szz = s[:, 0, 0], s[:, 1, 1], s[:, 2, 2]
    sxy = 0.5 * (s[:, 0, 1] + s[:, 1, 0])
    syz = 0.5 * (s[:, 1, 2] + s[:, 2, 1])
    szx = 0.5 * (s[:, 2, 0] + s[:, 0, 2])
    return np.sqrt(0.5 * ((sxx - syy) ** 2 + (syy - szz) ** 2 + (szz - sxx) ** 2) + 3.0 * (sxy ** 2 + syz ** 2 + szx ** 2))


class _Clock:
    """Accumulates wall time per phase (reported in FeaResult.notes)."""

    def __init__(self):
        self.t = time.perf_counter()
        self.parts: dict[str, float] = {}

    def __call__(self, name: str) -> None:
        now = time.perf_counter()
        self.parts[name] = self.parts.get(name, 0.0) + now - self.t
        self.t = now

    def note(self) -> str:
        return "timings: " + ", ".join(f"{k} {v:.2f}s" for k, v in self.parts.items())


def _run(problem: FeaProblem, notes: list[str]) -> tuple[list[CaseResult], NgsFields]:
    import ngsolve as ngs

    clock = _Clock()
    nodes = np.asarray(problem.nodes, float)
    tets = np.asarray(problem.tets, np.int64)
    n = len(nodes)
    mat = problem.material
    E, nu, rho = float(mat.E_mpa), float(mat.nu), float(mat.rho_t_mm3)
    mu = E / (2.0 * (1.0 + nu))
    lam = E * nu / ((1.0 + nu) * (1.0 - 2.0 * nu))

    mesh, regions = _build_mesh(problem)
    clock("mesh")
    supported = bool(regions.dirichlet)
    if problem.load_cases and not supported:
        raise ValueError("static load cases need fixed faces (a free part has no static solution)")

    fes = ngs.VectorH1(mesh, order=2, dirichlet=regions.dirichlet) if supported else ngs.VectorH1(mesh, order=2)
    free = np.array(list(fes.FreeDofs()), bool)
    n_dir = int((~free).sum())
    if n_dir != 3 * regions.n_dirichlet_nodes:
        raise RuntimeError(f"{n_dir} Dirichlet dofs, expected 3 x {regions.n_dirichlet_nodes} fixed tet10 nodes")

    u, v = fes.TnT()

    def stress(w):
        e = ngs.Sym(ngs.Grad(w))
        return 2.0 * mu * e + lam * ngs.Trace(e) * ngs.Id(3)

    a = ngs.BilinearForm(fes, symmetric=True)
    a += ngs.InnerProduct(stress(u), ngs.Sym(ngs.Grad(v))) * ngs.dx
    a.Assemble()

    # coefficient vectors of the three rigid translations (vertex dofs 1, edge-bubble dofs 0)
    gtmp = ngs.GridFunction(fes)
    rigid = []
    for d in range(3):
        gtmp.Set(ngs.CF(tuple(1.0 if k == d else 0.0 for k in range(3))))
        rigid.append(gtmp.vec.FV().NumPy().copy())
    rigid = np.array(rigid)                                              # (3, ndof)

    # element node positions: verify the reference-point mapping against the tet10 nodes before trusting it
    ref = _tet10_reference_points()
    ir = ngs.IntegrationRule(points=[tuple(q) for q in ref], weights=[0.0] * len(ref))
    pts = mesh.MapToAllElements(ir, ngs.VOL)
    xyz = np.asarray(ngs.CF((ngs.x, ngs.y, ngs.z))(pts)).reshape(len(tets), 10, 3)
    scale = max(1.0, float(np.abs(nodes).max()))
    mismatch = float(np.abs(xyz - nodes[tets]).max())
    if mismatch > 1e-9 * scale:
        raise RuntimeError(f"element node mapping mismatch {mismatch:.3g} mm")

    clock("assemble K")
    inv = a.mat.Inverse(fes.FreeDofs(), inverse=_DIRECT) if supported else None
    clock("factorise K")
    gfu = ngs.GridFunction(fes)
    res = gfu.vec.CreateVector()
    sig_cf = stress(gfu)
    exclude = np.zeros(n, bool)
    if problem.exclude_nodes is not None and len(problem.exclude_nodes):
        exclude[np.asarray(problem.exclude_nodes, np.int64)] = True

    cases: list[CaseResult] = []
    fields = NgsFields([], [], [], np.zeros(0))
    mass = problem.mass_t()
    for ci, case in enumerate(problem.load_cases):
        f = ngs.LinearForm(fes)
        applied = np.zeros(3)
        n_terms = 0
        for sl, s in zip(case.surface_loads, regions.case_sets[ci]):
            force = np.asarray(sl.total_force_n, float).reshape(3)
            moment = getattr(sl, "moment_nmm", None)
            has_moment = moment is not None and np.any(np.asarray(moment, float))
            if not np.any(force) and not has_moment:
                continue
            area = regions.set_area[s]
            if area <= 0.0:
                raise ValueError(f"load case {case.name!r}: a non-zero surface load acts on zero area")
            if has_moment:
                # linear traction t(x) = a + ω × (x − c) carrying the force and the moment (problem.SurfaceLoad)
                from .mesh import traction_field
                ta, w, c = traction_field(problem.nodes, np.asarray(sl.faces), force, moment)
                rx, ry, rz = ngs.x - c[0], ngs.y - c[1], ngs.z - c[2]
                t_cf = ngs.CF((ta[0] + w[1] * rz - w[2] * ry, ta[1] + w[2] * rx - w[0] * rz,
                               ta[2] + w[0] * ry - w[1] * rx))
            else:
                t_cf = ngs.CF(tuple(force / area))
            f += ngs.InnerProduct(t_cf, v) * ngs.ds(regions.set_regex[s])
            applied += force
            n_terms += 1
        if case.body_accel_mm_s2 is not None and np.any(case.body_accel_mm_s2):
            acc = np.asarray(case.body_accel_mm_s2, float).reshape(3)
            f += rho * ngs.InnerProduct(ngs.CF(tuple(acc)), v) * ngs.dx
            applied += mass * acc
            n_terms += 1
        if n_terms:
            f.Assemble()
            fvec = f.vec
        else:
            fvec = gfu.vec.CreateVector()
            fvec[:] = 0.0
        fn = fvec.FV().NumPy()
        assembled = rigid @ fn                                            # resultant of the assembled load
        # (a pure torque has zero resultant: the tolerance also scales with the nodal loads' size)
        tol = 1e-9 * max(1.0, float(np.abs(applied).max())) + 1e-12 * float(np.abs(fn).sum())
        if np.abs(assembled - applied).max() > tol:
            raise RuntimeError(f"load case {case.name!r}: assembled load {assembled} != applied {applied}")

        gfu.vec.data = inv * fvec
        res.data = a.mat * gfu.vec - fvec
        r = res.FV().NumPy()
        reaction = rigid[:, ~free] @ r[~free]
        free_res = float(np.abs(r[free]).max()) if free.any() else 0.0

        uu = np.asarray(gfu(pts)).reshape(len(tets), 10, 3)
        disp = np.full((n, 3), np.nan)
        disp[tets.ravel()] = uu.reshape(-1, 3)
        sig = np.asarray(sig_cf(pts)).reshape(len(tets), 10, 9)
        s_avg, cnt = _nodal_average(tets, n, sig)
        s_avg = s_avg.reshape(n, 3, 3)
        vm = _von_mises(s_avg)
        used = cnt > 0
        vm_f = vm[used & ~exclude]
        cases.append(CaseResult(
            name=case.name,
            max_disp_mm=float(np.linalg.norm(disp[used], axis=1).max()),
            max_vm_mpa=float(vm[used].max()),
            max_vm_filtered_mpa=float(vm_f.max()) if len(vm_f) else float("nan"),
            reaction_n=reaction,
            applied_n=applied,
        ))
        fields.displacement.append(disp)
        fields.stress.append(s_avg)
        fields.von_mises.append(vm)
        notes.append(f"{case.name}: max |K u - f| over free dofs {free_res:.3g} N")
        clock("load cases")

    if problem.n_modes > 0:
        fields.eigenvalues = _modes(problem, fes, a, inv, free, stress, regions, rigid, notes)
        clock("modes")
    notes.append(clock.note())
    return cases, fields


def _modes(problem: FeaProblem, fes, a, inv, free: np.ndarray, stress, regions: _Regions, rigid: np.ndarray,
           notes: list[str]) -> np.ndarray:
    import ngsolve as ngs
    from scipy.sparse.linalg import LinearOperator, eigsh

    k = problem.n_modes
    E, rho = float(problem.material.E_mpa), float(problem.material.rho_t_mm3)
    nodes = np.asarray(problem.nodes, float)
    u, v = fes.TnT()

    def add_mass(form, scale: float = 1.0) -> float:
        """Structural mass rho u.v dx plus the non-structural masses (m / A) u.v ds over their faces."""
        form += scale * rho * ngs.InnerProduct(u, v) * ngs.dx
        added = 0.0
        for j, (s, mt) in enumerate(regions.mass_sets):
            if mt == 0.0:
                continue
            area = regions.set_area[s]
            if mt < 0.0 or area <= 0.0:
                raise ValueError(f"added mass {j}: {mt} t on {area} mm^2 (needs mass >= 0 on a non-empty face set)")
            form += scale * (mt / area) * ngs.InnerProduct(u, v) * ngs.ds(regions.set_regex[s])
            added += mt
        return added

    m = ngs.BilinearForm(fes, symmetric=True)
    added = add_mass(m)
    m.Assemble()
    # the assembled mass matrix must carry the structural plus the added mass (rigid translation c: c^T M c = mass)
    mc = m.mat.CreateColVector()
    cx = m.mat.CreateColVector()
    cx.FV().NumPy()[:] = rigid[0]
    mc.data = m.mat * cx
    total = float(rigid[0] @ mc.FV().NumPy())
    expect = problem.mass_t() + added
    if abs(total - expect) > 1e-9 * expect:
        raise RuntimeError(f"assembled mass {total} t != structural + added {expect} t")
    if added:
        notes.append(f"added non-structural mass {added:.6g} t on {len(regions.mass_sets)} face set(s), mass matrix "
                     f"only (FeaResult.mass_t = structural {problem.mass_t():.6g} t)")
    if inv is not None:
        sigma, opinv = 0.0, inv                                           # supported: K is SPD on the free dofs
    else:
        # free part: K is singular (6 rigid modes). Shift to sigma = -s with s = 1e-4 c^2 / D^2 (c = sqrt(E/rho) the
        # bar wave speed, D the bounding-box diagonal): far below the first elastic eigenvalue of any compact part,
        # yet large enough that K + s M is well conditioned for the Cholesky factorisation.
        diag = float(np.linalg.norm(nodes.max(axis=0) - nodes.min(axis=0)))
        s = 1e-4 * (E / rho) / diag ** 2
        ks = ngs.BilinearForm(fes, symmetric=True)
        ks += ngs.InnerProduct(stress(u), ngs.Sym(ngs.Grad(v))) * ngs.dx
        add_mass(ks, s)                                                   # K + s M, M incl. the added masses
        ks.Assemble()
        sigma, opinv = -s, ks.mat.Inverse(fes.FreeDofs(), inverse=_DIRECT)

    idx = np.flatnonzero(free)
    nf = len(idx)
    k = min(k, nf - 2)
    xv, yv = m.mat.CreateColVector(), m.mat.CreateColVector()
    xn, yn = xv.FV().NumPy(), yv.FV().NumPy()

    def apply(op):
        def mv(x):
            xn[:] = 0.0
            xn[idx] = np.ravel(x)
            yv.data = op * xv
            return yn[idx].copy()
        return mv

    shape = (nf, nf)
    A = LinearOperator(shape, matvec=apply(a.mat), dtype=float)          # not used by ARPACK mode 3
    M = LinearOperator(shape, matvec=apply(m.mat), dtype=float)
    OPinv = LinearOperator(shape, matvec=apply(opinv), dtype=float)
    v0 = np.random.default_rng(0).standard_normal(nf)
    lam = eigsh(A, k=k, M=M, sigma=sigma, which="LM", OPinv=OPinv, v0=v0, ncv=min(nf - 1, max(2 * k + 1, 24)),
                return_eigenvectors=False)
    lam = np.sort(np.asarray(lam, float))
    notes.append(f"modes: ARPACK shift-invert, sigma = {sigma:.6g} (rad/s)^2, OPinv = {_DIRECT} of K - sigma M")
    return lam


def solve_with_fields(problem: FeaProblem, threads: int = 2) -> tuple[FeaResult, NgsFields]:
    """`solve` plus the nodal displacement / stress fields and the raw eigenvalues."""
    import ngsolve as ngs
    from threadpoolctl import threadpool_limits

    t0 = time.perf_counter()
    threads = max(1, int(threads))
    use_tm = threads > 1 and len(problem.nodes) >= _TM_MIN_NODES
    ngs.ngsglobals.msg_level = 0
    ngs.SetNumThreads(threads)
    tm = f"on ({threads} threads)" if use_tm else "off"
    notes = [(f"linear netgen tets from the tet10 corners + VectorH1(order=2) (= tet10 space); static solver: "
              f"direct {_DIRECT}; BLAS capped at {threads} threads, NGSolve TaskManager {tm}")]
    with threadpool_limits(limits=threads), (ngs.TaskManager() if use_tm else contextlib.nullcontext()):
        cases, fields = _run(problem, notes)
    freqs = [float(np.sqrt(max(lam, 0.0)) / (2.0 * np.pi)) for lam in fields.eigenvalues]
    result = FeaResult(
        solver=f"NGSolve {ngs.__version__}",
        cases=cases,
        frequencies_hz=freqs,
        mass_t=problem.mass_t(),
        n_nodes=len(problem.nodes),
        n_elements=len(problem.tets),
        seconds=time.perf_counter() - t0,
        notes=notes,
    )
    return result, fields


def solve(problem: FeaProblem, threads: int = 2) -> FeaResult:
    return solve_with_fields(problem, threads)[0]
