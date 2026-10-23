"""Manufacturable Design run (Addendum 1.5): algorithm choice → Stage 2 layout with bracket reach → mount synthesis →
full validation (parts and brackets) → cost and hardware list → exports.

Label everywhere: "manufacturing concept — assumed cost model, not a quote; brackets not stress-analysed".
"""
from __future__ import annotations

import csv
import io
import json
import pickle
import time
from pathlib import Path

import numpy as np

from ..collision.geom import part_geom_from_record
from ..collision.validate import Validator
from ..constraints.stage2_model import Stage2Model
from ..core.formfactor import COM_BOX
from ..geometry.stl_io import write_binary_stl
from ..objectives.metrics import part_phys
from ..optimise.brkga import (Evaluator, IslandState, LahcState, best_candidates, run_island, run_lahc, seed_keys,
                              sort_key)
from ..optimise.scalarize import Normaliser, alpha_from, slider_weights
from . import brackets as br
from .rules import MFG_REACH

LABEL = "manufacturing concept — assumed cost model, not a quote; brackets not stress-analysed"
AM_RULES = {"min_wall_mm": 1.0, "max_overhang_deg": 45.0, "min_hole_mm": 2.0}


def _seeds(model, records, ids):
    n = len(ids)
    out = []
    for order in (np.argsort([-records[i].obb_extents_mm.min() for i in ids]),
                  np.argsort([-(records[i].volume_mm3 or 0) for i in ids])):
        r = model.best_fit_all_orientations(list(order))
        hint = getattr(r, "keys_hint", None)
        allowed = [model.allowed[i] for i in ids]
        o_of = {p: o for p, o, _ in r.poses}
        s = seed_keys(list(order), [o_of.get(i) if o_of.get(i) in allowed[j] else allowed[j][0]
                                    for j, i in enumerate(ids)], allowed)
        if hint is not None:
            s[n:2 * n] = hint[0]
            s = np.concatenate([s[:2 * n], hint[1]])
        out.append(np.concatenate([s, np.full(max(0, model.dim - len(s)), 0.5)])[:model.dim])
    return out


def search(records, mode, sliders, budget_s, seed):
    model = Stage2Model(records, mode, mfg=True)
    ids = list(records)
    ev = Evaluator(model, ids, {i: part_phys(records[i]) for i in ids}, {i: records[i].orient_bounds for i in ids},
                   float(model.inner[0][2]), com_box=COM_BOX.copy())
    w = slider_weights(sliders, 2, "manufacturable")
    alpha = alpha_from(sliders)
    rng = np.random.default_rng(seed)
    seeds = _seeds(model, records, ids)
    st = IslandState(pop=np.vstack([np.array(seeds), rng.random((60 - len(seeds), model.dim))]), rng=rng)
    norm = Normaliser()
    run_island(st, ev, norm, w, alpha, time_budget_s=budget_s * 0.2, ls_elites=3, ls_moves=8)
    feas = [c.raw for c in st.cands if c.cv == 0] or [c.raw for c in st.cands]
    norm.update_from([r for r in feas if "D" in r])
    run_island(st, ev, norm, w, alpha, time_budget_s=budget_s * 0.45, ls_elites=3, ls_moves=8)
    b = best_candidates(st, 1)[0]
    lst = LahcState(current=b, best=b)
    run_lahc(lst, ev, norm, w, alpha, rng, time_budget_s=budget_s * 0.35)
    best = min([lst.best, b], key=sort_key)
    return model, best, w, st.evaluations + lst.evaluations


C_BRACKET = 1.2          # mm: brackets keep the part-to-frame clearance (U4) from every part they do not hold
AM_MARGINS = (0.4, 1.2)  # mm added to C_BRACKET in the AM construction (meshing error), tried in turn


