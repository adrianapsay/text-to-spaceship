"""Entrant: pyMOTO 2.0.1 — density-based topology optimisation (SIMP + MMA) on the domain's own voxel grid.

What pyMOTO offers (read from its installed 2.0.1 source): a modular "signal → module → signal" graph with automatic
back-propagation of sensitivities (`Signal`, `Module`, `Network`); a structured hexahedral mesh `VoxelDomain`
(trilinear 8-node elements, element number (k·ny + j)·nx + i); `DensityFilter` (linear cone filter, row-normalised);
`AssembleStiffness` (3-D isotropic element matrix of the actual voxel size, Dirichlet dofs set by zeroing row and
column with a positive diagonal); `LinSolve` (multi-RHS, linear-dependency-aware wrapper, MKL Pardiso when mkl_rt is
found); `EinSum`, `SetValue`, `Scaling`; and the optimisers `MMA` (Svanberg 2007), `OC`, `SLP`.

What this entrant builds (one pyMOTO `Network`, optimised with pyMOTO's `MMA`):

    x (design voxels only) → _Scatter (fixed/contact = 1, void = 0) → DensityFilter (r = 1.5 voxels)
      → _Heaviside (η = 0.5, β = 1, 2, 4, 8, 16 continuation) → SetValue (passives re-imposed exactly) = ρ
    ρ → _Simp (p = 3) → AssembleStiffness (E, ν, h; target-plane dofs clamped) = K
    ρ → _Loads (contact load + self-weight) = F (ndof × 3)        LinSolve(K, F) = U (one factorisation, 3 RHS)
    objective = Scaling(EinSum(F·U)) = Σ_cases compliance          constraint = Scaling(mean ρ[design] ≤ vol_frac)

* Mesh: one 8-node hexahedron per voxel, element size h, so FE elements and voxels coincide exactly.
* Supports: all three dofs of the target-plane face nodes of the fixed voxels are clamped (the face lying on the
  wall / plate — not all 8 nodes of the fixed voxels; the fixed layer itself stays passive solid).
* Loads: three cases (68 g in x, y, z) as one 3-column right-hand side; the objective is the SUM of the three
  compliances (not one summed load vector, whose cross terms would hide a soft diagonal direction). Each case's
  contact force is spread uniformly over the contact voxels, 1/8 of a voxel's share to each of its 8 nodes. The
  bracket's own 68 g body load is included: ρ_e · m_voxel · a, 1/8 per node (design-dependent load).
* SIMP p = 3 with E_min = 1e-9 E. Below ρ = 0.1 the stiffness interpolation turns linear (ρ_t^(p−1)·ρ, Bruyneel &
  Duysinx 2005) so near-void voxels, whose self-weight scales with ρ, do not get a ρ/ρ³ load-to-stiffness ratio.
* Passive voxels: void ρ = 0, fixed + contact ρ = 1 (in the filter input and again, exactly, after projection); the
  volume constraint counts design voxels only. The returned density is ρ (the projected, physical density). Only if
  its 0.5 cut misses the optimised design volume by > 1 % of the design voxels (a run stopped at low β) is it
  remapped monotonically (0 → 0, t → 0.5, 1 → 1; volume-preserving threshold t), and the notes say so.
* Schedule: a β stage ends after ≥ 10 iterations with relative objective change < 1e-3 or max|Δx| < 0.01, or after
  20 iterations; the run stops when the β = 16 stage meets the same test (or 40 iterations; 200 in total). This is
  deterministic. Only when the wall-clock budget binds are the stages cut short so that each later stage keeps
  ~10 % and β = 16 ~25 % of the iterations that still fit (≤ 12 each), and the loop stops before the next iteration
  would overrun `budget_s`; both are recorded in the notes. Numerics are bit-reproducible (Pardiso with a fixed
  thread count gave identical solutions run to run).
"""
from __future__ import annotations

import time
from types import SimpleNamespace

import numpy as np
import pymoto as pym
from pymoto.solvers import SolverSparsePardiso
from threadpoolctl import threadpool_limits

from ..domain import DesignDomain, GenResult

