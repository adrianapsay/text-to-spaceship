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


def test_contact_voxels_no_solid_can_reach_are_dropped(dom):
    """A pocket that the part (void) cuts off from the bolted layer: its contact voxels are dropped — they carry no
    load, and with them every design, the solid block included, would be refused — while reachable ones stay."""
    import copy

    from t2s.gd.domain import drop_unreachable_contact
    d = copy.copy(dom)
    d.void, d.contact, d.fixed = dom.void.copy(), dom.contact.copy(), dom.fixed.copy()
    nx = d.shape[0]
    wall = nx // 2
    d.void[wall] = True                                    # the part closes the box across the middle …
    d.contact[wall + 1] = True                             # … with contact voxels behind it (a pocket)
    d.contact[wall + 1] &= ~d.void[wall + 1]
    d.contact[wall - 1] = ~d.void[wall - 1]                # and some in front of it
    behind, front = int(d.contact[wall + 1:].sum()), int(d.contact[:wall].sum())
    assert behind > 0 and front > 0
    assert drop_unreachable_contact(d) == behind
    assert not d.contact[wall + 1:].any() and int(d.contact[:wall].sum()) == front
    assert drop_unreachable_contact(dom) == 0              # the plain test domain has no pocket


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


@pytest.fixture(scope="module")
def bar():
    """Square cantilever bar 200 × 10 × 10 mm (AlSi-like) with a rigid tip mass of 50 g and a polar inertia, solved
    once by NGSolve for the six trial cases (68 g x, y, z; torques x, y, z) and a seventh, nearly dependent one
    (the 68 g y case plus a small force at mid-span, test_ritz_cutoff_…)."""
    from types import SimpleNamespace

    from t2s.fea import ngs
    from t2s.fea.mesh import boundary_faces, face_set_moments, mesh_box
    from t2s.fea.problem import FeaProblem, LoadCase, Material, SurfaceLoad
    E, nu, rho, L, a = 70000.0, 0.33, 2.7e-9, 200.0, 10.0
    nodes, tets = mesh_box([0, 0, 0], [L, a, a], h=2.5)
    faces = boundary_faces(tets)
    p = nodes[faces[:, :3]]
    fixed = faces[np.all(np.abs(p[:, :, 0]) < 1e-9, axis=1)]
    tip = faces[np.all(np.abs(p[:, :, 0] - L) < 1e-9, axis=1)]
    mid = faces[np.all(np.abs(p[:, :, 2] - a) < 1e-9, axis=1) & np.all(np.abs(p[:, :, 0] - L / 2) < 10.0, axis=1)]
    _, c, _ = face_set_moments(nodes, tip)
    M, I_x = 5e-5, 0.1                                                  # t, t·mm²
    cases = []
    for k in range(3):
        acc = -G0 * 68 * np.eye(3)[k]
        cases.append(LoadCase(f"68 g {k}", [SurfaceLoad(tip, M * acc)], acc))
    for k in range(3):
        cases.append(LoadCase(f"torque {k}", [SurfaceLoad(tip, np.zeros(3), 1000.0 * np.eye(3)[k])], np.zeros(3)))
    cases.append(LoadCase("near-dependent", [SurfaceLoad(tip, cases[1].surface_loads[0].total_force_n),
                                             SurfaceLoad(mid, np.array([0.0, 0.6, 0.0]))], cases[1].body_accel_mm_s2))
    prob = FeaProblem(nodes, tets, Material("Al", E, nu, rho), fixed, cases, n_modes=0)
    prob.load_faces = tip
    _, fields = ngs.solve_with_fields(prob, threads=2)
    dom = SimpleNamespace(material={"rho_t_mm3": rho}, part_com=c, part_mass_kg=M * 1e3,
                          part_inertia_kgm2=np.diag([I_x, 0.0, 0.0]) * 1e-3)
    return dom, prob, fields


def test_static_limit_of_the_modal_sum_is_the_1g_field(bar):
    """Σ_k S⁽ᵏ⁾ Γ_kj / ω_k² (the modal response to a steady 1 g base acceleration along j) reproduces the static 1 g
    stress field of the load case along j: the inertia shapes are trial vectors and L = Φᵀ M r is the work of the
    solvers' own load vectors (consistent body load + the part's RBE3 load), so the identity is exact."""
    from t2s.gd.evaluate import ritz
    from t2s.gd.vibration import voigt
    dom, prob, fields = bar
    rz = ritz(dom, prob, fields.displacement[:6])
    S = np.stack([voigt(s) for s in fields.stress[:6]], axis=-1)          # (n, 6, trial)
    Sm = S @ rz.C                                                         # modal stress per unit modal coordinate
    for j in range(3):
        static = -(Sm * (rz.gamma[:, j] / rz.omega ** 2)[None, None, :]).sum(-1) * G0   # q_k = −Γ a / ω²
        ref = S[:, :, j] / 68.0
        assert np.abs(static - ref).max() < 1e-4 * np.abs(ref).max(), j


