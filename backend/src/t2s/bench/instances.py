"""Benchmark instances (protocol §J.3): the dataset, subsets, a perfect-packing generator with a known optimum.

All instances are built from part records; the generator writes binary STL boxes in memory and runs them through
the normal part pipeline, so no instance bypasses validation or mass properties.
"""
from __future__ import annotations

import copy
import io
from dataclasses import dataclass, field

import numpy as np

from ..geometry.stl_io import write_binary_stl
from ..parts.build import build_part


@dataclass
class Instance:
    id: str
    label: str
    stage: int
    records: dict                     # part_id -> PartRecord
    known_optimum_mm: float | None = None
    notes: list = field(default_factory=list)


def _box_stl(dims) -> bytes:
    x, y, z = dims
    v = np.array([[0, 0, 0], [x, 0, 0], [x, y, 0], [0, y, 0], [0, 0, z], [x, 0, z], [x, y, z], [0, y, z]], float)
    f = np.array([[0, 2, 1], [0, 3, 2], [4, 5, 6], [4, 6, 7], [0, 1, 5], [0, 5, 4],
                  [1, 2, 6], [1, 6, 5], [2, 3, 7], [2, 7, 6], [3, 0, 4], [3, 4, 7]])
    buf = io.BytesIO()
    write_binary_stl(buf, v, f)
    return buf.getvalue()


def perfect_packing(n_parts: int = 12, height: float = 200.0, seed: int = 5, gap: float = 0.02) -> Instance:
    """Guillotine-cut the 100 x 100 x height block into n boxes; the optimum used length is `height`
    (minus the cut allowance `gap`, which keeps the Stage 1 5 µm placement gap feasible)."""
    rng = np.random.default_rng(seed)
    blocks = [np.array([0.0, 0.0, 0.0, 100.0, 100.0, height])]
    while len(blocks) < n_parts:
        k = int(np.argmax([np.prod(b[3:] - b[:3]) for b in blocks]))
        b = blocks.pop(k)
        ext = b[3:] - b[:3]
        ax = int(rng.choice(3, p=ext / ext.sum()))
        cut = b[ax] + ext[ax] * rng.uniform(0.3, 0.7)
        lo, hi = b.copy(), b.copy()
        lo[3 + ax] = cut
        hi[ax] = cut
        blocks += [lo, hi]
    recs = {}
    for i, b in enumerate(blocks):
        dims = (b[3:] - b[:3]) - gap
        pid = f"box{i:02d}"
        recs[pid] = build_part(_box_stl(dims), pid, pid)
    return Instance("I5", f"perfect packing: {n_parts} boxes from a 100 x 100 x {height:.0f} mm block", 1, recs,
                    known_optimum_mm=float(height),
                    notes=[f"each box shrunk by {gap} mm so the 5 µm placement gaps fit; optimum ≤ {height:.0f} mm"])


def subset(records: dict, n: int, seed: int, ident: str) -> Instance:
    rng = np.random.default_rng(seed)
    ids = sorted(records)
    pick = sorted(rng.choice(len(ids), size=n, replace=False).tolist())
    sub = {ids[i]: records[ids[i]] for i in pick}
    return Instance(ident, f"{n}-part subset of the dataset (seed {seed})", 1, sub)


def dataset_instances(records: dict) -> list[Instance]:
    """records: the 19 packable dataset parts (part_id -> PartRecord)."""
    s2 = {}
    for pid, r in records.items():
        c = copy.copy(r)
        c.tags = ["pcb"] if "pcb" in r.name.lower() or "pcb" in r.tags else list(r.tags)
        s2[pid] = c
    return [Instance("I1", "all 19 parts, Stage 1", 1, records),
            Instance("I2", "all 19 parts, Stage 2 (default cable mode)", 2, s2),
            subset(records, 8, 11, "I3"),
            subset(records, 12, 12, "I4"),
            perfect_packing()]
