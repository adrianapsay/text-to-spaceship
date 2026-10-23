"""V2 generative design: the shared problem and evaluation pipeline (density → solid in the reserved box → two FEA
solvers → margins), on the self-contained flat-box domain at 2 mm voxels."""
import numpy as np
import pytest

from t2s.fea import ccx
from t2s.gd.domain import G0, LIMIT_G, box_part_domain
from t2s.gd.entrants import baseline_shell as bs
from t2s.gd.evaluate import evaluate, solid_from_density


@pytest.fixture(scope="module")
def dom():
    return box_part_domain(h=2.0)


def test_domain_layers(dom):
    assert dom.fixed.any() and dom.contact.any() and dom.void.any()
    assert not (dom.fixed & dom.void).any() and not (dom.contact & dom.void).any() and not (dom.fixed & dom.contact).any()
    # the bolted layer is the first layer along the axis, the void (the part) the last
    assert dom.fixed[0].all() and not dom.fixed[1:].any()
    assert dom.void[-1].all()
    lc = dom.load_cases()
    assert len(lc) == 3
    for c in lc:
        assert np.linalg.norm(c["contact_force_n"]) == pytest.approx(dom.part_mass_kg * LIMIT_G * G0 * 1e-3)


def test_solid_is_inside_the_box_and_disconnected_designs_fail(dom):
    g = bs.generate(dom)
    (v, f), why = solid_from_density(dom, g.density)
    assert why == ""
    r = dom.reserve
    assert np.all(v >= r[:3] - 1e-5) and np.all(v <= r[3:] + 1e-5)
    assert np.isclose(v[:, 0].min(), dom.plane_mm, atol=1e-5)          # the bolted face is exactly on the plane
    empty = np.zeros(dom.shape)                                            # only the passive layers: no link
    sol, why = solid_from_density(dom, empty)
    assert sol is None and "no solid path" in why


def test_rayleigh_frequency_of_a_cantilever_with_a_tip_mass():
    """Rayleigh's quotient on the static deflection under inertia load (beam self-weight + a rigid tip mass acting at
    the tip-face centroid) against the exact Euler–Bernoulli frequency equation with a tip mass."""
    import math
    from types import SimpleNamespace

    from scipy.optimize import brentq

    from t2s.fea import ngs
    from t2s.fea.mesh import boundary_faces, face_set_moments, mesh_box
    from t2s.fea.problem import FeaProblem, LoadCase, Material, SurfaceLoad
    from t2s.gd.evaluate import rayleigh_frequency
    E, nu, rho, L, B, H = 70000.0, 0.33, 2.7e-9, 200.0, 10.0, 6.0
    nodes, tets = mesh_box([0, 0, 0], [L, B, H], h=2.5)
    faces = boundary_faces(tets)
    p = nodes[faces[:, :3]]
    fixed = faces[np.all(np.abs(p[:, :, 0]) < 1e-9, axis=1)]
    tip = faces[np.all(np.abs(p[:, :, 0] - L) < 1e-9, axis=1)]
    m_beam = rho * L * B * H                                       # t
    M = 1.0 * m_beam
    _, c, _ = face_set_moments(nodes, tip)
    acc = np.array([0.0, 0.0, -9806.65 * 10])
    prob = FeaProblem(nodes, tets, Material("Al", E, nu, rho), fixed,
                      [LoadCase("z", [SurfaceLoad(tip, M * acc)], acc)], n_modes=0)
    prob.load_faces = tip
    _, fields = ngs.solve_with_fields(prob, threads=2)
    dom = SimpleNamespace(material={"rho_t_mm3": rho}, part_com=c, part_mass_kg=M * 1e3,
                          part_inertia_kgm2=np.zeros((3, 3)))
    f, u_p = rayleigh_frequency(dom, prob, np.asarray(fields.displacement[0]), acc)
    I, A = B * H ** 3 / 12, B * H
    r = M / m_beam
    x = brentq(lambda b: 1 + math.cos(b) * math.cosh(b) + r * b * (math.cos(b) * math.sinh(b) - math.sin(b) * math.cosh(b)),
               0.5, 1.8)
    f_ref = x ** 2 / (2 * math.pi) * math.sqrt(E * I / (rho * A * L ** 4))
    assert u_p[2] < 0
    assert f == pytest.approx(f_ref, rel=0.02)                    # upper bound, close for a dominant tip mass
    assert f >= 0.995 * f_ref


