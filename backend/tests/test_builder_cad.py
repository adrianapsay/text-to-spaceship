"""V3 CubeSat Builder, M4: CAD import (STEP → millimetre STL through OpenCASCADE in its own process), the checks on
every import, safe .zip handling (archives of archives too), which model of an archive is used, the memory guard,
simplified shapes labelled by origin, and the CAD endpoints."""
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
from t2s.builder.cad import ARCHIVE, ORIGINS, CadError, CadStore, pick_model, safe_extract
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


def make_box_step(path, dims):
    code = ("import gmsh\ngmsh.initialize(interruptible=False)\ngmsh.option.setNumber('General.Terminal', 0)\n"
            f"gmsh.model.occ.addBox(0, 0, 0, {dims[0]}, {dims[1]}, {dims[2]})\ngmsh.model.occ.synchronize()\n"
            f"gmsh.write(r'{path}')\ngmsh.finalize()\n")
    subprocess.run([sys.executable, "-c", code], check=True, capture_output=True, timeout=120)
    return path


def zipped(files: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in files.items():
            z.writestr(name, data)
    return buf.getvalue()


@pytest.fixture(scope="module")
def step_file(tmp_path_factory):
    return make_step(tmp_path_factory.mktemp("step") / "board.step")


@pytest.fixture(autouse=True)
def plenty_of_memory(monkeypatch):
    """These conversions are tiny: the memory guard has its own test and is not tripped here by this computer's load."""
    import t2s.gd.layouts as gl
    monkeypatch.setattr(gl, "available_mb", lambda: gl.MEM_RESERVE_MB + 4096.0)


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
    # the worker's own memory, not only the launcher's (a venv's python.exe on Windows runs the interpreter as a child)
    assert e["converter_peak_mb"] > 10 and e["archive_models"] == [] and e["archive_member"] is None
    assert next(c for c in e["checks"] if c["name"] == "repair")["detail"].startswith("none needed")
    assert not (tmp_path / "cad" / "aac-clyde-space-starbuck-nano" / "incoming").exists()


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


def test_an_assembly_keeps_its_solids(tmp_path):
    """Two solids that touch, as in a maker's assembly, are meshed as they are: OpenCASCADE's sewing used to merge
    such solids into loose shells (a maker's sun sensor lost all three)."""
    path = tmp_path / "pair.step"
    code = ("import gmsh\ngmsh.initialize(interruptible=False)\ngmsh.option.setNumber('General.Terminal', 0)\n"
            "gmsh.model.occ.addBox(0, 0, 0, 10, 10, 10)\ngmsh.model.occ.addBox(10, 0, 0, 10, 10, 10)\n"
            f"gmsh.model.occ.synchronize()\ngmsh.write(r'{path}')\ngmsh.finalize()\n")
    subprocess.run([sys.executable, "-c", code], check=True, capture_output=True, timeout=120)
    e = CadStore(tmp_path / "cad").import_file("aac-clyde-space-ss200", "pair.step", path.read_bytes())
    checks = {c["name"]: c for c in e["checks"]}
    assert checks["solids"]["ok"] and checks["solids"]["detail"].startswith("2 solid(s)")
    assert checks["repair"]["detail"].startswith("none needed")
    assert checks["volume"]["ok"] and checks["watertight"]["ok"] is not False
    assert e["volume_mm3"] == pytest.approx(2000.0, rel=1e-3)


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


def test_an_archive_uses_the_model_named_for_the_part():
    # the makers' own archives (AAC Clyde Space, Pumpkin): one zip per product family, several variants inside
    optimus = [("Optimus CAD models/Optimus-80-3D-01-02687 Rev2_defeature.STEP", 71_510_000),
               ("Optimus CAD models/Optimus-40-3D-01-02686_RevA_defeature.STEP", 40_640_000),
               ("Optimus CAD models/Optimus-30-3D-01-02685 RevC_defeature.STEP", 30_990_000)]
    i, ch = pick_model(optimus, "OPTIMUS-40")
    assert i == 1 and ch["ok"] is True and "matches OPTIMUS-40" in ch["detail"]
    assert "also holds Optimus-80-3D-01-02687 Rev2_defeature.STEP" in ch["detail"]
    starbuck = [("Starbuck-Nano CAD models/Starbuck-Nano-PLUS-3D-01-02453RevC_defeature.STEP", 28_910_000),
                ("Starbuck-Nano CAD models/Starbuck-Nano-3D-25-02452RevF_18_10_22_defeature_2.STEP", 22_030_000)]
    i, ch = pick_model(starbuck, "STARBUCK-NANO")
    assert i == 1 and ch["ok"] is True                                  # not the larger PLUS variant
    kryten = [("Kryten OBC CAD models/3D-25-02927 RevJ Assembly_defeature.STEP", 20_040_000),
              ("Kryten OBC CAD models/3D-25-02929 RevJ Assembly_defeature.STEP", 18_460_000)]
    i, ch = pick_model(kryten, "KRYTEN-M3")
    assert i == 0 and ch["ok"] is None and "do not say which model" in ch["detail"]
    i, ch = pick_model([("IADCS420-ASM-ST-1.0-defeatured-1.0_defeature.STEP", 1)], "iADCS400")
    assert i == 0 and ch["ok"] is None and "does not name iADCS400" in ch["detail"]
    i, ch = pick_model([("710-01552-F Battery Module 2 (BM2).step", 1)],
                       "Intelligent Protected Lithium Battery Module with SoC Reporting (BM 2)")
    assert ch["ok"] is True                                             # its bracketed name, BM 2
    i, _ = pick_model([("a/board.stl", 999), ("a/board.step", 1)], "STARBUCK-NANO")
    assert i == 1                                                       # STEP before STL
    i, ch = pick_model(optimus, "OPTIMUS-40", member="Optimus-30-3D-01-02685 RevC_defeature.STEP")
    assert i == 2 and ch["ok"] is True and "chosen" in ch["detail"]
    with pytest.raises(CadError, match="no single model named"):
        pick_model(optimus, "OPTIMUS-40", member="Optimus-60.STEP")


def test_a_zip_of_zips_is_unpacked_and_another_model_can_be_chosen(tmp_path, step_file):
    plus = make_box_step(tmp_path / "plus.step", (95.89, 90.17, 30.0))
    archive = zipped({"Starbuck/Starbuck-Nano-PLUS.zip": zipped({"Starbuck-Nano-PLUS-01.step": plus.read_bytes()}),
                      "Starbuck/Starbuck-Nano.zip": zipped({"Starbuck-Nano-02.step": step_file.read_bytes()}),
                      "Starbuck/readme.txt": "two variants"})
    store = CadStore(tmp_path / "cad")
    cid = "aac-clyde-space-starbuck-nano"
    e = store.import_file(cid, "starbuck.zip", archive)
    assert e["archive_models"] == ["Starbuck/Starbuck-Nano-PLUS.zip/Starbuck-Nano-PLUS-01.step",
                                   "Starbuck/Starbuck-Nano.zip/Starbuck-Nano-02.step"]
    assert e["archive_member"] == "Starbuck/Starbuck-Nano.zip/Starbuck-Nano-02.step"
    assert e["checks"][0]["name"] == "model" and e["checks"][0]["ok"] is True
    assert sorted(e["extents_mm"]) == pytest.approx(sorted(BOARD), abs=1e-3) and e["ok"]
    d = tmp_path / "cad" / cid
    assert (d / ARCHIVE).read_bytes() == archive and not (d / "incoming").exists()
    e2 = store.choose_model(cid, "Starbuck-Nano-PLUS-01.step")
    assert e2["archive_member"].endswith("Starbuck-Nano-PLUS-01.step")
    assert sorted(e2["extents_mm"]) == pytest.approx([30.0, 90.17, 95.89], abs=1e-3)
    assert next(c for c in e2["checks"] if c["name"] == "size")["ok"] is False        # PLUS is not the catalog's size
    with pytest.raises(CadError, match="no single model named"):
        store.choose_model(cid, "Starbuck-Nano-MINI.step")
    store.import_file(cid, "board.step", step_file.read_bytes())                       # one model: nothing kept
    assert not (d / ARCHIVE).exists() and sorted(p.name for p in d.glob("source.*")) == ["source.step"]
    with pytest.raises(CadError, match="no archive holding several models"):
        store.choose_model(cid, "Starbuck-Nano-PLUS-01.step")


def test_the_converter_keeps_the_memory_reserve_free(tmp_path, step_file, monkeypatch):
    import t2s.gd.layouts as gl
    store = CadStore(tmp_path / "cad")
    cid = "aac-clyde-space-starbuck-nano"
    monkeypatch.setattr(gl, "available_mb", lambda: gl.MEM_RESERVE_MB - 1.0)              # short before it starts
    with pytest.raises(CadError, match=r"not started: \d+ MB of memory available and \d+ MB must stay free"):
        store.import_file(cid, "board.step", step_file.read_bytes())
    calls = []

    def falling():                                    # enough to start, then the machine runs short while it works
        calls.append(1)
        return gl.MEM_RESERVE_MB + (100.0 if len(calls) == 1 else -1.0)

    monkeypatch.setattr(gl, "available_mb", falling)
    with pytest.raises(CadError, match=r"stopped to keep \d+ MB of memory free"):
        store.import_file(cid, "board.step", step_file.read_bytes())
    assert store.entry(cid) is None and not (tmp_path / "cad" / cid / "incoming").exists()


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
    two = zipped({"a/Starbuck-Nano-PLUS.step": step_file.read_bytes(), "a/Starbuck-Nano.step": step_file.read_bytes()})
    r = c.post("/api/builder/cad/aac-clyde-space-starbuck-nano/import",
               files={"file": ("sb.zip", two, "application/zip")}, data={"member": "Starbuck-Nano-PLUS.step"})
    assert r.status_code == 200 and r.json()["archive_member"] == "a/Starbuck-Nano-PLUS.step"
    r = c.post("/api/builder/cad/aac-clyde-space-starbuck-nano/model", json={"member": "a/Starbuck-Nano.step"})
    assert r.status_code == 200 and r.json()["archive_member"] == "a/Starbuck-Nano.step"
    assert c.post("/api/builder/cad/aac-clyde-space-starbuck-nano/model", json={"member": "x.step"}).status_code == 400
    assert c.post("/api/builder/cad/aac-clyde-space-starbuck-nano/model", json={}).status_code == 400
    assert c.post("/api/builder/cad/no-such-part/model", json={"member": "x.step"}).status_code == 404
