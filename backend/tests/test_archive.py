"""V2 bounded archive (service/archive.py): layouts kept on disk only are read back intact, the last line of an id
wins, compaction keeps one line per id, and the incremental Pareto filter and the objective table give the same
answers as the pairwise comparisons they replace."""
import json
import math

import numpy as np

from t2s.optimise.scalarize import dominates
from t2s.service.archive import LayoutArchive, ObjectiveTable, ParetoFront
from t2s.service.coordinator import LayoutEntry


def entry(i: int, status: str = "VALIDATED", stage: int = 2, spec: str = "s1", **kw) -> LayoutEntry:
    """A Stage 2-like layout: poses, bracket metadata with quotes and nested dicts, objective values."""
    rng = np.random.default_rng(i)
    meta = {"brackets": [{"pid": f"p{k}", "kind": "metal_am", "label": 'L "bracket" \\ 2', "reserve": [0, 1, 2, 3, 4, 5],
                          "nested": {"status": "x", "spec_sig": "decoy"}} for k in range(4)], "mode": "default"}
    return LayoutEntry(id=f"L-{i:04d}", hash=f"h{i:04d}", stage=stage, mode="default", status=status,
                       parts_sig="ps", constraint_sig="cs",
                       poses=[(f"p{k}", int(rng.integers(24)), rng.uniform(-40, 40, 3).round(3)) for k in range(3)],
                       geo={"length_used_mm": float(rng.uniform(100, 300))}, validation={"certified": True},
                       raw={"L": float(rng.uniform(100, 300)), "D": float(rng.uniform(0, 20))}, metrics={"m": i},
                       g=float(rng.uniform()), spec_sig=spec, meta=meta, **kw)


def same(a: LayoutEntry, b: LayoutEntry) -> bool:
    return json.dumps(a.to_store(), sort_keys=True) == json.dumps(b.to_store(), sort_keys=True)


def test_layouts_on_disk_only_are_read_back_intact_and_the_dict_view_covers_all(tmp_path):
    path = tmp_path / "archive.jsonl"
    a = LayoutArchive(path, LayoutEntry.from_store)
    es = [entry(i) for i in range(1, 21)]
    for e in es:
        a.append(e)
    assert a.n_hot == 20 and len(a) == 20
    for e in es[:15]:
        assert a.evict(e.id)
    assert a.n_hot == 5 and len(a) == 20 and list(a) == [e.id for e in es]
    assert {e.id for e in a.values()} == {e.id for e in es[15:]}          # values(): the layouts in memory only
    assert "L-0003" in a and "L-0999" not in a and a.get("L-0999") is None
    for e in es:
        assert same(a[e.id], e)                                             # read back (or still in memory)
    assert a.n_hot == 20 and a.loads == 15
    assert not a.evict("L-0999")
    fresh = {}
    b = LayoutArchive(path, LayoutEntry.from_store)                        # a restart: index only, nothing loaded
    b.scan(fresh)
    assert b.n_hot == 0 and len(b) == 20 and fresh == {e.hash: e.id for e in es}
    assert same(b["L-0007"], es[6]) and b.status_of("L-0008") == "VALIDATED" and b.line("L-0008").spec_sig == "s1"


def test_the_last_line_of_an_id_wins_and_compaction_keeps_only_it(tmp_path):
    path = tmp_path / "archive.jsonl"
    a = LayoutArchive(path, LayoutEntry.from_store)
    for i in range(1, 6):
        a.append(entry(i))
    e3 = entry(3)
    e3.meta = {**e3.meta, "bracket_designs": {"p0": {"mass_kg": 0.01}}}  # brackets designed: written again
    a.append(e3)
    e5 = entry(5, status="FINAL")
    a.append(e5)
    assert a.superseded == 2
    b = LayoutArchive(path, LayoutEntry.from_store)
    b.scan()
    assert b.superseded == 2 and b.status_of("L-0005") == "FINAL"
    assert b["L-0003"].meta["bracket_designs"] == {"p0": {"mass_kg": 0.01}}
    assert b.should_compact(min_superseded=2, share=0.2) and not b.should_compact()
    b.evict("L-0003")
    assert b.rewrite() == 2                                                 # two superseded lines went
    lines = path.read_bytes().splitlines()
    assert [json.loads(x)["id"] for x in lines] == [f"L-{i:04d}" for i in range(1, 6)]
    assert json.loads(lines[2])["meta"]["bracket_designs"] and json.loads(lines[4])["status"] == "FINAL"
    c = LayoutArchive(path, LayoutEntry.from_store)
    c.scan()
    assert c.superseded == 0 and same(c["L-0003"], e3) and same(c["L-0005"], e5) and same(c["L-0001"], entry(1))
    assert c.rewrite(keep=lambda lid, status: status == "FINAL") == 4      # reset: FINAL layouts only
    assert list(c) == ["L-0005"] and same(c["L-0005"], e5)


