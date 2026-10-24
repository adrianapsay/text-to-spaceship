"""Bracket design job: give every metal-AM, cradle and tube-clamp bracket of a V2 Stage 2 layout a real solid inside
its reserved box, checked with CalculiX and NGSolve (gd.evaluate) under a launch environment (gd.environment,
default GEVS with the qualification check). Metal-AM brackets use the contest winner (the volume-fraction ladder,
lightest passing design first) in the chosen AM material (gd.materials, default AlSi10Mg); cradles and clamps use
the rule-based conformal shape in 6061-T6 (a machined cradle follows the part; a clamp is a band around the tube on a
foot, until then shown as the catalogue envelope). One material table gives the FE check, the mass and the relative
cost. A bracket with no passing design keeps its best attempt, labelled with the failed criterion; if no solid can be
built at all, the machined-block reference is used and labelled as a fallback.
"""
from __future__ import annotations

import importlib
import json
import os
import pickle
import time
from pathlib import Path

import numpy as np

from .contest import ENTRANTS, REFERENCES, VOL_LADDER
from .domain import domain_from_bracket

DESIGNED_KINDS = ("metal_am", "cradle", "clamp")     # brackets whose solid the design job builds


def winner_key(results_path: Path | None) -> str:
    try:
        w = json.loads(Path(results_path).read_text(encoding="utf-8")).get("winner") if results_path else None
        if w and w.get("key") in ENTRANTS:
            return w["key"]
    except (OSError, json.JSONDecodeError):
        pass
    return "baseline"


def _gen(key):
    mod, fn, _ = ENTRANTS.get(key) or REFERENCES[key]
    m = importlib.import_module(mod)
    return getattr(m, fn), getattr(m, "NAME", key)


def _mesh_bin(v, f) -> bytes:
    v = np.asarray(v, "<f4")
    f = np.asarray(f, "<u4")
    return np.array([len(v), len(f)], "<u4").tobytes() + v.tobytes() + f.tobytes()


def _props(v, f, density):
    from ..massprops.core import integrate
    up = integrate(np.asarray(v, float), np.asarray(f, np.int64))
    m = density * up.volume_mm3 * 1e-9
    return float(m), np.asarray(up.com_mm, float), m * (np.asarray(up.j_mm5) / up.volume_mm3) * 1e-6, float(up.volume_mm3)


def solid_props(v, f, material: str | None = None):
    """(mass kg, COM mm, inertia kg·m² about the COM, volume mm³) of a designed solid in a gd.materials material —
    the density the FE check uses (before: 2670 kg/m³ for the mass, 2680 for the FE check)."""
    from .materials import density_kg_m3
    return _props(v, f, density_kg_m3(material))


MAX_VOXELS = 40000      # a larger reserved box is designed on coarser voxels (memory and time of the FE check)


def design_h(reserve, axis: int | None = None, h_min: float = 1.5, layers: int = 6) -> float:
    """Voxel size for a bracket's reserved box: the contest's 1.5 mm, coarser (in 0.25 mm steps) when the box would
    need more than MAX_VOXELS voxels — but fine enough for `layers` voxel layers between the wall and the far end of
    the box along the bracket axis (a 3 mm gap needs ~1 mm voxels to hold a bolted layer, a contact layer and
    material between them)."""
    ext = np.asarray(reserve[3:], float) - np.asarray(reserve[:3], float)
    h = float(np.ceil(max(h_min, float(np.prod(ext) / MAX_VOXELS) ** (1.0 / 3.0)) * 4.0) / 4.0)
    if axis is not None:
        h = min(h, max(0.5, float(np.floor(ext[axis] / layers * 4.0) / 4.0)))
    return h


