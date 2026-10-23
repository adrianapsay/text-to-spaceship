"""V2 Stage 2 brackets: every non-board part is held by a bracket whose reserved box is part of the packing and of
the fit proof (Lemma 4); the bracket budget switches metal-AM brackets on and weights the hardware cost."""
import copy
import json
import subprocess
import sys

import numpy as np
import pytest
from conftest import DATA
from test_proof import CHECKER

from t2s.collision.geom import part_geom_from_record
from t2s.collision.validate import Validator, box_gap
from t2s.constraints.stage2_model import Stage2Model
from t2s.mfg.brackets import cert_entry, v2_bracket
from t2s.mfg.rules import BRACKET_CLEARANCE, MFG_REACH
from t2s.optimise.scalarize import slider_weights
from t2s.proof.certificate import build_certificate, proof_markdown

SMALL = ("battery_pack", "payload_electronics_box", "reaction_wheel", "magnetorquer_rod")


@pytest.fixture(scope="module")
def recs(dataset_parts):
    out = {}
    for n, (p, r) in dataset_parts.items():
        if p["role"] != "packable":
            continue
        c = copy.copy(r)
        c.id, c.tags = n, (["pcb"] if n.startswith("pcb") else [])
        out[n] = c
    return out


@pytest.fixture(scope="module")
def files(dataset_parts):
    return {n: (p["file"], p["sha256"]) for n, (p, r) in dataset_parts.items()}


def _decode(m, k):
    n = m.n
    return m.decode(list(np.argsort(k[:n], kind="stable")), k[n:2 * n], k[2 * n:])


def _mounted_layout(m, seed=0, tries=600):
    """A random decode with every part mounted (random orientations often point a mounting side along Z, far
    from the end plates; the search steers away from those)."""
    rng = np.random.default_rng(seed)
    for _ in range(tries):
        r = _decode(m, rng.random(m.dim))
        if not r.unplaced and not r.meta["unmounted"] and r.meta["overflow_mm"] <= 0:
            return r
    return None


def test_every_bracket_keeps_its_clearances_and_lies_in_its_box(recs):
    val = Validator({i: part_geom_from_record(r) for i, r in recs.items()})
    seen = set()
    for mode, seed in (("default", 1), ("soft", 2), ("continuous", 3)):
        m = Stage2Model(recs, mode)
        rng = np.random.default_rng(seed)
        for _ in range(6):
            r = _decode(m, rng.random(m.dim))
            if r.unplaced:
                continue
            rep = val.validate(r.poses, m.spec(r.meta, relaxed=r.meta["overflow_mm"] > 0))
            assert rep.valid, (mode, rep.violations[:3])
            brs = r.meta["brackets"]
            for i, b in enumerate(brs):
                seen.add(b["kind"])
                res = np.asarray(b["reserve"], float)
                assert np.all(res[3:] > res[:3])                       # a proper box
                assert 0 <= b["gap_mm"] <= MFG_REACH + 1e-9
                br = v2_bracket(b["name"], b["pid"], b)
                assert br.mass_kg > 0 and br.estimate == (b["kind"] in ("cradle", "metal_am"))
                for v, _ in br.meshes:                                  # the solid stays inside its reserved box
                    assert np.all(v >= res[:3] - 1e-9) and np.all(v <= res[3:] + 1e-9)
                for o in brs[i + 1:]:
                    assert box_gap(*(np.array([x[:3], x[3:]]) for x in (res, np.asarray(o["reserve"])))) \
                        >= BRACKET_CLEARANCE - 1e-9
            # every mounted non-board part has exactly one bracket
            held = {b["pid"] for b in brs}
            for pid, info in r.meta["mounts"].items():
                if info["ok"] and pid in m.pads:
                    assert pid in held
    assert {"machined", "metal_am"} <= seen


