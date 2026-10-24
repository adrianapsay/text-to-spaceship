"""V2 bracket bolts (t2s.gd.bolts): the pattern on the bolted face, the passive bosses, per-bolt loads and the
bolt / flange capacities (M3 A2-70 from the research note, fitting factor 1.15)."""
import math

import numpy as np
import pytest

from t2s.gd import bolts
from t2s.gd.domain import box_part_domain


def test_pattern_inset_from_the_corners():
    lo, hi = np.array([0.0, 0.0]), np.array([40.0, 20.0])
    e = bolts.BOLT_EDGE
    four = bolts.pattern_2d(lo, hi, 4)
    assert {tuple(p) for p in four} == {(e, e), (e, 20 - e), (40 - e, e), (40 - e, 20 - e)}
    three = bolts.pattern_2d(lo, hi, 3)                       # two at one end of the long side, one at the other
    assert sorted(map(tuple, three)) == [(e, e), (e, 20 - e), (40 - e, 10.0)]
    two = bolts.pattern_2d(lo, hi, 2)
    assert {tuple(p) for p in two} == {(e, e), (40 - e, 20 - e)}
    assert np.allclose(bolts.pattern_2d(lo, hi, 1), [[20.0, 10.0]])
    six = bolts.pattern_2d(lo, hi, 6)
    assert len(six) == 6 and len({tuple(p) for p in six}) == 6
    narrow = bolts.pattern_2d(np.zeros(2), np.array([40.0, 8.0]), 4)   # narrower than 2 × edge: the centre line
    assert np.allclose(narrow[:, 1], 4.0)


def test_layout_on_the_test_domain_puts_bolts_on_the_bolted_layer_with_bosses():
    for h, layers in ((1.5, 2), (1.0, 2), (2.0, 1)):
        dom = box_part_domain(h=h)
        assert dom.bolts.shape == (3, 3) and np.allclose(dom.bolts[:, 0], dom.plane_mm)
        cen = dom.centres()
        for b in dom.bolts:                                   # each bolt sits over a voxel of the bolted layer
            d = np.hypot(cen[0, :, :, 1] - b[1], cen[0, :, :, 2] - b[2])
            assert dom.fixed[0][d <= 0.5 * h * math.sqrt(2) + 1e-9].any()
        # bosses: through the first 2 mm (whole voxel layers), within the boss radius, never in the part
        solid = dom.passive_solid()
        assert not (dom.boss & dom.void).any() and not (dom.design() & solid).any()
        depth = [k for k in range(dom.shape[0]) if (dom.boss[k] | dom.fixed[k]).any() and k < 4]
        assert max(depth) + 1 == layers, h
        if layers > 1:
            assert dom.boss[1].sum() > 0 and not dom.boss[layers:].any()


def test_tension_and_shear_of_static_and_random_loads():
    n = bolts.outward(0, True)
    assert np.allclose(n, [1, 0, 0]) and np.allclose(bolts.outward(1, False), [0, -1, 0])
    F = np.array([[-30.0, 40.0, 0.0], [10.0, 0.0, 0.0]])
    t, s = bolts.tension_shear_static(F, n)
    assert np.allclose(t, [30.0, 10.0]) and np.allclose(s, [40.0, 0.0])
    cov = np.array([np.diag([4.0, 9.0, 16.0])])
    t3, s3 = bolts.tension_shear_3sigma(cov, n)
    assert t3[0] == pytest.approx(6.0) and s3[0] == pytest.approx(15.0)       # 3·2, 3·√(9 + 16)


def test_capacities_and_margins():
    mat = {"yield_mpa": 170.0, "ultimate_mpa": 280.0}
    cap = bolts.capacities(mat, np.array([1.5, 3.0]))             # thickness capped at the 2 mm flange
    assert np.allclose(cap["t_mm"], [1.5, 2.0])
    assert cap["bearing_u"][1] == pytest.approx(3.0 * 2.0 * 280.0)
    assert cap["pullthrough_y"][0] == pytest.approx(math.pi * 5.5 * 1.5 * 170.0 / math.sqrt(3))
    assert cap["tension_u"][0] == 3520.0 and cap["shear_u"][0] == 1880.0 and cap["tension_y"][0] == 2260.0
    m = bolts.margins(np.array([100.0, 200.0]), np.array([50.0, 10.0]), cap, 1.25, 1.4)
    ff = bolts.FITTING_FACTOR
    assert m["margins"]["bolt tension yield"][1] == pytest.approx(2260.0 / (ff * 1.25 * 200.0) - 1)
    expect = min(min(v) for v in m["margins"].values())
    assert m["ms"] == pytest.approx(expect)
    # bolt 1: tension yield 2260 / (1.15 · 1.25 · 200) − 1 = 6.86 < pull-through 3392 / 287.5 − 1 = 10.8
    assert m["check"] == "bolt tension yield" and m["bolt"] == 1
    # a thin flange makes the pull-through govern: 0.2 mm
    thin = bolts.margins(np.array([1000.0]), np.array([1.0]), bolts.capacities(mat, np.array([0.2])), 1.25, 1.4)
    assert thin["check"] == "head pull-through yield"