def test_the_fast_index_reads_what_json_reads_and_old_lines_still_work(tmp_path):
    path = tmp_path / "archive.jsonl"
    es = [entry(i, status=("VALIDATED", "INFEASIBLE", "REJECTED")[i % 3], stage=1 + i % 2, spec=f"s{i % 4}")
          for i in range(1, 13)]
    with open(path, "w", encoding="utf-8") as fh:                          # written like the archive before V2
        fh.writelines(json.dumps(e.to_store()) + "\n" for e in es)         # (text mode: CRLF on Windows)
        fh.write("\n" + json.dumps({"id": "L-0099", "hash": "hx", "stage": 2, "status": "VALIDATED",
                                    "parts_sig": "ps", "spec_sig": "s9"}) + "\n")   # another key order: parsed in full
    a = LayoutArchive(path, LayoutEntry.from_store)
    by_hash = {}
    a.scan(by_hash)
    for e in es:
        x = a.line(e.id)
        assert (x.stage, x.parts_sig, x.spec_sig, x.status, x.hash) == (e.stage, "ps", e.spec_sig, e.status, e.hash)
    assert a.line("L-0099").spec_sig == "s9" and by_hash["hx"] == "L-0099"
    assert a.get("L-0099") is None and "L-0099" not in a                   # not a readable layout: dropped
    assert sorted(a.ids_of(2, "ps", "s1")) == sorted(e.id for e in es if e.stage == 2 and e.spec_sig == "s1")


def test_a_line_cut_short_does_not_swallow_the_next_one(tmp_path):
    path = tmp_path / "archive.jsonl"
    data = json.dumps(entry(1).to_store()) + "\n" + json.dumps(entry(2).to_store())[:300]
    path.write_bytes(data.encode())                                         # the process was killed mid-write
    a = LayoutArchive(path, LayoutEntry.from_store)
    a.scan()
    a.append(entry(3))
    b = LayoutArchive(path, LayoutEntry.from_store)
    b.scan()
    assert same(b["L-0001"], entry(1)) and same(b["L-0003"], entry(3)) and b.get("L-0002") is None


def brute_front(pts: np.ndarray) -> set[int]:
    le = np.all(pts[None, :, :] <= pts[:, None, :], axis=2)
    lt = np.any(pts[None, :, :] < pts[:, None, :], axis=2)
    return set(np.flatnonzero(~np.any(le & lt, axis=1)).tolist())


def test_incremental_pareto_front_equals_the_pairwise_comparison():
    rng = np.random.default_rng(7)
    for dim, n, ints in ((2, 400, False), (3, 1500, False), (4, 600, False), (3, 800, True), (6, 300, True)):
        pts = rng.integers(0, 6, (n, dim)).astype(float) if ints else rng.random((n, dim))   # ints: ties, duplicates
        f = ParetoFront(dim)
        for i in rng.permutation(n):
            f.insert(int(i), pts[i])
        assert set(f.ids) == brute_front(pts), (dim, n, ints)
        assert all(not f.dominated(pts[i]) for i in f.ids)


def test_objective_table_answers_like_the_scan_of_every_layout():
    rng = np.random.default_rng(11)
    t = ObjectiveTable()
    raws = {}
    for i in range(500):
        raw = {"L": float(rng.integers(100, 140)), "D": float(rng.integers(0, 30)), "T": float(rng.integers(1, 9)),
               "P": float(rng.random()), "span": 1.0, "com": [0, 0, 0]}
        if i % 50 == 0:
            raw["D"] = math.nan                                             # not finite: a group without D
        status = ("VALIDATED", "FINAL", "INFEASIBLE", "REJECTED")[i % 4]
        t.put(f"L-{i}", status, 0.0 if status != "INFEASIBLE" else 1.0, raw)
        raws[f"L-{i}"] = (status, raw)
    assert len(t) == 500 and t.count("ok") == 250 and t.count("inf") == 125
    keys = ("L", "D", "T")
    ok = [r for s, r in raws.values() if s in ("VALIDATED", "FINAL")]
    for _ in range(300):
        cand = {"L": float(rng.integers(95, 145)), "D": float(rng.integers(0, 32)), "T": float(rng.integers(0, 10))}
        assert t.dominated(cand, keys) == any(dominates(r, cand, keys) for r in ok)
    lo, hi, n = t.extremes("D")
    with_d = [r for r in ok if math.isfinite(r["D"])]
    assert n == len(with_d) and lo["L"] == min(r["L"] for r in with_d) and hi["P"] == max(r["P"] for r in with_d)
    assert t.put("L-4", "INFEASIBLE", 2.0, raws["L-4"][1]) and t.count("ok") == 249 and t.changes == 1
    assert t.discard("L-3") and "L-3" not in t and len(t) == 499
