"""M4/M6 probe: single-process BRKGA quality and speed on the dataset (development check, not a benchmark)."""
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from t2s.collision.geom import part_geom_from_record  # noqa: E402
from t2s.collision.validate import StageSpec, Validator  # noqa: E402
from t2s.decoders.box_decoder import PLACEMENT_GAP_STAGE1, BoxDecoder, ProxyPart  # noqa: E402
from t2s.objectives.metrics import ENCLOSURE_HI, ENCLOSURE_LO, part_phys  # noqa: E402
from t2s.optimise.brkga import Evaluator, IslandState, best_candidates, run_island, seed_keys  # noqa: E402
from t2s.optimise.scalarize import PRESETS, Normaliser, alpha_from, slider_weights  # noqa: E402
from t2s.parts.build import build_part  # noqa: E402

ROOT = Path(__file__).resolve().parents[2] / "data" / "synthetic"
man = json.loads((ROOT / "manifest.json").read_text())
recs = {}
for p in man["parts"]:
    if p["role"] == "packable":
        recs[p["name"]] = build_part((ROOT / p["file"]).read_bytes(), p["name"], p["name"], file=p["file"])
ids = list(recs)
dec = BoxDecoder([ProxyPart(i, recs[i].boxes, recs[i].allowed_orients) for i in ids], ENCLOSURE_LO, ENCLOSURE_HI,
                 PLACEMENT_GAP_STAGE1)
ev = Evaluator(dec, ids, {i: part_phys(recs[i]) for i in ids}, {i: recs[i].orient_bounds for i in ids}, ENCLOSURE_LO[2])
geoms = {i: part_geom_from_record(recs[i]) for i in ids}
val = Validator(geoms)
spec = StageSpec(1, ENCLOSURE_LO, ENCLOSURE_HI, 0.0, 0.0)
n = len(ids)
seeds = []
for order in (np.argsort([-recs[i].volume_mm3 for i in ids]), np.argsort([-recs[i].obb_extents_mm.min() for i in ids])):
    r = dec.best_fit_all_orientations(list(order))
    o_of = {pid: o for pid, o, _ in r.poses}
    seeds.append(seed_keys(list(order), [o_of.get(i, recs[i].allowed_orients[0]) for i in ids],
                           [recs[i].allowed_orients for i in ids]))
for preset in ("max_packing", "balanced"):
    rng = np.random.default_rng(42)
    pop = np.vstack([np.array(seeds), rng.random((60 - len(seeds), 3 * n))])
    st = IslandState(pop=pop, rng=rng)
    norm = Normaliser()
    w = slider_weights(PRESETS[preset], 1)
    t0 = time.perf_counter()
    st = run_island(st, ev, norm, w, alpha_from({}), time_budget_s=2.0)          # warm-up for a normaliser
    norm.update_from([c.raw for c in st.cands if c.cv == 0])
    st = run_island(st, ev, norm, w, alpha_from({}), time_budget_s=20.0)
    dt = time.perf_counter() - t0
    best = best_candidates(st, 1)[0]
    rep = val.validate(best.poses, spec)
    feas = [c for c in st.cands if c.cv == 0]
    print(f"  constructive seeds L={[round(ev.evaluate(s).raw['L'], 1) for s in seeds]} "
          f"population min L={min(c.raw['L'] for c in feas):.1f} min D={min(c.raw['D'] for c in feas):.1f}")
    print(f"{preset:12s} gens={st.generations} evals={st.evaluations} ({st.evaluations / dt:.0f}/s) "
          f"L={best.raw['L']:.1f} D={best.raw['D']:.1f} T={best.raw['T']:.4e} cv={best.cv} valid={rep.valid} "
          f"com={np.round(best.raw['com'], 1).tolist()}")
