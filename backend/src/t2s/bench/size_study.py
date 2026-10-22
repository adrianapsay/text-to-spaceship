"""Size Study (Addendum 1.3, stopping rule Addendum 2.2).

Every part is scaled uniformly by s (geometry s, volume and mass s³ at constant density, inertia s⁵); the
enclosure, walls, rails, clearances and PC/104 pitch are not scaled. For each stage:

1. scan s = 1.00, 1.05, … with every algorithm and 5 seeds until no algorithm finds a valid layout, then bisect
   the last interval to 0.5 %; a stage with no valid layout at s = 1 is scanned downwards instead (labelled);
2. refine with successive halving: each round gives every live (size, algorithm) pair one more seed at a doubled
   budget, and per size only the better half of the algorithms stays live.

The study ends at the earliest of 6 h, a proven optimum at every size (best length within 0.1 mm of a rigorous
lower bound — reported as "proven optimal" only then), or convergence (no improvement > 0.1 mm and < 0.1 % in
score for 30 min, once every algorithm had ≥ 20 min per size). Every reported layout is validated on the
true (scaled) meshes; "largest size with a layout found" is never called a proof of impossibility unless a bound
proves it.
"""
from __future__ import annotations

import copy
import json
import multiprocessing as mp
import os
import pickle
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path


STAGE_VARIANTS = {1: ("V1", "V5", "V7"), 2: ("V1", "V5")}
LABELS = {"V1": "constructive box decoder", "V5": "hybrid, box decoder", "V7": "hybrid, height-map decoder"}


def scale_record(rec, s: float):
    """Uniformly scaled copy of a part record (about the canonical origin; packing is translation-invariant)."""
    r = copy.copy(rec)
    r.v = rec.v * s
    r.boxes = rec.boxes * s
    r.orient_bounds = rec.orient_bounds * s
    r.obb_extents_mm = rec.obb_extents_mm * s
    if rec.volume_mm3 is not None:
        r.volume_mm3 = rec.volume_mm3 * s ** 3
        r.com_can_mm = rec.com_can_mm * s
        r.j_unit_mm5 = rec.j_unit_mm5 * s ** 5
    if rec.hull_volume_mm3 is not None:
        r.hull_volume_mm3 = rec.hull_volume_mm3 * s ** 3
    if rec.mass_override_kg is not None:
        r.mass_override_kg = rec.mass_override_kg * s ** 3          # density held constant
    cov = copy.copy(rec.cover)
    cov.pieces = [replace(p, vertices=p.vertices * s, hull_volume=p.hull_volume * s ** 3) for p in rec.cover.pieces]
    cov.total_hull_volume = rec.cover.total_hull_volume * s ** 3
    r.cover = cov
    from ..geometry.proxies import COVER_DELTA
    r.cover_delta = COVER_DELTA * max(1.0, s)                       # the cover certificate's inflation scales too
    return r


def bounds_for(records: dict, stage: int) -> list[dict]:
    """Bounds drawn on the chart: rigorous volume bound (L ≥ c·s³) and the axis-aligned fit bound."""
    from ..constraints import stage2 as s2
    vol = sum(r.volume_mm3 or 0 for r in records.values())
    if stage == 1:
        area, width, length = 100.0 * 100.0, 100.0, 340.5
    else:
        w = s2.ENVELOPE[0] - 2 * s2.WALL - 2 * s2.C_WALL
        area, width, length = w * w, w, s2.ENVELOPE[2] - 2 * s2.WALL - 2 * s2.C_WALL
    c = vol / area
    mid = max(sorted(r.obb_extents_mm)[1] for r in records.values())
    return [{"id": "volume", "label": f"volume bound {c:.1f}·s³ mm", "kind": "rigorous", "coeff_mm": c, "exponent": 3,
             "max_scale": (length / c) ** (1 / 3) if c > 0 else None},
            {"id": "axis", "label": f"axis-aligned fit: s ≤ {width / mid:.3f}", "kind": "axis-aligned orientations only",
             "max_scale": width / mid}]


_W: dict = {}


def _init(records_path: str) -> None:
    for var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMBA_NUM_THREADS"):
        os.environ[var] = "1"
    _W["records"] = pickle.loads(Path(records_path).read_bytes())
    _W["setups"] = {}
    _W["validators"] = {}


