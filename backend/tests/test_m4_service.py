"""M4 service: a finished combined / one-piece run is kept with the layout, "Use for saved STL files" switches what
the views, the physics, the bill of materials and the saved files show, and the per-part mode stays the default."""
import asyncio
import json
import pickle
from concurrent.futures import Future
from types import SimpleNamespace

import numpy as np
import pytest

from t2s.report.bom import bom_from_layout
from t2s.service.coordinator import Coordinator, InvalidSetting


def _bracket(pid, k):
    return {"name": f"bracket:{pid}", "pid": pid, "kind": "metal_am", "process": "metal_am", "axis": 0, "neg": True,
            "plane_mm": 0.0, "reserve": [0, 10 * k, 0, 7, 10 * k + 8, 8], "gap_mm": 3.0, "fasteners": 3,
            "target": "-x wall", "target_kind": "wall", "target_statics": [], "held_parts": [pid], "mass_kg": 0.02,
            "com_mm": [3, 10 * k + 4, 4], "inertia_kgm2": np.eye(3).tolist(), "cost_rel": 3.0, "material": "AlSi10Mg",
            "label": "metal-AM bracket — ESTIMATE", "exact": False, "mount_type": "metal AM bracket"}


def _coord(tmp_path):
    c = Coordinator.__new__(Coordinator)
    c.store = SimpleNamespace(settings={"launch_environment": "gevs", "bracket_material": "AlSi10Mg"}, cache=tmp_path,
                              folder=tmp_path)
    brs = [_bracket("p1", 0), _bracket("p2", 1), _bracket("p3", 2)]
    e = SimpleNamespace(id="L-9", stage=2, part_scale=1.0, poses=[(b["pid"], 0, [0.0, 0.0, 0.0]) for b in brs],
                        meta={"brackets": brs, "pad_orients": {}}, revs={"mass_rev": 1})
    c.archive, c.ladders, c.proof_cache = {"L-9": e}, {}, {("L-9", 1, "per_part"): {}}
    c.sent, c.calls = [], []
    c.broadcast = lambda kind, payload: c.sent.append((kind, payload))
    c._compute_physics = c._score_entry = c._persist = lambda e: c.calls.append(e.id)
    c.layout_json = lambda e: {"id": e.id}
    c._save_stl = lambda e, why: c.calls.append(("stl", why))
    c._error = lambda m: c.calls.append(("error", m))
    c._settings_view = dict
    c.best_id, c._design_lid = "L-9", None
    return c, e


def _combined_result(tmp_path, ok=True):
    """What gd.layouts.combined_job writes: one combined bracket of p1 and p2 (with its mesh file)."""
    folder = tmp_path / "items" / "L-9" / "combined"
    folder.mkdir(parents=True, exist_ok=True)
    v = np.array([[0, 0, 0], [5, 0, 0], [0, 5, 0], [0, 0, 5]], "<f4")
    f = np.array([[0, 2, 1], [0, 1, 3], [0, 3, 2], [1, 2, 3]], "<u4")
    (folder / "L-9-cb0.bin").write_bytes(np.array([4, 4], "<u4").tobytes() + v.tobytes() + f.tobytes())
    rec = {"name": "combined:1", "kind": "combined", "parts": ["p1", "p2"], "index": 0, "key": "p1+p2",
           "passed": ok, "reason": "" if ok else "MS yield -0.2", "mass_kg": 0.05 if ok else None,
           "solid_mass_kg": 0.0469, "fastener_mass_kg": 0.0031 * 1, "fasteners": 6, "com_mm": [3, 9, 4],
           "inertia_kgm2": np.eye(3).tolist(), "material": "AlSi10Mg", "material_name": "AlSi10Mg L-PBF",
           "label": "combined metal-AM bracket", "target": "-x wall", "mesh_file": "L-9-cb0.bin",
           "governing": {"case": "static", "axis": "z", "check": "yield", "ms": 1.5, "part": "bracket"},
           "f1_hz": 900.0, "size_mm": [7.0, 18.0, 8.0], "boxes": [{"name": "bracket:p1", "role": "member",
                                                                  "box": [0, 0, 0, 7, 8, 8]}],
           "checks": [{"case": "static"}] * 3}
    (folder / "progress.json").write_text(json.dumps({"status": "DONE", "mode": "combined", "designs": {
        "p1+p2": rec}, "groups": [{"name": "combined:1", "pids": ["p1", "p2"]}], "seconds_total": 12.0,
        "peak_rss_mb": 800.0, "brackets": []}), encoding="utf-8")
    return folder


