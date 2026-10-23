"""V2 FEA, NGSolve solver: verification against closed-form beam / bar results on the shared gmsh tet10 meshes.

Material: E = 70000 MPa, nu = 0.33, rho = 2.7e-9 t/mm^3. Units: mm, N, MPa, t/mm^3, s.
Run with -s to see the measured values next to the analytical ones.
"""
import dataclasses
import math

import numpy as np
import pytest

from t2s.fea.mesh import boundary_faces, mesh_box
from t2s.fea.ngs import solve, solve_with_fields
from t2s.fea.problem import FeaProblem, LoadCase, Material, SurfaceLoad

E, NU, RHO = 70000.0, 0.33, 2.7e-9
MAT = Material("Al (test)", E, NU, RHO)
G = E / (2 * (1 + NU))
KAPPA = 5.0 / 6.0
G10 = 9806.65 * 10                  # mm/s^2

# cantilever 200 (x) x 10 (y) x 6 (z), clamped at x = 0
L, B, H = 200.0, 10.0, 6.0
A = B * H
I = B * H ** 3 / 12
P = 100.0
H_CANT = 2.0                        # mesh size (mm)
H_BAR = 2.5


def _faces_at_x(nodes, faces, x):
    return faces[np.all(np.isclose(nodes[faces[:, :3]][:, :, 0], x), axis=1)]


def _report(what, measured, analytical):
    err = measured / analytical - 1.0
    print(f"\n  {what}: measured {measured:.6g}, analytical {analytical:.6g}, error {err:+.3%}")
    return err


@pytest.fixture(scope="module")
def cantilever():
    nodes, tets = mesh_box([0, 0, 0], [L, B, H], h=H_CANT)
    faces = boundary_faces(tets)
    fixed = _faces_at_x(nodes, faces, 0.0)
    tip = _faces_at_x(nodes, faces, L)
    cases = [LoadCase("tip", [SurfaceLoad(tip, np.array([0.0, 0.0, -P]))]),
             LoadCase("self-weight 10 g", [], np.array([0.0, 0.0, -G10]))]
    prob = FeaProblem(nodes, tets, MAT, fixed, cases, n_modes=3, label="cantilever")
    res, fields = solve_with_fields(prob, threads=2)
    print(f"\n  cantilever: {len(nodes)} nodes, {len(tets)} tets, solve {res.seconds:.2f} s; {res.notes}")
    return prob, res, fields


def test_cantilever_tip_load(cantilever):
    prob, res, fields = cantilever
    nodes = prob.nodes
    assert res.solver.startswith("NGSolve")
    assert res.n_nodes == len(nodes) and res.n_elements == len(prob.tets)
    assert res.mass_t == pytest.approx(L * B * H * RHO, rel=1e-9)
    case = res.cases[0]

    # mean tip deflection vs Timoshenko (bending + shear)
    tip = np.isclose(nodes[:, 0], L)
    w = -fields.displacement[0][tip, 2].mean()
    w_an = P * L ** 3 / (3 * E * I) + P * L / (KAPPA * G * A)
    assert abs(_report("cantilever mean tip deflection (mm)", w, w_an)) < 0.01
    assert case.max_disp_mm >= w

    # bending stress at the top fibre at mid-span, away from the clamp (nodal-averaged sigma_xx at top-face nodes
    # within 3 mm of x = L/2 and away from the side edges, each moved to x = L/2 with the linear moment M = P (L - x))
    sel = np.isclose(nodes[:, 2], H) & (np.abs(nodes[:, 0] - L / 2) <= 3.0) & (nodes[:, 1] >= 2) & (nodes[:, 1] <= 8)
    assert sel.sum() >= 5
    sxx = fields.stress[0][sel, 0, 0]
    s = float(np.mean(sxx * (L / 2) / (L - nodes[sel, 0])))
    s_an = 6 * P * (L / 2) / (B * H ** 2)
    print(f"\n  ({sel.sum()} top-fibre nodes, raw sigma_xx {sxx.min():.4g} .. {sxx.max():.4g} MPa)")
    assert abs(_report("mid-span top-fibre sigma_xx (MPa)", s, s_an)) < 0.02
    assert s > 0                                                  # tension on top for a downward tip load

    # reactions balance the applied load
    assert np.allclose(case.applied_n, [0.0, 0.0, -P], rtol=0, atol=1e-12)
    bal = np.linalg.norm(case.reaction_n + case.applied_n) / np.linalg.norm(case.applied_n)
    print(f"\n  tip load: reaction {case.reaction_n} N, applied {case.applied_n} N, relative imbalance {bal:.3g}")
    assert bal < 1e-6


