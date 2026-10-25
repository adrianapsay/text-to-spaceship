"""V2 frame-bracing one piece: the optimiser with the frame, the whole-satellite check of a bracket layout, the
one-piece job that braces the frame, and its setting (Bracket budget at 100)."""
import json
import pickle

import numpy as np
import pytest
from test_m4_layouts import combined_layout, curved  # noqa: F401 - module fixtures

from t2s.constraints import stage2 as s2
from t2s.gd import simp
from t2s.gd.frame import frame_spec
from t2s.gd.frame_eval import layout_frame_check
from t2s.gd.layouts import build_snapshot, frame_items, one_piece_job
from t2s.gd.materials import fea_material
from t2s.gd.multi import one_piece_grid


def test_the_optimiser_braces_the_frame_and_lowers_its_compliance():
    """A 40 × 40 × 48 mm frame held at its rail ends with one heavy point load in the middle (spread over a 2 × 2 × 2
    voxel contact block): the frame-bracing SIMP starts from an even 20 % and lowers the whole structure's compliance;
    the material it keeps reaches the walls (it has no other support)."""
    env = np.array([40.0, 40.0, 48.0])
    lo, hi = -(env / 2 - s2.WALL), env / 2 - s2.WALL
    origin, h, shape = one_piece_grid(lo, hi, False, even=True)
    active = np.ones(shape, bool)
    c = np.array(shape) // 2
    solid = np.zeros(shape, bool)
    solid[c[0] - 1:c[0] + 1, c[1] - 1:c[1] + 1, c[2] - 1:c[2] + 1] = True
    acc = []
    forces = []
    for k in range(3):
        a = np.zeros(3)
        a[k] = -68.0 * 9806.65
        acc.append(a)
        F = np.zeros(shape + (3,))
        F[solid] = 0.2e-3 * a / solid.sum()                    # a 200 g part on the block
        forces.append(F)
    spec = frame_spec(origin, acc, fea_material("AlSi10Mg"), envelope=env)
    r = simp.solve(active, solid, np.zeros(shape, bool), forces, h, 0.33, 0.2, budget_s=1e9, threads=2,
                   continuation=False, max_iter=25, frame=spec)
    hist = r["history"]
    assert hist[-1] < 0.8 * hist[0]
    d = r["density"] >= 0.5
    assert d[0].any() or d[-1].any() or d[:, 0].any() or d[:, -1].any()       # it reaches a side wall
    with pytest.raises(ValueError):
        simp.solve(active[:, :, :-1], solid[:, :, :-1], np.zeros(shape, bool)[:, :, :-1],
                   [F[:, :, :-1] for F in forces], h, 0.33, 0.2, frame=spec)            # odd counts: refused


@pytest.fixture(scope="module")
def snap(combined_layout, curved):  # noqa: F811
    _, r, _, _ = combined_layout
    s = build_snapshot("L-fr", curved, r.meta, r.poses, {p: 0.2 for p in curved}, "one_piece", "gevs", "AlSi10Mg")
    s["bracket_meshes"], s["bracket_materials"] = {}, {}
    return s


def test_the_whole_satellite_check_of_the_per_part_brackets(snap):
    """Per-part brackets without solids (all estimates: their reserved boxes, labelled), every held part tied to its
    bracket, the PC/104 boards to their rods' feet: a first frequency, the frame's and the brackets' margins, the
    frame's mass as constraints.stage2 computes it."""
    fc = layout_frame_check(snap, frame_items(snap), threads=2)
    assert fc["f1_hz"] > 0 and len(fc["modes"]) >= 6
    assert set(fc["groups"]) == {"frame", "brackets"}
    assert len(fc["estimated"]) == len(snap["brackets"])
    assert fc["frame_mass_kg"] == pytest.approx(s2.frame_mass_props()[0], rel=0.01)
    assert fc["total_mass_kg"] == pytest.approx(fc["frame_mass_kg"] + 0.2 * len(snap["poses"])
                                                + fc["groups"]["brackets"]["mass_kg"], rel=1e-6)
    # modes past the spectra's band (or the cap); what they leave is the residual, quasi-static
    from t2s.gd.frame_eval import MAX_MODES
    assert fc["highest_mode_hz"] >= 2400.0 or fc["n_modes"] == MAX_MODES
    for j in range(3):
        assert fc["eff_mass_captured"][j] + fc["residual_mass_frac"][j] == pytest.approx(1.0, abs=1e-3)
    assert isinstance(fc["passed"], bool) and fc["f1_guidance_hz"] == 100.0