def _job(stage: int, s: float, variant: str, seed: int, budget: float, preset: str) -> dict:
    from ..collision.geom import part_geom_from_record
    from ..collision.validate import StageSpec, Validator
    from ..objectives.metrics import ENCLOSURE_HI, ENCLOSURE_LO
    from .instances import Instance
    from .variants import make_setup, run_variant
    key = (stage, round(s, 6), preset)
    if key not in _W["setups"]:
        recs = {}
        for pid, r in _W["records"].items():
            c = scale_record(r, s)
            if stage == 2:
                c.tags = ["pcb"] if "pcb" in (r.name or "").lower() or "pcb" in r.tags else list(r.tags)
            recs[pid] = c
        inst = Instance(f"S{stage}x{s:.4f}", f"scale {s:.4f}", stage, recs)
        _W["setups"][key] = make_setup(inst, preset)
        _W["validators"][key] = Validator({p: part_geom_from_record(r) for p, r in recs.items()})
    setup, val = _W["setups"][key], _W["validators"][key]
    t0 = time.perf_counter()
    res = run_variant(setup, variant, seed, budget)
    b = res["best"]
    valid = False
    if not b.unplaced and b.cv <= 0:
        if stage == 2:
            spec = setup.decoders["box"].spec(b.meta or {})
        else:
            spec = StageSpec(1, ENCLOSURE_LO, ENCLOSURE_HI, 0.0, 0.0)
        valid = bool(val.validate(b.poses, spec, want_planes=False).valid)
    return {"stage": stage, "scale": round(s, 6), "algorithm": variant, "seed": seed, "budget": budget,
            "length_used_mm": b.raw.get("L"), "feasible": valid, "cv": b.cv, "g": b.g,
            "com_error_mm": b.raw.get("D"), "lambda_max_kgm2": b.raw.get("lambda_max"),
            "seconds": time.perf_counter() - t0, "unplaced": len(b.unplaced)}


