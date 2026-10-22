"""Benchmark runner (protocol §J.3): instances × presets × variants × seeds at a fixed evaluation budget.

Runs in spawned worker processes; each run's best layout is re-validated on the true meshes (collision and
constraint violations among validated outputs must be 0). Results stream to results.jsonl; benchmarks.json holds
the statistics the app shows and the evidence rows the algorithm selector uses.
"""
from __future__ import annotations

import json
import multiprocessing as mp
import os
import pickle
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from .stats import a12, a12_ci, friedman, frozen_normaliser, holm, hypervolume, norm_point, wilcoxon_p
from .variants import SELECTOR_ID, VARIANTS

PRESET_IDS = ("max_packing", "com_priority", "min_inertia", "balanced")
STAGE1_VARIANTS = ("V1", "V2", "V3", "V4", "V5", "V5m", "V6", "V7", "V9")
STAGE2_VARIANTS = ("V1", "V4", "V5", "V6")

_W: dict = {}


def _init(instances_path: str) -> None:
    for var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMBA_NUM_THREADS"):
        os.environ[var] = "1"
    _W["instances"] = {i.id: i for i in pickle.loads(Path(instances_path).read_bytes())}
    _W["setups"] = {}
    _W["validators"] = {}


def _job(inst_id: str, preset: str, variant: str, seed: int, budget: float) -> dict:
    import psutil
    from ..collision.geom import part_geom_from_record
    from ..collision.validate import StageSpec, Validator
    from ..objectives.metrics import ENCLOSURE_HI, ENCLOSURE_LO
    from .variants import make_setup, run_variant
    inst = _W["instances"][inst_id]
    key = (inst_id, preset)
    if key not in _W["setups"]:
        _W["setups"][key] = make_setup(inst, preset)
    setup = _W["setups"][key]
    res = run_variant(setup, variant, seed, budget)
    b = res["best"]
    if inst_id not in _W["validators"]:
        _W["validators"][inst_id] = Validator({p: part_geom_from_record(r) for p, r in inst.records.items()})
    val = _W["validators"][inst_id]
    valid, violations, feasible = None, None, b.cv <= 0 and not b.unplaced
    if not b.unplaced:
        if inst.stage == 2:
            model = setup.decoders["box"]
            spec = model.spec(b.meta or {}, relaxed=(b.meta or {}).get("overflow_mm", 0) > 0)
        else:
            spec = StageSpec(1, ENCLOSURE_LO, ENCLOSURE_HI, 0.0, 0.0)
        rep = val.validate(b.poses, spec, want_planes=False)
        valid, violations = rep.valid, len(rep.violations)
    mem = psutil.Process().memory_info()
    return {"instance": inst_id, "preset": preset, "variant": variant, "seed": seed, "budget": budget,
            "used": res["used"], "seconds": res["seconds"], "first_valid": res["first_valid"],
            "raw": {k: v for k, v in b.raw.items() if k != "com"}, "com": b.raw.get("com"), "cv": b.cv,
            "g_internal": b.g, "unplaced": len(b.unplaced), "feasible": bool(feasible), "valid": valid,
            "violations": violations, "front": res["front"], "trace": res["trace"],
            "peak_rss_mb": getattr(mem, "peak_wset", getattr(mem, "rss", 0)) / 2 ** 20,
            "poses": [(p, int(o), [int(round(v * 1000)) for v in t]) for p, o, t in b.poses],
            "meta": {k: (b.meta or {}).get(k) for k in ("overflow_mm", "unmounted")} if inst.stage == 2 else None}


def build_jobs(instances, presets=PRESET_IDS, seeds: int = 10, stage2_presets=("balanced",), variants=None):
    jobs = []
    for inst in instances:
        vs = variants or (STAGE2_VARIANTS if inst.stage == 2 else STAGE1_VARIANTS)
        for preset in (stage2_presets if inst.stage == 2 else presets):
            for v in vs:
                for s in range(seeds):
                    jobs.append((inst.id, preset, v, 1000 + s))
    return jobs


