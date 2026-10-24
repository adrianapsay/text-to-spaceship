"""Active-element SIMP for brackets that hold several parts (M4: combined per wall, one piece).

Why not the contest winner's own loop (gd/entrants/pytopo3d_simp.py): pytopo3d assembles every voxel of the bounding
grid, the void ones too (at Emin), so a domain that is a union of boxes, or the free space between the parts, would
pay for the whole grid. Here only the ACTIVE elements (the non-void voxels) exist: the nodes and degrees of freedom
are those of active elements, nothing else is assembled or solved.

The method is the winner's (pytopo3d 0.3.0, Kim & Kang), re-implemented on the active elements:

* trilinear 8-node hexahedra on the voxel grid; a voxel may be a box (hx, hy, hz), so that one grid can lie exactly on
  all six inner planes of the enclosure (one piece); stiffness E·(Emin + x^p (1 − Emin)), p = 3, Emin = 1e-9;
* the sum of the three load cases' compliances (68 g along x, y and z on every held part, at its centre of mass,
  spread over its contact voxels RBE3-like: gd.multi); one factorisation per iteration with three right-hand sides
  (PARDISO through pypardiso's MKL handle, real symmetric positive definite, upper triangle; the symbolic analysis
  once, the pattern never changes); clamped nodes are identity rows;
* passive solid (bolted layer, contact layer, bosses, plate, skin) held at 1; only design voxels count in the volume
  constraint; a linear density filter of radius rmin over the design voxels only (renormalised), as in the winner's
  entrant;
* the optimality-criteria update (move 0.2, bisection on the multiplier), stop at max|Δx| ≤ 0.01 or the iteration cap;
* coarse-to-fine continuation (solve): the problem on voxels twice as large first, its densities as the start on the
  fine grid;
* a wall-clock budget: each level's iteration cap comes from a cost model in the number of degrees of freedom
  (seconds_per_iteration), so the result does not depend on timing unless the machine is slower than the model (then a
  guard stops earlier, and the notes say so).

Not modelled in the optimisation (as in the winner's entrant): the bracket's own weight (the FE check adds it).
Units: mm, N, MPa.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field

import numpy as np

os.environ.setdefault("MKL_CBWR", "AUTO")        # repeatable multi-threaded PARDISO (see pytopo3d_simp.py)
os.environ.setdefault("KMP_BLOCKTIME", "0")

PENAL = 3.0
EMIN = 1e-9
TOLX = 0.01
MOVE = 0.2
MAX_ITER = 200

LOCAL = np.array([[n & 1, (n >> 1) & 1, (n >> 2) & 1] for n in range(8)])      # local node n = dx + 2 dy + 4 dz


def hex8_stiffness(h, E: float = 1.0, nu: float = 0.3) -> np.ndarray:
    """24 × 24 stiffness of a trilinear brick with edges h = (hx, hy, hz) (2 × 2 × 2 Gauss points: exact for a
    brick). Local node n = dx + 2 dy + 4 dz, dofs 3n + (0, 1, 2) = (ux, uy, uz)."""
    h = np.asarray(h, float).reshape(3)
    lam, mu = E * nu / ((1 + nu) * (1 - 2 * nu)), E / (2 * (1 + nu))
    D = np.zeros((6, 6))
    D[:3, :3] = lam
    D[np.arange(3), np.arange(3)] += 2 * mu
    D[3:, 3:] = np.eye(3) * mu
    c = LOCAL.astype(float)
    s = 2 * c - 1
    g = 0.5 + np.array([-1.0, 1.0]) / (2.0 * np.sqrt(3.0))       # Gauss points on [0, 1], weights 1/2
    K = np.zeros((24, 24))
    for a in g:
        for b in g:
            for z in g:
                xi = np.array([a, b, z])
                f = c * xi + (1 - c) * (1 - xi)                   # (8, 3) factors of N_n = Π_k f_nk
                dN = np.stack([s[:, 0] * f[:, 1] * f[:, 2], f[:, 0] * s[:, 1] * f[:, 2],
                               f[:, 0] * f[:, 1] * s[:, 2]], axis=1) / h
                B = np.zeros((6, 24))
                for n in range(8):
                    B[0, 3 * n], B[1, 3 * n + 1], B[2, 3 * n + 2] = dN[n]
                    B[3, 3 * n], B[3, 3 * n + 1] = dN[n, 1], dN[n, 0]           # γ_xy
                    B[4, 3 * n + 1], B[4, 3 * n + 2] = dN[n, 2], dN[n, 1]       # γ_yz
                    B[5, 3 * n], B[5, 3 * n + 2] = dN[n, 2], dN[n, 0]           # γ_zx
                K += B.T @ D @ B * (np.prod(h) / 8.0)
    return 0.5 * (K + K.T)


@dataclass
class SimpProblem:
    """One SIMP problem on the active voxels of a grid (nx, ny, nz): `active` voxels exist (not void); `solid` is the
    passive solid; `fixed` voxels have their 8 nodes clamped; `forces`: per load case (nx, ny, nz, 3) N per voxel,
    spread 1/8 to its nodes (as pytopo3d spreads an element force)."""
    h: np.ndarray
    active: np.ndarray
    solid: np.ndarray
    fixed: np.ndarray
    forces: list
    nu: float = 0.3
    rmin_mm: float = 3.0
    notes: list = field(default_factory=list)

    def __post_init__(self):
        from scipy import ndimage
        self.h = np.asarray(self.h, float).reshape(3)
        self.shape = tuple(int(x) for x in self.active.shape)
        # only voxels joined through shared faces to a fixed voxel can carry load: any other piece (or one hanging on
        # an edge or a corner) would be a mechanism and make K singular
        lab, _ = ndimage.label(self.active & True)
        keep = np.unique(lab[self.fixed & self.active])
        keep = keep[keep > 0]
        reach = np.isin(lab, keep)
        self.dropped = int((self.active & ~reach).sum())
        self.active = self.active & reach
        self.solid = self.solid & self.active
        self.fixed = self.fixed & self.active
        self.design = self.active & ~self.solid
        idx = np.argwhere(self.active)
        self.elems = idx
        self.ne = len(idx)
        if not self.fixed.any():
            raise ValueError("no fixed voxels: the problem has no support")
        nx, ny, _ = self.shape
        corners = idx[:, None, :] + LOCAL[None, :, :]
        gid = corners[..., 0] + (nx + 1) * (corners[..., 1] + (ny + 1) * corners[..., 2])
        used, inv = np.unique(gid, return_inverse=True)
        self.enodes = inv.reshape(-1, 8).astype(np.int64)        # compact node ids per element
        self.nn = len(used)
        self.ndof = 3 * self.nn
        self.edof = (3 * self.enodes[:, :, None] + np.arange(3)[None, None, :]).reshape(-1, 24)
        fixed_nodes = np.unique(self.enodes[self.fixed[tuple(idx.T)]])
        self.fixed_dofs = (3 * fixed_nodes[:, None] + np.arange(3)[None, :]).ravel()
        cons = np.zeros(self.ndof, bool)
        cons[self.fixed_dofs] = True
        self.cons = cons
        self.loads = []
        for F in self.forces:
            fe = np.asarray(F, float)[tuple(idx.T)] / 8.0
            f = np.zeros(self.ndof)
            for k in range(3):
                np.add.at(f, self.edof[:, k::3].ravel(), np.repeat(fe[:, k], 8))
            f[cons] = 0.0
            self.loads.append(f)
        self.KE = hex8_stiffness(self.h, 1.0, self.nu)
        self._pattern()
        self._filter()
        self.is_design = self.design[tuple(idx.T)]
        self.n_design = int(self.is_design.sum())

    def _pattern(self):
        """CSR pattern of the upper triangle of K over every active dof, and P[e, k]: the data position of element
        e's k-th upper-triangle entry (row-major, columns sorted), built from the node pairs that share an element."""
        n_n = self.nn
        ia, ib = np.triu_indices(8)                               # 36 node pairs of an element (with the diagonal)
        gi, gj = self.enodes[:, ia], self.enodes[:, ib]
        lo, hi = np.minimum(gi, gj), np.maximum(gi, gj)
        keys = np.unique((lo.astype(np.int64) * n_n + hi).ravel())     # coupled node pairs i ≤ j, sorted
        ki, kj = keys // n_n, keys % n_n
        first = np.searchsorted(keys, np.arange(n_n, dtype=np.int64) * n_n + np.arange(n_n))   # (i, i): first of i
        m = np.diff(np.concatenate([first, [len(keys)]]))          # |J_i|: coupled j ≥ i, i itself included
        rowlen = np.stack([3 - np.arange(3)[None, :] + 3 * (m[:, None] - 1)], 0)[0]      # (n_n, 3)
        indptr = np.concatenate([[0], np.cumsum(rowlen.ravel())]).astype(np.int64)
        # columns of every row: for node i, row 3i + d: (i, d..2) then (j, 0..2) for j in J_i \ {i}
        cols = np.empty(indptr[-1], np.int32)
        rank = np.arange(len(keys)) - first[ki]                    # rank of j in J_i (0 for j = i)
        for d in range(3):
            start = indptr[3 * np.arange(n_n) + d]
            for e in range(3):
                # the diagonal block (j = i): columns 3i + e for e ≥ d
                if e >= d:
                    cols[start + (e - d)] = (3 * np.arange(n_n) + e).astype(np.int32)
                off = (3 - d) + 3 * (rank - 1) + e
                sel = rank > 0
                cols[start[ki[sel]] + off[sel]] = (3 * kj[sel] + e).astype(np.int32)
        self.indptr, self.indices = indptr, cols
        # element entries → positions
        iu, ju = np.triu_indices(24)
        P = np.empty((self.ne, len(iu)), np.int32)
        na, da, nb, db = iu // 3, iu % 3, ju // 3, ju % 3
        for k in range(len(iu)):
            A = self.enodes[:, na[k]]
            B = self.enodes[:, nb[k]]
            swap = A > B
            i_ = np.where(swap, B, A)
            j_ = np.where(swap, A, B)
            di = np.where(swap, db[k], da[k])
            dj = np.where(swap, da[k], db[k])
            same = i_ == j_
            d_lo = np.where(same, np.minimum(di, dj), di)
            d_hi = np.where(same, np.maximum(di, dj), dj)
            kk = np.searchsorted(keys, i_.astype(np.int64) * n_n + j_)
            r = kk - first[i_]
            off = np.where(same, d_hi - d_lo, (3 - d_lo) + 3 * (r - 1) + d_hi)
            P[:, k] = (indptr[3 * i_ + d_lo] + off).astype(np.int32)
        self.P = P
        self.KEu = self.KE[iu, ju]
        self.nnz = int(indptr[-1])
        # entries that couple a clamped dof to anything (zeroed), and the clamped diagonals (set to 1)
        row = np.repeat(np.arange(len(indptr) - 1), np.diff(indptr))
        self.zero = self.cons[row] | self.cons[cols]
        self.cdiag = indptr[self.fixed_dofs]                       # the diagonal is the first entry of its row

    def _filter(self):
        """Density filter over the design voxels only (renormalised), radius rmin (mm, world distance between voxel
        centres); passive voxels are not filtered."""
        import scipy.sparse as sp
        from scipy.spatial import cKDTree
        idx = self.elems
        des = np.flatnonzero(self.design[tuple(idx.T)])
        c = (idx[des] + 0.5) * self.h
        r = max(float(self.rmin_mm), 1.5 * float(self.h.max()))
        self.rmin = r
        pairs = cKDTree(c).query_pairs(r, output_type="ndarray") if len(des) else np.zeros((0, 2), int)
        i = np.concatenate([np.arange(len(des)), pairs[:, 0], pairs[:, 1]])
        j = np.concatenate([np.arange(len(des)), pairs[:, 1], pairs[:, 0]])
        w = np.maximum(0.0, r - np.linalg.norm(c[i] - c[j], axis=1))
        self.H = sp.csr_matrix((w, (des[i], des[j])), shape=(self.ne, self.ne))
        self.Hs = np.asarray(self.H.sum(axis=1)).ravel()
        self.des_idx = des

    def filt(self, x: np.ndarray) -> np.ndarray:
        """Densities on the active elements → physical densities (passive solid 1, design filtered)."""
        out = np.ones(self.ne)
        d = self.des_idx
        out[d] = (self.H @ x)[d] / np.maximum(self.Hs[d], 1e-300)
        return out

    def filt_t(self, g: np.ndarray) -> np.ndarray:
        """Transpose of filt on the design part (chain rule for the sensitivities)."""
        d = self.des_idx
        z = np.zeros(self.ne)
        z[d] = g[d] / np.maximum(self.Hs[d], 1e-300)
        return self.H.T @ z

    def stiffness(self, xphys: np.ndarray, penal: float, chunk: int = 20000):
        """Upper-triangle CSR of K (all active dofs; clamped dofs are identity rows) for physical densities xphys."""
        import scipy.sparse as sp
        Ee = EMIN + xphys ** penal * (1.0 - EMIN)
        data = np.zeros(self.nnz)
        for s in range(0, self.ne, chunk):
            w = (Ee[s:s + chunk, None] * self.KEu[None, :]).ravel()
            data += np.bincount(self.P[s:s + chunk].ravel(), weights=w, minlength=self.nnz)
        data[self.zero] = 0.0
        data[self.cdiag] = 1.0
        return sp.csr_matrix((data, self.indices, self.indptr), shape=(self.ndof, self.ndof))


