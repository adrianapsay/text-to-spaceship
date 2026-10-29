"""Entrant: pytopo3d 0.3.0 — 3-D SIMP compliance minimisation (Kim & Kang, KAIST; MIT licence).

What pytopo3d itself offers (read from its installed 0.3.0 source): `pytopo3d.core.optimizer.top3d(nelx, nely,
nelz, volfrac, penal, rmin, disp_thres, obstacle_mask, force_field, support_mask, tolx, maxloop, ...)` — unit-cube
8-node hexahedra (`lk_H8`), E0 = 1, Emin = 1e-9, ν = 0.3 hard-wired, fixed penalisation, a linear density filter of
radius `rmin` (element units), optimality-criteria update (move 0.2, bisection on the multiplier), PARDISO solve,
stop at max|Δx| ≤ tolx or `maxloop`. Its inputs: ONE load vector (`force_field[y, x, z, :]` = force per element,
split 1/8 to its nodes), supports as an element mask (all 8 nodes of each marked element clamped in x, y, z), and a
passive-VOID mask (`obstacle_mask`). It has no passive solid, no multiple load cases, no body (self-weight) load and
no wall-clock budget.

What this entrant runs: top3d's CPU iteration step for step, assembled from pytopo3d's own pieces (`lk_H8`,
`build_edof`, `build_supports`, `build_force_vector`, `build_filter`, `ComplianceEvaluator`, `get_solver` →
pypardiso, `optimality_criteria_update`, `_make_scatter_map`), with four additions top3d() cannot express:

1. Three load cases: objective = c_x + c_y + c_z (sum of the three separate compliances, one `ComplianceEvaluator`
   per case; the three share one stiffness matrix, so PARDISO factorises once per iteration and pypardiso reuses
   the factorisation for the other two right-hand sides). Not a summed load vector: (Fx+Fy+Fz)ᵀK⁻¹(Fx+Fy+Fz) has
   cross terms and would let a design be soft at right angles to the (1,1,1) diagonal.
2. Passive solid: fixed + contact voxels are held at density 1 in the stiffness; they and the void are excluded
   from the design variables (pytopo3d's `obstacle_mask`, which forces x = 0, is given all passive voxels, and the
   solid ones are re-set to 1 before each FE solve).
3. The density filter acts on design voxels only (pytopo3d's H restricted to design × design, renormalised), so a
   design voxel next to the clamped plate or the loaded layer is neither dragged down by "obstacle" zeros nor
   lifted by the passive ones, and OC's bisection measures exactly the design-voxel volume it is asked to hold.
4. Budget: the iteration cap is min(MAX_ITER, what a fixed per-iteration cost model in the DOF count fits into
   0.85 · budget_s) — deterministic; a wall-clock guard stops earlier only if the machine is slower than the model
   (then the result depends on timing, and the notes say so).
With no passive solid, no void and one load case, the loop reproduces top3d() (tests/test_gd_pytopo3d.py).

Not modelled (pytopo3d has no design-dependent load): the bracket's own 68 g body acceleration (self-weight).
"""
from __future__ import annotations

import os
import time
import warnings

import numpy as np

from ..domain import DesignDomain, GenResult
from ..sparse import Spsolve, backend, speed_factor

# Set before MKL loads (pypardiso loads it on first import), unless the user set them:
# MKL_CBWR=AUTO makes multi-threaded PARDISO bitwise repeatable (measured: without it, 2-thread runs differ by
# ~1e-13 from run to run); KMP_BLOCKTIME=0 stops Intel OpenMP threads spinning 200 ms after every parallel region,
# which on a shared, CPU-capped machine burns the quota for nothing (measured: same speed, ~30 % less CPU).
os.environ.setdefault("MKL_CBWR", "AUTO")
os.environ.setdefault("KMP_BLOCKTIME", "0")