NAME = "pyMOTO SIMP"
PENAL = 3.0                     # SIMP exponent
E_MIN = 1e-9                    # void stiffness / E
RHO_TAIL = 0.1                  # below this density the stiffness interpolation is linear (self-weight fix)
FILTER_R = 1.5                  # density-filter radius, voxels
ETA = 0.5                       # Heaviside threshold
BETAS = (1.0, 2.0, 4.0, 8.0, 16.0)
MOVE = 0.2                      # MMA move limit
MIN_STAGE, MAX_STAGE, MAX_FINAL, MAX_ITER = 10, 20, 40, 200
TOL_F, TOL_X = 1e-3, 1e-2       # stage convergence: relative objective change, max design change
SQ_STAGE, SQ_FINAL = 12, 12     # iterations kept for each later β stage when the budget binds (see _run)
REMAP_TOL = 0.01                # volume-preserving remap only if the 0.5-cut misses the design volume by more


class _Scatter(pym.Module):
    """Design variables → element vector with the passive voxels at their fixed values."""

    def __init__(self, design_el: np.ndarray, base: np.ndarray):
        self.design_el, self.base = design_el, base

    def __call__(self, x):
        y = self.base.copy()
        y[self.design_el] = x
        return y

    def _sensitivity(self, dy):
        return dy[self.design_el]


class _Heaviside(pym.Module):
    """Smoothed Heaviside projection (Wang, Lazarov & Sigmund 2011); `beta` is changed between iterations."""

    def __init__(self, beta: float, eta: float = ETA):
        self.beta, self.eta = beta, eta

    def __call__(self, x):
        b, e = self.beta, self.eta
        return (np.tanh(b * e) + np.tanh(b * (x - e))) / (np.tanh(b * e) + np.tanh(b * (1.0 - e)))

    def _sensitivity(self, dy):
        b, e = self.beta, self.eta
        x = self.get_input_states()
        return dy * b * (1.0 - np.tanh(b * (x - e)) ** 2) / (np.tanh(b * e) + np.tanh(b * (1.0 - e)))


class _Simp(pym.Module):
    """Relative Young's modulus E_MIN + (1 − E_MIN)·s(ρ), s = ρ^p for ρ ≥ ρ_t and ρ_t^(p−1)·ρ below."""

    def __call__(self, rho):
        s = np.where(rho >= RHO_TAIL, np.abs(rho) ** PENAL, RHO_TAIL ** (PENAL - 1.0) * rho)
        return E_MIN + (1.0 - E_MIN) * s

    def _sensitivity(self, dy):
        rho = self.get_input_states()
        ds = np.where(rho >= RHO_TAIL, PENAL * np.abs(rho) ** (PENAL - 1.0), RHO_TAIL ** (PENAL - 1.0))
        return dy * (1.0 - E_MIN) * ds


class _Loads(pym.Module):
    """Load block F (ndof × ncases): fixed contact load F0 + self-weight ρ_e·m_vox·a_c, 1/8 to each element node.
    Rows of clamped dofs are zero (pyMOTO's Dirichlet rows carry a diagonal only)."""

    def __init__(self, F0: np.ndarray, conn: np.ndarray, accel: np.ndarray, m_vox: float, bc: np.ndarray):
        self.F0, self.conn, self.acc, self.m, self.bc = F0, conn, accel, m_vox, bc
        self.nn, self.nc = F0.shape[0] // 3, F0.shape[1]

    def __call__(self, rho):
        mn = np.bincount(self.conn.ravel(), weights=np.repeat(rho, 8), minlength=self.nn) * (self.m / 8.0)
        F = self.F0 + (mn[:, None, None] * self.acc.T[None, :, :]).reshape(3 * self.nn, self.nc)
        F[self.bc] = 0.0
        return F

    def _sensitivity(self, dF):
        dF = np.array(dF, dtype=float)
        dF[self.bc] = 0.0
        g = np.einsum("nkc,ck->n", dF.reshape(self.nn, 3, self.nc), self.acc)
        return (self.m / 8.0) * g[self.conn].sum(axis=1)


class _DesignMean(pym.Module):
    """Mean physical density of the design voxels."""

    def __init__(self, design_el: np.ndarray):
        self.idx = design_el

    def __call__(self, rho):
        return np.float64(np.mean(rho[self.idx]))

    def _sensitivity(self, dv):
        d = np.zeros_like(self.get_input_states())
        d[self.idx] = dv / self.idx.size
        return d