def test_cantilever_first_frequency(cantilever):
    _, res, _ = cantilever
    f_an = 1.8751 ** 2 / (2 * math.pi) * math.sqrt(E * I / (RHO * A * L ** 4))
    print(f"\n  cantilever frequencies (Hz): {res.frequencies_hz}")
    assert len(res.frequencies_hz) == 3
    assert abs(_report("cantilever first natural frequency (Hz)", res.frequencies_hz[0], f_an)) < 0.02
    assert res.frequencies_hz == sorted(res.frequencies_hz)


def _tip_mass_beta_l(mu: float) -> float:
    """Lowest root of the Euler-Bernoulli cantilever-with-tip-mass frequency equation
    1 + cos x cosh x + mu x (cos x sinh x - sin x cosh x) = 0, x = beta L, mu = M / (m L)."""
    from scipy.optimize import brentq

    def g(x):
        return 1 + math.cos(x) * math.cosh(x) + mu * x * (math.cos(x) * math.sinh(x) - math.sin(x) * math.cosh(x))
    return brentq(g, 0.05, 1.8751041, xtol=1e-14)


@pytest.mark.parametrize("ratio", [1.0, 5.0])
def test_cantilever_tip_mass_frequency(cantilever, ratio):
    prob, base, base_fields = cantilever
    tip = prob.load_cases[0].surface_loads[0].faces               # the tip face (it also carries the tip load)
    M = ratio * prob.mass_t()                                      # non-structural mass smeared over the tip face
    p2 = dataclasses.replace(prob, n_modes=1, added_masses=[(tip, M)])
    res, fields = solve_with_fields(p2, threads=2)
    assert p2.added_mass_t() == pytest.approx(M, rel=1e-15)
    assert res.mass_t == pytest.approx(base.mass_t, rel=1e-15)     # FeaResult.mass_t stays structural
    assert any("added non-structural mass" in n for n in res.notes)

    x = _tip_mass_beta_l(M / (RHO * A * L))
    f_an = x ** 2 / (2 * math.pi) * math.sqrt(E * I / (RHO * A * L ** 4))
    print(f"\n  tip mass M = {ratio:g} x beam mass ({M:.6g} t): beta L = {x:.6f}; solve {res.seconds:.2f} s")
    assert abs(_report(f"cantilever + {ratio:g}x tip mass, first frequency (Hz)", res.frequencies_hz[0], f_an)) < 0.02

    # the added mass enters the mass matrix only: the static results are unchanged
    du = 0.0
    for c0, c1, d0, d1 in zip(base.cases, res.cases, base_fields.displacement, fields.displacement, strict=True):
        du = max(du, float(np.abs(d1 - d0).max()))
        assert np.abs(d1 - d0).max() <= 1e-9 * np.abs(d0).max()
        assert c1.max_disp_mm == pytest.approx(c0.max_disp_mm, rel=1e-9)
        assert c1.max_vm_mpa == pytest.approx(c0.max_vm_mpa, rel=1e-9)
        assert np.array_equal(c1.applied_n, c0.applied_n)
        assert np.allclose(c1.reaction_n, c0.reaction_n, rtol=0, atol=1e-9 * np.abs(c0.applied_n).max())
    print(f"\n  static results with the added mass: max |u - u_without| = {du:.3g} mm")


def test_self_weight_cantilever(cantilever):
    prob, res, fields = cantilever
    nodes = prob.nodes
    case = res.cases[1]
    q = RHO * A * G10                                             # N/mm
    tip = np.isclose(nodes[:, 0], L)
    w = -fields.displacement[1][tip, 2].mean()
    w_an = q * L ** 4 / (8 * E * I) + q * L ** 2 / (2 * KAPPA * G * A)
    assert abs(_report("self-weight (10 g) mean tip deflection (mm)", w, w_an)) < 0.02
    ma = prob.mass_t() * G10
    assert np.allclose(case.applied_n, [0.0, 0.0, -ma], rtol=1e-12, atol=0)
    bal = np.linalg.norm(case.reaction_n + case.applied_n) / ma
    print(f"\n  self-weight: reaction {case.reaction_n} N, m*a {ma:.6g} N, relative imbalance {bal:.3g}")
    assert bal < 1e-6


