"""V2 (WS4): per-bracket design settings — material, material used, minimum member thickness — the launch
environment and default material of the project, and how a redesign of some brackets is sent and kept."""
import asyncio
import json
import pickle
from concurrent.futures import Future
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from t2s.gd.domain import DesignDomain, member_thickness_mm, thicken_plate, thicken_skin
from t2s.service.coordinator import Coordinator, InvalidSetting

AM, CRADLE = {"pid": "p1", "kind": "metal_am"}, {"pid": "p3", "kind": "cradle"}


def test_a_brackets_settings_are_checked():
    ok = Coordinator._bracket_override(AM, {"material": "Ti-6Al-4V", "vol_frac": 0.12, "min_member_mm": "auto"})
    assert ok == {"material": "Ti-6Al-4V", "vol_frac": 0.12, "min_member_mm": "auto"}
    assert Coordinator._bracket_override(AM, {"material": None, "vol_frac": None}) == {"material": None,
                                                                                       "vol_frac": "auto"}
    assert Coordinator._bracket_override(CRADLE, {"min_member_mm": 3}) == {"min_member_mm": 3.0}
    for bad in ({"material": "6061-T6"}, {"material": "steel"}, {"vol_frac": 0.9}, {"vol_frac": 0.01},
                {"vol_frac": "lots"}, {"min_member_mm": 0.5}, {"min_member_mm": float("nan")}, {"colour": "red"}):
        with pytest.raises(InvalidSetting):
            Coordinator._bracket_override(AM, bad)
    with pytest.raises(InvalidSetting, match="machined"):          # cradles and clamp bands are machined 6061-T6
        Coordinator._bracket_override(CRADLE, {"material": "Ti-6Al-4V"})
    with pytest.raises(InvalidSetting):
        Coordinator._bracket_override(AM, [0.1])


def test_the_launch_environment_and_default_material_are_checked():
    ok = Coordinator._check_design_settings({"launch_environment": "spacex", "bracket_material": "Ti-6Al-4V"})
    assert ok == {"launch_environment": "spacex", "bracket_material": "Ti-6Al-4V"}
    assert Coordinator._check_design_settings({"stage": 2}) == {}
    for bad in ({"launch_environment": "ariane"}, {"bracket_material": "6061-T6"}, {"bracket_material": "steel"}):
        with pytest.raises(InvalidSetting):
            Coordinator._check_design_settings(bad)
    c = Coordinator.__new__(Coordinator)
    c.store = SimpleNamespace(settings={"launch_environment": "gone", "bracket_material": None})
    assert c._design_defaults() == ("gevs", "AlSi10Mg")             # a stale project file: the defaults


def _design_coord(tmp_path, **settings):
    """The parts of a Coordinator that start a bracket design run (no workers: the pool only records the job)."""
    c = Coordinator.__new__(Coordinator)
    c.store = SimpleNamespace(settings={"launch_environment": "gevs", "bracket_material": "AlSi10Mg", **settings},
                              cache=tmp_path)
    pids = ("p1", "p2", "p3", "p4")
    brs = [{"pid": "p1", "kind": "metal_am"}, {"pid": "p2", "kind": "direct"}, {"pid": "p3", "kind": "cradle"},
           {"pid": "p4", "kind": "metal_am"}]
    e = SimpleNamespace(id="L-7", stage=2, part_scale=1.0, poses=[(p, 0, [0.0, 0.0, 0.0]) for p in pids],
                        meta={"brackets": brs, "pad_orients": {}})
    c.archive, c.ladders = {"L-7": e}, {}
    c.layout_records = lambda e: {p: f"rec-{p}" for p, _, _ in e.poses}
    c._phys = lambda scale: {p: SimpleNamespace(mass_kg=0.25) for p in pids}
    c.persisted, c.sent, c.submitted = [], [], []
    c._persist = lambda e: c.persisted.append(e.id)
    c.broadcast = lambda kind, payload: c.sent.append((kind, payload))
    c._settings_view = dict
    fut = Future()                                                  # never finishes here
    c.ladder_pool = SimpleNamespace(submit=lambda *a: (c.submitted.append(a), fut)[1])
    c.loop = asyncio.new_event_loop()
    return c, e


def _snap(tmp_path):
    return pickle.loads((tmp_path / "items" / "L-7" / "bracket_design.pkl").read_bytes())


