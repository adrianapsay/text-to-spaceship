"""Stage 2 search model (protocol §O.2, §F.2; Addendum 1.4 cable slider; Addendum 2.3 mountable edge boards).

All dimensions ASSUMED unless the CDS gives them (see stage2.py). The model wraps the certified box decoder:

* **Frame:** 2 mm walls, four 8.5 mm corner rails; parts keep 2.2 mm from each other and 1.2 mm from rails and
  keep-outs. Wall-facing sides keep 3.0 mm, so the 3 mm mounting layer of U6 fits on any wall-facing side
  (a conservative simplification of "3 mm on an optimiser-chosen face, replacing the 1.2 mm clearance there").
* **PC/104 stack** (cable slider < 70): PCB-tagged parts lie flat, centred on the enclosure axis, 15.24 mm apart.
  The stack's height along the enclosure is a search variable (an extra random key). The volume between boards is
  reserved for board components (ASSUMED), so nothing else is placed there. Rods (keep-outs) span the stack only.
* **Harness** (U5): slider 0 → a 10 mm channel on the +X wall between the rails, a hard keep-out except across the
  stack (wiring there uses the PC/104 bus, ASSUMED). Slider 1–69 → no keep-out; H = blocked fraction of the full
  +X corridor is a weighted objective. Slider ≥ 70 → continuous-cable mode: the corridor is a hard full-length
  keep-out on a wall chosen by the search (extra key), and boards stand on edge on four M3 standoffs
  (Addendum 2.3 option b; card guides are not implemented). A board whose standoffs do not reach a wall is not
  mounted, and the layout is infeasible — boards are never left floating.
* **Brackets (V2):** every other part is held by a bracket from its mounting side (the side with the 3 mm layer) to
  a wall, end plate, corner rail or the stack deck up to 40 mm away. The bracket owns a reserved box from the target
  to the part side (reaching into the part's bounding box where it wraps the part); the box keeps 1.2 mm from every
  other part, bracket and keep-out except its target, so brackets are part of the packing and of the proof. The
  cheapest bracket that fits is used (direct, machined block, sheet Z-bracket, tube clamp, machined cradle); with a
  bracket budget above 0 a metal-AM bracket stands in where no simple one fits. A part with no bracket is unmounted.
* **COM-centring shift:** the decoder packs from the −Z end plate, so a short layout has its centre of mass far
  below the middle. After decoding, the whole layout (stack, rods, harness breaks and reserved block included) moves
  along Z: at least far enough to bring the COM inside the CDS box (|z| ≤ 70 mm), and further toward the envelope
  centre as a third extra key asks (a search variable: more centring costs used length). The end plates limit the
  shift, and a shift that would lose a mount (e.g. a part fixed to the −Z end plate) is not taken.

Layout-specific geometry (stack height, corridor wall, standoffs) travels with each candidate in `meta`, so the
validator rebuilds exactly the rules the layout was decoded under.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..collision.validate import StageSpec, StaticItem
from ..core.rotations import ROTATIONS_F
from ..decoders.box_decoder import BoxDecoder, DecodeResult, ProxyPart
from ..parts.build import orient_equivalence
from . import stage2 as s2

SLACK = 0.002                  # integer-µm rounding allowance kept on every Stage 2 gap
WALL_MOUNT_GAP = s2.MOUNT_LAYER  # wall-facing sides keep room for the 3 mm mounting layer
STANDOFF_SIDE = 5.0            # ASSUMED M3 standoff envelope (square section, mm)
STANDOFF_LEN = 3.0             # shortest standoff (Addendum 2.3: 3–50 mm); it is lengthened to reach the wall
STANDOFF_MAX = 50.0
STANDOFF_INSET = 8.5           # ASSUMED distance of the standoff centre from the board corner (clear of the rails)
STANDOFF_MASS_DENSITY = 2700.0  # aluminium (ASSUMED)
WALLS = ("+x", "-x", "+y", "-y")


def _box(lo, hi) -> np.ndarray:
    return np.concatenate([np.asarray(lo, float), np.asarray(hi, float)])


OVERFLOW = 400.0               # the decoder may stack parts this far beyond the end plate; overflow is a violation
HARNESS_BREAK = s2.C_WALL + 0.01   # harness interruption beyond the stack ends (1.2 mm clearance + rounding allowance)
COM_BOX_Z = 70.0               # CDS Rev 14.1 COM box half-height (mm, "shall")
COM_SHIFT_MARGIN = 0.5         # the minimal shift puts the COM this far inside the box edge (rounding, standoff mass)


def corridor_box(wall: str, z_hi: float | None = None) -> np.ndarray:
    """10 mm channel along `wall`, between the rails, full inner length (or up to z_hi)."""
    lo, hi = s2.inner_box()
    if z_hi is not None:
        hi = hi.copy()
        hi[2] = z_hi
    r = s2.ENVELOPE[:2] / 2 - s2.RAIL
    ax = 0 if wall[1] == "x" else 1
    other = 1 - ax
    blo, bhi = lo.copy(), hi.copy()
    if wall[0] == "+":
        blo[ax] = hi[ax] - s2.HARNESS_W
    else:
        bhi[ax] = lo[ax] + s2.HARNESS_W
    blo[other], bhi[other] = -r[other], r[other]
    return _box(blo, bhi)


def rail_boxes() -> list[np.ndarray]:
    return [np.concatenate([r.corners.min(0), r.corners.max(0)]) for r in s2.rails()]


def flat_orient(rec) -> int | None:
    """An allowed orientation that puts the board's thinnest extent along Z."""
    best = None
    for o in rec.allowed_orients:
        b = rec.orient_bounds[o]
        ext = b[3:] - b[:3]
        if ext[2] <= ext.min() + 1e-6:
            if best is None:
                best = o
    return best


def board_macro(rec):
    """Board compound boxes + four standoffs on the board's -a face (a = thinnest canonical axis)."""
    v = rec.v
    lo, hi = v.min(0), v.max(0)
    a = int(np.argmin(hi - lo))
    b, c = [k for k in range(3) if k != a]
    boxes = [np.asarray(x, float) for x in rec.boxes]
    stand = []
    h = STANDOFF_SIDE / 2
    for sb in (lo[b] + STANDOFF_INSET, hi[b] - STANDOFF_INSET):
        for sc in (lo[c] + STANDOFF_INSET, hi[c] - STANDOFF_INSET):
            blo, bhi = np.zeros(3), np.zeros(3)
            blo[a], bhi[a] = lo[a] - STANDOFF_LEN, lo[a]
            blo[b], bhi[b] = sb - h, sb + h
            blo[c], bhi[c] = sc - h, sc + h
            stand.append(_box(blo, bhi))
    return np.array(boxes + stand), np.array(stand), a