NAME = "pytopo3d SIMP"
PENAL = 3.0          # pytopo3d CLI default
RMIN_MM = 3.0        # filter radius in mm (≥ 1.5 elements, pytopo3d's default)
TOLX = 0.01          # pytopo3d default stop: max |Δx| ≤ 0.01
MAX_ITER = 300       # iteration cap (pytopo3d default maxloop is 2000)
EMIN = 1e-9          # pytopo3d's Emin / E0


def iteration_seconds(ndof: int) -> float:
    """Cost model of one iteration (3-case FE solve, nonsymmetric PARDISO factorisation, 2 threads), fitted on the
    dev machine: measured 0.13 s (0.3–0.4 s when the shared machine throttles us) at 8 k DOF (h = 2 box domain),
    5 s throttled at 58 k DOF (h = 1); one thread is up to 2× slower. Without PARDISO, × the solver's measured speed
    relative to it (gd.sparse.speed_factor)."""
    return 0.2 * (ndof / 8151.0) ** 1.6 * speed_factor()


def iteration_cap(ndof: int, budget_s: float, max_iter: int = MAX_ITER) -> int:
    """Deterministic iteration cap for a wall-clock budget (setup and the final solve inside the 15 % margin)."""
    return int(max(1, min(max_iter, np.floor(0.85 * budget_s / iteration_seconds(ndof)) - 1)))


def to_p(a: np.ndarray) -> np.ndarray:
    """Domain grid [i, j, k] (world x, y, z) → pytopo3d element array [y, x, z] (shape (nely, nelx, nelz))."""
    return np.ascontiguousarray(np.transpose(a, (1, 0, 2)))


def from_p(a: np.ndarray) -> np.ndarray:
    """pytopo3d element array [y, x, z] → domain grid [i, j, k]."""
    return np.ascontiguousarray(np.transpose(a, (1, 0, 2)))