class SizeStudy:
    def __init__(self, records: dict, out_path: Path, stages=(1, 2), seeds: int = 5, budget0: float = 1500,
                 max_hours: float = 6.0, workers: int = 3, preset: str = "max_packing", conv_minutes: float = 30.0,
                 min_minutes_per_combo: float = 20.0, step: float = 0.05, tol: float = 0.005):
        self.records, self.out_path = records, Path(out_path)
        self.stages, self.seeds, self.budget0 = tuple(stages), seeds, budget0
        self.max_s, self.workers, self.preset = max_hours * 3600.0, workers, preset
        self.conv_s, self.min_combo_s = conv_minutes * 60.0, min_minutes_per_combo * 60.0
        self.step, self.tol = step, tol
        self.rows: list[dict] = []
        self.t0 = time.perf_counter()
        self.last_improve = time.perf_counter()
        self.best: dict = {}                    # (stage, s, alg) -> (L, g)
        self.combo_time: dict = {}
        self.stop_reason = None
        self.phase = "scan"
        self.notes: list[str] = []

    # ------------------------------------------------------------------------------------------ output
    def save(self, status="RUNNING"):
        out = {"status": status, "phase": self.phase, "stop_reason": self.stop_reason, "preset": self.preset,
               "elapsed_s": time.perf_counter() - self.t0, "max_hours": self.max_s / 3600.0, "seeds": self.seeds,
               "algorithms": [{"id": f"S{st}·{v}", "label": f"Stage {st} · {LABELS[v]}"}
                              for st in self.stages for v in STAGE_VARIANTS[st]],
               "results": [], "max_scale": {}, "winners": [], "bounds": [], "notes": self.notes,
               "progress": min(1.0, (time.perf_counter() - self.t0) / self.max_s),
               "created": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        by = {}
        for r in self.rows:
            k = (r["stage"], r["scale"], r["algorithm"])
            cur = by.get(k)
            if cur is None or (r["feasible"], -(r["length_used_mm"] or 1e9)) > (cur["feasible"], -(cur["length_used_mm"] or 1e9)):
                by[k] = r
        for (st, s, v), r in sorted(by.items()):
            out["results"].append({"scale": s, "algorithm": f"S{st}·{v}", "stage": st,
                                   "length_used_mm": r["length_used_mm"] if r["feasible"] else None,
                                   "feasible": r["feasible"], "layout_id": None, "com_error_mm": r["com_error_mm"],
                                   "lambda_max_kgm2": r["lambda_max_kgm2"], "seed": r["seed"],
                                   "runs": sum(1 for x in self.rows if (x["stage"], x["scale"], x["algorithm"]) == (st, s, v))})
        for st in self.stages:
            for v in STAGE_VARIANTS[st]:
                ok = [s for (a, s, b), r in by.items() if a == st and b == v and r["feasible"]]
                out["max_scale"][f"S{st}·{v}"] = max(ok) if ok else None
            for s in sorted({s for (a, s, _), _ in by.items() if a == st}):
                cands = [(r["length_used_mm"], v) for (a, ss, v), r in by.items() if a == st and ss == s and r["feasible"]]
                if cands:
                    L, v = min(cands)
                    out["winners"].append({"scale": s, "stage": st, "algorithm": f"S{st}·{v}", "layout_id": None,
                                           "length_used_mm": L})
            for b in bounds_for(self.records, st):
                out["bounds"].append({**b, "id": f"S{st}·{b['id']}", "label": f"Stage {st}: {b['label']}"})
        tmp = self.out_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(out, indent=1, default=float), encoding="utf-8")
        tmp.replace(self.out_path)

    # ------------------------------------------------------------------------------------------ running
    def _batch(self, pool, jobs) -> list[dict]:
        futs = [pool.submit(_job, *j, self.preset) for j in jobs]
        out = []
        for f in as_completed(futs):
            try:
                r = f.result()
            except Exception as exc:  # noqa: BLE001 - recorded, never hidden
                self.notes.append(f"run failed: {exc!r}")
                continue
            out.append(r)
            self.rows.append(r)
            k = (r["stage"], r["scale"], r["algorithm"])
            self.combo_time[k] = self.combo_time.get(k, 0.0) + r["seconds"]
            if r["feasible"]:
                old = self.best.get(k)
                if old is None or r["length_used_mm"] < old[0] - 0.1 or \
                        (abs(r["length_used_mm"] - old[0]) <= 0.1 and r["g"] < old[1] * (1 - 1e-3)):
                    self.last_improve = time.perf_counter()
                if old is None or r["length_used_mm"] < old[0]:
                    self.best[k] = (r["length_used_mm"], r["g"])
            self.save()
        return out

    def _any_feasible(self, results) -> bool:
        return any(r["feasible"] for r in results)

    def _time_up(self) -> bool:
        if time.perf_counter() - self.t0 >= self.max_s:
            self.stop_reason = "time_limit"
            return True
        return False

    def _scan(self, pool, stage: int) -> list[float]:
        vs = STAGE_VARIANTS[stage]
        run = lambda s: self._batch(pool, [(stage, s, v, 1000 + k, self.budget0) for v in vs for k in range(self.seeds)])  # noqa: E731
        sizes = []
        s = 1.0
        res = run(s)
        sizes.append(s)
        if self._any_feasible(res):
            lo, hi = s, None
            while not self._time_up() and s < 2.0:
                s = round(s + self.step, 6)
                res = run(s)
                sizes.append(s)
                if self._any_feasible(res):
                    lo = s
                else:
                    hi = s
                    break
        else:
            self.notes.append(f"Stage {stage}: no valid layout at s = 1.00 — scanned downwards (smaller parts)")
            hi, lo = s, None
            while not self._time_up() and s > 0.5:
                s = round(s - self.step, 6)
                res = run(s)
                sizes.append(s)
                if self._any_feasible(res):
                    lo = s
                    break
                hi = s
        if lo is None or hi is None:
            return sizes
        while not self._time_up() and (hi - lo) / lo > self.tol:          # bisection to 0.5 %
            mid = round(0.5 * (lo + hi), 6)
            res = run(mid)
            sizes.append(mid)
            if self._any_feasible(res):
                lo = mid
            else:
                hi = mid
        return sizes

    def run(self) -> dict:
        snap = self.out_path.with_name(self.out_path.stem + "_records.pkl")
        snap.write_bytes(pickle.dumps(self.records, protocol=pickle.HIGHEST_PROTOCOL))
        sizes = {}
        self.save()
        with ProcessPoolExecutor(max_workers=self.workers, mp_context=mp.get_context("spawn"), initializer=_init,
                                 initargs=(str(snap),)) as pool:
            for st in self.stages:
                if self._time_up():
                    break
                sizes[st] = sorted(set(self._scan(pool, st)))
            self.phase = "refine"
            live = {(st, s, v) for st in sizes for s in sizes[st] for v in STAGE_VARIANTS[st]}
            rnd, seed_next = 1, 1000 + self.seeds
            while live and not self._time_up():
                budget = self.budget0 * (2 ** rnd)
                self._batch(pool, [(st, s, v, seed_next, budget) for st, s, v in sorted(live)])
                seed_next += 1
                rnd = min(rnd + 1, 6)
                if self._proven_optimal(sizes):
                    self.stop_reason = "proven_optimal"
                    break
                if all(t >= self.min_combo_s for t in (self.combo_time.get(k, 0.0) for k in live)) and \
                        time.perf_counter() - self.last_improve >= self.conv_s:
                    self.stop_reason = "converged"
                    break
                live = self._halve(live)
        self.phase = "done"
        self.save("DONE")
        return json.loads(self.out_path.read_text(encoding="utf-8"))

    def _halve(self, live):
        """Successive halving: per size keep the better half of the algorithms (by best length; infeasible last)."""
        keep = set()
        for st, s in {(a, b) for a, b, _ in live}:
            algs = sorted([v for a, b, v in live if (a, b) == (st, s)],
                          key=lambda v: self.best.get((st, s, v), (1e9, 1e9)))
            n = max(1, (len(algs) + 1) // 2)
            keep |= {(st, s, v) for v in algs[:n]}
        return keep

    def _proven_optimal(self, sizes) -> bool:
        """Every size's best length within 0.1 mm of the rigorous volume bound (practically never true)."""
        for st, ss in sizes.items():
            vb = bounds_for(self.records, st)[0]["coeff_mm"]
            for s in ss:
                Ls = [b[0] for (a, sc, _), b in self.best.items() if a == st and sc == s]
                if not Ls or min(Ls) > vb * s ** 3 + 0.1:
                    return False
        return bool(sizes)


def size_study_main(records_path: str, out_path: str, opts: dict) -> None:
    """Entry point of the background process (holds a keep-awake request on Windows while it runs)."""
    try:
        import ctypes
        ES_CONTINUOUS, ES_SYSTEM_REQUIRED = 0x80000000, 0x00000001
        ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)
    except Exception:  # noqa: BLE001 - not on Windows
        pass
    records = pickle.loads(Path(records_path).read_bytes())
    SizeStudy(records, Path(out_path), **opts).run()
