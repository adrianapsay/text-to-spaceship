"""Algorithm selector (Addendum 3.1): deterministic, fast, sweepable.

select_algorithm(stage, weights, part_stats, modes) -> AlgorithmChoice. Until the M8 benchmarks provide evidence,
a documented default rule set decides; every choice says so ("default rule — no benchmark evidence yet").
When an evidence table is supplied (M8), the variant with the best median benchmark result at the nearest
measured weight vector wins (performance-based selection, Rice 1976).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .scalarize import slider_weights

ALGORITHMS = {
    "hybrid_box": "Hybrid BRKGA + box decoder",
    "hybrid_heightmap": "Hybrid BRKGA + height-map decoder",
    "portfolio": "Portfolio: box + height-map islands",
    "box_constructive": "Constructive best-fit (box decoder)",
}

# default-rule thresholds (ASSUMED; replaced by benchmark evidence in M8)
L_WEIGHT_NESTING = 0.40      # packing weight from which nesting curved parts is worth the slower decoder
L_WEIGHT_FAST = 0.20         # below this, compactness hardly matters: more evaluations beat tighter nesting
BOX_OVERHEAD_NESTING = 0.25  # box proxies over-cover the solids by at least this share


@dataclass
class PartStats:
    n_parts: int
    volume_mm3: float
    box_overhead: float            # sum(box proxy volume) / sum(solid volume) - 1
    shares: dict = field(default_factory=dict)   # label group -> volume share


def part_stats(records) -> PartStats:
    recs = [r for r in records if r.volume_mm3]
    vol = sum(r.volume_mm3 for r in recs)
    boxes = sum(float(np.prod(r.boxes[:, 3:] - r.boxes[:, :3], axis=1).sum()) for r in recs)
    groups = {"box-like": ("box-like",), "convex": ("convex",), "curved": ("curved",),
              "concave": ("mildly concave", "strongly concave"), "through-hole": ("through-hole",)}
    shares = {}
    for g, labs in groups.items():
        v = sum(r.volume_mm3 for r in recs if any(any(lab.startswith(x) for x in labs) for lab in r.labels))
        shares[g] = v / vol if vol else 0.0
    return PartStats(len(records), vol, boxes / vol - 1.0 if vol else 0.0, shares)


@dataclass
class AlgorithmChoice:
    id: str
    label: str
    decoder: str                   # box | heightmap | mixed
    search: str
    mode: str
    reasons: list[str]
    evidence: list[dict]
    rule: str                      # "default" | "evidence"

    def to_json(self) -> dict:
        return {"algorithm": {"id": self.id, "label": self.label, "reason": self.reasons[0] if self.reasons else ""},
                "decoder": self.decoder, "search": self.search, "mode": self.mode, "reasons": self.reasons,
                "evidence": self.evidence, "rule": self.rule}


def select_algorithm(stage: int, sliders: dict, stats: PartStats, mode: str = "default",
                     evidence: list[dict] | None = None) -> AlgorithmChoice:
    w = slider_weights(sliders, stage, mode)
    wl = w.get("L", 0.0)
    if evidence:
        best = _from_evidence(stage, w, stats, evidence)
        if best is not None:
            return best
    tag = "default rule — no benchmark evidence yet"
    if mode == "continuous_cable":
        return AlgorithmChoice("hybrid_box", ALGORITHMS["hybrid_box"], "box", "brkga+lahc", mode,
                               [f"cable-routing importance high: continuous harness channel kept free ({tag})"], [], "default")
    if stage == 2:
        return AlgorithmChoice("hybrid_box", ALGORITHMS["hybrid_box"], "box", "brkga+lahc", mode,
                               [f"Stage 2: the box decoder models the frame, rails and harness keep-outs ({tag})"], [],
                               "default")
    ov = stats.box_overhead
    if wl >= L_WEIGHT_NESTING and ov >= BOX_OVERHEAD_NESTING:
        return AlgorithmChoice(
            "hybrid_heightmap", ALGORITHMS["hybrid_heightmap"], "heightmap", "brkga+lahc", mode,
            [f"weight on compactness {wl:.2f} ≥ {L_WEIGHT_NESTING:.2f} and the box proxies over-cover the solids by "
             f"{100 * ov:.0f} % ≥ {100 * BOX_OVERHEAD_NESTING:.0f} %: the height-map decoder nests curved and hollow "
             f"parts ({tag})"], [], "default")
    if wl < L_WEIGHT_FAST:
        return AlgorithmChoice(
            "hybrid_box", ALGORITHMS["hybrid_box"], "box", "brkga+lahc", mode,
            [f"weight on compactness {wl:.2f} < {L_WEIGHT_FAST:.2f}: balance and inertia dominate, and the box decoder "
             f"evaluates about twice as many layouts per second ({tag})"], [], "default")
    return AlgorithmChoice(
        "portfolio", ALGORITHMS["portfolio"], "mixed", "brkga+lahc", mode,
        [f"weight on compactness {wl:.2f} is between {L_WEIGHT_FAST:.2f} and {L_WEIGHT_NESTING:.2f}"
         + (f" (box overhead {100 * ov:.0f} %)" if wl >= L_WEIGHT_NESTING else "")
         + f": islands are split between both decoders and the archive keeps whichever layouts score better ({tag})"],
        [], "default")


def _from_evidence(stage, w, stats, evidence):
    rows = [e for e in evidence if e.get("stage") == stage and e.get("algorithm") in ALGORITHMS]
    if not rows:
        return None
    keys = sorted(w)

    def dist(e):
        ew = e.get("weights", {})
        return float(np.sqrt(sum((w.get(k, 0) - ew.get(k, 0)) ** 2 for k in keys)))
    near = min(dist(e) for e in rows)
    cand = [e for e in rows if dist(e) <= near + 1e-9]
    best = min(cand, key=lambda e: e["median_g"])
    alg = best["algorithm"]
    dec = {"hybrid_box": "box", "hybrid_heightmap": "heightmap", "portfolio": "mixed", "box_constructive": "box"}[alg]
    reasons = [f"best median benchmark score at the nearest measured weights: {best['median_g']:.4f} "
               f"(n = {best.get('n', '?')}) vs " + ", ".join(f"{e['algorithm']} {e['median_g']:.4f}" for e in cand if e is not best)]
    return AlgorithmChoice(alg, ALGORITHMS[alg], dec, "brkga+lahc", "default", reasons, cand, "evidence")


def sweep(stage: int, sliders: dict, stats: PartStats, slider: str, mode: str = "default", evidence=None) -> dict:
    values = list(range(0, 101))
    choices = []
    for v in values:
        s = dict(sliders)
        s[slider] = v
        choices.append(select_algorithm(stage, s, stats, mode, evidence).id)
    return {"slider": slider, "values": values, "choices": choices, "legend": dict(ALGORITHMS)}


def grid_map(stage: int, sliders: dict, stats: PartStats, x: str, y: str, n: int = 41, mode: str = "default",
             evidence=None) -> dict:
    vals = [round(100 * i / (n - 1), 4) for i in range(n)]
    grid = []
    for vy in vals:
        row = []
        for vx in vals:
            s = dict(sliders)
            s[x], s[y] = vx, vy
            row.append(select_algorithm(stage, s, stats, mode, evidence).id)
        grid.append(row)
    return {"x": x, "y": y, "n": n, "values": vals, "grid": grid, "legend": dict(ALGORITHMS)}