class Pytopo3dProblem:
    """pytopo3d's FE / filter / OC data for one problem, in pytopo3d's own array convention.

    `void`, `solid`, `support`: bool arrays (nely, nelx, nelz); `force_fields`: list of (nely, nelx, nelz, 3) arrays
    (force per element, N), one per load case; `rmin` in element units."""

    def __init__(self, void, solid, support, force_fields, rmin: float, nu: float = 0.3):
        import scipy.sparse as sp
        from pytopo3d.core.evaluator import ComplianceEvaluator
        from pytopo3d.core.optimizer import _make_scatter_map
        from pytopo3d.utils.assembly import build_edof, build_force_vector, build_supports
        from pytopo3d.utils.filter import build_filter
        from pytopo3d.utils.solver import get_solver
        from pytopo3d.utils.stiffness import lk_H8

        self.shape = void.shape                                    # (nely, nelx, nelz)
        nely, nelx, nelz = self.shape
        self.nelx, self.nely, self.nelz = nelx, nely, nelz
        self.nele = nelx * nely * nelz
        self.ndof = 3 * (nelx + 1) * (nely + 1) * (nelz + 1)
        self.void, self.solid = void.astype(bool), solid.astype(bool)
        self.passive = self.void | self.solid
        self.design = ~self.passive
        self.n_design = int(self.design.sum())
        if not support.any():
            raise ValueError("no fixed voxels: pytopo3d would silently fall back to clamping the x = 0 face")
        self.freedofs0, self.fixeddof0 = build_supports(nelx, nely, nelz, self.ndof, support.astype(bool))

        # Loads: pytopo3d spreads each element's force 1/8 to its nodes. Scaled by the largest total-force component
        # so the OC multiplier stays inside its [1e-9, 1e9] bisection bracket; c_phys = c * scale² / (E h).
        mags = [float(np.abs(ff.reshape(-1, 3).sum(0)).max()) if ff.any() else 0.0 for ff in force_fields]
        self.scale = max(mags) if max(mags) > 0 else 1.0
        self.F = []
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)          # 0.3.0's one-off "Fx/Fy transpose fixed" notice
            for ff in force_fields:
                self.F.append(build_force_vector(nelx, nely, nelz, self.ndof, np.asarray(ff, float) / self.scale))
        tot = sum(np.abs(f).sum() for f in self.F)
        self.load_on_clamped = float(sum(np.abs(f[self.fixeddof0]).sum() for f in self.F) / tot) if tot else 0.0

        # Density filter (pytopo3d's), restricted to design × design and renormalised; passive rows = identity.
        H, _ = build_filter(nelx, nely, nelz, rmin)
        d = self.design.ravel(order="F").astype(float)
        Hd = (sp.diags(d) @ H @ sp.diags(d) + sp.diags(1.0 - d)).tocsr()
        Hd.eliminate_zeros()
        self.H, self.Hs = Hd, np.asarray(Hd.sum(axis=1)).ravel()

        KE = lk_H8(nu)
        edofMat, iK, jK = build_edof(nelx, nely, nelz)
        i_u, j_u, dup2uniq = _make_scatter_map(iK - 1, jK - 1, self.ndof)
        K = sp.csr_matrix((np.zeros(len(i_u)), (i_u, j_u)), shape=(self.ndof, self.ndof))
        solver, self.solver_name = get_solver(False)
        if backend() != "pardiso":            # no MKL (macOS): a sparse Cholesky, not pytopo3d's single-core SuperLU
            solver = Spsolve()
            self.solver_name = f"{solver.chol.name} (factorisation shared by the load cases)"
        self.evaluators = [ComplianceEvaluator(KE=KE, dup2uniq=dup2uniq, K=K, freedofs0=self.freedofs0, F=F,
                                               ndof=self.ndof, solver_func=solver, edofMat=edofMat, shape=self.shape,
                                               H=self.H, Hs=self.Hs, obstacle_mask=self.passive, E0=1.0, Emin=EMIN)
                           for F in self.F]

    def filt(self, x: np.ndarray) -> np.ndarray:
        xp = (self.H @ x.ravel(order="F") / self.Hs).reshape(self.shape, order="F")
        xp[self.passive] = 0.0
        return xp

    def evaluate(self, xPhys: np.ndarray, penal: float):
        """Sum of the cases' compliances (scaled units) at physical density xPhys (passive solid forced to 1), its
        filtered sensitivity, the filtered volume sensitivity, and the per-case compliances."""
        xfe = xPhys.copy()
        xfe[self.solid] = 1.0
        xfe[self.void] = 0.0
        c_cases, dc, dv = [], np.zeros(self.shape), None
        for ev in self.evaluators:
            c, dci, dv = ev.evaluate(xfe, penal)
            c_cases.append(float(c))
            dc += dci
        return float(sum(c_cases)), dc, dv, c_cases


def run_oc(prob: Pytopo3dProblem, volfrac: float, penal: float, maxloop: int, tolx: float,
           deadline: float | None = None, final_eval: bool = True) -> dict:
    """top3d's CPU loop (optimizer.py, `else` branch) on `prob`, plus the multi-case sum and the deadline."""
    from pytopo3d.utils.oc_update import optimality_criteria_update
    x = np.full(prob.shape, volfrac)
    x[prob.passive] = 0.0
    xPhys = prob.filt(x)
    loop, change, hist, t_iter, stop = 0, 1.0, [], 0.0, "converged"
    while change > tolx and loop < maxloop:
        if deadline is not None and time.perf_counter() + 2.0 * t_iter > deadline:   # this step + final solve
            stop = "wall-clock guard (timing-dependent result)"
            break
        t1 = time.perf_counter()
        loop += 1
        c, dc, dv, _ = prob.evaluate(xPhys, penal)
        hist.append(c)
        dv = dv + 1e-9                                       # as top3d: OC divides by dv
        xnew, change = optimality_criteria_update(x, dc, dv, volfrac, prob.H, prob.Hs, prob.nele, prob.passive,
                                                  prob.n_design, use_gpu=False)
        xnew[prob.passive] = 0.0
        xPhys = prob.filt(xnew)
        x = xnew
        t_iter = time.perf_counter() - t1 if loop == 1 else max(0.7 * t_iter, time.perf_counter() - t1)
    else:
        if change > tolx:
            stop = "iteration cap"
    out = {"xPhys": xPhys, "iterations": loop, "history": hist, "stop": stop, "change": float(change)}
    if final_eval:                                           # compliance of the design actually returned
        c, _, _, cc = prob.evaluate(xPhys, penal)
        out["c_final"], out["c_cases"] = c, cc
    return out


