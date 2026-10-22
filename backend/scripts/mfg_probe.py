"""M9 probe: Stage 2 with Manufacturable-Design brackets (reach 40 mm) — feasibility and hardware cost."""
import pickle
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from t2s.collision.geom import part_geom_from_record  # noqa: E402
from t2s.collision.validate import Validator  # noqa: E402
from t2s.constraints.stage2_model import Stage2Model  # noqa: E402
from t2s.objectives.metrics import part_phys  # noqa: E402
from t2s.optimise.brkga import Evaluator, IslandState, LahcState, best_candidates, run_island, run_lahc  # noqa: E402
from t2s.optimise.scalarize import Normaliser, slider_weights  # noqa: E402

recs = pickle.loads(Path(sys.argv[1]).read_bytes())
for pid in ("pcb_obc", "pcb_eps"):
    recs[pid].tags = ["pcb"]
ids = list(recs)
budget = float(sys.argv[2]) if len(sys.argv) > 2 else 60
mode = sys.argv[3] if len(sys.argv) > 3 else "default"
val = Validator({i: part_geom_from_record(recs[i]) for i in ids})
m = Stage2Model(recs, mode, mfg=True)
ev = Evaluator(m, ids, {i: part_phys(recs[i]) for i in ids}, {i: recs[i].orient_bounds for i in ids},
               float(m.inner[0][2]), com_box=np.array([20.0, 20.0, 70.0]))
rng = np.random.default_rng(3)
w = slider_weights({"space": 25, "balance": 25, "inertia": 25, "feasibility": 25, "cost": 50}, 2, "manufacturable")
st = IslandState(pop=rng.random((60, m.dim)), rng=rng)
t0 = time.perf_counter()
run_island(st, ev, Normaliser(), w, 0.5, time_budget_s=budget * 0.6, ls_elites=4, ls_moves=10)
b = best_candidates(st, 1)[0]
lst = LahcState(current=b, best=b)
run_lahc(lst, ev, Normaliser(), w, 0.5, rng, time_budget_s=budget * 0.4)
b = lst.best
rep = val.validate(b.poses, m.spec(b.meta, relaxed=b.meta["overflow_mm"] > 0))
print(f"{mode}: {time.perf_counter() - t0:.0f}s cv={b.cv:.2f} overflow={b.meta['overflow_mm']:.1f} "
      f"unmounted={b.meta['unmounted']} C={b.meta.get('C'):.1f} L={b.raw['L']:.1f} com={np.round(b.raw['com'], 1).tolist()} "
      f"valid={rep.valid}")
kinds = {}
for pid, v in b.meta["mounts"].items():
    k = v.get("process", "stack" if "stack" in v.get("how", "") else "?")
    kinds[k] = kinds.get(k, 0) + 1
print("mount processes:", kinds)
for pid, v in list(b.meta["mounts"].items())[:6]:
    print(" ", pid, "->", v["how"])
