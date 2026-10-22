"""Search context: everything a worker needs to decode, score and validate layouts for one set of inputs.

A context is identified by the parts signature (ids, file hashes, units) and the constraint signature (stage,
locks, allowed orientations, tags, Stage 2 rules). Masses are not part of it: they only change the physics terms,
which are sent to the workers separately so a mass edit never rebuilds anything.
"""
from __future__ import annotations

import hashlib
import json
import pickle
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from ..collision.validate import StageSpec
from ..constraints import stage2 as s2
from ..decoders.box_decoder import PLACEMENT_GAP_STAGE1, BoxDecoder, ProxyPart
from ..objectives.metrics import ENCLOSURE_HI, ENCLOSURE_LO

QUANT_SLACK = 0.002     # mm: poses are published in integer µm, so Stage 2 gaps keep 2 µm of rounding slack


def packable(rec) -> bool:
    return rec is not None and rec.status in ("VALID", "REPAIRED", "WITHHELD")


def parts_signature(records: dict) -> str:
    items = sorted((pid, r.sha256, r.units) for pid, r in records.items() if packable(r))
    return hashlib.sha256(json.dumps(items).encode()).hexdigest()[:16]


def constraint_signature(records: dict, stage: int, extra: dict | None = None) -> str:
    items = []
    for pid, r in sorted(records.items()):
        if not packable(r):
            continue
        lp = r.lock_pose if r.locked else None
        items.append((pid, list(r.allowed_orients), sorted(r.tags) if stage == 2 else [], lp))
    return hashlib.sha256(json.dumps([stage, items, extra or {}], default=str).encode()).hexdigest()[:16]


def spec_signature(spec: StageSpec) -> str:
    """Hash of the validation rules (bounds, clearances, keep-outs): equal signatures accept the same layouts."""
    statics = sorted((s.name, s.kind, np.round(s.corners, 9).tolist()) for s in spec.statics)
    d = [spec.stage, np.round(spec.lo, 9).tolist(), np.round(spec.hi, 9).tolist(), spec.c_pp, spec.c_static, statics,
         sorted(map(list, spec.exempt))]
    return hashlib.sha256(json.dumps(d).encode()).hexdigest()[:16]


@dataclass
class SearchContext:
    ctx_id: str
    stage: int
    parts_sig: str
    constraint_sig: str
    spec_sig: str
    ids: list[str]
    proxies: list[ProxyPart]
    orient_bounds: dict
    dec_lo: np.ndarray
    dec_hi: np.ndarray
    gap_pp: float
    wall_gap: float
    obstacles: np.ndarray
    obstacle_gap: float
    fixed: list
    spec: StageSpec
    z0: float
    com_box: np.ndarray | None
    records: dict = field(default_factory=dict, repr=False)   # part_id -> PartRecord (for validation workers)

    def decoder(self) -> BoxDecoder:
        return BoxDecoder(self.proxies, self.dec_lo, self.dec_hi, self.gap_pp, self.wall_gap,
                          self.obstacles if len(self.obstacles) else None, self.obstacle_gap, self.fixed)


def stage2_config(records: dict) -> s2.Stage2Config:
    pcb = [pid for pid, r in records.items() if packable(r) and "pcb" in r.tags]
    return s2.Stage2Config(harness=True, harness_mode="interrupted", pcb_ids=pcb, stack_z=None)


def build_context(records: dict, stage: int) -> SearchContext:
    recs = {pid: r for pid, r in records.items() if packable(r)}
    ids = list(recs)
    proxies = [ProxyPart(pid, recs[pid].boxes, list(recs[pid].allowed_orients)) for pid in ids]
    fixed = []
    for pid in ids:
        r = recs[pid]
        if r.locked and r.lock_pose:
            fixed.append((pid, int(r.lock_pose["orient"]), np.asarray(r.lock_pose["t_um"], float) / 1000.0))
    if stage == 1:
        spec = StageSpec(1, ENCLOSURE_LO.copy(), ENCLOSURE_HI.copy(), 0.0, 0.0)
        dec = dict(dec_lo=ENCLOSURE_LO.copy(), dec_hi=ENCLOSURE_HI.copy(), gap_pp=PLACEMENT_GAP_STAGE1, wall_gap=0.0,
                   obstacles=np.zeros((0, 6)), obstacle_gap=0.0)
        com_box = None
    else:
        cfg = stage2_config(recs)
        spec = s2.stage2_spec(cfg)
        lo, hi = s2.inner_box()
        obs = np.array([np.concatenate([s.corners.min(0), s.corners.max(0)]) for s in spec.statics]).reshape(-1, 6)
        dec = dict(dec_lo=lo, dec_hi=hi, gap_pp=s2.C_PP + QUANT_SLACK, wall_gap=s2.C_WALL + QUANT_SLACK / 2,
                   obstacles=obs, obstacle_gap=s2.C_WALL + QUANT_SLACK)
        com_box = np.array([20.0, 20.0, 70.0])
    psig = parts_signature(recs)
    csig = constraint_signature(recs, stage)
    return SearchContext(ctx_id=f"{psig}-{csig}", stage=stage, parts_sig=psig, constraint_sig=csig,
                         spec_sig=spec_signature(spec), ids=ids,
                         proxies=proxies, orient_bounds={pid: recs[pid].orient_bounds for pid in ids}, fixed=fixed,
                         spec=spec, z0=float(ENCLOSURE_LO[2]), com_box=com_box, records=recs, **dec)


def write_context(ctx: SearchContext, folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"ctx_{ctx.ctx_id}.pkl"
    if not path.exists():
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(pickle.dumps(ctx, protocol=pickle.HIGHEST_PROTOCOL))
        tmp.replace(path)
    return path


def load_context(path: str | Path) -> SearchContext:
    return pickle.loads(Path(path).read_bytes())
