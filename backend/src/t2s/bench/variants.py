"""Benchmark variants (protocol §J.3) run at a fixed evaluation budget.

The budget is counted in box-decode equivalents: one box decode costs 1, a height-map decode costs its measured
time ratio, and a constructive best-fit pass costs the number of orientations it tries per part. Every candidate
goes through one counting evaluator, which keeps the anytime trace (best (CV, g) after each 100 units) and the
run's non-dominated front in (L, D, T). Scores use one normaliser frozen per instance and preset, so g is
comparable across variants and seeds.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

import numpy as np

from ..decoders.box_decoder import PLACEMENT_GAP_STAGE1, BoxDecoder, ProxyPart
from ..objectives.metrics import ENCLOSURE_HI, ENCLOSURE_LO, part_phys
from ..optimise.brkga import (Candidate, Evaluator, IslandState, LahcState, run_island, run_lahc,
                              score, seed_keys, sort_key)
from ..optimise.scalarize import PRESETS, Normaliser, alpha_from, slider_weights

VARIANTS = {
    "V1": "Constructive multistart (best-fit, all orientations)",
    "V2": "BRKGA, box decoder",
    "V3": "LAHC alone, box decoder",
    "V4": "BRKGA + local search, box decoder",
    "V5": "Full hybrid, box decoder (islands + migration + refiner + NSGA-II)",
    "V5m": "Hybrid portfolio, box + height-map islands",
    "V6": "Independent portfolio (no migration, no local search)",
    "V7": "Hybrid, height-map decoder",
    "V9": "NSGA-II alone (pymoo), box decoder",
}
SELECTOR_ID = {"V5": "hybrid_box", "V7": "hybrid_heightmap", "V5m": "portfolio", "V1": "box_constructive",
               "V9": "nsga2_box"}


class BudgetExhausted(Exception):
    pass


@dataclass
class Counter:
    """Counting evaluator for one decoder; all counters of a run share one budget (`shared["used"]`)."""
    ev: Evaluator
    cost: float
    budget: float
    norm: Normaliser
    weights: dict
    alpha: float
    shared: dict = field(default_factory=lambda: {"used": 0.0})
    used: float = 0.0
    best: Candidate | None = None
    trace: list = field(default_factory=list)
    front: list = field(default_factory=list)
    next_mark: float = 100.0
    t0: float = field(default_factory=time.perf_counter)
    first_valid: float | None = None

    @property
    def ids(self):
        return self.ev.ids

    @property
    def dec(self):
        return self.ev.dec

    @property
    def dim(self):
        return self.ev.dim

    def refresh(self, c):
        self.ev.refresh(c)

    def evaluate(self, keys, cost: float | None = None) -> Candidate:
        if self.shared["used"] >= self.budget:
            raise BudgetExhausted
        c = self.ev.evaluate(keys)
        self.shared["used"] += self.cost if cost is None else cost
        self.used = self.shared["used"]
        score(c, self.norm, self.weights, self.alpha)
        self._observe(c)
        return c

    def _observe(self, c: Candidate) -> None:
        if c.cv == 0 and not c.unplaced:
            if self.first_valid is None:
                self.first_valid = self.used
            p = (c.raw["L"], c.raw.get("D", np.inf), c.raw.get("T", np.inf))
            if not any(all(q[k] <= p[k] for k in range(3)) for q in self.front):
                self.front = [q for q in self.front if not all(p[k] <= q[k] for k in range(3))] + [p]
                if len(self.front) > 300:
                    self.front = self.front[-300:]
        if self.best is None or sort_key(c) < sort_key(self.best):
            self.best = c
        while self.used >= self.next_mark:
            self.trace.append((self.next_mark, self.best.cv, self.best.g, self.best.raw.get("L")))
            self.next_mark += 100.0


@dataclass
class Setup:
    """Decoders and scoring shared by all runs of one (instance, preset)."""
    instance: object
    preset: str
    weights: dict
    alpha: float
    norm: Normaliser
    decoders: dict                  # "box" | "heightmap" | "stage2" -> decoder
    cost: dict                      # decoder kind -> cost per decode (box = 1)
    evaluators: dict


def make_setup(instance, preset: str, seed: int = 99) -> Setup:
    recs = instance.records
    ids = list(recs)
    phys = {i: part_phys(recs[i]) for i in ids}
    bounds = {i: recs[i].orient_bounds for i in ids}
    decoders, cost = {}, {}
    if instance.stage == 2:
        from ..constraints.stage2_model import Stage2Model
        decoders["box"] = Stage2Model(recs, "default")
        z0 = float(decoders["box"].inner[0][2])
        com_box = np.array([20.0, 20.0, 70.0])
    else:
        decoders["box"] = BoxDecoder([ProxyPart(i, recs[i].boxes, recs[i].allowed_orients) for i in ids], ENCLOSURE_LO,
                                     ENCLOSURE_HI, PLACEMENT_GAP_STAGE1)
        from ..decoders.heightmap import HeightmapDecoder
        decoders["heightmap"] = HeightmapDecoder({i: (recs[i].v, recs[i].f, recs[i].allowed_orients) for i in ids},
                                                 ENCLOSURE_LO, ENCLOSURE_HI, h=2.0)
        z0 = float(ENCLOSURE_LO[2])
        com_box = None
    evs = {k: Evaluator(d, ids, phys, bounds, z0, com_box=com_box) for k, d in decoders.items()}
    rng = np.random.default_rng(seed)
    n = len(ids)
    keys = rng.random((60, evs["box"].dim))
    for k, ev in evs.items():                      # measured relative decode cost (box = 1)
        ev.evaluate(keys[0])
        t0 = time.perf_counter()
        for row in keys[1:21]:
            ev.evaluate(row)
        cost[k] = time.perf_counter() - t0
    base = cost["box"]
    cost = {k: max(1.0, v / base) for k, v in cost.items()}
    raws = [evs["box"].evaluate(k).raw for k in rng.random((300, evs["box"].dim))]
    norm = Normaliser()
    norm.update_from([r for r in raws if "D" in r])
    w = slider_weights(PRESETS[preset], instance.stage)
    return Setup(instance, preset, w, alpha_from(PRESETS[preset]), norm, decoders, cost, evs)


def _seeds(setup: Setup, kind: str, count: int = 2) -> list[np.ndarray]:
    recs = setup.instance.records
    ids = list(recs)
    dec = setup.decoders[kind]
    n = len(ids)
    dim = setup.evaluators[kind].dim
    allowed = [dec.parts[i].allowed for i in ids]
    out = []
    for order in (np.argsort([-recs[i].obb_extents_mm.min() for i in ids]),
                  np.argsort([-(recs[i].volume_mm3 or 0) for i in ids]))[:count]:
        r = dec.best_fit_all_orientations(list(order))
        hint = getattr(r, "keys_hint", None)
        o_of = {p: o for p, o, _ in r.poses}
        s = seed_keys(list(order), [o_of.get(i) if o_of.get(i) in allowed[j] else allowed[j][0]
                                    for j, i in enumerate(ids)], allowed)
        if hint is not None:
            s[n:2 * n] = hint[0]
            s = np.concatenate([s[:2 * n], hint[1]])
        out.append(np.concatenate([s, np.full(max(0, dim - len(s)), 0.5)])[:dim])
    return out


def _brkga(counter, rng, seeds, pop=60, ls=(2, 6), params=None):
    st = IslandState(pop=np.vstack([np.array(seeds).reshape(-1, counter.dim),
                                    rng.random((pop - len(seeds), counter.dim))]), rng=rng)
    return st, dict(ls_elites=ls[0], ls_moves=ls[1], **(params or {}))


def run_variant(setup: Setup, variant: str, seed: int, budget: float) -> dict:
    rng = np.random.default_rng(np.random.SeedSequence([seed, 7]))
    kinds = ["box"] if variant not in ("V7", "V5m") else (["heightmap"] if variant == "V7" else ["box", "heightmap"])
    if setup.instance.stage == 2:
        kinds = ["box"]
    shared = {"used": 0.0}                     # one budget across decoders
    counters = {k: Counter(setup.evaluators[k], setup.cost[k], budget, setup.norm, setup.weights, setup.alpha, shared)
                for k in kinds}
    t0 = time.perf_counter()
    try:
        _dispatch(variant, setup, counters, rng)
    except BudgetExhausted:
        pass
    best = min((c.best for c in counters.values() if c.best is not None), key=sort_key)
    front = []
    for c in counters.values():
        for p in c.front:
            if not any(all(q[k] <= p[k] for k in range(3)) and q != p for q in front):
                front = [q for q in front if not all(p[k] <= q[k] for k in range(3))] + [p]
    trace = sorted(sum((c.trace for c in counters.values()), []))
    first = [c.first_valid for c in counters.values() if c.first_valid is not None]
    return {"variant": variant, "seed": seed, "best": best, "front": front, "trace": trace,
            "used": shared["used"], "seconds": time.perf_counter() - t0, "first_valid": min(first) if first else None}


def _dispatch(variant, setup, counters, rng):
    box = counters.get("box")
    hm = counters.get("heightmap")
    main = box or hm
    if variant == "V1":
        dec = setup.decoders["box"]
        recs = setup.instance.records
        ids = list(recs)
        n = len(ids)
        per = float(np.mean([len(dec.parts[i].allowed) for i in ids]))
        first = True
        while True:
            order = np.argsort([-recs[i].obb_extents_mm.min() for i in ids]) if first else rng.permutation(n)
            first = False
            s = _seeds_for_order(setup, "box", order)
            main.evaluate(s, cost=per)
    elif variant in ("V2", "V4"):
        st, kw = _brkga(main, rng, _seeds(setup, "box"), ls=(2, 6) if variant == "V4" else (0, 0))
        while True:
            run_island(st, main, setup.norm, setup.weights, setup.alpha, time_budget_s=1e9, max_generations=1, **kw)
    elif variant == "V3":
        seeds = _seeds(setup, "box")
        c0 = min((main.evaluate(s) for s in seeds), key=sort_key)
        st = LahcState(current=c0, best=c0)
        while True:
            run_lahc(st, main, setup.norm, setup.weights, setup.alpha, rng, time_budget_s=1e9, max_iters=60)
    elif variant == "V9":
        gen = _nsga_gen(main, rng, _seeds(setup, "box"))
        while True:
            next(gen)
    else:
        _islands(variant, setup, counters, rng)


def _seeds_for_order(setup, kind, order):
    recs = setup.instance.records
    ids = list(recs)
    dec = setup.decoders[kind]
    n = len(ids)
    dim = setup.evaluators[kind].dim
    allowed = [dec.parts[i].allowed for i in ids]
    r = dec.best_fit_all_orientations(list(order))
    hint = getattr(r, "keys_hint", None)
    o_of = {p: o for p, o, _ in r.poses}
    s = seed_keys(list(order), [o_of.get(i) if o_of.get(i) in allowed[j] else allowed[j][0] for j, i in enumerate(ids)],
                  allowed)
    if hint is not None:
        s[n:2 * n] = hint[0]
        s = np.concatenate([s[:2 * n], hint[1]])
    return np.concatenate([s, np.full(max(0, dim - len(s)), 0.5)])[:dim]


def _islands(variant, setup, counters, rng):
    """Island model emulated in one process: round-robin slices of a few generations, migration of the best."""
    migrate = variant in ("V5", "V5m", "V7")
    ls = (2, 6) if variant != "V6" else (0, 0)
    plan = {"V5": ["box", "box", "lahc:box", "nsga:box"], "V7": ["heightmap", "heightmap", "lahc:heightmap", "nsga:heightmap"],
            "V5m": ["box", "heightmap", "lahc:box", "nsga:box"], "V6": ["box", "box", "lahc:box", "nsga:box"]}[variant]
    islands = []
    for k, spec in enumerate(plan):
        kind = spec.split(":")[-1]
        c = counters[kind]
        seeds = _seeds(setup, kind, 1 + (k % 2))
        r = np.random.default_rng(rng.integers(2 ** 31))
        if spec.startswith("lahc"):
            c0 = min((c.evaluate(s) for s in seeds), key=sort_key)
            islands.append(("lahc", c, LahcState(current=c0, best=c0), r))
        elif spec.startswith("nsga"):
            gen = _nsga_gen(c, r, seeds)
            islands.append(("nsga", c, gen, r))
        else:
            params = [{"elite_frac": 0.2, "mutant_frac": 0.15, "bias": 0.7},
                      {"elite_frac": 0.15, "mutant_frac": 0.2, "bias": 0.65}][k % 2]
            st, kw = _brkga(c, r, seeds, ls=ls, params=params)
            islands.append(("brkga", c, (st, kw), r))
    rnd = 0
    while True:
        for kind, c, state, r in islands:
            if kind == "brkga":
                st, kw = state
                run_island(st, c, setup.norm, setup.weights, setup.alpha, time_budget_s=1e9, max_generations=1, **kw)
            elif kind == "lahc":
                run_lahc(state, c, setup.norm, setup.weights, setup.alpha, r, time_budget_s=1e9, max_iters=60)
            else:
                next(state)
        rnd += 1
        if migrate and rnd % 4 == 0:
            bests = [c.best for _, c, _, _ in islands if c.best is not None]
            if not bests:
                continue
            gbest = min(bests, key=sort_key)
            for kind, c, state, r in islands:
                if kind == "brkga" and c.ev.dec is gbest_dec(gbest, counters):
                    st, _ = state
                    worst = max(range(len(st.cands)), key=lambda i: sort_key(st.cands[i]))
                    st.cands[worst] = gbest
                    st.pop[worst] = gbest.keys
                elif kind == "lahc" and c.ev.dec is gbest_dec(gbest, counters) and sort_key(gbest) < sort_key(state.current):
                    state.current = gbest
                    state.hist = None


def gbest_dec(c, counters):
    for k in counters.values():
        if c is k.best:
            return k.ev.dec
    return None


def _nsga_gen(counter, rng, seeds):
    from pymoo.algorithms.moo.nsga2 import NSGA2
    from pymoo.core.evaluator import Evaluator as PE
    from pymoo.core.problem import Problem
    from pymoo.problems.static import StaticProblem
    dim = counter.dim
    prob = Problem(n_var=dim, n_obj=3, n_ieq_constr=1, xl=np.zeros(dim), xu=np.full(dim, 1 - 1e-9))
    X0 = np.vstack([np.array(seeds).reshape(-1, dim), rng.random((60 - len(seeds), dim))])
    alg = NSGA2(pop_size=60, sampling=X0, eliminate_duplicates=True)
    alg.setup(prob, termination=("n_gen", 10 ** 9), seed=int(rng.integers(2 ** 31)), verbose=False)
    while True:
        pop = alg.ask()
        X = np.clip(pop.get("X"), 0, 1 - 1e-9)
        F = np.empty((len(X), 3))
        G = np.empty((len(X), 1))
        for i, x in enumerate(X):
            c = counter.evaluate(x)
            F[i] = [c.raw.get("L", 1e9), c.raw.get("D", 1e9), c.raw.get("T", 1e9)]
            G[i, 0] = c.cv
        PE().eval(StaticProblem(prob, F=F, G=G), pop)
        alg.tell(infills=pop)
        yield None