def synthesize(model, records, best, geoms=None) -> list:
    """Brackets for every mounted part (from the mount chosen during the search). Metal-AM brackets are built clear
    of the other parts' certified boxes and then checked exactly; a bracket that still fails is rebuilt with a larger
    margin, and as a last resort replaced by a machined block (labelled; the final check reports it)."""
    out = []
    poses = {pid: (o, t) for pid, o, t in best.poses}
    pad_o = (best.meta or {}).get("pad_orients", {})
    for pid, info in (best.meta or {}).get("mounts", {}).items():
        if not info.get("ok") or "process" not in info:
            continue
        bid = f"b{len(out) + 1:02d}"
        if info["process"] == "metal_am":
            o = pad_o.get(pid, poses[pid][0])
            obstacles = [br.world_boxes(records[q], oq, tq) for q, (oq, tq) in poses.items() if q != pid]
            obstacles = np.vstack(obstacles) if obstacles else None
            b, why = None, "AM construction empty"
            for margin in AM_MARGINS:
                b = br.am_bracket(bid, pid, records[pid], o, poses[pid][1], info, obstacles=obstacles,
                                  clearance=C_BRACKET + margin)
                if b is None:
                    break
                if geoms is None or br.clearance_ok(b, pid, geoms, best.poses, C_BRACKET)[0]:
                    break
                b, why = None, "AM bracket could not keep 1.2 mm from its neighbours"
            if b is None:                      # fall back to a machined block (labelled)
                alt = dict(info, process="machined", mount_type=f"machined block ({why})")
                b = br.simple_bracket(bid, pid, alt)
        else:
            b = br.simple_bracket(bid, pid, info)
        out.append(b)
    meta = best.meta or {}
    if meta.get("stack_block") is not None and model.pcb:
        # one spacer set between consecutive boards (bottom to top)
        boards = sorted(model.pcb, key=lambda p: poses[p][1][2] + records[p].orient_bounds[poses[p][0]][2])
        for k in range(len(boards) - 1):
            lo_b, up_b = boards[k], boards[k + 1]
            top = poses[lo_b][1][2] + records[lo_b].orient_bounds[poses[lo_b][0]][5]
            bottom = poses[up_b][1][2] + records[up_b].orient_bounds[poses[up_b][0]][2]
            out.append(br.spacer_set(f"s{k + 1:02d}", lo_b, meta["stack_block"], top, bottom, upper=up_b,
                                     rod_xy=meta.get("rod_xy")))
    out += br.standoff_items("so", meta.get("standoffs", []))
    return out


def am_rule_rows(brackets) -> list[dict]:
    rows = []
    for b in brackets:
        if b.process != "metal_am" or not b.am:
            continue
        a = b.am
        rows += [
            {"item_id": b.id, "rule": "wall thickness ≥ 1.0 mm (by construction)", "value": a["wall_mm"],
             "limit": AM_RULES["min_wall_mm"], "pass": a["wall_mm"] >= AM_RULES["min_wall_mm"]},
            {"item_id": b.id, "rule": f"overhang > 45° area share, build axis {a['build_axis']} (supports planned)",
             "value": round(a["overhang_fraction"], 3), "limit": "supports if > 0", "pass": True},
            {"item_id": b.id, "rule": "fastener holes ≥ 2 mm (M3 clearance 3.4 mm; not modelled in the concept mesh)",
             "value": 3.4, "limit": AM_RULES["min_hole_mm"], "pass": True},
            {"item_id": b.id, "rule": "fits the build volume 250 × 250 × 325 mm (ASSUMED machine)",
             "value": " × ".join(f"{x:.0f}" for x in a["bbox_mm"]), "limit": "250 × 250 × 325",
             "pass": all(x <= y for x, y in zip(sorted(a["bbox_mm"]), sorted(br.BUILD_VOLUME)))},
        ]
    return rows


