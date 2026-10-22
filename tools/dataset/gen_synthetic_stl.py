#!/usr/bin/env python3
"""Synthetic CubeSat STL dataset generator (Python standard library only).

Units are millimetres. Every part is written as a binary STL. manifest.json
records SHA-256 hashes, construction parameters and, where a closed-form answer
exists, analytic mass properties for unit density expressed in the file frame.

Inertia convention: I = integral of (|r|^2 E - r r^T) dV about the centre of mass,
so off-diagonal entries are -integral(x y dV). Unit density, units mm^5.

Usage: python -I gen_synthetic_stl.py <output_dir>
"""
import hashlib
import json
import math
import os
import random
import struct
import sys

SEED = 20261021
TAU = 2.0 * math.pi
GENERATOR_VERSION = "0.1.0"


# ---------------------------------------------------------------- vectors
def add(a, b): return (a[0] + b[0], a[1] + b[1], a[2] + b[2])
def sub(a, b): return (a[0] - b[0], a[1] - b[1], a[2] - b[2])
def scale(a, s): return (a[0] * s, a[1] * s, a[2] * s)
def dot(a, b): return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
def cross(a, b): return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])
def norm(a): return math.sqrt(dot(a, a))


def mat_mul(A, B): return [[sum(A[i][k] * B[k][j] for k in range(3)) for j in range(3)] for i in range(3)]
def mat_t(A): return [[A[j][i] for j in range(3)] for i in range(3)]
def mat_vec(A, v): return tuple(sum(A[i][k] * v[k] for k in range(3)) for i in range(3))


IDENTITY = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]


def rot_axis_angle(axis, deg):
    x, y, z = scale(axis, 1.0 / norm(axis))
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    C = 1.0 - c
    return [[c + x * x * C, x * y * C - z * s, x * z * C + y * s],
            [y * x * C + z * s, c + y * y * C, y * z * C - x * s],
            [z * x * C - y * s, z * y * C + x * s, c + z * z * C]]


# ---------------------------------------------------------------- mesh
class Mesh:
    """Indexed triangle mesh; vertices are welded on coordinates rounded to 1e-9 mm."""

    def __init__(self):
        self.v, self.f, self._ids = [], [], {}

    def vid(self, p):
        key = (round(p[0], 9) + 0.0, round(p[1], 9) + 0.0, round(p[2], 9) + 0.0)
        i = self._ids.get(key)
        if i is None:
            i = self._ids[key] = len(self.v)
            self.v.append(key)
        return i

    def tri(self, a, b, c):
        if a != b and b != c and c != a:
            self.f.append((a, b, c))

    def poly(self, pts, outward):
        """Fan-triangulate a convex planar polygon, wound so its normal faces `outward`."""
        idx = [self.vid(p) for p in pts]
        n = (0.0, 0.0, 0.0)
        for i in range(len(pts)):  # Newell normal
            p, q = pts[i], pts[(i + 1) % len(pts)]
            n = add(n, ((p[1] - q[1]) * (p[2] + q[2]), (p[2] - q[2]) * (p[0] + q[0]), (p[0] - q[0]) * (p[1] + q[1])))
        if dot(n, outward) < 0:
            idx = [idx[0]] + idx[:0:-1]  # keep the fan apex, reverse the rest
        for i in range(1, len(idx) - 1):
            self.tri(idx[0], idx[i], idx[i + 1])
        return self

    def transformed(self, R, t):
        out = Mesh()
        for face in self.f:
            out.tri(*(out.vid(add(mat_vec(R, self.v[i]), t)) for i in face))
        return out

    def merged(self, other):
        for face in other.f:
            self.tri(*(self.vid(other.v[i]) for i in face))
        return self

    def flip(self):
        self.f = [(a, c, b) for a, b, c in self.f]
        return self

    def signed_volume(self):
        return sum(dot(self.v[a], cross(self.v[b], self.v[c])) for a, b, c in self.f) / 6.0

    def orient_outward(self):
        return self.flip() if self.signed_volume() < 0 else self


def edge_report(mesh):
    """Return (boundary, non-manifold, mis-oriented) undirected edge counts."""
    count = {}
    for a, b, c in mesh.f:
        for e in ((a, b), (b, c), (c, a)):
            count[e] = count.get(e, 0) + 1
    boundary = nonmanifold = misoriented = 0
    seen = set()
    for a, b in count:
        u = (min(a, b), max(a, b))
        if u in seen:
            continue
        seen.add(u)
        fwd, rev = count.get((a, b), 0), count.get((b, a), 0)
        if fwd + rev == 1:
            boundary += 1
        elif fwd + rev > 2:
            nonmanifold += 1
        elif fwd != 1 or rev != 1:
            misoriented += 1
    return boundary, nonmanifold, misoriented