def design_bracket(b: dict, rec, orient: int, t, part_mass_kg: float, key: str, h: float | None = None,
                   budget_s: float = 300.0, threads: int = 2, log=print, material: str | None = None,
                   environment: str | None = None) -> tuple[dict, tuple | None]:
    """Design one bracket. `material`: the AM material id for a metal-AM bracket (gd.materials; default AlSi10Mg);
    cradles and clamp bands are machined 6061-T6 whatever it says. `environment`: the launch preset
    (gd.environment; default GEVS)."""
    from ..mfg.rules import FASTENER_MASS_KG, bracket_cost
    from . import environment as envs
    from . import materials as mats
    from .evaluate import evaluate
    am = b["kind"] == "metal_am"
    mat_id = mats.for_kind(b["kind"], material)
    env = envs.get(environment)
    gkey = key if am else "baseline"
    fn, name = _gen(gkey)
    h = design_h(b["reserve"], int(b["axis"])) if h is None else h
    dom = domain_from_bracket(b, rec, orient, t, h=h, part_mass_kg=part_mass_kg, material=mat_id)
    ladder = VOL_LADDER if (am and gkey != "baseline") else (None,)
    best, best_mesh = None, None
    for vf in ladder:
        if vf is not None:
            dom.vol_frac = vf
        try:
            g = fn(dom, budget_s=budget_s, threads=threads)
        except Exception as exc:  # noqa: BLE001
            log(f"[design] {b['name']}: {name} failed: {exc!r}")
            break
        ev = evaluate(dom, g, threads=threads, env=env.id)
        row = ev.summary()
        row["vol_frac"] = vf
        log(f"[design] {b['name']} {name} vf={vf}: mass {row['mass_g']} g, MS {row['ms_yield']}, f1 {row['f1_hz']}")
        if ev.mesh is not None and (best is None or (row["passed"] and not best["passed"]) or
                                    (not best["passed"] and (row["ms_yield"] or -9) > (best["ms_yield"] or -9))):
            best, best_mesh = row, ev.mesh
        if row["passed"]:
            break
    fallback = None
    if best_mesh is None:                                   # no solid at all: the machined block (labelled)
        fn, _ = _gen("block")
        ev = evaluate(dom, fn(dom), threads=threads, env=env.id)
        best, best_mesh = ev.summary(), ev.mesh
        fallback = "no generated solid joined wall and part: machined block used"
        if best_mesh is None:
            return {"pid": b["pid"], "generator": name, "passed": False, "reason": ev.reason, "fallback": fallback,
                    "environment": env.id, "material": mat_id}, None
    v, f = best_mesh
    mat = mats.material(mat_id)
    m, com, inertia, vol = solid_props(v, f, mat_id)
    if dom.bolts is not None and len(dom.bolts):            # the fasteners at the bolt pattern (gd.bolts)
        fpts = [np.asarray(p, float) for p in dom.bolts]
    else:
        p = 0.5 * (np.asarray(b["reserve"][:3]) + np.asarray(b["reserve"][3:]))
        p[int(b["axis"])] = b["plane_mm"]
        fpts = [p] * int(b.get("fasteners", 3))
    nf = len(fpts)
    from ..mfg.brackets import _combine, _fastener_items
    m2, c2, i2 = _combine([(m, com, inertia)] + _fastener_items(fpts))
    cost = bracket_cost(b["kind"], float(b["gap_mm"]), vol / 1e3, nf) * float(mat["cost_factor"])
    what = {"metal_am": "metal-AM bracket", "cradle": "machined cradle",
            "clamp": "tube-clamp band (aluminium, follows the tube)"}.get(b["kind"], b["kind"])
    label = (f"{what} designed by {name}, {mat['id']}"
             + (f" (volume fraction {best['vol_frac']:.2f})" if best.get("vol_frac") else ""))
    d = {"pid": b["pid"], "generator": name, "mass_kg": m2, "com_mm": c2.tolist(), "inertia_kgm2": np.asarray(i2).tolist(),
         "solid_mass_kg": m, "volume_cm3": vol / 1e3, "cost_rel": float(cost), "label": label,
         "passed": bool(best.get("passed")), "reason": best.get("reason", ""), "sigma_mpa": best.get("sigma_mpa"),
         "ms_yield": best.get("ms_yield"), "ms_ult": best.get("ms_ult"), "f1_hz": best.get("f1_hz"),
         "agreement": best.get("agreement"), "fallback": fallback, "n_nodes": best.get("n_nodes"),
         "solvers": {k: {"solver": s["solver"], "seconds": s["seconds"], "f1_hz": s.get("f1_hz")}
                     for k, s in (best.get("solvers") or {}).items() if isinstance(s, dict) and "solver" in s},
         "modes": best.get("modes"),
         "overhang_fraction": best.get("overhang_fraction"), "fastener_mass_kg": nf * FASTENER_MASS_KG,
         "voxel_mm": h, "sigma_peak_mpa": best.get("sigma_peak_mpa"), "axes": best.get("axes"),
         # WS3: launch environment, material, every check's margin, the governing one, bolts, flags
         "environment": best.get("environment") or env.id, "environment_name": best.get("environment_name"),
         "material": mat_id, "material_name": mat["name"], "material_allowables": mats.ALLOWABLES,
         "margins": best.get("margins"), "factor_sources": best.get("factor_sources"),
         "checks": best.get("checks"), "bolt_checks": best.get("bolt_checks"),
         "governing": best.get("governing"), "ms_bolt": best.get("ms_bolt"), "flags": best.get("flags"),
         "bolts": [np.asarray(p, float).tolist() for p in fpts], "vol_frac": best.get("vol_frac")}
    return d, (v, f)