def run_benchmarks(instances, out_dir: Path, budget: float = 2000, seeds: int = 10, workers: int = 8,
                   presets=PRESET_IDS, variants=None, progress=None, stage2_presets=("balanced",)) -> dict:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ipath = out_dir / "instances.pkl"
    ipath.write_bytes(pickle.dumps(list(instances), protocol=pickle.HIGHEST_PROTOCOL))
    jobs = build_jobs(instances, presets, seeds, stage2_presets, variants)
    results = []
    t0 = time.perf_counter()
    meta = {"budget": budget, "seeds": seeds, "jobs": len(jobs), "workers": workers,
            "started": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    with open(out_dir / "results.jsonl", "w", encoding="utf-8") as fh, \
            ProcessPoolExecutor(max_workers=workers, mp_context=mp.get_context("spawn"), initializer=_init,
                                initargs=(str(ipath),)) as pool:
        futs = {pool.submit(_job, *j, budget): j for j in jobs}
        for k, f in enumerate(as_completed(futs)):
            try:
                r = f.result()
            except Exception as exc:  # noqa: BLE001 - recorded, never hidden
                j = futs[f]
                r = {"instance": j[0], "preset": j[1], "variant": j[2], "seed": j[3], "error": repr(exc)}
            results.append(r)
            fh.write(json.dumps(r, default=float) + "\n")
            fh.flush()
            if progress:
                progress((k + 1) / len(jobs), r)
    meta["seconds"] = time.perf_counter() - t0
    summary = summarise(results, instances, meta)
    (out_dir / "benchmarks.json").write_text(json.dumps(summary, indent=1, default=float), encoding="utf-8")
    return summary


def summarise(results: list[dict], instances, meta: dict) -> dict:
    inst = {i.id: i for i in instances}
    ok = [r for r in results if "error" not in r]
    errors = [r for r in results if "error" in r]
    out = {"status": "DONE", **meta, "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "instances": [{"id": i.id, "label": i.label, "stage": i.stage, "parts": len(i.records),
                          "known_optimum_mm": i.known_optimum_mm, "notes": i.notes} for i in instances],
           "algorithms": [{"id": k, "label": v} for k, v in VARIANTS.items()],
           "rows": [], "summary": [], "tests": [], "curves": {}, "hv_table": [], "errors": errors[:50],
           "validation": {"runs": len(ok), "validated_outputs": sum(1 for r in ok if r.get("valid")),
                          "invalid_outputs": sum(1 for r in ok if r.get("valid") is False)}}
    from ..optimise.scalarize import PRESETS, slider_weights
    blocks = {}
    groups = {}
    for r in ok:
        groups.setdefault((r["instance"], r["preset"]), []).append(r)
    for (iid, preset), rs in sorted(groups.items()):
        stage = inst[iid].stage
        feas = [r for r in rs if r["feasible"]]
        nz = frozen_normaliser([r["raw"] for r in feas] or [r["raw"] for r in rs])
        w = slider_weights(PRESETS[preset], stage)
        alpha = 0.5
        for r in rs:
            r["g"] = _g(r, nz, w, alpha)
            r["hv"] = hypervolume(r["front"], nz)
            out["rows"].append({"instance": iid, "preset": preset, "algorithm": r["variant"], "seed": r["seed"],
                                "L": r["raw"].get("L"), "D": r["raw"].get("D"), "I": r["raw"].get("T"),
                                "g": r["g"], "cv": r["cv"], "feasible": r["feasible"], "valid": r["valid"],
                                "runtime_s": r["seconds"], "hv": r["hv"], "first_valid": r["first_valid"],
                                "peak_rss_mb": r["peak_rss_mb"]})
        by_v = {}
        for r in rs:
            by_v.setdefault(r["variant"], []).append(r)
        med = {}
        for v, vr in sorted(by_v.items()):
            vr = sorted(vr, key=lambda r: r["seed"])
            gs = np.array([r["g"] for r in vr], float)
            Ls = np.array([r["raw"].get("L", np.nan) for r in vr], float)
            Ds = np.array([r["raw"].get("D", np.nan) for r in vr], float)
            hv = np.array([r["hv"] if r["hv"] is not None else np.nan for r in vr], float)
            med[v] = float(np.median(gs))
            out["summary"].append({
                "instance": iid, "preset": preset, "algorithm": v, "n": len(vr),
                "feasible": sum(1 for r in vr if r["feasible"]), "valid": sum(1 for r in vr if r["valid"]),
                "median_g": float(np.median(gs)), "iqr_g": [float(np.percentile(gs, 25)), float(np.percentile(gs, 75))],
                "median_L": float(np.nanmedian(Ls)), "best_L": float(np.nanmin(Ls)),
                "median_D": float(np.nanmedian(Ds)), "median_hv": float(np.nanmedian(hv)) if np.any(np.isfinite(hv)) else None,
                "median_runtime_s": float(np.median([r["seconds"] for r in vr])),
                "median_first_valid": _median_or_none([r["first_valid"] for r in vr]),
                "gap_to_optimum_mm": (float(np.nanmedian(Ls)) - inst[iid].known_optimum_mm)
                if inst[iid].known_optimum_mm else None})
            out["curves"][f"{iid}|{preset}|{v}"] = _curve(vr)
        blocks[f"{iid}|{preset}"] = med
        # paired tests: the full hybrid against every other variant (protocol §D.4)
        ref = "V5" if "V5" in by_v else None
        if ref:
            tests = []
            xs = {r["seed"]: r["g"] for r in by_v[ref]}
            for v, vr in sorted(by_v.items()):
                if v == ref:
                    continue
                ys = {r["seed"]: r["g"] for r in vr}
                common = sorted(set(xs) & set(ys))
                x, y = [xs[s] for s in common], [ys[s] for s in common]
                lo, hi = a12_ci(x, y)
                tests.append({"instance": iid, "preset": preset, "a": ref, "b": v, "n": len(common),
                              "p": wilcoxon_p(x, y), "a12": a12(x, y), "a12_ci": [lo, hi]})
            for t, ph in zip(tests, holm([t["p"] for t in tests])):
                t["p_holm"] = ph
                t["verdict"] = ("hybrid better" if ph < 0.05 and t["a12"] > 0.5 else
                                "hybrid worse" if ph < 0.05 and t["a12"] < 0.5 else "inconclusive")
            out["tests"] += tests
    out["friedman"] = friedman({k: v for k, v in blocks.items() if not k.startswith("I2")})
    out["adoption"] = adoption(out["tests"], [i.id for i in instances if i.stage == 1])
    out["evidence"] = evidence(out["summary"], inst)
    # hv table (across all Stage 1 blocks): median hypervolume per variant
    for v in VARIANTS:
        hvs = [s["median_hv"] for s in out["summary"] if s["algorithm"] == v and s["median_hv"] is not None]
        if hvs:
            out["hv_table"].append({"algorithm": v, "hv": float(np.median(hvs)), "n": len(hvs)})
    return out