class _Pardiso(SolverSparsePardiso):
    """pyMOTO's MKL-Pardiso wrapper keeping the symbolic factorisation (phase 11) between design iterations — the
    stiffness sparsity pattern never changes — so each update is a numerical refactorisation (phase 22) only."""

    def update(self, A):
        if self._phase != 33 or getattr(self, "A", None) is None or A.shape != self.A.shape:
            return super().update(A)
        self.A = self._check_A(A)
        self._phase = 22
        self._iparm[11] = 0
        self._call_pardiso()
        self._phase = 33
        return self


def _link(mods: list, module, sig_in, tag: str):
    """Connect `module` (computes its response once) without touching pyMOTO's global default network."""
    module.connect(sig_in, pym.Signal(tag))
    mods.append(module)
    return module.sig_out[0]


def _clamped_dofs(domain: DesignDomain, dom: pym.VoxelDomain) -> np.ndarray:
    """All dofs of the fixed voxels' nodes on the target-plane face (the face of the fixed layer on the plane)."""
    fi = np.argwhere(domain.fixed)
    ax = int(domain.axis)
    o1, o2 = [a for a in range(3) if a != ax]
    nodes = []
    for d1 in (0, 1):
        for d2 in (0, 1):
            ijk = fi.copy()
            ijk[:, ax] += 0 if domain.neg else 1
            ijk[:, o1] += d1
            ijk[:, o2] += d2
            nodes.append(dom.get_nodenumber(ijk[:, 0], ijk[:, 1], ijk[:, 2]))
    nodes = np.unique(np.concatenate(nodes))
    return np.asarray(dom.get_dofnumber(nodes, np.arange(3), 3)).ravel()


def _volume_preserving(rho: np.ndarray, design: np.ndarray, target: float) -> tuple[np.ndarray, float]:
    """Monotone remap (0 → 0, t → 0.5, 1 → 1) with t chosen so that the design voxels ≥ 0.5 hold `target`."""
    v = np.sort(rho[design])[::-1]
    k = round(target * v.size)
    if v.size == 0 or k <= 0 or k >= v.size:
        return rho, 0.5
    t = 0.5 * (v[k - 1] + v[k])
    if not 1e-6 < t < 1.0 - 1e-6:
        return rho, 0.5
    out = np.where(rho < t, 0.5 * rho / t, 0.5 + 0.5 * (rho - t) / (1.0 - t))
    return np.clip(out, 0.0, 1.0), float(t)


