"""V2 optional parts (tag "optional"): the search may leave them out when they do not fit — no violation — and the
objective O (share left out) asks it to include them."""
import copy

import numpy as np

from t2s.constraints.stage2_model import Stage2Model
from t2s.decoders.box_decoder import BoxDecoder, ProxyPart
from t2s.objectives.metrics import ENCLOSURE_HI, ENCLOSURE_LO, part_phys
from t2s.optimise.brkga import Evaluator
from t2s.optimise.scalarize import slider_weights


def _recs(dataset_parts, optional=()):
    out = {}
    for n, (p, r) in dataset_parts.items():
        if p["role"] != "packable":
            continue
        c = copy.copy(r)
        c.id = n
        c.tags = (["pcb"] if n.startswith("pcb") else []) + (["optional"] if n in optional else [])
        out[n] = c
    return out


def test_stage1_optional_part_that_does_not_fit_is_dropped_not_a_violation(dataset_parts):
    recs = _recs(dataset_parts)
    ids = list(recs)
    # three copies of the largest parts' boxes cannot all fit: shrink the box to make some parts unplaceable
    lo, hi = ENCLOSURE_LO.copy(), ENCLOSURE_HI.copy()
    hi[2] = lo[2] + 120.0
    dec = BoxDecoder([ProxyPart(i, recs[i].boxes, recs[i].allowed_orients) for i in ids], lo, hi, 0.005)
    phys = {i: part_phys(recs[i]) for i in ids}
    bounds = {i: recs[i].orient_bounds for i in ids}
    keys = np.random.default_rng(2).random(3 * len(ids))
    plain = Evaluator(dec, ids, phys, bounds, float(lo[2])).evaluate(keys)
    assert plain.unplaced and plain.cv >= len(plain.unplaced)          # required parts that do not fit: violations
    opt = set(plain.unplaced)
    ev = Evaluator(dec, ids, phys, bounds, float(lo[2]), optional=opt | {ids[0]})
    c = ev.evaluate(keys)
    assert not c.unplaced and c.cv == 0.0                                # left out instead
    assert set(c.meta["dropped"]) == opt
    assert c.raw["O"] == len(opt) / (len(opt) + (ids[0] not in opt))
    assert all(p not in opt for p, _, _ in c.poses)


def test_stage2_unmounted_optional_part_is_left_out(dataset_parts):
    names = ("battery_pack", "payload_electronics_box", "reaction_wheel", "magnetorquer_rod", "gas_tank_capsule")
    allr = _recs(dataset_parts)
    sub = {k: allr[k] for k in names}
    m_plain = Stage2Model(sub, "soft", relax={"com_box"})
    rng = np.random.default_rng(3)
    for _ in range(40):
        k = rng.random(m_plain.dim)
        r = m_plain.decode(list(np.argsort(k[:m_plain.n])), k[m_plain.n:2 * m_plain.n], k[2 * m_plain.n:])
        if not r.unplaced and r.meta["unmounted"]:
            break
    else:
        raise AssertionError("no layout with an unmounted part")
    bad = r.meta["unmounted"][0]
    sub2 = {k: copy.copy(v) for k, v in sub.items()}
    sub2[bad].tags = list(sub2[bad].tags) + ["optional"]
    m_opt = Stage2Model(sub2, "soft", relax={"com_box"})
    r2 = m_opt.decode(list(np.argsort(k[:m_opt.n])), k[m_opt.n:2 * m_opt.n], k[2 * m_opt.n:])
    assert bad in r2.meta["dropped"] and bad not in r2.meta["unmounted"]
    assert all(p != bad for p, _, _ in r2.poses)
    assert r2.penalty < r.penalty                                       # one violation fewer
    assert all(b["pid"] != bad for b in r2.meta["brackets"])


def test_optional_weight_only_when_there_are_optional_parts():
    s = {"space": 25, "balance": 25, "inertia": 25, "feasibility": 25, "optional_parts": 90}
    assert "O" not in slider_weights(s, 1)
    w = slider_weights(s, 1, optional=True)
    assert w["O"] > w["L"]
