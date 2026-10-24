"""Stage 2 (ENGINEERING-CONSTRAINED) geometry and rules (protocol §O.2, Addenda 1–2). All values ASSUMED unless noted.

Frame: 2.0 mm walls, four 8.5 x 8.5 mm full-length corner rails inside the 100 x 100 mm envelope (CDS rail width).
Clearances: 2.2 mm part-part, 1.2 mm part-wall/rail (2.0/1.0 + 0.2 mm tolerance per gap, decision U4).
Harness (U5): 10 mm channel along the +X wall between the rails, interrupted across the PCB stack's Z span.
PC/104 stack: PCB-tagged parts parallel to XY, XY-centred, 15.24 mm pitch; 4 rods with spacer tubes (5 mm square
  keep-outs) run from the stack's end plate through every board (v2.5; before: rods spanning only the stack).
  Rod positions are ASSUMED at (±35, ±35) mm (inside the boards' notched corners): no cited PC/104 source yet (DD-20).
Mounting layer (U6): 3 mm on an optimiser-chosen face; replaces the 1.2 mm wall clearance on that face (the V2 bracket
  model in stage2_model.py decides where it is fixed).
Frame mass (U7): computed from this geometry at 2,700 kg/m^3; excluded from the hard COM check by default.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..collision.validate import StageSpec, StaticItem
from ..core.formfactor import ENVELOPE      # shared array: 3U 100 × 100 × 340.5 mm unless 6U / 12U is chosen (V2)
WALL = 2.0
RAIL = 8.5
C_PP = 2.2
C_WALL = 1.2
HARNESS_W = 10.0
PCB_PITCH = 15.24
ROD_XY = 35.0
ROD_D = 3.2               # M3 clearance keep-out (square of this side): rods of layouts decoded before v2.5
ROD_KEEP = 5.0            # v2.5 rod keep-out: the spacer-tube envelope around each rod (as mfg.brackets.spacer_set)
MOUNT_LAYER = 3.0
AL_DENSITY = 2700.0


def box_corners(lo, hi) -> np.ndarray:
    return np.array([[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])], float)


@dataclass
class Stage2Config:
    harness: bool = True
    harness_mode: str = "interrupted"         # "interrupted" (default) | "continuous" (cable-routing high mode)
    harness_wall: str = "+x"
    pcb_ids: list[str] = field(default_factory=list)
    stack_z: tuple[float, float] | None = None   # Z span of the PCB stack (for harness interruption and rods)
    include_frame_mass: bool = False
    rod_end: str | None = None                   # "-z" / "+z": rods run from that end plate (v2.5); None: stack only


def inner_box():
    half = ENVELOPE / 2 - WALL
    return -half, half


def rails() -> list[StaticItem]:
    lo, hi = inner_box()
    half = ENVELOPE[:2] / 2
    out = []
    for sx in (1, -1):
        for sy in (1, -1):
            x0, x1 = sorted([sx * (half[0] - RAIL), sx * half[0]])
            y0, y1 = sorted([sy * (half[1] - RAIL), sy * half[1]])
            out.append(StaticItem(f"rail{'+' if sx > 0 else '-'}x{'+' if sy > 0 else '-'}y",
                                  box_corners([x0, y0, lo[2]], [x1, y1, hi[2]]), "rail"))
    return out


def harness_items(cfg: Stage2Config) -> list[StaticItem]:
    if not cfg.harness:
        return []
    lo, hi = inner_box()
    y0, y1 = -(ENVELOPE[1] / 2 - RAIL), ENVELOPE[1] / 2 - RAIL
    x0, x1 = hi[0] - HARNESS_W, hi[0]
    spans = [(lo[2], hi[2])]
    if cfg.harness_mode == "interrupted" and cfg.stack_z is not None:
        z0, z1 = cfg.stack_z
        spans = [(lo[2], z0 - C_WALL), (z1 + C_WALL, hi[2])]
    out = []
    for i, (a, b) in enumerate(spans):
        if b - a > 1e-6:
            out.append(StaticItem(f"harness{i}", box_corners([x0, y0, a], [x1, y1, b]), "harness"))
    return out


def pc104_rods(rod_xy: float, z0: float, z1: float, side: float = ROD_KEEP) -> list[tuple[str, np.ndarray]]:
    """The four PC/104 rod keep-outs (name, box lo + hi) at (±rod_xy, ±rod_xy) from z0 to z1, `side` mm square: the one
    rod builder behind the decoder's obstacles, the validation rules, the insertion check and the display."""
    h = side / 2
    return [(f"rod{'+' if sx > 0 else '-'}{'+' if sy > 0 else '-'}",
             np.array([sx * rod_xy - h, sy * rod_xy - h, z0, sx * rod_xy + h, sy * rod_xy + h, z1], float))
            for sx in (1, -1) for sy in (1, -1)]


