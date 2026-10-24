"""M4: live backend — REST, WebSocket protocol, search → validation → archive, proofs, parts added later (T-API)."""
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from t2s.api.app import create_app
from t2s.collision.geom import part_geom_from_record
from t2s.collision.validate import StageSpec, Validator
from t2s.objectives.metrics import ENCLOSURE_HI, ENCLOSURE_LO
from t2s.service.coordinator import Coordinator
from t2s.service.project import DATASET, ProjectStore

REPO = Path(__file__).resolve().parents[2]
PARTS = ["battery_pack", "pcb_obc", "payload_electronics_box", "reaction_wheel", "wedge_bracket"]


def wait_for(pred, timeout=90.0, every=0.25):
    t0 = time.time()
    while time.time() - t0 < timeout:
        v = pred()
        if v:
            return v
        time.sleep(every)
    raise AssertionError("timed out")


@pytest.fixture(scope="module")
def live(tmp_path_factory):
    root = tmp_path_factory.mktemp("projects")
    store = ProjectStore("t", root=root)
    for name in PARTS:
        store.add_file((DATASET / f"{name}.stl").read_bytes(), f"{name}.stl", units="mm", source="dataset")
    coord = Coordinator(store, n_islands=1, n_validators=1, seed=7)
    coord.cpsat_time_s = 10.0
    coord.use_evidence = False                      # the selector tests check the documented default rules
    coord.auto_ladder = False                       # the ladder has its own (shortened) test below
    coord.ladder_opts = {"generations": 2, "pop": 12, "fr_samples": 20}
    app = create_app(coord)
    with TestClient(app) as client:
        yield client, coord, store


def best(client):
    r = client.get("/api/layouts", params={"limit": 1}).json()
    return r["best_id"]


def test_cpsat_seed_layout_is_validated_and_archived(live):
    client, coord, _ = live
    e = wait_for(lambda: next((x for x in list(coord.archive.values()) if x.algorithm.get("id") == "cpsat_box"), None),
                 timeout=120)
    assert e.status == "VALIDATED" and e.validation["certified"]
    res = coord.cpsat_results[e.parts_sig]
    assert res["lower_bound_mm"] is not None and res["lower_bound_mm"] <= res["length_mm"] + 1e-9
    assert client.get("/api/project").json()["bounds"]["cpsat_single_box"]["status"] in ("OPTIMAL", "FEASIBLE")


def test_health_and_project(live):
    client, coord, _ = live
    h = client.get("/api/health").json()
    assert h["ok"] and h["fusion360"] == "NOT_CONFIGURED"
    p = client.get("/api/project").json()
    assert len(p["rotations"]) == 24 and p["rotations"][0] == [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
    assert p["enclosure"]["size_mm"] == [100.0, 100.0, 340.5]
    assert {q["name"] for q in p["parts"]} == set(PARTS)
    wait_for(lambda: all(q["status"] == "VALID" for q in client.get("/api/project").json()["parts"]))
    q = next(q for q in client.get("/api/project").json()["parts"] if q["name"] == "battery_pack")
    assert q["mass_source"] == "ASSUMED" and abs(q["mass_kg"] - 0.38016) < 1e-9
    assert len(q["inertia_com_kgm2"]) == 3 and q["units_confirmed"]


def test_search_validates_layouts_and_they_really_fit(live):
    client, coord, store = live
    lid = wait_for(lambda: best(client))
    lay = client.get(f"/api/layouts/{lid}").json()
    assert lay["status"] == "VALIDATED" and lay["validation"]["certified"]
    assert {p["part_id"] for p in lay["poses"]} == set(store.entries)
    assert all(isinstance(v, int) for p in lay["poses"] for v in p["t_um"])
    # independent re-validation of exactly the published (integer-µm) poses
    poses = [(p["part_id"], p["orient"], np.array(p["t_um"], float) / 1000.0) for p in lay["poses"]]
    geoms = {pid: part_geom_from_record(coord.records[pid]) for pid, _, _ in poses}
    rep = Validator(geoms).validate(poses, StageSpec(1, ENCLOSURE_LO, ENCLOSURE_HI, 0.0, 0.0))
    assert rep.valid, rep.violations
    assert abs(rep.min_clearance_mm - lay["metrics"]["min_clearance_mm"]) < 1e-6
    m = lay["metrics"]
    assert 0 < m["length_used_mm"] <= 340.5 and m["mass_kg"] > 0 and len(m["principal_axes"]) == 3


def test_ws_snapshot_settings_ack_and_rescore(live):
    client, coord, _ = live
    wait_for(lambda: best(client))
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"v": 1, "type": "hello", "payload": {"last_epoch": None, "want_candidates": False}})
        snap = ws.receive_json()
        assert snap["type"] == "state.snapshot" and snap["payload"]["best_validated"]["status"] == "VALIDATED"
        w0 = snap["weights_rev"]
        settings = snap["payload"]["project"]["settings"]
        settings["sliders"].update({"space": 5, "balance": 95})
        ws.send_json({"v": 1, "type": "edit.settings", "payload": {"client_seq": 1, "settings": settings, "commit": True}})
        got, last_seq = {}, snap["seq"]
        for _ in range(400):
            m = ws.receive_json()
            assert m["seq"] > last_seq
            last_seq = m["seq"]
            got.setdefault(m["type"], m)
            if m["type"] == "edit.ack":
                break
        assert got["edit.ack"]["payload"]["client_seq"] == 1 and got["edit.ack"]["applied_client_seq"] == 1
        lv = got["layout.validated"]["payload"]
        assert lv["source"] == "archive" and lv["layout"]["weights_rev"] == w0 + 1
        settings["sliders"].update({"space": 25, "balance": 25})
        ws.send_json({"v": 1, "type": "edit.settings", "payload": {"client_seq": 2, "settings": settings, "commit": True}})
        for _ in range(400):
            if ws.receive_json()["type"] == "edit.ack":
                break