def test_bracket_budget_zero_uses_simple_brackets_only(recs):
    # no COM shift: both models then decode the same poses
    simple = Stage2Model(recs, "soft", relax={"com_box"}, am_allowed=False)
    am = Stage2Model(recs, "soft", relax={"com_box"}, am_allowed=True)
    rng = np.random.default_rng(4)
    mounted_simple = mounted_am = 0
    for _ in range(10):
        k = rng.random(simple.dim)
        a, b = _decode(simple, k), _decode(am, k)
        assert [p[0] for p in a.poses] == [p[0] for p in b.poses]
        assert all(x["kind"] != "metal_am" for x in a.meta["brackets"])
        mounted_simple += len(a.meta["brackets"])
        mounted_am += len(b.meta["brackets"])
        # the cheapest bracket that fits is used: for the first part checked (nothing reserved before it) the
        # wider choice with metal AM never costs more
        first = next(pid for pid, _, _ in a.poses if pid in simple.pads)
        x = next((y for y in a.meta["brackets"] if y["pid"] == first), None)
        z = next((y for y in b.meta["brackets"] if y["pid"] == first), None)
        if x is not None:
            assert z is not None and z["cost_rel"] <= x["cost_rel"] + 1e-9
    assert mounted_am >= mounted_simple


def test_cost_weight_follows_the_bracket_budget():
    base = {"space": 25, "balance": 25, "inertia": 25, "feasibility": 25}
    w0 = slider_weights({**base, "bracket_budget": 0}, 2)
    w100 = slider_weights({**base, "bracket_budget": 100}, 2)
    assert w0["C"] > w100["C"] > 0
    assert "C" not in slider_weights({**base, "bracket_budget": 0}, 1)     # Stage 1 has no brackets


def test_bracket_proof_round_trip_and_mutations(recs, files, tmp_path):
    sub = {k: recs[k] for k in SMALL}
    m = Stage2Model(sub, "soft")
    r = _mounted_layout(m)
    assert r is not None, "no fully mounted layout of the small set in 600 random decodes"
    geoms = {i: part_geom_from_record(x) for i, x in sub.items()}
    spec = m.spec(r.meta)
    rep = Validator(geoms).validate(r.poses, spec, want_planes=True)
    assert rep.valid, rep.violations[:3]
    assert rep.static_pairs and all(p.ok for p in rep.static_pairs)
    brs = [cert_entry(b) for b in r.meta["brackets"]]
    cert = build_certificate("L-br", rep, sub, r.poses, spec, files, brackets=brs)
    md = proof_markdown(cert, rep)
    assert "Lemma 4" in md
    cp = tmp_path / "c.json"

    def check(c):
        cp.write_text(json.dumps(c))
        out = subprocess.run([sys.executable, "-I", str(CHECKER), str(cp), str(DATA)], capture_output=True,
                             text=True, timeout=600)
        return out.returncode, out.stdout
    code, out = check(cert)
    assert code == 0 and "OVERALL: PASS" in out, out
    assert "PASS  bracket_solids_in_boxes" in out and "PASS  bracket_boxes_apart" in out
    # a solid poking out of its box
    solid = next(i for i, b in enumerate(brs) if b["solid_vertices"])
    bad = copy.deepcopy(cert)
    bad["brackets"][solid]["solid_vertices"][0][0] = bad["brackets"][solid]["reserve"][3] + 1.0
    code, out = check(bad)
    assert code != 0 and "FAIL" in out
    # two boxes claimed apart that overlap
    if cert["static_pairs"]:
        bad = copy.deepcopy(cert)
        bad["static_pairs"][0]["corners_b"] = bad["static_pairs"][0]["corners_a"]
        code, out = check(bad)
        assert code != 0
    # a frame item the app certified numerically (compound boxes / exact distance) is counted, not re-derived from
    # the part's vertex box (a sphere in a corner overlaps the rail as a box, not as a solid)
    num = copy.deepcopy(cert)
    num["statics"][0]["method"] = "numeric"
    num["statics"][0]["corners"] = [list(p) for p in np.asarray(num["statics"][0]["corners"]) * 0 +
                                    np.asarray(num["parts"][0]["t_mm"])]
    code, out = check(num)
    assert code == 0 and "certified numerically" in out, out
    # a part-to-bracket clearance check left out
    i = next(i for i, s in enumerate(cert["statics"]) if s["static"].startswith("bracket:"))
    bad = copy.deepcopy(cert)
    del bad["statics"][i]
    code, out = check(bad)
    assert code != 0 and "no clearance check" in out