def test_root_rms_stress_matches_the_one_mode_formula(bar):
    """On a flat 0.04 g²/Hz spectrum the RMS von Mises near the root of the cantilever (CQC over all six Ritz modes,
    Segalman) is within 3 % of the one-mode estimate σ(1 g) × Miles √(π/2 f₁ Q W): the tip mass makes the first
    bending mode carry nearly all of the static root stress."""
    import math

    from t2s.gd import environment as env
    from t2s.gd.evaluate import ritz
    from t2s.gd.vibration import modal_covariance, vm_rms, voigt, von_mises_voigt
    dom, prob, fields = bar
    rz = ritz(dom, prob, fields.displacement[:6])
    S = np.stack([voigt(s) for s in fields.stress[:6]], axis=-1)
    x = prob.nodes[:, 0]
    near = np.flatnonzero((x > 8.0) & (x < 12.0))
    s1g = von_mises_voigt(S[near, :, 2] / 68.0)
    n = near[int(np.argmax(s1g))]
    spec = env.Spectrum(((0.5, 0.04), (50000.0, 0.04)), "flat")
    I = modal_covariance(rz.f_hz, rz.gamma[:, 2], spec, 0.05)
    rms = vm_rms((S @ rz.C)[[n]], I)[0]
    f1 = rz.f_hz[int(np.argmax(rz.gamma[:, 2] ** 2))]
    one = s1g.max() * math.sqrt(math.pi / 2 * f1 * 10.0 * 0.04)
    assert rms == pytest.approx(one, rel=0.03), (rms, one, f1)


def test_ritz_cutoff_is_scale_free_and_above_the_noise_floor(bar):
    """The dependent-shape cutoff acts on M-normalised trial shapes. A seventh shape that is the 68 g y case plus a
    small mid-span force is nearly dependent (normalised Gram eigenvalue ≈ 2e-10) yet carries a genuine second
    bending mode (≈ 970 Hz, which the six standard shapes put at ≈ 1206 Hz). Rounding every displacement to
    CalculiX's 7 significant digits changes the 7-shape modes by < 1e-4, so the 1e-10 cutoff keeps a direction that
    is still accurate; the planned 1e-8 would drop that mode. Scaling one trial shape by 1e6 changes nothing."""
    import copy

    from t2s.fea.problem import LoadCase, SurfaceLoad
    from t2s.gd.evaluate import RITZ_CUTOFF, _mass_products, ritz
    dom, prob, fields = bar
    U = [np.asarray(u, float) for u in fields.displacement]
    Mg, _, _ = _mass_products(dom, prob, U)
    d = 1 / np.sqrt(np.diag(Mg))
    s = np.linalg.eigvalsh(d[:, None] * Mg * d[None, :])
    assert 1e-10 < s.min() / s.max() < 1e-8
    exact = ritz(dom, prob, U)
    rounded = ritz(dom, prob, [np.vectorize(lambda v: float(f"{v:.6e}"))(u) for u in U])
    assert RITZ_CUTOFF == 1e-10 and exact.kept == rounded.kept == 7
    assert np.allclose(exact.f_hz, rounded.f_hz, rtol=1e-4)
    six = ritz(dom, prob, U[:6])
    second_bending = exact.f_hz[3]
    assert 0.75 * six.f_hz[3] < second_bending < 0.85 * six.f_hz[3]          # 970 vs 1206 Hz
    planned = ritz(dom, prob, U, cutoff=1e-8)
    assert planned.kept == 6 and not np.any(np.isclose(planned.f_hz, second_bending, rtol=1e-3))
    # scale-free: the third trial shape × 1e6 (its load case too) gives the same modes
    k, sc = 2, 1e6
    p2 = copy.copy(prob)
    c = prob.load_cases[k]
    p2.load_cases = list(prob.load_cases)
    p2.load_cases[k] = LoadCase(c.name, [SurfaceLoad(sl.faces, sl.total_force_n * sc) for sl in c.surface_loads],
                                c.body_accel_mm_s2 * sc)
    U2 = list(U[:6])
    U2[k] = U2[k] * sc
    assert np.allclose(ritz(dom, p2, U2).f_hz, six.f_hz, rtol=1e-9)


