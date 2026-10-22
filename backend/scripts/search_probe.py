"""M6 probe: compare BRKGA, BRKGA + memetic LS and LAHC at equal time (development check, not the M8 benchmark)."""
import pickle
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from t2s.decoders.box_decoder import PLACEMENT_GAP_STAGE1, BoxDecoder, ProxyPart  # noqa: E402
from t2s.objectives.metrics import ENCLOSURE_HI, ENCLOSURE_LO, part_phys  # noqa: E402
from t2s.optimise.brkga import (Evaluator, IslandState, LahcState, best_candidates, run_island, run_lahc,  # noqa: E402
                                seed_keys)
from t2s.optimise.scalarize import PRESETS, Normaliser, alpha_from, slider_weights  # noqa: E402

recs = pickle.loads(Path(sys.argv[1]).read_bytes())
budget = float(sys.argv[2]) if len(sys.argv) > 2 else 20.0
ids = list(recs)
n = len(ids)
if len(sys.argv) > 3 and sys.argv[3].startswith("hm"):
    from t2s.decoders.heightmap import HeightmapDecoder
    dec = HeightmapDecoder({i: (recs[i].v, recs[i].f, recs[i].allowed_orients) for i in ids}, ENCLOSURE_LO,
                           ENCLOSURE_HI, h=float(sys.argv[3][2:] or 2))
else:
    dec = BoxDecoder([ProxyPart(i, recs[i].boxes, recs[i].allowed_orients) for i in ids], ENCLOSURE_LO, ENCLOSURE_HI,
                     PLACEMENT_GAP_STAGE1)
ev = Evaluator(dec, ids, {i: part_phys(recs[i]) for i in ids}, {i: recs[i].orient_bounds for i in ids}, ENCLOSURE_LO[2])
seeds = []
for order in (np.argsort([-recs[i].volume_mm3 for i in ids]), np.argsort([-recs[i].obb_extents_mm.min() for i in ids])):
    r = dec.best_fit_all_orientations(list(order))
    o_of = {pid: o for pid, o, _ in r.poses}
    seeds.append(seed_keys(list(order), [o_of[i] for i in ids], [recs[i].allowed_orients for i in ids]))
print("constructive seeds L:", [round(dec.decode(list(np.argsort(s[:n], kind="stable")), s[n:2 * n], s[2 * n:]).length_top, 1)
                                for s in seeds])
w = slider_weights(PRESETS["max_packing"], 1)
alpha = alpha_from({})
# one shared normaliser from a random sample so g values are comparable across variants
rng0 = np.random.default_rng(0)
norm = Normaliser()
norm.update_from([ev.evaluate(k).raw for k in rng0.random((200, 3 * n))] + [ev.evaluate(s).raw for s in seeds])
for seed in (1, 2, 3):
    out = []
    for name in ("brkga", "brkga+ls", "lahc"):
        rng = np.random.default_rng(seed)
        t0 = time.perf_counter()
        if name == "lahc":
            c0 = ev.evaluate(seeds[1])
            st = LahcState(current=c0, best=c0)
            while time.perf_counter() - t0 < budget:
                run_lahc(st, ev, norm, w, alpha, rng, time_budget_s=0.5)
            best, evals = st.best, st.evaluations
        else:
            pop = np.vstack([np.array(seeds), rng.random((60 - len(seeds), 3 * n))])
            st = IslandState(pop=pop, rng=rng)
            ls = (2, 6) if name == "brkga+ls" else (0, 0)
            while time.perf_counter() - t0 < budget:
                run_island(st, ev, norm, w, alpha, time_budget_s=0.5, ls_elites=ls[0], ls_moves=ls[1])
            best, evals = best_candidates(st, 1)[0], st.evaluations
        out.append(f"{name}: g={best.g:.4f} L={best.raw['L']:.1f} D={best.raw['D']:.1f} evals={evals}")
    print(f"seed {seed}: " + " | ".join(out))
