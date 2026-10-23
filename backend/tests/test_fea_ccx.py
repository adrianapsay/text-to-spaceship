"""V2 FEA, CalculiX solver (t2s.fea.ccx): analytical benchmarks and thread determinism.

Material E = 70000 MPa, nu = 0.33, rho = 2.7e-9 t/mm³; quadratic tets from t2s.fea.mesh (h = 2.5 mm).
a. cantilever 200 x 10 x 6 (x = 0 clamped), P = 100 N in -z on x = 200: Timoshenko tip deflection (1 %),
   mid-span top-fibre bending stress (2 %), first natural frequency (2 %), reaction = load (1e-6)
b. axial bar 100 x 10 x 10, F = 1000 N in +x on x = 100: mid-length sigma_xx = F/A and elongation F L/(E A) (1 %)
c. the cantilever under 10 g self-weight in -z: q L^4/(8 E I) + q L^2/(2 kappa G A) (2 %), reaction = m a (1e-6)
d. threads = 1 is bitwise repeatable (difference 0, so within 1e-9); threads = 1 vs threads = 2 agree to 1e-6 of
   max |u|, NOT 1e-9: multi-threaded stiffness assembly and SPOOLES factorisation sum in a different order, which
   moves displacements by about one unit in the 7th significant digit (the resolution of ccx's .dat output), see
   test_threads_change_displacements_only_in_the_last_digit.
e. added (non-structural) mass M smeared on the cantilever's tip face, M = 1x and 5x the beam mass: f1 within 2 % of
   the Euler-Bernoulli cantilever with a tip point mass (root of 1 + cos bL cosh bL + (M/mL) bL (cos bL sinh bL -
   sin bL cosh bL) = 0); static results and the structural mass are unchanged by the added mass.

"Mean" face displacements are work-conjugate averages: the displacement of the face weighted by the consistent nodal
loads of a uniform unit traction (= area average of the quadratic displacement field over the face).
"""
import numpy as np
import pytest

from t2s.fea import ccx
from t2s.fea.mesh import boundary_faces, consistent_surface_load, mesh_box
from t2s.fea.problem import FeaProblem, LoadCase, Material, SurfaceLoad

pytestmark = pytest.mark.skipif(
    not ccx.available(),
    reason=f"CalculiX not installed: {ccx.CCX_EXE} is missing (fetch the conda-forge files listed under 'ccx' "
           f"in tools/toolchain.lock.json into tools/ccx/)")

E, NU, RHO = 70000.0, 0.33, 2.7e-9
G = E / (2 * (1 + NU))
KAPPA = 5.0 / 6.0
MAT = Material("benchmark aluminium", E, NU, RHO)
H_MESH = 2.5
G0 = 9806.65                                   # mm/s²

L, B, H = 200.0, 10.0, 6.0                     # cantilever: x length, y width, z height
P = 100.0
A_BEAM, I_BEAM = B * H, B * H ** 3 / 12.0
ACCEL = 10.0 * G0


def faces_at(nodes, faces, axis, value, tol=1e-9):
    return faces[np.all(np.abs(nodes[faces[:, :3]][:, :, axis] - value) < tol, axis=1)]


def face_mean(nodes, faces, field):
    """Work-conjugate (area) average of a nodal field over 6-node faces."""
    w = consistent_surface_load(nodes, faces, [1.0, 0.0, 0.0])
    return sum(wt[0] * field[n] for n, wt in w.items())


def rel(measured, reference):
    return abs(measured - reference) / abs(reference)


def pct(measured, reference):
    return f"{100 * (measured - reference) / reference:+.3f} %"


@pytest.fixture(scope="module")
def cantilever():
    nodes, tets = mesh_box([0, 0, 0], [L, B, H], h=H_MESH)
    faces = boundary_faces(tets)
    fixed, tip = faces_at(nodes, faces, 0, 0.0), faces_at(nodes, faces, 0, L)
    cases = [LoadCase("tip_load", [SurfaceLoad(tip, np.array([0.0, 0.0, -P]))]),
             LoadCase("self_weight_10g", [], np.array([0.0, 0.0, -ACCEL]))]
    problem = FeaProblem(nodes, tets, MAT, fixed, cases, n_modes=1, label="cantilever benchmark")
    result, fields = ccx.run(problem, threads=2)
    print(f"\ncantilever: {len(nodes)} nodes, {len(tets)} elements, ccx solve {result.seconds:.2f} s")
    return problem, tip, result, fields


def test_cantilever_tip_deflection(cantilever):
    problem, tip, result, fields = cantilever
    w = -face_mean(problem.nodes, tip, fields.displacement[0][:, 2])
    ref = P * L ** 3 / (3 * E * I_BEAM) + P * L / (KAPPA * G * A_BEAM)
    print(f"\ntip deflection {w:.6f} mm vs {ref:.6f} mm (error {pct(w, ref)})")
    assert rel(w, ref) < 0.01
    assert result.cases[0].max_disp_mm >= w