def _synthetic_solvers(sig68=20.0, rl=(10.0, 30.0, 5.0), rq=(14.0, 42.0, 7.0), eff=0.95, f1=250.0):
    """A saved-evaluation dict (Evaluation.solvers) with given voxel stresses: 68 g cases and, for every preset, the
    random 3σ at the limit (rl) and qualification (rq) levels per axis, no sine / shock / bolts."""
    from t2s.gd import environment as env
    modes = [{"f_hz": f1, "eff_mass_frac": [0, 0, 0], "motion": "part rotates about x"},
             {"f_hz": 600.0, "eff_mass_frac": [0.9, 0.9, 0.9], "motion": "part moves along y"}]
    cases = [{"name": f"68 g {a}", "voxel_vm_mpa": sig68, "f_rayleigh_hz": 650.0} for a in "xyz"]
    cases += [{"name": f"torque {a}", "voxel_vm_mpa": None} for a in "xyz"]
    presets = {}
    for e in env.ENVIRONMENTS.values():
        axes = []
        for k in range(3):
            ax = {"random": {"limit": {"sigma3_mpa": rl[k], "accel3_g": 30.0},
                             "qual": {"sigma3_mpa": rq[k], "accel3_g": 42.0}},
                  "dominant_f_hz": 600.0, "dominant_eff_mass_frac": 0.9, "miles_g": 50.0, "miles_qual_g": 70.0}
            if e.sine is not None:
                ax["sine"] = {"sigma_peak_mpa": 1.0}
            if e.shock is not None:
                ax["shock"] = {"limit": {"sigma_peak_mpa": 200.0}, "qual": {"sigma_peak_mpa": 400.0}}
            axes.append(ax)
        presets[e.id] = {"axes": axes}
    dyn = {"part_mass_kg": 0.3, "n_modes": 2, "trial_kept": 6, "eff_mass_sum": [eff, eff, 0.99], "presets": presets}
    return {"ngs": {"modes": modes, "cases": cases, "dynamics": dyn}, "retries": ["ignored"]}


def test_score_applies_the_design_policy_without_double_counting():
    """GEVS: (a) the limit level × 1.6 / 1.8 and (b) the qualification level × 1.0 / 1.25 are separate checks, the
    68 g quasi-static × 1.25 / 1.4 another one — never added. With the random qualification stress √2 × the limit
    one, (a) governs yield (1.6 > √2) and ultimate (1.8 > 1.25 √2); SpaceX's 1.10 / 1.25 makes (b) govern. The
    shock ESTIMATE is reported, not gating; flags for the mass share and the missing sine / shock analyses."""
    import math

    from t2s.gd.domain import MATERIAL
    from t2s.gd.evaluate import score
    sv = _synthetic_solvers(sig68=20.0, rl=(10.0, 60.0, 5.0), rq=(10 * math.sqrt(2), 60 * math.sqrt(2), 5 * math.sqrt(2)),
                            eff=0.85)
    s = score(sv, MATERIAL)
    assert s["environment"] == "gevs" and s["f1_hz"] == 250.0
    y = {r["case"]: r for r in s["checks"] if r["axis"] == "y"}
    assert y["static"]["sigma_mpa"] == pytest.approx(20.0)                    # 68 g at 0.3 kg: the reference level
    assert y["static"]["ms_yield"] == pytest.approx(170 / (1.25 * 20) - 1)
    assert y["random limit"]["ms_yield"] == pytest.approx(170 / (1.6 * 60) - 1)
    assert y["random qualification"]["ms_yield"] == pytest.approx(170 / (60 * math.sqrt(2)) - 1)
    assert y["random qualification"]["ms_ult"] == pytest.approx(280 / (1.25 * 60 * math.sqrt(2)) - 1)
    assert s["ms_yield"] == pytest.approx(170 / (1.6 * 60) - 1)               # (a) governs, not the sum of cases
    assert s["governing"]["case"] == "random limit" and s["governing"]["axis"] == "y"
    assert s["governing"]["check"] == "yield" and s["passed"]
    assert s["axes"][1]["yield_factor_g"] == pytest.approx(68 * 1.6 * 60 / 20)
    assert s["margins"]["random limit"]["axis"] == "y"
    codes = [f["code"] for f in s["flags"]]
    assert codes.count("effective_mass") == 2 and "shock" in codes and "fatigue" in codes and "sine" not in codes
    sx = score(sv, MATERIAL, "spacex")
    assert sx["governing"]["case"] == "random qualification"                  # 1.10 / 1.25 < √2
    shock = [r for r in sx["checks"] if r["case"].startswith("shock")]
    assert shock and not any(r["gates"] for r in shock) and sx["passed"]      # 200 MPa shock: reported only
    assert any(f["code"] == "shock_estimate" for f in sx["flags"])
    an = score(sv, MATERIAL, "gevs_analysis")                                 # no-test factors 2.0 / 2.6 on static
    assert next(r for r in an["checks"] if r["case"] == "static")["factor_yield"] == 2.0
    low = score(_synthetic_solvers(f1=90.0), MATERIAL)
    assert not low["passed"] and "f1 90 Hz < 100" in low["reason"]
    assert any(f["code"] == "sine" for f in low["flags"])                     # f1 < 1.5 × 100 Hz
    with pytest.raises(ValueError):                                           # an old record: evaluate again
        score({"ngs": {"modes": sv["ngs"]["modes"], "cases": sv["ngs"]["cases"]}}, MATERIAL)