def test_mass_edit_updates_metrics_without_new_geometry(live):
    client, coord, store = live
    lid = wait_for(lambda: best(client))
    pid = next(pid for pid, e in store.entries.items() if e.name == "battery_pack")
    m0 = client.get(f"/api/layouts/{lid}").json()["metrics"]["mass_kg"]
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"v": 1, "type": "hello", "payload": {}})
        assert ws.receive_json()["type"] == "state.snapshot"
        ws.send_json({"v": 1, "type": "edit.part", "payload": {"client_seq": 1, "part_id": pid, "patch": {"mass_kg": 1.0}}})
        upd = None
        for _ in range(400):
            m = ws.receive_json()
            if m["type"] == "metrics.update":
                upd = m
            if m["type"] == "edit.ack":
                break
        assert upd is not None and upd["mass_rev"] >= 1
        assert abs(upd["payload"]["metrics"]["mass_kg"] - (m0 - 0.38016 + 1.0)) < 1e-9
    part = next(q for q in client.get("/api/project").json()["parts"] if q["id"] == pid)
    assert part["mass_source"] == "USER_MASS" and part["mass_kg"] == 1.0
    r = client.patch(f"/api/parts/{pid}", json={"mass_kg": None})
    assert r.status_code == 200 and r.json()["mass_source"] == "ASSUMED"
    assert client.patch(f"/api/parts/{pid}", json={"mass_kg": -2}).status_code == 409


def test_proof_and_independent_checker(live, tmp_path):
    client, coord, store = live
    lid = wait_for(lambda: best(client))
    p = client.get(f"/api/layouts/{lid}/proof").json()
    assert p["valid"] and p["markdown"].startswith(f"# Proof that layout {lid} fits")
    cert = tmp_path / "certificate.json"
    cert.write_text(json.dumps(p["certificate"]), encoding="utf-8")
    out = subprocess.run([sys.executable, "-I", str(REPO / "tools" / "check_certificate.py"), str(cert),
                          str(store.parts_dir)], capture_output=True, text=True, timeout=300)
    assert out.returncode == 0, out.stdout + out.stderr
    assert "OVERALL: PASS" in out.stdout
    chk = client.get(f"/api/layouts/{lid}/proof/download", params={"kind": "checker"})
    assert chk.status_code == 200 and b"def main" in chk.content


