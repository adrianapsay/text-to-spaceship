"""V2 WS2: the search runs until Pause (no automatic stop), the running time counts searching only, the recommended
minimum is reported, and the archive keeps bounded memory: layouts kept on disk only still count for the best layout,
the least-violating one, the normaliser and the Pareto plot, exactly as when every layout was in memory."""
import json
import math
import tracemalloc
from types import SimpleNamespace

import numpy as np

from t2s.bench.convergence_table import best_length_trajectory, recommended_minimum, time_within
from t2s.optimise.scalarize import Normaliser
from t2s.service import coordinator as co
from t2s.service.coordinator import Coordinator, LayoutEntry
from t2s.service.project import DEFAULT_SETTINGS

PIDS = ["p1", "p2", "p3"]


def make_ctx(ctx_id="ctx-a", stage=1):
    return SimpleNamespace(ctx_id=ctx_id, stage=stage, parts_sig="ps", spec_sig="ss", constraint_sig="cs", ids=PIDS,
                           proxies=[SimpleNamespace(id=p, allowed=list(range(24))) for p in PIDS], fixed=[],
                           records={}, part_scale=1.0)


def make_coord(tmp_path, **settings) -> Coordinator:
    """The coordinator without workers or parts: physics is the layouts' own raw objectives (no records)."""
    s = json.loads(json.dumps(DEFAULT_SETTINGS))
    s.update(settings)
    store = SimpleNamespace(archive_path=tmp_path / "archive.jsonl", settings=s, entries={}, folder=tmp_path,
                            revs={"parts_rev": 1, "constraint_rev": 1, "mass_rev": 0, "weights_rev": 1},
                            counters={"layout": 0, "epoch": 1}, save=lambda: None, scan_inbox=list)
    c = Coordinator(store, workers=False, auto_start=False)
    c.ctx = make_ctx()
    c._compute_physics = lambda e, phys=None: None
    return c


def lay(i, raw, status="VALIDATED", cv=0.0, spec="ss", meta=None) -> LayoutEntry:
    return LayoutEntry(id=f"L-{i:04d}", hash=f"h{i}", stage=1, mode="default", status=status, parts_sig="ps",
                       constraint_sig="cs", poses=[(p, 0, np.zeros(3)) for p in PIDS],
                       geo={"length_used_mm": raw["L"]}, validation={"certified": True}, raw=dict(raw), cv=cv,
                       spec_sig=spec, meta=meta or {})


def random_raw(rng):
    return {"L": float(rng.uniform(150, 300)), "D": float(rng.uniform(0, 40)), "T": float(rng.uniform(0.01, 0.05)),
            "P": float(rng.uniform(0, 0.01)), "span": 1.0}


def old_pareto(c, entries):
    """pareto() as it was: every current VALIDATED / FINAL layout in memory, N × N comparison."""
    cur = [e for e in entries if c._current(e) and e.status in ("VALIDATED", "FINAL")]
    nrm = {e.id: c._score_raw(e.raw)[1] for e in cur}
    cur = [e for e in cur if all(nrm[e.id].get(k) is not None for k in ("L", "D", "I"))]
    if not cur:
        return set()
    a = np.array([[nrm[e.id]["L"], nrm[e.id]["D"], nrm[e.id]["I"]] for e in cur], float)
    le = np.all(a[None, :, :] <= a[:, None, :], axis=2)
    lt = np.any(a[None, :, :] < a[:, None, :], axis=2)
    return {e.id for e, d in zip(cur, np.any(le & lt, axis=1)) if not d}


def fill(c, n, rng, enforce_every=20):
    entries = []
    for i in range(1, n + 1):
        r = random_raw(rng)
        kind = i % 10
        if kind == 7:
            e = lay(i, r, status="INFEASIBLE", cv=float(rng.uniform(0.1, 3)))
        elif kind == 8:
            e = lay(i, r, status="REJECTED")
        elif kind == 9:
            e = lay(i, r, spec="other")                      # validated for other rules: never current
        else:
            e = lay(i, r)
        c._admit(e)
        entries.append(e)
        if i % enforce_every == 0:
            c._enforce_memory()
        if i == n // 2:
            c._maybe_new_epoch(force=True)                   # a normaliser half-way, as during a search
    return entries


