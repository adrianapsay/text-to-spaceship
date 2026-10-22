"""Bracket geometry for Manufacturable Design (Addendum 1.5). All shapes and rules are ASSUMED concepts:
"manufacturing concept — assumed cost model, not a quote; brackets not stress-analysed".

Every bracket is a real solid: it gets mass properties, is checked against every other part at the exact-mesh
level (FCL distance + containment probe), and is exported as STL. Metal-AM brackets are conformal: a 2 mm shell
that follows the part surface at a 0.3 mm gap inside the mounting zone, joined by ribs to a 2 mm plate on the wall,
end plate, rail or deck (a signed-distance level set meshed with manifold3d).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..core.rotations import ROTATIONS_F
from .rules import CLAMP_MASS_KG, COST, FASTENER_MASS_KG, MATERIAL, SPACER_SET_MASS_KG

AM_GAP = 0.3          # mm between the AM shell and the part surface (ASSUMED)
AM_SHELL = 2.0        # mm shell thickness (≥ 1.0 mm AM wall rule)
AM_PLATE = 2.0
AM_RIB = 2.5
SHEET_T = 1.5
WASHER = 7.0          # mm square envelope of an M3 spacer washer stack
BUILD_VOLUME = (250.0, 250.0, 325.0)   # mm, a common laser powder-bed machine (ASSUMED)
STEEL = 7850.0


@dataclass
class Bracket:
    id: str
    for_part: str
    mount_type: str
    process: str
    material: str
    meshes: list                       # [(v (n,3) world mm, f (m,3))]
    mass_kg: float
    com_mm: np.ndarray
    inertia_kgm2: np.ndarray
    cost_rel: float
    fasteners: int
    envelope: list | None = None
    am: dict = field(default_factory=dict)     # AM facts (volume, overhang, bbox) for the rule report
    label: str = ""
    hosts: tuple = ()                          # parts it may touch (default: for_part)

    def host_set(self) -> set:
        return set(self.hosts) | {self.for_part}


def box_mesh(lo, hi):
    x0, y0, z0 = lo
    x1, y1, z1 = hi
    v = np.array([[x0, y0, z0], [x1, y0, z0], [x1, y1, z0], [x0, y1, z0], [x0, y0, z1], [x1, y0, z1], [x1, y1, z1],
                  [x0, y1, z1]], float)
    f = np.array([[0, 2, 1], [0, 3, 2], [4, 5, 6], [4, 6, 7], [0, 1, 5], [0, 5, 4],
                  [1, 2, 6], [1, 6, 5], [2, 3, 7], [2, 7, 6], [3, 0, 4], [3, 4, 7]])
    return v, f


def _box_props(boxes, density):
    """Mass, COM, inertia (kg, mm, kg·m² about the COM) of disjoint boxes."""
    items = []
    for lo, hi in boxes:
        d = np.asarray(hi, float) - np.asarray(lo, float)
        m = density * float(np.prod(d)) * 1e-9
        c = 0.5 * (np.asarray(lo, float) + np.asarray(hi, float))
        i = m / 12 * np.diag([d[1] ** 2 + d[2] ** 2, d[0] ** 2 + d[2] ** 2, d[0] ** 2 + d[1] ** 2]) * 1e-6
        items.append((m, c, i))
    return _combine(items)


def _combine(items):
    m = sum(x[0] for x in items)
    if m <= 0:
        return 0.0, np.zeros(3), np.zeros((3, 3))
    c = sum(x[0] * np.asarray(x[1]) for x in items) / m
    i = np.zeros((3, 3))
    for mi, ci, ii in items:
        d = (np.asarray(ci) - c) * 1e-3
        i += ii + mi * (d @ d * np.eye(3) - np.outer(d, d))
    return float(m), c, i


def _mesh_props(v, f, density):
    from ..massprops.core import integrate
    up = integrate(v, f)
    m = density * up.volume_mm3 * 1e-9
    return float(m), np.asarray(up.com_mm), m * (up.j_mm5 / up.volume_mm3) * 1e-6, float(up.volume_mm3)


def _fastener_items(points):
    return [(FASTENER_MASS_KG, np.asarray(p, float), np.zeros((3, 3))) for p in points]


def _split(env, ax, neg, frac_b=0.6, frac_c=0.6):
    """Centred sub-footprint of an envelope box (fractions of its two in-plane extents)."""
    env = np.asarray(env, float)
    b, c = [k for k in range(3) if k != ax]
    lo, hi = env[:3].copy(), env[3:].copy()
    for k, fr in ((b, frac_b), (c, frac_c)):
        mid, half = 0.5 * (lo[k] + hi[k]), 0.5 * fr * (hi[k] - lo[k])
        lo[k], hi[k] = mid - half, mid + half
    return lo, hi


def _corners(lo, hi, ax, inset):
    b, c = [k for k in range(3) if k != ax]
    pts = []
    for sb in (lo[b] + inset, hi[b] - inset):
        for sc in (lo[c] + inset, hi[c] - inset):
            p = 0.5 * (lo + hi)
            p[b], p[c] = sb, sc
            pts.append(p)
    return pts


def simple_bracket(bid, pid, mount) -> Bracket:
    """Direct (washers), machined block, sheet Z-bracket, tube clamp — from the mount's envelope box."""
    env = np.asarray(mount["envelope"], float)
    ax, neg = mount["axis"], mount["neg"]
    proc = mount["process"]
    lo, hi = env[:3], env[3:]
    part_end = hi[ax] if neg else lo[ax]               # the envelope face on the part side
    if proc == "direct":
        boxes = []
        for p in _corners(lo, hi, ax, WASHER / 2 + 1.0)[:4]:
            blo, bhi = p - WASHER / 2, p + WASHER / 2
            blo[ax], bhi[ax] = lo[ax], hi[ax]
            boxes.append((blo, bhi))
        m, c, i = _box_props(boxes, STEEL)
        meshes = [box_mesh(a, b) for a, b in boxes]
        cost = mount["fasteners"] * COST["fastener"]
        label = f"{mount['fasteners']} × M3 with spacer washers"
        mat = "steel fasteners / washers (ASSUMED)"
    elif proc == "machined":
        blo, bhi = _split(env, ax, neg, 0.6, 0.6)
        boxes = [(blo, bhi)]
        m, c, i = _box_props(boxes, MATERIAL["machined"][1])
        vol = float(np.prod(bhi - blo)) / 1e3
        meshes = [box_mesh(blo, bhi)]
        cost = COST["machined"] + COST["machined_per_cm3"] * vol + mount["fasteners"] * COST["fastener"]
        label = f"machined spacer block {vol:.1f} cm³"
        mat = MATERIAL["machined"][0]
    elif proc == "sheet":
        flo, fhi = _split(env, ax, neg, 0.5, 0.6)
        t = SHEET_T
        if neg:      # target at lo[ax], part at hi[ax]
            f_part = (np.r_[flo[:ax], [hi[ax] - t], flo[ax + 1:]], fhi.copy())
            f_wall = (flo.copy(), np.r_[fhi[:ax], [lo[ax] + t], fhi[ax + 1:]])
        else:
            f_part = (flo.copy(), np.r_[fhi[:ax], [lo[ax] + t], fhi[ax + 1:]])
            f_wall = (np.r_[flo[:ax], [hi[ax] - t], flo[ax + 1:]], fhi.copy())
        b = [k for k in range(3) if k != ax][0]
        wlo, whi = flo.copy(), fhi.copy()
        wlo[ax], whi[ax] = lo[ax] + t, hi[ax] - t
        whi[b] = wlo[b] + t                               # web: one plate across the gap
        boxes = [f_part, f_wall] + ([(wlo, whi)] if whi[ax] > wlo[ax] else [])
        m, c, i = _box_props(boxes, MATERIAL["sheet"][1])
        meshes = [box_mesh(a, bb) for a, bb in boxes]
        cost = COST["sheet"] + 2 * COST["sheet_per_bend"] + mount["fasteners"] * COST["fastener"]
        label = "sheet-metal Z-bracket, 2 bends, 1.5 mm"
        mat = MATERIAL["sheet"][0]
    else:            # catalogue tube clamp: generic envelope, catalogue mass
        blo, bhi = _split(env, ax, neg, 0.35, 0.9)
        meshes = [box_mesh(blo, bhi)]
        m, c, i = CLAMP_MASS_KG, 0.5 * (blo + bhi), np.zeros((3, 3))
        d = (bhi - blo)
        i = m / 12 * np.diag([d[1] ** 2 + d[2] ** 2, d[0] ** 2 + d[2] ** 2, d[0] ** 2 + d[1] ** 2]) * 1e-6
        extra = COST["sheet"] + 2 * COST["sheet_per_bend"] if "sheet" in mount["mount_type"] else 0.0
        cost = COST["catalogue"] + extra + mount["fasteners"] * COST["fastener"]
        label = "generic tube clamp (catalogue envelope)" + (" on a sheet bracket" if extra else "")
        mat = MATERIAL["catalogue"][0]
    fpts = _corners(lo, hi, ax, 4.0)[:mount["fasteners"]]
    m2, c2, i2 = _combine([(m, c, i)] + _fastener_items(fpts))
    _ = part_end
    return Bracket(bid, pid, mount["mount_type"], proc if proc != "direct" else "direct", mat, meshes, m2, c2, i2,
                   float(cost), int(mount["fasteners"]), env.tolist(), label=label)