class Pardiso:
    """PARDISO (MKL, through pypardiso's library handle) for a real symmetric positive definite matrix given as its
    upper triangle: the symbolic analysis once for the fixed pattern, then numeric factorisation + solve per call."""

    def __init__(self):
        from pypardiso import PyPardisoSolver
        self.s = PyPardisoSolver(mtype=2)
        self.analysed = False

    def solve(self, A, B: np.ndarray) -> np.ndarray:
        if not A.has_sorted_indices:
            A.sort_indices()
        B = np.asfortranarray(B, dtype=np.float64)
        if not self.analysed:
            self.s.set_phase(11)
            self.s._call_pardiso(A, B)
            self.analysed = True
        self.s.set_phase(23)
        return self.s._call_pardiso(A, B)

    def free(self):
        import contextlib

        import scipy.sparse as sp
        with contextlib.suppress(Exception):           # freeing MKL's memory is best effort
            self.s.set_phase(-1)
            self.s._call_pardiso(sp.csr_matrix(np.ones((1, 1))), np.zeros((1, 1)))


SECONDS_AT_50K = 0.25        # cost model of one iteration at 50 k dofs (ASSUMED until measured, docs/notes/m4.md)
GROWTH = 1.4


def seconds_per_iteration(ndof: int, threads: int = 4) -> float:
    """Cost model of one OC iteration (assembly, factorisation with three right-hand sides, sensitivities, filter,
    update): SECONDS_AT_50K at 50 k dofs, growing as dofs^GROWTH; fewer than 4 threads: 1.6 × (ASSUMED)."""
    t = SECONDS_AT_50K * (max(int(ndof), 1) / 5.0e4) ** GROWTH
    return float(t * (1.0 if threads >= 4 else 1.6))