def test_best_least_normaliser_and_pareto_count_layouts_kept_on_disk_only(tmp_path, monkeypatch):
    monkeypatch.setattr(co, "TOP_K", 5)
    monkeypatch.setattr(co, "NEWEST_KEEP", 3)
    monkeypatch.setattr(co, "HOT_SLACK", 2)
    c = make_coord(tmp_path)
    rng = np.random.default_rng(5)
    entries = fill(c, 400, rng)
    c._enforce_memory()
    assert len(c.archive) == 400 and c.archive.n_hot <= 5 + 3 + 2 + 2
    cur = [e for e in entries if c._current(e)]
    ok = [e for e in cur if e.status in ("VALIDATED", "FINAL")]
    assert len(c._table) == len(cur)                         # every current layout has its row
    # the normaliser from all layouts of these inputs (as the full archive scan did), then the best and the plot
    c._maybe_new_epoch(force=True)
    ref = Normaliser()
    ref.update_from([e.raw for e in ok if "D" in e.raw] + c.raw_pool.get("ctx-a", [])[-300:])
    assert c._norm().utopia == ref.utopia and c._norm().nadir == ref.nadir
    best = min(ok, key=lambda e: (e.cv, c._score_raw(e.raw)[0], e.raw["L"], e.id))
    assert c.best_id == best.id and c.archive.is_hot(best.id)
    assert {p["layout_id"] for p in c.pareto()["points"]} == old_pareto(c, entries)
    # a slider move re-scores: still the best over all of them
    c.store.settings["sliders"].update({"space": 90, "balance": 5, "mass_symmetry": 10})
    c._restamp_and_rescore()
    best = min(ok, key=lambda e: (e.cv, c._score_raw(e.raw)[0], e.raw["L"], e.id))
    assert c.best_id == best.id
    assert {p["layout_id"] for p in c.pareto()["points"]} == old_pareto(c, entries)
    # the candidate filter: dominated by any current validated layout, as the scan over all of them said
    for _ in range(200):
        cand = random_raw(rng)
        assert c._table.dominated(cand, ("L", "D", "T")) == any(
            all(e.raw[k] <= cand[k] for k in "LDT") and any(e.raw[k] < cand[k] for k in "LDT") for e in ok)


def test_the_least_violating_layout_counts_layouts_on_disk_too(tmp_path, monkeypatch):
    monkeypatch.setattr(co, "TOP_K", 3)
    monkeypatch.setattr(co, "NEWEST_KEEP", 2)
    monkeypatch.setattr(co, "HOT_SLACK", 1)
    c = make_coord(tmp_path)
    rng = np.random.default_rng(9)
    inf = []
    for i in range(1, 120):
        e = lay(i, random_raw(rng), status="INFEASIBLE", cv=float(rng.choice([0.5, 1.0, 2.0])))
        c._admit(e)
        inf.append(e)
        c._enforce_memory()
    assert c.best_id is None and c.archive.n_hot <= 3 + 2 + 1 + 2
    least = min(inf, key=lambda e: (e.cv, c._score_raw(e.raw)[0], e.id))
    assert c.least_id == least.id


def test_a_layout_on_disk_only_is_read_back_as_it_was(tmp_path, monkeypatch):
    monkeypatch.setattr(co, "TOP_K", 2)
    monkeypatch.setattr(co, "NEWEST_KEEP", 1)
    monkeypatch.setattr(co, "HOT_SLACK", 0)
    c = make_coord(tmp_path)
    rng = np.random.default_rng(3)
    meta = {"filler": [{"pid": "p1", "label": 'a "b" \\ c', "reserve": [0.5, 1, 2, 3, 4, 5], "nested": {"x": None}}]}
    shown = {}
    for i in range(1, 31):
        e = lay(i, random_raw(rng), meta=meta)
        c._admit(e)
        shown[e.id] = json.dumps(c.layout_json(e), sort_keys=True)
    c._enforce_memory()
    cold = [lid for lid in shown if not c.archive.is_hot(lid)]
    assert len(cold) >= 20
    for lid in cold:
        assert json.dumps(c.layout_json(c.archive[lid]), sort_keys=True) == shown[lid]
    c.archive.evict(c.best_id)                               # even the best, gone from memory, is read back
    b = c.best_id
    c.best_id = None
    c._select_best()
    assert c.best_id == b and c.archive.is_hot(b)