# ---------------------------------------------------------------- primitives
def box(m, lo, hi):
    x0, y0, z0 = lo
    x1, y1, z1 = hi
    P = lambda i, j, k: (x1 if i else x0, y1 if j else y0, z1 if k else z0)
    m.poly([P(0, 0, 0), P(0, 1, 0), P(1, 1, 0), P(1, 0, 0)], (0, 0, -1))
    m.poly([P(0, 0, 1), P(1, 0, 1), P(1, 1, 1), P(0, 1, 1)], (0, 0, 1))
    m.poly([P(0, 0, 0), P(1, 0, 0), P(1, 0, 1), P(0, 0, 1)], (0, -1, 0))
    m.poly([P(0, 1, 0), P(0, 1, 1), P(1, 1, 1), P(1, 1, 0)], (0, 1, 0))
    m.poly([P(0, 0, 0), P(0, 0, 1), P(0, 1, 1), P(0, 1, 0)], (-1, 0, 0))
    m.poly([P(1, 0, 0), P(1, 1, 0), P(1, 1, 1), P(1, 0, 1)], (1, 0, 0))
    return m


def lattice(m, rows, n, closed_rows=False):
    """Stitch rows of n points (columns wrap). Rows that collapse to one point become poles."""
    ids = [[m.vid(p) for p in row] for row in rows]
    last = len(ids) if closed_rows else len(ids) - 1
    for i in range(last):
        A, B = ids[i], ids[(i + 1) % len(ids)]
        for j in range(n):
            k = (j + 1) % n
            m.tri(A[j], A[k], B[k])
            m.tri(A[j], B[k], B[j])
    return m.orient_outward()


def revolve(m, profile, n, closed=False):
    rows = [[(r * math.cos(TAU * j / n), r * math.sin(TAU * j / n), z) for j in range(n)] for r, z in profile]
    return lattice(m, rows, n, closed)


def signed_area(poly):
    return 0.5 * sum(poly[i][0] * poly[(i + 1) % len(poly)][1] - poly[(i + 1) % len(poly)][0] * poly[i][1]
                     for i in range(len(poly)))


def ear_clip(poly):
    """Triangulate a simple CCW polygon; returns index triples."""
    def area2(a, b, c): return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
    def inside(p, a, b, c): return area2(a, b, p) >= 0 and area2(b, c, p) >= 0 and area2(c, a, p) >= 0
    idx, tris = list(range(len(poly))), []
    while len(idx) > 3:
        n = len(idx)
        for k in range(n):
            i0, i1, i2 = idx[k - 1], idx[k], idx[(k + 1) % n]
            a, b, c = poly[i0], poly[i1], poly[i2]
            if area2(a, b, c) <= 1e-12:
                continue
            if any(inside(poly[j], a, b, c) for j in idx if j not in (i0, i1, i2)):
                continue
            tris.append((i0, i1, i2))
            idx.pop(k)
            break
        else:
            raise RuntimeError("ear clipping failed")
    tris.append(tuple(idx))
    return tris


def extrude(m, poly, h):
    if signed_area(poly) < 0:
        poly = poly[::-1]
    bot = [m.vid((x, y, 0.0)) for x, y in poly]
    top = [m.vid((x, y, h)) for x, y in poly]
    for a, b, c in ear_clip(poly):
        m.tri(top[a], top[b], top[c])
        m.tri(bot[a], bot[c], bot[b])
    n = len(poly)
    for i in range(n):
        j = (i + 1) % n
        m.tri(bot[i], bot[j], top[j])
        m.tri(bot[i], top[j], top[i])
    return m