def test_lock_keeps_current_layout(live):
    client, coord, store = live
    lid = wait_for(lambda: best(client))
    lay = client.get(f"/api/layouts/{lid}").json()
    pose = lay["poses"][0]
    r = client.patch(f"/api/parts/{pose['part_id']}", json={"locked": True})
    assert r.status_code == 200 and r.json()["locked"] and r.json()["lock_pose"]["t_um"] == pose["t_um"]
    # the layout satisfies the new lock exactly, so it stays current (re-stamped with the new constraint_rev)
    lay2 = client.get(f"/api/layouts/{lid}").json()
    assert lay2["current"] and lay2["constraint_rev"] == coord.store.revs["constraint_rev"]
    # new layouts keep the locked part where it is
    n0 = len(coord.archive)
    wait_for(lambda: any(e for e in list(coord.archive.values())[n0:] if coord._current(e)), timeout=60)
    for e in list(coord.archive.values())[n0:]:
        if coord._current(e):
            q = next(p for p in coord.layout_json(e)["poses"] if p["part_id"] == pose["part_id"])
            assert q["t_um"] == pose["t_um"] and q["orient"] == pose["orient"]
    assert client.patch(f"/api/parts/{pose['part_id']}", json={"locked": False}).json()["locked"] is False


def test_add_part_later_needs_units_then_joins_the_search(live):
    client, coord, store = live
    data = (DATASET / "magnetorquer_rod.stl").read_bytes()
    r = client.post("/api/parts", files=[("files[]", ("friend_part.stl", data, "application/octet-stream"))])
    assert r.status_code == 200
    part = r.json()["parts"][0]
    assert part["status"] == "NEEDS_UNITS" and part["name"] == "friend_part"
    mesh = client.get(f"/api/parts/{part['id']}/mesh").content
    nv, nt = np.frombuffer(mesh[:8], "<u4")
    assert len(mesh) == 8 + 12 * nv + 12 * nt
    parts_rev = client.get("/api/project").json()["revs"]["parts_rev"]
    c = client.post(f"/api/parts/{part['id']}/units", json={"units": "mm"})
    assert c.status_code == 200 and c.json()["status"] == "VALID"
    assert client.get("/api/project").json()["revs"]["parts_rev"] > parts_rev
    lid = wait_for(lambda: (b := best(client)) and part["id"] in client.get(f"/api/layouts/{b}").json()["part_ids"] and b,
                   timeout=120)
    assert client.get(f"/api/layouts/{lid}").json()["current"]
    assert client.delete(f"/api/parts/{part['id']}").status_code == 200
    assert part["id"] not in {q["id"] for q in client.get("/api/project").json()["parts"]}


def test_inbox_files_are_picked_up(live):
    client, coord, store = live
    shutil.copy(DATASET / "sensor_housing_hex.stl", store.inbox / "dropped.stl")
    found = wait_for(lambda: next((q for q in client.get("/api/project").json()["parts"] if q["name"] == "dropped"), None),
                     timeout=20)
    assert found["status"] == "NEEDS_UNITS"
    assert (store.inbox / "imported" / "dropped.stl").exists()
    assert client.delete(f"/api/parts/{found['id']}").status_code == 200


def test_bad_upload_and_unbuilt_features(live):
    client, _, _ = live
    r = client.post("/api/parts", files=[("files[]", ("junk.stl", b"not an stl", "application/octet-stream"))])
    assert r.status_code == 400
    assert client.get("/api/cad/status").json()["status"] == "NOT_CONFIGURED"
    assert client.post("/api/cad/package/L-9999").status_code == 404
    assert client.get("/api/export/L-9999", params={"kind": "report_md"}).status_code == 404