def test_a_finished_combined_run_is_kept_and_per_part_stays_the_default(tmp_path):
    c, e = _coord(tmp_path)
    folder = _combined_result(tmp_path)
    c.ladders["__bracket_design__"] = {"settings": {}}
    fut = Future()
    fut.set_result(str(folder / "progress.json"))
    c._on_bracket_layout(fut, "L-9", folder, "combined", {"material": "AlSi10Mg"}, {})
    res = e.meta["bracket_layouts"]["combined"]
    assert res["status"] == "designed" and res["designs"]["p1+p2"]["mass_kg"] == 0.05 and res["peak_rss_mb"] == 800.0
    assert c.ladders["__bracket_design__"]["finalised"] and not c.proof_cache          # its proofs are rebuilt
    assert c._bracket_mode(e) == "per_part" and c._active_layout(e) == ("per_part", None)
    assert not any(isinstance(x, tuple) and x[0] == "stl" for x in c.calls)             # not chosen: files unchanged
    kinds = [b["bracket_kind"] for b in c._extra_items(e) if b["kind"] == "bracket"]
    assert kinds == ["metal_am"] * 3                                                    # still one bracket per part


def test_use_for_saved_stl_switches_items_meshes_and_bom(tmp_path):
    c, e = _coord(tmp_path)
    folder = _combined_result(tmp_path)
    c.ladders["__bracket_design__"] = {"settings": {}}
    fut = Future()
    fut.set_result(str(folder / "progress.json"))
    c._on_bracket_layout(fut, "L-9", folder, "combined", {}, {})
    with pytest.raises(InvalidSetting):
        c.use_bracket_layout("L-9", "everything")
    with pytest.raises(ValueError, match="not designed"):
        c.use_bracket_layout("L-9", "one_piece")
    with pytest.raises(KeyError):
        c.use_bracket_layout("L-NOPE", "combined")
    r = c.use_bracket_layout("L-9", "combined")
    assert r["chosen"] == "combined" and e.meta["bracket_mode"] == "combined"
    assert ("stl", "bracket layout chosen: combined") in c.calls
    items = [b for b in c._extra_items(e) if b["kind"] == "bracket"]
    assert [b["bracket_kind"] for b in items] == ["metal_am", "combined"]                # p3 keeps its own bracket
    cb = items[1]
    assert cb["id"] == "L-9-cb0" and cb["for_parts"] == ["p1", "p2"] and cb["designed"] and cb["mass_kg"] == 0.05
    mesh = c.item_mesh("L-9-cb0")
    assert np.frombuffer(mesh[:8], "<u4").tolist() == [4, 4]
    with pytest.raises(KeyError):
        c.item_mesh("L-9-cb7")
    bom = bom_from_layout({"id": "L-9", "stage": 2, "poses": [{"part_id": p} for p in ("p1", "p2", "p3")],
                           "extra_items": c._extra_items(e), "metrics": {}, "stage2": {"brackets": e.meta["brackets"]}},
                          {p: {"name": p.upper(), "mass_kg": 0.1} for p in ("p1", "p2", "p3")})
    rows = [r for r in bom["items"] if r["group"] == "brackets"]
    comb = next(r for r in rows if r["bracket_kind"] == "combined")
    assert comb["for_parts"] == ["p1", "p2"] and comb["designed"] and comb["unit_mass_kg"] == pytest.approx(0.0469)
    fast = next(r for r in bom["items"] if r["kind"] == "fastener")
    assert fast["qty"] == 6 + 3                                       # its 6 bolts and p3's bracket's 3
    # back to one bracket per part
    c.use_bracket_layout("L-9", "per_part")
    assert [b["bracket_kind"] for b in c._extra_items(e) if b["kind"] == "bracket"] == ["metal_am"] * 3


def test_a_chosen_layout_without_a_solid_falls_back_to_per_part(tmp_path):
    c, e = _coord(tmp_path)
    folder = _combined_result(tmp_path, ok=False)
    c.ladders["__bracket_design__"] = {"settings": {}}
    fut = Future()
    fut.set_result(str(folder / "progress.json"))
    c._on_bracket_layout(fut, "L-9", folder, "combined", {}, {})
    with pytest.raises(ValueError, match="not designed"):
        c.use_bracket_layout("L-9", "combined")
    e.meta["bracket_mode"] = "combined"                              # e.g. an older record: shown as per part
    assert c._active_layout(e) == ("per_part", None)