def test_redesigning_one_bracket_sends_its_settings_and_keeps_them(tmp_path):
    c, e = _design_coord(tmp_path, launch_environment="spacex")
    try:
        r = c.start_bracket_design("L-7", ["p1"], {"p1": {"material": "Ti-6Al-4V", "vol_frac": 0.12,
                                                          "min_member_mm": 3}})
        assert r["status"] == "RUNNING" and r["brackets"] == 1 and r["environment"] == "spacex"
        snap = _snap(tmp_path)
        assert snap["only"] == ["p1"] and snap["environment"] == "spacex"
        assert snap["materials"] == {"p1": "Ti-6Al-4V", "p4": "AlSi10Mg"}      # p4: the project's default material
        assert snap["overrides"] == {"p1": {"material": "Ti-6Al-4V", "vol_frac": 0.12, "min_member_mm": 3.0}}
        assert e.meta["bracket_overrides"] == snap["overrides"] and c.persisted == ["L-7"]   # kept with the layout
        assert [x["pid"] for x in c.sent[-1][1]["partial"]["brackets"]] == ["p1"]  # the progress bars: that one
        with pytest.raises(ValueError, match="already in progress"):           # one run at a time
            c.start_bracket_design("L-7")
        c.ladders.clear()
        for pids, ov in ((["p2"], None), (["nope"], None), (None, {"p1": {"vol_frac": 2}}),
                         (None, {"p3": {"material": "Ti-6Al-4V"}}), ("p1", None), (None, ["p1"])):
            with pytest.raises(InvalidSetting):                       # refused before anything changes
                c.start_bracket_design("L-7", pids, ov)
        assert e.meta["bracket_overrides"]["p1"]["vol_frac"] == 0.12 and not c.ladders
        # a later setting merges with the stored ones; a null material goes back to the project default
        c.start_bracket_design("L-7", ["p1"], {"p1": {"material": None}})
        snap = _snap(tmp_path)
        assert snap["overrides"]["p1"] == {"material": None, "vol_frac": 0.12, "min_member_mm": 3.0}
        assert snap["materials"]["p1"] == "AlSi10Mg"
        c.ladders.clear()
        c.start_bracket_design("L-7")                                  # every bracket, their stored settings
        snap = _snap(tmp_path)
        assert snap["only"] == [] and [x["pid"] for x in c.sent[-1][1]["partial"]["brackets"]] == ["p1", "p3", "p4"]
    finally:
        c.loop.close()


def test_the_fea_minimum_is_carried_only_for_the_same_material_thickness_and_environment():
    old = {"min_vol_frac": 0.08, "environment": "gevs", "ladder": [{"vol_frac": 0.08, "passed": True}],
           "settings": {"material": "AlSi10Mg", "vol_frac": "auto", "min_member_mm": "auto"}}
    new = {"min_vol_frac": None, "environment": "gevs",
           "settings": {"material": "AlSi10Mg", "vol_frac": 0.12, "min_member_mm": "auto"}}
    kept = Coordinator._carry_minimum(old, new)
    assert kept["min_vol_frac"] == 0.08 and kept["min_vol_frac_carried"] and kept["auto_ladder"] == old["ladder"]
    for change in ({"environment": "spacex"}, {"settings": {**new["settings"], "material": "Ti-6Al-4V"}},
                   {"settings": {**new["settings"], "min_member_mm": 3.0}}):
        assert Coordinator._carry_minimum(old, {**new, **change})["min_vol_frac"] is None
    own = {**new, "min_vol_frac": 0.05}
    assert Coordinator._carry_minimum(old, own) is own                # its own automatic run wins
    assert Coordinator._carry_minimum(None, new) is new


def test_a_redesign_keeps_the_designs_of_the_other_brackets(tmp_path):
    c = Coordinator.__new__(Coordinator)
    old = {"pid": "p1", "mass_kg": 0.03, "environment": "gevs", "min_vol_frac": 0.08,
           "settings": {"material": "AlSi10Mg", "vol_frac": "auto", "min_member_mm": "auto"}}
    other = {"pid": "p4", "mass_kg": 0.05, "environment": "gevs"}
    new = {"pid": "p1", "mass_kg": 0.04, "environment": "gevs", "min_vol_frac": None,
           "settings": {"material": "AlSi10Mg", "vol_frac": 0.12, "min_member_mm": "auto"}}
    (tmp_path / "progress.json").write_text(json.dumps({"designs": {"p1": new}}), encoding="utf-8")
    e = SimpleNamespace(id="L-7", meta={"bracket_designs": {"p1": old, "p4": other}})
    c.archive, c.ladders, c.proof_cache = {"L-7": e}, {"__bracket_design__": {"settings": {}}}, {("L-7", "x"): 1}
    calls = []
    c._compute_physics = c._score_entry = c._persist = lambda e: calls.append(e.id)
    c.broadcast, c.layout_json, c._settings_view = (lambda *a: None), (lambda e: {}), dict
    c.best_id, c.run_status, c._design_lid = "L-7", "SEARCHING", "L-7"
    c._save_stl = lambda e, why: calls.append("stl")
    c._error = lambda m: calls.append(m)
    fut = Future()
    fut.set_result(str(tmp_path / "progress.json"))
    c._on_bracket_design(fut, "L-7", tmp_path)
    d = e.meta["bracket_designs"]
    assert d["p4"] == other                                             # not redesigned: kept as it was
    assert d["p1"]["mass_kg"] == 0.04 and d["p1"]["min_vol_frac"] == 0.08 and d["p1"]["min_vol_frac_carried"]
    assert calls == ["L-7", "L-7", "L-7", "stl"] and not c.proof_cache and c.ladders["__bracket_design__"]["finalised"]


