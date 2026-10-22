"""CP-SAT on the single-box proxy (protocol §F.8, variant V8).

Each part is its canonical bounding box in one of its distinct axis permutations; integer grid of 0.1 mm with
dimensions rounded UP (so every grid-feasible layout keeps the 5 µm Stage 1 gap for the true meshes); pairwise
six-literal relative-position disjunctions; minimise the used length.
Outputs: an upper-bound layout (valid for the true geometry because each box contains its part — re-validated by
the caller) and a lower bound valid for this single-box proxy problem only (never for the true shapes).
"""
from __future__ import annotations

import itertools
import time

import numpy as np


GRID = 0.1           # mm per integer unit
GAP = 0.005          # Stage 1 placement gap (mm)


def _orientations(rec):
    """Distinct axis-aligned extents with one representative orientation each (from the part's allowed set)."""
    seen = {}
    for o in rec.allowed_orients:
        b = rec.orient_bounds[o]
        ext = tuple(np.round(b[3:] - b[:3], 6))
        if ext not in seen:
            seen[ext] = o
    return [(np.array(e), o) for e, o in seen.items()]


def solve_box_proxy(records: dict, width=(100.0, 100.0), length_cap: float = 340.5, time_limit_s: float = 60.0,
                    workers: int = 8, seed: int = 0) -> dict:
    from ortools.sat.python import cp_model
    ids = list(records)
    m = cp_model.CpModel()
    W = [int(np.floor(w / GRID)) for w in width]
    Lcap = int(np.floor(length_cap / GRID))
    L = m.NewIntVar(0, Lcap, "L")
    X, Y, Z, WX, WY, WZ, ORI = {}, {}, {}, {}, {}, {}, {}
    for pid in ids:
        opts = _orientations(records[pid])
        lits = [m.NewBoolVar(f"o_{pid}_{k}") for k in range(len(opts))]
        m.AddExactlyOne(lits)
        d = [[int(np.ceil((e[a] + GAP) / GRID)) for a in range(3)] for e, _ in opts]
        for a, (store, cap) in enumerate(((WX, W[0]), (WY, W[1]), (WZ, Lcap))):
            v = m.NewIntVar(min(x[a] for x in d), max(x[a] for x in d), f"w{a}_{pid}")
            m.Add(v == sum(lit * x[a] for lit, x in zip(lits, d)))
            store[pid] = v
        X[pid] = m.NewIntVar(0, W[0], f"x_{pid}")
        Y[pid] = m.NewIntVar(0, W[1], f"y_{pid}")
        Z[pid] = m.NewIntVar(0, Lcap, f"z_{pid}")
        m.Add(X[pid] + WX[pid] <= W[0])
        m.Add(Y[pid] + WY[pid] <= W[1])
        m.Add(Z[pid] + WZ[pid] <= L)
        ORI[pid] = (lits, opts)
    for i, j in itertools.combinations(ids, 2):
        b = [m.NewBoolVar(f"s_{i}_{j}_{k}") for k in range(6)]
        m.Add(X[i] + WX[i] <= X[j]).OnlyEnforceIf(b[0])
        m.Add(X[j] + WX[j] <= X[i]).OnlyEnforceIf(b[1])
        m.Add(Y[i] + WY[i] <= Y[j]).OnlyEnforceIf(b[2])
        m.Add(Y[j] + WY[j] <= Y[i]).OnlyEnforceIf(b[3])
        m.Add(Z[i] + WZ[i] <= Z[j]).OnlyEnforceIf(b[4])
        m.Add(Z[j] + WZ[j] <= Z[i]).OnlyEnforceIf(b[5])
        m.AddBoolOr(b)
    # redundant: total box volume per unit length cannot exceed the cross-section
    m.Minimize(L)
    s = cp_model.CpSolver()
    s.parameters.max_time_in_seconds = float(time_limit_s)
    s.parameters.num_search_workers = int(workers)
    s.parameters.random_seed = int(seed)
    t0 = time.perf_counter()
    st = s.Solve(m)
    out = {"status": s.StatusName(st), "seconds": time.perf_counter() - t0, "grid_mm": GRID,
           "lower_bound_mm": float(s.BestObjectiveBound()) * GRID if st in (cp_model.OPTIMAL, cp_model.FEASIBLE) else None,
           "valid_for": "single-box proxy problem only (not the true shapes)", "poses": None, "length_mm": None}
    if st in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        poses = []
        lo = np.array([-width[0] / 2, -width[1] / 2, -length_cap / 2])
        for pid in ids:
            lits, opts = ORI[pid]
            k = next(k for k, lit in enumerate(lits) if s.Value(lit))
            ext, o = opts[k]
            b = records[pid].orient_bounds[o]
            corner = np.array([s.Value(X[pid]), s.Value(Y[pid]), s.Value(Z[pid])], float) * GRID + lo
            t = corner - b[:3] + GAP / 2
            poses.append((pid, int(o), np.round(t * 1000.0) / 1000.0))
        out["poses"] = poses
        out["length_mm"] = float(s.Value(L)) * GRID
        out["optimal"] = st == cp_model.OPTIMAL
    return out


def cpsat_job(records_path: str, time_limit_s: float = 60.0, workers: int = 2, seed: int = 0) -> dict:
    """Process-pool entry point for the live service (poses as plain lists)."""
    import pickle
    from pathlib import Path
    records = pickle.loads(Path(records_path).read_bytes())
    r = solve_box_proxy(records, time_limit_s=time_limit_s, workers=workers, seed=seed)
    if r["poses"]:
        r["poses"] = [(p, int(o), np.asarray(t, float).tolist()) for p, o, t in r["poses"]]
    return r
