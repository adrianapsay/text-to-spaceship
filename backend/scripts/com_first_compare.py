"""Centre-of-mass-first mode against the standard rules: the same fixed-effort Stage 2 search (the protocol of
scripts/feasibility_check.py — BRKGA + local search from two constructive seeds, budget in generations) with the
mode off and on, at the same sliders and seed. Reports the best layout's centre of mass, its error from the target,
the length used, whether it is feasible (search, validator, ±Z insertion order) and how long its brackets are.

Unlike feasibility_check.py (whose empty normaliser ranks by length alone), the search here scores by the sliders as
the app does: the normaliser is set from the feasible candidates evaluated so far, after the first population and
every NORM_EVERY generations (the app takes the archive's extremes and its recent candidates).

    python scripts/com_first_compare.py <seed> [--ctx context.pkl | --ff 3U --scale 0.55] [--set user|com_only]
                                        [--mode off|on] [--gens 25] [--pop 30] [--out f.jsonl]

--ctx: a search-context pickle written by the app (its scaled part records, as the app searches them); otherwise the
synthetic parts at --scale. --set user: the user's sliders of 2026-10-24 with Balance at 100 (Space 87, Inertia 10,
Feasibility 25, bracket budget 100); com_only: the same with Space 0.
"""
from __future__ import annotations

import argparse
import json
import pickle
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np

USER = {"space": 87.0, "balance": 100.0, "inertia": 10.0, "feasibility": 25.0, "mass_symmetry": 50.0, "cable": 0.0,
        "cost": 0.0, "speed_quality": 50.0, "bracket_budget": 100.0, "optional_parts": 75.0}
SETS = {"user": USER, "com_only": dict(USER, space=0.0)}
NORM_EVERY = 5


def search(recs, sliders, com_first, seed, gens, pop) -> dict:
    from t2s.collision.geom import part_geom_from_record
    from t2s.collision.validate import Validator
    from t2s.constraints.stage2_model import Stage2Model
    from t2s.core.formfactor import COM_BOX
    from t2s.mfg.rules import MFG_REACH, am_level
    from t2s.objectives.metrics import part_phys
    from t2s.optimise.brkga import Evaluator, IslandState, best_candidates, run_island, score, seed_keys
    from t2s.optimise.scalarize import Normaliser, alpha_from, slider_weights
    from t2s.service.worker import insertion_check
    model = Stage2Model(recs, "default", am_level=am_level(sliders["bracket_budget"]), com_first=com_first)
    ids, n = model.ids, model.n
    ev = Evaluator(model, ids, {i: part_phys(recs[i]) for i in ids}, {i: recs[i].orient_bounds for i in ids},
                   float(model.inner[0][2]), com_box=COM_BOX.copy(), optional=[])
    pool = []                                   # raw objectives of every feasible candidate evaluated
    evaluate = ev.evaluate

    def collect(keys):
        c = evaluate(keys)
        if c.cv <= 0 and not c.unplaced:
            pool.append(c.raw)
        return c
    ev.evaluate = collect
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
    w, alpha, norm = slider_weights(sliders, 2), alpha_from(sliders), Normaliser()
    t0 = time.perf_counter()
    st.cands = [ev.evaluate(k) for k in st.pop]
    st.evaluations += len(st.cands)
    done = 0
    while done < gens:
        if len(pool) >= 2:
            norm.update_from(pool)
        step = min(NORM_EVERY, gens - done)
        run_island(st, ev, norm, w, alpha, time_budget_s=1e9, max_generations=step, ls_elites=3, ls_moves=8)
        done += step
    if len(pool) >= 2:
        norm.update_from(pool)
    for c in st.cands:
        score(c, norm, w, alpha)
    secs = time.perf_counter() - t0
    b = best_candidates(st, 1)[0]
    meta = b.meta or {}
    brs = meta.get("brackets", [])
    gaps = [float(x["gap_mm"]) for x in brs]
    com = b.raw.get("com")
    out = {"evaluations": st.evaluations, "seconds": round(secs, 1), "cv": float(b.cv), "unplaced": len(b.unplaced),
           "feasible_evaluated": len(pool), "L_mm": b.raw.get("L"), "D_mm": b.raw.get("D"),
           "com_mm": [round(float(x), 2) for x in com] if com is not None else None,
           "unmounted": len(meta.get("unmounted", [])), "rod_end": meta.get("rod_end"),
           "com_shift_mm": meta.get("com_shift_mm"), "brackets": len(brs),
           "brackets_over_40mm": sum(g > MFG_REACH + 1e-6 for g in gaps),
           "bracket_gap_max_mm": round(max(gaps), 1) if gaps else None,
           "bracket_gap_mean_mm": round(float(np.mean(gaps)), 1) if gaps else None,
           "metal_am": sum(x["kind"] == "metal_am" for x in brs),
           "end_plate_brackets": sum(x.get("target_kind") == "end_plate" for x in brs)}
    out["search_feasible"] = bool(b.cv <= 0 and not b.unplaced)
    out["valid"] = out["insertion_ok"] = None
    if out["search_feasible"]:
        rep = Validator({p: part_geom_from_record(recs[p]) for p, _, _ in b.poses}).validate(b.poses, model.spec(meta))
        out["valid"] = bool(rep.valid)
        out["insertion_ok"] = insertion_check(SimpleNamespace(records=recs), b.poses, meta)["order"] is not None
    out["feasible"] = bool(out["search_feasible"] and out["valid"] and out["insertion_ok"])
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("seed", type=int)
    ap.add_argument("--ctx", default="")
    ap.add_argument("--ff", default="3U")
    ap.add_argument("--scale", type=float, default=0.55)
    ap.add_argument("--set", default="user", choices=sorted(SETS))
    ap.add_argument("--mode", default="on", choices=("off", "on"))
    ap.add_argument("--gens", type=int, default=25)
    ap.add_argument("--pop", type=int, default=30)
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    from t2s.core.formfactor import set_form_factor
    if a.ctx:
        ctx = pickle.loads(Path(a.ctx).read_bytes())
        set_form_factor(ctx.form_factor)
        recs, src = ctx.records, {"ctx": Path(a.ctx).name, "ff": ctx.form_factor, "scale": ctx.part_scale}
    else:
        set_form_factor(a.ff)
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from feasibility_check import records
        recs, src = records(a.scale), {"ff": a.ff, "scale": a.scale}
    row = {**src, "seed": a.seed, "set": a.set, "mode": a.mode, "gens": a.gens, "pop": a.pop}
    row.update(search(recs, SETS[a.set], a.mode == "on", a.seed, a.gens, a.pop))
    line = json.dumps(row, default=float)
    print(line)
    if a.out:
        with open(a.out, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")


if __name__ == "__main__":
    sys.exit(main())