def problem_from_domain(domain: DesignDomain, rmin_mm: float = RMIN_MM) -> tuple[Pytopo3dProblem, float]:
    """pytopo3d problem of `domain` (axis mapping: nelx = nx, nely = ny, nelz = nz, arrays [y, x, z]) and the
    factor that turns its compliance into N·mm."""
    if domain.contact.sum() == 0:
        raise ValueError("domain has no contact voxels to load")
    ff = []
    n_c = int(domain.contact.sum())
    for lc in domain.load_cases():
        # the part's force at its centre of mass, as force + moment over the contact voxels (domain.contact_voxel_forces)
        f = domain.contact_voxel_forces(lc)
        assert n_c and np.allclose(f.sum(axis=(0, 1, 2)), lc["contact_force_n"])
        ff.append(np.ascontiguousarray(np.transpose(f, (1, 0, 2, 3))))
    rmin = max(1.5, rmin_mm / domain.h)
    prob = Pytopo3dProblem(to_p(domain.void), to_p(domain.passive_solid()), to_p(domain.fixed), ff, rmin,
                           nu=float(domain.material["nu"]))
    prob.rmin = rmin
    # lk_H8 is the unit cube with E = 1; a cube of edge h has stiffness E·h·KE → U scales by 1/(E h)
    return prob, prob.scale ** 2 / (float(domain.material["E_mpa"]) * domain.h)


def mkl_cnr_branch() -> int:
    """MKL's conditional-numerical-reproducibility branch as pypardiso's MKL reports it (1 = off, ≥ 2 = on)."""
    try:
        import ctypes

        from pypardiso.scipy_aliases import pypardiso_solver
        get = pypardiso_solver.libmkl.MKL_CBWR_Get
        get.restype = ctypes.c_int
        return int(get(ctypes.c_int(1)))            # MKL_CBWR_BRANCH
    except Exception:                               # noqa: BLE001 — unknown MKL build: treat as off
        return 0


def _connectivity_note(domain: DesignDomain, rho: np.ndarray) -> str:
    from scipy import ndimage
    solid = rho >= 0.5
    lab, n = ndimage.label(solid, structure=ndimage.generate_binary_structure(3, 1))
    path = (set(np.unique(lab[domain.fixed])) & set(np.unique(lab[domain.contact]))) - {0}
    main = float(np.isin(lab, list(path)).sum() / max(1, solid.sum()))
    return (f"thresholded solid: {n} 6-connected component(s); fixed↔contact joined: {bool(path)} "
            f"({100 * main:.1f} % of the solid voxels in the joining component)")


