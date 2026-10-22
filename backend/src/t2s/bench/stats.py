"""Benchmark statistics (protocol §J.3): medians and IQR, paired Wilcoxon, Vargha–Delaney A12 with bootstrap CI,
Holm correction, Friedman test, hypervolume in one frozen normalised space."""
from __future__ import annotations

import numpy as np


def a12(x, y) -> float:
    """Probability that a value from x is better (lower) than one from y (ties count half)."""
    x, y = np.asarray(x, float), np.asarray(y, float)
    if len(x) == 0 or len(y) == 0:
        return float("nan")
    lt = (x[:, None] < y[None, :]).sum()
    eq = (x[:, None] == y[None, :]).sum()
    return float((lt + 0.5 * eq) / (len(x) * len(y)))


def a12_ci(x, y, n_boot: int = 1000, seed: int = 0) -> tuple[float, float]:
    rng = np.random.default_rng(seed)
    x, y = np.asarray(x, float), np.asarray(y, float)
    vals = [a12(rng.choice(x, len(x)), rng.choice(y, len(y))) for _ in range(n_boot)]
    return float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))


def wilcoxon_p(x, y) -> float:
    from scipy.stats import wilcoxon
    d = np.asarray(x, float) - np.asarray(y, float)
    if np.all(np.abs(d) < 1e-15):
        return 1.0
    try:
        return float(wilcoxon(x, y, zero_method="zsplit").pvalue)
    except ValueError:
        return 1.0


def holm(ps: list[float]) -> list[float]:
    m = len(ps)
    order = np.argsort(ps)
    out = np.empty(m)
    running = 0.0
    for rank, i in enumerate(order):
        adj = min(1.0, (m - rank) * ps[i])
        running = max(running, adj)
        out[i] = running
    return out.tolist()


def friedman(blocks: dict[str, dict[str, float]]) -> dict:
    """blocks: block id -> {variant: median score}; only variants present in every block."""
    from scipy.stats import friedmanchisquare, rankdata
    variants = sorted(set.intersection(*[set(b) for b in blocks.values()])) if blocks else []
    if len(variants) < 3 or len(blocks) < 2:
        return {"variants": variants, "stat": None, "p": None, "mean_ranks": {}}
    data = [[blocks[b][v] for b in blocks] for v in variants]
    stat, p = friedmanchisquare(*data)
    ranks = np.mean([rankdata([blocks[b][v] for v in variants]) for b in blocks], axis=0)
    return {"variants": variants, "stat": float(stat), "p": float(p),
            "mean_ranks": {v: float(r) for v, r in zip(variants, ranks)}}


def frozen_normaliser(raws: list[dict], keys=("L", "D", "T", "P")) -> dict:
    out = {}
    for k in keys:
        vals = np.array([r[k] for r in raws if r.get(k) is not None and np.isfinite(r[k])], float)
        if len(vals) == 0:
            continue
        lo, hi = (0.0 if k in ("D", "P") else float(vals.min())), float(vals.max())
        if hi - lo < 1e-12:
            hi = lo + max(1e-12, abs(lo) * 0.01 + 1e-9)
        out[k] = (lo, hi)
    return out


def norm_point(p, nz, keys=("L", "D", "T")):
    return [(p[i] - nz[k][0]) / (nz[k][1] - nz[k][0]) for i, k in enumerate(keys)]


def hypervolume(points: list, nz: dict, ref=(1.1, 1.1, 1.1)) -> float | None:
    if not points or any(k not in nz for k in ("L", "D", "T")):
        return None
    arr = np.array([norm_point(p, nz) for p in points], float)
    arr = arr[np.all(arr < np.asarray(ref), axis=1)]
    if len(arr) == 0:
        return 0.0
    import moocore
    return float(moocore.hypervolume(arr, ref=np.asarray(ref, float)))