def test_the_frame_bracing_one_piece_job(snap, tmp_path, monkeypatch):
    """The one-piece job with brace_frame: its domain on an even grid, the frame in the optimiser, the piece checked
    by both solvers where it meets the walls, then the whole satellite with it (one fixed material use, a short
    budget). The memory guard keeps no reserve here: this tests the job, not the free memory of the machine."""
    import t2s.gd.layouts as L
    monkeypatch.setattr(L, "MEM_RESERVE_MB", 0.0)
    s = dict(snap)
    s["settings"] = {"brace_frame": True, "vol_frac": 0.08, "budget_s": 60.0}
    p = tmp_path / "snap.pkl"
    p.write_bytes(pickle.dumps(s))
    prog = one_piece_job(str(p), str(tmp_path / "out"), threads=2)
    with open(prog, encoding="utf-8") as fh:
        out = json.load(fh)
    rec = out["designs"]["one_piece"]
    assert rec["brace_frame"] is True and rec["settings"]["brace_frame"] is True
    assert all(n % 2 == 0 for n in rec["grid"])
    assert rec.get("mass_kg") is not None, rec.get("reason")
    fc = out["frame_check"]
    assert fc is not None and "error" not in fc, fc
    assert fc["f1_hz"] > 0 and fc["groups"]["brackets"]["mass_kg"] > 0


def test_a_whole_satellite_check_that_would_not_fit_in_memory_says_so(snap, tmp_path, monkeypatch):
    """The memory guard refuses the check when its predicted need (PARDISO's forecast and the eigensolver's vectors)
    would leave less than the reserve free: the check's result is that reason, nothing is factorised, and the job's
    progress row has no result (the app says "not checked", not "failed")."""
    import t2s.gd.layouts as L
    monkeypatch.setattr(L, "available_mb", lambda: 2001.0)
    monkeypatch.setattr(L, "MEM_RESERVE_MB", 2000.0)
    p = tmp_path / "snap.pkl"
    p.write_bytes(pickle.dumps({**snap, "frame_mode": "per_part"}))
    with open(L.frame_check_job(str(p), str(tmp_path / "out"), threads=2), encoding="utf-8") as fh:
        out = json.load(fh)
    fc = out["frame_check"]
    assert set(fc) == {"error"}
    assert fc["error"].startswith("not solved: whole satellite with") and "2000 MB must stay free" in fc["error"]
    row = out["brackets"][0]
    assert row["status"] == "done" and row["solid"] is False and row["reason"].startswith("not solved")


