"""V2 bracket design job: a metal-AM bracket of a Stage 2 layout gets a real solid inside its reserved box, checked
with both FEA solvers, and its certificate entry carries every vertex of that solid."""
import copy

import numpy as np
import pytest

from t2s.constraints.stage2_model import Stage2Model
from t2s.fea import ccx
from t2s.gd.design import design_bracket
from t2s.mfg.brackets import cert_entry


@pytest.mark.skipif(not ccx.available(), reason="CalculiX not installed (tools/ccx)")
def test_metal_am_bracket_is_designed_inside_its_box(dataset_parts):
    recs = {}
    for n, (p, r) in dataset_parts.items():
        if p["role"] != "packable":
            continue
        c = copy.copy(r)
        c.id, c.tags = n, (["pcb"] if n.startswith("pcb") else [])
        recs[n] = c
    m = Stage2Model(recs, "soft")
    rng = np.random.default_rng(1)
    b = None
    for _ in range(30):
        k = rng.random(m.dim)
        r = m.decode(list(np.argsort(k[:m.n])), k[m.n:2 * m.n], k[2 * m.n:])
        am = [x for x in r.meta.get("brackets", []) if x["kind"] == "metal_am"]
        if am:
            b = min(am, key=lambda x: np.prod(np.subtract(x["reserve"][3:], x["reserve"][:3])))   # smallest box
            pad = r.meta["pad_orients"]
            o, t = next((pad.get(p, o), t) for p, o, t in r.poses if p == b["pid"])
            break
    assert b is not None, "no metal-AM bracket in 30 random layouts"
    from t2s.gd.design import design_h
    assert design_h([0, 0, 0, 30, 30, 30]) == 1.5 and design_h([0, 0, 0, 100, 100, 100]) > 1.5
    assert design_h([0, 0, 0, 7, 48, 32], axis=0) == 1.0            # a 3 mm gap + 4 mm wrap: six layers across
    # at the app's voxel size for this box (design_h: enough layers across a thin 3 mm gap + wrap)
    d, mesh = design_bracket(b, recs[b["pid"]], o, t, 0.3, "baseline", h=design_h(b["reserve"], int(b["axis"])),
                             threads=2, log=lambda *_: None)
    assert mesh is not None and d["mass_kg"] > 0 and d["generator"]
    v, f = mesh
    res = np.asarray(b["reserve"])
    assert np.all(v >= res[:3] - 1e-5) and np.all(v <= res[3:] + 1e-5)          # inside the certified box
    assert d["sigma_mpa"] is not None and d["f1_hz"] is not None
    assert set(d["solvers"]) == {"ccx", "ngs"}
    e = cert_entry(b, v)
    assert not e["estimate"] and len(e["solid_vertices"]) == len(v)


@pytest.mark.skipif(not ccx.available(), reason="CalculiX not installed (tools/ccx)")
def test_design_job_designs_brackets_in_parallel_inside_a_pool_worker(dataset_parts, tmp_path):
    """As the app runs it: the job in a process-pool worker, its brackets designed two at a time in processes of
    their own; every bracket gets its solid, its mesh files and its entry in progress.json."""
    import json
    import pickle
    from concurrent.futures import ProcessPoolExecutor
    from pathlib import Path

    from t2s.gd.design import DESIGNED_KINDS, design_job
    recs = {}
    for n, (p, r) in dataset_parts.items():
        if p["role"] == "packable":
            c = copy.copy(r)
            c.id, c.tags = n, (["pcb"] if n.startswith("pcb") else [])
            recs[n] = c
    m = Stage2Model(recs, "soft")
    rng = np.random.default_rng(2)
    for _ in range(30):
        k = rng.random(m.dim)
        r = m.decode(list(np.argsort(k[:m.n])), k[m.n:2 * m.n], k[2 * m.n:])
        todo = [x for x in r.meta.get("brackets", []) if x["kind"] in DESIGNED_KINDS]
        if len(todo) >= 2:
            break
    todo = sorted(todo, key=lambda x: np.prod(np.subtract(x["reserve"][3:], x["reserve"][:3])))[:2]   # smallest
    pad = r.meta["pad_orients"]
    poses = {p: (pad.get(p, o), np.asarray(t, float)) for p, o, t in r.poses}
    snap = {"layout_id": "L-T", "brackets": todo, "records": {b["pid"]: recs[b["pid"]] for b in todo},
            "poses": {b["pid"]: poses[b["pid"]] for b in todo}, "masses": {b["pid"]: 0.2 for b in todo},
            "results_path": None}                                       # no contest results: the rule-based shape
    sp = tmp_path / "snap.pkl"
    sp.write_bytes(pickle.dumps(snap))
    with ProcessPoolExecutor(1) as ex:
        prog = ex.submit(design_job, str(sp), str(tmp_path / "out"), 1, 2).result(timeout=1800)
    res = json.loads(Path(prog).read_text(encoding="utf-8"))
    assert res["status"] == "DONE" and res["progress"] == 1.0 and set(res["designs"]) == {b["pid"] for b in todo}
    for b in todo:
        d = res["designs"][b["pid"]]
        assert d["mass_kg"] > 0 and (tmp_path / "out" / d["mesh_file"]).is_file(), d.get("reason")