try:
    from numba import njit as _njit
except Exception:  # noqa: BLE001
    _njit = None


def _am_sdf_py(x, y, z, s, glo, h, reg_lo, reg_hi, target, ax, neg, b, rib1, rib2, gap, shell_t, plate_t, rib_t, obs):
    """Signed distance of the AM bracket (positive inside): (shell ∪ plate ∪ ribs) ∩ region ∖ obstacles; `s` is
    the part's signed distance (positive outside) on a regular grid, trilinearly interpolated; `obs` are the other
    parts' certified boxes, already grown by the required clearance."""
    p0, p1, p2 = x, y, z
    fx = (p0 - glo[0]) / h
    fy = (p1 - glo[1]) / h
    fz = (p2 - glo[2]) / h
    nx, ny, nz = s.shape
    if fx < 0 or fy < 0 or fz < 0 or fx > nx - 1.000001 or fy > ny - 1.000001 or fz > nz - 1.000001:
        sp = 1e3
    else:
        i, j, k = int(fx), int(fy), int(fz)
        tx, ty, tz = fx - i, fy - j, fz - k
        c00 = s[i, j, k] * (1 - tx) + s[i + 1, j, k] * tx
        c10 = s[i, j + 1, k] * (1 - tx) + s[i + 1, j + 1, k] * tx
        c01 = s[i, j, k + 1] * (1 - tx) + s[i + 1, j, k + 1] * tx
        c11 = s[i, j + 1, k + 1] * (1 - tx) + s[i + 1, j + 1, k + 1] * tx
        sp = (c00 * (1 - ty) + c10 * ty) * (1 - tz) + (c01 * (1 - ty) + c11 * ty) * tz
    pv = (p0, p1, p2)
    box = 1e9
    for q in range(3):
        box = min(box, pv[q] - reg_lo[q], reg_hi[q] - pv[q])
    shell = min(sp - gap, gap + shell_t - sp)
    along = (pv[ax] - target) if neg else (target - pv[ax])
    plate = plate_t - along if along >= 0 else along
    rib = max(rib_t / 2 - abs(pv[b] - rib1), rib_t / 2 - abs(pv[b] - rib2))
    rib = min(rib, sp - gap)
    out = min(max(shell, plate, rib), box)
    for q in range(obs.shape[0]):
        dx = max(obs[q, 0] - p0, p0 - obs[q, 3])
        dy = max(obs[q, 1] - p1, p1 - obs[q, 4])
        dz = max(obs[q, 2] - p2, p2 - obs[q, 5])
        if dx > 0 or dy > 0 or dz > 0:
            d = (max(dx, 0.0) ** 2 + max(dy, 0.0) ** 2 + max(dz, 0.0) ** 2) ** 0.5
        else:
            d = max(dx, dy, dz)
        out = min(out, d)
    return out


