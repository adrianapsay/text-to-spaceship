"""V2 launch environments (t2s.gd.environment) and the bracket material table (t2s.gd.materials).

* Every preset spectrum integrates to its published overall level (GSFC-STD-7000B Tables 2.4-3 / 2.4-4: 14.1, 10.0
  and 6.8 Grms; SpaceX Rideshare v11 Table 4-6: 5.57 Grms; NanoRacks NR-NRCSD-S0003 Table 4.3.2.1-1: 9.47 Grms) within
  1 %: a wrong breakpoint would not.
* GEVS qualification = acceptance + 3 dB (Table 2.2-2) and envelopes the workmanship level; the envelope is exact.
* MAC: the table points and log-log interpolation between them.
* LSP note 3: the SpaceX qualification random level does not cover its shock SRS.
* One material table for FEA, mass and cost: densities agree, every entry is sourced, the domain uses it.
"""
import math

import numpy as np
import pytest

from t2s.gd import environment as env
from t2s.gd import materials


@pytest.mark.parametrize("spec, grms", [(env.GEVS_QUALIFICATION, 14.1), (env.GEVS_ACCEPTANCE, 10.0),
                                        (env.GEVS_WORKMANSHIP, 6.8), (env.SPACEX_MPE, 5.57),
                                        (env.NANORACKS_HARD_MOUNT, 9.47)])
def test_preset_spectra_integrate_to_their_published_grms(spec, grms):
    assert spec.grms_published == grms
    assert spec.grms() == pytest.approx(grms, rel=0.01)
    # the exact power-law integral against a fine numerical one
    f = np.geomspace(*spec.band, 200001)
    num = math.sqrt(np.trapezoid(spec.asd(f), f))
    assert spec.grms() == pytest.approx(num, rel=1e-6)


def test_spectra_are_zero_outside_their_band():
    s = env.GEVS_ACCEPTANCE
    assert s.asd(19.99) == 0.0 and s.asd(2000.01) == 0.0 and s.asd(20.0) == pytest.approx(0.013)
    assert s.asd(100.0) == pytest.approx(0.08) and s.asd(2000.0) == pytest.approx(0.013)
    # the old curve continued at −6 dB/oct above 2 kHz (unconservative for stiff modes): gone
    from t2s.gd.domain import gevs_acceptance_asd
    assert gevs_acceptance_asd(4000.0) == 0.0 and gevs_acceptance_asd(400.0) == pytest.approx(0.08)


def test_gevs_qualification_is_acceptance_plus_3db_enveloped_with_workmanship():
    e = env.get("gevs")
    assert e is env.get(None) and env.DEFAULT == "gevs"
    plus3 = env.GEVS_ACCEPTANCE.scaled_db(3.0, "")
    f = np.geomspace(20, 2000, 2001)
    assert np.allclose(env.GEVS_QUALIFICATION.asd(f), plus3.asd(f), rtol=0.003)      # 0.026/0.16 vs ×1.995
    assert np.all(e.random_qual.asd(f) >= env.GEVS_WORKMANSHIP.asd(f) * (1 - 1e-12))
    assert np.all(e.random_qual.asd(f) >= env.GEVS_QUALIFICATION.asd(f) * (1 - 1e-12))
    assert e.random_qual.grms() == pytest.approx(14.1, rel=0.01)
    assert e.random_limit is env.GEVS_ACCEPTANCE
    # an exact envelope where the spectra cross: a flat level against a sloped one
    a = env.Spectrum(((10.0, 1.0), (1000.0, 1.0)), "flat")
    b = env.Spectrum(((10.0, 0.1), (1000.0, 10.0)), "rising")              # crosses at 100 Hz
    ab = a.envelope(b, "env")
    assert any(abs(p[0] - 100.0) < 1e-9 for p in ab.points)
    g = np.geomspace(10, 1000, 999)
    assert np.allclose(ab.asd(g), np.maximum(a.asd(g), b.asd(g)), rtol=1e-12)