def build(domain: DesignDomain) -> SimpleNamespace:
    """The pyMOTO network of `domain` (design variables at vol_frac, β at its first value), evaluated once.

    Returned fields: `fn` (Network), signals `x` (design variables), `rho` (physical density per element), `F`, `U`,
    `compliance`, `objective`, `volume`, `g_volume`; modules `heaviside`, `linsolve`; and the mesh data."""
    nx, ny, nz = (int(n) for n in domain.shape)
    h = float(domain.h)
    mat = domain.material
    vf = float(domain.vol_frac)
    void = np.asarray(domain.void, bool)
    solid = (np.asarray(domain.fixed, bool) | np.asarray(domain.contact, bool)) & ~void
    design = domain.design()
    contact = np.asarray(domain.contact, bool) & ~void
    if not domain.fixed.any():
        raise ValueError("domain has no fixed voxels to clamp")
    if not contact.any():
        raise ValueError("domain has no contact voxels to load")
    if not design.any():
        raise ValueError("domain has no design voxels")

    dom = pym.VoxelDomain(nx, ny, nz, unitx=h, unity=h, unitz=h)
    el = dom.elements                                       # grid [i, j, k] → pyMOTO element number
    design_el, solid_el, void_el = el[design], el[solid], el[void]
    base = np.zeros(dom.nel)
    base[solid_el] = 1.0

    bc = _clamped_dofs(domain, dom)
    cases = domain.load_cases()
    Fc = np.array([c["contact_force_n"] for c in cases], float)           # (ncases, 3) N
    acc = np.array([c["body_accel_mm_s2"] for c in cases], float)         # (ncases, 3) mm/s²
    c_el = el[contact]
    w = np.bincount(dom.conn[c_el].ravel(), minlength=dom.nnodes) / (8.0 * c_el.size)
    F0 = (w[:, None, None] * Fc.T[None, :, :]).reshape(3 * dom.nnodes, len(cases))
    m_vox = float(mat["rho_t_mm3"]) * h ** 3                              # t; t·mm/s² = N

    use_pardiso = SolverSparsePardiso.defined
    solver = _Pardiso(symmetric=True, hermitian=True, positive_definite=True) if use_pardiso else None

    mods: list = []
    sx = pym.Signal("x", state=np.full(design_el.size, vf))
    s_el = _link(mods, _Scatter(design_el, base), sx, "x_el")
    s_f = _link(mods, pym.DensityFilter(dom, radius=FILTER_R), s_el, "x_filt")
    heav = _Heaviside(BETAS[0])
    s_p = _link(mods, heav, s_f, "x_proj")
    passive = np.concatenate([solid_el, void_el])
    s_rho = _link(mods, pym.SetValue(passive, np.concatenate([np.ones(solid_el.size), np.zeros(void_el.size)])),
                  s_p, "rho")
    s_E = _link(mods, _Simp(), s_rho, "E_rel")
    s_K = _link(mods, pym.AssembleStiffness(dom, bc=bc, e_modulus=float(mat["E_mpa"]),
                                            poisson_ratio=float(mat["nu"])), s_E, "K")
    s_F = _link(mods, _Loads(F0, dom.conn, acc, m_vox, bc), s_rho, "F")
    m_solve = pym.LinSolve(symmetric=True, hermitian=True, positive_definite=True, solver=solver)
    s_U = _link(mods, m_solve, [s_K, s_F], "U")
    s_C = _link(mods, pym.EinSum("ij,ij->"), [s_F, s_U], "compliance")
    s_obj = _link(mods, pym.Scaling(scaling=100.0), s_C, "objective")
    s_V = _link(mods, _DesignMean(design_el), s_rho, "volume")
    s_g = _link(mods, pym.Scaling(scaling=10.0, maxval=vf), s_V, "g_volume")
    inner = getattr(m_solve.solver, "solver", m_solve.solver)               # inside pyMOTO's LDAWrapper
    return SimpleNamespace(
        fn=pym.Network(mods), x=sx, rho=s_rho, F=s_F, U=s_U, compliance=s_C, objective=s_obj, volume=s_V,
        g_volume=s_g, heaviside=heav, linsolve=m_solve, dom=dom, el=el, design=design, solid=solid, void=void,
        bc=bc, Fc=Fc, acc=acc, n_contact=int(c_el.size), m_vox=m_vox, names=[c["name"] for c in cases],
        load_on_bc=float(np.abs(F0[bc]).sum() / max(np.abs(F0).sum(), 1e-300)),
        solver_name="MKL Pardiso (symbolic factorisation reused)" if use_pardiso else type(inner).__name__)


def generate(domain: DesignDomain, budget_s: float = 120.0, threads: int = 2) -> GenResult:
    t0 = time.perf_counter()
    with threadpool_limits(limits=max(1, int(threads))):
        return _run(domain, float(budget_s), t0)