def test_start_compacts_an_archive_with_many_superseded_lines(tmp_path):
    rng = np.random.default_rng(2)
    path = tmp_path / "archive.jsonl"
    es = [lay(i, random_raw(rng)) for i in range(1, 301)]
    with open(path, "w", encoding="utf-8") as fh:
        fh.writelines(json.dumps(e.to_store()) + "\n" for e in es)
        for e in es[:250]:                                   # written again (e.g. its brackets designed)
            e.meta = {"bracket_designs": {"p1": {"mass_kg": 0.01}}}
            fh.write(json.dumps(e.to_store()) + "\n")
    c = make_coord(tmp_path)
    c._load_archive()
    lines = path.read_bytes().splitlines()
    assert len(lines) == 300 and c.archive.superseded == 0 and len(c.archive) == 300
    assert c.archive["L-0007"].meta == {"bracket_designs": {"p1": {"mass_kg": 0.01}}} and c.archive["L-0290"].meta == {}
    assert c.store.counters["layout"] == 300


def test_layout_list_is_newest_first_by_number_and_includes_layouts_on_disk(tmp_path):
    c = make_coord(tmp_path)
    rng = np.random.default_rng(1)
    for i in (9998, 9999, 10000, 10001):
        c._admit(lay(i, random_raw(rng)))
    c.archive.evict("L-10000")
    assert [e.id for e in c.layout_list(limit=3)] == ["L-10001", "L-10000", "L-9999"]   # a string sort: 9999 first
    assert not c.archive.is_hot("L-10000")                   # read for the answer only
    assert [e.id for e in c.layout_list(status="REJECTED")] == []


def test_memory_stays_bounded_for_a_stream_of_5000_layouts(tmp_path, capsys):
    """5,000 layouts with ~10 kB of bracket-like metadata each through the admission path with the real limits: the
    layouts in memory stop growing, and so (but for a few hundred bytes of index and objective row per layout) does
    the memory."""
    c = make_coord(tmp_path)
    rng = np.random.default_rng(13)
    filler = [{"pid": f"p{k}", "kind": "metal_am", "process": "metal_am", "label": "AM bracket (estimate)",
               "reserve": rng.uniform(-50, 50, 6).round(3).tolist(), "com_mm": rng.uniform(-50, 50, 3).tolist(),
               "inertia_kgm2": rng.uniform(0, 1e-5, (3, 3)).tolist(), "mass_kg": 0.01, "cost_rel": 4.0,
               "target": {"kind": "wall", "axis": 0, "neg": True}} for k in range(24)]
    sizes, hot = {}, []
    for i in range(1, 5001):
        c._admit(lay(i, random_raw(rng), meta={"filler": filler, "n": i}))
        if i % 100 == 0:
            c._enforce_memory()
            hot.append(c.archive.n_hot)
        if i == 1000:
            tracemalloc.start()
        if i in (3000, 5000):
            sizes[i] = tracemalloc.get_traced_memory()[0]
    tracemalloc.stop()
    entry_bytes = len(json.dumps(lay(1, random_raw(rng), meta={"filler": filler}).to_store()))
    per_layout = (sizes[5000] - sizes[3000]) / 2000
    limit = co.TOP_K + co.NEWEST_KEEP + co.HOT_SLACK
    with capsys.disabled():
        print(f"\n[memory] {len(c.archive)} layouts, {entry_bytes} B of JSON each; in memory at most {max(hot)} "
              f"(limit {limit} + pinned); memory growth {per_layout:.0f} B per layout between 3,000 and 5,000")
    assert len(c.archive) == 5000 and max(hot[10:]) <= limit + 4
    assert per_layout < 0.25 * entry_bytes                   # a full layout in memory is several times its JSON


