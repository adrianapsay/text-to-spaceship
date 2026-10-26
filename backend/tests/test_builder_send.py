"""V3 CubeSat Builder, M6: Send to Optimization writes a new optimiser project (never overwriting one) with the parts'
masses, subsystems and the CubeSat size, states what the optimiser does not enforce, and the app switches between
projects and back."""
import json

import pytest
from fastapi.testclient import TestClient

from t2s.api.app import create_app
from t2s.builder import catalog as K
from t2s.builder import engine as E
from t2s.builder import questions as Q
from t2s.builder.cad import CadStore
from t2s.builder.intake import apply_statement
from t2s.builder.model import new_design
from t2s.builder.send import SendError, send
from t2s.service.coordinator import Coordinator
from t2s.service.project import ProjectStore

CALIFORNIA = "I want to build a satellite that photographs California from orbit."


def california():
    d, _ = apply_statement(new_design("California imager"), CALIFORNIA)
    Q.accept_defaults(d)
    return d, E.analyse(d)


def test_send_writes_a_new_project_and_never_overwrites_one(tmp_path):
    d, a = california()
    cad = CadStore(tmp_path / "cad")
    root = tmp_path / "projects"
    out = send(d, a, cad, root)
    assert out["project"] == "builder-california-imager" and out["size"] == "6U"
    store = ProjectStore(out["project"], root=root)
    assert store.settings["form_factor"] == "6U" and store.settings["launch_environment"] == "gevs"
    internal = [it for p in a["picks"].values() if p["place"] == "internal" for it in p["items"]]
    assert len(store.entries) == sum(it["qty"] for it in internal)
    by_name = {e.name: e for e in store.entries.values()}
    cam = by_name["Simera Sense MultiScape100"]
    assert cam.mass_override_kg == K.mass_kg(K.by_id("simera-sense-multiscape100"))
    assert cam.subsystem_override == "payload" and cam.units == "mm" and cam.units_confirmed and cam.tags == []
    meta = json.loads((store.folder / "builder.json").read_text(encoding="utf-8"))
    assert meta["design_id"] == d["id"] and meta["inputs_hash"] == a["inputs_hash"]
    assert {p["origin"] for p in meta["parts"]} == {"bbox"}                 # no CAD imported: simplified, and said so
    assert any("not packed" in u for u in meta["unenforced"])
    assert any("Fields of view" in u for u in meta["unenforced"])
    assert {n["slot"] for n in meta["not_packed"]} >= {"solar", "antenna_ttc"}
    assert "structure" not in {n["slot"] for n in meta["not_packed"]}         # the frame is the optimiser's own
    assert meta["frame"][0]["slot"] == "structure" and any("own frame model" in u for u in meta["unenforced"])
    assert any("Stage 2" in w for w in meta["warnings"])                    # the 98.3 mm camera
    again = send(d, a, cad, root)
    assert again["project"] == "builder-california-imager-2"                 # a second send never overwrites
    assert len(ProjectStore(out["project"], root=root).entries) == len(store.entries)


def test_sizes_the_optimiser_cannot_pack_are_refused(tmp_path):
    d, _ = california()
    d["size_u"] = 1.5
    a = E.analyse(d)
    with pytest.raises(SendError, match="3U, 6U and 12U"):
        send(d, a, CadStore(tmp_path / "cad"), tmp_path / "projects")


def test_a_part_as_wide_as_the_envelope_is_refused_before_sending(tmp_path):
    from t2s.builder.analysis import structure as S
    assert S.packing_fit((100, 100, 250), 6) == "too_big"          # equal to the 6U's 100 mm: never strictly inside
    assert S.packing_fit((98.3, 98.3, 176.5), 6) == "stage1"
    assert S.packing_fit((100, 100, 250), 12) == "stage2"
    d, _ = california()
    d["selections"] = {"payload": {"component": "dragonfly-aerospace-caiman", "qty": 1}}
    a = E.analyse(d)
    assert a["size_label"] == "6U"
    with pytest.raises(SendError, match="cannot place Dragonfly Aerospace Caiman"):
        send(d, a, CadStore(tmp_path / "cad"), tmp_path / "projects")
    assert not (tmp_path / "projects").exists() or not any((tmp_path / "projects").iterdir())   # nothing written
    d["size_u"] = 12
    out = send(d, E.analyse(d), CadStore(tmp_path / "cad"), tmp_path / "projects")
    assert out["size"] == "12U"


def test_imported_cad_is_what_gets_sent(tmp_path):
    import trimesh
    d, a = california()
    cad = CadStore(tmp_path / "cad")
    box = trimesh.creation.box(extents=[95.89, 90.17, 5.51])                  # KRYTEN-M3's published size
    cad.import_file("aac-clyde-space-kryten-m3", "kryten.stl", box.export(file_type="stl"), "reconstructed")
    out = send(d, a, cad, tmp_path / "projects")
    origins = {p["catalog_id"]: p["origin"] for p in out["parts"]}
    assert origins["aac-clyde-space-kryten-m3"] == "reconstructed"
    assert origins["simera-sense-multiscape100"] == "bbox"


@pytest.fixture()
def app_client(tmp_path):
    root = tmp_path / "projects"
    store = ProjectStore("start", root=root)
    coord = Coordinator(store, workers=False, auto_start=False)
    coord.use_cpsat = False
    coord.auto_ladder = False
    app = create_app(coord, builder_root=tmp_path / "builder")
    with TestClient(app) as client:
        yield client, app


def test_send_switches_the_app_and_the_user_can_switch_back(app_client):
    client, app = app_client
    did = client.post("/api/builder/designs", json={"statement": CALIFORNIA}).json()["design"]["id"]
    client.post(f"/api/builder/designs/{did}/defaults")
    r = client.post(f"/api/builder/designs/{did}/send", json={"switch": True}).json()
    assert r["switched"] and r["previous"] == "start"
    assert app.state.coord.store.name == r["project"]
    assert client.get("/api/project").json()["parts"]                         # the optimiser runs on the new project
    listing = client.get("/api/projects").json()
    assert listing["current"] == r["project"]
    sent = next(p for p in listing["projects"] if p["name"] == r["project"])
    assert sent["builder"]["design_id"] == did and sent["form_factor"] == "6U"
    assert client.get(f"/api/builder/designs/{did}").json()["design"]["sent"][0]["project"] == r["project"]
    back = client.post("/api/projects/switch", json={"name": "start"}).json()
    assert back["switched"] and app.state.coord.store.name == "start"
    assert client.post("/api/projects/switch", json={"name": "nope"}).status_code == 404
    assert client.post("/api/projects/switch", json={"name": "../start"}).status_code == 404
