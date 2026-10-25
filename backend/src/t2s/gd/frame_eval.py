"""Whole-satellite check (V2): the frame (gd.frame) with the brackets or the one piece and the held parts, held at the
ends of the rails, under the launch environment. It compares the bracket layouts as structures — what the
frame-bracing one piece is designed for — and is used for every layout: per part, combined, one piece.

* Model, on one grid (gd.frame's extended numbering), assembled with gd.simp.SimpProblem (every element passive):
  the frame's cells (walls and end plates: incompatible-mode bricks, 6061-T6), its rail voxels (6061-T6, scaled) and
  the solid voxels of the brackets or the piece (their material; trilinear bricks, the optimiser's element). Masses
  are lumped, an eighth of each element's mass to each of its nodes.
* Held parts: rigid masses (mass, centre of mass, inertia) tied RBE3-like to the nodes of their contact voxels. The
  reference motion is the least-squares rigid motion of those nodes (equal weights), W (6 × 3n); a part adds
  Wᵀ diag(m, m, m, I) W to the mass and no stiffness, and its load is Wᵀ (m a, 0).
* Supports: the rail-end squares of both end plates, clamped (gd.frame, the user's choice).
* Static: each axis at the launch preset's quasi-static level for the satellite's total mass (environment.static_g:
  the mass–acceleration curve applied to the whole CubeSat — ASSUMED; a launch vehicle's own CubeSat loads are lower).
* Modes: shift-invert Lanczos (scipy eigsh) on the stiffness, factorised once with PARDISO; the mass as an operator.
  N_MODES first, doubled until the highest passes F_COVER × the spectra's upper band edge (2.4 kHz for GEVS) or
  MAX_MODES. Each mode's effective mass along x, y, z is reported, and how much of the total the computed modes hold.
* Memory (gd.layouts.mem_guard): before the factorisation, PARDISO's own forecast from its analysis phase and the
  eigensolver's vectors; before the modes are doubled, the larger basis. When that does not fit, the modes computed so
  far are kept (noted) and the others act through the residual below.
* Random: the preset's limit and qualification spectra at the supports along each axis, all computed modes combined
  (CQC, gd.vibration.modal_covariance), 3σ von Mises per element (Segalman, gd.vibration.vm_rms); the modes not
  computed respond quasi-statically: their residual (missing-mass) shape, K⁻¹Mr − Σ φ_k Γ_k / ω_k², at the input's
  RMS acceleration is added to the stress variance, uncorrelated with the modal part.
* Margins: static (the preset's static factors), random limit (random factors) and random qualification
  (qualification factors), on yield and ultimate, per group — the frame (walls, end plates, rails) and the brackets or
  piece — at the element centres (voxel averages, as the bracket designs' margins).

Units: mm, N, t, s, MPa.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

import numpy as np

from . import environment as _env
from .frame import FRAME_MATERIAL, LOCAL, centre_strain_matrix, elasticity, frame_layer
from .materials import fea_material
from .vibration import modal_covariance, vm_rms, von_mises_voigt

N_MODES = 12            # modes computed first; doubled until they pass F_COVER × the spectra's upper band edge
MAX_MODES = 96
F_COVER = 1.2
STRESS_CHUNK = 4096     # elements whose stresses are recovered at a time


@dataclass
class Rigid:
    """A part as a rigid mass: kg, centre of mass (mm), inertia about it (kg·m²), and the grid voxels whose nodes
    carry it — or `anchor` points (mm; e.g. the feet of the PC/104 rods on their end plate), each tied to its nearest
    model nodes."""
    pid: str
    mass_kg: float
    com: np.ndarray
    inertia: np.ndarray
    contact: np.ndarray
    anchor: np.ndarray | None = None


class Factor:
    """PARDISO (pypardiso's handle, real symmetric positive definite, upper triangle): analysed when made (phase 11,
    ordering and symbolic factorisation, with PARDISO's forecast of its peak memory), factorised once (phase 22), then
    solved many times (phase 33)."""

    def __init__(self, A):
        from pypardiso import PyPardisoSolver
        self.A = A.tocsr()
        self.A.sort_indices()
        self.s = PyPardisoSolver(mtype=2)
        self.s.set_phase(11)
        self.s._call_pardiso(self.A, np.zeros((self.A.shape[0], 1)))
        ip = self.s.iparm                   # KB: the symbolic phase's peak, its permanent part, the numerical factor
        self.forecast_mb = max(float(ip[14]), float(ip[15]) + float(ip[16])) / 1024.0

    def factorise(self) -> None:
        self.s.set_phase(22)
        self.s._call_pardiso(self.A, np.zeros((self.A.shape[0], 1)))

    def solve(self, B: np.ndarray) -> np.ndarray:
        B = np.asarray(B, float)
        one = B.ndim == 1
        self.s.set_phase(33)
        X = self.s._call_pardiso(self.A, np.asfortranarray(B[:, None] if one else B))
        return X[:, 0] if one else X

    def free(self) -> None:
        import contextlib

        import scipy.sparse as sp
        with contextlib.suppress(Exception):
            self.s.set_phase(-1)
            self.s._call_pardiso(sp.csr_matrix(np.ones((1, 1))), np.zeros((1, 1)))


def _vectors_mb(n: int, count: int) -> float:
    """MB of `count` vectors of n dofs (float64)."""
    return count * n * 8 / 2 ** 20


def rigid_map(X: np.ndarray, c: np.ndarray) -> np.ndarray:
    """W (6 × 3n): the least-squares rigid motion (translation, rotation about c) of nodes X (n, 3), equal weights —
    the RBE3 reference motion. u_i = t + θ × r_i, r_i = X_i − c."""
    r = np.asarray(X, float) - np.asarray(c, float)
    n = len(r)
    A = np.zeros((3 * n, 6))
    A[0::3, 0] = A[1::3, 1] = A[2::3, 2] = 1.0
    A[0::3, 4], A[0::3, 5] = r[:, 2], -r[:, 1]
    A[1::3, 3], A[1::3, 5] = -r[:, 2], r[:, 0]
    A[2::3, 3], A[2::3, 4] = r[:, 1], -r[:, 0]
    return np.linalg.pinv(A)


def _group_margins(sig: dict, allow_y: np.ndarray, allow_u: np.ndarray, E) -> dict:
    """The smallest margins over the elements of a group: static, random limit, random qualification; each on yield
    and ultimate with its factors. sig: {"static": (n,), "random limit": (n,), "random qualification": (n,)}."""
    fac = {"static": E.factors["static"], "random limit": E.factors["random"], "random qualification": E.qual_factors}
    rows = []
    for name, s in sig.items():
        f = fac[name]
        s = np.maximum(np.asarray(s, float), 1e-12)
        my = allow_y / (f.yield_ * s) - 1.0
        mu = allow_u / (f.ult * s) - 1.0
        ky, ku = int(np.argmin(my)), int(np.argmin(mu))
        rows.append({"check": name, "ms_yield": float(my[ky]), "ms_ult": float(mu[ku]), "sigma_mpa": float(s[ky]),
                     "element": ky, "factors": [f.yield_, f.ult]})
    worst = min(rows, key=lambda r: min(r["ms_yield"], r["ms_ult"]))
    return {"ms_yield": min(r["ms_yield"] for r in rows), "ms_ult": min(r["ms_ult"] for r in rows),
            "governing": worst["check"], "checks": rows}


@dataclass
class Model:
    """The assembled whole-satellite model (frame_check): the SimpProblem holding the elements and the stiffness K
    (upper-triangle CSR, clamped dofs as identity rows), the lumped masses per dof, the RBE3-tied parts
    [(Rigid, dofs, W, M_ref)], the node coordinates and, per voxel, modulus, density, allowables and group."""
    p: object
    K: object
    layer: object
    mnode: np.ndarray
    mdof: np.ndarray
    rig: list
    X: np.ndarray
    nu: float
    Ev: np.ndarray
    rho: np.ndarray
    ay: np.ndarray
    au: np.ndarray
    grp: np.ndarray
    labels: list
    notes: list

    def mass_mv(self, x: np.ndarray) -> np.ndarray:
        y = self.mdof * x
        for _, dofs, W, Mp in self.rig:
            y[dofs] += W.T @ (Mp @ (W @ x[dofs]))
        y[self.p.cons] = 0.0
        return y

    def total_mass_kg(self) -> float:
        """Every element (the supported nodes' share included) and every part."""
        return float(self.mnode.sum()) * 1e3 + sum(pt.mass_kg for pt, *_ in self.rig)

    def static_loads(self, g: float) -> np.ndarray:
        """(ndof, 3): every mass at g along x, y, z in turn (mm/s² × t = N); the parts through Wᵀ."""
        p = self.p
        F = np.zeros((p.ndof, 3))
        for j in range(3):
            a = np.zeros(3)
            a[j] = g * _env.G0
            F[:, j] = self.mdof * np.tile(a, p.nn)
            for pt, dofs, W, _ in self.rig:
                F[dofs, j] += W.T @ np.concatenate([pt.mass_kg * 1e-3 * a, np.zeros(3)])
        F[p.cons] = 0.0
        return F


def assemble(origin, h, shape, solids: list, parts: list, envelope=None) -> Model:
    """The whole-satellite model (module docstring) on the grid (origin, h, shape): `solids` [(grid mask, material
    id, label)] of the brackets or the piece, `parts` [Rigid]."""
    from .simp import SimpProblem
    h = np.asarray(h, float).reshape(3)
    shape = tuple(int(x) for x in shape)
    L = frame_layer(origin, h, shape, envelope)
    fm = L.material
    vol = float(np.prod(h))
    # per voxel: modulus, density, allowables, group (1 frame rails, 2 brackets / piece)
    Ev, rho, ay, au = (np.zeros(shape) for _ in range(4))
    grp = np.zeros(shape, np.int8)
    labels = []
    for mask, mat_id, label in solids:
        m = fea_material(mat_id)
        sel = np.asarray(mask, bool) & ~L.rail
        Ev[sel], rho[sel], ay[sel], au[sel], grp[sel] = m["E_mpa"], m["rho_t_mm3"], m["yield_mpa"], m["ultimate_mpa"], 2
        labels.append(label)
    r = L.rail
    Ev[r], rho[r] = fm["E_mpa"] * L.rail_scale, fm["rho_t_mm3"] * L.rail_scale
    ay[r], au[r], grp[r] = fm["yield_mpa"], fm["ultimate_mpa"], 1
    active = grp > 0
    nu = float(fea_material(solids[0][1])["nu"]) if solids else float(fm["nu"])
    p = SimpProblem(h, active, active, np.zeros(shape, bool), [], nu=nu, rmin_mm=float(h.max()), frame=L,
                    escale=Ev, frame_escale=float(fm["E_mpa"]), frame_nu=float(fm["nu"]))
    K = p.stiffness(np.ones(p.ne), 3.0)
    idx = p.elems
    me = rho[tuple(idx.T)] * vol                                  # lumped masses (t)
    mn = np.zeros(p.nn)
    np.add.at(mn, p.enodes[:p.ne].ravel(), np.repeat(me / 8.0, 8))
    np.add.at(mn, p.enodes[p.ne:].ravel(), np.repeat(L.cell_masses_t() / 8.0, 8))
    mdof = np.repeat(mn, 3)
    mdof[p.cons] = 0.0
    X = L.node_xyz(p.node_ids)
    elem_of = -np.ones(shape, np.int64)
    elem_of[tuple(idx.T)] = np.arange(p.ne)
    rig, notes = [], []
    for part in parts:                                            # RBE3-tied rigid masses
        if part.anchor is not None and len(part.anchor):
            from scipy.spatial import cKDTree
            free_nodes = np.flatnonzero(~p.cons[0::3])
            _, near = cKDTree(X[free_nodes]).query(np.asarray(part.anchor, float).reshape(-1, 3), k=4)
            nodes = np.unique(free_nodes[np.asarray(near).ravel()])
        else:
            el = elem_of[np.asarray(part.contact, bool) & p.active] if np.shape(part.contact) == shape else []
            el = np.asarray(el, np.int64)
            el = el[el >= 0]
            if not len(el):                    # no contact voxel kept: its mass on the nearest element nodes
                cen = X[p.enodes[:p.ne]].mean(axis=1)
                el = np.argsort(((cen - part.com) ** 2).sum(axis=1))[:8]
                notes.append(f"{part.pid}: no contact voxel in the model — tied to the 8 nearest elements")
            nodes = np.unique(p.enodes[el].ravel())
        W = rigid_map(X[nodes], part.com)
        Mp = np.zeros((6, 6))
        Mp[:3, :3] = np.eye(3) * part.mass_kg * 1e-3
        Mp[3:, 3:] = np.asarray(part.inertia, float) * 1e3        # kg·m² → t·mm²
        dofs = (3 * nodes[:, None] + np.arange(3)[None, :]).ravel()
        rig.append((part, dofs, W, Mp))
    return Model(p, K, L, mn, mdof, rig, X, nu, Ev, rho, ay, au, grp, labels, notes)


def frame_check(origin, h, shape, solids: list, parts: list, env: str | None = None, n_modes: int = N_MODES,
                envelope=None, threads: int = 4, mem_guard=None) -> dict:
    """The whole satellite (module docstring) on the grid (origin, h, shape): `solids` [(grid mask, material id,
    label)] of the brackets or the piece, `parts` [Rigid]. Returns a JSON-ready record."""
    from threadpoolctl import threadpool_limits
    t0 = time.perf_counter()
    E = _env.get(env)
    with threadpool_limits(limits=int(threads)):
        md = assemble(origin, h, shape, solids, parts, envelope)
        p, K, L, X, nu, rig = md.p, md.K, md.layer, md.X, md.nu, md.rig
        fm = L.material
        h = np.asarray(h, float).reshape(3)
        shape = tuple(int(x) for x in shape)
        idx = p.elems
        grp, ay, au = md.grp, md.ay, md.au
        me = md.rho[tuple(idx.T)] * float(np.prod(h))
        mc = L.cell_masses_t()
        m_tot_t = md.total_mass_kg() * 1e-3
        g_s = E.static_g(m_tot_t * 1e3)
        mass_mv = md.mass_mv
        labels, notes = md.labels, md.notes
        F = md.static_loads(g_s)
        R = np.zeros((p.ndof, 3))
        for j in range(3):
            R[3 * np.arange(p.nn) + j, j] = 1.0
        R[p.cons] = 0.0
        MR = np.stack([mass_mv(R[:, j]) for j in range(3)], axis=1)
        f_cover = F_COVER * max(E.random_limit.band[1], E.random_qual.band[1])
        n = p.ndof
        k_max = int(max(1, n - p.cons.sum() - 1))
        k = int(min(n_modes, k_max))
        fac = Factor(K)                                # ordering and symbolic factorisation: PARDISO's memory forecast
        try:
            if mem_guard is not None:                  # the factor, the Lanczos basis, the modes and the static vectors
                mem_guard(n, "whole satellite", need_mb=fac.forecast_mb + _vectors_mb(n, 3 * k + 19))
            fac.factorise()
            U = fac.solve(F)
            U_unit = fac.solve(MR)                     # static response to a unit base acceleration (missing mass)
            from scipy.sparse.linalg import LinearOperator, eigsh
            Mop = LinearOperator((n, n), matvec=mass_mv, dtype=float)
            Kinv = LinearOperator((n, n), matvec=fac.solve, dtype=float)
            while True:                                # modes until they pass the spectra's band (or MAX_MODES)
                lam, phi = eigsh(K, k=k, M=Mop, sigma=0.0, which="LM", OPinv=Kinv)
                if np.sqrt(max(float(lam.max()), 0.0)) / (2 * np.pi) >= f_cover or k >= min(MAX_MODES, k_max):
                    break
                k2 = int(min(2 * k, MAX_MODES, k_max))
                if mem_guard is not None:
                    try:
                        mem_guard(n, "whole satellite", need_mb=_vectors_mb(n, 3 * k2 + 1))
                    except MemoryError as exc:         # the modes computed stay; the rest act through the residual
                        notes.append(f"modes limited to {k} by memory ({exc}): the others respond quasi-statically")
                        break
                k = k2
        finally:
            fac.free()
    order = np.argsort(lam)
    lam, phi = lam[order], phi[:, order]
    for i in range(phi.shape[1]):                                  # mass-normalised
        phi[:, i] /= np.sqrt(max(float(phi[:, i] @ mass_mv(phi[:, i])), 1e-300))
    f_hz = np.sqrt(np.maximum(lam, 0.0)) / (2.0 * np.pi)
    m_free = np.array([R[:, j] @ MR[:, j] for j in range(3)])
    gamma = phi.T @ MR                                             # (n_m, 3)
    eff = gamma ** 2 / m_free[None, :]
    # the modes not computed respond quasi-statically to the base input: the residual (missing-mass) shape per axis
    U_res = U_unit - phi @ (gamma / np.maximum(lam, 1e-300)[:, None])
    # element-centre stresses (Voigt) of the static cases, the modes and the residual shapes, a chunk of elements at a
    # time (all at once, the modal stresses of many modes would outgrow the factorisation)
    Bg = elasticity(1.0, nu) @ centre_strain_matrix(h)             # (6, 24)
    es = p.escale_e
    dims = L.class_dims()
    Bf = np.stack([elasticity(float(fm["E_mpa"]), float(fm["nu"])) @ centre_strain_matrix(d) for d in dims])

    def stresses(V, ids):                      # V (ndof, n) → (len(ids), 6, n); grid elements first, then frame cells
        g, f = ids[ids < p.ne], ids[ids >= p.ne]
        sg = es[g, None, None] * np.einsum("ab,ebn->ean", Bg, V[p.edof[g]])
        sf = np.einsum("eab,ebn->ean", Bf[p.fcls[f - p.ne]], V[p.edof_all[f]])
        return np.concatenate([sg, sf], axis=0)
    covs = [[(modal_covariance(f_hz, gamma[:, j], spec, E.zeta), spec.grms() * _env.G0)
             for spec in (E.random_limit, E.random_qual)] for j in range(3)]
    n_el = p.ne + p.nf
    vm_static, sig_rl, sig_rq = np.zeros(n_el), np.zeros(n_el), np.zeros(n_el)
    for s0 in range(0, n_el, STRESS_CHUNK):
        ids = np.arange(s0, min(s0 + STRESS_CHUNK, n_el))
        vm_static[ids] = np.max(von_mises_voigt(np.moveaxis(stresses(U, ids), 1, 2)), axis=1)
        S_modal = stresses(phi, ids)                               # (chunk, 6, n_m)
        vm_res = von_mises_voigt(np.moveaxis(stresses(U_res, ids), 1, 2))   # (chunk, 3): per unit base acceleration
        for j in range(3):
            for (I, a_rms), out in zip(covs[j], (sig_rl, sig_rq), strict=True):
                # modal part (CQC) and the residual quasi-static part at the input's RMS acceleration, uncorrelated
                out[ids] = np.maximum(out[ids], 3.0 * np.sqrt(vm_rms(S_modal, I) ** 2 + (vm_res[:, j] * a_rms) ** 2))
    g_el = np.concatenate([grp[tuple(idx.T)], np.ones(p.nf, np.int8)])        # frame cells: group 1
    a_y = np.concatenate([ay[tuple(idx.T)], np.full(p.nf, float(fm["yield_mpa"]))])
    a_u = np.concatenate([au[tuple(idx.T)], np.full(p.nf, float(fm["ultimate_mpa"]))])
    cen = np.concatenate([X[p.enodes[:p.ne]].mean(axis=1), X[p.enodes[p.ne:]].mean(axis=1)])
    groups = {}
    for gid, name in ((1, "frame"), (2, "brackets")):
        sel = g_el == gid
        if not sel.any():
            continue
        m = _group_margins({"static": vm_static[sel], "random limit": sig_rl[sel], "random qualification": sig_rq[sel]},
                           a_y[sel], a_u[sel], E)
        for row in m["checks"]:
            row["where_mm"] = cen[np.flatnonzero(sel)[row.pop("element")]].round(2).tolist()
        mass = float(me[grp[tuple(idx.T)] == gid].sum()) + (float(mc.sum()) if gid == 1 else 0.0)
        groups[name] = {**m, "mass_kg": mass * 1e3, "elements": int(sel.sum())}
    disp = np.linalg.norm(U.reshape(p.nn, 3, 3), axis=1)           # (nn, 3 cases)
    kmax = np.unravel_index(int(np.argmax(disp)), disp.shape)
    part_disp = {pt.pid: float(max(np.linalg.norm((W @ U[dofs, j])[:3]) for j in range(3))) for pt, dofs, W, _ in rig}
    return {"environment": E.id, "static_g": float(g_s), "f1_hz": float(f_hz[0]) if len(f_hz) else None,
            "modes": [{"f_hz": float(f_hz[i]), "eff_mass_frac": eff[i].round(4).tolist()}
                      for i in range(min(len(f_hz), 24))],
            "n_modes": len(f_hz), "highest_mode_hz": float(f_hz[-1]) if len(f_hz) else None,
            "eff_mass_captured": eff.sum(axis=0).round(4).tolist(),
            "residual_mass_frac": np.clip(1.0 - eff.sum(axis=0), 0.0, 1.0).round(4).tolist(),
            "max_deflection_mm": float(disp[kmax]), "max_deflection_at_mm": X[kmax[0]].round(2).tolist(),
            "max_deflection_axis": "xyz"[kmax[1]], "part_deflection_mm": part_disp,
            "groups": groups, "total_mass_kg": m_tot_t * 1e3, "frame_mass_kg": L.mass_t() * 1e3,
            "solids": labels, "notes": notes,
            "model": {"h_mm": h.tolist(), "grid": list(shape), "elements": int(p.ne), "frame_cells": int(p.nf),
                      "dofs": int(p.ndof), "supports": int(len(p.fixed_dofs) // 3), "dropped_voxels": int(p.dropped),
                      "n_modes": len(f_hz), "seconds": time.perf_counter() - t0},
            "assumed": ["satellite held at the ends of its four rails (rail-end squares of both end plates clamped)",
                        f"frame: walls and end plates {L.wall:g} mm and corner rails, {FRAME_MATERIAL}",
                        "brackets / piece bonded to the walls, end plates and rails where they meet them",
                        "quasi-static level: the mass-acceleration curve at the satellite's total mass",
                        "parts are rigid masses tied RBE3-like to their contact voxels; masses lumped"]}


def rigid_parts(dom_parts, contact_of=None) -> list:
    """Rigid parts from gd.multi.HeldPart records (their contact masks, or contact_of[pid])."""
    out = []
    for p in dom_parts:
        c = p.contact if contact_of is None else contact_of.get(p.pid)
        out.append(Rigid(p.pid, float(p.mass_kg), np.asarray(p.com, float), np.asarray(p.inertia, float),
                         np.zeros(1, bool) if c is None else np.asarray(c, bool)))
    return out


def voxelise(v: np.ndarray, f: np.ndarray, origin, h, shape) -> np.ndarray:
    """Grid voxels whose centres lie inside the closed mesh (v, f) (ray parity)."""
    from ..geometry.mesh import ray_parity_inside
    h = np.asarray(h, float)
    lo, hi = np.asarray(v, float).min(0), np.asarray(v, float).max(0)
    i0 = np.maximum(np.floor((lo - origin) / h - 0.5).astype(int), 0)
    i1 = np.minimum(np.ceil((hi - origin) / h - 0.5).astype(int) + 1, np.asarray(shape))
    out = np.zeros(shape, bool)
    if np.any(i1 <= i0):
        return out
    ax = [np.arange(i0[k], i1[k]) for k in range(3)]
    idx = np.stack(np.meshgrid(*ax, indexing="ij"), axis=-1).reshape(-1, 3)
    cen = origin + (idx + 0.5) * h
    inside = ray_parity_inside(cen, np.asarray(v, float), np.asarray(f, np.int64)) > 0.5
    out[tuple(idx[inside].T)] = True
    return out


def box_voxels(box, origin, h, shape) -> np.ndarray:
    """Grid voxels whose centres lie in the box (lo, hi)."""
    h = np.asarray(h, float)
    b = np.asarray(box, float)
    ax = [origin[k] + (np.arange(shape[k]) + 0.5) * h[k] for k in range(3)]
    m = [(ax[k] >= b[k]) & (ax[k] <= b[3 + k]) for k in range(3)]
    return m[0][:, None, None] & m[1][None, :, None] & m[2][None, None, :]


MIN_VOXELS = 4           # a solid that covers fewer voxel centres than this is modelled as its reserved box (ESTIMATE)


def layout_frame_check(snap: dict, items: list, threads: int = 4, mem_guard=None, env: str | None = None) -> dict:
    """The whole-satellite check of one bracket layout of a Stage 2 layout (gd.layouts.build_snapshot `snap`), on the
    one-piece grid (even counts). `items`: its brackets, [{"label", "material", "mesh": (v, f) or None, "box": (6,)
    or None}] — a designed or estimated solid, voxelised (centres inside); one too thin for the grid (direct mounts,
    sheet brackets) is modelled as its reserved box, labelled ESTIMATE. Parts: every part with a bracket is a rigid
    mass tied to the solid voxels next to its surface; the PC/104 boards to the feet of their rods on the end plate
    (ASSUMED: rods rigid); any other part to the nearest elements (said in the notes)."""
    from .domain import CONTACT_GAP
    from .multi import _mass_props, _part_world, one_piece_grid, part_masks
    lo, hi = snap["inner"]
    brackets = snap.get("brackets") or []
    origin, h, shape = one_piece_grid(lo, hi, any(int(b["axis"]) == 2 for b in brackets), even=True)
    solids, union, estimated = [], np.zeros(shape, bool), []
    for it in items:
        m = np.zeros(shape, bool)
        if it.get("mesh") is not None:
            m = voxelise(it["mesh"][0], it["mesh"][1], origin, h, shape)
        if int(m.sum()) < MIN_VOXELS and it.get("box") is not None:
            m = box_voxels(it["box"], origin, h, shape)
            estimated.append(it["label"])
        if m.any():
            solids.append((m, it["material"], it["label"]))
            union |= m
    held = {b["pid"] for b in brackets}
    rods = [np.asarray(b, float) for _, kind, b in snap.get("keepouts") or [] if kind == "rod"]
    feet = []
    for r in rods:                                   # the rod's end on an end plate (its other end is the stack)
        z = r[2] if abs(r[2] - lo[2]) < abs(r[5] - hi[2]) else r[5]
        feet.append([0.5 * (r[0] + r[3]), 0.5 * (r[1] + r[4]), z])
    parts, notes = [], []
    reach = CONTACT_GAP + 1.5 * float(np.max(h))
    for pid, (o, t) in snap["poses"].items():
        mass = (snap.get("masses") or {}).get(pid)
        if mass is None:
            notes.append(f"{pid}: mass withheld — left out")
            continue
        v, f = _part_world(snap["records"][pid], o, t)
        com, inertia = _mass_props(v, f, float(mass))
        if pid in held:
            _, _, close = part_masks(origin, h, shape, v, f, CONTACT_GAP, reach)
            parts.append(Rigid(pid, float(mass), com, inertia, close & union))
        elif feet:
            parts.append(Rigid(pid, float(mass), com, inertia, np.zeros(shape, bool), anchor=np.array(feet)))
        else:
            parts.append(Rigid(pid, float(mass), com, inertia, np.zeros(shape, bool)))
    out = frame_check(origin, h, shape, solids, parts, env=env or snap.get("environment"), threads=threads,
                      mem_guard=mem_guard)
    out["estimated"] = estimated
    out["notes"] = notes + out["notes"]
    if feet:
        out["assumed"].append("PC/104 boards: rigid masses on rigid rods, tied at the rods' feet on their end plate")
    E = _env.get(env or snap.get("environment"))
    worst = min((min(g["ms_yield"], g["ms_ult"]) for g in out["groups"].values()), default=None)
    out["f1_guidance_hz"] = float(E.f1_guidance_hz)
    out["passed"] = bool(out["f1_hz"] is not None and out["f1_hz"] >= E.f1_guidance_hz and worst is not None
                         and worst >= 0.0)
    return out


__all__ = ["LOCAL", "MIN_VOXELS", "N_MODES", "Factor", "Model", "Rigid", "assemble", "box_voxels", "frame_check",
           "layout_frame_check", "rigid_map", "rigid_parts", "voxelise"]