def cross_hub(m, a, L):
    """Centre cube of side a with six a x a x L arms (a 3D cross)."""
    h = a / 2.0
    for axis in range(3):
        j, k = (axis + 1) % 3, (axis + 2) % 3
        for s in (1.0, -1.0):
            def pt(along, comp, cval, other, oval):
                p = [0.0, 0.0, 0.0]
                p[axis], p[comp], p[other] = s * along, cval, oval
                return tuple(p)
            out = [0.0, 0.0, 0.0]
            out[axis] = s
            m.poly([pt(h + L, j, -h, k, -h), pt(h + L, j, h, k, -h), pt(h + L, j, h, k, h), pt(h + L, j, -h, k, h)],
                   tuple(out))
            for comp, other in ((j, k), (k, j)):
                for sign in (1.0, -1.0):
                    nrm = [0.0, 0.0, 0.0]
                    nrm[comp] = sign
                    m.poly([pt(h, comp, sign * h, other, -h), pt(h + L, comp, sign * h, other, -h),
                            pt(h + L, comp, sign * h, other, h), pt(h, comp, sign * h, other, h)], tuple(nrm))
    return m


def camera(m, a, c, r, h, n):
    """Square body a x a x c (z from 0 to c) with a cylindrical lens r x h on the +Z face."""
    assert n % 8 == 0
    half = a / 2.0
    th = [TAU * k / n for k in range(n)]
    S = []
    for t in th:  # square boundary sampled at the lens angles (corners land on k = n/8, 3n/8, ...)
        cx, sy = math.cos(t), math.sin(t)
        mx = max(abs(cx), abs(sy))
        S.append((half * cx / mx, half * sy / mx, c))
    C0 = [(r * math.cos(t), r * math.sin(t), c) for t in th]
    C1 = [(r * math.cos(t), r * math.sin(t), c + h) for t in th]
    for k in range(n):  # top annulus between square and lens base, +Z
        k1 = (k + 1) % n
        m.tri(m.vid(S[k]), m.vid(S[k1]), m.vid(C0[k1]))
        m.tri(m.vid(S[k]), m.vid(C0[k1]), m.vid(C0[k]))
        mid = (th[k] + TAU / (2 * n))
        m.poly([C0[k], C0[k1], C1[k1], C1[k]], (math.cos(mid), math.sin(mid), 0.0))
    m.poly(C1, (0, 0, 1))
    m.poly([(-half, -half, 0.0), (half, -half, 0.0), (half, half, 0.0), (-half, half, 0.0)], (0, 0, -1))
    e = n // 8
    for q in range(4):
        ks = [(k % n) for k in range((2 * q - 1) * e, (2 * q + 1) * e + 1)]
        top = [S[k] for k in ks]
        bottom = [(top[0][0], top[0][1], 0.0), (top[-1][0], top[-1][1], 0.0)]
        out = (round(math.cos(q * math.pi / 2)), round(math.sin(q * math.pi / 2)), 0)
        m.poly(bottom + top[::-1], out)
    return m


def gear_polygon(r_root, r_tip, teeth):
    pts, p = [], TAU / teeth
    for t in range(teeth):
        for frac, r in ((0.0, r_root), (0.25, r_tip), (0.5, r_tip), (0.75, r_root)):
            a = (t + frac) * p
            pts.append((r * math.cos(a), r * math.sin(a)))
    return pts


def ellipsoid_rows(a, b, c, n_lat, n_lon):
    rows = []
    for i in range(n_lat + 1):
        phi = math.pi * i / n_lat
        rows.append([(a * math.sin(phi) * math.cos(TAU * j / n_lon), b * math.sin(phi) * math.sin(TAU * j / n_lon),
                      -c * math.cos(phi)) for j in range(n_lon)])
    return rows


def blob_rows(R, n_lat, n_lon, rng):
    """Star-shaped radial surface: a sphere displaced by seeded smooth waves (never self-intersects)."""
    waves = []
    for _ in range(9):  # amplitudes sum to < 0.6, so the radius stays above 0.4 R
        d = (rng.gauss(0, 1), rng.gauss(0, 1), rng.gauss(0, 1))
        waves.append((scale(d, 1.0 / norm(d)), rng.uniform(5.0, 10.0), rng.uniform(0.0, TAU), rng.uniform(0.04, 0.065)))
    rows = []
    for i in range(n_lat + 1):
        phi = math.pi * i / n_lat
        row = []
        for j in range(n_lon):
            u = (math.sin(phi) * math.cos(TAU * j / n_lon), math.sin(phi) * math.sin(TAU * j / n_lon), -math.cos(phi))
            r = R * (1.0 + sum(A * math.sin(w * dot(u, d) + ph) for d, w, ph, A in waves))
            row.append(scale(u, r))
        rows.append(row)
    return rows, waves