def test_ritz_modes_find_the_torsion_mode_of_a_bar_with_a_tip_inertia():
    """Rayleigh–Ritz on three translational and three torque deflections of a square cantilever bar carrying a rigid
    tip mass with a polar inertia: the twisting mode (no translational load excites it, so per-axis Rayleigh misses
    it) against k_t / (I + I_bar/3) with Saint-Venant's torsion constant 0.1406 a⁴, and the bending modes against
    the exact Euler–Bernoulli frequency with a tip mass."""
    import math
    from types import SimpleNamespace

    from scipy.optimize import brentq

    from t2s.fea import ngs
    from t2s.fea.mesh import boundary_faces, face_set_moments, mesh_box
    from t2s.fea.problem import FeaProblem, LoadCase, Material, SurfaceLoad
    from t2s.gd.evaluate import rayleigh_frequency, ritz_modes
    E, nu, rho, L, a = 70000.0, 0.33, 2.7e-9, 200.0, 10.0
    nodes, tets = mesh_box([0, 0, 0], [L, a, a], h=2.5)
    faces = boundary_faces(tets)
    p = nodes[faces[:, :3]]
    fixed = faces[np.all(np.abs(p[:, :, 0]) < 1e-9, axis=1)]
    tip = faces[np.all(np.abs(p[:, :, 0] - L) < 1e-9, axis=1)]
    _, c, _ = face_set_moments(nodes, tip)
    m_bar, M, I_x = rho * L * a * a, 5e-5, 0.1                     # t, t, t·mm²
    cases = []
    for k in range(3):
        acc = -9806.65 * 68 * np.eye(3)[k]
        cases.append(LoadCase(f"68 g {k}", [SurfaceLoad(tip, M * acc)], acc))
    for k in range(3):
        cases.append(LoadCase(f"torque {k}", [SurfaceLoad(tip, np.zeros(3), 1000.0 * np.eye(3)[k])], np.zeros(3)))
    prob = FeaProblem(nodes, tets, Material("Al", E, nu, rho), fixed, cases, n_modes=0)
    prob.load_faces = tip
    _, fields = ngs.solve_with_fields(prob, threads=2)
    dom = SimpleNamespace(material={"rho_t_mm3": rho}, part_com=c, part_mass_kg=M * 1e3,
                          part_inertia_kgm2=np.diag([I_x, 0.0, 0.0]) * 1e-3)
    modes = ritz_modes(dom, prob, fields.displacement)
    assert [m["f_hz"] for m in modes] == sorted(m["f_hz"] for m in modes)
    G = E / (2 * (1 + nu))
    f_tor = math.sqrt(G * 0.1406 * a ** 4 / L / (I_x + rho * L * a ** 4 / 6 / 3)) / (2 * math.pi)
    tor = [m for m in modes if m["motion"] == "part rotates about x"]
    assert len(tor) == 1 and max(tor[0]["eff_mass_frac"]) < 1e-6        # a pure twist: no base-excitation mass
    assert tor[0]["f_hz"] == pytest.approx(f_tor, rel=0.01)
    # bending: the y and z modes match Euler–Bernoulli with a tip mass and are no higher than per-axis Rayleigh
    r = M / m_bar
    x = brentq(lambda b: 1 + math.cos(b) * math.cosh(b) + r * b * (math.cos(b) * math.sinh(b) - math.sin(b) * math.cosh(b)),
               0.5, 1.8)
    f_ref = x ** 2 / (2 * math.pi) * math.sqrt(E * a ** 4 / 12 / (rho * a * a * L ** 4))
    # the square bar's y and z bending modes are degenerate: any pair of orthogonal directions is a solution, so the
    # pair is checked together — effective mass (Γ²/gen. mass of the static shape: 0.76 here) and frequency
    bend = [m for m in modes if abs(m["f_hz"] - modes[0]["f_hz"]) < 1e-4 * modes[0]["f_hz"]]
    assert len(bend) == 2 and all(m["motion"].startswith("part moves along") for m in bend)
    for k in (1, 2):
        assert sum(m["eff_mass_frac"][k] for m in bend) == pytest.approx(0.76, abs=0.01)
        f_r, _ = rayleigh_frequency(dom, prob, np.asarray(fields.displacement[k]), cases[k].body_accel_mm_s2)
        assert bend[0]["f_hz"] <= f_r * (1 + 1e-9)
    assert f_ref * 0.995 <= bend[0]["f_hz"] <= f_ref * 1.02
    assert modes[0]["f_hz"] < tor[0]["f_hz"]                                # the bar bends first here