def test_reports_exports_and_fusion_package(live):
    """M10: report (Markdown / HTML), placed STL ZIP and the Fusion export package — values from the layout."""
    import io
    import zipfile
    client, coord, _ = live
    lid = wait_for(lambda: best(client))
    lay = client.get(f"/api/layouts/{lid}").json()
    md = client.get(f"/api/export/{lid}", params={"kind": "report_md"})
    assert md.status_code == 200 and f"layout report — {lid}" in md.text
    assert "FUSION 360 VALIDATION: NOT CONFIGURED" in md.text and "IDEALIZED" in md.text
    assert f"{lay['metrics']['length_used_mm']:,.1f} mm" in md.text
    assert "Proof that the parts fit" in md.text and "VALID" in md.text
    h = client.get(f"/api/export/{lid}", params={"kind": "report_html"})
    assert h.status_code == 200 and h.text.startswith("<!doctype html>") and "<svg" in h.text
    assert h.text.count("<polygon") == 3 * len(lay["poses"]) + 3 * len(lay["extra_items"])
    z = zipfile.ZipFile(io.BytesIO(client.get(f"/api/export/{lid}", params={"kind": "stl_zip"}).content))
    stls = [n for n in z.namelist() if n.startswith("parts/") and n.endswith(".stl")]
    assert len(stls) == len(lay["poses"]) and f"layout_{lid}.json" in z.namelist()
    data = z.read(stls[0])
    assert len(data) == 84 + 50 * int(np.frombuffer(data[80:84], "<u4")[0])
    assert client.get(f"/api/export/{lid}", params={"kind": "nope"}).status_code == 400
    r = client.post(f"/api/cad/package/{lid}")
    assert r.status_code == 200, r.text
    pkg = r.json()
    assert pkg["status"] == "PACKAGED" and pkg["fusion360"] == "NOT_CONFIGURED"
    z = zipfile.ZipFile(io.BytesIO(client.get(pkg["download"]).content))
    names = set(z.namelist())
    assert {"assembly.json", "README.md", "fusion_import_t2s.py", f"report_{lid}.md", f"certificate_{lid}.json",
            "check_certificate.py"} <= names
    asm = json.loads(z.read("assembly.json"))
    assert asm["status"] == "FUSION 360 VALIDATION: NOT CONFIGURED" and len(asm["parts"]) == len(lay["poses"])
    assert sum(p["app_mass_kg"] for p in asm["parts"]) == pytest.approx(lay["metrics"]["mass_kg"])
    p0 = asm["parts"][0]
    pose = next(p for p in lay["poses"] if p["part_id"] == p0["id"])
    assert np.allclose(np.array(p0["canonical_to_world_4x4_mm"])[:3, 3], np.array(pose["t_um"]) / 1000)
    assert "DRAFT - NEVER RUN" in z.read("fusion_import_t2s.py").decode()
    assert client.get("/api/cad/status").json()["status"] == "NOT_CONFIGURED"


def test_detail_ladder_runs_and_feeds_the_search(live):
    """Addendum 4 on a box-shaped part: every level gives the same result, so the cheapest (F0) is chosen."""
    client, coord, store = live
    pid = next(pid for pid, e in store.entries.items() if e.name == "battery_pack")
    assert client.get(f"/api/parts/{pid}/fidelity").status_code == 404
    r = client.post("/api/fidelity/run", json={"part_ids": [pid], "budget_s": 240})
    assert r.status_code == 200 and r.json()["started"] == [pid]
    f = wait_for(lambda: (x := client.get(f"/api/parts/{pid}/fidelity")).status_code == 200 and
                 x.json()["status"] == "DONE" and x.json(), timeout=300, every=1.0)
    assert f["levels"] and f["levels"][0]["level"] == "F0"
    assert set(f["chosen"]) == {"hybrid_box", "hybrid_heightmap"}
    assert f["chosen"]["hybrid_box"] == "F0" and f["reasons"]["hybrid_box"]
    for lv in f["levels"]:
        for alg, res in lv["results"].items():
            assert res.get("skipped") or res["valid"], (lv["level"], alg, res)
    assert f["stop_reason"] in ("converged", "time_budget", "max_level")
    wait_for(lambda: coord.ctx is not None and coord.ctx.levels[pid]["hybrid_box"] == "F0", timeout=30)
    summary = client.get("/api/fidelity/summary").json()["parts"]
    assert next(p for p in summary if p["part_id"] == pid)["in_use"]["hybrid_box"] == "F0"


def _stage2_result(client, coord):
    if coord.best_id is not None and coord.archive[coord.best_id].stage == 2:
        return coord.layout_json(coord.archive[coord.best_id])
    if coord.least_id is not None:
        return coord.layout_json(coord.archive[coord.least_id])
    return None