# ---------------------------------------------------------------- analytic mass properties (unit density)
def diag3(a, b, c): return [[a, 0.0, 0.0], [0.0, b, 0.0], [0.0, 0.0, c]]


def props_box(d, c):
    a, b, h = d
    V = a * b * h
    return V, tuple(c), diag3(V * (b * b + h * h) / 12, V * (a * a + h * h) / 12, V * (a * a + b * b) / 12)


def props_cyl(r, h, zc):
    V = math.pi * r * r * h
    t = V * (3 * r * r + h * h) / 12
    return V, (0.0, 0.0, zc), diag3(t, t, V * r * r / 2)


def props_tube(ro, ri, h, zc):
    V = math.pi * (ro * ro - ri * ri) * h
    t = V * (3 * (ro * ro + ri * ri) + h * h) / 12
    return V, (0.0, 0.0, zc), diag3(t, t, V * (ro * ro + ri * ri) / 2)


def props_ellipsoid(a, b, c):
    V = 4.0 / 3.0 * math.pi * a * b * c
    return V, (0.0, 0.0, 0.0), diag3(V * (b * b + c * c) / 5, V * (a * a + c * c) / 5, V * (a * a + b * b) / 5)


def props_torus(R, r):
    V = 2 * math.pi ** 2 * R * r * r
    t = V * (0.5 * R * R + 0.625 * r * r)
    return V, (0.0, 0.0, 0.0), diag3(t, t, V * (R * R + 0.75 * r * r))


def props_capsule(r, L):
    Vc, Vh = math.pi * r * r * L, 2.0 / 3.0 * math.pi * r ** 3
    d = L / 2 + 3 * r / 8
    t = Vc * (3 * r * r + L * L) / 12 + 2 * (Vh * 83.0 / 320.0 * r * r + Vh * d * d)
    return Vc + 2 * Vh, (0.0, 0.0, 0.0), diag3(t, t, Vc * r * r / 2 + 2 * 0.4 * Vh * r * r)


def props_prism(poly, h):
    """Prism of a simple polygon extruded from z = 0 to z = h (exact polygon moment formulas)."""
    if signed_area(poly) < 0:
        poly = poly[::-1]
    A = cx = cy = sxx = syy = sxy = 0.0
    n = len(poly)
    for i in range(n):
        x0, y0 = poly[i]
        x1, y1 = poly[(i + 1) % n]
        cr = x0 * y1 - x1 * y0
        A += cr
        cx += (x0 + x1) * cr
        cy += (y0 + y1) * cr
        syy += (x0 * x0 + x0 * x1 + x1 * x1) * cr
        sxx += (y0 * y0 + y0 * y1 + y1 * y1) * cr
        sxy += (x0 * y1 + 2 * x0 * y0 + 2 * x1 * y1 + x1 * y0) * cr
    A /= 2.0
    cx /= 6.0 * A
    cy /= 6.0 * A
    sxx = sxx / 12.0 - A * cy * cy
    syy = syy / 12.0 - A * cx * cx
    sxy = sxy / 24.0 - A * cx * cy
    I = [[h * sxx + A * h ** 3 / 12, -h * sxy, 0.0], [-h * sxy, h * syy + A * h ** 3 / 12, 0.0], [0.0, 0.0, h * (sxx + syy)]]
    return A * h, (cx, cy, h / 2.0), I


def props_combine(parts):
    V = sum(p[0] for p in parts)
    c = tuple(sum(p[0] * p[1][i] for p in parts) / V for i in range(3))
    I = [[0.0] * 3 for _ in range(3)]
    for v, ci, Ii in parts:
        d = sub(ci, c)
        dd = dot(d, d)
        for r in range(3):
            for s in range(3):
                I[r][s] += Ii[r][s] + v * ((dd if r == s else 0.0) - d[r] * d[s])
    return V, c, I


def props_transform(p, R, t):
    V, c, I = p
    return V, add(mat_vec(R, c), t), mat_mul(mat_mul(R, I), mat_t(R))