def rod_items(cfg: Stage2Config) -> list[StaticItem]:
    """Rods of a stack at cfg.stack_z: from the end plate cfg.rod_end through the stack (v2.5), or over the stack only."""
    if not cfg.pcb_ids or cfg.stack_z is None:
        return []
    z0, z1 = cfg.stack_z
    lo, hi = inner_box()
    if cfg.rod_end is None:
        rods = pc104_rods(ROD_XY, z0, z1, ROD_D)
    else:
        rods = pc104_rods(ROD_XY, lo[2], z1) if cfg.rod_end == "-z" else pc104_rods(ROD_XY, z0, hi[2])
    return [StaticItem(name, box_corners(b[:3], b[3:]), "rod") for name, b in rods]


def stage2_spec(cfg: Stage2Config) -> StageSpec:
    lo, hi = inner_box()
    statics = rails() + harness_items(cfg) + rod_items(cfg)
    exempt = {(pid, s.name) for pid in cfg.pcb_ids for s in statics if s.kind == "rod"}
    # containment bounds: parts keep the wall clearance; the mounting-layer face is checked separately
    return StageSpec(2, lo + C_WALL, hi - C_WALL, C_PP, C_WALL, statics, exempt)


def frame_mass_props():
    """Mass, COM (mm) and inertia about its COM (kg m^2) of the ASSUMED frame: walls + rails (aluminium)."""
    half_out = ENVELOPE / 2
    half_in = half_out - WALL
    pieces = []
    # walls: outer box minus inner box, as 6 slabs (x, y side walls full length; end plates)
    def slab(lo, hi):
        d = np.array(hi) - np.array(lo)
        m = AL_DENSITY * np.prod(d) * 1e-9
        c = 0.5 * (np.array(lo) + np.array(hi))
        i = m / 12 * np.diag([d[1] ** 2 + d[2] ** 2, d[0] ** 2 + d[2] ** 2, d[0] ** 2 + d[1] ** 2]) * 1e-6
        pieces.append((m, c, i))
    slab([-half_out[0], -half_out[1], -half_in[2]], [-half_in[0], half_out[1], half_in[2]])
    slab([half_in[0], -half_out[1], -half_in[2]], [half_out[0], half_out[1], half_in[2]])
    slab([-half_in[0], -half_out[1], -half_in[2]], [half_in[0], -half_in[1], half_in[2]])
    slab([-half_in[0], half_in[1], -half_in[2]], [half_in[0], half_out[1], half_in[2]])
    slab([-half_out[0], -half_out[1], -half_out[2]], [half_out[0], half_out[1], -half_in[2]])
    slab([-half_out[0], -half_out[1], half_in[2]], [half_out[0], half_out[1], half_out[2]])
    for r in rails():
        lo, hi = r.corners.min(0), r.corners.max(0)
        # rail portion inside the walls only (the wall slabs already cover the outer 2 mm)
        lo2 = np.maximum(lo, -half_in)
        hi2 = np.minimum(hi, half_in)
        if np.all(hi2 > lo2):
            slab(lo2, hi2)
    m = sum(p[0] for p in pieces)
    c = sum(p[0] * p[1] for p in pieces) / m
    inertia = np.zeros((3, 3))
    for mi, ci, ii in pieces:
        d = (ci - c) * 1e-3
        inertia += ii + mi * (d @ d * np.eye(3) - np.outer(d, d))
    return m, c, inertia