def run_oc(p: SimpProblem, volfrac: float, penal: float = PENAL, maxloop: int = MAX_ITER, tolx: float = TOLX,
           x0: np.ndarray | None = None, deadline: float | None = None, progress=None) -> dict:
    """The OC loop (top3d's update, as in the winner's entrant) on the active elements. x0: start densities on the
    active elements (continuation); else the volume fraction on every design voxel."""
    solver = Pardiso()
    x = np.full(p.ne, float(volfrac)) if x0 is None else np.clip(np.asarray(x0, float), 0.0, 1.0).copy()
    x[~p.is_design] = 1.0
    xphys = p.filt(x)
    F = np.stack(p.loads, axis=1)
    dv = np.maximum(p.filt_t(np.where(p.is_design, 1.0, 0.0)), 1e-12)
    hist, change, loop, stop, t_iter = [], 1.0, 0, "converged", 0.0
    xn = x[p.is_design]
    try:
        while change > tolx and loop < maxloop:
            if deadline is not None and time.perf_counter() + 2.0 * t_iter > deadline:
                stop = "wall-clock guard (timing-dependent result)"
                break
            t1 = time.perf_counter()
            loop += 1
            U = solver.solve(p.stiffness(xphys, penal), F)            # (ndof, n_cases)
            ue = U[p.edof]                                             # (ne, 24, n_cases)
            ce = np.einsum("eac,ab,ebc->e", ue, p.KE, ue)              # Σ over the cases of u_eᵀ KE u_e
            del ue
            c = float(((EMIN + xphys ** penal * (1 - EMIN)) * ce).sum())
            hist.append(c)
            dc = p.filt_t(np.where(p.is_design, -penal * xphys ** (penal - 1) * (1 - EMIN) * ce, 0.0))
            xd, dcd, dvd = x[p.is_design], dc[p.is_design], dv[p.is_design]
            l1, l2 = 0.0, 1e9 * max(1.0, float(np.abs(dcd).max()) if len(dcd) else 1.0)
            target = volfrac * p.n_design
            xt = x.copy()
            while (l2 - l1) / max(l1 + l2, 1e-300) > 1e-6:
                lm = 0.5 * (l1 + l2)
                xn = np.clip(xd * np.sqrt(np.maximum(-dcd, 0.0) / (dvd * lm)), np.maximum(0.0, xd - MOVE),
                             np.minimum(1.0, xd + MOVE))
                xt[p.is_design] = xn
                if p.filt(xt)[p.is_design].sum() > target:
                    l1 = lm
                else:
                    l2 = lm
            change = float(np.abs(xn - xd).max()) if len(xd) else 0.0
            x[p.is_design] = xn
            xphys = p.filt(x)
            dt = time.perf_counter() - t1
            t_iter = dt if loop == 1 else max(0.7 * t_iter, dt)
            if progress is not None:
                progress(loop, c, change)
        else:
            if change > tolx:
                stop = "iteration cap"
    finally:
        solver.free()
    return {"xphys": xphys, "x": x, "iterations": loop, "history": hist, "stop": stop, "change": float(change),
            "seconds_per_iteration": t_iter}