def test_cantilever_bending_stress(cantilever):
    problem, _, _, fields = cantilever
    x, z = problem.nodes[:, 0], problem.nodes[:, 2]
    sel = (np.abs(z - H) < 1e-9) & (np.abs(x - L / 2) <= 1.5)          # top fibre, mid-span band
    assert sel.sum() >= 5
    sxx = float(fields.stress[0][sel, 0].mean())
    ref = 6 * P * (L / 2) / (B * H ** 2)
    print(f"\nmid-span top-fibre sigma_xx {sxx:.4f} MPa over {sel.sum()} nodes (mean x {x[sel].mean():.3f}) "
          f"vs {ref:.4f} MPa (error {pct(sxx, ref)})")
    assert rel(sxx, ref) < 0.02


def test_cantilever_first_frequency(cantilever):
    _, _, result, _ = cantilever
    f1 = result.frequencies_hz[0]
    ref = 1.8751 ** 2 / (2 * np.pi) * np.sqrt(E * I_BEAM / (RHO * A_BEAM * L ** 4))
    print(f"\nfirst natural frequency {f1:.4f} Hz vs {ref:.4f} Hz (error {pct(f1, ref)})")
    assert rel(f1, ref) < 0.02


def test_cantilever_reaction_balances_load(cantilever):
    problem, _, result, _ = cantilever
    case = result.cases[0]
    assert np.allclose(case.applied_n, [0, 0, -P], rtol=0, atol=1e-12)
    err = np.linalg.norm(case.reaction_n + case.applied_n) / P
    print(f"\ntip-load reaction {case.reaction_n} N (relative imbalance {err:.2e})")
    assert err < 1e-6
    assert result.mass_t == pytest.approx(problem.mass_t(), rel=1e-6)
    assert result.solver == "CalculiX 2.23"
    assert (result.n_nodes, result.n_elements) == (len(problem.nodes), len(problem.tets))
    assert case.max_vm_filtered_mpa == case.max_vm_mpa            # nothing excluded


def test_self_weight_deflection_and_reaction(cantilever):
    problem, tip, result, fields = cantilever
    q = RHO * A_BEAM * ACCEL
    w = -face_mean(problem.nodes, tip, fields.displacement[1][:, 2])
    ref = q * L ** 4 / (8 * E * I_BEAM) + q * L ** 2 / (2 * KAPPA * G * A_BEAM)
    print(f"\nself-weight tip deflection {w:.6e} mm vs {ref:.6e} mm (error {pct(w, ref)})")
    assert rel(w, ref) < 0.02
    case = result.cases[1]
    ma = problem.mass_t() * ACCEL
    assert np.allclose(case.applied_n, [0, 0, -ma], rtol=1e-12, atol=0)
    err = np.linalg.norm(case.reaction_n - np.array([0, 0, ma])) / ma
    print(f"self-weight reaction {case.reaction_n} N vs m a = {ma:.7f} N (relative error {err:.2e})")
    assert err < 1e-6


def test_axial_bar():
    lx, s = 100.0, 10.0
    f = 1000.0
    nodes, tets = mesh_box([0, 0, 0], [lx, s, s], h=H_MESH)
    faces = boundary_faces(tets)
    end, root = faces_at(nodes, faces, 0, lx), faces_at(nodes, faces, 0, 0.0)
    problem = FeaProblem(nodes, tets, MAT, root,
                         [LoadCase("axial", [SurfaceLoad(end, np.array([f, 0.0, 0.0]))])], n_modes=0,
                         exclude_nodes=np.unique(root.ravel()), label="axial bar benchmark")
    result, fields = ccx.run(problem, threads=2)
    keep = np.ones(len(nodes), bool)
    keep[problem.exclude_nodes] = False
    assert result.cases[0].max_vm_filtered_mpa == pytest.approx(fields.von_mises[0][keep].max(), rel=1e-12)
    assert result.cases[0].max_vm_filtered_mpa < result.cases[0].max_vm_mpa      # the clamp edge peak is excluded
    area = s * s
    sel = np.abs(nodes[:, 0] - lx / 2) <= 1.5
    sxx = float(fields.stress[0][sel, 0].mean())
    du = face_mean(nodes, end, fields.displacement[0][:, 0])
    ref_s, ref_u = f / area, f * lx / (E * area)
    print(f"\naxial bar: {len(nodes)} nodes, {len(tets)} elements, {result.seconds:.2f} s\n"
          f"mid-length sigma_xx {sxx:.5f} MPa over {sel.sum()} nodes vs {ref_s:.5f} MPa (error {pct(sxx, ref_s)})\n"
          f"end elongation {du:.7f} mm vs {ref_u:.7f} mm (error {pct(du, ref_u)})")
    assert rel(sxx, ref_s) < 0.01
    assert rel(du, ref_u) < 0.01
    assert np.linalg.norm(result.cases[0].reaction_n + result.cases[0].applied_n) / f < 1e-6
    assert result.frequencies_hz == []