def test_axial_bar():
    Lb, Ab, F = 100.0, 100.0, 1000.0
    nodes, tets = mesh_box([0, 0, 0], [Lb, 10, 10], h=H_BAR)
    faces = boundary_faces(tets)
    fixed = _faces_at_x(nodes, faces, 0.0)
    end = _faces_at_x(nodes, faces, Lb)
    excl = np.flatnonzero(nodes[:, 0] < 1e-9)                    # clamp face nodes (exercises the filtered peak)
    prob = FeaProblem(nodes, tets, MAT, fixed, [LoadCase("axial", [SurfaceLoad(end, np.array([F, 0.0, 0.0]))])],
                      n_modes=0, exclude_nodes=excl)
    res, fields = solve_with_fields(prob, threads=2)
    print(f"\n  axial bar: {len(nodes)} nodes, {len(tets)} tets, solve {res.seconds:.2f} s")
    case = res.cases[0]
    assert res.frequencies_hz == []

    mid = np.abs(nodes[:, 0] - Lb / 2) <= 5.0
    sxx = float(fields.stress[0][mid, 0, 0].mean())
    assert abs(_report("bar mid-length sigma_xx (MPa)", sxx, F / Ab)) < 0.01
    vm_mid = float(fields.von_mises[0][mid].mean())
    assert abs(_report("bar mid-length nodal von Mises (MPa)", vm_mid, F / Ab)) < 0.01

    endn = np.isclose(nodes[:, 0], Lb)
    du = float(fields.displacement[0][endn, 0].mean())
    # the clamped face also stops the Poisson contraction there (a local stiffening near x = 0)
    assert abs(_report("bar end elongation (mm)", du, F * Lb / (E * Ab))) < 0.01

    assert case.max_vm_filtered_mpa <= case.max_vm_mpa
    bal = np.linalg.norm(case.reaction_n + case.applied_n) / F
    print(f"\n  axial: reaction {case.reaction_n} N, relative imbalance {bal:.3g}; max vm {case.max_vm_mpa:.4g}, "
          f"filtered {case.max_vm_filtered_mpa:.4g} MPa")
    assert bal < 1e-6


def test_free_free_modes_have_six_rigid_body_modes():
    nodes, tets = mesh_box([0, 0, 0], [L, B, H], h=H_CANT)
    prob = FeaProblem(nodes, tets, MAT, np.zeros((0, 6), np.int64), [], n_modes=7, label="free-free")
    res, fields = solve_with_fields(prob, threads=2)
    f = res.frequencies_hz
    print(f"\n  free-free: {len(nodes)} nodes, solve {res.seconds:.2f} s; frequencies (Hz) {f}; "
          f"eigenvalues (rad/s)^2 {fields.eigenvalues}")
    assert len(f) == 7
    assert np.abs(fields.eigenvalues[:6]).max() < 1e-6 * fields.eigenvalues[6]
    assert max(f[:6]) < 1.0 and f[6] > 100.0
    # the 7th is the first free-free bending mode about y (Euler-Bernoulli 4.7300^2)
    f_ff = 4.7300 ** 2 / (2 * math.pi) * math.sqrt(E * I / (RHO * A * L ** 4))
    assert abs(_report("free-free first elastic frequency (Hz)", f[6], f_ff)) < 0.02


def test_public_solve_and_face_validation():
    nodes, tets = mesh_box([0, 0, 0], [20, 10, 6], h=3.0)
    faces = boundary_faces(tets)
    fixed = _faces_at_x(nodes, faces, 0.0)
    end = _faces_at_x(nodes, faces, 20.0)
    case = LoadCase("pull", [SurfaceLoad(end, np.array([60.0, 0.0, 0.0]))])
    res = solve(FeaProblem(nodes, tets, MAT, fixed, [case], n_modes=1))
    assert res.cases[0].max_vm_mpa > 0 and len(res.frequencies_hz) == 1 and res.seconds > 0
    assert np.linalg.norm(res.cases[0].reaction_n + [60.0, 0, 0]) < 1e-6 * 60
    # a face that is not on the boundary is rejected
    on_boundary = {tuple(sorted(r)) for r in faces[:, :3].tolist()}
    tri = tets[:, [0, 1, 2, 4, 5, 6]]                            # face (0, 1, 2) of every tet with its mid-nodes
    interior = next(r for r in tri if tuple(sorted(r[:3].tolist())) not in on_boundary)
    with pytest.raises(ValueError, match="not a boundary face"):
        solve(FeaProblem(nodes, tets, MAT, interior[None, :], [case], n_modes=0))
    # a free part has no static solution
    with pytest.raises(ValueError):
        solve(FeaProblem(nodes, tets, MAT, np.zeros((0, 6), np.int64), [case], n_modes=0))
