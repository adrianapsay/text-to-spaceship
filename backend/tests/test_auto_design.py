"""V2: the automatic bracket design run (Coordinator._maybe_auto_design) — when it starts and when it waits."""
from types import SimpleNamespace

from t2s.service.coordinator import Coordinator


def _coord(**settings):
    c = Coordinator.__new__(Coordinator)            # the trigger logic only: no workers, no project
    c.store = SimpleNamespace(settings={"auto_design_brackets": True, **settings})
    c.val_queue, c.val_pending, c.ladders = [], {}, {}
    c.run_status = "PAUSED"
    c.archive = {"L-1": SimpleNamespace(id="L-1", stage=2, status="VALIDATED",
                                        meta={"brackets": [{"pid": "p1", "kind": "metal_am"},
                                                           {"pid": "p2", "kind": "direct"}]})}
    c.best_id = "L-1"
    c.started = []
    c.start_bracket_design = lambda lid: c.started.append(lid)
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


def test_nothing_to_design_switched_off_or_a_run_in_progress():
    off = _coord(auto_design_brackets=False)
    off._maybe_auto_design()
    designed = _coord()
    designed.archive["L-1"].meta["bracket_designs"] = {"p1": {"mass_kg": 0.01}}
    designed._maybe_auto_design()
    busy = _coord()
    busy.ladders["__bracket_design__"] = {"finalised": False}
    busy._maybe_auto_design()
    stage1 = _coord()
    stage1.archive["L-1"].stage = 1
    stage1._maybe_auto_design()
    assert off.started == designed.started == busy.started == stage1.started == []
    busy.ladders["__bracket_design__"]["finalised"] = True            # the running one has finished
    busy._maybe_auto_design()
    assert busy.started == ["L-1"]