@pytest.fixture(scope="module")
def single_thread(cantilever):
    return ccx.run(cantilever[0], threads=1)


def test_single_thread_is_bitwise_repeatable(cantilever, single_thread):
    result_a, fields_a = single_thread
    result_b, fields_b = ccx.run(cantilever[0], threads=1)
    for k in range(len(fields_a.displacement)):
        diff = np.abs(fields_a.displacement[k] - fields_b.displacement[k]).max()
        print(f"\ncase {k}: max |u(1 thread, run 1) - u(1 thread, run 2)| = {diff:.3e} mm")
        assert diff <= 1e-9 * np.abs(fields_a.displacement[k]).max()
        assert np.array_equal(fields_a.stress[k], fields_b.stress[k])
    assert result_a.frequencies_hz == result_b.frequencies_hz


def test_threads_change_displacements_only_in_the_last_digit(cantilever, single_thread):
    problem, _, result2, fields2 = cantilever
    result1, fields1 = single_thread
    for k, case in enumerate(problem.load_cases):
        u1, u2 = fields1.displacement[k], fields2.displacement[k]
        scale = np.abs(u1).max()
        diff = np.abs(u1 - u2).max()
        print(f"\ncase {case.name}: max |u(1 thread) - u(2 threads)| = {diff:.3e} mm = {diff / scale:.2e} of "
              f"max |u| ({scale:.6e} mm); {(u1 != u2).sum()} of {u1.size} printed values differ")
        assert diff <= 1e-6 * scale
    assert np.allclose(result1.frequencies_hz, result2.frequencies_hz, rtol=1e-6, atol=0)


def tip_mass_frequency(mass_ratio: float) -> float:
    """First frequency (Hz) of the Euler-Bernoulli cantilever with a tip point mass M = mass_ratio * (rho A L)."""
    from scipy.optimize import brentq

    def char(bl):
        return (1 + np.cos(bl) * np.cosh(bl)
                + mass_ratio * bl * (np.cos(bl) * np.sinh(bl) - np.sin(bl) * np.cosh(bl)))

    bl = brentq(char, 1e-3, 1.8751040687, xtol=1e-14)        # first root lies below the no-mass root
    return bl ** 2 / (2 * np.pi * L ** 2) * np.sqrt(E * I_BEAM / (RHO * A_BEAM))


@pytest.mark.parametrize("mass_ratio", [1.0, 5.0])
def test_tip_added_mass_frequency(cantilever, single_thread, mass_ratio):
    problem, tip, _, _ = cantilever
    m_tip = mass_ratio * problem.mass_t()
    with_mass = FeaProblem(problem.nodes, problem.tets, MAT, problem.fixed_faces,
                           problem.load_cases if mass_ratio == 1.0 else [], n_modes=1,
                           added_masses=[(tip, m_tip)], label="cantilever with tip mass")
    result, fields = ccx.run(with_mass, threads=1)
    f1, ref = result.frequencies_hz[0], tip_mass_frequency(mass_ratio)
    print(f"\ntip mass {mass_ratio:g} x beam mass ({m_tip:.6e} t): f1 {f1:.4f} Hz vs {ref:.4f} Hz "
          f"(error {pct(f1, ref)}); ccx {result.seconds:.2f} s")
    assert rel(f1, ref) < 0.02
    assert result.mass_t == pytest.approx(problem.mass_t(), rel=1e-6)          # structural mass only
    assert any("added non-structural mass" in n for n in result.notes)
    assert with_mass.added_mass_t() == pytest.approx(m_tip, rel=1e-12)
    if with_mass.load_cases:                                                   # statics unchanged by the mass
        base_result, base = single_thread
        for k, case in enumerate(with_mass.load_cases):
            du = np.abs(fields.displacement[k] - base.displacement[k]).max()
            ds = np.abs(fields.stress[k] - base.stress[k]).max()
            dr = np.abs(result.cases[k].reaction_n - base_result.cases[k].reaction_n).max()
            print(f"case {case.name}: max |du| {du:.3e} mm, max |dsigma| {ds:.3e} MPa, max |dR| {dr:.3e} N "
                  f"(with vs without added mass, 1 thread each)")
            assert du <= 1e-9 * np.abs(base.displacement[k]).max()
            assert ds <= 1e-9 * np.abs(base.stress[k]).max()
            assert np.allclose(result.cases[k].applied_n, base_result.cases[k].applied_n, rtol=1e-12, atol=0)
            assert np.linalg.norm(result.cases[k].reaction_n + result.cases[k].applied_n) \
                <= 1e-6 * np.linalg.norm(result.cases[k].applied_n)