def test_a_piece_that_runs_along_the_walls_passes_the_fit_proof(combined_layout, curved, dataset_parts,  # noqa: F811
                                                               tmp_path):
    """The frame-bracing piece meets the walls wherever it runs along them: a piece of the pads and contact layers
    joined to a full-length band of material on the −x and +y walls (no optimisation) is a valid one piece for the
    fit proof as it stands (check 10: inside the inner planes, 1.2 mm from the rails and every other keep-out)."""
    from test_m4_layouts import _check, _files

    from t2s.collision.geom import part_geom_from_record
    from t2s.collision.validate import Validator
    from t2s.gd import multi, multi_eval
    from t2s.proof.bracket_layout import certificate_brackets, spec_for_layout
    from t2s.proof.certificate import build_certificate
    m, r, _, _ = combined_layout
    s = build_snapshot("L-fr", curved, r.meta, r.poses, {p: 0.2 for p in curved}, "one_piece", "gevs", "AlSi10Mg")
    dom = multi.one_piece_domain(s["brackets"], s["records"], s["poses"], s["masses"], s["inner"],
                                 [(n, k, np.asarray(b)) for n, k, b in s["keepouts"]],
                                 {p: np.asarray(b) for p, b in s["nonheld_boxes"].items()}, brace_frame=True)
    band = np.zeros(dom.shape, bool)
    band[0, :, :] = True
    band[:, -1, :] = True
    band &= dom.design()
    assert band.sum() > 100
    joined, _ = multi.join(dom, dom.passive_solid() | band)
    sol, info = multi_eval.solid_from_density(dom, np.zeros(dom.shape), joined=joined)
    assert sol is not None, info
    rec = {"parts": [p.pid for p in dom.parts], "mass_kg": 0.05, "brace_frame": True,
           "bolted": [{"part": p.pid, "axis": p.axis, "neg": p.neg, "plane_mm": p.plane, "footprint": p.box.tolist()}
                      for p in dom.parts], "held_part_distance_mm": info["held_part_distance_mm"]}
    layout = {"designs": {"one_piece": rec}}
    spec = spec_for_layout(m, r.meta, "one_piece", layout)
    rep = Validator({i: part_geom_from_record(x) for i, x in curved.items()}).validate(r.poses, spec, want_planes=True)
    assert rep.valid, rep.violations[:3]
    brs = certificate_brackets(r.meta, "one_piece", layout, lambda b: None, lambda d: sol)
    cert = build_certificate("L-fr", rep, curved, r.poses, spec, _files(dataset_parts), brackets=brs)
    code, out = _check(cert, tmp_path)
    assert code == 0 and "OVERALL: PASS" in out, out


def test_whole_satellite_results_are_kept_with_the_layout(tmp_path):
    """A combined / one-piece run's whole-satellite check goes to meta frame_checks under its mode (with whether the
    piece braces the frame), and so does the result of an on-request check (per part)."""
    from concurrent.futures import Future

    from test_m4_service import _combined_result, _coord
    c, e = _coord(tmp_path)
    folder = _combined_result(tmp_path)
    res = json.loads((folder / "progress.json").read_text(encoding="utf-8"))
    res["frame_check"] = {"f1_hz": 412.0, "passed": True, "groups": {}}
    (folder / "progress.json").write_text(json.dumps(res), encoding="utf-8")
    c.ladders["__bracket_design__"] = {"settings": {}}
    fut = Future()
    fut.set_result(str(folder / "progress.json"))
    c._on_bracket_layout(fut, "L-9", folder, "combined", {"material": "AlSi10Mg"}, {})
    fc = e.meta["frame_checks"]["combined"]
    assert fc["f1_hz"] == 412.0 and fc["brace_frame"] is False and "created" in fc
    out = tmp_path / "items" / "L-9" / "frame_check" / "per_part"
    out.mkdir(parents=True)
    (out / "progress.json").write_text(json.dumps({"status": "DONE", "mode": "frame_check", "brackets": [],
                                                   "frame_check": {"f1_hz": 300.0, "passed": True}}),
                                       encoding="utf-8")
    c.ladders["__bracket_design__"] = {"settings": {}}
    fut = Future()
    fut.set_result(str(out / "progress.json"))
    c._on_frame_check(fut, "L-9", out, "per_part")
    assert e.meta["frame_checks"]["per_part"]["f1_hz"] == 300.0
    assert e.meta["frame_checks"]["combined"]["f1_hz"] == 412.0                 # the other modes' checks stay
    assert c.ladders["__bracket_design__"]["finalised"]


def test_brace_frame_needs_the_bracket_budget_at_100(tmp_path):
    from test_search_until_pause import make_coord

    from t2s.service.coordinator import InvalidSetting
    c = make_coord(tmp_path, stage=2)
    c.store.settings["sliders"]["bracket_budget"] = 50
    with pytest.raises(InvalidSetting):
        c._check_layout_settings("one_piece", {"brace_frame": True})
    c.store.settings["sliders"]["bracket_budget"] = 100
    assert c._check_layout_settings("one_piece", {"brace_frame": True})["brace_frame"] is True
    with pytest.raises(InvalidSetting):
        c._check_layout_settings("combined", {"brace_frame": True})
    with pytest.raises(InvalidSetting):
        c._check_layout_settings("one_piece", {"brace_frame": "yes"})
    assert c._check_layout_settings("one_piece", {"brace_frame": False})["brace_frame"] is False