def test_stage2_default_then_continuous_cable(live):
    client, coord, store = live
    wait_for(lambda: best(client))
    s = client.put("/api/settings", json={"stage": 2, "sliders": {"cable": 0}}).json()
    assert s["stage"] == 2
    lay = wait_for(lambda: (x := _stage2_result(client, coord)) and x["current"] and x, timeout=120)
    assert lay["stage"] == 2 and lay["label"] == "ENGINEERING-CONSTRAINED — not flight-qualified"
    assert lay["status"] in ("VALIDATED", "INFEASIBLE") and lay["validation"]["certified"]
    st2 = lay["stage2"]
    assert st2["mode"] == "default" and any(f["kind"] == "rail" for f in st2["frame"])
    if lay["status"] == "INFEASIBLE":
        assert lay["verdict"] == "NO FEASIBLE LAYOUT FOUND (not proven infeasible)" and lay["violations_engineering"]
    else:
        assert not lay["violations_engineering"] and lay["metrics"]["com_box_ok"]
        assert lay["stage2"]["insertion_order"]
    c0 = store.revs["constraint_rev"]
    client.put("/api/settings", json={"sliders": {"cable": 85}})
    assert store.revs["constraint_rev"] > c0                 # continuous-cable mode: new rules, new islands
    lay = wait_for(lambda: (x := _stage2_result(client, coord)) and x["current"] and x["stage2"]["mode"] == "continuous"
                   and x, timeout=120)
    assert lay["stage2"]["corridor"] in ("+x", "-x", "+y", "-y")
    board = lay["stage2"]["mounts"].get(next(p for p, e in store.entries.items() if e.name == "pcb_obc"))
    assert board is not None
    if board["ok"]:
        items = [i for i in lay["extra_items"] if i["kind"] == "standoff"]
        assert len(items) == 4 and all(i["mass_kg"] > 0 for i in items)
        mesh = client.get(items[0]["mesh_url"]).content
        assert np.frombuffer(mesh[:8], "<u4").tolist() == [8, 12]
    client.put("/api/settings", json={"sliders": {"cable": 0}})
    # constraint attribution (O.3): one row per relaxed family, same seed and budget
    coord.attribution_opts = {"generations": 2, "pop": 10}
    assert client.get("/api/stage2/attribution").status_code == 404
    assert client.post("/api/stage2/attribution/run").json()["status"] == "PENDING"
    try:
        att = wait_for(lambda: (x := client.get("/api/stage2/attribution")).status_code == 200 and
                       x.json()["status"] == "DONE" and x.json(), timeout=240, every=1.0)
    except AssertionError:
        raise AssertionError(f"attribution did not finish; coordinator errors: {coord.errors[-3:]}") from None
    fams = [r["relaxed"] for r in att["rows"]]
    assert fams[0] == "none" and {"clearances", "frame", "pcb_stack", "harness", "mounting", "com_box"} <= set(fams)
    assert all(r["evaluations"] > 0 for r in att["rows"])
    assert "delta_length_used_mm" in att["rows"][1]
    client.put("/api/settings", json={"stage": 1, "sliders": {"cable": 0}})
    wait_for(lambda: coord.ctx is not None and coord.ctx.stage == 1 and best(client), timeout=60)