def run_mfg(records: dict, mode: str, sliders: dict, out_dir: Path, budget_s: float = 90.0, seed: int = 20261024) -> dict:
    from ..optimise.selector import part_stats, select_algorithm
    t0 = time.perf_counter()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    # the tab chooses its own algorithm: the selector's Stage 2 rule for the manufacturable weights (mount synthesis
    # needs the box decoder's frame, rail and keep-out model, so a height-map choice is not available here)
    choice = select_algorithm(2, sliders, part_stats(list(records.values())), "manufacturable")
    model, best, weights, evals = search(records, mode, sliders, budget_s, seed)
    geoms = {pid: part_geom_from_record(r) for pid, r in records.items()}
    brackets = synthesize(model, records, best, geoms)
    meta = best.meta or {}
    feasible_layout = best.cv <= 0 and not best.unplaced
    rep = Validator(geoms).validate(best.poses, model.spec(meta, relaxed=meta.get("overflow_mm", 0) > 0),
                                    want_planes=False)
    bracket_checks = []
    for b in brackets:
        if b.process == "standoff":
            continue                       # standoffs are already part of the validated Stage 2 rules
        ok, d = br.clearance_ok(b, b.host_set(), geoms, best.poses, C_BRACKET)
        bracket_checks.append({"item_id": b.id, "ok": ok, "min_clearance_mm": None if d == np.inf else d})
    pair_conflicts = br.bracket_conflicts(brackets, C_BRACKET)
    all_ok = rep.valid and all(c["ok"] for c in bracket_checks) and not pair_conflicts
    exports = []
    rows = []
    for b in brackets:
        name = f"bracket_AM_{b.for_part}.stl" if b.process == "metal_am" else f"{b.process}_{b.id}_{b.for_part}.stl"
        v = np.vstack([m[0] for m in b.meshes])
        offs = np.cumsum([0] + [len(m[0]) for m in b.meshes[:-1]])
        f = np.vstack([m[1] + o for m, o in zip(b.meshes, offs)])
        write_binary_stl(out_dir / name, v, f, header=f"t2s {b.process} {b.id}")
        exports.append({"kind": "stl", "url": name, "label": f"{b.label or b.mount_type} — {name}",
                        "metal_am": b.process == "metal_am"})
        rows.append([b.id, b.for_part, records[b.for_part].name, b.mount_type, b.process, b.material,
                     f"{b.mass_kg:.5f}", f"{b.cost_rel:.2f}", b.fasteners])
    buf = io.StringIO()
    wr = csv.writer(buf)
    wr.writerow([f"# {LABEL}"])
    wr.writerow(["item", "part_id", "part", "mount type", "process", "material", "mass_kg", "relative_cost", "fasteners"])
    wr.writerows(rows)
    (out_dir / "hardware.csv").write_text(buf.getvalue(), encoding="utf-8")
    exports.insert(0, {"kind": "csv", "url": "hardware.csv", "label": "hardware list (CSV)"})
    total = float(sum(b.cost_rel for b in brackets))
    result = {
        "status": "DONE", "label": LABEL, "mode": mode, "seconds": time.perf_counter() - t0, "evaluations": evals,
        "weights": weights, "bracket_reach_mm": MFG_REACH,
        "algorithm": {"id": choice.id, "label": choice.label, "reason": choice.reasons[0] if choice.reasons else ""},
        "feasible": bool(feasible_layout and all_ok),
        "verdict": None if feasible_layout else "NO FEASIBLE LAYOUT FOUND (not proven infeasible)",
        "violations": ([f"exceeds the usable length by {meta['overflow_mm']:.1f} mm"] if meta.get("overflow_mm", 0) > 0 else [])
        + [f"{records[p].name}: {meta['mounts'][p]['how']}" for p in meta.get("unmounted", [])]
        + [f"{records[p].name}: could not be placed" for p in best.unplaced]
        + [f"bracket {c['item_id']} is closer than 1.2 mm to another part"
           + ("" if c["min_clearance_mm"] is None or c["min_clearance_mm"] < 0 else f" ({c['min_clearance_mm']:.2f} mm)")
           for c in bracket_checks if not c["ok"]]
        + [f"brackets {a} and {b} are closer than 1.2 mm" + ("" if d < 0 else f" ({d:.2f} mm)")
           for a, b, d in pair_conflicts],
        "validation": {"parts_valid": rep.valid, "pairs": len(rep.pairs), "statics": len(rep.statics),
                       "violations": rep.violations[:10], "brackets": bracket_checks,
                       "bracket_pairs_checked": len(brackets) * (len(brackets) - 1) // 2,
                       "bracket_conflicts": [{"a": a, "b": b, "distance_mm": d} for a, b, d in pair_conflicts],
                       "relaxed_rules": meta.get("overflow_mm", 0) > 0},
        "items": [{"id": b.id, "for_part": b.for_part, "part_name": records[b.for_part].name, "mount_type": b.mount_type,
                   "process": b.process, "material": b.material, "mass_kg": b.mass_kg, "cost_rel": b.cost_rel,
                   "fasteners": b.fasteners, "label": b.label} for b in brackets],
        "am_rules": am_rule_rows(brackets), "total_cost_rel": total, "exports": exports,
        "hardware_mass_kg": float(sum(b.mass_kg for b in brackets)),
    }
    with open(out_dir / "layout.pkl", "wb") as fh:
        pickle.dump({"poses": best.poses, "meta": meta, "raw": best.raw, "cv": best.cv, "keys": best.keys,
                     "brackets": brackets, "validation": rep.valid, "min_clearance_mm": rep.min_clearance_mm,
                     "levels": rep.levels, "pairs": len(rep.pairs), "statics": len(rep.statics)}, fh)
    (out_dir / "mfg.json").write_text(json.dumps(result, indent=1, default=float), encoding="utf-8")
    return result


def mfg_job(records_path: str, mode: str, sliders: dict, out_dir: str, budget_s: float) -> str:
    records = pickle.loads(Path(records_path).read_bytes())
    run_mfg(records, mode, sliders, Path(out_dir), budget_s)
    return out_dir
