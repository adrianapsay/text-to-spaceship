"""Brackets that hold several parts (M4): one printed bracket per wall ("combined") and one printed piece for every
part except the PC/104 boards ("one piece"). The user's rule: a bracket may hold several parts as long as no part is
held only by another part — every part's contact zone must reach the chassis through bracket material.

Combined per wall
-----------------
* Candidates: the metal-AM brackets of a layout (the printed ones; direct mounts, machined blocks, sheet brackets,
  clamps and cradles keep their per-part form). Two of them can be joined when they are fixed to the same target —
  the same wall or end-plate plane, or the same corner rail — and the space between their reserved boxes is clear:
  a bridging box spans the gap between the two boxes (along one in-plane axis, over the width both boxes share on the
  other, from the target plane to the nearer part side). It must keep 1.2 mm (+ the 2 µm rounding allowance of the
  packing) from every part except the two it joins, every reserved box except theirs, every keep-out except the
  target rail, and every bridge of another group (box arithmetic, as the packing checks a reserved box). Pairs are
  tried closest first; joined brackets form groups (union-find).
* Design region = the voxels inside the member boxes and the bridging boxes. Every box starts on the target plane and
  extends to the same side (a "column"), and the region is eroded at the boxes' re-entrant corners until the voxels of
  every 2 × 2 × 2 block lie in one common box. Then every marching-cubes triangle lies inside one box (its vertices lie
  on edges between voxel centres of its block, at most half a voxel beyond a solid one), the boundary of the solid
  lies in the union of the boxes, and — the boxes being columns on one plane, so that no point outside them is
  enclosed by them — the solid does too. tools/check_certificate.py checks every triangle against the boxes.
* Each held part: its contact zone is the part surface within its own reserved box (its mounting side, and where the
  box wraps the part), its mass, centre of mass and inertia; its bolts are its own bracket's pattern on its own
  bolted face. One bolted plane (the target).

One piece (exploratory)
-----------------------
* One grid over the true inner box (walls and end plates), voxels ≤ 2.7 mm across the side walls so that the 3 mm
  mounting gap of every part holds one voxel layer with ≥ 0.3 mm to the part (and ≤ 4 mm along the length, ≤ 2.7 mm
  if a part is mounted on an end plate). The grid lies exactly on all six inner planes (h = length ÷ count per axis).
* Bolted planes (chosen, documented): the one piece is bolted where the per-part brackets are — on each part's own
  target wall or end plate, within the footprint of its reserved box, with that bracket's fasteners. Parts on a corner
  rail keep their per-part bracket (a rail face is not a grid plane).
* Void: within 1.2 mm of every keep-out (rails, PC/104 rods and stack reserve, harness, standoffs, brackets that stay)
  and of every part it does not hold, measured from the 2h-cube around each voxel (a marching-cubes triangle of a
  voxel lies in that cube, so the proof needs no voxel cover); within 1.2 mm of every held part outside its contact
  zone (a numeric check of the final solid reports the true distance); the part interiors.
* Contact zone and pad: the voxels in the part's reserved box next to its surface; the first voxel layer on its
  target plane under it is bolted. The optimiser (gd.simp) fills the free space; the solid is then joined into one
  piece by shortest paths through the free space (gd.multi.join).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .domain import CONTACT_GAP, LIMIT_G
from .environment import G0
from .materials import fea_material

CLEAR = 1.2                     # mm: mfg.rules.BRACKET_CLEARANCE (packing rule)
SLACK = 0.002                   # mm: rounding allowance kept on every Stage 2 gap (constraints.stage2_model.SLACK)
COMBINE_KINDS = ("metal_am",)   # brackets that are printed and can be joined
MIN_BRIDGE_W = 3.0              # mm: narrowest shared width a bridge may have (ASSUMED)
MAX_BRIDGE_GAP = 25.0           # mm: widest gap between two boxes a bridge spans (ASSUMED; "neighbouring")
H_PRE = 2.0                     # mm: the coarsest voxel a combined bracket uses (its bridge pre-check margin)
HELD_MARGIN = 1.2               # mm: one piece keeps this from a held part outside its contact zone
ONE_PIECE_H_WALL = 2.7          # mm: largest voxel across a side wall (3 mm gap − 0.3 mm contact gap)
ONE_PIECE_H_LONG = 4.0          # mm: largest voxel along the length when no part sits on an end plate


# ================================================================================================== box helpers
def box_gap(a, b) -> float:
    """Largest axis separation of two boxes (lo xyz, hi xyz): ≤ their distance (box arithmetic)."""
    a, b = np.asarray(a, float), np.asarray(b, float)
    return float(np.max(np.maximum(b[:3] - a[3:], a[:3] - b[3:])))


def _gaps(boxes: np.ndarray, r: np.ndarray) -> np.ndarray:
    boxes = np.asarray(boxes, float).reshape(-1, 6)
    return np.max(np.maximum(boxes[:, :3] - r[3:], r[:3] - boxes[:, 3:]), axis=1)


def target_key(b: dict) -> tuple:
    """Brackets with the same key are fixed to the same plane of the same chassis structure."""
    kind = b.get("target_kind") or ("end_plate" if int(b["axis"]) == 2 else "wall")
    rails = tuple(sorted(b.get("target_statics") or [])) if kind == "rail" else ()
    return kind, int(b["axis"]), bool(b["neg"]), round(float(b["plane_mm"]), 6), rails


# ================================================================================================== grouping
def bridge_candidate(a: dict, b: dict, h_pre: float = H_PRE) -> dict | None:
    """The bridging box between two brackets of one target, or None: the boxes must be apart along one in-plane axis
    (≤ MAX_BRIDGE_GAP) and share at least MIN_BRIDGE_W on the other. Returns the gap box (from the target plane to the
    nearer part side, between the two boxes, over the shared width) and the conservative check box: the gap box grown
    2 h_pre into each member box along the gap axis (the box the voxel grid can snap the bridge to)."""
    ax, neg, plane = int(a["axis"]), bool(a["neg"]), float(a["plane_mm"])
    ra, rb = np.asarray(a["reserve"], float), np.asarray(b["reserve"], float)
    lat = [k for k in range(3) if k != ax]
    best = None
    for s in lat:
        w = lat[0] if s == lat[1] else lat[1]
        lo_box, hi_box = (ra, rb) if ra[3 + s] <= rb[s] else (rb, ra)
        gap = float(hi_box[s] - lo_box[3 + s])
        if gap <= 0 or gap > MAX_BRIDGE_GAP:
            continue
        wlo, whi = max(ra[w], rb[w]), min(ra[3 + w], rb[3 + w])
        if whi - wlo < MIN_BRIDGE_W:
            continue
        depth = min(float(a["gap_mm"]), float(b["gap_mm"]))
        if depth <= 0:
            continue
        g = np.zeros(6)
        g[s], g[3 + s] = lo_box[3 + s], hi_box[s]
        g[w], g[3 + w] = wlo, whi
        g[ax], g[3 + ax] = (plane, plane + depth) if neg else (plane - depth, plane)
        chk = g.copy()
        chk[s], chk[3 + s] = g[s] - 2 * h_pre, g[3 + s] + 2 * h_pre
        if best is None or gap < best["gap_mm"]:
            best = {"gap_box": g.tolist(), "check_box": chk.tolist(), "gap_mm": gap, "across": s, "along": w,
                    "ends": [a["pid"], b["pid"]]}
    return best


def combine_groups(brackets: list[dict], part_boxes: dict, keepouts: list, kinds=COMBINE_KINDS,
                   h_pre: float = H_PRE, clearance: float = CLEAR + SLACK) -> list[dict]:
    """Groups of brackets joined by bridges (two or more members each). `part_boxes`: {pid: (k, 6) world boxes that
    contain the part (its certified G1 boxes)}; `keepouts`: [(name, kind, (6,) box)] every keep-out of the layout
    (rails, rods, stack reserve, harness, standoffs) — not the brackets. Each group: members (bracket dicts), bridges
    [{gap_box, check_box, ends, across, along}], the target (axis, neg, plane, kind, rails)."""
    tol = clearance - 1e-6
    bs = [b for b in brackets if b.get("kind") in kinds]
    others = {b["name"]: np.asarray(b["reserve"], float) for b in brackets}
    keys = [target_key(b) for b in bs]
    pairs = []
    for i in range(len(bs)):
        for j in range(i + 1, len(bs)):
            if keys[i] != keys[j]:
                continue
            c = bridge_candidate(bs[i], bs[j], h_pre)
            if c is not None:
                pairs.append((c["gap_mm"], i, j, c))
    parent = list(range(len(bs)))

    def find(k):
        while parent[k] != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k
    accepted = []
    for _, i, j, c in sorted(pairs, key=lambda x: (x[0], bs[x[1]]["pid"], bs[x[2]]["pid"])):
        chk = np.asarray(c["check_box"], float)
        ends = {bs[i]["pid"], bs[j]["pid"]}
        rails = set(keys[i][4])
        ok = True
        for pid, boxes in part_boxes.items():              # every part but the two it joins
            if pid not in ends and len(boxes) and _gaps(boxes, chk).min() < tol:
                ok = False
                break
        if ok:
            for name, r in others.items():                 # every reserved box but the two it joins
                if name not in (bs[i]["name"], bs[j]["name"]) and box_gap(r, chk) < tol:
                    ok = False
                    break
        if ok:
            for name, kind, r in keepouts:                 # every keep-out but the target rail
                if name not in rails and box_gap(r, chk) < tol:
                    ok = False
                    break
        if ok:                                             # bridges of other groups (any target) keep away too
            gi, gj = find(i), find(j)
            for ci, cj, cc in accepted:
                if find(ci) not in (gi, gj) and box_gap(np.asarray(cc["check_box"], float), chk) < tol:
                    ok = False
                    break
        if not ok:
            continue
        accepted.append((i, j, c))
        parent[find(i)] = find(j)
    comps: dict = {}
    for k in range(len(bs)):
        comps.setdefault(find(k), []).append(k)
    groups = []
    for root, ks in comps.items():
        if len(ks) < 2:
            continue
        members = [bs[k] for k in sorted(ks, key=lambda k: bs[k]["pid"])]
        br = [c for i, j, c in accepted if find(i) == root]
        kind, ax, neg, plane, rl = keys[ks[0]]
        groups.append({"members": members, "bridges": br, "axis": ax, "neg": neg, "plane_mm": plane,
                       "target_kind": kind, "target_statics": list(rl), "target": members[0]["target"],
                       "pids": [m["pid"] for m in members]})
    for k, g in enumerate(sorted(groups, key=lambda g: (g["target"], g["pids"]))):
        g["name"] = f"combined:{k + 1}"
    return sorted(groups, key=lambda g: g["name"])


# ================================================================================================== the domain
@dataclass
class HeldPart:
    pid: str
    mass_kg: float
    com: np.ndarray                       # world mm
    inertia: np.ndarray                   # kg·m² about the centre of mass
    v: np.ndarray                         # world vertices (mm)
    f: np.ndarray
    box: np.ndarray                       # its reserved box (lo, hi): the contact zone's extent
    axis: int
    neg: bool
    plane: float
    fasteners: int
    bracket: dict
    contact: np.ndarray | None = None     # grid mask
    fixed: np.ndarray | None = None       # grid mask: its bolted voxels
    bolts: np.ndarray | None = None       # (n, 3) world mm, on its target plane


@dataclass
class MultiDomain:
    """Design domain of a bracket that holds several parts (combined: a union of column boxes on one plane; one
    piece: the free space of the enclosure). Same voxel conventions as gd.domain.DesignDomain, with h per axis:
    voxel (i, j, k) has its centre at origin + (i + ½, j + ½, k + ½) · h."""
    name: str
    kind: str                             # "combined" | "one_piece"
    origin: np.ndarray
    h: np.ndarray                         # (3,) voxel size per axis (mm)
    shape: tuple
    region: np.ndarray                    # voxels that may hold material (inside the boxes / the free space)
    void: np.ndarray                      # ~region, the part interiors and their margins
    fixed: np.ndarray                     # bolted voxels (passive solid)
    contact: np.ndarray                   # contact voxels of every held part (passive solid)
    parts: list
    material: dict
    vol_frac: float = 0.05
    boxes: list = field(default_factory=list)        # combined: [{name, role, part, box (6,)}] certified boxes
    bits: np.ndarray | None = None                  # combined: per voxel, the boxes containing it (bit k = box k)
    boss: np.ndarray | None = None
    plate: np.ndarray | None = None
    skin: np.ndarray | None = None
    axis: int | None = None               # combined: the one bolted plane
    neg: bool | None = None
    plane_mm: float | None = None
    notes: list = field(default_factory=list)
    kept_brackets: list = field(default_factory=list)   # one piece: parts that keep their own bracket (corner rail)

    # -- the DesignDomain interface the FE helpers use
    @property
    def part_mass_kg(self) -> float:
        return float(sum(p.mass_kg for p in self.parts))

    def passive_solid(self) -> np.ndarray:
        out = self.fixed | self.contact
        for extra in (self.boss, self.plate, self.skin):
            if extra is not None:
                out = out | extra
        return out & ~self.void

    def design(self) -> np.ndarray:
        return ~(self.void | self.passive_solid())

    def centres(self) -> np.ndarray:
        idx = np.stack(np.meshgrid(*[np.arange(n) for n in self.shape], indexing="ij"), axis=-1)
        return self.origin + (idx + 0.5) * self.h

    @property
    def bolts(self) -> np.ndarray:
        return np.vstack([p.bolts for p in self.parts if p.bolts is not None and len(p.bolts)]) \
            if any(p.bolts is not None and len(p.bolts) for p in self.parts) else np.zeros((0, 3))

    def load_cases(self) -> list[dict]:
        """The three FE reference cases: every held part's mass × 68 g along x, y, z at its centre of mass (all parts
        at once) and 68 g on the bracket itself."""
        out = []
        for k, ax in enumerate("xyz"):
            e = np.eye(3)[k]
            out.append({"name": f"{LIMIT_G:.0f} g {ax}", "part_forces_n": [-p.mass_kg * LIMIT_G * G0 * 1e-3 * e
                                                                            for p in self.parts],
                        "body_accel_mm_s2": -LIMIT_G * G0 * e})
        return out

    def contact_voxel_forces(self, case: dict) -> np.ndarray:
        """(nx, ny, nz, 3) N: each part's force at its centre of mass spread over its own contact voxels, RBE3-like
        (gd.domain.DesignDomain.contact_voxel_forces per part)."""
        out = np.zeros(tuple(self.shape) + (3,))
        for p, F in zip(self.parts, case["part_forces_n"]):
            idx = np.argwhere(p.contact)
            if not len(idx):
                continue
            x = self.origin + (idx + 0.5) * self.h
            c = x.mean(axis=0)
            r = x - c
            f = np.repeat(np.asarray(F, float)[None] / len(x), len(x), axis=0)
            J = np.trace(r.T @ r) * np.eye(3) - r.T @ r
            M = np.cross(np.asarray(p.com, float) - c, np.asarray(F, float))
            f += np.cross(np.linalg.lstsq(J, M, rcond=None)[0], r)
            out[tuple(idx.T)] += f
        return out


# ------------------------------------------------------------------------------------------------- part geometry
def _part_world(rec, orient: int, t):
    from ..core.rotations import ROTATIONS_F
    R = ROTATIONS_F[int(orient)]
    return np.asarray(rec.v, float) @ R.T + np.asarray(t, float), np.asarray(rec.f, np.int64)


def _mass_props(v, f, mass_kg: float):
    from ..massprops.core import integrate
    up = integrate(np.asarray(v, float), np.asarray(f, np.int64))
    return np.asarray(up.com_mm, float), mass_kg * (np.asarray(up.j_mm5, float) / up.volume_mm3) * 1e-6


def _cell_boxes_hit(dom_origin, h, shape, pts: np.ndarray, grow) -> np.ndarray:
    """Voxels whose cell grown by `grow` (mm, per axis) contains at least one of the points."""
    out = np.zeros(shape, bool)
    if not len(pts):
        return out
    h = np.asarray(h, float)
    g = np.broadcast_to(np.asarray(grow, float), (3,))
    lo = np.floor((pts - g - dom_origin) / h).astype(np.int64)
    hi = np.floor((pts + g - dom_origin) / h).astype(np.int64)
    span = int(max(1, (hi - lo).max() + 1))
    for dx in range(span):
        for dy in range(span):
            for dz in range(span):
                q = lo + np.array([dx, dy, dz])
                ok = np.all(q <= hi, axis=1) & np.all(q >= 0, axis=1) & np.all(q < np.array(shape), axis=1)
                if ok.any():
                    out[tuple(q[ok].T)] = True
    return out


def part_masks(origin, h, shape, v, f, gap: float, contact_reach: float):
    """For one part on a grid: (inside — voxel centres inside the part, near — cells that come within `gap` of its
    surface, close — cells within `contact_reach` of its surface). Cells whose grown box misses the part's bounding
    box are never near (exact for a flat side: the 3 mm mounting gap holds one voxel layer); within it the surface is
    sampled at a quarter of the smallest voxel."""
    from ..geometry.mesh import ray_parity_inside
    from ..geometry.voxel import surface_samples
    h = np.asarray(h, float)
    lo, hi = v.min(0), v.max(0)
    s = float(h.min()) / 4.0
    samples = surface_samples(v, f, s)
    near = _cell_boxes_hit(origin, h, shape, samples, gap)
    close = _cell_boxes_hit(origin, h, shape, samples, contact_reach)
    idx = np.stack(np.meshgrid(*[np.arange(n) for n in shape], indexing="ij"), axis=-1).reshape(-1, 3)
    cen = origin + (idx + 0.5) * h
    cand = np.all((cen >= lo) & (cen <= hi), axis=1)
    inside = np.zeros(len(cen), bool)
    if cand.any():
        inside[cand] = ray_parity_inside(cen[cand], v, f) > 0.5
    return inside.reshape(shape), near, close


def held_part(b: dict, rec, pose, mass_kg: float) -> HeldPart:
    o, t = pose
    v, f = _part_world(rec, o, t)
    com, inertia = _mass_props(v, f, mass_kg)
    return HeldPart(b["pid"], float(mass_kg), com, inertia, v, f, np.asarray(b["reserve"], float), int(b["axis"]),
                    bool(b["neg"]), float(b["plane_mm"]), int(b.get("fasteners", 3) or 3), b)


# ------------------------------------------------------------------------------------------------- bolts
def member_bolts(dom: MultiDomain, p: HeldPart, n: int):
    """The part's own bolt pattern (gd.bolts.pattern_2d on its bolted voxels' footprint, each bolt moved onto a bolted
    voxel if needed) and its bosses (voxels within BOSS_RADIUS in plane, within FLANGE_T of the plane, inside its
    reserved box)."""
    from . import bolts as B
    ax = p.axis
    b_, c_ = B.in_plane_axes(ax)
    cells = np.argwhere(p.fixed)
    if not len(cells):
        return np.zeros((0, 3)), np.zeros(dom.shape, bool)
    cen = dom.origin + (cells + 0.5) * dom.h
    lo = np.array([cen[:, b_].min(), cen[:, c_].min()]) - 0.5 * dom.h[[b_, c_]]
    hi = np.array([cen[:, b_].max(), cen[:, c_].max()]) + 0.5 * dom.h[[b_, c_]]
    pts = B.pattern_2d(lo, hi, n)
    fc = cen[:, [b_, c_]]
    out = []
    for q in pts:
        d = np.linalg.norm(fc - q, axis=1)
        k = int(np.argmin(d))
        out.append(q if d[k] <= 0.5 * float(np.linalg.norm(dom.h[[b_, c_]])) + 1e-9 else fc[k])
    bolts = np.zeros((len(out), 3))
    for i, q in enumerate(out):
        bolts[i, b_], bolts[i, c_], bolts[i, ax] = q[0], q[1], p.plane
    allc = dom.centres()
    dist_plane = np.abs(allc[..., ax] - p.plane) - 0.5 * dom.h[ax]           # of each voxel's near face
    rr = np.full(dom.shape, np.inf)
    for q in bolts:
        rr = np.minimum(rr, np.hypot(allc[..., b_] - q[b_], allc[..., c_] - q[c_]))
    inbox = np.all((allc >= p.box[:3]) & (allc <= p.box[3:]), axis=-1)
    boss = (dist_plane < B.FLANGE_T - 1e-9) & (rr <= B.BOSS_RADIUS) & inbox & dom.region & ~dom.void & \
        ~dom.fixed & ~dom.contact
    return bolts, boss


# ------------------------------------------------------------------------------------------------- combined
def _snap_in(lo: float, hi: float, o: float, h: float) -> tuple[int, int]:
    """Cell index range [i0, i1) of the cells lying inside [lo, hi] (1 nm tolerance)."""
    i0 = int(np.ceil((lo - o) / h - 1e-9))
    i1 = int(np.floor((hi - o) / h + 1e-9))
    return i0, i1


def combined_domain(group: dict, records: dict, poses: dict, masses: dict, h: float, material: str | None = None,
                    vol_frac: float = 0.05, name: str | None = None) -> MultiDomain:
    """Design domain of one combined bracket (combine_groups): the voxels inside its member boxes and its bridging boxes
    snapped to the grid, eroded at re-entrant corners (see the module docstring), the parts' interiors and contact gaps
    void, a contact zone per part inside its own box, the bolted layer on the target plane, the bolt pattern of each
    member on its own bolted face."""
    ax, neg, plane = int(group["axis"]), bool(group["neg"]), float(group["plane_mm"])
    members = group["members"]
    H = np.full(3, float(h))
    rs = np.array([m["reserve"] for m in members], float)
    lo, hi = rs[:, :3].min(0), rs[:, 3:].max(0)
    origin = lo.copy()
    shape = [int(np.ceil((hi[k] - lo[k]) / h - 1e-9)) for k in range(3)]
    depth = float(np.max(rs[:, 3 + ax] - rs[:, ax]))
    n_ax = int(np.ceil(depth / h - 1e-9))
    shape[ax] = n_ax
    origin[ax] = plane if neg else plane - n_ax * h
    shape = tuple(int(max(1, s)) for s in shape)
    boxes = []
    for m in members:
        boxes.append({"name": m["name"], "role": "member", "part": m["pid"], "box": np.asarray(m["reserve"], float)})
    # bridges snapped to the grid: one voxel into each member box beyond its last full voxel, over the shared width
    member_idx = {}
    for m in members:
        r = np.asarray(m["reserve"], float)
        member_idx[m["pid"]] = [_snap_in(r[k], r[3 + k], origin[k], h) for k in range(3)]
    for k, br in enumerate(group["bridges"]):
        g = np.asarray(br["gap_box"], float)
        s, w = int(br["across"]), int(br["along"])
        a, b = br["ends"]
        ia, ib = member_idx[a], member_idx[b]
        lo_m, hi_m = (ia, ib) if ia[s][1] <= ib[s][0] + 1 else (ib, ia)
        i_s0 = lo_m[s][1] - 1
        i_s1 = hi_m[s][0] + 1
        i_w0, i_w1 = _snap_in(g[w], g[3 + w], origin[w], h)
        n_u = int(np.floor(abs(g[3 + ax] - g[ax]) / h + 1e-9))
        if i_s1 - i_s0 < 2 or i_w1 - i_w0 < 2 or n_u < 1:
            continue
        idx_lo, idx_hi = np.zeros(3, int), np.zeros(3, int)
        idx_lo[s], idx_hi[s] = i_s0, i_s1
        idx_lo[w], idx_hi[w] = i_w0, i_w1
        if neg:
            idx_lo[ax], idx_hi[ax] = 0, n_u
        else:
            idx_lo[ax], idx_hi[ax] = shape[ax] - n_u, shape[ax]
        bl = origin + idx_lo * h
        bh = origin + idx_hi * h
        if neg:
            bl[ax] = plane                                    # exactly on the plane (no rounding)
        else:
            bh[ax] = plane
        boxes.append({"name": f"{name or group['name']}/bridge{k}", "role": "bridge", "part": None,
                      "ends": [a, b], "box": np.concatenate([bl, bh])})
    # which boxes contain each voxel (cell inside the box, 1 nm tolerance)
    cen = origin + (np.stack(np.meshgrid(*[np.arange(n) for n in shape], indexing="ij"), axis=-1) + 0.5) * h
    bits = np.zeros(shape, np.int64)
    for k, b in enumerate(boxes):
        r = b["box"]
        inside = np.all((cen - 0.5 * h >= r[:3] - 1e-9) & (cen + 0.5 * h <= r[3:] + 1e-9), axis=-1)
        bits[inside] |= (1 << k)
    region = bits != 0
    parts = [held_part(m, records[m["pid"]], poses[m["pid"]], masses.get(m["pid"]) or 0.2) for m in members]
    void = ~region
    contact = np.zeros(shape, bool)
    for k, p in enumerate(parts):
        inside, near, close = part_masks(origin, H, shape, p.v, p.f, CONTACT_GAP, CONTACT_GAP + 1.5 * h)
        void |= inside | near
        p.contact = close & ((bits & (1 << k)) != 0)          # in its own member box only
    for p in parts:
        p.contact &= ~void
        contact |= p.contact
    first = np.zeros(shape, bool)
    sl = [slice(None)] * 3
    sl[ax] = 0 if neg else shape[ax] - 1
    first[tuple(sl)] = True
    fixed = first & ~void
    contact &= ~fixed
    dom = MultiDomain(name or group["name"], "combined", origin, H, shape, region, void, fixed, contact, parts,
                      fea_material(material), vol_frac, boxes=boxes, bits=bits, axis=ax, neg=neg, plane_mm=plane)
    eroded = erode_corners(dom)
    for k, p in enumerate(parts):
        p.contact &= ~dom.void & ~dom.fixed
        p.fixed = dom.fixed & ((bits & (1 << k)) != 0)
    dom.contact = np.any([p.contact for p in parts], axis=0) if parts else contact
    dropped = drop_unreachable(dom)
    boss = np.zeros(shape, bool)
    for p in parts:
        p.bolts, b_ = member_bolts(dom, p, p.fasteners)
        boss |= b_
    dom.boss = boss if boss.any() else None
    dom.notes.append(f"{len(members)} members, {sum(1 for b in boxes if b['role'] == 'bridge')} bridges; "
                     f"{eroded} voxels removed at re-entrant corners; {dropped} unreachable contact voxels dropped")
    return dom


def erode_corners(dom: MultiDomain) -> int:
    """Remove region voxels until the region voxels of every 2 × 2 × 2 block lie in one common box (each block keeps
    the voxels of the box that holds most of them). Returns the number removed. Blocks reaching outside the grid count
    the outside as non-region (the marching cubes pad)."""
    bits = np.where(dom.region & ~dom.void, dom.bits, 0)
    nb = len(dom.boxes)
    removed = 0
    for _ in range(64):
        P = np.pad(bits, 1)
        sx, sy, sz = (n + 1 for n in bits.shape)
        blocks = [P[i:i + sx, j:j + sy, k:k + sz] for i in (0, 1) for j in (0, 1) for k in (0, 1)]
        common = np.full((sx, sy, sz), -1, np.int64)
        nreg = np.zeros((sx, sy, sz), np.int16)
        for b in blocks:
            common &= np.where(b != 0, b, -1)
            nreg += b != 0
        bad = (nreg >= 2) & (common == 0)
        if not bad.any():
            break
        cnt = np.zeros((nb,) + bad.shape, np.int16)
        for k in range(nb):
            m = 1 << k
            for b in blocks:
                cnt[k] += (b & m) != 0
        best = np.argmax(cnt, axis=0)
        keepbit = np.where(bad, np.left_shift(1, best), -1)
        kill = np.zeros(P.shape, bool)
        for (i, j, k), b in zip([(i, j, k) for i in (0, 1) for j in (0, 1) for k in (0, 1)], blocks):
            bad_here = bad & (b != 0) & ((b & keepbit) == 0)
            kill[i:i + sx, j:j + sy, k:k + sz] |= bad_here
        kill = kill[1:-1, 1:-1, 1:-1] & (bits != 0)
        removed += int(kill.sum())
        bits[kill] = 0
    lost = (bits == 0) & dom.region & ~dom.void
    dom.void = dom.void | lost
    dom.fixed &= ~dom.void
    dom.contact &= ~dom.void
    return removed


def drop_unreachable(dom: MultiDomain) -> int:
    """Contact voxels that no solid can join to the bolted layer within the region (cut off by the part's own shape:
    gd.domain.drop_unreachable_contact) are dropped; 6-connected."""
    from scipy import ndimage
    free = ~dom.void
    lab, _ = ndimage.label(free)
    reach = np.unique(lab[dom.fixed & free])
    reach = reach[reach > 0]
    n = 0
    for p in dom.parts:
        keep = p.contact & np.isin(lab, reach)
        n += int(p.contact.sum() - keep.sum())
        p.contact = keep
    dom.contact = np.any([p.contact for p in dom.parts], axis=0) if dom.parts else dom.contact
    return n


# ------------------------------------------------------------------------------------------------- load path
def load_path(dom: MultiDomain, solid: np.ndarray) -> dict:
    """The user's rule — no part held only by another part: every contact voxel of every held part lies in a
    6-connected component of the solid that contains bolted (chassis-fixed) voxels. Parts are void, so a path through
    another part does not count. Returns {pid: {"ok", "loose" contact voxels, "contact" voxels}}."""
    from scipy import ndimage
    s = np.asarray(solid, bool) & ~dom.void
    lab, _ = ndimage.label(s)
    fixed_labels = np.unique(lab[dom.fixed & s])
    fixed_labels = fixed_labels[fixed_labels > 0]
    out = {}
    for p in dom.parts:
        c = p.contact & s
        loose = c & ~np.isin(lab, fixed_labels)
        n_c = int(p.contact.sum())
        missing = int((p.contact & ~s).sum())
        out[p.pid] = {"ok": bool(n_c > 0 and not loose.any() and missing == 0), "contact": n_c,
                      "loose": int(loose.sum()), "missing": missing}
    return out


# ------------------------------------------------------------------------------------------------- one piece
def one_piece_grid(inner_lo, inner_hi, end_plate_parts: bool) -> tuple[np.ndarray, np.ndarray, tuple]:
    """(origin, h (3,), shape) of a grid lying exactly on all six inner planes: h_k = L_k / n_k with n_k the fewest
    voxels keeping h ≤ 2.7 mm across the side walls (x, y) and ≤ 4 mm along z (≤ 2.7 mm if a part is mounted on an
    end plate)."""
    lo, hi = np.asarray(inner_lo, float), np.asarray(inner_hi, float)
    L = hi - lo
    hmax = np.array([ONE_PIECE_H_WALL, ONE_PIECE_H_WALL, ONE_PIECE_H_WALL if end_plate_parts else ONE_PIECE_H_LONG])
    n = np.ceil(L / hmax - 1e-9).astype(int)
    return lo.copy(), L / n, tuple(int(x) for x in n)


def _cube_near_boxes(origin, h, shape, boxes, clear: float) -> np.ndarray:
    """Voxels whose 2h-cube (the voxel grown by h/2 on every side: every marching-cubes triangle of the voxel lies in
    it) comes within `clear` of one of the boxes (box arithmetic: the larger axis gap below `clear`)."""
    h = np.asarray(h, float)
    out = np.zeros(shape, bool)
    axes = [origin[k] + (np.arange(shape[k]) + 0.5) * h[k] for k in range(3)]
    for b in boxes:
        b = np.asarray(b, float)
        g = []
        for k in range(3):
            c = axes[k]
            g.append(np.maximum(b[k] - (c + h[k]), (c - h[k]) - b[3 + k]))     # per axis gap of the 2h-cube
        gap = np.maximum(np.maximum(g[0][:, None, None], g[1][None, :, None]), g[2][None, None, :])
        out |= gap < clear
    return out


def one_piece_domain(brackets: list[dict], records: dict, poses: dict, masses: dict, inner, keepouts: list,
                     nonheld_boxes: dict, material: str | None = None, vol_frac: float = 0.05,
                     name: str = "one piece") -> MultiDomain:
    """Design domain of the one piece: every part with a bracket on a wall or an end plate is held (a part on a corner
    rail keeps its own bracket, which then is a keep-out). `keepouts`: [(name, kind, box)] of the layout (rails, rods,
    stack reserve, harness, standoffs); `nonheld_boxes`: {pid: (6,) bounding box} of every part the piece does not hold
    (the PC/104 boards, rail-mounted parts). See the module docstring for the rules."""
    held_b = [b for b in brackets if (b.get("target_kind") or "wall") in ("wall", "end_plate")]
    kept_b = [b for b in brackets if b not in held_b]
    origin, h, shape = one_piece_grid(inner[0], inner[1], any(int(b["axis"]) == 2 for b in held_b))
    clear = CLEAR + SLACK
    obstacles = [np.asarray(r, float) for _, _, r in keepouts]
    obstacles += [np.asarray(b["reserve"], float) for b in kept_b]
    obstacles += [np.asarray(r, float) for r in nonheld_boxes.values()]
    void = _cube_near_boxes(origin, h, shape, obstacles, clear)
    region = ~void
    parts = [held_part(b, records[b["pid"]], poses[b["pid"]], masses.get(b["pid"]) or 0.2) for b in held_b]
    allc = origin + (np.stack(np.meshgrid(*[np.arange(n) for n in shape], indexing="ij"), axis=-1) + 0.5) * h
    contact = np.zeros(shape, bool)
    fixed = np.zeros(shape, bool)
    margin_void = np.zeros(shape, bool)
    reach = CONTACT_GAP + 1.5 * float(h.max())
    sample_err = float(h.min()) / 4.0 / np.sqrt(2.0)
    zones = []
    for p in parts:
        inside, near, close = part_masks(origin, h, shape, p.v, p.f, CONTACT_GAP, reach)
        _, far, _ = part_masks(origin, h, shape, p.v, p.f, HELD_MARGIN + sample_err, reach)
        inbox = np.all((allc >= p.box[:3] - 1e-9) & (allc <= p.box[3:] + 1e-9), axis=-1)
        # the skirt: in the mounting gap (target plane → part side) around the footprint, the piece may pass the
        # part's edges (else every pad would be sealed in by the margin: the gap is 3 mm)
        lat = [a for a in range(3) if a != p.axis]
        grow = HELD_MARGIN + float(h[lat].max())
        side = p.plane + (1.0 if p.neg else -1.0) * float(p.bracket.get("gap_mm", 0.0))
        u = allc[..., p.axis]
        in_gap = (u >= min(p.plane, side) - 1e-9) & (u <= max(p.plane, side) + 1e-9)
        skirt = in_gap & np.all((allc[..., lat] >= p.box[lat] - grow) &
                                (allc[..., lat] <= p.box[[3 + a for a in lat]] + grow), axis=-1)
        zones.append((inside, near, close, far, inbox | skirt))
        void |= inside | near
    for p, (inside, near, close, far, zone) in zip(parts, zones):
        margin_void |= far & ~zone                           # 1.2 mm from the part outside its own contact zone
    void |= margin_void
    for p, (inside, near, close, far, zone) in zip(parts, zones):
        inbox = np.all((allc >= p.box[:3] - 1e-9) & (allc <= p.box[3:] + 1e-9), axis=-1)
        p.contact = close & inbox & ~void
        k = np.arange(shape[p.axis])
        first = (k == 0) if p.neg else (k == shape[p.axis] - 1)
        sl = [None, None, None]
        sl[p.axis] = slice(None)
        lat = [a for a in range(3) if a != p.axis]
        foot = np.all((allc[..., lat] >= p.box[lat] - 1e-9) & (allc[..., lat] <= p.box[[3 + a for a in lat]] + 1e-9),
                      axis=-1)
        p.fixed = np.broadcast_to(first[tuple(sl)], shape) & foot & ~void
        fixed |= p.fixed
    for p in parts:
        p.contact &= ~fixed | p.fixed                         # a pad voxel is bolted and holds its part
        contact |= p.contact
    dom = MultiDomain(name, "one_piece", origin, h, shape, region, void | ~region, fixed, contact, parts,
                      fea_material(material), vol_frac)
    dropped = drop_unreachable(dom)
    boss = np.zeros(shape, bool)
    for p in parts:
        p.bolts, b_ = member_bolts(dom, p, p.fasteners)
        boss |= b_
    dom.boss = boss if boss.any() else None
    dom.notes.append(f"grid {shape[0]} × {shape[1]} × {shape[2]} voxels of {h[0]:.3f} × {h[1]:.3f} × {h[2]:.3f} mm on "
                     f"the inner planes; {int((~dom.void).sum())} voxels free; {len(parts)} parts held, "
                     f"{len(kept_b)} keep their own bracket (corner rail); {dropped} unreachable contact voxels dropped")
    dom.kept_brackets = [b["pid"] for b in kept_b]
    return dom


# ------------------------------------------------------------------------------------------------- one piece: join
def join(dom: MultiDomain, solid: np.ndarray, width: int = 1) -> tuple[np.ndarray, list]:
    """Join the solid into one 6-connected piece: repeatedly the shortest path (in voxels) through the free space from
    the largest component to the nearest other one becomes solid, grown to `width` voxels. Returns (solid, joins:
    [{voxels, from, to}])."""
    import scipy.sparse as sp
    from scipy import ndimage
    from scipy.sparse.csgraph import dijkstra
    s = np.asarray(solid, bool) & ~dom.void
    free = ~dom.void
    idx = -np.ones(dom.shape, np.int64)
    fi = np.argwhere(free)
    idx[tuple(fi.T)] = np.arange(len(fi))
    rows, cols = [], []
    for k in range(3):
        a = [slice(None)] * 3
        b = [slice(None)] * 3
        a[k], b[k] = slice(0, -1), slice(1, None)
        ia, ib = idx[tuple(a)], idx[tuple(b)]
        m = (ia >= 0) & (ib >= 0)
        rows.append(ia[m])
        cols.append(ib[m])
    r, c = np.concatenate(rows), np.concatenate(cols)
    G = sp.csr_matrix((np.ones(len(r)), (r, c)), shape=(len(fi), len(fi)))
    G = G + G.T
    joins = []
    for _ in range(200):
        lab, n = ndimage.label(s)
        if n <= 1:
            break
        sizes = np.bincount(lab.ravel())[1:]
        main = int(np.argmax(sizes)) + 1
        src = idx[lab == main]
        src = src[src >= 0]
        dist, pred, _ = dijkstra(G, directed=False, indices=src, min_only=True, return_predecessors=True)
        other = (lab > 0) & (lab != main)
        oi = idx[other]
        oi = oi[oi >= 0]
        if not len(oi) or not np.isfinite(dist[oi]).any():
            break
        tgt = int(oi[np.argmin(dist[oi])])
        path = [tgt]
        while pred[path[-1]] >= 0:
            path.append(int(pred[path[-1]]))
        cells = fi[np.array(path)]
        add = np.zeros(dom.shape, bool)
        add[tuple(cells.T)] = True
        if width > 1:
            add = ndimage.binary_dilation(add, iterations=width - 1) & free
        new = int((add & ~s).sum())
        s |= add
        joins.append({"voxels": new, "to": int(lab[tuple(cells[0])])})
    return s, joins