# ---------------------------------------------------------------- dataset definition
def build_parts(rng):
    parts = []

    def part(name, mesh, props, role, labels, ptype, construction, R=IDENTITY, t=(0.0, 0.0, 0.0), note=""):
        if R is not IDENTITY or t != (0.0, 0.0, 0.0):
            mesh = mesh.transformed(R, t)
            props = props_transform(props, R, t) if props else None
        parts.append(dict(name=name, mesh=mesh, props=props, role=role, labels=labels, type=ptype,
                          construction=construction, R=R, t=t, note=note))

    # simple
    part("battery_pack", box(Mesh(), (0, 0, 0), (80, 80, 22)), props_box((80, 80, 22), (40, 40, 11)),
         "packable", ["box-like", "convex"], "battery", {"primitive": "box", "size_mm": [80, 80, 22],
         "frame": "corner at origin"})
    s, nt = 45.0, 7.0
    pcb = [(-s + nt, -s), (s - nt, -s), (s - nt, -s + nt), (s, -s + nt), (s, s - nt), (s - nt, s - nt),
           (s - nt, s), (-s + nt, s), (-s + nt, s - nt), (-s, s - nt), (-s, -s + nt), (-s + nt, -s + nt)]
    for nm in ("pcb_obc", "pcb_eps"):
        part(nm, extrude(Mesh(), pcb, 1.6), props_prism(pcb, 1.6), "packable", ["plate-like", "thin", "near-box"],
             "pcb", {"primitive": "extruded polygon", "outline_mm": "90 x 90 with 7 x 7 corner notches",
                     "thickness_mm": 1.6})
    part("payload_electronics_box", box(Mesh(), (-30, -20, -15), (30, 20, 15)), props_box((60, 40, 30), (0, 0, 0)),
         "packable", ["box-like", "convex"], "electronics", {"primitive": "box", "size_mm": [60, 40, 30]},
         R=rot_axis_angle((1, 2, 3), 37.0), t=(12.5, -7.25, 4.0), note="authored in a tilted, offset frame")
    part("reaction_wheel", revolve(Mesh(), [(0, -12.5), (25, -12.5), (25, 12.5), (0, 12.5)], 96),
         props_cyl(25, 25, 0.0), "packable", ["convex", "cylindrical"], "reaction wheel",
         {"primitive": "cylinder", "diameter_mm": 50, "height_mm": 25, "segments": 96})
    part("magnetorquer_rod", revolve(Mesh(), [(0, 0), (5, 0), (5, 80), (0, 80)], 48), props_cyl(5, 80, 40.0),
         "packable", ["convex", "elongated", "cylindrical"], "magnetorquer",
         {"primitive": "cylinder", "diameter_mm": 10, "length_mm": 80, "segments": 48})
    part("propellant_tank_sphere", lattice(Mesh(), ellipsoid_rows(30, 30, 30, 48, 96), 96),
         props_ellipsoid(30, 30, 30), "packable", ["convex", "spherical"], "tank",
         {"primitive": "sphere", "diameter_mm": 60, "latitude_bands": 48, "longitude_segments": 96})
    # convex, not box-shaped
    r, L, k = 22.5, 45.0, 24
    prof = [(r * math.sin(math.pi / 2 * i / k), -L / 2 - r * math.cos(math.pi / 2 * i / k)) for i in range(k + 1)]
    prof += [(r * math.cos(math.pi / 2 * i / k), L / 2 + r * math.sin(math.pi / 2 * i / k)) for i in range(k + 1)]
    part("gas_tank_capsule", revolve(Mesh(), prof, 96), props_capsule(r, L), "packable",
         ["convex", "elongated"], "tank", {"primitive": "capsule", "diameter_mm": 45, "overall_length_mm": 90,
                                           "segments": 96, "hemisphere_rings": k})
    sh = 40.0 / math.sqrt(3.0)
    hexagon = [(sh * math.cos(math.pi / 3 * i), sh * math.sin(math.pi / 3 * i)) for i in range(6)]
    part("sensor_housing_hex", extrude(Mesh(), hexagon, 50), props_prism(hexagon, 50), "packable",
         ["convex", "prismatic"], "sensor", {"primitive": "hexagonal prism", "across_flats_mm": 40, "height_mm": 50})
    part("ellipsoid_module", lattice(Mesh(), ellipsoid_rows(30, 20, 15, 48, 96), 96), props_ellipsoid(30, 20, 15),
         "packable", ["convex"], "module", {"primitive": "ellipsoid", "axes_mm": [60, 40, 30]},
         R=rot_axis_angle((0.3, -0.5, 0.8), 52.0), note="authored in a tilted frame")
    tri = [(0.0, 0.0), (50.0, 0.0), (0.0, 30.0)]
    part("wedge_bracket", extrude(Mesh(), tri, 40), props_prism(tri, 40), "packable", ["convex", "prismatic"],
         "bracket", {"primitive": "triangular prism", "legs_mm": [50, 30], "thickness_mm": 40},
         R=rot_axis_angle((1, 0, 1), 25.0), t=(-15.0, 22.0, 8.0), note="authored in a tilted, offset frame")
    # concave or complex
    ell = [(0, 0), (70, 0), (70, 25), (25, 25), (25, 70), (0, 70)]
    part("l_shaped_electronics", extrude(Mesh(), ell, 30), props_prism(ell, 30), "packable", ["concave"],
         "electronics", {"primitive": "extruded L", "outline_mm": "70 x 70, 25 wide arms", "height_mm": 30})
    u = [(0, 0), (60, 0), (60, 30), (56, 30), (56, 4), (4, 4), (4, 30), (0, 30)]
    part("u_channel_bracket", extrude(Mesh(), u, 80), props_prism(u, 80), "packable", ["concave", "open cavity"],
         "bracket", {"primitive": "extruded U", "outline_mm": "60 x 30, 4 mm walls", "length_mm": 80})
    a, arm = 16.0, 16.0
    boxes = [props_box((a, a, a), (0, 0, 0))]
    for axis in range(3):
        for sgn in (1, -1):
            dims, cen = [a, a, a], [0.0, 0.0, 0.0]
            dims[axis], cen[axis] = arm, sgn * (a / 2 + arm / 2)
            boxes.append(props_box(dims, cen))
    part("cross_connector_hub", cross_hub(Mesh(), a, arm), props_combine(boxes), "packable",
         ["concave", "strongly non-convex"], "connector hub",
         {"primitive": "3D cross", "core_mm": a, "arm_length_mm": arm})
    part("camera_with_lens", camera(Mesh(), 50, 40, 15, 30, 64),
         props_combine([props_box((50, 50, 40), (0, 0, 20)), props_cyl(15, 30, 55)]), "packable",
         ["concave"], "camera", {"primitive": "box + cylinder", "body_mm": [50, 50, 40],
                                 "lens_diameter_mm": 30, "lens_length_mm": 30, "segments": 64})
    part("optics_baffle_tube", revolve(Mesh(), [(17, 0), (20, 0), (20, 60), (17, 60)], 96, closed=True),
         props_tube(20, 17, 60, 30.0), "packable", ["concave", "through-hole"], "optics",
         {"primitive": "tube", "outer_diameter_mm": 40, "inner_diameter_mm": 34, "length_mm": 60, "segments": 96})
    part("magnetometer_ring_torus",
         revolve(Mesh(), [(30 + 8 * math.cos(TAU * i / 32), 8 * math.sin(TAU * i / 32)) for i in range(32)], 96,
                 closed=True),
         props_torus(30, 8), "packable", ["concave", "through-hole", "curved"], "magnetometer",
         {"primitive": "torus", "ring_radius_mm": 30, "tube_radius_mm": 8, "segments": [96, 32]})
    gear = gear_polygon(20.0, 25.0, 16)
    part("gear_mechanism", extrude(Mesh(), gear, 10), props_prism(gear, 10), "packable", ["concave", "plate-like"],
         "mechanism", {"primitive": "extruded gear outline", "root_diameter_mm": 40, "tip_diameter_mm": 50,
                       "teeth": 16, "thickness_mm": 10})
    rows, waves = blob_rows(25.0, 160, 160, rng)
    part("irregular_blob", lattice(Mesh(), rows, 160), None, "packable", ["concave", "highly irregular"], "unknown",
         {"primitive": "radially displaced sphere", "base_radius_mm": 25, "grid": [160, 160],
          "waves": [{"direction": list(d), "frequency": w, "phase": ph, "amplitude": A} for d, w, ph, A in waves]},
         note="no closed-form answer; reference values come from the mesh itself")
    # validation-only fixtures
    two = box(Mesh(), (0, 0, 0), (20, 20, 15)).merged(box(Mesh(), (30, 0, 0), (50, 20, 15)))
    part("fixture_two_bodies", two, props_combine([props_box((20, 20, 15), (10, 10, 7.5)),
                                                   props_box((20, 20, 15), (40, 10, 7.5))]),
         "fixture", ["multi-body"], "fixture", {"primitive": "two separate boxes", "size_mm": [20, 20, 15],
                                                 "gap_mm": 10})
    opened = box(Mesh(), (0, 0, 0), (30, 20, 10))
    opened.f.pop()
    part("fixture_open_mesh", opened, props_box((30, 20, 10), (15, 10, 5)), "fixture", ["defect: open"], "fixture",
         {"primitive": "box with one triangle removed", "size_mm": [30, 20, 10]},
         note="mass properties must be withheld; analytic values are for the intact box")
    part("fixture_flipped_normals", revolve(Mesh(), [(0, 0), (10, 0), (10, 30), (0, 30)], 48).flip(),
         props_cyl(10, 30, 15.0), "fixture", ["defect: inverted"], "fixture",
         {"primitive": "cylinder with every face reversed", "diameter_mm": 20, "height_mm": 30, "segments": 48},
         note="signed volume is negative until the winding is repaired")
    return parts


