"""Objective normalisation and augmented weighted Tchebycheff scalarisation (protocol §F.4–F.6).

Raw objectives (all minimised): L length used (mm), D COM error (mm), T inertia trace (kg·m²), P products-of-inertia
norm (kg·m²), G feasibility margin in [0, 1] (Stage 2 only), H blocked cable-corridor fraction (Stage 2), C hardware
cost (relative units, Manufacturable Design). The inertia objective is I = α·T̂ + (1 − α)·P̂.
Hard constraints never enter g: candidates are compared by (CV, g).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

RHO = 1e-3
FLOORS = {"L": 1.0, "D": 0.5, "T": None, "P": None, "G": 0.05, "H": 0.05, "C": 1.0}

PRESETS = {
    "max_packing": {"space": 70, "balance": 10, "inertia": 10, "feasibility": 10},
    "com_priority": {"space": 10, "balance": 70, "inertia": 10, "feasibility": 10},
    "min_inertia": {"space": 10, "balance": 10, "inertia": 70, "feasibility": 10},
    "balanced": {"space": 25, "balance": 25, "inertia": 25, "feasibility": 25},
}


@dataclass
class Normaliser:
    epoch: int = 0
    utopia: dict = field(default_factory=dict)
    nadir: dict = field(default_factory=dict)
    provisional: bool = True

    def update_from(self, raws: list[dict], keys=("L", "D", "T", "P", "G", "H", "C")) -> None:
        """New epoch from a set of validated raw objective vectors (payoff table ∪ archive)."""
        self.epoch += 1
        for k in keys:
            vals = np.array([r[k] for r in raws if k in r and np.isfinite(r[k])], float)
            if len(vals) == 0:
                continue
            lo, hi = float(vals.min()), float(vals.max())
            if k in ("D", "P", "G", "H", "C"):
                lo = 0.0
            else:
                lo = lo - 0.01 * max(hi - lo, 1e-12)
            floor = FLOORS.get(k)
            if floor is None:
                floor = 0.01 * max(abs(lo), abs(hi), 1e-12)
            if hi - lo < floor:
                hi = lo + floor
            self.utopia[k], self.nadir[k] = lo, hi

    def norm(self, raw: dict) -> dict:
        out = {}
        for k, v in raw.items():
            if k in self.utopia and v is not None and np.isfinite(v):
                out[k] = (v - self.utopia[k]) / (self.nadir[k] - self.utopia[k])
        return out


def slider_weights(sliders: dict, stage: int, mode: str = "default") -> dict:
    """Map 0..100 sliders to strictly positive objective weights (w = (s+1)/Σ(s+1))."""
    active = {"L": sliders.get("space", 25), "D": sliders.get("balance", 25), "I": sliders.get("inertia", 25)}
    if stage == 2:
        active["G"] = sliders.get("feasibility", 25)
        if sliders.get("cable", 0) > 0:
            active["H"] = sliders.get("cable", 0)
    if mode == "manufacturable" or sliders.get("cost", 0) > 0 and stage == 2:
        active["C"] = sliders.get("cost", 0)
    tot = sum(s + 1 for s in active.values())
    return {k: (s + 1) / tot for k, s in active.items()}


def scalarise(nrm: dict, weights: dict, alpha: float) -> float:
    terms = {}
    for k, w in weights.items():
        if k == "I":
            if "T" in nrm and "P" in nrm:
                terms[k] = w * (alpha * nrm["T"] + (1 - alpha) * nrm["P"])
        elif k in nrm:
            terms[k] = w * nrm[k]
    if not terms:
        return np.inf
    vals = np.array(list(terms.values()))
    return float(vals.max() + RHO * vals.sum())


def alpha_from(sliders: dict) -> float:
    """α = weight of the trace inside I; the Expert 'mass-distribution symmetry' slider raises the products' share."""
    return 1.0 - float(np.clip(sliders.get("mass_symmetry", 50), 0, 100)) / 100.0


def dominates(a: dict, b: dict, keys) -> bool:
    return all(a[k] <= b[k] for k in keys) and any(a[k] < b[k] for k in keys)
