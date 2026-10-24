"""V2 "Find largest size that fits": bisection on the part-size factor (Stage 2).

At each size a fixed-effort Stage 2 search (BRKGA + local search, same seed and budget every time) looks for a layout
with every rule met; its best layout is then certified by the validator. The largest size with a certified layout,
to 1 % of full size, is reported. This is SEARCH-BASED: "not found" at a size does not prove no layout exists there,
and the bisection assumes that what fits at one size also fits at a smaller one (true for the rules, not guaranteed
for a budget-limited search). Every tried size is listed.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np

from ..core.fileio import atomic_write_text

NOTE = ("search-based: the largest size at which a fixed-effort search found a layout meeting every Stage 2 rule "
        "(certified by the validator); not a proof that larger sizes are impossible")


def _try(records: dict, scale: float, mode: str, sliders: dict, am_allowed: bool | int, generations: int, pop: int,
         seed: int) -> dict:
    """am_allowed: the bracket budget's metal-AM step (mfg.rules.am_level; True / False = step 1 / 0). With the
    sliders asking for it, the search runs in centre-of-mass-first mode (stage2_model.com_first_mode), as the app's."""
    from ..collision.geom import part_geom_from_record
    from ..collision.validate import Validator
    from ..constraints.stage2_model import Stage2Model, com_first_mode
    from ..core.formfactor import COM_BOX
    from ..objectives.metrics import part_phys
    from ..optimise.brkga import Evaluator, IslandState, best_candidates, run_island, seed_keys
    from ..optimise.scalarize import Normaliser, alpha_from, slider_weights
    from ..parts.scale import scale_part
    t0 = time.perf_counter()
    recs = {pid: scale_part(r, scale) for pid, r in records.items()}
    model = Stage2Model(recs, mode, am_level=int(am_allowed), com_first=com_first_mode(sliders, int(am_allowed)))
    ids = model.ids
    n = len(ids)
    optional = [p for p in ids if "optional" in (recs[p].tags or [])]
    ev = Evaluator(model, ids, {i: part_phys(recs[i]) for i in ids}, {i: recs[i].orient_bounds for i in ids},
                   float(model.inner[0][2]), com_box=COM_BOX.copy(), optional=optional)
    rng = np.random.default_rng(seed)
    seeds = []
    for order in (np.argsort([-(recs[i].volume_mm3 or 0) for i in ids]),
                  np.argsort([-recs[i].obb_extents_mm.min() for i in ids])):
        r = model.best_fit_all_orientations(list(order))
        hint = getattr(r, "keys_hint", None)
        o_of = {pid: o for pid, o, _ in r.poses}
        s = seed_keys(list(order), [o_of.get(i) if o_of.get(i) in model.allowed[i] else model.allowed[i][0]
                                    for i in ids], [model.allowed[i] for i in ids])
        if hint is not None:
            s[n:2 * n] = hint[0]
            s = np.concatenate([s[:2 * n], hint[1]])
        seeds.append(np.concatenate([s, np.full(model.dim - len(s), 0.5)])[:model.dim])
    st = IslandState(pop=np.vstack([np.array(seeds), rng.random((max(pop - len(seeds), 0), model.dim))]), rng=rng)
    run_island(st, ev, Normaliser(), slider_weights(sliders, 2, optional=bool(optional)), alpha_from(sliders),
               time_budget_s=1e9, max_generations=generations, ls_elites=3, ls_moves=8)
    b = best_candidates(st, 1)[0]
    meta = b.meta or {}
    feasible = b.cv <= 0 and not b.unplaced
    certified = False
    if feasible:
        rep = Validator({p: part_geom_from_record(recs[p]) for p, _, _ in b.poses}).validate(b.poses, model.spec(meta))
        certified = bool(rep.valid)
    return {"scale": round(scale, 4), "pct": round(100 * scale, 1), "found": bool(feasible and certified),
            "search_feasible": bool(feasible), "certified": certified, "cv": float(b.cv),
            "length_used_mm": b.raw.get("L"), "unmounted": len(meta.get("unmounted", [])),
            "overflow_mm": meta.get("overflow_mm"), "optional_left_out": meta.get("dropped", []),
            "evaluations": st.evaluations, "seconds": time.perf_counter() - t0}


def run_largest_size(records: dict, mode: str, sliders: dict, out_path: Path, am_allowed: bool = True,
                     lo: float = 0.5, hi: float = 1.0, tol: float = 0.01, generations: int = 25, pop: int = 30,
                     seed: int = 20261022) -> dict:
    out = {"status": "RUNNING", "mode": mode, "seed": seed, "generations": generations, "population": pop,
           "rows": [], "progress": 0.0, "largest_pct": None, "note": NOTE}
    steps = 2 + int(np.ceil(np.log2((hi - lo) / tol)))

    def save():
        atomic_write_text(out_path, json.dumps(out, indent=1, default=float))

    def attempt(s):
        r = _try(records, s, mode, sliders, am_allowed, generations, pop, seed)
        out["rows"].append(r)
        out["progress"] = min(1.0, len(out["rows"]) / steps)
        save()
        return r["found"]

    save()
    if attempt(hi):
        out["largest_pct"] = round(100 * hi, 1)
    elif not attempt(lo):
        out["largest_pct"] = None
        out["verdict"] = f"no layout found even at {100 * lo:.0f} % (search-based)"
    else:
        step = max(1, int(round(100 * tol)))            # whole percentages
        a, b = int(round(100 * lo)), int(round(100 * hi))   # found at a %, not found at b %
        while b - a > step:
            mid = (a + b) // 2
            if attempt(mid / 100.0):
                a = mid
            else:
                b = mid
        out["largest_pct"] = float(a)
    if out["largest_pct"] is not None:
        out["verdict"] = f"largest size with a certified layout: {out['largest_pct']:.0f} % (search-based)"
    out["status"] = "DONE"
    out["progress"] = 1.0
    save()
    return out


def largest_size_job(records_path: str, mode: str, sliders: dict, out_path: str, am_allowed: bool,
                     opts: dict | None = None) -> str:
    import pickle
    records = pickle.loads(Path(records_path).read_bytes())
    run_largest_size(records, mode, sliders, Path(out_path), am_allowed, **(opts or {}))
    return out_path
