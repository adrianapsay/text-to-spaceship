"""Detail-level ladder (Addendum 4): find, by measurement, the cheapest shape representation of a part that still
gives the best result, separately for every search algorithm.

For one part, levels are tried from simplest to most detailed. At each level the whole part set is packed with
each applicable algorithm while only that part uses the level (all other parts keep their defaults), with the same
seeds and a fixed number of evaluations, so differences come from the level and not from luck. The best layout of
each run is checked by the validator on the true meshes. Validation always uses the full mesh; the ladder only
changes what the search sees.

Measured per level: proxy volume and overhead, build time, median query time, and per algorithm the used length,
COM error, scalarised score, time to the first valid layout and the false-reject rate (how often the level blocks
a pose that the true geometry allows).
Stopping: two successive level changes each within 0.5 mm, 0.5 % of score and 1 point of false-reject rate, i.e.
three levels in a row agree (converged); or the next level would make one generation slower than the 2 s
interactive budget (time_budget); or the time budget runs out; or levels are exhausted. False-reject rates are
measured around one fixed reference layout, so they depend on the representation only.
Chosen level: the cheapest level within those tolerances of the most detailed level tested.
Not implemented in this build: F2 support polytopes (26/64/128 directions) and F5 decimated meshes.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from ..collision.geom import part_geom_from_record, to_world
from ..collision.validate import StageSpec, Validator, plane_certificate
from ..decoders.box_decoder import PLACEMENT_GAP_STAGE1, BoxDecoder, ProxyPart
from ..decoders.heightmap import HeightmapDecoder
from ..geometry.proxies import COVER_DELTA, certify_boxes, compound_boxes, planar_cut_cover
from ..objectives.metrics import ENCLOSURE_HI, ENCLOSURE_LO, part_phys
from ..optimise.brkga import Evaluator, IslandState, best_candidates, run_island, seed_keys
from ..optimise.scalarize import Normaliser, alpha_from, slider_weights

TOL_L_MM = 0.5
TOL_G_REL = 0.005
TOL_FR = 0.01
GEN_BUDGET_S = 2.0          # one generation must stay below this for interactive use (rule b)
ALG_BOX, ALG_HM = "hybrid_box", "hybrid_heightmap"

LEVELS = [
    ("F0", "F0", "bounding box", {}),
    ("F1-2", "F1", "compound boxes, k = 2", {"k": 2}),
    ("F1-4", "F1", "compound boxes, k = 4", {"k": 4}),
    ("F1-6", "F1", "compound boxes, k = 6", {"k": 6}),
    ("F2", "F2", "convex hull", {}),
    ("F3-4", "F3", "convex cover, ≤ 4 pieces", {"pieces": 4}),
    ("F3-8", "F3", "convex cover, ≤ 8 pieces", {"pieces": 8}),
    ("F3-16", "F3", "convex cover, ≤ 16 pieces", {"pieces": 16}),
    ("F4-2", "F4", "voxel columns of the full mesh, 2 mm", {"h": 2.0}),
    ("F4-1", "F4", "voxel columns of the full mesh, 1 mm", {"h": 1.0}),
]
# which algorithm can use which level family
APPLICABLE = {ALG_BOX: {"F0", "F1", "F3"}, ALG_HM: {"F0", "F1", "F2", "F3", "F4"}}
DEFAULT_LEVEL = {ALG_BOX: "F1-6", ALG_HM: "F4-2"}


def _box_mesh(boxes: np.ndarray):
    vs, fs = [], []
    tri = np.array([[0, 2, 1], [0, 3, 2], [4, 5, 6], [4, 6, 7], [0, 1, 5], [0, 5, 4],
                    [1, 2, 6], [1, 6, 5], [2, 3, 7], [2, 7, 6], [3, 0, 4], [3, 4, 7]])
    for k, b in enumerate(boxes):
        x0, y0, z0, x1, y1, z1 = b
        vs.append([[x0, y0, z0], [x1, y0, z0], [x1, y1, z0], [x0, y1, z0], [x0, y0, z1], [x1, y0, z1], [x1, y1, z1],
                   [x0, y1, z1]])
        fs.append(tri + 8 * k)
    return np.array(vs, float).reshape(-1, 3), np.vstack(fs)


def _pieces_mesh(pieces):
    from scipy.spatial import ConvexHull
    vs, fs, off = [], [], 0
    for p in pieces:
        h = ConvexHull(p)
        vs.append(p)
        fs.append(h.simplices + off)
        off += len(p)
    return np.vstack(vs), np.vstack(fs)


@dataclass
class Representation:
    level: str
    family: str
    label: str
    params: dict
    boxes: np.ndarray | None          # for the box decoder (certified containment)
    mesh: tuple | None                # (v, f) for the height-map decoder (contains the part)
    pieces: list | None               # convex sets for the false-reject proxy test
    h: float
    proxy_volume: float
    build_s: float
    note: str = ""


def build_representation(rec, level: str) -> Representation | None:
    name, fam, label, params = next(x for x in LEVELS if x[0] == level)
    t0 = time.perf_counter()
    v, f = rec.v, rec.f
    vol = rec.volume_mm3 or 0.0
    if fam == "F0":
        b = np.concatenate([v.min(0) - 1e-6, v.max(0) + 1e-6])[None]
        rep = Representation(name, fam, label, params, b, _box_mesh(b), [_box_mesh(b)[0]], 2.0,
                             float(np.prod(b[0, 3:] - b[0, :3])), 0.0)
    elif fam == "F1":
        b, method = compound_boxes(v, f, params["k"])
        ok, why = certify_boxes(v, f, b)
        if not ok:
            return None
        rep = Representation(name, fam, label, params, b, _box_mesh(b), [_box_mesh(b[i:i + 1])[0] for i in range(len(b))],
                             2.0, float(np.prod(b[:, 3:] - b[:, :3], axis=1).sum()), 0.0, method)
    elif fam == "F2":
        if rec.hull is None:
            return None
        hp = v[rec.hull.vertex_ids]
        b = np.concatenate([hp.min(0), hp.max(0)])[None]
        rep = Representation(name, fam, label, params, b, (v, rec.hull.simplices), [hp], 2.0,
                             float(rec.hull_volume_mm3 or 0.0), 0.0)
    elif fam == "F3":
        if not vol:
            return None
        axis_hint = None
        if (rec.topology.genus_total or 0) > 0 and rec.j_unit_mm5 is not None:
            wv, vecs = np.linalg.eigh(rec.j_unit_mm5)
            axis_hint = vecs[:, 2] if abs(wv[1] - wv[0]) < abs(wv[2] - wv[1]) else vecs[:, 0]
        cover = planar_cut_cover(v, f, vol, axis_hint=axis_hint, max_pieces=params["pieces"], target_overhead=1e-9)
        if not cover.certified or not cover.pieces:
            return None
        pts = [p.vertices for p in cover.pieces]
        b = np.array([np.concatenate([p.min(0) - COVER_DELTA, p.max(0) + COVER_DELTA]) for p in pts])
        rep = Representation(name, fam, label, {**params, "pieces_built": len(pts)}, b, _pieces_mesh(pts), pts, 2.0,
                             float(cover.total_hull_volume), 0.0)
    else:   # F4: full mesh on an h grid
        rep = Representation(name, fam, label, params, None, (v, f), None, params["h"], float(vol), 0.0)
    rep.build_s = time.perf_counter() - t0
    return rep


# ----------------------------------------------------------------------------------------------- measurement
def _median_query_us(rep: Representation, rec, other, n: int = 2000, seed: int = 0) -> float | None:
    """Median time of the query the consuming decoder makes at this level."""
    rng = np.random.default_rng(seed)
    times = []
    if rep.family in ("F0", "F1") and rep.boxes is not None:
        ob = other.boxes
        for _ in range(n):
            t = rng.uniform(-20, 20, 3)
            t0 = time.perf_counter()
            bx = rep.boxes + np.concatenate([t, t])
            np.any(np.all((bx[:, None, :3] < ob[None, :, 3:]) & (bx[:, None, 3:] > ob[None, :, :3]), axis=2))
            times.append(time.perf_counter() - t0)
    elif rep.family in ("F2", "F3"):
        oh = other.v[other.hull.vertex_ids]
        for _ in range(max(200, n // 10)):
            t = rng.uniform(-60, 60, 3)
            t0 = time.perf_counter()
            for p in rep.pieces:
                plane_certificate(p + t, oh)
            times.append(time.perf_counter() - t0)
    else:                               # F4: one column drop (max-plus over the footprint) on an empty skyline
        from ..decoders.heightmap import _best_position
        o = rec.allowed_orients[0]
        dec = HeightmapDecoder({"p": (rep.mesh[0], rep.mesh[1], [o])}, ENCLOSURE_LO, ENCLOSURE_HI, h=rep.h)
        fp = dec.fp[("p", o)]
        for _ in range(max(50, n // 40)):
            t0 = time.perf_counter()
            _best_position(dec.H0, fp.bot, fp.top, fp.w, fp.d, dec.nx, dec.ny, dec.hi[2], 0.0, dec.h, dec.lo[2])
            times.append(time.perf_counter() - t0)
    return float(np.median(times) * 1e6)


def _false_reject_rate(rep: Representation, pid: str, records: dict, poses, spec: StageSpec, validator: Validator,
                       samples: int = 200, seed: int = 1) -> float | None:
    """P(level blocks the pose | true geometry allows it), over random near-contact poses of the part."""
    rng = np.random.default_rng(seed)
    rec = records[pid]
    others = [(q, o, t) for q, o, t in poses if q != pid]
    oth_pieces = []
    for q, o, t in others:
        r = records[q]
        ps = [p.vertices for p in r.cover.pieces] if r.cover.certified and r.cover.pieces else [r.v[r.hull.vertex_ids]]
        oth_pieces.append([to_world(p, o, t) for p in ps])
    oth_box = [np.concatenate([np.vstack(ps).min(0), np.vstack(ps).max(0)]) for ps in oth_pieces]
    if rep.family == "F4":
        return None                     # column proxy: blocking also depends on the other parts' columns
    req = spec.c_pp + 2 * COVER_DELTA
    free = blocked = tries = 0
    while free < samples and tries < samples * 40:
        tries += 1
        o = int(rng.choice(rec.allowed_orients))
        hull = to_world(rec.v[rec.hull.vertex_ids], o, np.zeros(3))
        lo = spec.lo - hull.min(0)
        hi = spec.hi - hull.max(0)
        if np.any(hi < lo):
            continue
        t = np.round(rng.uniform(lo, hi) * 1000) / 1000
        ab = np.concatenate([hull.min(0) + t, hull.max(0) + t])
        near = [k for k, b in enumerate(oth_box) if np.max(np.maximum(b[:3] - ab[3:], ab[:3] - b[3:])) < 5.0]
        if not near:
            continue
        sub = [(pid, o, t)] + [others[k] for k in near]
        rep_exact = validator.validate(sub, StageSpec(spec.stage, spec.lo, spec.hi, spec.c_pp, spec.c_static),
                                       want_planes=False, stop_on_failure=True)
        if not rep_exact.valid:
            continue
        free += 1
        mine = [to_world(p, o, t) for p in rep.pieces]
        hit = False
        for k in near:
            for a in mine:
                for b in oth_pieces[k]:
                    if plane_certificate(a, b)[1] < req:
                        hit = True
                        break
                if hit:
                    break
            if hit:
                break
        blocked += hit
    return blocked / free if free else None


def _run(dec, recs: dict, ids: list[str], weights, alpha, norm, generations: int, pop: int, seed: int, validator,
         spec) -> dict:
    t0 = time.perf_counter()
    ev = Evaluator(dec, ids, {i: part_phys(recs[i]) for i in ids}, {i: recs[i].orient_bounds for i in ids},
                   float(ENCLOSURE_LO[2]))
    n = len(ids)
    order = list(np.argsort([-recs[i].obb_extents_mm.min() for i in ids]))
    r = dec.best_fit_all_orientations(order)
    o_of = {p: o for p, o, _ in r.poses}
    seeds = [seed_keys(order, [o_of.get(i, recs[i].allowed_orients[0]) for i in ids], [recs[i].allowed_orients for i in ids])]
    first = validator.validate([(p, o, np.round(t * 1000) / 1000) for p, o, t in r.poses], spec, want_planes=False)
    first_valid_s = time.perf_counter() - t0 if first.valid and not r.unplaced else None
    rng = np.random.default_rng(seed)
    st = IslandState(pop=np.vstack([np.array(seeds), rng.random((pop - 1, 3 * n))]), rng=rng)
    tg = time.perf_counter()
    run_island(st, ev, norm, weights, alpha, time_budget_s=1e9, max_generations=generations)
    gen_s = (time.perf_counter() - tg) / max(1, generations)
    best = best_candidates(st, 1)[0]
    rep = validator.validate(best.poses, spec, want_planes=False)
    return {"length_used_mm": best.raw.get("L"), "com_error_mm": best.raw.get("D"), "score_g": best.g,
            "first_valid_s": first_valid_s, "valid": rep.valid and not best.unplaced, "generation_s": gen_s,
            "evaluations": st.evaluations, "poses": best.poses, "seconds": time.perf_counter() - t0}


def run_ladder(records: dict, pid: str, sliders: dict, out_path: Path, budget_s: float = 600.0,
               generations: int = 10, pop: int = 40, seed: int = 20261022, fr_samples: int = 150) -> dict:
    """Run the ladder for part `pid` (Stage 1). Progress is written to out_path (JSON) after every level."""
    t_start = time.perf_counter()
    ids = list(records)
    spec = StageSpec(1, ENCLOSURE_LO.copy(), ENCLOSURE_HI.copy(), 0.0, 0.0)
    validator = Validator({i: part_geom_from_record(records[i]) for i in ids})
    rec = records[pid]
    weights = slider_weights(sliders, 1)
    alpha = alpha_from(sliders)
    # one fixed normaliser for every run, from the default box decoder
    base = BoxDecoder([ProxyPart(i, records[i].boxes, records[i].allowed_orients) for i in ids], ENCLOSURE_LO,
                      ENCLOSURE_HI, PLACEMENT_GAP_STAGE1)
    ev0 = Evaluator(base, ids, {i: part_phys(records[i]) for i in ids}, {i: records[i].orient_bounds for i in ids},
                    float(ENCLOSURE_LO[2]))
    rng0 = np.random.default_rng(seed)
    norm = Normaliser()
    norm.update_from([ev0.evaluate(k).raw for k in rng0.random((120, 3 * len(ids)))])
    other = next(records[i] for i in ids if i != pid) if len(ids) > 1 else rec
    ref = base.best_fit_all_orientations(list(np.argsort([-records[i].obb_extents_mm.min() for i in ids])))
    ref_poses = [(p, o, np.round(t * 1000) / 1000) for p, o, t in ref.poses]
    out = {"part_id": pid, "status": "RUNNING", "levels": [], "chosen": {}, "reasons": {}, "stop_reason": None,
           "progress": 0.0, "weights": weights, "budget_s": budget_s, "generations": generations, "population": pop,
           "seeds": seed, "started": time.strftime("%Y-%m-%dT%H:%M:%S"),
           "notes": ["validation always uses the full mesh; levels only change what the search sees",
                     "F2 support polytopes and F5 decimated meshes are not implemented in this build",
                     "false-reject rate: proxy of this part vs certified covers of its neighbours, over random "
                     f"near-contact poses that the true geometry allows ({fr_samples} samples)"]}
    active = {ALG_BOX: True, ALG_HM: True}
    fr_cache: dict[str, float | None] = {}
    stop = {}
    hist = {ALG_BOX: [], ALG_HM: []}

    def save():
        tmp = Path(out_path).with_suffix(".tmp")
        tmp.write_text(json.dumps(_clean(out), indent=1), encoding="utf-8")
        tmp.replace(out_path)

    hull_exact = rec.volume_mm3 is not None and rec.hull_volume_mm3 is not None and \
        rec.hull_volume_mm3 - rec.volume_mm3 <= 1e-6 * rec.volume_mm3
    for li, (level, fam, label, params) in enumerate(LEVELS):
        if not any(active.values()):
            break
        if time.perf_counter() - t_start > budget_s:
            for a in active:
                if active[a]:
                    stop[a] = "time_budget"
            break
        if fam == "F3" and hull_exact:
            continue                      # a convex part's cover is its hull (identical to F2)
        rep = build_representation(rec, level)
        if rep is None:
            continue
        entry = {"level": level, "family": fam, "label": label, "params": rep.params,
                 "proxy_volume_mm3": rep.proxy_volume,
                 "overhead": rep.proxy_volume / rec.volume_mm3 - 1.0 if rec.volume_mm3 else None,
                 "build_s": rep.build_s, "eval_us_median": _median_query_us(rep, rec, other), "results": {},
                 "note": rep.note}
        for alg in (ALG_BOX, ALG_HM):
            if not active[alg] or fam not in APPLICABLE[alg]:
                continue
            if alg == ALG_BOX:
                dec = BoxDecoder([ProxyPart(i, rep.boxes if i == pid else records[i].boxes, records[i].allowed_orients)
                                  for i in ids], ENCLOSURE_LO, ENCLOSURE_HI, PLACEMENT_GAP_STAGE1)
            else:
                parts = {i: ((*rep.mesh, records[i].allowed_orients) if i == pid else
                             (records[i].v, records[i].f, records[i].allowed_orients)) for i in ids}
                dec = HeightmapDecoder(parts, ENCLOSURE_LO, ENCLOSURE_HI, h=rep.h)
            # rule (b): estimate one generation from a few decodes before committing to a full run
            n = len(ids)
            k = np.random.default_rng(1).random((3, 3 * n))
            t0 = time.perf_counter()
            for row in k:
                dec.decode(list(np.argsort(row[:n])), row[n:2 * n], row[2 * n:])
            gen_est = (time.perf_counter() - t0) / 3 * 60
            if gen_est > GEN_BUDGET_S and hist[alg]:
                active[alg] = False
                stop[alg] = "time_budget"
                entry["results"][alg] = {"skipped": f"one generation would take ≈ {gen_est:.1f} s > {GEN_BUDGET_S:.0f} s"}
                continue
            res = _run(dec, records, ids, weights, alpha, norm, generations, pop, seed, validator, spec)
            if level not in fr_cache:
                fr_cache[level] = _false_reject_rate(rep, pid, records, ref_poses, spec, validator, fr_samples)
            res["false_reject_rate"] = fr_cache[level]
            res["decode_ms"] = gen_est / 60 * 1e3
            res.pop("poses")
            entry["results"][alg] = res
            hist[alg].append((li, level, res))
            h_ = hist[alg]
            if len(h_) >= 3 and _close(h_[-3][2], h_[-2][2]) and _close(h_[-2][2], h_[-1][2]):
                active[alg] = False
                stop[alg] = "converged"
        out["levels"].append(entry)
        out["progress"] = (li + 1) / len(LEVELS)
        out["current_level"] = level
        save()
    import pickle
    for alg in (ALG_BOX, ALG_HM):
        stop.setdefault(alg, "max_level")
        if hist[alg]:
            lvl, why = _choose(hist[alg], out["levels"], alg)
            out["chosen"][alg] = lvl
            out["reasons"][alg] = why
            rep = build_representation(rec, lvl) if lvl != DEFAULT_LEVEL[alg] else None
            if rep is not None:            # cached so the search context can use it without rebuilding
                Path(rep_path(out_path, lvl)).write_bytes(pickle.dumps(rep, protocol=pickle.HIGHEST_PROTOCOL))
    out["stop_reasons"] = stop
    out["stop_reason"] = "converged" if all(v == "converged" for v in stop.values()) else \
        ("time_budget" if "time_budget" in stop.values() else "max_level")
    out["status"] = "DONE"
    out["progress"] = 1.0
    out["seconds"] = time.perf_counter() - t_start
    save()
    return out


def _close(a: dict, b: dict) -> bool:
    if not (a.get("valid") and b.get("valid")):
        return False
    dl = abs(a["length_used_mm"] - b["length_used_mm"])
    dg = abs(a["score_g"] - b["score_g"]) / max(abs(b["score_g"]), 1e-12)
    fa, fb = a.get("false_reject_rate"), b.get("false_reject_rate")
    dfr = abs(fa - fb) if fa is not None and fb is not None else 0.0
    return dl < TOL_L_MM and dg < TOL_G_REL and dfr < TOL_FR


def _choose(hist, levels, alg):
    ref_li, ref_level, ref = hist[-1]
    for li, level, r in hist:
        if r.get("valid") and _close(r, ref):
            lvl_entry = next(e for e in levels if e["level"] == level)
            ref_entry = next(e for e in levels if e["level"] == ref_level)
            if level == ref_level:
                return level, (f"{level} ({lvl_entry['label']}) is the most detailed level tested and no cheaper level "
                               "matched it within 0.5 mm, 0.5 % of score and 1 point of false rejects")
            speed = (ref.get("generation_s") or 0) / max(r.get("generation_s") or 1e-9, 1e-9)
            return level, (f"{level} ({lvl_entry['label']}): more detail ({ref_level}, {ref_entry['label']}) changed the "
                           f"best length by {abs(ref['length_used_mm'] - r['length_used_mm']):.2f} mm and the score by "
                           f"{100 * abs(ref['score_g'] - r['score_g']) / max(abs(ref['score_g']), 1e-12):.2f} %, "
                           f"but took {speed:.1f}× as long per generation")
    return ref_level, f"{ref_level}: no cheaper level matched the most detailed one"


def _clean(o):
    if isinstance(o, dict):
        return {str(k): _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, np.ndarray):
        return _clean(o.tolist())
    if isinstance(o, (np.floating, float)):
        return float(o) if np.isfinite(o) else None
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, np.bool_):
        return bool(o)
    return o


def rep_path(out_path, level: str) -> Path:
    p = Path(out_path)
    return p.with_name(f"{p.stem}_{level}.pkl")


def load_choice(out_path) -> tuple[dict, dict]:
    """(result JSON or {}, {algorithm: Representation}) for a finished ladder."""
    import pickle
    p = Path(out_path)
    if not p.exists():
        return {}, {}
    try:
        res = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}, {}
    reps = {}
    if res.get("status") == "DONE":
        for alg, lvl in res.get("chosen", {}).items():
            rp = rep_path(p, lvl)
            if lvl != DEFAULT_LEVEL.get(alg) and rp.exists():
                try:
                    reps[alg] = pickle.loads(rp.read_bytes())
                except Exception:  # noqa: BLE001
                    pass
    return res, reps


def ladder_job(records_path: str, pid: str, sliders: dict, out_path: str, budget_s: float, opts: dict | None = None) -> str:
    """Process-pool entry point. opts: generations, pop, fr_samples, seed (tests use small values)."""
    import pickle
    records = pickle.loads(Path(records_path).read_bytes())
    run_ladder(records, pid, sliders, Path(out_path), budget_s=budget_s, **(opts or {}))
    return out_path