def test_saved_stl_files_of_a_stage2_layout_lose_their_brackets_when_a_slider_moves(live):
    """V2 saved STL files: every part and every bracket with a real solid as STL in world coordinates plus the
    assembly; moving a slider deletes the bracket files and writes the assembly again from the parts alone."""
    import io
    import struct
    import zipfile
    client, coord, store = live
    assert client.get("/api/saved-stl").json()["status"] == "none"
    assert client.get("/api/saved-stl/download").status_code == 404
    e = next((x for x in list(coord.archive.values()) if x.stage == 2 and x.status in ("VALIDATED", "INFEASIBLE")), None)
    assert e is not None, "the Stage 2 test before this one leaves Stage 2 layouts in the archive"
    stage1 = next(x for x in list(coord.archive.values()) if x.stage == 1)
    assert client.post("/api/saved-stl", json={"layout_id": stage1.id}).status_code == 409
    assert client.post("/api/saved-stl", json={"layout_id": e.id}).json()["status"] == "SAVING"
    m = wait_for(lambda: (x := client.get("/api/saved-stl").json())["status"] == "complete" and not x["saving"] and x,
                 timeout=60)
    folder = Path(m["folder"])
    assert m["layout_id"] == e.id and folder == store.folder / "saved_stl"
    assert len(m["parts"]) == len(e.poses) and all((folder / r["file"]).is_file() for r in m["parts"] + m["brackets"])
    assert m["brackets"], "a Stage 2 layout has at least one bracket with a real solid (direct mount, block, …)"
    left = {r["item"] for r in m["left_out"]}           # brackets still drawn as a box: not saved
    assert all(r["item"] not in left for r in m["brackets"])
    asm = (folder / "assembly.stl").read_bytes()
    n_all = sum(r["triangles"] for r in m["parts"] + m["brackets"])
    assert struct.unpack_from("<I", asm, 80)[0] == n_all and len(asm) == 84 + 50 * n_all
    z = zipfile.ZipFile(io.BytesIO(client.get("/api/saved-stl/download").content))
    assert "assembly.stl" in z.namelist() and m["brackets"][0]["file"] in z.namelist()
    space = store.settings["sliders"]["space"]
    client.put("/api/settings", json={"sliders": {"space": space + 1}})
    try:
        m2 = wait_for(lambda: (x := client.get("/api/saved-stl").json())["status"] == "brackets_removed" and x,
                      timeout=30)
    finally:
        client.put("/api/settings", json={"sliders": {"space": space}})
    assert m2["brackets"] == [] and m2["brackets_removed"]["reason"] == f"Use Space Efficiently {space:g} → {space + 1:g}"
    assert not any((folder / r["file"]).exists() for r in m2["removed_brackets"])
    n_parts = sum(r["triangles"] for r in m2["parts"])
    assert struct.unpack_from("<I", (folder / "assembly.stl").read_bytes(), 80)[0] == n_parts


def test_size_study_runs_in_the_background(live):
    client, coord, _ = live
    assert client.get("/api/studies/size").status_code == 404
    r = client.post("/api/studies/size/run", json={"stages": [1], "seeds": 1, "budget0": 100, "max_hours": 0.02,
                                                     "workers": 1, "conv_minutes": 0.2, "min_minutes_per_combo": 0.01,
                                                     "step": 0.25, "tol": 0.05})
    assert r.status_code == 200
    d = wait_for(lambda: (x := client.get("/api/studies/size")).status_code == 200 and x.json()["status"] == "DONE"
                 and x.json(), timeout=240, every=1.0)
    assert d["stop_reason"] in ("converged", "time_limit", "proven_optimal")
    assert any(r["feasible"] for r in d["results"]) and d["max_scale"]["S1·V1"] is not None
    assert {b["kind"] for b in d["bounds"]} >= {"rigorous", "axis-aligned orientations only"}


