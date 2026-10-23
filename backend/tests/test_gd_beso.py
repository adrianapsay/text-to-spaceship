"""Generative-design entrant: BESO (github.com/calculix/beso) driving CalculiX (t2s.gd.entrants.beso_ccx).

a. the voxel deck: one C3D8 per non-void voxel, design + passive element sets cover them, the clamped nodes lie on the
   target plane, and every load step's *CLOAD sums to the case's contact force (no ccx or BESO needed);
b. a full BESO run on box_part_domain(h = 2 mm), 240 s budget: density shape and range, void empty and passives solid,
   design-voxel volume fraction within 0.05 of vol_frac, a 6-connected solid component touching both the fixed and
   the contact voxels, under 5 minutes, one compliance value per FE iteration.
"""
import re
import time

import numpy as np
import pytest
from scipy import ndimage

from t2s.gd.domain import box_part_domain
from t2s.gd.entrants import beso_ccx

needs_beso = pytest.mark.skipif(
    not beso_ccx.available(),
    reason=(f"BESO or CalculiX not installed: need {beso_ccx.BESO_DIR} (calculix/beso commit "
            f"{beso_ccx.BESO_COMMIT[:7]}, see 'beso' in tools/toolchain.lock.json) and {beso_ccx.CCX_EXE}"))


@pytest.fixture(scope="module")
def dom():
    return box_part_domain(h=2.0)


def test_deck_supports_and_loads(dom, tmp_path):
    r = beso_ccx.filter_radius(dom.h)
    design, passive, _isolated = beso_ccx.split_domain(dom, r)
    assert not (design & passive).any()
    assert ((design | passive) == ~dom.void).all()
    info = beso_ccx.write_deck(dom, tmp_path / "beso.inp", design, passive)
    assert info["elements"] == int((~dom.void).sum())
    assert info["design"] == int(design.sum()) and info["passive"] == int(passive.sum())
    text = (tmp_path / "beso.inp").read_text()
    nodes = {}
    block = re.search(r"\*NODE, NSET=NALL\n(.*?)\n\*", text, re.DOTALL).group(1)
    for line in block.splitlines():
        n, x, y, z = line.split(",")
        nodes[int(n)] = np.array([float(x), float(y), float(z)])
    nset = re.search(r"\*NSET, NSET=NFIX\n(.*?)\n\*", text, re.DOTALL).group(1)
    nfix = [int(v) for v in nset.replace("\n", ",").split(",")]
    plane = dom.origin[dom.axis] if dom.neg else dom.origin[dom.axis] + dom.shape[dom.axis] * dom.h
    assert len(nfix) == info["fixed_nodes"] > 0
    assert np.allclose([nodes[n][dom.axis] for n in nfix], plane)
    steps = text.split("*STEP")[1:]
    cases = dom.load_cases()
    assert len(steps) == len(cases) == 3
    for step, case in zip(steps, cases):
        cl = re.search(r"\*CLOAD, OP=NEW\n(.*?)\n\*", step, re.DOTALL).group(1)
        tot = np.zeros(3)
        for line in cl.splitlines():
            n, d, v = line.split(",")
            tot[int(d) - 1] += float(v)
        assert np.allclose(tot, case["contact_force_n"], rtol=1e-9, atol=1e-9)
        assert "EALL,GRAV" in step


@pytest.fixture(scope="module")
def run(dom):
    if not beso_ccx.available():
        pytest.skip("BESO or CalculiX not installed")
    t = time.perf_counter()
    res = beso_ccx.generate(dom, budget_s=240.0, threads=2)
    return res, time.perf_counter() - t


@needs_beso
def test_beso_density_field(dom, run):
    res, _wall = run
    d = res.density
    assert res.generator == beso_ccx.NAME
    assert d.shape == dom.shape
    assert np.isfinite(d).all() and d.min() >= 0.0 and d.max() <= 1.0
    assert (d[dom.void] == 0.0).all()
    assert (d[dom.fixed] == 1.0).all() and (d[dom.contact] == 1.0).all()
    vf = float((d[dom.design()] >= 0.5).mean())
    assert abs(vf - dom.vol_frac) <= 0.05, (vf, res.notes)


@needs_beso
def test_beso_load_path_is_connected(dom, run):
    res, _ = run
    lab, n = ndimage.label(res.density >= 0.5)          # default structure: 6-connectivity
    both = [k for k in range(1, n + 1) if (lab[dom.fixed] == k).any() and (lab[dom.contact] == k).any()]
    assert both, f"{n} solid components, none joins the fixed and the contact voxels"


@needs_beso
def test_beso_runtime_and_history(run):
    res, wall = run
    assert wall < 300.0 and res.seconds < 300.0
    assert res.iterations and res.iterations > 1
    assert len(res.history) == res.iterations
    assert all(np.isfinite(res.history)) and min(res.history) > 0
    assert any("BESO 5056d30" in n for n in res.notes)
