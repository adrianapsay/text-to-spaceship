"""V2 "Find largest size that fits": bisection to 1 % on a search-based fit test."""
import copy
import json

from t2s.bench import largest_size as ls


def test_bisection_finds_the_threshold(monkeypatch, tmp_path):
    tried = []

    def fake(records, scale, *a, **k):
        tried.append(scale)
        return {"scale": scale, "pct": 100 * scale, "found": scale <= 0.8349, "search_feasible": True,
                "certified": True, "cv": 0.0, "unmounted": 0, "seconds": 0.0}
    monkeypatch.setattr(ls, "_try", fake)
    out = ls.run_largest_size({}, "soft", {}, tmp_path / "r.json")
    assert out["largest_pct"] == 83.0 and out["status"] == "DONE"
    assert tried[:2] == [1.0, 0.5] and len(tried) <= 2 + 6
    assert json.loads((tmp_path / "r.json").read_text())["largest_pct"] == 83.0


def test_nothing_found_and_everything_fits(monkeypatch, tmp_path):
    monkeypatch.setattr(ls, "_try", lambda r, s, *a, **k: {"scale": s, "found": False})
    out = ls.run_largest_size({}, "soft", {}, tmp_path / "a.json")
    assert out["largest_pct"] is None and "no layout found" in out["verdict"]
    monkeypatch.setattr(ls, "_try", lambda r, s, *a, **k: {"scale": s, "found": True})
    out = ls.run_largest_size({}, "soft", {}, tmp_path / "b.json")
    assert out["largest_pct"] == 100.0 and len(out["rows"]) == 1


def test_a_small_set_fits_at_full_size(dataset_parts, tmp_path):
    recs = {}
    for n in ("battery_pack", "payload_electronics_box"):
        r = copy.copy(dataset_parts[n][1])
        r.id, r.tags = n, []
        recs[n] = r
    out = ls.run_largest_size(recs, "soft", {"space": 25}, tmp_path / "c.json", generations=6, pop=12)
    row = out["rows"][0]
    assert row["pct"] == 100.0
    if row["found"]:                                     # certified by the validator, not just the search
        assert row["certified"] and out["largest_pct"] == 100.0
