"""Bracket design job: give every metal-AM and cradle bracket of a V2 Stage 2 layout a real solid inside its reserved
box, checked with CalculiX and NGSolve (gd.evaluate). Metal-AM brackets use the contest winner (the volume-fraction
ladder, lightest passing design first); cradles use the rule-based conformal shape (a machined cradle follows the
part). A bracket with no passing design keeps its best attempt, labelled with the failed criterion; if no solid can be
built at all, the machined-block reference is used and labelled as a fallback.
"""
from __future__ import annotations

import importlib
import json
import pickle
import time
from pathlib import Path

import numpy as np

from .contest import ENTRANTS, REFERENCES, VOL_LADDER
from .domain import domain_from_bracket


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
                   budget_s: float = 300.0, threads: int = 2, log=print) -> tuple[dict, tuple | None]:
    from ..mfg.rules import FASTENER_MASS_KG, MATERIAL, bracket_cost
    from .evaluate import evaluate
    am = b["kind"] == "metal_am"
    gkey = key if am else "baseline"
    fn, name = _gen(gkey)
    h = design_h(b["reserve"], int(b["axis"])) if h is None else h
    dom = domain_from_bracket(b, rec, orient, t, h=h, part_mass_kg=part_mass_kg)
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
        ev = evaluate(dom, g, threads=threads)
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
        ev = evaluate(dom, fn(dom), threads=threads)
        best, best_mesh = ev.summary(), ev.mesh
        fallback = "no generated solid joined wall and part: machined block used"
        if best_mesh is None:
            return {"pid": b["pid"], "generator": name, "passed": False, "reason": ev.reason, "fallback": fallback}, None
    v, f = best_mesh
    proc = "metal_am" if am else "machined"
    m, com, inertia, vol = _props(v, f, MATERIAL[proc][1])
    nf = int(b.get("fasteners", 3))
    fpts = []
    for _ in range(nf):
        p = 0.5 * (np.asarray(b["reserve"][:3]) + np.asarray(b["reserve"][3:]))
        p[int(b["axis"])] = b["plane_mm"]
        fpts.append(p)
    from ..mfg.brackets import _combine, _fastener_items
    m2, c2, i2 = _combine([(m, com, inertia)] + _fastener_items(fpts))
    cost = bracket_cost(b["kind"], float(b["gap_mm"]), vol / 1e3, nf)
    label = (f"{'metal-AM bracket' if am else 'machined cradle'} designed by {name}"
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
         "voxel_mm": h, "sigma_peak_mpa": best.get("sigma_peak_mpa"), "axes": best.get("axes")}
    return d, (v, f)


def design_job(snapshot: str, out_dir: str, threads: int = 2) -> str:
    """Process-pool job. snapshot: pickle {layout_id, brackets, records, poses {pid: (orient, t)}, masses {pid: kg},
    results_path}. Writes progress.json, and per bracket <layout>-br<k>.bin (mesh) and .npy (vertices)."""
    snap = pickle.loads(Path(snapshot).read_bytes())
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    key = winner_key(snap.get("results_path"))
    lid = snap["layout_id"]
    todo = [(k, b) for k, b in enumerate(snap["brackets"]) if b["kind"] in ("metal_am", "cradle")]
    designs, t0 = {}, time.perf_counter()
    prog = out / "progress.json"

    def write(status, i):
        prog.write_text(json.dumps({"status": status, "progress": i / max(len(todo), 1), "layout_id": lid,
                                    "generator_key": key, "designs": designs, "seconds": time.perf_counter() - t0},
                                   default=float), encoding="utf-8")
    write("RUNNING", 0)
    for i, (k, b) in enumerate(todo):
        o, t = snap["poses"][b["pid"]]
        d, mesh = design_bracket(b, snap["records"][b["pid"]], o, t, snap["masses"].get(b["pid"]) or 0.2, key,
                                 threads=threads)
        if mesh is not None:
            (out / f"{lid}-br{k}.bin").write_bytes(_mesh_bin(*mesh))
            np.save(out / f"{lid}-br{k}.npy", np.asarray(mesh[0], float))
            d["vertices_file"] = f"{lid}-br{k}.npy"
            d["mesh_file"] = f"{lid}-br{k}.bin"
        designs[b["pid"]] = d
        write("RUNNING", i + 1)
    write("DONE", len(todo))
    return str(prog)
