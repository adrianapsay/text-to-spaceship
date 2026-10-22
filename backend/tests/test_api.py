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
    coord.auto_ladder = False                       # the ladder has its own (shortened) test below
    coord.ladder_opts = {"generations": 2, "pop": 12, "fr_samples": 20}
    app = create_app(coord)
    with TestClient(app) as client:
        yield client, coord, store


def best(client):
    r = client.get("/api/layouts", params={"limit": 1}).json()
    return r["best_id"]


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
    assert client.post("/api/cad/package/L-0001").status_code == 501


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
    att = wait_for(lambda: (x := client.get("/api/stage2/attribution")).status_code == 200 and
                   x.json()["status"] == "DONE" and x.json(), timeout=240, every=1.0)
    fams = [r["relaxed"] for r in att["rows"]]
    assert fams[0] == "none" and {"clearances", "frame", "pcb_stack", "harness", "mounting", "com_box"} <= set(fams)
    assert all(r["evaluations"] > 0 for r in att["rows"])
    assert "delta_length_used_mm" in att["rows"][1]
    client.put("/api/settings", json={"stage": 1, "sliders": {"cable": 0}})
    wait_for(lambda: coord.ctx is not None and coord.ctx.stage == 1 and best(client), timeout=60)


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
    assert lay["algorithm"]["search"] in ("brkga", "lahc", "nsga2") and lay["algorithm"]["decoder"] in ("box", "heightmap")