_am_sdf = _njit(cache=True)(_am_sdf_py) if _njit else _am_sdf_py


def world_boxes(rec, o, t) -> np.ndarray:
    """The part's certified G1 boxes in world coordinates (axis-aligned under the 24 orientations)."""
    R = ROTATIONS_F[o]
    b = np.asarray(rec.boxes, float)
    lo = np.minimum(b[:, :3] @ R.T, b[:, 3:] @ R.T) + t
    hi = np.maximum(b[:, :3] @ R.T, b[:, 3:] @ R.T) + t
    return np.concatenate([lo, hi], axis=1)


def am_bracket(bid, pid, rec, o, t, mount, h: float = 1.0, obstacles=None, clearance: float = 0.0) -> Bracket | None:
    """Conformal metal-AM bracket via a signed-distance level set (None if the construction is empty).
    `obstacles`: world boxes of the other parts; the bracket keeps `clearance` from them by construction."""
    import manifold3d
    from scipy.spatial import cKDTree
    from ..geometry.mesh import ray_parity_inside
    from ..geometry.voxel import surface_samples
    env = np.asarray(mount["envelope"], float)
    ax, neg = mount["axis"], mount["neg"]
    R = ROTATIONS_F[o]
    # region: the envelope plus a zone reaching into the part's bounding box, to hug the curved surface
    vw = rec.v @ R.T + t
    plo, phi = vw.min(0), vw.max(0)
    reg_lo, reg_hi = env[:3].copy(), env[3:].copy()
    depth = 12.0
    if neg:
        reg_hi[ax] = min(phi[ax], env[3 + ax] + depth)
    else:
        reg_lo[ax] = max(plo[ax], env[ax] - depth)
    ext = reg_hi - reg_lo
    if np.any(ext <= 2 * h):
        return None
    pad = 2 * h
    glo, ghi = reg_lo - pad, reg_hi + pad
    axes = [np.arange(glo[k], ghi[k] + h * 0.5, h) for k in range(3)]
    G = np.stack(np.meshgrid(*axes, indexing="ij"), axis=-1).reshape(-1, 3)
    samples = surface_samples(rec.v, rec.f, h / 2) @ R.T + t
    dist, _ = cKDTree(samples).query(G)
    inside = np.zeros(len(G), bool)
    cand = np.all((G >= plo) & (G <= phi), axis=1) & (dist < 3 * AM_SHELL + 2 * h)   # far points cannot matter
    if cand.any():
        inside[cand] = ray_parity_inside((G[cand] - t) @ R, rec.v, rec.f) > 0.5
    s = np.ascontiguousarray(np.where(inside, -dist, dist).reshape([len(a) for a in axes]))   # >0 outside the part
    target = env[ax] if neg else env[3 + ax]                                  # wall / rail / deck plane
    b = [k for k in range(3) if k != ax][0]
    rib1 = reg_lo[b] + 0.25 * (reg_hi[b] - reg_lo[b])
    rib2 = reg_lo[b] + 0.75 * (reg_hi[b] - reg_lo[b])
    obs = np.zeros((0, 6))
    if obstacles is not None and len(obstacles):
        ob = np.asarray(obstacles, float)
        ob = np.concatenate([ob[:, :3] - clearance, ob[:, 3:] + clearance], axis=1)
        near = np.all((ob[:, :3] < ghi) & (ob[:, 3:] > glo), axis=1)
        obs = np.ascontiguousarray(ob[near])
    args = (s, np.ascontiguousarray(glo), float(h), np.ascontiguousarray(reg_lo), np.ascontiguousarray(reg_hi),
            float(target), int(ax), bool(neg), int(b), float(rib1), float(rib2), AM_GAP, AM_SHELL, AM_PLATE, AM_RIB,
            obs)

    def f(x, y, z):
        return _am_sdf(x, y, z, *args)
    try:
        man = manifold3d.Manifold.level_set(f, [*glo, *ghi], h)
    except Exception as exc:  # noqa: BLE001
        am_bracket.last_error = repr(exc)
        return None
    if man.is_empty() or man.volume() < 1.0:
        am_bracket.last_error = f"empty level set (volume {man.volume():.3f} mm³)"
        return None
    mesh = man.to_mesh()
    v = np.asarray(mesh.vert_properties)[:, :3].astype(float)
    tri = np.asarray(mesh.tri_verts).astype(np.int64)
    dens = MATERIAL["metal_am"][1]
    m, com, inertia, vol = _mesh_props(v, tri, dens)
    # overhang w.r.t. the best of the six build directions (supports counted in the cost)
    tv = v[tri]
    n = np.cross(tv[:, 1] - tv[:, 0], tv[:, 2] - tv[:, 0])
    area = 0.5 * np.linalg.norm(n, axis=1)
    nn = n / np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-30)
    best = None
    for k in range(3):
        for sg in (1.0, -1.0):
            down = -sg * nn[:, k]                       # cosine with the downward direction
            over = area[down > np.cos(np.radians(45.0))].sum() / area.sum()
            if best is None or over < best[0]:
                best = (float(over), "xyz"[k], sg)
    bb = v.max(0) - v.min(0)
    fpts = [0.5 * (env[:3] + env[3:])]
    fpts[0][ax] = target
    fasteners = mount["fasteners"]
    m2, c2, i2 = _combine([(m, com, inertia)] + _fastener_items(fpts * fasteners))
    cost = COST["metal_am"] + COST["metal_am_per_cm3"] * vol / 1e3 + COST["metal_am_support"] + fasteners * COST["fastener"]
    return Bracket(bid, pid, mount["mount_type"], "metal_am", MATERIAL["metal_am"][0], [(v, tri)], m2, c2, i2, float(cost),
                   int(fasteners), env.tolist(), label="conformal metal-AM bracket (AM)",
                   am={"volume_cm3": vol / 1e3, "overhang_fraction": best[0], "build_axis": f"{'+' if best[2] > 0 else '-'}{best[1]}",
                       "bbox_mm": bb.tolist(), "wall_mm": AM_SHELL, "gap_mm": AM_GAP})


