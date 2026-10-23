"""V2 form factor (3U / 6U / 12U, CDS Rev 14.1): one switch changes the envelope, the frame, the COM box and the
search signatures everywhere; layouts packed in a 6U are certified under the 6U rules."""
import copy

import numpy as np
import pytest

from t2s.collision.geom import part_geom_from_record
from t2s.collision.validate import Validator
from t2s.constraints import stage2 as s2
from t2s.core import formfactor
from t2s.objectives import metrics
from t2s.physics.assembly import com_box_check


@pytest.fixture
def six_u():
    formfactor.set_form_factor("6U")
    yield
    formfactor.set_form_factor("3U")


def test_switch_changes_every_shared_value(six_u):
    assert list(s2.ENVELOPE) == [226.3, 100.0, 366.0]
    assert np.allclose(metrics.ENCLOSURE_HI, [113.15, 50.0, 183.0]) and np.allclose(metrics.ENCLOSURE_LO, -metrics.ENCLOSURE_HI)
    lo, hi = s2.inner_box()
    assert np.allclose(hi - lo, [222.3, 96.0, 362.0])
    rails = {r.name: r.corners for r in s2.rails()}
    assert np.isclose(rails["rail+x+y"][:, 0].max(), 113.15) and np.isclose(rails["rail+x+y"][:, 0].min(), 113.15 - 8.5)
    assert com_box_check([40.0, 0, 0])["com_box_ok"]           # 6U: ±45 mm in X
    assert not com_box_check([0, 25.0, 0])["com_box_ok"]       # but ±20 mm in Y
    m, _, _ = s2.frame_mass_props()
    formfactor.set_form_factor("3U")
    m3, _, _ = s2.frame_mass_props()
    assert m > m3                                               # a bigger frame
    assert list(s2.ENVELOPE) == [100.0, 100.0, 340.5] and com_box_check([0, 25.0, 0])["com_box_ok"] is False


def test_unknown_form_factor_is_refused():
    with pytest.raises(ValueError):
        formfactor.set_form_factor("4U")


def test_context_signature_includes_the_form_factor(dataset_parts):
    from t2s.service.context import build_context
    recs = {n: r for n, (p, r) in dataset_parts.items() if p["role"] == "packable"}
    a = build_context(recs, 2, form_factor="3U")
    b = build_context(recs, 2, form_factor="6U")
    try:
        assert a.ctx_id != b.ctx_id and a.spec_sig != b.spec_sig and b.form_factor == "6U"
        assert np.allclose(b.com_box, [45, 20, 70])
    finally:
        formfactor.set_form_factor("3U")
    c = build_context(recs, 2, form_factor="3U")
    assert c.ctx_id == a.ctx_id                                  # the 3U default keeps its signature


def test_a_6u_layout_is_certified_under_6u_rules(dataset_parts, six_u):
    from t2s.constraints.stage2_model import Stage2Model
    recs = {}
    for n, (p, r) in dataset_parts.items():
        if p["role"] != "packable":
            continue
        c = copy.copy(r)
        c.id, c.tags = n, (["pcb"] if n.startswith("pcb") else [])
        recs[n] = c
    m = Stage2Model(recs, "soft")
    val = Validator({i: part_geom_from_record(r) for i, r in recs.items()})
    rng = np.random.default_rng(6)
    seen = 0
    best_unmounted = None
    for _ in range(6):
        k = rng.random(m.dim)
        r = m.decode(list(np.argsort(k[:m.n])), k[m.n:2 * m.n], k[2 * m.n:])
        if r.unplaced:
            continue
        seen += 1
        rep = val.validate(r.poses, m.spec(r.meta, relaxed=r.meta["overflow_mm"] > 0))
        assert rep.valid, rep.violations[:3]
        for pid, o, t in r.poses:                               # parts use the 6U width
            b = recs[pid].orient_bounds[o]
            assert b[0] + t[0] >= -113.15 and b[3] + t[0] <= 113.15
        n_un = len(r.meta["unmounted"])
        best_unmounted = n_un if best_unmounted is None else min(best_unmounted, n_un)
    assert seen
