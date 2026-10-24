"""Bolted joint of a designed bracket: the bolt pattern on the bolted face, passive bosses around the bolts, per-bolt
forces from the per-node support reactions of the FE solution, and the bolt / flange checks.

* Pattern (ASSUMED): `n` M3 bolts (the bracket's fastener count) at the corners of the bolted face, inset by
  BOLT_EDGE mm (edge distance e = 2 d, the e/D = 2 of the research note's bearing values); 3 bolts: two at one end of
  the longer side and one at the middle of the other end; 2: diagonal corners; 1: the centre; more than 4: the
  corners plus bolts spaced along the longer sides. A bolt is moved to the nearest solid voxel of the bolted layer
  when its spot is inside the part.
* Bosses (ASSUMED): passive solid of radius BOSS_RADIUS around each bolt through the first FLANGE_T mm from the
  bolted face (the 2 mm structural-wall rule, research note §4), so every bolt has a flange to clamp.
* Bolt forces: the FE model clamps the whole bolted face. Each supported node's reaction is given to the nearest
  bolt (in the face plane); a bolt's force is the sum over its nodes. Tension = the part of that force pulling the
  bracket off the wall (compression is carried by contact), shear = the in-plane part. Preload, prying and joint
  gapping are not modelled.
* Checks (fitting factor 1.15 on every joint check, research note §3 / ECSS-E-HB-32-23A §5.5.2): M3 A2-70 tension
  (yield 2.26 kN, ultimate 3.52 kN) and shear (ultimate 1.88 kN) — ECSS-E-HB-32-23A Table D-2 via the research
  note; flange bearing d·t·F (F = Fty / Ftu of the bracket material: no bearing increase is credited, ASSUMED
  conservative — 6061-T6 at e/D = 2 has Fbry ≈ 1.67 Fty, Fbru ≈ 2.1 Ftu, research note §1) and pull-through of the
  head π·D_head·t·F/√3 (shear strength = tensile / √3, von Mises, ASSUMED), t = the solid's thickness at the bolt,
  at most FLANGE_T.
"""
from __future__ import annotations

import math

import numpy as np

BOLT_D = 3.0                  # mm, M3
HEAD_D = 5.5                  # mm, ISO 4762 M3 socket head diameter (the smaller of head and 7 mm washer)
BOLT_EDGE = 2.0 * BOLT_D      # mm from the face edge to a bolt centre (ASSUMED, e/D = 2)
BOSS_RADIUS = 4.0             # mm (ASSUMED: covers the 7 mm M3 washer envelope of mfg.brackets.WASHER)
FLANGE_T = 2.0                # mm (research note §4: 2 mm recommended for structural walls)
FITTING_FACTOR = 1.15
FF_SOURCE = "fitting factor 1.15 (ECSS-E-HB-32-23A §5.5.2, research note §1/§3)"
M3_A2_70 = {"tension_yield_n": 2260.0, "tension_ult_n": 3520.0, "shear_ult_n": 1880.0,
            "source": "M3 A2-70: tension yield 2.26 kN, ultimate 3.52 kN, shear ≈ 1.88 kN (ECSS-E-HB-32-23A Table "
                      "D-2, S-basis; research note §1)"}


def in_plane_axes(axis: int) -> tuple[int, int]:
    b, c = [k for k in range(3) if k != axis]
    return b, c