def spacer_set(bid, pid, block, z_lo, z_hi, upper: str | None = None) -> Bracket:
    """4 PC/104 spacers (catalogue) between two stacked boards (`pid` below, `upper` above), at the rod positions
    (±35, ±35) mm; they touch both boards by design."""
    from ..constraints import stage2 as s2
    boxes = []
    for sx in (1, -1):
        for sy in (1, -1):
            c = np.array([sx * s2.ROD_XY, sy * s2.ROD_XY])
            boxes.append((np.r_[c - 2.5, z_lo], np.r_[c + 2.5, z_hi]))
    meshes = [box_mesh(a, b) for a, b in boxes]
    m = SPACER_SET_MASS_KG
    cz = 0.5 * (z_lo + z_hi)
    return Bracket(bid, pid, "PC/104 spacer set (4)", "catalogue", MATERIAL["catalogue"][0], meshes, m,
                   np.array([0.0, 0.0, cz]), np.zeros((3, 3)), COST["catalogue"] + 4 * COST["fastener"], 4,
                   label="4 × PC/104 spacers", hosts=(upper,) if upper else ())


def standoff_items(bid0, standoffs) -> list[Bracket]:
    out = []
    for k, (pid, b) in enumerate(standoffs):
        b = np.asarray(b, float)
        m, c, i = _box_props([(b[:3], b[3:])], MATERIAL["standoff"][1])
        out.append(Bracket(f"{bid0}{k}", pid, "M3 standoff", "standoff", MATERIAL["standoff"][0], [box_mesh(b[:3], b[3:])],
                           m + FASTENER_MASS_KG, c, i, COST["catalogue"] + 2 * COST["fastener"], 2, b.tolist(),
                           label="M3 standoff (edge-mounted board)"))
    return out