def _design_one(k: int, b: dict, rec, pose, mass: float, key: str, out_dir: str, lid: str, threads: int,
                material: str | None = None, environment: str | None = None) -> dict:
    """One bracket (its own process when the job runs brackets in parallel): design it and write its mesh files."""
    o, t = pose
    d, mesh = design_bracket(b, rec, o, t, mass, key, threads=threads, log=lambda m: None, material=material,
                             environment=environment)
    if mesh is not None:
        out = Path(out_dir)
        (out / f"{lid}-br{k}.bin").write_bytes(_mesh_bin(*mesh))
        np.save(out / f"{lid}-br{k}.npy", np.asarray(mesh[0], float))
        d["vertices_file"] = f"{lid}-br{k}.npy"
        d["mesh_file"] = f"{lid}-br{k}.bin"
    return d


def design_workers(n_todo: int, threads: int) -> int:
    """Brackets designed at the same time: independent, so several processes (each `threads` threads) — at most 4,
    and at most half the logical cores between them."""
    return max(1, min(4, n_todo, (os.cpu_count() or 4) // (2 * max(int(threads), 1))))


def eta_seconds(rows: list[dict], workers: int, now_s: float) -> float | None:
    """Time left (s) from the brackets designed so far: each one still running needs the mean design time less what
    it has had, each queued one the mean time, shared among the workers. None until one bracket is done."""
    done = [r["seconds"] for r in rows if r["status"] == "done" and r.get("seconds") is not None]
    if not done:
        return None
    mean = float(np.mean(done))
    running = [max(0.0, mean - (now_s - r["started_s"])) for r in rows if r["status"] == "running"]
    queued = sum(1 for r in rows if r["status"] == "queued")
    if not running and not queued:
        return 0.0
    return max(max(running, default=0.0), (sum(running) + mean * queued) / max(1, workers))


def design_job(snapshot: str, out_dir: str, threads: int = 2, workers: int | None = None) -> str:
    """Process-pool job. snapshot: pickle {layout_id, brackets, records, poses {pid: (orient, t)}, masses {pid: kg},
    results_path, optional environment (gd.environment id, default GEVS) and materials {pid: AM material id}}.
    Writes progress.json when it starts and after every bracket — with one row per bracket (queued /
    running / done, its time, mass and result) for the progress bars — and per bracket <layout>-br<k>.bin (mesh) and
    .npy (vertices). The brackets are designed `workers` at a time in separate processes (design_workers), in order
    (the pool takes them first in, first out: the first `workers` not yet done are the running ones); if a process
    dies (BrokenProcessPool), the brackets left are designed one by one in this process."""
    from ..core.fileio import atomic_write_text
    from . import environment as envs
    snap = pickle.loads(Path(snapshot).read_bytes())
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    key = winner_key(snap.get("results_path"))
    lid = snap["layout_id"]
    todo = [(k, b) for k, b in enumerate(snap["brackets"]) if b["kind"] in DESIGNED_KINDS]
    designs, t0 = {}, time.perf_counter()
    prog = out / "progress.json"
    n = design_workers(len(todo), threads) if workers is None else max(1, int(workers))
    rows = [{"k": k, "pid": b["pid"], "kind": b["kind"], "status": "queued"} for k, b in todo]
    by_k = {r["k"]: r for r in rows}

    def start_next(slots: int) -> None:
        """Mark the next queued brackets as running, up to `slots` at a time."""
        now = time.perf_counter() - t0
        for r in rows:
            if sum(1 for x in rows if x["status"] == "running") >= slots:
                return
            if r["status"] == "queued":
                r.update(status="running", started_s=now)

    def finish(k: int, d: dict) -> None:
        r = by_k[k]
        now = time.perf_counter() - t0
        r.update(status="done", seconds=now - r.get("started_s", now), passed=bool(d.get("passed")),
                 mass_g=(1000.0 * d["mass_kg"]) if d.get("mass_kg") is not None else None,
                 solid=d.get("mass_kg") is not None, reason=str(d.get("reason") or "")[:160])

    def write(status, slots):
        now = time.perf_counter() - t0
        atomic_write_text(prog, json.dumps({
            "status": status, "progress": len(designs) / max(len(todo), 1), "layout_id": lid, "generator_key": key,
            "environment": envs.get(snap.get("environment")).id,
            "designs": designs, "seconds": now, "workers": slots, "n_total": len(todo), "n_done": len(designs),
            "brackets": rows, "eta_s": eta_seconds(rows, slots, now) if status != "DONE" else 0.0}, default=float))

    def args(k, b):
        return (k, b, snap["records"][b["pid"]], snap["poses"][b["pid"]], snap["masses"].get(b["pid"]) or 0.2, key,
                str(out), lid, threads, (snap.get("materials") or {}).get(b["pid"]), snap.get("environment"))
    left = list(todo)
    if n > 1 and len(todo) > 1:
        from concurrent.futures import ProcessPoolExecutor, as_completed
        from concurrent.futures.process import BrokenProcessPool
        start_next(n)
        write("RUNNING", n)
        try:
            with ProcessPoolExecutor(max_workers=n) as ex:
                futs = {ex.submit(_design_one, *args(k, b)): (k, b) for k, b in todo}
                for f in as_completed(futs):
                    k, b = futs[f]
                    try:
                        designs[b["pid"]] = f.result()
                    except BrokenProcessPool:
                        raise
                    except Exception as exc:  # noqa: BLE001 - one bracket's failure is that bracket's result
                        designs[b["pid"]] = {"pid": b["pid"], "generator": key, "passed": False,
                                             "reason": f"design failed: {exc!r}"[:300]}
                    finish(k, designs[b["pid"]])
                    left.remove((k, b))
                    start_next(n)
                    write("RUNNING", n)
        except BrokenProcessPool:
            for r in rows:                              # the brackets left: one by one below
                if r["status"] == "running":
                    r["status"] = "queued"
    for k, b in left:
        start_next(1)
        write("RUNNING", 1)
        designs[b["pid"]] = _design_one(*args(k, b))
        finish(k, designs[b["pid"]])
    write("DONE", n)
    return str(prog)