PAD = s2.MOUNT_LAYER - s2.C_WALL        # 1.8 mm reserved beyond the 1.2 mm clearance = the 3 mm mounting layer


def planar_face_areas(rec) -> dict:
    """Planar contact area (mm²) on each of the six canonical bounding-box faces: triangles lying in the face plane
    with the outward normal. Keys (axis, sign), sign -1 = the low face."""
    v, f = rec.v, rec.f
    lo, hi = v.min(0), v.max(0)
    tri = v[f]
    n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    a2 = np.linalg.norm(n, axis=1)
    ok = a2 > 0
    nn = np.zeros_like(n)
    nn[ok] = n[ok] / a2[ok, None]
    cen = tri.mean(axis=1)
    out = {}
    for a in range(3):
        for sgn, plane in ((-1, lo[a]), (1, hi[a])):
            sel = (np.abs(cen[:, a] - plane) < 0.25) & (nn[:, a] * sgn > 0.99)
            out[(a, sgn)] = float(0.5 * a2[sel].sum())
    return out


def pad_box(rec):
    """Mounting-layer reservation (U6) on the bounding-box face with the most planar contact area (ties: the
    larger face). Returns (box, axis, sign)."""
    lo, hi = rec.v.min(0), rec.v.max(0)
    ext = hi - lo
    areas = planar_face_areas(rec)
    rect = {(a, s): ext[[k for k in range(3) if k != a]].prod() for a in range(3) for s in (-1, 1)}
    a, sgn = max(areas, key=lambda k: (round(areas[k], 3), rect[k], -k[0], -k[1]))
    blo, bhi = lo.copy(), hi.copy()
    if sgn < 0:
        bhi[a], blo[a] = lo[a], lo[a] - PAD
    else:
        blo[a], bhi[a] = hi[a], hi[a] + PAD
    return _box(blo, bhi), a, sgn


@dataclass
class Stage2Config:
    mode: str                  # default | soft | continuous
    pcb_ids: list
    threshold: float = 70.0


def mode_for(cable: float, threshold: float = 70.0) -> str:
    return "continuous" if cable >= threshold else ("soft" if cable > 0 else "default")