def to_grid(p: SimpProblem, xe: np.ndarray) -> np.ndarray:
    out = np.zeros(p.shape)
    out[tuple(p.elems.T)] = xe
    return out


def coarsen(a: np.ndarray, how: str) -> np.ndarray:
    """2 × 2 × 2 blocks of a grid (odd sizes padded with zeros): any / count / sum."""
    a = np.asarray(a)
    pad = [(0, s % 2) for s in a.shape[:3]] + [(0, 0)] * (a.ndim - 3)
    b = np.pad(a, pad)
    s = b.shape
    b = b.reshape(s[0] // 2, 2, s[1] // 2, 2, s[2] // 2, 2, *s[3:])
    ax = (1, 3, 5)
    if how == "any":
        return b.any(axis=ax)
    if how == "count":
        return b.astype(np.int16).sum(axis=ax)
    if how == "sum":
        return b.sum(axis=ax)
    raise ValueError(how)


def solve(active, solid, fixed, forces, h, nu: float, volfrac: float, rmin_mm: float = 3.0, budget_s: float = 300.0,
          threads: int = 4, continuation: bool = True, max_iter: int = MAX_ITER, progress=None,
          mem_check=None) -> dict:
    """SIMP with coarse-to-fine continuation: on 2 × 2 × 2 blocks first (a block exists where at least half its voxels
    do; it is passive solid or fixed where any voxel is; loads summed), then on the given grid starting from the coarse
    densities. A third of the budget goes to the coarse level; each level's iteration cap comes from the cost model.
    mem_check(dofs, "SIMP") raises MemoryError when the fine level would not fit the memory left: the coarse level's
    densities on the fine grid are then the result (said in the notes and levels); without a coarse level the
    MemoryError reaches the caller. Returns the density on the grid (1 on passive solid, 0 outside the active voxels),
    the levels and notes."""
    from threadpoolctl import threadpool_limits
    t0 = time.perf_counter()
    h = np.asarray(h, float).reshape(3)
    levels, x0 = [], None
    with threadpool_limits(limits=int(threads)):
        if continuation and min(active.shape) >= 8:
            act_c = coarsen(active, "count") >= 4
            sol_c = coarsen(solid & active, "any") & act_c
            fix_c = coarsen(fixed & active, "any") & act_c
            f_c = [coarsen(np.asarray(F, float), "sum") for F in forces]
            if fix_c.any() and int(act_c.sum()) > 8 and int((act_c & ~sol_c).sum()) > 0:
                pc = SimpProblem(2 * h, act_c, sol_c, fix_c, f_c, nu=nu, rmin_mm=max(rmin_mm, 3.0 * float(h.max())))
                cap = int(max(5, min(max_iter, (budget_s / 3.0) / seconds_per_iteration(pc.ndof, threads))))
                rc = run_oc(pc, volfrac, maxloop=cap, deadline=t0 + budget_s / 3.0,
                            progress=None if progress is None else (lambda i, c, d: progress("coarse", i, c, d)))
                levels.append({"level": "coarse", "h_mm": (2 * h).tolist(), "elements": pc.ne, "dofs": pc.ndof,
                               "iterations": rc["iterations"], "stop": rc["stop"],
                               "seconds_per_iteration": rc["seconds_per_iteration"]})
                # the coarse design densities on the fine grid; a fine design voxel in a coarse block that was passive
                # or absent starts at the volume fraction (continuation) and has no density of its own (skip)
                xc = to_grid(pc, np.where(pc.is_design, rc["x"], -1.0))
                xc[to_grid(pc, np.ones(pc.ne)) <= 0.0] = -1.0          # not an element of the coarse problem
                up = np.repeat(np.repeat(np.repeat(xc, 2, 0), 2, 1), 2, 2)[:active.shape[0], :active.shape[1],
                                                                            :active.shape[2]]
                x0 = np.where(up >= 0.0, up, float(volfrac))
                x_skip = np.where(up >= 0.0, up, 0.0)
                del pc, rc
        if mem_check is not None:
            try:
                mem_check(int(3 * 1.15 * int(active.sum())), "SIMP")
            except MemoryError as exc:           # the coarse design, on the fine grid (none: the caller is told)
                if x0 is None:
                    raise
                rho = np.where(active, np.clip(x_skip, 0.0, 1.0), 0.0)
                rho[solid & active] = 1.0
                levels.append({"level": "fine", "h_mm": h.tolist(), "skipped": f"memory: {exc}"})
                return {"density": rho, "seconds": time.perf_counter() - t0, "levels": levels, "history": [],
                        "notes": [(f"fine level skipped ({exc}): the coarse level's densities ({2 * h} mm voxels) are "
                                   "the design")], "ndof": None, "elements": int(active.sum())}
        p = SimpProblem(h, active, solid, fixed, forces, nu=nu, rmin_mm=rmin_mm)
        left = budget_s - (time.perf_counter() - t0)
        cap = int(max(3, min(max_iter, left / seconds_per_iteration(p.ndof, threads))))
        r = run_oc(p, volfrac, maxloop=cap, x0=None if x0 is None else x0[tuple(p.elems.T)], deadline=t0 + budget_s,
                   progress=None if progress is None else (lambda i, c, d: progress("fine", i, c, d)))
        levels.append({"level": "fine", "h_mm": h.tolist(), "elements": p.ne, "dofs": p.ndof,
                       "iterations": r["iterations"], "stop": r["stop"],
                       "seconds_per_iteration": r["seconds_per_iteration"]})
    rho = to_grid(p, r["xphys"])
    rho[~active] = 0.0
    rho[solid & active] = 1.0
    des = p.design
    vf_c = float(rho[des].mean()) if des.any() else 0.0
    vf_t = float((rho[des] >= 0.5).mean()) if des.any() else 0.0
    notes = [f"active-element SIMP: {p.ne} elements of a {p.shape[0]} × {p.shape[1]} × {p.shape[2]} grid, {p.ndof} "
             f"dofs, filter radius {p.rmin:.2f} mm, penal {PENAL}, volume fraction {volfrac} of {p.n_design} design "
             "voxels; " + "; ".join(f"{x['level']}: {x['elements']} elements, {x['iterations']} iterations "
                                   f"({x['stop']})" for x in levels),
             f"design volume fraction: continuous {vf_c:.4f}, thresholded (≥ 0.5) {vf_t:.4f}"]
    return {"density": rho, "seconds": time.perf_counter() - t0, "levels": levels, "notes": notes,
            "history": r["history"], "ndof": p.ndof, "elements": p.ne}
