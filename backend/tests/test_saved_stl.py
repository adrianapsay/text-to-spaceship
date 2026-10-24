"""V2 saved STL files (report/saved_stl.py and the coordinator's rules): the designed assembly is written as STL files,
a slider move deletes the bracket files from it, and the set follows the best layout once its brackets are designed."""
import io
import struct
import zipfile
from types import SimpleNamespace

import numpy as np

from t2s.geometry.stl_io import stl_bytes
from t2s.report.saved_stl import read_manifest, remove_brackets, triangles, write_set, zip_set
from t2s.service.coordinator import Coordinator, settings_change_text

CUBE_F = np.array([[0, 2, 1], [0, 3, 2], [4, 5, 6], [4, 6, 7], [0, 1, 5], [0, 5, 4], [1, 2, 6], [1, 6, 5], [2, 3, 7],
                   [2, 7, 6], [3, 0, 4], [3, 4, 7]])


def cube(x0: float) -> bytes:
    v = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0], [0, 0, 1], [1, 0, 1], [1, 1, 1], [0, 1, 1]], float)
    return stl_bytes(v + x0, CUBE_F, f"cube {x0}")


def n_tri(data: bytes) -> int:
    n = struct.unpack_from("<I", data, 80)[0]
    assert len(data) == 84 + 50 * n                   # a well-formed binary STL
    return n


def saved(folder):
    parts = [("p1_box", cube(0), {"part_id": "p1", "part": "box"}), ("p2_tank", cube(5), {"part_id": "p2", "part": "tank"})]
    brs = [("AM_box_br0", cube(2), {"part_id": "p1", "part": "box", "kind": "metal_am", "designed": True, "passed": True})]
    m = write_set(folder, "L-0007", parts, brs, {"settings": {"sliders": {"balance": 36.0}},
                                                  "left_out": [{"part_id": "p2", "part": "tank", "kind": "cradle",
                                                                "why": "not designed yet (reserved box)"}]})
    return parts, brs, m


def test_the_saved_set_is_every_part_and_bracket_and_their_assembly(tmp_path):
    parts, brs, m = saved(tmp_path)
    asm = (tmp_path / "assembly.stl").read_bytes()
    assert n_tri(asm) == 36 and triangles(asm) == b"".join(triangles(d) for _, d, _ in parts + brs)
    assert m["status"] == "complete" and m["layout_id"] == "L-0007" and m["brackets_removed"] is None
    assert [r["file"] for r in m["parts"]] == ["parts/p1_box.stl", "parts/p2_tank.stl"]
    assert [r["file"] for r in m["brackets"]] == ["brackets/AM_box_br0.stl"] and m["brackets"][0]["triangles"] == 12
    assert read_manifest(tmp_path) == m
    readme = (tmp_path / "README.txt").read_text(encoding="utf-8")
    assert "assembly.stl" in readme and "tank: cradle - not designed yet" in readme
    names = zipfile.ZipFile(io.BytesIO(zip_set(tmp_path))).namelist()
    assert {"assembly.stl", "manifest.json", "README.txt", "parts/p1_box.stl", "brackets/AM_box_br0.stl"} <= set(names)


def test_a_slider_move_deletes_the_bracket_files_and_the_assembly_keeps_the_parts(tmp_path):
    parts, _, _ = saved(tmp_path)
    m = remove_brackets(tmp_path, "Balance the Spacecraft 36 → 40")
    assert m["status"] == "brackets_removed" and m["brackets"] == [] and m["brackets_removed"]["reason"].startswith("Bal")
    assert [r["part_id"] for r in m["removed_brackets"]] == ["p1"]
    assert not (tmp_path / "brackets").exists()
    asm = (tmp_path / "assembly.stl").read_bytes()
    assert n_tri(asm) == 24 and triangles(asm) == b"".join(triangles(d) for _, d, _ in parts)
    assert read_manifest(tmp_path) == m
    assert remove_brackets(tmp_path, "again") is None             # nothing left to remove
    assert remove_brackets(tmp_path / "none", "no set") is None   # no saved set at all