def test_layout_summaries_count_every_bracket_once():
    """The comparison numbers: per part sums every bracket; a combined print replaces its members' brackets; one
    without a solid is listed as failed and its parts keep their per-part brackets (as the views show them)."""
    from t2s.gd.layouts import mode_summary, per_part_summary
    brs = [_bracket("p1", 0), _bracket("p2", 1), _bracket("p3", 2)]
    pp = per_part_summary(brs, {})
    assert pp["bracket_mass_kg"] == pytest.approx(0.06) and pp["prints"] == 3 and pp["estimates"] == 3
    rec = {"name": "combined:1", "parts": ["p1", "p2"], "passed": True, "mass_kg": 0.05, "size_mm": [7.0, 18.0, 8.0],
           "governing": {"case": "static", "axis": "z", "check": "yield", "ms": 1.5}, "f1_hz": 900.0}
    ok = mode_summary("combined", brs, {}, {"designs": {"p1+p2": rec}})
    assert ok["bracket_mass_kg"] == pytest.approx(0.05 + 0.02) and ok["prints"] == 2 and ok["pieces"] == 2
    assert ok["unchanged"] == ["p3"] and ok["failed"] == [] and ok["passed"]
    assert ok["worst"]["ms"] == 1.5 and ok["f1"]["f_hz"] == 900.0 and ok["largest_print_mm"] == [7.0, 18.0, 8.0]
    bad = mode_summary("combined", brs, {}, {"designs": {"p1+p2": {**rec, "mass_kg": None, "passed": False}}})
    assert bad["failed"] == ["p1+p2"] and bad["passed"] is False
    assert bad["bracket_mass_kg"] == pytest.approx(0.06) and bad["prints"] == 3 and bad["pieces"] == 3
    assert bad["unchanged"] == ["p1", "p2", "p3"]


def test_layout_run_settings_are_checked(tmp_path):
    c, _ = _coord(tmp_path)
    assert c._check_layout_settings("one_piece", {"budget_s": 600, "vol_frac": 0.05}) == {"budget_s": 600.0,
                                                                                          "vol_frac": 0.05}
    assert c._check_layout_settings("combined", {"material": "Ti-6Al-4V", "min_member_mm": "auto"}) == {
        "material": "Ti-6Al-4V", "min_member_mm": "auto"}
    for mode, bad in (("combined", {"budget_s": 60}), ("one_piece", {"budget_s": 5}), ("one_piece", {"budget_s": "x"}),
                      ("combined", {"vol_frac": 0.95}), ("combined", {"material": "6061-T6"}), ("combined", [1])):
        with pytest.raises(InvalidSetting):
            c._check_layout_settings(mode, bad)


def test_starting_a_layout_run_sends_one_job_at_a_time(tmp_path, monkeypatch):
    c, e = _coord(tmp_path)
    snap = {"layout_id": "L-9", "brackets": e.meta["brackets"]}
    monkeypatch.setattr(Coordinator, "_layout_snapshot",
                        lambda self, e, mode, st=None, ov=None, with_meshes=False: dict(snap, mode=mode))
    import t2s.gd.layouts as L
    monkeypatch.setattr(L, "plan_combined", lambda s: [{"name": "combined:1"}])
    fut = Future()
    submitted = []
    c.ladder_pool = SimpleNamespace(submit=lambda *a: (submitted.append(a), fut)[1])
    c.loop = asyncio.new_event_loop()
    try:
        with pytest.raises(InvalidSetting):
            c.start_bracket_layout("L-9", "per_part")
        r = c.start_bracket_layout("L-9", "one_piece", {"budget_s": 300})
        assert r["status"] == "RUNNING" and r["mode"] == "one_piece" and submitted[-1][2] is L.one_piece_job
        sent = pickle.loads((tmp_path / "items" / "L-9" / "one_piece" / "snapshot.pkl").read_bytes())
        assert sent["mode"] == "one_piece" and c.sent[-1][1]["partial"]["mode"] == "one_piece"
        with pytest.raises(ValueError, match="already in progress"):            # one run at a time
            c.start_bracket_layout("L-9", "combined")
        with pytest.raises(ValueError, match="already in progress"):            # the per-part job too
            c.start_bracket_design("L-9")
        c.ladders.clear()
        monkeypatch.setattr(L, "plan_combined", lambda s: [])
        with pytest.raises(ValueError, match="can be joined"):
            c.start_bracket_layout("L-9", "combined")
    finally:
        c.loop.close()
