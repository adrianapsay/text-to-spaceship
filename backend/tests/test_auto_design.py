"""V2: the automatic bracket design run (Coordinator._maybe_auto_design) — when it starts and when it waits."""
from types import SimpleNamespace

from t2s.service.coordinator import Coordinator


def _coord(**settings):
    c = Coordinator.__new__(Coordinator)            # the trigger logic only: no workers, no project
    c.store = SimpleNamespace(settings={"auto_design_brackets": True, **settings})
    c.val_queue, c.val_pending, c.ladders = [], {}, {}
    c.workers = [SimpleNamespace(role="island", busy=False), SimpleNamespace(role="validator", busy=True)]
    c.run_status = "PAUSED"
    c.archive = {"L-1": SimpleNamespace(id="L-1", stage=2, status="VALIDATED",
                                        meta={"brackets": [{"pid": "p1", "kind": "metal_am"},
                                                           {"pid": "p2", "kind": "direct"}]})}
    c.best_id = "L-1"
    c.started, c.synced, c.pids = [], [], []
    c.start_bracket_design = lambda lid, pids=None, overrides=None: (c.started.append(lid), c.pids.append(pids))
    c._sync_saved_stl = lambda e: c.synced.append(e.id)     # the saved STL files (test_saved_stl.py)
    c._error = lambda msg: None
    return c


def test_waits_for_the_validation_backlog_then_designs_the_best_layout_once():
    c = _coord()
    c.val_queue = ["pending"]
    c._maybe_auto_design()
    assert c.started == [] and c._auto_design_due                     # the best may still change
    c.val_queue = []
    c._maybe_auto_design()
    assert c.started == ["L-1"]
    c._maybe_auto_design()                                            # once per layout
    assert c.started == ["L-1"]


def test_waits_for_island_jobs_still_in_flight_after_the_pause():
    c = _coord()
    c.workers[0].busy = True                                          # its results may still bring a better layout
    c._maybe_auto_design()
    assert c.started == [] and c._auto_design_due and not c._search_settled()
    c.workers[0].busy = False                                         # a busy validator worker alone does not count
    assert c._search_settled()
    c._maybe_auto_design()
    assert c.started == ["L-1"]


def test_islands_get_new_jobs_only_while_searching():
    """Pause really stops the search (the only stop since V2): an island reporting back gets no next job (it used
    to)."""
    c = _coord()
    calls = []
    c._dispatch = lambda: calls.append(c.run_status)
    for status in ("PAUSED", "IDLE", "SEARCHING"):
        c.run_status = status
        c._continue_search()
    assert calls == ["SEARCHING"]


def test_layout_ids_continue_after_the_archive_when_the_saved_counter_lags(tmp_path):
    """The project file (with the layout counter) is saved now and then, the archive with every layout: after a
    stop the counter can lag behind, and new layouts must not reuse ids of archived ones."""
    import json

    from t2s.service.coordinator import LayoutEntry
    path = tmp_path / "archive.jsonl"
    with open(path, "w", encoding="utf-8") as fh:
        for i in (2, 41, 17):
            e = LayoutEntry(f"L-{i:04d}", f"h{i}", 2, "default", "VALIDATED", "p", "c", [], {}, {})
            fh.write(json.dumps(e.to_store()) + "\n")
    for saved, expect in ((3, 41), (50, 50)):
        c = Coordinator.__new__(Coordinator)
        c.store = SimpleNamespace(archive_path=path, counters={"layout": saved})
        c.archive, c.by_hash = {}, {}
        c._load_archive()
        assert set(c.archive) == {"L-0002", "L-0017", "L-0041"} and c.store.counters["layout"] == expect


def test_nothing_to_design_switched_off_or_a_run_in_progress():
    off = _coord(auto_design_brackets=False)
    off._maybe_auto_design()
    designed = _coord()
    designed.archive["L-1"].meta["bracket_designs"] = {"p1": {"mass_kg": 0.01, "environment": "gevs",
                                                              "material": "AlSi10Mg"}}
    designed._maybe_auto_design()
    busy = _coord()
    busy.ladders["__bracket_design__"] = {"finalised": False}
    busy._maybe_auto_design()
    stage1 = _coord()
    stage1.archive["L-1"].stage = 1
    stage1._maybe_auto_design()
    assert off.started == designed.started == busy.started == stage1.started == []
    assert designed.synced == ["L-1"] and off.synced == stage1.synced == []   # designed: its STL files follow it
    busy.ladders["__bracket_design__"]["finalised"] = True            # the running one has finished
    busy._maybe_auto_design()
    assert busy.started == ["L-1"]


def test_brackets_designed_for_another_environment_or_material_are_designed_again():
    """WS4: the automatic design follows the launch environment and the AM material — a design made for others (or
    before the launch environments) is designed again, once; the current ones are kept."""
    c = _coord()
    meta = c.archive["L-1"].meta
    meta["brackets"].append({"pid": "p3", "kind": "cradle"})
    meta["bracket_designs"] = {"p1": {"mass_kg": 0.01, "environment": "gevs", "material": "AlSi10Mg"},
                               "p3": {"mass_kg": 0.02, "environment": "gevs", "material": "6061-T6"}}
    c._maybe_auto_design()
    assert c.started == [] and c.synced == ["L-1"]                    # current: nothing to design
    c.store.settings["launch_environment"] = "spacex"
    c._maybe_auto_design()
    assert c.started == ["L-1"] and c.pids[-1] == ["p1", "p3"]        # both were designed for GEVS
    c._maybe_auto_design()
    assert len(c.started) == 1                                        # once per layout and environment
    c.store.settings.update(launch_environment="gevs", bracket_material="Ti-6Al-4V")
    c._maybe_auto_design()
    assert c.pids[-1] == ["p1"]                                       # the machined cradle stays 6061-T6
    meta["bracket_overrides"] = {"p1": {"material": "AlSi10Mg"}}       # its own material: the design is current
    c._auto_design_tried.clear()
    c.started.clear()
    c._maybe_auto_design()
    assert c.started == []
    del meta["bracket_designs"]["p1"]["environment"]                  # designed before the launch environments
    c._maybe_auto_design()
    assert c.started == ["L-1"] and c.pids[-1] == ["p1"]


def test_waits_until_a_moving_slider_has_settled():
    c = _coord()
    c._settle_at = 123.0                                              # set by apply_settings, cleared by _tick
    c._maybe_auto_design()
    assert c.started == []
    c._settle_at = None
    c._maybe_auto_design()
    assert c.started == ["L-1"]


def test_islands_skip_migrants_of_another_chromosome_length():
    """A Stage 2 chromosome (3 extra keys) sent to a Stage 1 island broke every later crossover of that island."""
    import numpy as np

    from t2s.service.worker import fitting_keys
    keys = fitting_keys([np.full(60, 0.5), np.full(57, 0.25), [0.1] * 57], 57)
    assert [k.shape for k in keys] == [(57,), (57,)] and keys[0][0] == 0.25
    assert fitting_keys(None, 57) == [] and fitting_keys([np.zeros(57)], 60) == []
