"""V3 CubeSat Builder, M4: CAD import (STEP → millimetre STL through OpenCASCADE in its own process), the checks on
every import, safe .zip handling, simplified shapes labelled by origin, and the CAD endpoints."""
import io
import math
import subprocess
import sys
import zipfile

import pytest
import trimesh
from fastapi import FastAPI
from fastapi.testclient import TestClient

from t2s.api.builder import router
from t2s.builder.cad import ORIGINS, CadError, CadStore, safe_extract
from t2s.builder.store import BuilderStore

BOARD = (95.89, 90.17, 16.2)             # STARBUCK-NANO's published size (mm)
HOLE_R = 5.0


def make_step(path, surfaces_only=False):
    """A STEP file written by gmsh/OpenCASCADE in a separate process (a board with a hole, or a bare rectangle)."""
    body = ("r = gmsh.model.occ.addRectangle(0, 0, 0, 50, 40)" if surfaces_only else
            f"b = gmsh.model.occ.addBox(0, 0, 0, {BOARD[0]}, {BOARD[1]}, {BOARD[2]})\n"
            f"c = gmsh.model.occ.addCylinder(47.9, 45.0, -1, 0, 0, 20, {HOLE_R})\n"
            "gmsh.model.occ.cut([(3, b)], [(3, c)])")
    code = ("import gmsh\ngmsh.initialize(interruptible=False)\ngmsh.option.setNumber('General.Terminal', 0)\n"
            f"{body}\ngmsh.model.occ.synchronize()\ngmsh.write(r'{path}')\ngmsh.finalize()\n")
    subprocess.run([sys.executable, "-c", code], check=True, capture_output=True, timeout=120)
    return path


@pytest.fixture(scope="module")
def step_file(tmp_path_factory):
    return make_step(tmp_path_factory.mktemp("step") / "board.step")


def test_a_step_file_round_trips_to_a_millimetre_stl(tmp_path, step_file):
    store = CadStore(tmp_path / "cad")
    e = store.import_file("aac-clyde-space-starbuck-nano", "board.step", step_file.read_bytes(), "manufacturer",
                          "https://example.org/board")
    assert e["origin"] == "manufacturer" and e["origin_text"] == ORIGINS["manufacturer"]
    assert e["ok"] and {c["name"] for c in e["checks"]} >= {"opens", "solids", "watertight", "volume", "size"}
    exact = BOARD[0] * BOARD[1] * BOARD[2] - math.pi * HOLE_R ** 2 * BOARD[2]
    assert e["volume_mm3"] == pytest.approx(exact, rel=0.005)
    assert sorted(e["extents_mm"]) == pytest.approx(sorted(BOARD), abs=1e-3)
    m = trimesh.load(store.stl_path("aac-clyde-space-starbuck-nano"))
    assert m.is_watertight
    assert (m.bounds[0] + m.bounds[1]) == pytest.approx([0, 0, 0], abs=1e-6)        # centred; the shift is kept
    assert e["shift_mm"] == pytest.approx([-BOARD[0] / 2, -BOARD[1] / 2, -BOARD[2] / 2], abs=1e-3)
    assert (tmp_path / "cad" / e["source_file"]).read_bytes() == step_file.read_bytes()
    assert store.manifest()["aac-clyde-space-starbuck-nano"]["sha256"] == e["sha256"]


def test_an_stl_without_units_is_matched_against_the_catalog(tmp_path):
    store = CadStore(tmp_path / "cad")
    box = trimesh.creation.box(extents=[x / 1000 for x in BOARD])                    # drawn in metres
    e = store.import_file("aac-clyde-space-starbuck-nano", "board.stl", box.export(file_type="stl"))
    assert e["scale"] == 1000.0 and e["units"].startswith("m (matched")
    assert sorted(e["extents_mm"]) == pytest.approx(sorted(BOARD), rel=1e-6)
    odd = trimesh.creation.box(extents=[3, 4, 5])
    e = store.import_file("aac-clyde-space-starbuck-nano", "odd.stl", odd.export(file_type="stl"))
    assert e["scale"] == 1.0 and "ASSUMED" in e["units"]
    assert next(c for c in e["checks"] if c["name"] == "size")["ok"] is False and not e["ok"]


