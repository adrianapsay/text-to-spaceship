"""Worker processes (spawned): long-lived search islands and validators.

Each island keeps its population in memory between short time slices, so a slider move only changes the weights
sent with the next slice and a mass edit only refreshes the physics terms of cached candidates (no re-decode).
Messages are plain tuples over multiprocessing queues; results always carry the context id and mass revision they
were computed for, so the coordinator can drop anything computed for older inputs.
"""
from __future__ import annotations

import os
import time
import traceback

import numpy as np


def _phys_from_wire(phys: dict):
    from ..physics.assembly import PartPhys
    out = {}
    for pid, v in phys.items():
        out[pid] = None if v is None else PartPhys(v[0], np.asarray(v[1], float), np.asarray(v[2], float))
    return out


def _cand_wire(c, k_g=None):
    return {"keys": c.keys, "poses": [(pid, int(o), np.asarray(t, float)) for pid, o, t in c.poses],
            "raw": c.raw, "cv": float(c.cv), "unplaced": list(c.unplaced), "g": float(c.g) if k_g is None else k_g}


def _keys_from_poses(ctx, poses, rng):
    """Warm start: chromosome whose decode order follows the given layout from the bottom up."""
    n = len(ctx.ids)
    idx = {pid: i for i, pid in enumerate(ctx.ids)}
    k = rng.random(3 * n)
    placed = sorted([(float(t[2] + ctx.orient_bounds[pid][o, 2]), pid, o) for pid, o, t in poses if pid in idx])
    for rank, (_, pid, o) in enumerate(placed):
        i = idx[pid]
        k[i] = (rank + 0.5) / (n + 1)
        allowed = ctx.proxies[i].allowed
        if o in allowed:
            k[n + i] = (allowed.index(o) + 0.5) / len(allowed)
        k[2 * n + i] = 0.0
    return k


def island_main(worker_id: int, role: str, cmd_q, res_q, base_seed: int) -> None:
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    from ..collision.geom import part_geom_from_record
    from ..collision.validate import Validator
    from ..optimise.brkga import Evaluator, IslandState, best_candidates, run_island, seed_keys
    from ..optimise.scalarize import Normaliser
    from .context import load_context

    ctx = ev = state = None
    ctx_id = None
    mass_rev = -1
    validator = None
    params = {"elite_frac": 0.2, "mutant_frac": 0.15, "bias": 0.7}
    variants = [{"elite_frac": 0.2, "mutant_frac": 0.15, "bias": 0.7}, {"elite_frac": 0.15, "mutant_frac": 0.2, "bias": 0.65},
                {"elite_frac": 0.25, "mutant_frac": 0.1, "bias": 0.75}, {"elite_frac": 0.2, "mutant_frac": 0.25, "bias": 0.6}]
    params = variants[worker_id % len(variants)]
    res_q.put(("ready", worker_id, role, os.getpid()))
    while True:
        cmd = cmd_q.get()
        kind = cmd[0]
        if kind == "stop":
            break
        try:
            if kind == "context":
                _, new_id, path, mass_rev, phys, target, warm, pop_size, counter = cmd
                ctx = load_context(path)
                ctx_id = new_id
                if role == "validator":
                    validator = Validator({pid: part_geom_from_record(r) for pid, r in ctx.records.items()})
                    res_q.put(("context_ok", worker_id, ctx_id))
                    continue
                dec = ctx.decoder()
                ev = Evaluator(dec, ctx.ids, _phys_from_wire(phys), ctx.orient_bounds, ctx.z0, target=target,
                               com_box=ctx.com_box)
                rng = np.random.default_rng(base_seed + 7919 * worker_id + 104729 * counter)
                n = len(ctx.ids)
                seeds = []
                recs = ctx.records
                orders = [np.argsort([-recs[i].volume_mm3 if recs[i].volume_mm3 else 0 for i in ctx.ids]),
                          np.argsort([-np.prod(recs[i].obb_extents_mm) for i in ctx.ids]),
                          np.argsort([-recs[i].obb_extents_mm.max() for i in ctx.ids]),
                          np.argsort([-recs[i].obb_extents_mm.min() for i in ctx.ids])]
                for order in orders[worker_id % 2::2] if worker_id else orders:
                    r = dec.best_fit_all_orientations(list(order))
                    o_of = {pid: o for pid, o, _ in r.poses}
                    seeds.append(seed_keys(list(order), [o_of.get(i, ctx.proxies[j].allowed[0]) for j, i in enumerate(ctx.ids)],
                                           [p.allowed for p in ctx.proxies]))
                for poses in warm or []:
                    seeds.append(_keys_from_poses(ctx, poses, rng))
                seeds = seeds[:pop_size // 2]
                pop = np.vstack([np.array(seeds).reshape(-1, 3 * n), rng.random((pop_size - len(seeds), 3 * n))])
                state = IslandState(pop=pop, rng=rng)
                res_q.put(("context_ok", worker_id, ctx_id))
            elif kind == "phys":
                _, for_ctx, mass_rev, phys, target = cmd
                if ev is not None and for_ctx == ctx_id:
                    ev.phys = _phys_from_wire(phys)
                    ev.target = np.asarray(target, float)
                    for c in state.cands:
                        ev.refresh(c)
            elif kind == "inject":
                _, for_ctx, keys_list = cmd
                if state is not None and for_ctx == ctx_id and state.cands:
                    from ..optimise.brkga import sort_key
                    order = sorted(range(len(state.cands)), key=lambda i: sort_key(state.cands[i]))
                    for slot, keys in zip(reversed(order), keys_list):
                        c = ev.evaluate(np.asarray(keys, float))
                        state.cands[slot] = c
                        state.pop[slot] = c.keys
                        state.evaluations += 1
            elif kind == "run":
                _, job, for_ctx, budget, weights, alpha, norm_wire, k = cmd
                if state is None or for_ctx != ctx_id:
                    res_q.put(("island", worker_id, job, for_ctx, mass_rev, 0, 0, [], "no context"))
                    continue
                norm = Normaliser(epoch=norm_wire["epoch"], utopia=dict(norm_wire["utopia"]), nadir=dict(norm_wire["nadir"]))
                e0, g0 = state.evaluations, state.generations
                t0 = time.perf_counter()
                run_island(state, ev, norm, weights, alpha, time_budget_s=budget, **params)
                best = best_candidates(state, k)
                res_q.put(("island", worker_id, job, ctx_id, mass_rev, state.evaluations - e0, state.generations - g0,
                           [_cand_wire(c) for c in best], f"{time.perf_counter() - t0:.2f}s"))
            elif kind == "validate":
                _, job, for_ctx, poses, want_planes = cmd
                if validator is None or for_ctx != ctx_id:
                    res_q.put(("validated", worker_id, job, for_ctx, None))
                    continue
                rep = validator.validate(poses, ctx.spec, want_planes=want_planes)
                res_q.put(("validated", worker_id, job, ctx_id, {
                    "valid": rep.valid, "min_clearance_mm": rep.min_clearance_mm, "levels": rep.levels,
                    "violations": rep.violations[:20], "pairs": len(rep.pairs), "statics": len(rep.statics),
                    "seconds": rep.seconds, "validator_version": rep.validator_version}))
        except Exception as exc:  # noqa: BLE001
            res_q.put(("error", worker_id, f"{type(exc).__name__}: {exc}", traceback.format_exc()))
