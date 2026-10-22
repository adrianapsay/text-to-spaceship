"""Biased random-key GA over the box decoder (protocol §F.7; Gonçalves & Resende 2013; Londe et al.).

Chromosome: 3n keys in [0, 1): order (argsort), orientation (index into the part's allowed set), placement rule.
The decoder is weight-independent, so raw objective vectors are cached and re-scored when weights change.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

import numpy as np

from ..core.rotations import ROTATIONS_F
from ..decoders.box_decoder import BoxDecoder
from ..physics.assembly import PartPhys, assembly, inertia_metrics
from .scalarize import Normaliser, scalarise


@dataclass
class Candidate:
    keys: np.ndarray
    poses: list
    raw: dict
    cv: float
    g: float = np.inf
    unplaced: list = field(default_factory=list)


@dataclass
class IslandState:
    pop: np.ndarray
    cands: list = field(default_factory=list)       # Candidate per row of pop
    rng: np.random.Generator | None = None
    generations: int = 0
    evaluations: int = 0


class Evaluator:
    """Decode + raw objectives, all geometry-only except the physics terms (which use current masses)."""

    def __init__(self, decoder: BoxDecoder, ids: list[str], phys: dict[str, PartPhys | None], orient_bounds: dict,
                 z0: float, target=(0.0, 0.0, 0.0), com_box=None):
        self.dec = decoder
        self.ids = ids
        self.phys = phys
        self.bounds = orient_bounds
        self.z0 = z0
        self.target = np.asarray(target, float)
        self.com_box = com_box                 # (3,) half-widths when the CDS box is hard (Stage 2)

    def raw_from_poses(self, poses, unplaced) -> tuple[dict, float]:
        tops = [t[2] + self.bounds[pid][o, 5] for pid, o, t in poses]
        bottoms = [t[2] + self.bounds[pid][o, 2] for pid, o, t in poses]
        items = []
        for pid, o, t in poses:
            p = self.phys.get(pid)
            if p is None:
                continue
            r = ROTATIONS_F[o]
            items.append((p.mass_kg, r @ p.com_can_mm + t, r @ p.inertia_com_kgm2 @ r.T))
        raw = {"L": float(max(tops) - self.z0) if tops else 0.0, "span": float(max(tops) - min(bottoms)) if tops else 0.0}
        cv = float(len(unplaced))
        if items:
            a = assembly([], [], np.zeros((0, 3)), items)
            i = a.inertia_kgm2
            raw["D"] = float(np.linalg.norm(a.com_mm - self.target))
            raw["T"] = float(np.trace(i))
            raw["P"] = float(np.sqrt(i[0, 1] ** 2 + i[0, 2] ** 2 + i[1, 2] ** 2))
            raw["lambda_max"] = float(np.linalg.eigvalsh(i)[-1])
            raw["com"] = a.com_mm.tolist()
            if self.com_box is not None:
                excess = np.maximum(np.abs(a.com_mm) - self.com_box, 0.0)
                cv += float(excess.sum() / 10.0)
        return raw, cv

    def evaluate(self, keys: np.ndarray) -> Candidate:
        n = len(self.ids)
        res = self.dec.decode(list(np.argsort(keys[:n], kind="stable")), keys[n:2 * n], keys[2 * n:])
        poses = [(pid, o, np.round(t * 1000.0) / 1000.0) for pid, o, t in res.poses]   # wire poses: integer µm
        raw, cv = self.raw_from_poses(poses, res.unplaced)
        return Candidate(keys.copy(), poses, raw, cv, unplaced=list(res.unplaced))

    def refresh(self, c: Candidate) -> None:
        """Recompute the physics terms after a mass edit (geometry unchanged)."""
        c.raw, c.cv = self.raw_from_poses(c.poses, c.unplaced)


def score(c: Candidate, norm: Normaliser, weights: dict, alpha: float) -> float:
    if norm.utopia:
        c.g = scalarise(norm.norm(c.raw), weights, alpha)
    else:
        c.g = c.raw.get("L", np.inf)
    return c.g


def sort_key(c: Candidate):
    return (c.cv, c.g)


def seed_keys(order: list[int], orients: list[int], allowed: list[list[int]], rule: float = 0.0) -> np.ndarray:
    n = len(order)
    k = np.zeros(3 * n)
    for rank, idx in enumerate(order):
        k[idx] = (rank + 0.5) / n
    for i, o in enumerate(orients):
        a = allowed[i]
        k[n + i] = (a.index(o) + 0.5) / len(a) if o in a else 0.5
    k[2 * n:] = rule
    return k


def neighbour(keys: np.ndarray, n: int, allowed_sizes: list[int], rng) -> np.ndarray:
    """One key-space move (protocol §F.7 memetic moves): re-orient, swap, re-insert or re-rule one part."""
    k = keys.copy()
    m = rng.integers(4)
    i = int(rng.integers(n))
    if m == 0 and allowed_sizes[i] > 1:
        cur = min(int(k[n + i] * allowed_sizes[i]), allowed_sizes[i] - 1)
        new = (cur + 1 + int(rng.integers(allowed_sizes[i] - 1))) % allowed_sizes[i]
        k[n + i] = (new + 0.5) / allowed_sizes[i]
    elif m == 1:
        j = int(rng.integers(n - 1))
        j = j + 1 if j >= i else j
        k[i], k[j] = k[j], k[i]
    elif m == 2:
        k[i] = rng.random()
    else:
        k[2 * n + i] = 0.0 if k[2 * n + i] > 0.5 else 1.0
    return k


def local_search(c: Candidate, ev: Evaluator, norm: Normaliser, weights: dict, alpha: float, rng,
                 moves: int, sizes: list[int]) -> tuple[Candidate, int]:
    """First-improvement descent on one elite; the improved chromosome is written back (Lamarckian)."""
    n = len(ev.ids)
    best = c
    for _ in range(moves):
        cand = ev.evaluate(neighbour(best.keys, n, sizes, rng))
        score(cand, norm, weights, alpha)
        if sort_key(cand) < sort_key(best):
            best = cand
    return best, moves


def run_island(state: IslandState, ev: Evaluator, norm: Normaliser, weights: dict, alpha: float,
               time_budget_s: float = 0.5, max_generations: int | None = None, elite_frac: float = 0.2,
               mutant_frac: float = 0.15, bias: float = 0.7, ls_elites: int = 2, ls_moves: int = 6) -> IslandState:
    """Advance an island for a time slice. Existing candidates are re-scored first (weights may have changed)."""
    rng = state.rng
    dim = state.pop.shape[1]
    p = state.pop.shape[0]
    if len(state.cands) != p:
        state.cands = [ev.evaluate(k) for k in state.pop]
        state.evaluations += p
    for c in state.cands:
        score(c, norm, weights, alpha)
    t_end = time.perf_counter() + time_budget_s
    ne, nm = max(1, int(elite_frac * p)), max(1, int(mutant_frac * p))
    gens = 0
    while time.perf_counter() < t_end and (max_generations is None or gens < max_generations):
        order = sorted(range(p), key=lambda i: sort_key(state.cands[i]))
        elites = [state.cands[i] for i in order[:ne]]
        non = [state.cands[i] for i in order[ne:]]
        children = []
        for _ in range(p - ne - nm):
            e = elites[rng.integers(ne)].keys
            o = non[rng.integers(len(non))].keys
            mask = rng.random(dim) < bias
            children.append(np.where(mask, e, o))
        mutants = list(rng.random((nm, dim)))
        new = [ev.evaluate(k) for k in children + mutants]
        for c in new:
            score(c, norm, weights, alpha)
        if ls_elites and ls_moves:
            sizes = [len(ev.dec.parts[pid].allowed) for pid in ev.ids]
            for e_i in range(min(ls_elites, len(elites))):
                improved, used = local_search(elites[e_i], ev, norm, weights, alpha, rng, ls_moves, sizes)
                elites[e_i] = improved
                state.evaluations += used
        state.cands = elites + new
        state.pop = np.array([c.keys for c in state.cands])
        state.evaluations += len(new)
        gens += 1
    state.generations += gens
    return state


@dataclass
class LahcState:
    """Late-acceptance hill climbing on one chromosome (refiner island, protocol §F.7)."""
    current: Candidate | None = None
    best: Candidate | None = None
    hist: np.ndarray | None = None
    it: int = 0
    evaluations: int = 0
    generations: int = 0
    weights_key: tuple | None = None


def run_lahc(state: LahcState, ev: Evaluator, norm: Normaliser, weights: dict, alpha: float, rng,
             time_budget_s: float = 0.5, hist_len: int = 60) -> LahcState:
    n = len(ev.ids)
    sizes = [len(ev.dec.parts[pid].allowed) for pid in ev.ids]
    wkey = (tuple(sorted(weights.items())), alpha, norm.epoch)
    for c in (state.current, state.best):
        score(c, norm, weights, alpha)
    if state.hist is None or state.weights_key != wkey:
        state.hist = np.full(hist_len, state.current.g)     # g values are only comparable under fixed weights
        state.weights_key = wkey
        if sort_key(state.current) < sort_key(state.best):
            state.best = state.current
    t_end = time.perf_counter() + time_budget_s
    while time.perf_counter() < t_end:
        k = neighbour(state.current.keys, n, sizes, rng)
        if rng.random() < 0.3:
            k = neighbour(k, n, sizes, rng)
        cand = ev.evaluate(k)
        score(cand, norm, weights, alpha)
        state.evaluations += 1
        v = state.it % hist_len
        cur = state.current
        if sort_key(cand) <= sort_key(cur) or (cand.cv == 0 and cur.cv == 0 and cand.g <= state.hist[v]):
            state.current = cand
        if state.current.cv == 0 and state.current.g < state.hist[v]:
            state.hist[v] = state.current.g
        if sort_key(state.current) < sort_key(state.best):
            state.best = state.current
        state.it += 1
    state.generations += 1
    return state


def best_candidates(state: IslandState, k: int = 3) -> list[Candidate]:
    seen, out = set(), []
    for c in sorted(state.cands, key=sort_key):
        key = tuple((pid, o, tuple(np.round(t, 4))) for pid, o, t in c.poses)
        if key in seen:
            continue
        seen.add(key)
        out.append(c)
        if len(out) >= k:
            break
    return out
