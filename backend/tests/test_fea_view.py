"""V2: a designed bracket's FEA colour maps as the app reads them (Coordinator.item_fea / item_fea_field)."""
from types import SimpleNamespace

import numpy as np
import pytest

from t2s.service.coordinator import Coordinator


def _coord(tmp_path, design):
    c = Coordinator.__new__(Coordinator)
    c.store = SimpleNamespace(cache=tmp_path)
    e = SimpleNamespace(id="L-7", meta={"brackets": [{"pid": "p1", "kind": "metal_am"}, {"pid": "p2", "kind": "direct"}],
                                        "bracket_designs": {"p1": design}})
    c.archive = {"L-7": e}
    (tmp_path / "items" / "L-7").mkdir(parents=True, exist_ok=True)
    return c


VIEW = {"fields": [{"id": "util_body", "label": "Utilisation", "unit": "", "kind": "utilisation", "max": 0.4,
                    "max_all": 0.5}], "environment": "gevs", "n_vertices": 3}


def test_a_designed_brackets_maps_are_described_and_served_per_vertex(tmp_path):
    c = _coord(tmp_path, {"pid": "p1", "mass_kg": 0.01, "passed": True, "fea_file": "L-7-br0.fea.npz",
                          "fea_view": VIEW, "ms_yield": 1.0})
    np.savez_compressed(tmp_path / "items" / "L-7" / "L-7-br0.fea.npz", util_body=np.array([0.1, 0.4, 0.2], np.float32))
    info = c.item_fea("L-7-br0")
    assert info["available"] and info["fields"][0]["id"] == "util_body" and info["part_id"] == "p1"
    assert np.frombuffer(c.item_fea_field("L-7-br0", "util_body"), "<f4").tolist() == pytest.approx([0.1, 0.4, 0.2])
    for bad in (("L-7-br0", "nope"), ("L-7-br1", "util_body"), ("L-7-br9", "util_body"), ("L-8-br0", "util_body")):
        with pytest.raises(KeyError):
            c.item_fea_field(*bad)
    with pytest.raises(KeyError):                                   # a direct mount is not a designed bracket
        c.item_fea("L-7-br1")


def test_the_one_piece_and_a_combined_bracket_have_maps_too(tmp_path):
    """M4 designs that hold several parts: the one piece (<layout>-op) and a combined bracket (<layout>-cb<k>), their
    maps in their layout's folder, with the checks they belong to; one whose check did not run says so."""
    c = _coord(tmp_path, {"pid": "p1", "mass_kg": 0.01, "passed": True})
    checks = [{"case": "static", "axis": "x", "sigma_mpa": 9.0, "ms_yield": 2.0, "ms_ult": 3.0, "gates": True}]
    c.archive["L-7"].meta["bracket_layouts"] = {
        "one_piece": {"designs": {"one_piece": {"name": "one piece", "kind": "one_piece", "parts": ["p1", "p2"],
                                                "mass_kg": 0.3, "passed": True, "fea_file": "L-7-op.fea.npz",
                                                "fea_view": VIEW, "checks": checks, "bolt_checks": []}}},
        "combined": {"designs": {"p1+p2": {"name": "combined:1", "kind": "combined", "parts": ["p1", "p2"], "index": 0,
                                           "mass_kg": 0.05, "passed": False,
                                           "reason": "not solved: NGSolve with 9 dofs needs about 1 MB"}}}}
    (tmp_path / "items" / "L-7" / "one_piece").mkdir()
    np.savez_compressed(tmp_path / "items" / "L-7" / "one_piece" / "L-7-op.fea.npz",
                        util_body=np.array([0.1, 0.4, 0.2], np.float32))
    info = c.item_fea("L-7-op")
    assert info["available"] and info["parts"] == ["p1", "p2"] and info["kind"] == "one_piece"
    assert info["checks"] == checks and info["part_id"] is None
    assert np.frombuffer(c.item_fea_field("L-7-op", "util_body"), "<f4").tolist() == pytest.approx([0.1, 0.4, 0.2])
    cb = c.item_fea("L-7-cb0")
    assert not cb["available"] and cb["why"].startswith("no colour maps: its two-solver check did not run (not solved")
    for bad in ("L-7-cb1", "L-7-opx", "L-8-op"):
        with pytest.raises(KeyError):
            c.item_fea(bad)
    with pytest.raises(KeyError):
        c.item_fea_field("L-7-cb0", "util_body")


def test_a_design_without_maps_says_why(tmp_path):
    old = _coord(tmp_path, {"pid": "p1", "mass_kg": 0.01, "passed": True})       # designed before the maps existed
    info = old.item_fea("L-7-br0")
    assert not info["available"] and "redesign" in info["why"]
    with pytest.raises(KeyError):
        old.item_fea_field("L-7-br0", "util_body")
    failed = _coord(tmp_path, {"pid": "p1", "mass_kg": None, "passed": False})   # no solid: no maps, no item
    with pytest.raises(KeyError):
        failed.item_fea("L-7-br0")
