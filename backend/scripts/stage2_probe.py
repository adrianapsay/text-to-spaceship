"""M7 probe: Stage 2 model in default / soft / continuous modes (development check)."""
import pickle
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from t2s.collision.geom import part_geom_from_record  # noqa: E402
from t2s.collision.validate import Validator  # noqa: E402
from t2s.constraints.stage2_model import Stage2Model  # noqa: E402

recs = pickle.loads(Path(sys.argv[1]).read_bytes())
for pid in ("pcb_obc", "pcb_eps"):
    recs[pid].tags = ["pcb"]
ids = list(recs)
n = len(ids)
val = Validator({i: part_geom_from_record(recs[i]) for i in ids})
for mode in ("default", "soft", "continuous"):
    m = Stage2Model(recs, mode)
    rng = np.random.default_rng(0)
    t0 = time.perf_counter()
    stats = {"placed_all": 0, "mount_ok": 0, "valid": 0}
    best = None
    N = 60
    for _ in range(N):
        k = rng.random(m.dim)
        r = m.decode(list(np.argsort(k[:n])), k[n:2 * n], k[2 * n:])
        if not r.unplaced:
            stats["placed_all"] += 1
            if r.penalty == 0:
                stats["mount_ok"] += 1
                if best is None or r.length_top < best[0]:
                    best = (r.length_top, r)
    dt = (time.perf_counter() - t0) / N
    c = m.best_fit_all_orientations(list(np.argsort([-recs[i].obb_extents_mm.min() for i in ids])))
    rep = val.validate(c.poses, m.spec(c.meta, relaxed=True)) if not c.unplaced else None
    print(f"{mode:10s} decode {1e3 * dt:.1f} ms; of {N} random: all placed {stats['placed_all']}, penalty-free "
          f"{stats['mount_ok']}; constructive: unplaced={c.unplaced} penalty={c.penalty:.2f} overflow="
          f"{c.meta['overflow_mm']:.1f} mm unmounted={len(c.meta['unmounted'])} relaxed-valid={rep.valid if rep else None} "
          f"{rep.violations[:3] if rep else ''}")
    fails = [f"{p}: {v['how']}" for p, v in c.meta["mounts"].items() if not v["ok"]]
    print("   constructive mount failures:", fails[:6], "| meta:", {k: v for k, v in c.meta.items()
                                                                   if k in ("corridor", "stack_span", "H")})
    if best:
        r = best[1]
        rep = val.validate(r.poses, m.spec(r.meta))
        print(f"   best random fully-mounted layout: L={best[0]:.1f} valid={rep.valid} {rep.violations[:3]}")
    # short length-and-feasibility GA
    from t2s.objectives.metrics import part_phys
    from t2s.optimise.brkga import Evaluator, IslandState, best_candidates, run_island
    from t2s.optimise.scalarize import Normaliser
    ev = Evaluator(m, ids, {i: part_phys(recs[i]) for i in ids}, {i: recs[i].orient_bounds for i in ids},
                   float(m.inner[0][2]), com_box=np.array([20.0, 20.0, 70.0]))
    st = IslandState(pop=rng.random((60, m.dim)), rng=rng)
    t0 = time.perf_counter()
    budget = float(sys.argv[2]) if len(sys.argv) > 2 else 20.0
    run_island(st, ev, Normaliser(), {"L": 1.0}, 0.5, time_budget_s=budget * 0.6, ls_elites=4, ls_moves=10)
    from t2s.optimise.brkga import LahcState, run_lahc
    lst = LahcState(current=best_candidates(st, 1)[0], best=best_candidates(st, 1)[0])
    run_lahc(lst, ev, Normaliser(), {"L": 1.0}, 0.5, rng, time_budget_s=budget * 0.4)
    b = lst.best
    rep = val.validate(b.poses, m.spec(b.meta, relaxed=True))
    print(f"   GA {time.perf_counter() - t0:.0f}s: cv={b.cv:.2f} overflow={b.meta['overflow_mm']:.1f} mm unmounted="
          f"{b.meta['unmounted']} com={np.round(b.raw.get('com', [0, 0, 0]), 1).tolist()} L={b.raw['L']:.1f} "
          f"relaxed-valid={rep.valid} {rep.violations[:2]}")