def test_the_design_job_designs_only_the_brackets_asked_for_with_their_settings(tmp_path, monkeypatch):
    from t2s.gd import design as gd
    seen = []

    def fake(k, b, rec, pose, mass, key, out_dir, lid, threads, material=None, environment=None, vol_frac=None,
             min_member_mm=None):
        seen.append((b["pid"], material, environment, vol_frac, min_member_mm))
        return {"pid": b["pid"], "mass_kg": 0.01, "passed": True}
    monkeypatch.setattr(gd, "_design_one", fake)
    pids = ("p1", "p2", "p3", "p4")
    snap = {"layout_id": "L-7", "brackets": [{"pid": "p1", "kind": "metal_am"}, {"pid": "p2", "kind": "direct"},
                                             {"pid": "p3", "kind": "cradle"}, {"pid": "p4", "kind": "metal_am"}],
            "records": dict.fromkeys(pids), "poses": {p: (0, np.zeros(3)) for p in pids}, "masses": {},
            "results_path": None, "environment": "spacex", "materials": {"p1": "Ti-6Al-4V", "p4": "AlSi10Mg"},
            "overrides": {"p1": {"vol_frac": 0.12, "min_member_mm": "auto"}, "p3": {"min_member_mm": 3.0}},
            "only": ["p1", "p3"]}
    sp = tmp_path / "snap.pkl"
    sp.write_bytes(pickle.dumps(snap))
    res = json.loads(Path(gd.design_job(str(sp), str(tmp_path / "out"), 1, 1)).read_text(encoding="utf-8"))
    assert seen == [("p1", "Ti-6Al-4V", "spacex", 0.12, None), ("p3", None, "spacex", None, 3.0)]
    assert set(res["designs"]) == {"p1", "p3"} and res["environment"] == "spacex" and res["n_total"] == 2


def _dom(shape=(12, 16, 16), h=0.5, neg=True):
    fixed, contact = np.zeros(shape, bool), np.zeros(shape, bool)
    fixed[0 if neg else -1] = True
    contact[-1 if neg else 0] = True
    return DesignDomain("t", np.zeros(3), h, shape, np.zeros(shape, bool), fixed, contact, 0, neg, 0.0,
                        np.r_[0, 0, 0, 6, 8, 8], 0.2)


def test_the_member_thickness_thickens_the_bolted_plate_and_the_contact_skin():
    for neg in (True, False):
        d = _dom(neg=neg)
        assert thicken_plate(d, 2.0) == 2.0 and thicken_skin(d, 1.2) == 1.5     # whole 0.5 mm voxel layers
        layers = d.plate.sum(axis=(1, 2)), d.skin.sum(axis=(1, 2))
        plate, skin = ([1, 2, 3], [9, 10]) if neg else ([8, 9, 10], [1, 2])     # behind the bolted / contact layer
        assert [i for i, n in enumerate(layers[0]) if n] == plate and [i for i, n in enumerate(layers[1]) if n] == skin
        assert (d.passive_solid() == (d.fixed | d.contact | d.plate | d.skin)).all()
    d = _dom()
    d.void[5:] = True                                                 # never into the part
    thicken_skin(d, 3.0)
    assert d.skin is None


def test_the_thinnest_generated_member_is_measured():
    for w in (1, 3, 5, 7):                                            # a w × w post from the plate to the skin
        d = _dom()
        rho = np.zeros(d.shape)
        a = 8 - w // 2
        rho[:, a:a + w, a:a + w] = 1.0
        assert member_thickness_mm(d, rho) == pytest.approx(0.5 * w)
    d = _dom()
    rho = np.zeros(d.shape)
    rho[:, 2:5, 2:5] = rho[:, 9:14, 9:14] = 1.0                       # 1.5 and 2.5 mm: the thinner one
    assert member_thickness_mm(d, rho) == pytest.approx(1.5)
    assert member_thickness_mm(d, np.zeros(d.shape)) is None           # only the prescribed plate and skin
    assert member_thickness_mm(d, np.zeros((2, 2, 2))) is None