def test_score_random_load_is_the_dominant_mode_or_the_srss_of_all_modes():
    """Axis y: one dominant mode (500 Hz, 80 %) and a small high one: Miles at the dominant mode governs. Axis x: the
    mass is split between 3000 Hz (50 %, dominant) and 800 Hz (49 %, the strongest Miles response of the spectrum):
    the SRSS of the modal base forces exceeds Miles at the dominant mode and governs. f1 is the lowest mode of any
    kind (here a twist at 250 Hz)."""
    import math

    from t2s.gd.domain import MATERIAL, miles_3sigma_g
    from t2s.gd.evaluate import score

    def mode(f, e, motion="part moves along x"):
        return {"f_hz": f, "eff_mass_frac": e, "motion": motion}
    modes = [mode(250, [0, 0, 0], "part rotates about x"), mode(800, [0.49, 0, 0]), mode(3000, [0.5, 0, 0]),
             mode(500, [0, 0.8, 0]), mode(2000, [0, 0.1, 0]), mode(700, [0, 0, 0.8])]
    cases = [{"name": f"68 g {a}", "voxel_vm_mpa": 20.0, "f_rayleigh_hz": 1000.0} for a in "xyz"]
    cases += [{"name": f"torque {a}", "voxel_vm_mpa": None} for a in "xyz"]
    s = score({"ngs": {"modes": modes, "cases": cases}, "retries": ["ignored"]}, MATERIAL)
    x, y = s["axes"][0], s["axes"][1]
    srss = math.hypot(0.5 * miles_3sigma_g(3000), 0.49 * miles_3sigma_g(800))
    assert x["f_hz"] == 3000 and x["random_dominant_g"] == pytest.approx(miles_3sigma_g(3000))
    assert srss > miles_3sigma_g(3000) and x["random_3sigma_g"] == pytest.approx(srss)
    assert y["f_hz"] == 500 and y["random_3sigma_g"] == pytest.approx(miles_3sigma_g(500))
    assert y["random_srss_g"] < y["random_3sigma_g"]
    assert s["f1_hz"] == 250 and s["modes"][0]["motion"] == "part rotates about x"
    assert len(s["axes"]) == 3 and s["passed"] and s["ms_yield"] == min(a["ms_yield"] for a in s["axes"])


@pytest.mark.skipif(not ccx.available(), reason="CalculiX not installed (tools/ccx)")
def test_baseline_bracket_is_checked_by_both_solvers(dom):
    ev = evaluate(dom, bs.generate(dom))
    assert ev.ok, ev.reason
    assert set(ev.solvers) == {"ccx", "ngs"}
    for s in ev.solvers.values():
        assert all(c["balance"] < 1e-6 for c in s["cases"])                   # reactions balance the loads
    assert ev.agreement["sigma_rel"] < 0.01 and ev.agreement["f1_rel"] < 0.01
    assert ev.mass_g > 0 and ev.f1_hz > 0
    # margins: per axis, the larger of the quasi-static (1.25 × 68 g) and random (1.6 × Miles 3σ) yield loads
    assert len(ev.axes) == 3 and all(a["yield_factor_g"] >= 1.25 * 68 - 1e-9 for a in ev.axes)
    assert ev.ms_yield == pytest.approx(min(170.0 / (a["sigma_68g_mpa"] * a["yield_factor_g"] / 68) - 1 for a in ev.axes))
    # f1 is the lowest Ritz mode of any kind; each axis takes the mode with the most effective mass along it
    assert ev.f1_hz == pytest.approx(ev.modes[0]["f_hz"]) and ev.f1_hz <= min(a["f_hz"] for a in ev.axes) + 1e-9
    assert len(ev.modes) == 6 and all(0.3 < a["eff_mass_frac"] <= 1.0 for a in ev.axes)
    assert all(abs(c["balance"]) < 1e-6 for s in ev.solvers.values() for c in s["cases"][3:])   # torque: no net force
    # the machined block is heavier and stiffer than the shell bracket
    blk = evaluate(dom, bs.machined_block(dom))
    assert blk.mass_g > ev.mass_g and blk.f1_hz > ev.f1_hz
