"""Turn a generator's density field into a certified-ready solid and check it with two FEA solvers.

1. Passives are imposed (void 0, fixed/contact 1); the solid (density ≥ 0.5) keeps only the voxel islands that join
   the bolted layer to the part (6-connected); a design with no such island fails.
2. Surface: marching cubes on the density (iso 0.5), extended one voxel through the target plane, then intersected
   with the reserved box (so the solid lies in the box the fit proof certifies, and the bolted face is exactly the
   plane) and with the complement of the held part.
3. Quadratic tets on exactly that surface; the bolted face is fixed; the faces within the contact zone of the part
   carry the part's 68 g inertia load (each axis separately) and its mass (for the modal check); the bracket carries
   its own 68 g body load.
4. CalculiX and NGSolve solve the same problem. Margins use the larger peak stress and the lower first frequency.
   Peak stress excludes only the nodes on the bolted face (the constraint is singular there).
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

import numpy as np

from .domain import CONTACT_GAP, F1_PASS, FOS_ULT, FOS_YIELD, DesignDomain, GenResult


@dataclass
class Evaluation:
    name: str
    generator: str
    ok: bool                              # a solid exists, joins wall and part, both solvers ran
    passed: bool = False                  # ok, margins ≥ 0 and f1 ≥ F1_PASS
    reason: str = ""
    mass_g: float | None = None
    volume_cm3: float | None = None
    sigma_mpa: float | None = None        # max over cases and solvers of the filtered peak von Mises
    ms_yield: float | None = None
    ms_ult: float | None = None
    f1_hz: float | None = None            # lower of the two solvers, with the part's mass
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
    d = np.where(np.isin(lab, keep) | (d < 0.5), d, 0.0)         # drop islands
    P = np.pad(d, 2)                         # two empty layers: the outer one closes the marching-cubes surface
    ax = dom.axis
    sl_out = [slice(2, -2)] * 3
    sl_in = [slice(2, -2)] * 3
    sl_out[ax] = 1 if dom.neg else -2                                # the layer beyond the target plane
    sl_in[ax] = 2 if dom.neg else -3
    P[tuple(sl_out)] = P[tuple(sl_in)]
    verts, faces, _, _ = marching_cubes(P, level=0.5, spacing=(dom.h,) * 3, allow_degenerate=False)
    verts = verts + dom.origin - 1.5 * dom.h                         # padded index i ↔ centre origin + (i − 1.5) h
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
    return (np.asarray(mesh.vert_properties)[:, :3].astype(float), np.asarray(mesh.tri_verts).astype(np.int64)), ""


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


def fea_problem(dom: DesignDomain, v, f, h_fea: float | None = None, n_modes: int = 1):
    from scipy.spatial import cKDTree

    from ..fea.mesh import boundary_faces, mesh_surface
    from ..fea.problem import FeaProblem, LoadCase, Material, SurfaceLoad
    from ..geometry.voxel import surface_samples
    h_fea = h_fea or max(1.5, dom.h)
    # the tets keep the certified surface triangles (gmsh cannot re-parametrise marching-cubes surfaces); h_fea sets
    # the interior element size
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
    cases = [LoadCase(c["name"], [SurfaceLoad(load, np.asarray(c["contact_force_n"], float))],
                      np.asarray(c["body_accel_mm_s2"], float)) for c in dom.load_cases()]
    prob = FeaProblem(nodes, tets, mat, fixed, cases, n_modes=n_modes, exclude_nodes=np.unique(fixed.ravel()),
                      label=dom.name, added_masses=[(load, dom.part_mass_kg * 1e-3)])
    return prob


def evaluate(dom: DesignDomain, gen: GenResult, solvers=("ccx", "ngs"), threads: int = 2,
             h_fea: float | None = None) -> Evaluation:
    from ..fea import ccx, ngs
    ev = Evaluation(dom.name, gen.generator, False, gen_seconds=gen.seconds)
    if gen.mesh is not None:
        v, f = gen.mesh
        man = _to_manifold(v, f) ^ _box(dom.reserve[:3], dom.reserve[3:])
        mesh = man.to_mesh()
        sol = (np.asarray(mesh.vert_properties)[:, :3].astype(float), np.asarray(mesh.tri_verts).astype(np.int64))
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
    res = {}
    for s in solvers:
        mod = {"ccx": ccx, "ngs": ngs}[s]
        if s == "ccx" and not ccx.available():
            continue
        try:
            res[s] = mod.solve(prob, threads=threads)
        except Exception as exc:  # noqa: BLE001
            ev.reason = f"{s} failed: {exc}"
            return ev
    ev.fea_seconds = time.perf_counter() - t0
    if not res:
        ev.reason = "no solver available"
        return ev
    for s, r in res.items():
        ev.solvers[s] = {"solver": r.solver, "seconds": r.seconds, "f1_hz": r.frequencies_hz[0] if r.frequencies_hz else None,
                         "cases": [{"name": c.name, "max_disp_mm": c.max_disp_mm, "max_vm_mpa": c.max_vm_mpa,
                                    "max_vm_filtered_mpa": c.max_vm_filtered_mpa,
                                    "balance": float(np.linalg.norm(c.reaction_n + c.applied_n) /
                                                     max(np.linalg.norm(c.applied_n), 1e-30))} for c in r.cases],
                         "notes": list(r.notes)}
    ev.sigma_mpa = max(c.max_vm_filtered_mpa for r in res.values() for c in r.cases)
    ev.max_disp_mm = max(c.max_disp_mm for r in res.values() for c in r.cases)
    f1s = [r.frequencies_hz[0] for r in res.values() if r.frequencies_hz]
    ev.f1_hz = min(f1s) if f1s else None
    m = dom.material
    ev.ms_yield = m["yield_mpa"] / (FOS_YIELD * ev.sigma_mpa) - 1.0
    ev.ms_ult = m["ultimate_mpa"] / (FOS_ULT * ev.sigma_mpa) - 1.0
    if len(res) == 2:
        a, b = res["ccx"], res["ngs"]
        ev.agreement = {
            "disp_rel": max(abs(x.max_disp_mm - y.max_disp_mm) / max(y.max_disp_mm, 1e-30) for x, y in zip(a.cases, b.cases)),
            "sigma_rel": max(abs(x.max_vm_filtered_mpa - y.max_vm_filtered_mpa) / max(y.max_vm_filtered_mpa, 1e-30)
                             for x, y in zip(a.cases, b.cases)),
            "f1_rel": (abs(a.frequencies_hz[0] - b.frequencies_hz[0]) / b.frequencies_hz[0]
                       if a.frequencies_hz and b.frequencies_hz else None)}
    ev.ok = True
    fails = []
    if ev.ms_yield < 0:
        fails.append(f"MS yield {ev.ms_yield:+.2f}")
    if ev.ms_ult < 0:
        fails.append(f"MS ultimate {ev.ms_ult:+.2f}")
    if ev.f1_hz is None or ev.f1_hz < F1_PASS:
        fails.append(f"f1 {ev.f1_hz if ev.f1_hz is not None else float('nan'):.0f} Hz < {F1_PASS:.0f}")
    ev.passed = not fails
    ev.reason = "; ".join(fails)
    return ev