def pattern_2d(lo: np.ndarray, hi: np.ndarray, n: int, edge: float = BOLT_EDGE) -> np.ndarray:
    """Bolt centres (n, 2) on the rectangle [lo, hi] (in-plane coordinates), inset `edge` from the sides (less on a
    face narrower than 2 × edge: then the centre line)."""
    lo, hi = np.asarray(lo, float), np.asarray(hi, float)
    a = np.where(hi - lo > 2 * edge, lo + edge, 0.5 * (lo + hi))
    b = np.where(hi - lo > 2 * edge, hi - edge, 0.5 * (lo + hi))
    n = int(n)
    if n <= 1:
        return np.array([0.5 * (lo + hi)])
    if n == 2:
        return np.array([a, b])
    long = int(np.argmax(hi - lo))
    short = 1 - long

    def pt(u_long, u_short):
        p = np.zeros(2)
        p[long], p[short] = u_long, u_short
        return p
    if n == 3:
        return np.array([pt(a[long], a[short]), pt(a[long], b[short]), pt(b[long], 0.5 * (a[short] + b[short]))])
    out = [pt(a[long], a[short]), pt(a[long], b[short]), pt(b[long], a[short]), pt(b[long], b[short])]
    extra = n - 4
    per_side = [extra - extra // 2, extra // 2]
    for side, k in zip((a[short], b[short]), per_side):
        for i in range(k):
            out.append(pt(a[long] + (i + 1) * (b[long] - a[long]) / (k + 1), side))
    return np.array(out)


def layout(dom, n: int) -> tuple[np.ndarray, np.ndarray]:
    """(bolt centres (n, 3) world mm on the target plane, boss mask) for a design domain: the pattern on the grid's
    bolted face, each bolt moved to the nearest solid voxel of the bolted layer if needed; bosses = voxels within
    BOSS_RADIUS (in plane) of a bolt whose lower face lies within FLANGE_T of the plane, outside the part."""
    ax = dom.axis
    b, c = in_plane_axes(ax)
    lo = np.array([dom.origin[b], dom.origin[c]])
    hi = lo + np.array([dom.shape[b], dom.shape[c]]) * dom.h
    pts = pattern_2d(lo, hi, n)
    cen = dom.centres()
    fixed_idx = np.argwhere(dom.fixed)
    out = []
    if len(fixed_idx):
        fc = cen[tuple(fixed_idx.T)][:, [b, c]]
        for p in pts:
            d = np.linalg.norm(fc - p, axis=1)
            k = int(np.argmin(d))
            q = p if d[k] <= 0.5 * dom.h * math.sqrt(2) + 1e-9 else fc[k]
            out.append(q)
    else:
        out = list(pts)
    bolts = np.zeros((len(out), 3))
    for i, q in enumerate(out):
        bolts[i, b], bolts[i, c], bolts[i, ax] = q[0], q[1], dom.plane_mm
    k = np.arange(dom.shape[ax])
    low_face = k * dom.h if dom.neg else (dom.shape[ax] - 1 - k) * dom.h     # distance of each layer from the plane
    sl = [None, None, None]
    sl[ax] = slice(None)
    near = np.broadcast_to((low_face < FLANGE_T - 1e-9)[tuple(sl)], dom.shape)
    rr = np.full(dom.shape, np.inf)
    for q in bolts:
        rr = np.minimum(rr, np.hypot(cen[..., b] - q[b], cen[..., c] - q[c]))
    boss = near & (rr <= BOSS_RADIUS) & ~dom.void & ~dom.fixed & ~dom.contact
    return bolts, boss


def assign_nodes(node_xyz: np.ndarray, bolts: np.ndarray, axis: int) -> np.ndarray:
    """Index of the nearest bolt (in the face plane) for every supported node."""
    b, c = in_plane_axes(axis)
    d = (node_xyz[:, None, b] - bolts[None, :, b]) ** 2 + (node_xyz[:, None, c] - bolts[None, :, c]) ** 2
    return np.argmin(d, axis=1)


def bolt_forces(node_forces: np.ndarray, owner: np.ndarray, n_bolts: int) -> np.ndarray:
    """(n_bolts, 3): the sum of the node forces each bolt collects."""
    out = np.zeros((n_bolts, 3))
    np.add.at(out, owner, np.asarray(node_forces, float))
    return out


def outward(axis: int, neg: bool) -> np.ndarray:
    """Unit normal from the wall into the bracket."""
    e = np.zeros(3)
    e[axis] = 1.0 if neg else -1.0
    return e


def tension_shear_static(F: np.ndarray, n_out: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Per bolt (tension, shear) for a quasi-static load acting in either sense (±: the MAC cases are applied one
    sense, the opposite gives the opposite force): tension |F·n|, shear |F − (F·n) n|."""
    F = np.atleast_2d(F)
    fn = F @ n_out
    return np.abs(fn), np.linalg.norm(F - fn[:, None] * n_out[None, :], axis=1)


def tension_shear_3sigma(cov: np.ndarray, n_out: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Per bolt (3σ tension, 3σ shear) of a zero-mean Gaussian force with covariance cov (n_b, 3, 3): tension
    3 √(nᵀCn); shear 3 √(tr(PCP)) (P the in-plane projector; ≥ the 3σ of the larger in-plane direction)."""
    P = np.eye(3) - np.outer(n_out, n_out)
    t = 3.0 * np.sqrt(np.maximum(np.einsum("i,bij,j->b", n_out, cov, n_out), 0.0))
    s = 3.0 * np.sqrt(np.maximum(np.einsum("ij,bjk,ki->b", P, cov, P), 0.0))
    return t, s


def capacities(material: dict, t_mm: np.ndarray) -> dict:
    """Per bolt capacities (N): bolt tension/shear, flange bearing and head pull-through at thickness t."""
    t = np.minimum(np.asarray(t_mm, float), FLANGE_T)
    fy, fu = float(material["yield_mpa"]), float(material["ultimate_mpa"])
    return {"tension_y": np.full(len(t), M3_A2_70["tension_yield_n"]),
            "tension_u": np.full(len(t), M3_A2_70["tension_ult_n"]),
            "shear_u": np.full(len(t), M3_A2_70["shear_ult_n"]),
            "bearing_y": BOLT_D * t * fy, "bearing_u": BOLT_D * t * fu,
            "pullthrough_y": math.pi * HEAD_D * t * fy / math.sqrt(3.0),
            "pullthrough_u": math.pi * HEAD_D * t * fu / math.sqrt(3.0), "t_mm": t}


def margins(tension: np.ndarray, shear: np.ndarray, cap: dict, fos_y: float, fos_u: float) -> dict:
    """Margins of safety per bolt for (tension, shear) loads with design factors (yield, ultimate) × the fitting
    factor: bolt tension (yield, ultimate), bolt shear (ultimate), bearing (shear load; yield, ultimate), pull-through
    (tension load; yield, ultimate). Returns {check: (n_b,) margins} and the minimum with its check and bolt."""
    T, V = np.maximum(np.asarray(tension, float), 1e-12), np.maximum(np.asarray(shear, float), 1e-12)
    ff = FITTING_FACTOR
    ms = {"bolt tension yield": cap["tension_y"] / (ff * fos_y * T) - 1.0,
          "bolt tension ultimate": cap["tension_u"] / (ff * fos_u * T) - 1.0,
          "bolt shear ultimate": cap["shear_u"] / (ff * fos_u * V) - 1.0,
          "flange bearing yield": cap["bearing_y"] / (ff * fos_y * V) - 1.0,
          "flange bearing ultimate": cap["bearing_u"] / (ff * fos_u * V) - 1.0,
          "head pull-through yield": cap["pullthrough_y"] / (ff * fos_y * T) - 1.0,
          "head pull-through ultimate": cap["pullthrough_u"] / (ff * fos_u * T) - 1.0}
    worst = min(((float(v.min()), k, int(np.argmin(v))) for k, v in ms.items()), key=lambda x: x[0])
    return {"margins": {k: v.tolist() for k, v in ms.items()}, "ms": worst[0], "check": worst[1], "bolt": worst[2]}


def thickness_at(v: np.ndarray, f: np.ndarray, bolts: np.ndarray, axis: int, neg: bool,
                 depth: float = FLANGE_T, step: float = 0.05) -> np.ndarray:
    """Solid thickness (mm) at each bolt along the bracket axis from the bolted face, up to `depth` (winding-number
    probes every `step` mm)."""
    from ..geometry.mesh import ray_parity_inside
    n_out = outward(axis, neg)
    s = np.arange(step / 2, depth + step / 2, step)
    out = []
    for p in np.asarray(bolts, float):
        pts = p[None, :] + s[:, None] * n_out[None, :]
        inside = ray_parity_inside(pts, np.asarray(v, float), np.asarray(f, np.int64)) > 0.5
        k = int(np.argmin(inside)) if not inside.all() else len(s)
        out.append(min(depth, k * step))
    return np.array(out)
