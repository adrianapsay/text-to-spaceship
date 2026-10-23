"""Stage 2 (ENGINEERING-CONSTRAINED) geometry and rules (protocol §O.2, Addenda 1–2). All values ASSUMED unless noted.

Frame: 2.0 mm walls, four 8.5 x 8.5 mm full-length corner rails inside the 100 x 100 mm envelope (CDS rail width).
Clearances: 2.2 mm part-part, 1.2 mm part-wall/rail (2.0/1.0 + 0.2 mm tolerance per gap, decision U4).
Harness (U5): 10 mm channel along the +X wall between the rails, interrupted across the PCB stack's Z span.
PC/104 stack: PCB-tagged parts parallel to XY, XY-centred, 15.24 mm pitch; 4 rod keep-outs spanning only the stack.
  Rod positions are ASSUMED at (±35, ±35) mm (inside the boards' notched corners): no cited PC/104 source yet (DD-20).
Mounting layer (U6): 3 mm on an optimiser-chosen face touching a wall or rail; replaces the 1.2 mm wall clearance on
  that face; reach is ASSUMED <= 5 mm beyond the layer.
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
ROD_D = 3.2               # M3 clearance keep-out (square of this side)
MOUNT_LAYER = 3.0
MOUNT_REACH = 5.0
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


def rod_items(cfg: Stage2Config) -> list[StaticItem]:
    if not cfg.pcb_ids or cfg.stack_z is None:
        return []
    z0, z1 = cfg.stack_z
    h = ROD_D / 2
    return [StaticItem(f"rod{'+' if sx > 0 else '-'}{'+' if sy > 0 else '-'}",
                       box_corners([sx * ROD_XY - h, sy * ROD_XY - h, z0], [sx * ROD_XY + h, sy * ROD_XY + h, z1]), "rod")
            for sx in (1, -1) for sy in (1, -1)]


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


# ----------------------------------------------------------------------------------- mounting (U6)
def mount_check(hull_world: np.ndarray, spec: StageSpec, deck_planes: list[tuple[int, float, float]] = ()):
    """Find a face of the part's AABB that can carry the 3 mm mounting layer to a wall, rail or deck.

    Returns (ok, description, distance_mm). A face qualifies when its distance to the target surface lies in
    [MOUNT_LAYER, MOUNT_LAYER + MOUNT_REACH]; walls are at the inner box (spec bounds + C_WALL).
    """
    lo, hi = hull_world.min(axis=0), hull_world.max(axis=0)
    wall_lo = spec.lo - C_WALL
    wall_hi = spec.hi + C_WALL
    best = None
    for ax in range(3):
        for side, d in (("-", lo[ax] - wall_lo[ax]), ("+", wall_hi[ax] - hi[ax])):
            if MOUNT_LAYER - 1e-9 <= d <= MOUNT_LAYER + MOUNT_REACH:
                cand = (d, f"face {side}{'xyz'[ax]} to wall ({d:.2f} mm)")
                if best is None or d < best[0]:
                    best = cand
    for ax, z_face, sign in deck_planes:
        d = (lo[ax] - z_face) if sign > 0 else (z_face - hi[ax])
        if MOUNT_LAYER - 1e-9 <= d <= MOUNT_LAYER + MOUNT_REACH:
            cand = (d, f"face to deck at {z_face:.1f} mm ({d:.2f} mm)")
            if best is None or d < best[0]:
                best = cand
    if best is None:
        return False, "no face within mounting reach of a wall, rail or deck", None
    return True, best[1], best[0]


# ----------------------------------------------------------------------------------- insertion (±Z)
def blocking_matrix(world_hulls: dict[str, np.ndarray], world_pieces: dict[str, list[np.ndarray]],
                    z_extent: tuple[float, float], c_ins: float = 0.2):
    """B[u][i][j] = True when part i, swept straight along u (+Z or -Z) out of the enclosure, comes within
    c_ins of part j. Sweeps of convex hulls are convex (hull of V and V + L·u), so plane certificates apply.
    Non-convex blockers use their certified cover pieces."""
    from ..collision.validate import plane_certificate
    ids = list(world_hulls)
    zlo, zhi = z_extent
    out = {"+z": {}, "-z": {}}
    for u, sign in (("+z", 1.0), ("-z", -1.0)):
        for i in ids:
            h = world_hulls[i]
            length = (zhi - h[:, 2].min()) if sign > 0 else (h[:, 2].max() - zlo)
            sweep = np.vstack([h, h + np.array([0, 0, sign * (length + 1.0)])])
            row = {}
            for j in ids:
                if i == j:
                    continue
                blocked = False
                lo_s, hi_s = sweep.min(0), sweep.max(0)
                lo_j, hi_j = world_hulls[j].min(0), world_hulls[j].max(0)
                if np.any(hi_s < lo_j - c_ins) or np.any(lo_s > hi_j + c_ins):
                    row[j] = False
                    continue
                for piece in world_pieces[j]:
                    _, gap, _, _ = plane_certificate(sweep, piece)
                    if gap < c_ins:
                        blocked = True
                        break
                row[j] = blocked
            out[u][i] = row
    return out


def assembly_order(block) -> tuple[list[tuple[str, str]] | None, list[str]]:
    """Greedy disassembly (complete for single-part straight-line removal): repeatedly remove any part with no
    remaining blocker in some direction. Returns (insertion order [(part, direction)], stuck parts)."""
    remaining = set(block["+z"])
    removal = []
    while remaining:
        progress = False
        for i in sorted(remaining):
            for u in ("+z", "-z"):
                if not any(block[u][i].get(j, False) for j in remaining if j != i):
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