@pytest.mark.skipif(not ccx.available(), reason="CalculiX not installed (tools/ccx)")
def test_baseline_bracket_is_checked_by_both_solvers(dom):
    ev = evaluate(dom, bs.generate(dom))
    assert ev.ok, ev.reason
    assert set(ev.solvers) == {"ccx", "ngs"}
    for s in ev.solvers.values():
        assert all(c["balance"] < 1e-6 for c in s["cases"])                   # reactions balance the loads
    assert ev.agreement["sigma_rel"] < 0.01 and ev.agreement["f1_rel"] < 0.01 and ev.agreement["random_rel"] < 0.01
    assert ev.mass_g > 0 and ev.f1_hz > 0
    # margins: per axis the governing check's equivalent load (static 1.25 × 68 g at least)
    assert len(ev.axes) == 3 and all(a["yield_factor_g"] >= 1.25 * 68 - 1e-9 for a in ev.axes)
    assert ev.ms_yield == pytest.approx(min(170.0 / (a["sigma_68g_mpa"] * a["yield_factor_g"] / 68) - 1 for a in ev.axes))
    assert ev.environment == "gevs" and ev.material == "AlSi10Mg" and ev.governing["ms"] <= ev.ms_yield
    # f1 is the lowest Ritz mode of any kind; each axis takes the mode with the most effective mass along it
    assert ev.f1_hz == pytest.approx(ev.modes[0]["f_hz"]) and ev.f1_hz <= min(a["f_hz"] for a in ev.axes) + 1e-9
    assert len(ev.modes) == 6 and all(0.3 < a["eff_mass_frac"] <= 1.0 for a in ev.axes)
    assert all(0.9 < a["eff_mass_sum"] <= 1.0 for a in ev.axes)
    assert all(abs(c["balance"]) < 1e-6 for s in ev.solvers.values() for c in s["cases"][3:])   # torque: no net force
    # random: the GEVS qualification ASD is exactly 2 × the acceptance one (0.16 / 0.08, 0.026 / 0.013), so the CQC
    # 3σ stress is √2 × the limit one (the workmanship envelope adds nothing below 22.7 kg)
    for a in ev.axes:
        assert a["sigma3_qual_mpa"] / a["sigma3_limit_mpa"] == pytest.approx(np.sqrt(2.0), rel=1e-4)
    # bolt reactions balance the loads in both solvers: Σ over bolts = 68 g × (part + bracket) along the axis
    m = (dom.part_mass_kg + ev.mass_g / 1000.0) * 1e-3
    for s in ev.solvers.values():
        b = s["dynamics"]["bolts"]
        assert len(b["positions_mm"]) == 3 and sum(b["nodes_per_bolt"]) > 0
        for k in range(3):
            tot = np.sum(b["static_68g_n"][k], axis=0)
            assert np.allclose(tot, 68 * G0 * m * np.eye(3)[k], atol=1e-6 * 68 * G0 * m)
    assert ev.ms_bolt is not None and any(r["case"] == "random qualification" for r in ev.bolt_checks)
    # the machined block is heavier and stiffer than the shell bracket
    blk = evaluate(dom, bs.machined_block(dom))
    assert blk.mass_g > ev.mass_g and blk.f1_hz > ev.f1_hz
    # the same solid in Ti-6Al-4V: heavier by the density ratio, stiffer, its own allowables
    import copy

    from t2s.gd.materials import fea_material
    ti = copy.copy(dom)
    ti.material = fea_material("Ti-6Al-4V")
    et = evaluate(ti, bs.generate(ti))
    assert et.material == "Ti-6Al-4V" and et.mass_g == pytest.approx(ev.mass_g * 4.41 / 2.68, rel=1e-9)
    assert et.f1_hz > ev.f1_hz and et.ms_yield > ev.ms_yield