def generate(domain: DesignDomain, budget_s: float = 120.0, threads: int = 2, *, penal: float = PENAL,
             rmin_mm: float = RMIN_MM, max_iter: int = MAX_ITER, tolx: float = TOLX,
             deterministic: bool = True) -> GenResult:
    """`threads` caps every BLAS / OpenMP pool. `deterministic` (default): PARDISO runs on `threads` threads only if
    MKL's conditional numerical reproducibility is on (MKL_CBWR, set at import of this module — too late if MKL
    was loaded earlier by someone else), otherwise on one thread."""
    t0 = time.perf_counter()
    for v in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
        os.environ.setdefault(v, str(threads))
    from importlib.metadata import version

    import pytopo3d.utils.solver  # noqa: F401 — loads pypardiso → MKL now, so threadpool_limits below reaches it
    from threadpoolctl import threadpool_limits

    rho = np.zeros(domain.shape)
    rho[domain.passive_solid()] = 1.0
    des = domain.design()
    if not des.any():
        return GenResult(rho, time.perf_counter() - t0, NAME, notes=["no design voxels: passives only"],
                         iterations=0)
    # one cap for all pools (a per-library dict, limits={"mkl": 1}, did not reach MKL here — threadpoolctl 3.7)
    cnr = mkl_cnr_branch()
    mkl_threads = threads if (not deterministic or cnr >= 2) else 1
    with threadpool_limits(limits=mkl_threads):
        prob, to_nmm = problem_from_domain(domain, rmin_mm)
        t_setup = time.perf_counter() - t0
        cap = iteration_cap(prob.ndof, budget_s, max_iter)
        res = run_oc(prob, domain.vol_frac, penal, cap, tolx, deadline=t0 + budget_s)

    rho = np.clip(from_p(res["xPhys"]), 0.0, 1.0)
    rho[domain.void] = 0.0
    rho[domain.passive_solid()] = 1.0
    vf_c = float(rho[des].mean())
    vf_t = float((rho[des] >= 0.5).mean())
    hist = [c * to_nmm for c in res["history"]] + [res["c_final"] * to_nmm]
    names = [lc["name"] for lc in domain.load_cases()]
    cc = ", ".join(f"{n}: {c * to_nmm:.4g}" for n, c in zip(names, res["c_cases"]))
    notes = [
        (f"pytopo3d {version('pytopo3d')} SIMP/OC ({prob.solver_name}), top3d's CPU loop on pytopo3d's own "
         "lk_H8/build_edof/build_supports/build_force_vector/build_filter/ComplianceEvaluator/OC update"),
        (f"grid {domain.shape} → pytopo3d (nely, nelx, nelz) = {prob.shape} (arrays [y, x, z], nelx = nx), "
         f"{prob.ndof} DOF; h = {domain.h} mm; E = {domain.material['E_mpa']:.0f} MPa (scales the reported "
         f"compliance only), ν = {domain.material['nu']}"),
        (f"supports: all 8 nodes of every fixed voxel clamped (pytopo3d support_mask); loads: each case's contact "
         f"force spread uniformly over the {int(domain.contact.sum())} contact voxels, 1/8 per node "
         f"({100 * prob.load_on_clamped:.1f} % lands on clamped nodes)"),
        ("objective: sum of the 3 separate load-case compliances (one factorisation, 3 right-hand sides); "
         "bracket self-weight (68 g body acceleration) NOT modelled — pytopo3d has no design-dependent body load"),
        "passive: void → 0 and fixed + contact → 1 in the stiffness and in the result; filter on design voxels only",
        (f"penal {penal}, rmin {prob.rmin:.2f} el = {prob.rmin * domain.h:.1f} mm, volfrac {domain.vol_frac} of "
         f"design voxels, tolx {tolx}; iteration cap {cap} (max_iter {max_iter}, budget {budget_s:.0f} s, model "
         f"{iteration_seconds(prob.ndof):.2f} s/iteration)"),
        (f"{res['iterations']} iterations, stop: {res['stop']} (max|Δx| {res['change']:.4f}); "
         f"setup {t_setup:.1f} s; threads {mkl_threads} (cap {threads}, deterministic={deterministic}, "
         f"MKL CNR branch {cnr})"),
        f"compliance (N·mm, returned continuous design): total {hist[-1]:.4g} ({cc}); first iterate {hist[0]:.4g}",
        f"design volume fraction: continuous {vf_c:.4f}, thresholded (≥ 0.5) {vf_t:.4f} (target {domain.vol_frac})",
        _connectivity_note(domain, rho),
    ]
    return GenResult(rho, time.perf_counter() - t0, NAME, notes=notes, iterations=res["iterations"], history=hist)