# ---------------------------------------------------------------- output
def write_stl(path, mesh, title):
    with open(path, "wb") as fh:
        fh.write(("text-to-spaceship synthetic | units=mm | " + title).encode("ascii")[:80].ljust(80, b" "))
        fh.write(struct.pack("<I", len(mesh.f)))
        for a, b, c in mesh.f:
            p, q, r = mesh.v[a], mesh.v[b], mesh.v[c]
            n = cross(sub(q, p), sub(r, p))
            ln = norm(n)
            n = scale(n, 1.0 / ln) if ln > 0 else (0.0, 0.0, 0.0)
            fh.write(struct.pack("<12fH", *n, *p, *q, *r, 0))


def main(out_dir):
    os.makedirs(os.path.join(out_dir, "fixtures"), exist_ok=True)
    rng = random.Random(SEED)
    entries, hashes = [], []
    for p in build_parts(rng):
        mesh = p["mesh"]
        boundary, nonmanifold, misoriented = edge_report(mesh)
        vol = mesh.signed_volume()
        if p["role"] == "packable" and (boundary or nonmanifold or misoriented or vol <= 0):
            raise SystemExit("%s failed self-check: %d/%d/%d vol=%g" % (p["name"], boundary, nonmanifold,
                                                                         misoriented, vol))
        rel = ("fixtures/" if p["role"] == "fixture" else "") + p["name"] + ".stl"
        path = os.path.join(out_dir, *rel.split("/"))
        write_stl(path, mesh, p["name"])
        with open(path, "rb") as fh:
            blob = fh.read()
        sha = hashlib.sha256(blob).hexdigest()
        hashes.append("%s:%s" % (rel, sha))
        analytic = None
        if p["props"]:
            V, c, I = p["props"]
            analytic = {"volume_mm3": V, "com_mm": list(c), "inertia_about_com_unit_density_mm5": I,
                        "basis": "exact" if p["construction"]["primitive"] in (
                            "box", "extruded polygon", "triangular prism", "hexagonal prism", "extruded L",
                            "extruded U", "3D cross", "extruded gear outline", "two separate boxes",
                            "box with one triangle removed") else "continuous shape; the mesh is a tessellation"}
        entries.append({
            "name": p["name"], "file": rel, "sha256": sha, "bytes": len(blob), "role": p["role"],
            "triangles": len(mesh.f), "welded_vertices": len(mesh.v),
            "generator_self_check": {"boundary_edges": boundary, "nonmanifold_edges": nonmanifold,
                                     "misoriented_edges": misoriented, "signed_volume_mm3": vol},
            "intended_labels": p["labels"], "suggested_type": p["type"], "construction": p["construction"],
            "authored_transform": {"rotation": p["R"], "translation_mm": list(p["t"])},
            "analytic": analytic, "note": p["note"]})
    manifest = {
        "dataset": "text-to-spaceship synthetic CubeSat parts", "generator_version": GENERATOR_VERSION,
        "seed": SEED, "units": "mm", "stl_precision": "binary STL stores float32 coordinates",
        "inertia_convention": "about COM, I = integral(|r|^2 E - r r^T) dV, unit density, mm^5",
        "dataset_sha256": hashlib.sha256("\n".join(sorted(hashes)).encode()).hexdigest(),
        "parts": entries}
    with open(os.path.join(out_dir, "manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=1)
    for e in entries:
        print("%-26s %-8s %7d tris  %s" % (e["name"], e["role"], e["triangles"], e["sha256"][:12]))
    print("dataset_sha256", manifest["dataset_sha256"])


if __name__ == "__main__":
    main(sys.argv[1])