# ----------------------------------------------------------------------------------- insertion (±Z)
def blocking_matrix(world_hulls: dict, world_pieces: dict[str, list[np.ndarray]],
                    z_extent: tuple[float, float], c_ins: float = 0.2, fixed: dict | None = None):
    """B[u][i][j] = True when part i, swept straight along u (+Z or -Z) out of the enclosure, comes within
    c_ins of part j. world_hulls[i]: the convex point set that moves (the part's hull), or a list of them (the hull
    and what moves with it: standoffs, a bracket's reserved box), each swept on its own. Sweeps of convex sets are
    convex (hull of V and V + L·u), so plane certificates apply. Non-convex blockers use their certified cover
    pieces. fixed: {name: (corners, exempt part ids)} — items that are never removed (the PC/104 rods on their end
    plate); B[u][i][name] says whether one blocks part i (B["fixed"] lists their names)."""
    from ..collision.validate import plane_certificate
    moving = {i: (list(h) if isinstance(h, (list, tuple)) else [h]) for i, h in world_hulls.items()}
    ids = list(moving)
    span = {i: np.vstack(m) for i, m in moving.items()}
    fixed = fixed or {}
    zlo, zhi = z_extent
    out = {"+z": {}, "-z": {}, "fixed": sorted(fixed)}
    for u, sign in (("+z", 1.0), ("-z", -1.0)):
        for i in ids:
            length = (zhi - span[i][:, 2].min()) if sign > 0 else (span[i][:, 2].max() - zlo)
            sweeps = [np.vstack([h, h + np.array([0, 0, sign * (length + 1.0)])]) for h in moving[i]]
            boxes = [(s.min(0), s.max(0)) for s in sweeps]
            row = {}
            blockers = [(j, span[j], world_pieces[j]) for j in ids if j != i]
            blockers += [(name, c, [c]) for name, (c, exempt) in fixed.items() if i not in exempt]
            for j, pts_j, pieces_j in blockers:
                blocked = False
                lo_j, hi_j = pts_j.min(0), pts_j.max(0)
                for sweep, (lo_s, hi_s) in zip(sweeps, boxes):
                    if np.any(hi_s < lo_j - c_ins) or np.any(lo_s > hi_j + c_ins):
                        continue
                    for piece in pieces_j:
                        _, gap, _, _ = plane_certificate(sweep, piece)
                        if gap < c_ins:
                            blocked = True
                            break
                    if blocked:
                        break
                row[j] = blocked
            out[u][i] = row
    return out


def assembly_order(block, allowed: dict | None = None) -> tuple[list[tuple[str, str]] | None, list[str]]:
    """Greedy disassembly (complete for single-part straight-line removal): repeatedly remove any part with no
    remaining blocker (fixed items always remain) in some direction it may leave in (allowed: part -> directions,
    default both). Returns (insertion order [(part, direction)], stuck parts)."""
    remaining = set(block["+z"])
    fixed = list(block.get("fixed", []))
    allowed = allowed or {}
    removal = []
    while remaining:
        progress = False
        for i in sorted(remaining):
            for u in ("+z", "-z"):
                if u not in allowed.get(i, ("+z", "-z")):
                    continue
                if not any(block[u][i].get(j, False) for j in [*remaining, *fixed] if j != i):
                    removal.append((i, u))
                    remaining.discard(i)
                    progress = True
                    break
            if progress:
                break
        if not progress:
            return None, sorted(remaining)
    # insertion is the reverse of removal, entering from the end it left through
    return list(reversed(removal)), []