def test_other_presets_limit_and_qualification():
    sx, nr = env.get("spacex"), env.get("nanoracks")
    assert sx.random_qual.grms() == pytest.approx(5.57 * math.sqrt(2), rel=0.01)        # MPE + 3 dB
    assert nr.random_qual is env.NANORACKS_HARD_MOUNT
    assert nr.random_limit.grms() == pytest.approx(9.47 / math.sqrt(2), rel=0.01)      # profile − 3 dB
    assert sx.factors["random"].yield_ == 1.10 and sx.factors["random"].ult == 1.25
    g = env.get("gevs").factors
    assert (g["static"].yield_, g["static"].ult, g["random"].yield_, g["random"].ult) == (1.25, 1.4, 1.6, 1.8)
    assert env.get("gevs_analysis").factors["static"].yield_ == 2.0 and env.get("gevs_analysis").response_id == "gevs"
    assert env.QUAL_FACTORS.yield_ == 1.0 and env.QUAL_FACTORS.ult == 1.25
    for e in env.ENVIRONMENTS.values():                                   # every value carries its source
        assert e.random_limit.source and e.random_qual.source and e.static_source and e.q_source and e.f1_source
        assert all(f.source for f in e.factors.values()) and e.qual_factors.source
        assert e.zeta == pytest.approx(0.05)


def test_mac_table_points_and_log_log_interpolation():
    assert env.mac_g(0.05) == env.mac_g(1.0) == 68.0
    assert env.mac_g(5.0) == pytest.approx(49.0) and env.mac_g(10.0) == pytest.approx(39.8)
    assert env.mac_g(math.sqrt(5.0)) == pytest.approx(math.sqrt(68.0 * 49.0), rel=1e-12)   # geometric mean
    assert env.mac_g(500.0) == 12.0
    assert env.get("nanoracks").static_g(0.3) == 68.0                     # the larger of MAC and its 7 g table
    assert env.get("spacex").static_g(0.3) == 68.0 and env.get("gevs").static_g(5.0) == pytest.approx(49.0)


def test_lsp_note_3_shock_coverage():
    ok, text = env.shock_covered_by_random(env.get("spacex"))
    assert ok is False and "NOT covered" in text
    ok, text = env.shock_covered_by_random(env.get("gevs"))
    assert ok is None
    # the random-equivalent SRS is Miles' 3σ at each frequency
    f = 300.0
    assert env.random_equivalent_srs(env.GEVS_QUALIFICATION, [f])[0] == pytest.approx(
        3 * math.sqrt(math.pi / 2 * f * 10 * 0.16))


def test_material_table_is_one_source_for_fea_mass_and_cost():
    from t2s.gd.domain import MATERIAL, box_part_domain
    for k, m in materials.MATERIALS.items():
        assert m["id"] == k and m["source"] and 0 < m["yield_mpa"] < m["ultimate_mpa"]
        assert materials.density_kg_m3(k) == pytest.approx(m["rho_t_mm3"] * 1e12)
        assert materials.fea_material(k)["rho_t_mm3"] == m["rho_t_mm3"]
    assert materials.density_kg_m3("AlSi10Mg") == pytest.approx(2680.0)          # was 2670 for the mass
    assert materials.density_kg_m3("Ti-6Al-4V") == pytest.approx(4410.0)
    assert materials.density_kg_m3("6061-T6") == pytest.approx(2710.0)
    assert MATERIAL == materials.fea_material("AlSi10Mg")
    assert materials.for_kind("metal_am", "Ti-6Al-4V") == "Ti-6Al-4V"
    assert materials.for_kind("cradle", "Ti-6Al-4V") == materials.for_kind("clamp") == "6061-T6"
    with pytest.raises(ValueError):
        materials.for_kind("metal_am", "6061-T6")
    with pytest.raises(KeyError):
        materials.material("unobtainium")
    dom = box_part_domain(h=2.0)
    assert dom.material["id"] == "AlSi10Mg"
    # the designed solid's mass uses the FE density: a 10 mm cube
    from t2s.gd.design import solid_props
    from t2s.mfg.brackets import box_mesh
    v, f = box_mesh(np.zeros(3), np.full(3, 10.0))
    for k in materials.MATERIALS:
        m, _, _, vol = solid_props(v, f, k)
        assert vol == pytest.approx(1000.0) and m == pytest.approx(materials.MATERIALS[k]["rho_t_mm3"] * 1e3 * 1000.0)