class Stage2Model:
    """Decoder + rule builder for one parts set and one mode. Chromosome: 3n keys + 3 extra keys
    (stack height, corridor wall, COM centring)."""

    n_extra = 3
    EXTRA_DEFAULT = (0.5, 0.5, 0.0)      # keys missing from a short chromosome (older keys, constructive passes)

    RELAXABLE = ("clearances", "frame", "pcb_stack", "harness", "mounting", "com_box")

    def __init__(self, records: dict, mode: str, fixed: list | None = None, relax=frozenset(), mfg: bool = False,
                 am_allowed: bool = True):
        """relax: constraint families switched off (constraint attribution, protocol §O.3 — never used for the
        layouts the app reports as Stage 2 results). mfg: V1 Manufacturable Design tab — brackets may bridge up to
        MFG_REACH and are synthesised after the search. Otherwise (V2 Stage 2) every part except the boards is held
        by a modelled bracket whose reserved box is part of the packing; am_allowed (bracket budget > 0) lets a
        metal-AM bracket stand in where no simple bracket fits. The relative hardware cost C is an objective."""
        self.mfg = bool(mfg)
        self.am_allowed = bool(am_allowed)
        self.profiles: dict = {}
        self.records = records
        self.ids = list(records)
        self.n = len(self.ids)
        self.dim = 3 * self.n + self.n_extra
        self.mode = mode
        self.relax = frozenset(relax)
        self.pcb = [] if "pcb_stack" in self.relax else [pid for pid in self.ids if "pcb" in records[pid].tags]
        self.optional = frozenset(pid for pid in self.ids if "optional" in (records[pid].tags or []))
        lo, hi = s2.inner_box()
        if "frame" in self.relax:                      # no walls, no rails: the bare 100 × 100 × 340.5 envelope
            lo, hi = -s2.ENVELOPE / 2, s2.ENVELOPE / 2
        self.inner = (lo, hi)
        self.dec_hi = hi + np.array([0.0, 0.0, OVERFLOW])   # decoder container: open beyond the end plate
        self.wall_gap = s2.C_WALL + SLACK               # every side keeps the 1.2 mm wall clearance …
        self.gap_pp = s2.C_PP + SLACK
        self.obs_gap = s2.C_WALL + SLACK
        if "clearances" in self.relax:                 # Stage 1 contact policy instead of 2.2 / 1.2 mm
            self.gap_pp = 0.005 + SLACK
            self.obs_gap = SLACK
            self.wall_gap = self.gap_pp / 2
        # the box decoder inflates part boxes by half the part gap on every side, walls included
        self.dec_wall_gap = self.wall_gap - self.gap_pp / 2
        self.board_wall_gap = self.wall_gap
        self.flat = {pid: flat_orient(records[pid]) for pid in self.pcb}
        self.stack_ok = self.mode != "continuous" and all(o is not None for o in self.flat.values())
        proxies = []
        self.macro = {}
        self.pads = {}
        self.equiv = {}
        for pid in self.ids:
            r = records[pid]
            allowed = list(r.allowed_orients)
            boxes = r.boxes
            if pid in self.pcb and self.mode == "continuous":
                mb, stand, a = board_macro(r)
                # edge-on: the board's thin axis (and so the standoffs) must point along X or Y
                edge = [o for o in range(24) if abs(ROTATIONS_F[o][2, a]) < 0.5]
                self.macro[pid] = {"stand": stand, "axis": a}
                boxes, allowed = mb, edge
            elif pid not in self.pcb and "mounting" not in self.relax:
                # … and the mounting side gets the 3 mm layer (U6): a 1.8 mm pad reserved on the part's largest
                # face, pointed by the part's orientation (any of 24), so that side ends up 3.0 mm from its target
                pad, a, sgn = pad_box(r)
                self.pads[pid] = (pad, a, sgn)
                boxes = np.vstack([r.boxes, pad[None]])
                # with the pad, orientations that are equivalent for the bare part differ: offer every orientation
                # whose bare-part representative is allowed, and report poses with the representative
                allowed = [o for o in range(24) if self._rep(pid, o) in r.allowed_orients]
            proxies.append(ProxyPart(pid, boxes, allowed))
        self.proxies = proxies
        self.parts = {p.id: p for p in proxies}
        self.allowed = {p.id: list(p.allowed) for p in proxies}
        self.decoders = {}
        self.fixed = [f for f in (fixed or []) if f[0] not in self.pcb or self.mode == "continuous"]
        self._statics_rails = [] if "frame" in self.relax else \
            [np.concatenate([b[:3], [b[3], b[4], self.dec_hi[2]]]) for b in rail_boxes()]
        self.harness_on = "harness" not in self.relax
        self.com_shift_on = "com_box" not in self.relax and not self.fixed
        self._phys_cache: dict = {}

    def _rep(self, pid: str, o: int) -> int:
        if pid not in self.equiv:
            r = self.records[pid]
            self.equiv[pid] = getattr(r, "_orient_equiv", None) or orient_equivalence(r.v)
            try:
                r._orient_equiv = self.equiv[pid]
            except Exception:  # noqa: BLE001
                pass
        return int(self.equiv[pid][o])

    # ------------------------------------------------------------------------------------------ geometry
    def _decoder(self, key: str, obstacles: list[np.ndarray]) -> BoxDecoder:
        if key not in self.decoders:
            lo, hi = self.inner[0], self.dec_hi
            pwg = {pid: self.board_wall_gap - self.gap_pp / 2 for pid in self.macro}
            self.decoders[key] = BoxDecoder(self.proxies, lo, hi, self.gap_pp, self.dec_wall_gap,
                                            np.array(obstacles).reshape(-1, 6), self.obs_gap, self.fixed,
                                            part_wall_gap=pwg, mixed_candidates=True)
        return self.decoders[key]

    def stack_layout(self, key_z: float):
        """Board poses, the reserved stack block and its z-span for a stack-height key in [0, 1)."""
        lo, hi = self.inner
        poses, boxes = [], []
        thick = []
        for pid in self.pcb:
            b = self.records[pid].orient_bounds[self.flat[pid]]
            thick.append(b[5] - b[2])
        span = (len(self.pcb) - 1) * s2.PCB_PITCH + (thick[-1] if thick else 0.0)
        zmin = lo[2] + self.wall_gap
        zmax = hi[2] - self.wall_gap - span
        if zmax < zmin:
            return None
        z0 = zmin + float(key_z) * (zmax - zmin)
        z0 = np.ceil(z0 * 1000.0) / 1000.0
        for k, pid in enumerate(self.pcb):
            o = self.flat[pid]
            b = self.records[pid].orient_bounds[o]
            c = 0.5 * (b[:3] + b[3:])
            t = np.array([-c[0], -c[1], z0 + k * s2.PCB_PITCH - b[2]])
            t = np.round(t * 1000.0) / 1000.0
            poses.append((pid, o, t))
            boxes.append(np.concatenate([b[:3] + t, b[3:] + t]))
        bb = np.array(boxes)
        block = np.concatenate([bb[:, :3].min(0), bb[:, 3:].max(0)])
        return poses, block, (float(block[2]), float(block[5]))

    def statics(self, meta: dict, relaxed: bool = False) -> list[StaticItem]:
        """Keep-outs a layout was decoded under (for validation and display). relaxed: extended beyond the end
        plate, to certify an overflowing (infeasible) candidate everywhere else."""
        lo, hi = self.inner[0], (self.dec_hi if relaxed else self.inner[1])
        out = [] if "frame" in self.relax else \
            [StaticItem(r.name, s2.box_corners(r.corners.min(0), np.concatenate([r.corners.max(0)[:2], [hi[2]]])), "rail")
             for r in s2.rails()]
        if meta.get("mode") == "continuous" and meta.get("corridor"):
            cb = corridor_box(meta["corridor"], hi[2])
            out.append(StaticItem(f"corridor{meta['corridor']}", s2.box_corners(cb[:3], cb[3:]), "harness"))
            for k, (pid, b) in enumerate(meta.get("standoffs", [])):
                out.append(StaticItem(f"standoff{k}:{pid}", s2.box_corners(b[:3], b[3:]), "standoff"))
        else:
            span = meta.get("stack_span")
            if meta.get("mode") == "default" and self.harness_on:
                cb = corridor_box("+x")
                segs = [(lo[2], hi[2])] if span is None else [(lo[2], span[0] - HARNESS_BREAK),
                                                               (span[1] + HARNESS_BREAK, hi[2])]
                for i, (a, b) in enumerate(segs):
                    if b - a > 1e-6:
                        out.append(StaticItem(f"harness{i}", s2.box_corners([cb[0], cb[1], a], [cb[3], cb[4], b]),
                                              "harness"))
            if span is not None and self.pcb:
                h = s2.ROD_D / 2
                for sx in (1, -1):
                    for sy in (1, -1):
                        out.append(StaticItem(f"rod{'+' if sx > 0 else '-'}{'+' if sy > 0 else '-'}",
                                              s2.box_corners([sx * s2.ROD_XY - h, sy * s2.ROD_XY - h, span[0]],
                                                             [sx * s2.ROD_XY + h, sy * s2.ROD_XY + h, span[1]]), "rod"))
                blk = meta["stack_block"]
                out.append(StaticItem("stack_reserve", s2.box_corners(blk[:3], blk[3:]), "stack"))
        for b in meta.get("brackets", []):          # V2: every bracket's reserved box is a keep-out for the others
            r = np.asarray(b["reserve"], float)
            out.append(StaticItem(b["name"], s2.box_corners(r[:3], r[3:]), "bracket"))
        return out

    def spec(self, meta: dict, relaxed: bool = False) -> StageSpec:
        """Validation rules of one layout. V2 brackets: parts keep 1.2 mm from every reserved box except their own
        (and the boards from one landing on the stack deck); `static_pairs` keep the boxes 1.2 mm from each other and
        from every keep-out except their target (box arithmetic)."""
        from ..mfg.rules import BRACKET_CLEARANCE
        lo, hi = self.inner[0], (self.dec_hi if relaxed else self.inner[1])
        st = self.statics(meta, relaxed)
        exempt = set()
        for s in st:
            if s.kind in ("rod", "stack"):
                exempt |= {(pid, s.name) for pid in self.pcb}
            if s.kind == "standoff":
                exempt.add((s.name.split(":", 1)[1], s.name))
        pairs = []
        brs = meta.get("brackets", [])
        names = [s.name for s in st if s.kind != "bracket"]
        for i, b in enumerate(brs):
            exempt.add((b["pid"], b["name"]))
            exempt |= {(p, b["name"]) for p in b.get("target_parts", [])}
            pairs += [(b["name"], n, BRACKET_CLEARANCE) for n in names if n not in b.get("target_statics", [])]
            pairs += [(b["name"], o["name"], BRACKET_CLEARANCE) for o in brs[i + 1:]]
        return StageSpec(2, lo + s2.C_WALL, hi - s2.C_WALL, s2.C_PP, s2.C_WALL, st, exempt, pairs)

    def feasible(self, meta: dict) -> bool:
        """Engineering feasibility beyond geometry (validated separately): inside the enclosure, every part
        mounted. The COM box and insertion order are checked by the caller."""
        return meta.get("overflow_mm", 0.0) <= 0.0 and not meta.get("unmounted")

    # ------------------------------------------------------------------------------------------ decoding
    def decode(self, order, orient_keys, rule_keys) -> DecodeResult:
        rule_keys = np.asarray(rule_keys, float)
        extra = np.array(self.EXTRA_DEFAULT, float)
        given = rule_keys[self.n:self.n + self.n_extra]
        extra[:len(given)] = given
        rk = rule_keys[:self.n]
        meta = {"mode": self.mode}
        pre_poses, skip = [], set()
        idx = {pid: i for i, pid in enumerate(self.ids)}
        ztop = self.dec_hi[2]
        if self.mode == "continuous":
            wall = WALLS[min(int(extra[1] * 4), 3)]
            if self.harness_on:
                meta["corridor"] = wall
            dec = self._decoder(wall, self._statics_rails + ([corridor_box(wall, ztop)] if self.harness_on else []))
            res = dec.decode(order, orient_keys, rk)
        else:
            obstacles = self._statics_rails + ([corridor_box("+x", ztop)]
                                               if self.mode == "default" and self.harness_on else [])
            stack = self.stack_layout(extra[0]) if self.stack_ok and self.pcb else None
            if self.pcb and stack is None:
                return DecodeResult([], np.zeros((0, 6)), list(self.ids), 0.0)
            if stack is None:
                dec = self._decoder(self.mode, obstacles)
                res = dec.decode(order, orient_keys, rk)
            else:
                poses, block, span = stack
                meta.update(stack_z=span[0], stack_span=span, stack_block=block.tolist(), stack_ids=list(self.pcb))
                # harness interrupted across the stack span (default mode)
                obs = list(self._statics_rails)
                if self.mode == "default" and self.harness_on:
                    cb = corridor_box("+x")
                    lo, hi = self.inner
                    for a, b in ((lo[2], span[0] - HARNESS_BREAK), (span[1] + HARNESS_BREAK, ztop)):
                        if b - a > 1e-6:
                            obs.append(np.array([cb[0], cb[1], a, cb[3], cb[4], b]))
                dec = self._decoder(f"{self.mode}-stack", self._statics_rails)
                extra_obs = dec.inflate_obstacles(np.array(obs[len(self._statics_rails):]).reshape(-1, 6), self.obs_gap)
                extra_obs = np.vstack([extra_obs.reshape(-1, 6), self._stack_obstacle(dec, block)[None]])
                skip = {idx[p] for p in self.pcb}
                res = dec.decode(order, orient_keys, rk, extra_obstacles=extra_obs, skip=skip)
                pre_poses = poses
        poses = pre_poses + [(pid, int(o), np.round(np.asarray(t, float) * 1000.0) / 1000.0) for pid, o, t in res.poses]
        dropped = []
        if self.optional:          # V2: an optional part that would overflow the end plate is left out
            limit = self.inner[1][2] - s2.C_WALL
            over = [pid for pid, o, t in poses if pid in self.optional and pid not in self.pcb
                    and t[2] + self.records[pid].orient_bounds[o][5] > limit + 1e-9]
            dropped += over
            poses = [p for p in poses if p[0] not in over]
        partial = any(p not in self.optional for p in res.unplaced)
        shift, poses, meta, (penalty, mounts, extras) = self._com_shift(poses, meta, extra[2], partial)
        placed_boxes, length_top = res.placed_boxes, res.length_top
        if shift:
            placed_boxes = np.asarray(placed_boxes, float).copy()
            if placed_boxes.size:
                placed_boxes[:, [2, 5]] += shift
            length_top = length_top + shift
        if self.optional:          # … and so is one that no bracket / standoff can hold
            gone = [p for p, v in mounts.items() if not v["ok"] and p in self.optional]
            for p in gone:
                mounts.pop(p)
            penalty -= len(gone)
            poses = [p for p in poses if p[0] not in gone]
            dropped += gone
        meta["dropped"] = dropped
        meta["mounts"] = mounts
        meta["unmounted"] = [p for p, v in mounts.items() if not v["ok"]]
        top = max((t[2] + self.records[pid].orient_bounds[o][5] for pid, o, t in poses), default=self.inner[0][2])
        meta["overflow_mm"] = float(max(0.0, top - (self.inner[1][2] - s2.C_WALL)))
        penalty += meta["overflow_mm"] / 10.0
        if self.mode == "continuous":
            meta["standoffs"] = extras
        if self.mode == "soft":
            meta["H"] = self.blocked_fraction(poses, meta)
        hardware = self.standoff_mass(extras)
        if not self.mfg:
            meta["brackets"] = self.brackets(mounts)
            hardware += [(b["mass_kg"], np.asarray(b["com_mm"]), np.asarray(b["inertia_kgm2"])) for b in meta["brackets"]]
        from ..mfg.rules import COST
        c = sum(v.get("cost_est", 0.0) for v in mounts.values() if v.get("ok"))
        c += len(meta.get("standoffs", [])) * (COST["catalogue"] + 2 * COST["fastener"])
        c += len(self.pcb) * (COST["catalogue"] + 4 * COST["fastener"]) if meta.get("stack_block") else 0.0
        meta["C"] = float(c)
        # the pad was only a reservation: report each part with its bare-part representative orientation
        meta["pad_orients"] = {pid: int(o) for pid, o, _ in poses if pid in self.pads or pid in self.macro}
        poses = [(pid, self._rep(pid, o) if (pid in self.pads or pid in self.macro) else o, t) for pid, o, t in poses]
        out = DecodeResult(poses, placed_boxes, res.unplaced, length_top)
        out.meta = meta
        out.penalty = float(penalty)
        out.raw_extra = {k: meta[k] for k in ("H", "C") if k in meta}
        out.extra_mass = hardware
        return out

    @staticmethod
    def brackets(mounts: dict) -> list[dict]:
        """V2 Stage 2 bracket list (reserved box, target, mass properties, cost) from the mount check."""
        from ..mfg.brackets import v2_bracket
        out = []
        for pid, v in mounts.items():
            if not v.get("ok") or "reserve" not in v:
                continue
            br = v2_bracket(f"bracket:{pid}", pid, v)
            out.append({"name": f"bracket:{pid}", "pid": pid, **{k: v[k] for k in (
                "kind", "mount_type", "process", "fasteners", "gap_mm", "target", "target_statics", "target_parts",
                "reserve", "axis", "neg", "part_side_mm", "plane_mm", "depth_mm")},
                "mass_kg": br.mass_kg, "com_mm": np.asarray(br.com_mm).tolist(),
                "inertia_kgm2": np.asarray(br.inertia_kgm2).tolist(), "cost_rel": br.cost_rel,
                "material": br.material, "label": br.label, "exact": not br.estimate})
        return out

    def best_fit_all_orientations(self, order, rule: float = 0.0) -> DecodeResult:
        """Constructive baseline: stack at mid-height (key 0.5), corridor wall key 0.5, all orientations tried."""
        n = self.n
        if self.mode == "continuous":
            wall = WALLS[2]
            dec = self._decoder(wall, self._statics_rails + [corridor_box(wall, self.dec_hi[2])])
            res = dec.best_fit_all_orientations(order, rule)
            meta = {"mode": self.mode, "corridor": wall}
            poses = [(p, int(o), np.round(np.asarray(t) * 1000) / 1000) for p, o, t in res.poses]
            okeys = np.zeros(n)
            o_of = {p: o for p, o, _ in poses}
            for i, pid in enumerate(self.ids):
                if pid in o_of and o_of[pid] in self.allowed[pid]:
                    okeys[i] = (self.allowed[pid].index(o_of[pid]) + 0.5) / len(self.allowed[pid])
            rk = np.concatenate([np.full(n, rule), [0.5, 0.5, 0.0]])
            out = self.decode(order, okeys, rk)
            out.keys_hint = (okeys, rk)
            return out
        # flat stack: orientations of the free parts from a best-fit pass, then a normal decode
        rk = np.concatenate([np.full(n, rule), [0.0, 0.5, 0.0]])     # minimal COM shift: the baseline stays short
        best = None
        for kz in (0.0, 1.0, 0.5):
            rk[n] = kz
            probe = self._best_fit_orients(order, rule, kz)
            r = self.decode(order, probe, rk.copy())
            if best is None or (len(r.unplaced), r.penalty, r.length_top) < (len(best.unplaced), best.penalty, best.length_top):
                best = r
                best.keys_hint = (probe.copy(), rk.copy())
        return best

    def _best_fit_orients(self, order, rule, kz) -> np.ndarray:
        n = self.n
        stack = self.stack_layout(kz) if self.stack_ok and self.pcb else None
        okeys = np.full(n, 0.5)
        if stack is None:
            return okeys
        poses, block, span = stack
        dec = self._decoder(f"{self.mode}-stack", self._statics_rails)
        obs = [self._stack_obstacle(dec, block)]
        if self.mode == "default" and self.harness_on:
            cb = corridor_box("+x")
            lo, hi = self.inner
            for a, b in ((lo[2], span[0] - HARNESS_BREAK), (span[1] + HARNESS_BREAK, self.dec_hi[2])):
                if b - a > 1e-6:
                    obs += list(dec.inflate_obstacles(np.array([cb[0], cb[1], a, cb[3], cb[4], b]), self.obs_gap))
        idx = {pid: i for i, pid in enumerate(self.ids)}
        res = dec.best_fit_all_orientations(order, rule, extra_obstacles=np.array(obs), skip={idx[p] for p in self.pcb})
        for pid, o, _ in res.poses:
            i = idx[pid]
            okeys[i] = (self.allowed[pid].index(o) + 0.5) / len(self.allowed[pid])
        return okeys

    def _stack_obstacle(self, dec: BoxDecoder, block) -> np.ndarray:
        """The stack block grown so that part boxes keep the part-part gap from it on every side."""
        g = max(self.gap_pp - dec.half, 0.0)
        return np.array([block[0] - g, block[1] - g, block[2] - g, block[3] + g, block[4] + g, block[5] + g])

    # ------------------------------------------------------------------------------------------ COM centring
    def _phys(self, pid):
        """Mass properties of a part (cached; recomputed when its mass or density changes)."""
        from ..objectives.metrics import part_phys
        r = self.records[pid]
        key = (r.mass_kg, r.density_kg_m3)
        hit = self._phys_cache.get(pid)
        if hit is None or hit[0] != key:
            hit = self._phys_cache[pid] = (key, part_phys(r))
        return hit[1]

    def _com_z(self, poses) -> float | None:
        """COM height of the parts (the CDS box check uses the parts only, decision U7); None if a mass is withheld."""
        m = mz = 0.0
        for pid, o, t in poses:
            p = self._phys(pid)
            if p is None:
                return None
            m += p.mass_kg
            mz += p.mass_kg * float(ROTATIONS_F[o][2] @ p.com_can_mm + t[2])
        return mz / m if m > 0 else None

    def _z_room(self, poses) -> tuple[float, float]:
        """How far the whole layout may move down / up: proxy boxes (mounting pads included) keep the wall clearance
        from both end plates, and the bare parts stay below the overflow limit."""
        lo, hi = self.inner
        bottom, top, bare_top = np.inf, -np.inf, -np.inf
        for pid, o, t in poses:
            ob = self.parts[pid].oriented(o)
            bottom = min(bottom, float(ob[:, 2].min() + t[2]))
            top = max(top, float(ob[:, 5].max() + t[2]))
            bare_top = max(bare_top, float(self.records[pid].orient_bounds[o][5] + t[2]))
        return bottom - (lo[2] + self.wall_gap), min(hi[2] - self.wall_gap - top, hi[2] - s2.C_WALL - bare_top)

    def com_shift_options(self, poses, u: float) -> tuple[list[float], dict]:
        """Candidate shifts along Z, preferred first: the key's choice between the minimal shift that brings the COM
        inside the CDS box and full centring (u = 0 … 1), then the minimal shift, then none. µm multiples, within
        the room the end plates leave."""
        info = {}
        com = self._com_z(poses) if self.com_shift_on and poses else None
        if com is None:
            return [0.0], info
        down, up = self._z_room(poses)
        info = {"com_z_unshifted_mm": com, "room_mm": [-max(down, 0.0), max(up, 0.0)]}
        if up < -SLACK or down < -SLACK:      # overflowing (beyond the µm-rounding allowance): nothing to move into
            return [0.0], info
        down, up = max(down, 0.0), max(up, 0.0)
        lim = COM_BOX_Z - COM_SHIFT_MARGIN
        s_min = (-lim - com) if com < -lim else ((lim - com) if com > lim else 0.0)
        s_full = -com                           # COM at the envelope centre (the CDS box centre)
        u = float(np.clip(u, 0.0, 1.0))

        def fit(s):
            return float(np.trunc(np.clip(s, -down, up) * 1000.0) / 1000.0)
        out = []
        for s in (fit(s_min + u * (s_full - s_min)), fit(s_min), 0.0):
            if s not in out:
                out.append(s)
        return out, info

    @staticmethod
    def shifted(poses, meta, s: float):
        """The layout moved by s along Z, with the stack-relative rules (rods, harness breaks, reserve) moved too."""
        if not s:
            return poses, meta
        dz = np.array([0.0, 0.0, s])
        poses = [(pid, o, np.round((np.asarray(t, float) + dz) * 1000.0) / 1000.0) for pid, o, t in poses]
        meta = dict(meta)
        if meta.get("stack_block") is not None:
            b = list(meta["stack_block"])
            b[2] += s
            b[5] += s
            meta["stack_block"] = b
            meta["stack_span"] = (meta["stack_span"][0] + s, meta["stack_span"][1] + s)
            meta["stack_z"] = meta["stack_z"] + s
        return poses, meta

    def _com_shift(self, poses, meta, u: float, partial: bool):
        """Apply the first candidate shift that mounts as many parts as any candidate does (a shift never costs a
        mount). Returns (shift, poses, meta, mount_check result)."""
        opts, info = self.com_shift_options(poses, u) if not partial else ([0.0], {})
        best = None
        for s in opts:
            p2, m2 = self.shifted(poses, meta, s)
            mc = self.mount_check(p2, m2)
            if best is None or mc[0] < best[3][0]:
                best = (s, p2, m2, mc)
            if mc[0] == 0:
                break
        s, p2, m2, mc = best
        m2 = dict(m2)
        m2["com_shift_mm"] = s
        if info:
            m2["com_z_unshifted_mm"] = info["com_z_unshifted_mm"]
            m2["com_shift_room_mm"] = info["room_mm"]
        return s, p2, m2, mc

    # ------------------------------------------------------------------------------------------ checks
    def mount_check(self, poses, meta) -> tuple[int, dict, list]:
        """Boards: PC/104 stack rods, or standoff contact for edge boards. Every other part: a bracket (V2 Stage 2,
        a reserved box that is part of the packing) or, in the V1 Manufacturable Design tab, a bracket envelope.
        Returns (failures, info, standoffs); a bracket's reserved box travels in its part's info."""
        decks = []
        if meta.get("stack_block") is not None:
            blk = meta["stack_block"]
            decks = [(2, blk[5], +1), (2, blk[2], -1)]
        fails, info, standoffs = 0, {}, []
        world_boxes = {}
        for pid, o, t in poses:
            p = self.proxies[self.ids.index(pid)]
            ob = p.oriented(o)
            world_boxes[pid] = np.concatenate([ob[:, :3] + t, ob[:, 3:] + t], axis=1)
        keepouts = list(self._statics_rails)
        if meta.get("corridor"):
            keepouts.append(corridor_box(meta["corridor"], self.dec_hi[2]))
        rest = []
        for pid, o, t in poses:                    # boards first: their standoffs are keep-outs for the brackets
            if pid in self.pcb and self.mode != "continuous":
                info[pid] = {"ok": True, "how": "PC/104 stack rods"}
            elif pid in self.macro:
                ok, how, st = self._standoffs(pid, o, t, world_boxes, keepouts)
                if "mounting" in self.relax and not ok:
                    ok, how, st = True, "mounting not checked (relaxed)", []
                standoffs += [(pid, s) for s in st]
                info[pid] = {"ok": ok, "how": how}
                fails += 0 if ok else 1
            elif pid not in self.pads:
                info[pid] = {"ok": True, "how": "mounting not checked (relaxed)"}
            else:
                rest.append((pid, o, t))
        if self.mfg:
            for pid, o, t in rest:
                info[pid] = self._mfg_mount(pid, o, t, decks, world_boxes, keepouts)
                fails += 0 if info[pid]["ok"] else 1
            return fails, info, standoffs
        m = {k: v for k, v in meta.items() if k != "brackets"}
        m["standoffs"] = standoffs
        keep = [(s.name, np.concatenate([s.corners.min(0), s.corners.max(0)])) for s in self.statics(m, relaxed=True)]
        reserved = []
        for pid, o, t in rest:
            info[pid] = self._bracket_mount(pid, o, t, meta, world_boxes, keep, reserved)
            if info[pid]["ok"]:
                reserved.append((f"bracket:{pid}", np.asarray(info[pid]["reserve"], float)))
            fails += 0 if info[pid]["ok"] else 1
        return fails, info, standoffs

    def _bracket_mount(self, pid, o, t, meta, world_boxes, keep, reserved) -> dict:
        """V2 Stage 2: the cheapest bracket whose reserved box reaches a wall, end plate, corner rail or the PC/104
        deck in front of the part's mounting side (within MFG_REACH) and keeps BRACKET_CLEARANCE from every other
        part, every keep-out except its own target, and every bracket reserved before it."""
        from ..mfg.rules import MFG_REACH, bracket_estimate, bracket_options, face_profile
        lo, hi = self.inner
        pad, a, sgn = self.pads[pid]
        if pid not in self.profiles:
            self.profiles[pid] = face_profile(self.records[pid], a, sgn)
        prof = self.profiles[pid]
        R = ROTATIONS_F[o]
        c = np.array([pad[:3] @ R.T, pad[3:] @ R.T])
        pw = np.concatenate([c.min(0) + t, c.max(0) + t])     # the 3 mm layer reservation in world
        d = sgn * R[:, a]
        ax = int(np.argmax(np.abs(d)))
        neg = bool(d[ax] < 0)
        side_mm = float(pw[3 + ax] if neg else pw[ax])        # the part's mounting side (its bounding-box face)
        side = f"{'-' if neg else '+'}{'xyz'[ax]}"
        b, cc = [k for k in range(3) if k != ax]
        # targets: (gap part side → target surface, target plane, label, keep-outs it may touch, parts it may touch,
        # lateral extent of the target or None for a whole wall)
        wall = float(lo[ax] if neg else hi[ax])
        targets = []
        if (side_mm - wall if neg else wall - side_mm) >= 0:     # an overflowing part may be beyond the end plate
            targets.append((abs(side_mm - wall), wall, f"{side} {'end plate' if ax == 2 else 'wall'}", (), (), None))
        if meta.get("stack_block") is not None and ax == 2:
            blk = np.asarray(meta["stack_block"], float)
            z = float(blk[5] if neg else blk[2])
            if (side_mm - z if neg else z - side_mm) >= 0:
                deck = ("stack_reserve", "rod++", "rod+-", "rod-+", "rod--")
                targets.append((abs(side_mm - z), z, f"PC/104 stack {'top' if neg else 'underside'}", deck,
                                tuple(self.pcb), blk))
        for name, rb in keep:
            if not name.startswith("rail"):
                continue
            if rb[b] < pw[3 + b] and rb[3 + b] > pw[b] and rb[cc] < pw[3 + cc] and rb[3 + cc] > pw[cc]:
                plane = float(rb[3 + ax] if neg else rb[ax])
                dist = (side_mm - plane) if neg else (plane - side_mm)
                if dist >= 0:
                    targets.append((dist, plane, f"corner rail {name[4:]} ({side})", (name,), (), rb))
        cands = []
        for gap, plane, label, tkeep, tparts, tbox in targets:
            if gap > MFG_REACH + 1e-9:
                continue
            for opt in bracket_options(prof, gap, self.am_allowed):
                r, depth = self._reserve(pw, ax, neg, plane, side_mm, opt, prof["extent_mm"], tbox)
                if r is None:
                    continue
                cost, vol = bracket_estimate(opt.kind, r, ax, gap, depth, opt.fasteners)
                cands.append((cost, gap, len(cands), opt, r, depth, plane, label, tkeep, tparts))
        blocked = None
        for cost, gap, _, opt, r, depth, plane, label, tkeep, tparts in sorted(cands, key=lambda x: x[:3]):
            hit = self._clear(r, pid, world_boxes, keep, reserved, tkeep, tparts)
            if hit is not None:
                blocked = blocked or (opt.kind, label, hit)
                continue
            return {"ok": True, "how": f"{opt.mount_type} to the {label} ({gap:.1f} mm)", "kind": opt.kind,
                    "mount_type": opt.mount_type, "process": opt.process, "fasteners": opt.fasteners,
                    "cost_est": float(cost), "gap_mm": float(gap), "target": label, "target_statics": list(tkeep),
                    "target_parts": list(tparts), "reserve": r.tolist(), "axis": ax, "neg": neg,
                    "part_side_mm": side_mm, "plane_mm": float(plane), "depth_mm": float(depth)}
        if blocked:
            return {"ok": False, "how": f"every bracket path is blocked (cheapest: {blocked[0]} to the {blocked[1]}, "
                                        f"blocked by {blocked[2]})"}
        return {"ok": False, "how": f"no wall, rail or deck within {MFG_REACH:.0f} mm in front of its mounting side "
                                    f"({side}) — not within reach"}

    @staticmethod
    def _reserve(pw, ax, neg, plane, side_mm, opt, extent, tbox):
        """Reserved box of one bracket option: from the target plane to the part side, `depth` into the part's
        bounding box, over a share of the mounting-side footprint (centred, or moved toward a rail or deck and
        clipped to it). Returns (box, depth) or (None, 0) when the clipped flange is too narrow."""
        from ..mfg.rules import BRACKET_MIN_W
        r = np.asarray(pw, float).copy()
        depth = float(min(opt.depth, extent))
        if neg:
            r[ax], r[3 + ax] = plane, side_mm + depth
        else:
            r[ax], r[3 + ax] = side_mm - depth, plane
        lat = [k for k in range(3) if k != ax]
        lat.sort(key=lambda k: -(pw[3 + k] - pw[k]))          # longer side first
        for k, share in zip(lat, opt.lateral):
            w = share * (pw[3 + k] - pw[k])
            mid = 0.5 * (pw[k] + pw[3 + k])
            if tbox is not None:
                mid = float(np.clip(0.5 * (tbox[k] + tbox[3 + k]), pw[k] + w / 2, pw[3 + k] - w / 2))
            r[k], r[3 + k] = mid - w / 2, mid + w / 2
            if tbox is not None:
                r[k], r[3 + k] = max(r[k], tbox[k]), min(r[3 + k], tbox[3 + k])
                if r[3 + k] - r[k] < min(BRACKET_MIN_W, pw[3 + k] - pw[k]) - 1e-9:
                    return None, 0.0
        return r, depth

    @staticmethod
    def _clear(r, pid, world_boxes, keep, reserved, tkeep, tparts):
        """None if the box keeps BRACKET_CLEARANCE (+ rounding allowance) from every other part's boxes, every
        keep-out except the target's and every reserved bracket; else the name of the first obstacle."""
        from ..mfg.rules import BRACKET_CLEARANCE
        g = BRACKET_CLEARANCE + SLACK
        for qid, boxes in world_boxes.items():
            if qid == pid or qid in tparts:
                continue
            if np.max(np.maximum(boxes[:, :3] - r[3:], r[:3] - boxes[:, 3:]), axis=1).min() < g:
                return qid
        for name, kb in keep:
            if name not in tkeep and np.max(np.maximum(kb[:3] - r[3:], r[:3] - kb[3:])) < g:
                return name
        for name, kb in reserved:
            if np.max(np.maximum(kb[:3] - r[3:], r[:3] - kb[3:])) < g:
                return name
        return None

    def _mfg_mount(self, pid, o, t, decks, world_boxes, keepouts) -> dict:
        """Manufacturable Design: the nearest wall / end plate / deck / rail in front of the mounting side, a clear
        bracket envelope to it, and the cheapest mount type the rules allow for that gap and side shape."""
        from ..mfg.rules import MFG_REACH, choose_mount, face_profile
        lo, hi = self.inner
        pad, a, sgn = self.pads[pid]
        if pid not in self.profiles:
            self.profiles[pid] = face_profile(self.records[pid], a, sgn)
        R = ROTATIONS_F[o]
        c = np.array([pad[:3] @ R.T, pad[3:] @ R.T])
        pw = np.concatenate([c.min(0) + t, c.max(0) + t])
        d = sgn * R[:, a]
        ax = int(np.argmax(np.abs(d)))
        neg = d[ax] < 0
        face = pw[ax] if neg else pw[3 + ax]
        side = f"{'-' if neg else '+'}{'xyz'[ax]}"
        b, cc = [k for k in range(3) if k != ax]
        targets = [((face - lo[ax]) if neg else (hi[ax] - face), lo[ax] if neg else hi[ax],
                    f"{side} {'end plate' if ax == 2 else 'wall'}")]
        for dax, z, sgn in decks:
            if dax == ax and ((sgn > 0 and neg) or (sgn < 0 and not neg)):
                targets.append(((face - z) if neg else (z - face), z, "PC/104 stack deck"))
        for rb in self._statics_rails:
            if rb[b] < pw[3 + b] and rb[3 + b] > pw[b] and rb[cc] < pw[3 + cc] and rb[3 + cc] > pw[cc]:
                plane = rb[3 + ax] if neg else rb[ax]
                dist = (face - plane) if neg else (plane - face)
                if dist >= 0:
                    targets.append((dist, plane, f"corner rail ({side})"))
        for dist, plane, label in sorted(targets):
            if dist < -1e-6:
                continue
            gap = dist + PAD                         # part side → target surface
            if gap > MFG_REACH + 1e-9:
                break
            env = pw.copy()
            if neg:
                env[ax], env[3 + ax] = plane, face
            else:
                env[ax], env[3 + ax] = face, plane
            blocked = None
            for qid, boxes in world_boxes.items():
                if qid == pid or dist <= s2.C_WALL + 0.01:
                    continue
                if np.any(np.all((boxes[:, :3] < env[3:] - 1e-6) & (boxes[:, 3:] > env[:3] + 1e-6), axis=1)):
                    blocked = qid
                    break
            if blocked:
                continue
            if any(np.all(kb[:3] < env[3:] - 1e-6) and np.all(kb[3:] > env[:3] + 1e-6) for kb in keepouts):
                continue                             # the bracket would cross a rail or the cable corridor
            ch = choose_mount(self.profiles[pid], gap)
            if ch is None:
                break
            return {"ok": True, "how": f"{ch.mount_type} to the {label} ({gap:.1f} mm)", "mount_type": ch.mount_type,
                    "process": ch.process, "fasteners": ch.fasteners, "cost_est": ch.cost_est, "gap_mm": gap,
                    "target": label, "envelope": env.tolist(), "axis": ax, "neg": bool(neg), "reason": ch.reason}
        return {"ok": False, "how": f"no wall, rail or deck within {MFG_REACH:.0f} mm in front of its mounting side "
                                    f"({side}), or the bracket path is blocked"}

    def _standoffs(self, pid, o, t, world_boxes, keepouts):
        """Lengthen the board's 3 mm standoffs to the wall they face (≤ 50 mm) if the path is clear."""
        lo, hi = self.inner
        m = self.macro[pid]
        R = ROTATIONS_F[o]
        st = []
        for sb in m["stand"]:
            c = np.array([sb[:3] @ R.T, sb[3:] @ R.T])
            st.append(np.concatenate([c.min(0) + t, c.max(0) + t]))
        d = -R[:, m["axis"]]                      # world direction the standoffs point to
        ax = int(np.argmax(np.abs(d)))
        neg = d[ax] < 0
        tips = min(s[ax] for s in st) if neg else max(s[3 + ax] for s in st)
        wall = lo[ax] if neg else hi[ax]
        gap = abs(tips - wall)
        name = f"{'-' if neg else '+'}{'xyz'[ax]} wall"
        if STANDOFF_LEN + gap > STANDOFF_MAX + 1e-9:
            return False, f"the {name} is {gap + STANDOFF_LEN:.1f} mm from the board (> {STANDOFF_MAX:.0f} mm standoffs)", []
        ext = []
        for s in st:
            s = s.copy()
            if neg:
                s[ax] = wall
            else:
                s[3 + ax] = wall
            ext.append(s)
        c = s2.C_WALL
        for e in ext:
            path = e.copy()
            if neg:
                path[3 + ax] = tips             # only the added length can meet something new
            else:
                path[ax] = tips
            for qid, boxes in world_boxes.items():
                if qid == pid:
                    continue
                if np.any(np.all((boxes[:, :3] < path[3:] + c) & (boxes[:, 3:] > path[:3] - c), axis=1)):
                    return False, f"the path to the {name} is blocked by {qid}", []
            for kb in keepouts:
                if np.all(kb[:3] < path[3:] + c) and np.all(kb[3:] > path[:3] - c):
                    return False, f"the path to the {name} crosses a rail or the cable corridor", []
        length = STANDOFF_LEN + gap
        return True, f"4 × M3 standoffs ({length:.1f} mm) to the {name}", [e.tolist() for e in ext]

    def blocked_fraction(self, poses, meta) -> float:
        """Share of the +X corridor's length crossed by any part (soft mode objective H)."""
        cb = corridor_box("+x")
        ivs = []
        for pid, o, t in poses:
            b = self.records[pid].orient_bounds[o]
            plo, phi = b[:3] + t, b[3:] + t
            if np.all(plo[:2] < cb[3:5] + s2.C_WALL) and np.all(phi[:2] > cb[:2] - s2.C_WALL):
                ivs.append((max(plo[2], cb[2]), min(phi[2], cb[5])))
        ivs = sorted(iv for iv in ivs if iv[1] > iv[0])
        total, cur = 0.0, None
        for a, b in ivs:
            if cur is None or a > cur[1]:
                if cur:
                    total += cur[1] - cur[0]
                cur = [a, b]
            else:
                cur[1] = max(cur[1], b)
        if cur:
            total += cur[1] - cur[0]
        return float(total / (cb[5] - cb[2]))

    @staticmethod
    def standoff_mass(standoffs) -> list:
        out = []
        for _, b in standoffs:
            b = np.asarray(b, float)
            d = b[3:] - b[:3]
            m = STANDOFF_MASS_DENSITY * float(np.prod(d)) * 1e-9
            c = 0.5 * (b[:3] + b[3:])
            i = m / 12 * np.diag([d[1] ** 2 + d[2] ** 2, d[0] ** 2 + d[2] ** 2, d[0] ** 2 + d[1] ** 2]) * 1e-6
            out.append((m, c, i))
        return out
