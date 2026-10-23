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


def parts_signature(records: dict, part_scale: float = 1.0) -> str:
    """Ids, file hashes and units; the V2 part-size factor too when it is not 1 (scaled parts are other parts)."""
    items = sorted((pid, r.sha256, r.units) for pid, r in records.items() if packable(r))
    key = items if part_scale == 1.0 else [items, round(float(part_scale), 6)]
    return hashlib.sha256(json.dumps(key).encode()).hexdigest()[:16]


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
    hm_meshes: dict = field(default_factory=dict, repr=False)  # part_id -> (v, f) chosen by the detail ladder
    levels: dict = field(default_factory=dict)                # part_id -> {algorithm: level} in use
    stage2_mode: str | None = None                            # default | soft | continuous (cable slider)
    part_scale: float = 1.0                                   # V2 part-size slider (Stage 2): records are scaled
    am_allowed: bool = True                                   # V2 bracket budget > 0: metal-AM brackets allowed

    def decoder(self):
        if self.stage == 2:
            return self.stage2_model()
        return BoxDecoder(self.proxies, self.dec_lo, self.dec_hi, self.gap_pp, self.wall_gap,
                          self.obstacles if len(self.obstacles) else None, self.obstacle_gap, self.fixed)

    def stage2_model(self):
        from ..constraints.stage2_model import Stage2Model
        if getattr(self, "_s2", None) is None:
            self._s2 = Stage2Model(self.records, self.stage2_mode or "default", self.fixed,
                                   am_allowed=getattr(self, "am_allowed", True))
        return self._s2

    def spec_for(self, meta: dict | None, relaxed: bool = False) -> StageSpec:
        """Validation rules for one layout (Stage 2 rules depend on the layout's stack height / corridor)."""
        if self.stage == 2:
            return self.stage2_model().spec(meta or {"mode": self.stage2_mode}, relaxed)
        return self.spec

    def __getstate__(self):
        d = dict(self.__dict__)
        d.pop("_s2", None)
        return d


def stage2_config(records: dict) -> s2.Stage2Config:
    pcb = [pid for pid, r in records.items() if packable(r) and "pcb" in r.tags]
    return s2.Stage2Config(harness=True, harness_mode="interrupted", pcb_ids=pcb, stack_z=None)


def build_context(records: dict, stage: int, reps: dict | None = None, stage2_mode: str = "default",
                  part_scale: float = 1.0, am_allowed: bool = True) -> SearchContext:
    """reps: part_id -> {algorithm id: Representation} from finished detail ladders (Addendum 4).
    stage2_mode: cable-slider mode for Stage 2 (default | soft | continuous).
    part_scale: V2 part-size factor, Stage 2 only (the detail-ladder proxies belong to the full-size parts, so they
    are not used for scaled parts).
    am_allowed: V2 bracket budget above 0 — metal-AM brackets may stand in where no simple bracket fits."""
    am_allowed = bool(am_allowed) if stage == 2 else True
    from ..parts.scale import scale_part
    part_scale = float(part_scale) if stage == 2 else 1.0
    recs = {pid: scale_part(r, part_scale) for pid, r in records.items() if packable(r)}
    ids = list(recs)
    reps = (reps or {}) if part_scale == 1.0 else {}
    levels = {pid: {"hybrid_box": "F1-6", "hybrid_heightmap": "F4-2"} for pid in ids}
    proxies = []
    for pid in ids:
        rb = reps.get(pid, {}).get("hybrid_box")
        boxes = rb.boxes if rb is not None and rb.boxes is not None else recs[pid].boxes
        if rb is not None and rb.boxes is not None:
            levels[pid]["hybrid_box"] = rb.level
        proxies.append(ProxyPart(pid, boxes, list(recs[pid].allowed_orients)))
    hm_meshes = {}
    for pid in ids:
        rh = reps.get(pid, {}).get("hybrid_heightmap")
        if rh is not None and rh.mesh is not None:
            hm_meshes[pid] = rh.mesh
            levels[pid]["hybrid_heightmap"] = rh.level
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
        # Stage 2 rules depend on each layout (stack height, corridor wall): see constraints/stage2_model.py
        lo, hi = s2.inner_box()
        spec = StageSpec(2, lo + s2.C_WALL, hi - s2.C_WALL, s2.C_PP, s2.C_WALL)
        dec = dict(dec_lo=lo, dec_hi=hi, gap_pp=s2.C_PP + QUANT_SLACK, wall_gap=s2.C_WALL + QUANT_SLACK / 2,
                   obstacles=np.zeros((0, 6)), obstacle_gap=s2.C_WALL + QUANT_SLACK)
        com_box = np.array([20.0, 20.0, 70.0])
    psig = parts_signature(recs, part_scale)
    csig = constraint_signature(recs, stage, {"stage2_mode": stage2_mode, "am_allowed": am_allowed}
                                if stage == 2 else None)
    lsig = hashlib.sha256(json.dumps(levels, sort_keys=True).encode()).hexdigest()[:8]
    if stage == 2:
        from ..constraints import stage2_model as s2m
        from ..mfg import rules as mr
        pcb = sorted(pid for pid in ids if "pcb" in recs[pid].tags)
        ssig = hashlib.sha256(json.dumps([2, stage2_mode, pcb, s2.WALL, s2.RAIL, s2.C_PP, s2.C_WALL, s2.HARNESS_W,
                                          s2.PCB_PITCH, s2m.PAD, s2m.STANDOFF_INSET, s2m.STANDOFF_SIDE,
                                          mr.BRACKET_MODEL_VERSION, mr.BRACKET_CLEARANCE, mr.MFG_REACH,
                                          am_allowed]).encode()).hexdigest()[:16]
    else:
        ssig = spec_signature(spec)
    return SearchContext(ctx_id=f"{psig}-{csig}-{lsig}", stage=stage, parts_sig=psig, constraint_sig=csig,
                         spec_sig=ssig, ids=ids,
                         proxies=proxies, orient_bounds={pid: recs[pid].orient_bounds for pid in ids}, fixed=fixed,
                         spec=spec, z0=float(ENCLOSURE_LO[2]), com_box=com_box, records=recs, hm_meshes=hm_meshes,
                         levels=levels, stage2_mode=stage2_mode if stage == 2 else None, part_scale=part_scale,
                         am_allowed=am_allowed, **dec)


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
