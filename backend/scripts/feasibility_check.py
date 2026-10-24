"""Fixed-effort Stage 2 feasibility check on the synthetic parts (the protocol of bench/largest_size and of the V2
feasibility runs: BRKGA + local search from two constructive seeds, budget in generations, not seconds).

    python scripts/feasibility_check.py <3U|6U|12U> <scale> <seed> [--gens 25] [--pop 30] [--label x] [--out f.jsonl]
                                        [--dump folder]     (the best layout's poses and meta, pickled)
    python scripts/feasibility_check.py <3U|6U|12U> <scale> <seed> --decode-bench 100 [--label x] [--out f.jsonl]

It runs against whichever `t2s` comes first on PYTHONPATH, so the same script measures the code before and after a
change. A layout counts as feasible when the search's best candidate has cv 0 (every part placed and mounted, inside
the length, COM inside the CDS box), the validator certifies it under its own rules, and a straight ±Z insertion order
exists — what the app requires before it reports a Stage 2 layout as feasible. One JSON line per run is printed (and
appended to --out).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np

SLIDERS = {"space": 51.0, "balance": 25.0, "inertia": 25.0, "feasibility": 25.0, "mass_symmetry": 50.0, "cable": 0.0,
           "cost": 0.0, "speed_quality": 50.0, "bracket_budget": 50.0, "optional_parts": 75.0}
DATA = Path(__file__).resolve().parents[2] / "data" / "synthetic"


def records(scale: float) -> dict:
    from t2s.parts.build import build_part
    from t2s.parts.scale import scale_part
    from t2s.service.project import suggest_tags
    man = json.loads((DATA / "manifest.json").read_text())
    out = {}
    for p in man["parts"]:
        if p["role"] == "packable":
            r = build_part((DATA / p["file"]).read_bytes(), p["name"], p["name"], file=p["file"])
            r.tags = suggest_tags(p["name"])
            out[p["name"]] = scale_part(r, scale)
    return out


def layout_facts(model, recs, poses, meta) -> dict:
    """Engineering facts of one decoded layout: mounting, deck and end-plate brackets, the stack, the COM shift."""
    brs = meta.get("brackets", [])
    mounts = meta.get("mounts", {})
    gap = None
    if meta.get("rod_end") and meta.get("stack_span") is not None:      # the stack's distance from its end plate
        lo, hi = model.inner
        gap = float(meta["stack_span"][0] - lo[2]) if meta["rod_end"] == "-z" else float(hi[2] - meta["stack_span"][1])
    return {"unmounted": len(meta.get("unmounted", [])), "stack_gap_mm": gap,
            "unmounted_why": {p: mounts.get(p, {}).get("how", "") for p in meta.get("unmounted", [])},
            "overflow_mm": float(meta.get("overflow_mm", 0.0)), "brackets": len(brs),
            "deck_brackets": sum(1 for b in brs if "PC/104" in str(b.get("target", ""))),
            "end_plate_brackets": sum(1 for b in brs if "end plate" in str(b.get("target", ""))),
            "rod_end": meta.get("rod_end"), "rod_model": meta.get("rod_model"),
            "stack_span": [float(x) for x in meta["stack_span"]] if meta.get("stack_span") is not None else None,
            "com_shift_mm": meta.get("com_shift_mm")}


def insertion(recs, poses, meta) -> dict:
    from t2s.service.worker import insertion_check
    ins = insertion_check(SimpleNamespace(records=recs), poses, meta)
    return {"insertion_ok": ins["order"] is not None, "stuck": ins["stuck"]}


def search(ff, scale, seed, gens, pop, dump: str = "", label: str = "") -> dict:
    from t2s.collision.geom import part_geom_from_record
    from t2s.collision.validate import Validator
    from t2s.constraints.stage2_model import Stage2Model
    from t2s.core.formfactor import COM_BOX
    from t2s.objectives.metrics import part_phys
    from t2s.optimise.brkga import Evaluator, IslandState, best_candidates, run_island, seed_keys
    from t2s.optimise.scalarize import Normaliser, alpha_from, slider_weights
    recs = records(scale)
    model = Stage2Model(recs, "default", am_level=1)
    ids, n = model.ids, model.n
    ev = Evaluator(model, ids, {i: part_phys(recs[i]) for i in ids}, {i: recs[i].orient_bounds for i in ids},
                   float(model.inner[0][2]), com_box=COM_BOX.copy(), optional=[])
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
    t0 = time.perf_counter()
    run_island(st, ev, Normaliser(), slider_weights(SLIDERS, 2), alpha_from(SLIDERS), time_budget_s=1e9,
               max_generations=gens, ls_elites=3, ls_moves=8)
    secs = time.perf_counter() - t0
    b = best_candidates(st, 1)[0]
    meta = b.meta or {}
    out = {"evaluations": st.evaluations, "seconds": round(secs, 1),
           "ms_per_evaluation": round(1e3 * secs / max(st.evaluations, 1), 1), "cv": float(b.cv),
           "unplaced": len(b.unplaced), "L_mm": b.raw.get("L"),
           "com_mm": [round(float(x), 2) for x in b.raw["com"]] if b.raw.get("com") is not None else None}
    out.update(layout_facts(model, recs, b.poses, meta))
    out["search_feasible"] = bool(b.cv <= 0 and not b.unplaced)
    out["valid"] = None
    out["insertion_ok"] = None
    if out["search_feasible"]:
        rep = Validator({p: part_geom_from_record(recs[p]) for p, _, _ in b.poses}).validate(b.poses, model.spec(meta))
        out["valid"] = bool(rep.valid)
        out["violations"] = [str(v) for v in rep.violations[:3]]
        out.update(insertion(recs, b.poses, meta))
        if "brackets" in meta or "rod_end" in meta:        # the same layout under the parts-only ±Z rule
            plain = {k: v for k, v in meta.items() if k not in ("brackets", "rod_end", "rod_model")}
            out["insertion_ok_parts_only"] = insertion(recs, b.poses, plain)["insertion_ok"]
    out["feasible"] = bool(out["search_feasible"] and out["valid"] and out["insertion_ok"])
    if dump:
        import pickle
        Path(dump).mkdir(parents=True, exist_ok=True)
        (Path(dump) / f"{label}_{ff}_{scale}_{seed}_{gens}.pkl").write_bytes(
            pickle.dumps({"poses": b.poses, "meta": meta, "raw": b.raw, "cv": b.cv, "unplaced": b.unplaced}))
    return out


def decode_bench(ff, scale, seed, count) -> dict:
    """Time per decode of random chromosomes (after 3 warm-up decodes), and how many decode to a layout with every
    part placed and mounted inside the length (no search pressure)."""
    from t2s.constraints.stage2_model import Stage2Model
    recs = records(scale)
    model = Stage2Model(recs, "default", am_level=1)
    n = model.n
    rng = np.random.default_rng(seed)
    keys = [rng.random(model.dim) for _ in range(count + 3)]
    times, ok = [], 0
    for i, k in enumerate(keys):
        t0 = time.perf_counter()
        r = model.decode(list(np.argsort(k[:n], kind="stable")), k[n:2 * n], k[2 * n:])
        dt = time.perf_counter() - t0
        if i < 3:
            continue
        times.append(dt)
        m = r.meta or {}
        ok += int(not r.unplaced and not m.get("unmounted") and m.get("overflow_mm", 0.0) <= 0)
    return {"decodes": count, "ms_per_decode_mean": round(1e3 * float(np.mean(times)), 1),
            "ms_per_decode_median": round(1e3 * float(np.median(times)), 1), "all_mounted": ok}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("ff")
    ap.add_argument("scale", type=float)
    ap.add_argument("seed", type=int)
    ap.add_argument("--gens", type=int, default=25)
    ap.add_argument("--pop", type=int, default=30)
    ap.add_argument("--decode-bench", type=int, default=0)
    ap.add_argument("--label", default="")
    ap.add_argument("--out", default="")
    ap.add_argument("--dump", default="")
    a = ap.parse_args()
    from t2s.core.formfactor import set_form_factor
    set_form_factor(a.ff)
    import t2s
    from t2s.mfg.rules import BRACKET_MODEL_VERSION
    row = {"label": a.label, "t2s": str(Path(t2s.__file__).parent), "bracket_model": BRACKET_MODEL_VERSION,
           "ff": a.ff, "scale": a.scale, "seed": a.seed}
    if a.decode_bench:
        row.update(decode_bench(a.ff, a.scale, a.seed, a.decode_bench))
    else:
        row.update(gens=a.gens, pop=a.pop)
        row.update(search(a.ff, a.scale, a.seed, a.gens, a.pop, a.dump, a.label))
    line = json.dumps(row, default=float)
    print(line)
    if a.out:
        with open(a.out, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")


if __name__ == "__main__":
    sys.exit(main())
