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


@pytest.mark.skipif(not ccx.available(), reason="CalculiX not installed (tools/ccx)")
def test_baseline_bracket_is_checked_by_both_solvers(dom):
    ev = evaluate(dom, bs.generate(dom))
    assert ev.ok, ev.reason
    assert set(ev.solvers) == {"ccx", "ngs"}
    for s in ev.solvers.values():
        assert all(c["balance"] < 1e-6 for c in s["cases"])                   # reactions balance the loads
    assert ev.agreement["sigma_rel"] < 0.01 and ev.agreement["f1_rel"] < 0.01
    assert ev.mass_g > 0 and ev.f1_hz > 0
    assert ev.ms_yield == pytest.approx(170.0 / (1.25 * ev.sigma_mpa) - 1.0)
    # the machined block is heavier and stiffer than the shell bracket
    blk = evaluate(dom, bs.machined_block(dom))
    assert blk.mass_g > ev.mass_g and blk.f1_hz > ev.f1_hz