def _median_or_none(xs):
    xs = [x for x in xs if x is not None]
    return float(np.median(xs)) if xs else None


def _g(r, nz, w, alpha):
    if not r["feasible"] or any(k not in nz for k in ("L", "D", "T", "P")):
        return 1e3 + float(r["cv"])                        # infeasible runs rank behind every feasible one
    raw = r["raw"]
    n = {k: (raw[k] - nz[k][0]) / (nz[k][1] - nz[k][0]) for k in ("L", "D", "T", "P") if k in raw}
    terms = []
    for k, wk in w.items():
        if k == "I":
            terms.append(wk * (alpha * n["T"] + (1 - alpha) * n["P"]))
        elif k in n:
            terms.append(wk * n[k])
    return float(max(terms) + 1e-3 * sum(terms))


def _curve(vr):
    """Anytime curve: median and quartiles of the best (internal) score at each budget mark."""
    marks = sorted({m for r in vr for m, *_ in r["trace"]})
    t, med, q1, q3 = [], [], [], []
    for m in marks:
        vals = []
        for r in vr:
            last = [g if cv <= 0 else 1e3 + cv for mm, cv, g, _ in r["trace"] if mm <= m]
            if last:
                vals.append(last[-1])
        if len(vals) == len(vr):
            t.append(m)
            med.append(float(np.median(vals)))
            q1.append(float(np.percentile(vals, 25)))
            q3.append(float(np.percentile(vals, 75)))
    return {"t": t, "median": med, "q1": q1, "q3": q3}


def adoption(tests: list[dict], stage1_instances: list[str]) -> dict:
    """§D.4: the hybrid ships as default if A12 ≥ 0.64 with Holm p < 0.05 on at least half the instances (vs the
    single algorithms) and it is significantly worse on none."""
    per_inst = {}
    for t in tests:
        if t["instance"] not in stage1_instances or t["b"] in ("V5m", "V7"):
            continue
        per_inst.setdefault(t["instance"], []).append(t)
    wins = [i for i, ts in per_inst.items() if ts and all(x["a12"] >= 0.64 and x["p_holm"] < 0.05 for x in ts)]
    worse = [i for i, ts in per_inst.items() if any(x["verdict"] == "hybrid worse" for x in ts)]
    ships = bool(per_inst) and len(wins) >= len(per_inst) / 2 and not worse
    return {"instances_tested": sorted(per_inst), "hybrid_wins_on": sorted(wins), "hybrid_worse_on": sorted(worse),
            "ships_as_default": ships,
            "text": ("the hybrid meets the pre-registered adoption rule" if ships else
                     "the hybrid does not meet the pre-registered adoption rule (A12 ≥ 0.64 with Holm p < 0.05 on at "
                     "least half the instances, worse on none); the simplest variant that is not significantly worse "
                     "should ship")}


def evidence(summary: list[dict], inst: dict) -> list[dict]:
    """Rows for the performance-based selector (Addendum 3.1): median score per selector algorithm and weights."""
    from ..optimise.scalarize import PRESETS, slider_weights
    from ..optimise.selector import part_stats
    stats = {k: part_stats(list(v.records.values())) for k, v in inst.items()}
    rows = []
    for s in summary:
        alg = SELECTOR_ID.get(s["algorithm"])
        if alg is None or alg == "box_constructive":
            continue
        stage = inst[s["instance"]].stage
        st = stats[s["instance"]]
        rows.append({"stage": stage, "algorithm": alg, "instance": s["instance"], "preset": s["preset"],
                     "weights": slider_weights(PRESETS[s["preset"]], stage), "median_g": s["median_g"], "n": s["n"],
                     "variant": s["algorithm"], "n_parts": st.n_parts, "box_overhead": st.box_overhead})
    return rows