def _run(domain: DesignDomain, budget_s: float, t0: float) -> GenResult:
    if not domain.design().any():                           # nothing to optimise: the passives are the bracket
        rho = ((domain.fixed | domain.contact) & ~domain.void).astype(float)
        return GenResult(rho, time.perf_counter() - t0, NAME, notes=["no design voxels: passives only"],
                         iterations=0, history=[])
    P = build(domain)
    vf = float(domain.vol_frac)
    mma = pym.MMA([P.x], [P.objective, P.g_volume], P.fn, move=MOVE, xmin=0.0, xmax=1.0, verbosity=0)
    t_setup = time.perf_counter() - t0

    x = mma.x
    hist: list[float] = []
    t_it: list[float] = []
    per_stage = [0] * len(BETAS)
    squeezed: list[int] = []
    it = stage = 0
    stop, dxmax = "iteration limit", float("nan")
    while it < MAX_ITER:
        ts = time.perf_counter()
        if it > 0 and (ts - t0) + 1.5 * max(t_it[-3:]) > budget_s:
            stop = f"budget ({budget_s:.0f} s)"
            break
        xnew, _, _ = mma.step(x)                            # evaluates x (ρ, U, … now belong to x)
        it += 1
        per_stage[stage] += 1
        n_st = per_stage[stage]
        hist.append(float(P.compliance.state))
        t_it.append(time.perf_counter() - ts)
        dxmax = float(np.max(np.abs(xnew - x)))
        rel_df = abs(hist[-1] - hist[-2]) / abs(hist[-1]) if n_st > 1 else np.inf
        converged = n_st >= MIN_STAGE and (rel_df < TOL_F or dxmax < TOL_X)
        last = stage == len(BETAS) - 1
        squeeze = False
        if not last:                                        # will the remaining β stages still fit the budget?
            t_avg = float(np.mean((t_it[1:] or t_it)[-3:]))
            left = int((budget_s - (time.perf_counter() - t0)) / t_avg) - 1
            n_est = it + left
            q_stage = min(SQ_STAGE, max(2, round(0.1 * n_est)))
            q_final = min(SQ_FINAL, max(6, round(0.25 * n_est)))
            squeeze = left <= (len(BETAS) - 2 - stage) * q_stage + q_final
        if converged or squeeze or n_st >= (MAX_FINAL if last else MAX_STAGE):
            if last:
                stop = "converged" if converged else "final-stage iteration limit"
                break
            if squeeze and not converged and n_st < MAX_STAGE:
                squeezed.append(it)
            stage += 1
            P.heaviside.beta = BETAS[stage]
        x = xnew
        mma.response_is_uptodate = False
    stages = ", ".join(f"{b:g}: {n}" for b, n in zip(BETAS, per_stage) if n)
    if squeezed:
        stages += f"; budget-compressed stage ends after iterations {squeezed}"

    # Results of the last evaluated design
    design, solid, void = P.design, P.solid, P.void
    rho = np.clip(np.asarray(P.rho.state, float), 0.0, 1.0)[P.el]
    rho[void] = 0.0
    rho[solid] = 1.0
    vf_c = float(rho[design].mean())
    vf_t_raw = float((rho[design] >= 0.5).mean())
    out, t_thr = rho, 0.5
    if abs(vf_t_raw - vf_c) > REMAP_TOL:
        out, t_thr = _volume_preserving(rho, design, vf_c)
    vf_t = float((out[design] >= 0.5).mean())
    cc = np.einsum("ij,ij->j", np.asarray(P.F.state), np.asarray(P.U.state))
    sw = float(P.m_vox * rho.sum() * np.linalg.norm(P.acc[0]))               # self-weight force magnitude, N
    gray = float(np.mean((rho[design] > 0.05) & (rho[design] < 0.95)))
    case_c = ", ".join(f"{n}: {c:.4g}" for n, c in zip(P.names, cc))
    remap = f" → {vf_t:.4f} after a volume-preserving remap (t = {t_thr:.3f} → 0.5)" if t_thr != 0.5 else ""
    notes = [
        (f"pyMOTO {pym.__version__}: VoxelDomain {tuple(domain.shape)} of 8-node hexahedra, h = {domain.h} mm "
         f"({P.dom.nnodes * 3} dofs), DensityFilter r = {FILTER_R} voxels, Heaviside η = {ETA}, SIMP p = {PENAL} "
         f"(E_min = {E_MIN:g} E, linear below ρ = {RHO_TAIL}), MMA (MMA2007, move {MOVE}), LinSolve with "
         f"{P.solver_name}"),
        (f"supports: all 3 dofs of the {P.bc.size // 3} target-plane face nodes of the {int(domain.fixed.sum())} "
         f"fixed voxels clamped ({100 * P.load_on_bc:.1f} % of the contact load lands on clamped nodes, dropped)"),
        (f"loads: {len(P.names)} cases (68 g x, y, z) as one 3-RHS solve; each case's contact force "
         f"({np.linalg.norm(P.Fc[0]):.1f} N) spread uniformly over the {P.n_contact} contact voxels, 1/8 per node; "
         f"self-weight included (ρ·m·a, final bracket {sw:.2f} N per case)"),
        ("objective: sum of the 3 load-case compliances; constraint: mean physical density of the design voxels "
         f"≤ vol_frac {vf}; passives: void ρ = 0, fixed + contact ρ = 1"),
        (f"{it} iterations, stop: {stop} (last max|Δx| {dxmax:.4f}); iterations per β {{{stages}}}; "
         f"setup {t_setup:.1f} s, mean iteration {np.mean(t_it):.2f} s"),
        (f"compliance (N·mm, last design, continuous ρ, incl. self-weight): total {cc.sum():.4g} ({case_c}); "
         f"first iterate {hist[0]:.4g}"),
        (f"design volume fraction: continuous {vf_c:.4f}, thresholded (≥ 0.5) {vf_t_raw:.4f}{remap}; "
         f"gray (0.05–0.95) {100 * gray:.1f} %"),
    ]
    return GenResult(out, time.perf_counter() - t0, NAME, notes=notes, iterations=it, history=hist)