def test_what_moved_is_named_like_the_sliders():
    b = {"sliders": {"balance": 36.0, "space": 25.0}, "part_scale_pct": 54, "form_factor": "3U", "stage": 2}
    a = {"sliders": {"balance": 40.0, "space": 25.0}, "part_scale_pct": 60.0, "form_factor": "6U", "stage": 2}
    assert settings_change_text(b, a) == "Balance the Spacecraft 36 → 40, CubeSat size 3U → 6U, Part size 54 → 60"
    assert settings_change_text(a, a) == "settings changed"


def _coord(tmp_path, best="L-1", designed=True):
    c = Coordinator.__new__(Coordinator)               # the saved-STL rules only: no workers, no event loop
    c.store = SimpleNamespace(folder=tmp_path, settings={"auto_design_brackets": True, "stage": 2, "form_factor": "3U",
                                                         "part_scale_pct": 54, "sliders": {"balance": 36.0}})
    c.val_queue, c.val_pending, c.ladders, c.workers = [], {}, {}, []
    c.run_status = "PAUSED"
    c.archive = {"L-1": SimpleNamespace(id="L-1", stage=2, status="VALIDATED", part_scale=0.54, meta={
        "brackets": [{"pid": "p1", "kind": "metal_am"}],
        "bracket_designs": {"p1": {"mass_kg": 0.01, "passed": True, "environment": "gevs", "material": "AlSi10Mg"}}
        if designed else {}})}
    c.best_id = best
    c.saves, c.started, c.sent = [], [], []
    c._stl_items = lambda e: ([("p1_box", cube(0), {"part_id": "p1"})],
                              [("AM_box_br0", cube(2), {"part_id": "p1", "kind": "metal_am"})], [])
    c.start_bracket_design = lambda lid, pids=None, overrides=None: c.started.append(lid)
    c.broadcast = lambda kind, payload: c.sent.append((kind, payload))
    c._error = lambda msg: (_ for _ in ()).throw(AssertionError(msg))
    return c


def test_the_saved_set_follows_the_best_layout_once_its_brackets_are_designed(tmp_path):
    c = _coord(tmp_path)
    c._maybe_auto_design()                             # paused on a designed best: its STL files are written
    m = read_manifest(tmp_path / "saved_stl")
    assert m["layout_id"] == "L-1" and m["status"] == "complete" and m["settings"] == c._settings_view()
    assert c.sent[-1][0] == "saved_stl.updated" and c.sent[-1][1]["saved_stl"]["layout_id"] == "L-1"
    n = len(c.sent)
    c._maybe_auto_design()                             # already saved at these settings: not written again
    assert len(c.sent) == n and c.started == []
    undesigned = _coord(tmp_path / "u", designed=False)
    undesigned._maybe_auto_design()                    # not designed yet: the design run first, no STL files
    assert undesigned.started == ["L-1"] and read_manifest(tmp_path / "u" / "saved_stl") is None


def test_after_a_slider_move_the_brackets_go_and_come_back_once_it_has_settled(tmp_path):
    c = _coord(tmp_path)
    c._maybe_auto_design()
    before = c._settings_view()
    c.store.settings["sliders"]["balance"] = 40.0      # what apply_settings does on a slider move
    c._drop_saved_brackets(settings_change_text(before, c._settings_view()))
    c._settle_at = 1.0
    m = read_manifest(tmp_path / "saved_stl")
    assert m["status"] == "brackets_removed" and m["brackets_removed"]["reason"] == "Balance the Spacecraft 36 → 40"
    c._maybe_auto_design()                             # the slider may still be moving: nothing yet
    assert read_manifest(tmp_path / "saved_stl")["status"] == "brackets_removed"
    c._settle_at = None                                # settled (_tick): the same designed best is saved again
    c._maybe_auto_design()
    m = read_manifest(tmp_path / "saved_stl")
    assert m["status"] == "complete" and m["settings"]["sliders"]["balance"] == 40.0 and m["brackets"]


def test_a_failed_file_write_is_reported_not_raised(tmp_path):
    c = _coord(tmp_path)
    errors = []
    c._error = errors.append
    (tmp_path / "saved_stl").write_text("a file where the folder should be", encoding="utf-8")
    c._maybe_auto_design()
    assert errors and "saving the STL files of L-1 failed" in errors[0] and c.__dict__.get("_stl_pending") is None