def test_no_automatic_stop_and_pause_still_designs(tmp_path, monkeypatch):
    c = make_coord(tmp_path)
    for name in ("_dispatch", "_dispatch_validation", "_migrate", "_maybe_new_epoch"):
        setattr(c, name, lambda: None)
    designs = []
    c._maybe_auto_design = lambda: designs.append(c.run_status)
    c.run_control("start")
    c._admit(lay(1, random_raw(np.random.default_rng(0))))
    now = [1e6]
    monkeypatch.setattr(co.time, "monotonic", lambda: now[0])
    for _ in range(5):                                       # 7 h without any improvement, ticks every hour
        now[0] += 7 * 3600 / 5
        c._tick()
    assert c.run_status == "SEARCHING" and designs == []
    c.run_control("pause")
    assert c.run_status == "PAUSED" and designs == ["PAUSED"]
    c.apply_settings({"sliders": {"space": 40}})            # a slider move while paused does not restart the search
    assert c.run_status == "PAUSED"
    c.run_control("resume")
    assert c.run_status == "SEARCHING"


def test_running_time_counts_searching_per_context_and_the_recommended_minimum(tmp_path, monkeypatch):
    c = make_coord(tmp_path)
    now = [1000.0]
    monkeypatch.setattr(co.time, "monotonic", lambda: now[0])
    c._clock_context("ctx-a")
    c.run_control("start")
    now[0] = 1600.0
    assert c.searching_s() == 600.0
    c.run_control("pause")
    now[0] = 2600.0                                           # paused for 1000 s: not counted
    p = c._progress()
    assert p["elapsed_s"] == 600.0 and p["status"] == "PAUSED"
    assert p["recommended_min_s"] == recommended_minimum("3U")["minimum_s"] == 5930.0
    assert "provisional" in p["recommended_note"] and "7.5 h run at 3U 54 %" in p["recommended_note"]
    c.run_control("resume")
    now[0] = 2900.0
    assert c.searching_s() == 900.0
    c.ctx = make_ctx("ctx-b")                                 # other inputs: their own running time
    c._clock_context("ctx-b")
    now[0] = 3000.0
    assert c.searching_s() == 100.0
    c.ctx = make_ctx("ctx-a")                                 # back: the time searched before counts again
    c._clock_context("ctx-a")
    now[0] = 3100.0
    assert c.searching_s() == 1000.0
    c.run_control("rerun")                                    # new seeds: from zero
    now[0] = 3200.0
    assert c.searching_s() == 100.0
    monkeypatch.setattr(co.formfactor, "current", lambda: "6U")
    p = c._progress()
    assert p["recommended_min_s"] is None and p["recommended_note"] == "No recommended minimum has been measured for 6U yet."


def test_speed_quality_is_not_a_search_setting(tmp_path):
    c = make_coord(tmp_path, stage=2)
    c.ctx = make_ctx(stage=2)
    dropped = []
    c._drop_saved_brackets = dropped.append
    assert "speed_quality" not in c._settings_view()["sliders"] and "space" in c._settings_view()["sliders"]
    c.apply_settings({"sliders": {"speed_quality": 90}})
    assert c.store.settings["sliders"]["speed_quality"] == 90 and dropped == []   # the saved bracket files stay
    c.apply_settings({"sliders": {"space": 33}})
    assert dropped == ["Use Space Efficiently 25 → 33"]


def test_convergence_table_from_archive_lines():
    def line(i, minute, status, length, spec="s"):
        return json.dumps({"id": f"L-{i}", "stage": 2, "parts_sig": "p", "spec_sig": spec, "status": status,
                           "created": f"2026-10-24T00:{minute:02d}:00+00:00", "raw": {"L": length}})
    lines = [line(1, 0, "REJECTED", 100.0), line(2, 1, "VALIDATED", 150.0), line(3, 2, "INFEASIBLE", 120.0),
             line(4, 5, "VALIDATED", 140.0), line(5, 6, "VALIDATED", 145.0), line(6, 9, "VALIDATED", 138.0),
             line(7, 3, "VALIDATED", 90.0, spec="other"), line(4, 50, "INFEASIBLE", 140.0)]   # L-4 re-written
    traj = best_length_trajectory(lines, "p", "s")
    assert traj == [(60.0, 150.0, "L-2"), (360.0, 145.0, "L-5"), (540.0, 138.0, "L-6")]   # L-4: last line INFEASIBLE
    assert time_within(traj, 0.01) == 540.0 and time_within(traj, 0.1) == 60.0 and time_within([], 0.01) is None
    assert recommended_minimum("12U") is None and recommended_minimum("3U")["provisional"] is True
    assert math.isclose(recommended_minimum("3U")["minimum_s"] / 60, 98.83, abs_tol=0.01)