def _fcl_obj(v, f):
    import fcl
    m = fcl.BVHModel()
    m.beginModel(len(v), len(f))
    m.addSubModel(np.ascontiguousarray(v, float), np.ascontiguousarray(f, np.int32))
    m.endModel()
    return fcl.CollisionObject(m, fcl.Transform())


def clearance_ok(bracket: Bracket, hosts, geoms: dict, poses, c_req: float) -> tuple[bool, float]:
    """Exact check: every bracket mesh keeps c_req from every part except its hosts (FCL distance + probe)."""
    import fcl
    from ..geometry.mesh import ray_parity_inside
    hosts = {hosts} if isinstance(hosts, str) else set(hosts)
    worst = np.inf
    for v, f in bracket.meshes:
        bo = _fcl_obj(v, f)
        lo, hi = v.min(0), v.max(0)
        for pid, o, t in poses:
            if pid in hosts:
                continue
            g = geoms[pid]
            wb = g.orient_bounds[o]
            plo, phi = wb[:3] + t, wb[3:] + t
            gap = float(np.max(np.maximum(plo - hi, lo - phi)))
            if gap >= c_req + 5.0:
                continue
            po = fcl.CollisionObject(g.fcl_model(), fcl.Transform(ROTATIONS_F[o], np.asarray(t, float)))
            if fcl.collide(bo, po, fcl.CollisionRequest(), fcl.CollisionResult()) > 0:
                return False, -1.0
            d = float(fcl.distance(bo, po, fcl.DistanceRequest(), fcl.DistanceResult()))
            probe = (v[:1] - t) @ ROTATIONS_F[o]
            if ray_parity_inside(probe, g.v, g.f)[0] > 0.5:          # bracket inside the part
                return False, -1.0
            if ray_parity_inside(g.v[:1] @ ROTATIONS_F[o].T + t, v, f)[0] > 0.5:   # part inside the bracket
                return False, -1.0
            worst = min(worst, d)
            if d < c_req - 1e-3:
                return False, d
    return True, worst


def bracket_conflicts(brackets: list, c_req: float) -> list[tuple[str, str, float]]:
    """Exact bracket-to-bracket check (FCL): pairs closer than c_req, unless they share a host part (a spacer set
    and the board above it)."""
    import fcl
    out = []
    bb = [(b, [(v.min(0), v.max(0), v, f) for v, f in b.meshes]) for b in brackets]
    for i in range(len(bb)):
        for j in range(i + 1, len(bb)):
            a, ma = bb[i]
            b, mb = bb[j]
            if a.host_set() & b.host_set():
                continue
            worst = np.inf
            for alo, ahi, av, af in ma:
                for blo, bhi, bv, bf in mb:
                    if float(np.max(np.maximum(alo - bhi, blo - ahi))) >= c_req:
                        continue
                    oa, ob = _fcl_obj(av, af), _fcl_obj(bv, bf)
                    if fcl.collide(oa, ob, fcl.CollisionRequest(), fcl.CollisionResult()) > 0:
                        worst = -1.0
                    else:
                        worst = min(worst, float(fcl.distance(oa, ob, fcl.DistanceRequest(), fcl.DistanceResult())))
            if worst < c_req - 1e-3:
                out.append((a.id, b.id, worst))
    return out
