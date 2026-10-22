"""Primary mass-property integration: float64 signed-tetrahedron (covariance) method.

Exact for polyhedra. Integrals are taken about the bounding-box centre to limit cancellation.
Convention: I = integral(|r|^2 E - r r^T) dV about the COM, so off-diagonal terms are -integral(x y dV).
Values are for unit density in mm units (V in mm^3, J in mm^5); scale by density and units elsewhere.
"""
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class UnitMassProps:
    volume_mm3: float
    com_mm: np.ndarray          # (3,)
    j_mm5: np.ndarray           # (3, 3) unit-density inertia about COM


def integrate(v: np.ndarray, f: np.ndarray) -> UnitMassProps:
    v = np.asarray(v, dtype=np.float64)
    p0 = 0.5 * (v.min(axis=0) + v.max(axis=0))
    a = v[f[:, 0]] - p0
    b = v[f[:, 1]] - p0
    c = v[f[:, 2]] - p0
    d = np.einsum("ij,ij->i", a, np.cross(b, c))
    vol = d.sum() / 6.0
    if vol <= 0:
        raise ValueError(f"non-positive volume {vol}: mesh must be closed and outward-oriented")
    s = a + b + c
    first = (d[:, None] * s).sum(axis=0) / 24.0
    cov = (np.einsum("n,ni,nj->ij", d, s, s) + np.einsum("n,ni,nj->ij", d, a, a)
           + np.einsum("n,ni,nj->ij", d, b, b) + np.einsum("n,ni,nj->ij", d, c, c)) / 120.0
    com_rel = first / vol
    cov_c = cov - vol * np.outer(com_rel, com_rel)
    cov_c = 0.5 * (cov_c + cov_c.T)
    j = np.trace(cov_c) * np.eye(3) - cov_c
    return UnitMassProps(float(vol), p0 + com_rel, j)


def principal(j: np.ndarray, degeneracy_rel: float = 1e-3):
    """Ascending principal moments and a sign-stable, right-handed axis matrix (columns = axes).

    Returns (moments, axes, degenerate_groups) where axes are matched to the body axes by the best of the
    6 permutations and sign-fixed so the matched component is positive.
    """
    w, vecs = np.linalg.eigh(0.5 * (j + j.T))
    scale = max(abs(w[-1]), 1e-300)
    gaps = np.diff(w) / scale
    degenerate = [int(i) for i in np.flatnonzero(gaps < degeneracy_rel)]
    if degenerate:
        # inside a degenerate eigenspace, use the Gram-Schmidt projection of the body axes for a stable basis
        vecs = _stabilise(vecs, w, degeneracy_rel)
    for k in range(3):
        i = int(np.argmax(np.abs(vecs[:, k])))
        if vecs[i, k] < 0:
            vecs[:, k] = -vecs[:, k]
    if np.linalg.det(vecs) < 0:
        align = np.max(np.abs(vecs), axis=0)
        k = int(np.argmin(align))
        vecs[:, k] = -vecs[:, k]
    return w, vecs, degenerate


def _stabilise(vecs, w, tol):
    scale = max(abs(w[-1]), 1e-300)
    groups, cur = [], [0]
    for k in range(1, 3):
        if (w[k] - w[k - 1]) / scale < tol:
            cur.append(k)
        else:
            groups.append(cur)
            cur = [k]
    groups.append(cur)
    out = vecs.copy()
    eye = np.eye(3)
    for g in groups:
        if len(g) == 1:
            continue
        basis = vecs[:, g]
        proj = basis @ basis.T
        chosen = []
        for axis in np.argsort(-np.linalg.norm(proj @ eye, axis=0)):
            cand = proj @ eye[:, axis]
            for q in chosen:
                cand = cand - (cand @ q) * q
            if np.linalg.norm(cand) > 1e-6:
                chosen.append(cand / np.linalg.norm(cand))
            if len(chosen) == len(g):
                break
        for k, q in zip(g, chosen):
            out[:, k] = q
    return out


def misalignment_deg(axes: np.ndarray) -> float:
    """Angle of the rotation between the principal frame and the best-matching signed body-axis permutation."""
    from itertools import permutations
    best = 0.0
    for perm in permutations(range(3)):
        p = np.zeros((3, 3))
        for col, row in enumerate(perm):
            p[row, col] = 1.0
        s = np.sign(np.diag(p.T @ axes))
        s[s == 0] = 1
        p = p * s
        tr = np.trace(p.T @ axes)
        best = max(best, tr)
    c = np.clip((best - 1.0) / 2.0, -1.0, 1.0)
    return float(np.degrees(np.arccos(c)))
