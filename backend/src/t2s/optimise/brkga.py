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


def run_island(state: IslandState, ev: Evaluator, norm: Normaliser, weights: dict, alpha: float,
               time_budget_s: float = 0.5, max_generations: int | None = None, elite_frac: float = 0.2,
               mutant_frac: float = 0.15, bias: float = 0.7) -> IslandState:
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
        state.cands = elites + new
        state.pop = np.array([c.keys for c in state.cands])
        state.evaluations += len(new)
        gens += 1
    state.generations += gens
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