def test_manufacturable_design_runs_and_archives_its_layout(live):
    """Addendum 1.5: own algorithm choice, mounts and brackets, exact bracket checks, hardware list and exports."""
    client, coord, _ = live
    wait_for(lambda: best(client))
    assert client.get("/api/mfg").status_code == 404
    r = client.post("/api/mfg/run", json={"budget_s": 15})
    assert r.status_code == 200 and r.json()["status"] == "RUNNING"
    assert client.post("/api/mfg/run", json={"budget_s": 15}).status_code == 409
    try:
        res = wait_for(lambda: (x := client.get("/api/mfg")).status_code == 200 and x.json()["status"] in ("DONE", "ERROR")
                       and x.json(), timeout=420, every=1.0)
    except AssertionError:
        raise AssertionError(f"mfg did not finish; coordinator errors: {coord.errors[-3:]}") from None
    assert res["status"] == "DONE", res
    assert res["label"].startswith("manufacturing concept") and res["layout_id"]
    assert res["algorithm"]["id"] == "hybrid_box" and res["algorithm"]["reason"]
    assert res["items"] and all(i["cost_rel"] >= 0 and i["mass_kg"] > 0 for i in res["items"])
    assert res["total_cost_rel"] == pytest.approx(sum(i["cost_rel"] for i in res["items"]))
    assert len(res["validation"]["brackets"]) == sum(i["process"] != "standoff" for i in res["items"])
    lay = client.get(f"/api/layouts/{res['layout_id']}").json()
    assert lay["stage"] == 2 and lay["mode"] == "manufacturable"
    assert lay["validation"]["certified"] == res["validation"]["parts_valid"]
    assert res["feasible"] == (lay["status"] == "VALIDATED") and res["layout_status"] == lay["status"]
    if res["feasible"]:
        assert not res["violations"] and res["verdict"] is None
    elif lay["validation"]["certified"]:
        assert lay["status"] == "INFEASIBLE" and res["violations"]
    assert [i["process"] for i in lay["extra_items"]] == [i["process"] for i in res["items"]]
    assert lay["metrics"]["hardware_mass_kg"] == pytest.approx(res["hardware_mass_kg"])
    assert lay["metrics"]["hardware_cost_rel"] == pytest.approx(res["total_cost_rel"])
    for it in lay["extra_items"]:
        mesh = client.get(it["mesh_url"]).content
        nv, nf = np.frombuffer(mesh[:8], "<u4")
        assert nf > 0 and len(mesh) == 8 + 12 * int(nv) + 12 * int(nf)
    csv = client.get(res["exports"][0]["url"])
    assert csv.status_code == 200 and "relative_cost" in csv.text and "not a quote" in csv.text
    for x in res["exports"][1:]:
        stl = client.get(x["url"])
        assert stl.status_code == 200 and len(stl.content) > 84
    for it in (i for i in res["items"] if i["process"] == "metal_am"):
        assert any(x["url"].endswith(f"bracket_AM_{it['for_part']}.stl") for x in res["exports"])
        assert any(row["item_id"] == it["id"] for row in res["am_rules"])
    assert client.get("/api/mfg/download/layout.pkl").status_code == 404
    assert client.get("/api/mfg/download/..%2F..%2Fsettings.json").status_code == 404


def test_free_rotation_experiment_endpoint(live):
    """Research experiment, reported separately: starts from the shortest validated Stage 1 layout."""
    client, coord, _ = live
    wait_for(lambda: best(client))
    assert client.get("/api/experiments/free-rotation").status_code == 404
    r = client.post("/api/experiments/free-rotation/run", json={"budget_s": 8})
    assert r.status_code == 200, r.text
    start = r.json()["start_layout_id"]
    assert coord.archive[start].stage == 1 and coord.archive[start].status in ("VALIDATED", "FINAL")
    d = wait_for(lambda: (x := client.get("/api/experiments/free-rotation")).status_code == 200 and
                 x.json()["status"] in ("DONE", "ERROR") and x.json(), timeout=240, every=1.0)
    assert d["status"] == "DONE" and d["start_valid"] and d["valid"], d
    assert d["start_layout_id"] == start and d["improvement_mm"] >= 0
    assert d["start_length_mm"] == pytest.approx(coord.archive[start].geo["length_used_mm"], abs=1e-6)
    assert "not used by the main search" in d["label"]


def test_selector_endpoints(live):
    client, coord, _ = live
    wait_for(lambda: best(client))
    s = client.get("/api/selector").json()
    assert s["algorithm"]["id"] in ("hybrid_box", "hybrid_heightmap", "portfolio")
    assert "default rule" in s["reasons"][0] and s["islands"]
    sw = client.get("/api/selector/sweep", params={"slider": "space"}).json()
    assert len(sw["choices"]) == 101 and set(sw["choices"]) <= set(sw["legend"])
    m = client.get("/api/selector/map", params={"x": "space", "y": "balance", "n": 5}).json()
    assert len(m["grid"]) == 5 and len(m["grid"][0]) == 5
    assert client.get("/api/selector/sweep", params={"slider": "nope"}).status_code == 400
    lay = client.get(f"/api/layouts/{best(client)}").json()
    assert lay["algorithm"]["search"] in ("brkga", "lahc", "nsga2", "cp-sat")
    im = client.get("/api/ideamap").json()
    ids = {n["id"] for n in im["nodes"]}
    assert {"parts", "choice", "layout", "proof", "stage"} <= ids
    assert all(e["from"] in ids and e["to"] in ids for e in im["edges"])
    assert any(e["to"] == "choice" and e["label"] and "weight" in e["label"] for e in im["edges"])