def test_surfaces_only_and_unreadable_files_are_reported(tmp_path):
    store = CadStore(tmp_path / "cad")
    flat = make_step(tmp_path / "flat.step", surfaces_only=True)
    e = store.import_file("aac-clyde-space-starbuck-nano", "flat.step", flat.read_bytes())
    assert next(c for c in e["checks"] if c["name"] == "solids")["ok"] is False and not e["ok"]
    with pytest.raises(CadError, match="could not read|no geometry"):
        store.import_file("aac-clyde-space-starbuck-nano", "junk.step", b"this is not a STEP file")
    with pytest.raises(CadError, match="send STEP"):
        store.import_file("aac-clyde-space-starbuck-nano", "notes.txt", b"hello")
    with pytest.raises(CadError, match="maker's CAD or your reconstruction"):
        store.import_file("aac-clyde-space-starbuck-nano", "x.step", b"x", origin="bbox")
    with pytest.raises(KeyError):
        store.import_file("no-such-part", "x.step", b"x")


def test_zip_archives_are_unpacked_safely(tmp_path, step_file):
    store = CadStore(tmp_path / "cad")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("readme.txt", "CAD model")
        z.writestr("model/board.step", step_file.read_bytes())
    e = store.import_file("aac-clyde-space-starbuck-nano", "board.zip", buf.getvalue())
    assert e["ok"] and e["source_name"] == "board.zip"
    for bad in ("../evil.step", "/abs/evil.step", "..\\evil.step", "C:/evil.step"):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr(bad, "x")
        (tmp_path / "bad.zip").write_bytes(buf.getvalue())
        out = tmp_path / f"out{abs(hash(bad))}"
        out.mkdir()
        with pytest.raises(CadError, match="unsafe path"):
            safe_extract(tmp_path / "bad.zip", out)


def test_simplified_shapes_say_what_they_are(tmp_path):
    store = CadStore(tmp_path / "cad")
    b = store.simplified("bct-xact-15")
    assert b["origin"] == "bbox" and b["extents_mm"] == [100.0, 100.0, 50.0]
    assert trimesh.load(store.stl_path("bct-xact-15")).is_watertight
    p = store.simplified("bct-rwp015")                                               # its size is not published
    assert p["origin"] == "placeholder" and p["extents_mm"] == [20.0, 20.0, 20.0]
    assert store.geometry("bct-xact-15")["origin"] == "bbox"
    store.delete("bct-xact-15")
    assert store.entry("bct-xact-15") is None
    with pytest.raises(KeyError):
        store.simplified("no-such-part")


def test_the_cad_endpoints(tmp_path, step_file):
    app = FastAPI()
    app.state.builder = BuilderStore(tmp_path)
    app.include_router(router)
    c = TestClient(app)
    r = c.post("/api/builder/cad/aac-clyde-space-starbuck-nano/import",
               files={"file": ("board.step", step_file.read_bytes(), "application/step")},
               data={"origin": "manufacturer"})
    assert r.status_code == 200 and r.json()["ok"]
    bad = c.post("/api/builder/cad/aac-clyde-space-starbuck-nano/import",
                 files={"file": ("junk.step", b"nope", "application/step")})
    assert bad.status_code == 400
    assert c.post("/api/builder/cad/no-such-part/simplified").status_code == 404
    assert c.post("/api/builder/cad/bct-xact-15/simplified").json()["origin"] == "bbox"
    listing = c.get("/api/builder/cad").json()
    assert set(listing["items"]) == {"aac-clyde-space-starbuck-nano", "bct-xact-15"}
    assert any(o["available"] == "public" and o["url"] for o in listing["offered"])
    stl = c.get("/api/builder/cad/bct-xact-15/stl")
    assert stl.status_code == 200 and len(stl.content) > 80
    assert c.delete("/api/builder/cad/bct-xact-15").json()["ok"]
    assert c.get("/api/builder/cad/bct-xact-15/stl").status_code == 404
