"""Constraint attribution (protocol §O.3): Stage 2 re-solved with each constraint family relaxed in turn.

Every run uses the same seed, the same warm start (constructive seeds) and the same evaluation budget, so the
differences are measured sensitivities of this search — "which constraint cost the most" — not a narrative.
Results are search results under relaxed rules: the box decoder keeps them free of box overlaps by construction,
but they are not certified by the validator and are never shown as Stage 2 layouts.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np

from ..core.fileio import atomic_write_text
from ..core.formfactor import COM_BOX
from ..objectives.metrics import part_phys
from ..optimise.brkga import Evaluator, IslandState, best_candidates, run_island, seed_keys
from ..optimise.scalarize import Normaliser, alpha_from, slider_weights
from .stage2_model import Stage2Model

FAMILIES = [
    ("none", "all Stage 2 rules (baseline)"),
    ("clearances", "clearances 2.2 / 1.2 mm → Stage 1 contact policy"),
    ("frame", "walls and corner rails removed"),
    ("pcb_stack", "PC/104 stack: boards placed freely"),
    ("harness", "harness channel / cable corridor removed"),
    ("mounting", "3 mm mounting layer and reach check removed"),
    ("com_box", "CDS COM box not enforced"),
]


def _run_one(records, mode, relax, sliders, generations, pop, seed, com_box=True):
    model = Stage2Model(records, mode, relax=set() if relax == "none" else {relax})
    ids = model.ids
    n = len(ids)
    lo = float(model.inner[0][2])
    ev = Evaluator(model, ids, {i: part_phys(records[i]) for i in ids}, {i: records[i].orient_bounds for i in ids},
                   lo, com_box=None if relax == "com_box" or not com_box else COM_BOX.copy())
    rng = np.random.default_rng(seed)
    seeds = []
    for order in (np.argsort([-(records[i].volume_mm3 or 0) for i in ids]),
                  np.argsort([-records[i].obb_extents_mm.min() for i in ids])):
        r = model.best_fit_all_orientations(list(order))
        hint = getattr(r, "keys_hint", None)
        o_of = {pid: o for pid, o, _ in r.poses}
        s = seed_keys(list(order), [o_of.get(i, model.allowed[i][0]) if o_of.get(i) in model.allowed[i]
                                    else model.allowed[i][0] for i in ids], [model.allowed[i] for i in ids])
        if hint is not None:
            s[n:2 * n] = hint[0]
            s = np.concatenate([s[:2 * n], hint[1]])
        seeds.append(np.concatenate([s, np.full(model.dim - len(s), 0.5)])[:model.dim])
    w = slider_weights(sliders, 2)
    alpha = alpha_from(sliders)
    norm = Normaliser()
    t0 = time.perf_counter()
    st = IslandState(pop=np.vstack([np.array(seeds), rng.random((pop - len(seeds), model.dim))]), rng=rng)
    # a fixed number of generations (not a time budget), so every row gets exactly the same search effort
    run_island(st, ev, norm, w, alpha, time_budget_s=1e9, max_generations=generations, ls_elites=3, ls_moves=8)
    b = best_candidates(st, 1)[0]
    meta = b.meta or {}
    return {
        "relaxed": relax, "cv": b.cv, "feasible": b.cv <= 0 and not b.unplaced,
        "length_used_mm": b.raw.get("L"), "overflow_mm": meta.get("overflow_mm"),
        "unmounted": len(meta.get("unmounted", [])), "unplaced": len(b.unplaced),
        "com_mm": b.raw.get("com"), "com_error_mm": b.raw.get("D"), "trace_kgm2": b.raw.get("T"),
        "evaluations": st.evaluations, "seconds": time.perf_counter() - t0,
    }


def run_attribution(records: dict, mode: str, sliders: dict, out_path: Path, generations: int = 40, pop: int = 40,
                    seed: int = 20261023) -> dict:
    out = {"status": "RUNNING", "mode": mode, "seed": seed, "generations": generations, "population": pop,
           "rows": [], "progress": 0.0,
           "note": "measured with the same seed and budget per row; search results under relaxed rules, not certified"}

    def save():
        atomic_write_text(out_path, json.dumps(out, indent=1, default=float))

    save()
    base = None
    for k, (fam, label) in enumerate(FAMILIES):
        r = _run_one(records, mode, fam, sliders, generations, pop, seed)
        r["label"] = label
        if fam == "none":
            base = r
        else:
            for key in ("length_used_mm", "overflow_mm", "com_error_mm", "cv"):
                if r.get(key) is not None and base.get(key) is not None:
                    r[f"delta_{key}"] = r[key] - base[key]
        out["rows"].append(r)
        out["progress"] = (k + 1) / len(FAMILIES)
        save()
    # seed-to-seed spread of the baseline: differences smaller than this are not attributable to a rule
    b2 = _run_one(records, mode, "none", sliders, generations, pop, seed + 1)
    if base is not None and base.get("length_used_mm") is not None and b2.get("length_used_mm") is not None:
        out["baseline_spread"] = {"length_used_mm": abs(base["length_used_mm"] - b2["length_used_mm"]),
                                  "cv": abs(base["cv"] - b2["cv"]), "second_seed": seed + 1}
        out["note"] += (f"; baseline repeated with seed {seed + 1}: used length differs by "
                        f"{out['baseline_spread']['length_used_mm']:.1f} mm and the violation measure by "
                        f"{out['baseline_spread']['cv']:.2f} — smaller differences are noise")
    rel = [r for r in out["rows"] if r["relaxed"] != "none"]
    if rel and base is not None:
        top = min(rel, key=lambda r: (r["cv"], r.get("length_used_mm") or 1e9))
        out["largest_effect"] = {"family": top["relaxed"], "label": top["label"],
                                 "text": f"relaxing '{top['label']}' lowered the violation measure from "
                                         f"{base['cv']:.2f} to {top['cv']:.2f} and the used length by "
                                         f"{(base['length_used_mm'] or 0) - (top['length_used_mm'] or 0):.1f} mm "
                                         "(same seed and budget)"}
    out["status"] = "DONE"
    save()
    return out


def attribution_job(records_path: str, mode: str, sliders: dict, out_path: str, opts: dict | None = None) -> str:
    import pickle
    records = pickle.loads(Path(records_path).read_bytes())
    run_attribution(records, mode, sliders, Path(out_path), **(opts or {}))
    return out_path
