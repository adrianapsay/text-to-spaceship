#!/usr/bin/env python3
"""Read-only STL analysis (Python standard library only).

Reads every .stl under a folder (never writes there), checks mesh validity,
computes mass properties only for closed, consistently oriented meshes, and
derives the shape descriptors used for classification. If a manifest.json
with analytic values is present, the results are compared against it.

Usage: python -I analyze_stl.py <dataset_dir> <out.json> [density_kg_m3]
"""
import json
import math
import os
import struct
import sys
import time


def add(a, b): return (a[0] + b[0], a[1] + b[1], a[2] + b[2])
def sub(a, b): return (a[0] - b[0], a[1] - b[1], a[2] - b[2])
def scale(a, s): return (a[0] * s, a[1] * s, a[2] * s)
def dot(a, b): return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
def cross(a, b): return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])
def norm(a): return math.sqrt(dot(a, a))
def mat_mul(A, B): return [[sum(A[i][k] * B[k][j] for k in range(3)) for j in range(3)] for i in range(3)]
def mat_t(A): return [[A[j][i] for j in range(3)] for i in range(3)]


# ---------------------------------------------------------------- reading
def read_stl(path):
    with open(path, "rb") as fh:
        data = fh.read()
    if len(data) >= 84:
        n = struct.unpack_from("<I", data, 80)[0]
        if len(data) == 84 + 50 * n:
            return [struct.unpack_from("<12f", data, 84 + 50 * i)[3:] for i in range(n)], "binary"
    toks = data.decode("ascii", errors="replace").split()
    verts = [tuple(float(x) for x in toks[i + 1:i + 4]) for i, t in enumerate(toks) if t == "vertex"]
    return [verts[i] + verts[i + 1] + verts[i + 2] for i in range(0, len(verts) - 2, 3)], "ascii"


def weld(raw):
    ids, V, F = {}, [], []
    for t in raw:
        face = []
        for k in range(3):
            p = (t[3 * k], t[3 * k + 1], t[3 * k + 2])
            i = ids.get(p)
            if i is None:
                i = ids[p] = len(V)
                V.append(p)
            face.append(i)
        F.append(tuple(face))
    return V, F


# ---------------------------------------------------------------- topology
def topology(V, F):
    count = {}
    for a, b, c in F:
        for e in ((a, b), (b, c), (c, a)):
            count[e] = count.get(e, 0) + 1
    und = {}
    for (a, b), k in count.items():
        u = (min(a, b), max(a, b))
        und.setdefault(u, [0, 0])[0 if a < b else 1] += k
    boundary = sum(1 for f, r in und.values() if f + r == 1)
    nonmanifold = sum(1 for f, r in und.values() if f + r > 2)
    misoriented = sum(1 for f, r in und.values() if f + r == 2 and (f != 1 or r != 1))
    degenerate = sum(1 for a, b, c in F if a == b or b == c or a == c
                     or norm(cross(sub(V[b], V[a]), sub(V[c], V[a]))) == 0.0)
    parent = list(range(len(F)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    edge_owner = {}
    for fi, (a, b, c) in enumerate(F):
        for e in ((a, b), (b, c), (c, a)):
            u = (min(e), max(e))
            if u in edge_owner:
                ra, rb = find(fi), find(edge_owner[u])
                if ra != rb:
                    parent[ra] = rb
            else:
                edge_owner[u] = fi
    components = len({find(i) for i in range(len(F))})
    used = len({i for f in F for i in f})
    chi = used - len(und) + len(F)
    closed = boundary == 0 and nonmanifold == 0
    return {"boundary_edges": boundary, "nonmanifold_edges": nonmanifold, "misoriented_edges": misoriented,
            "degenerate_triangles": degenerate, "components": components, "euler_characteristic": chi,
            "genus_total": (components - chi // 2) if closed else None,
            "watertight": closed, "consistently_oriented": closed and misoriented == 0}


# ---------------------------------------------------------------- mass properties
def mass_props(V, F, origin):
    """Divergence-theorem integrals over signed tetrahedra from `origin` (exact for polyhedra)."""
    vol6 = 0.0
    m1 = [0.0, 0.0, 0.0]
    C = [[0.0] * 3 for _ in range(3)]
    for a, b, c in F:
        A, B, D = sub(V[a], origin), sub(V[b], origin), sub(V[c], origin)
        d = dot(A, cross(B, D))
        vol6 += d
        s = add(add(A, B), D)
        for i in range(3):
            m1[i] += d * s[i]
            for j in range(i, 3):
                C[i][j] += d * (A[i] * A[j] + B[i] * B[j] + D[i] * D[j] + s[i] * s[j])
    vol = vol6 / 6.0
    if vol == 0:
        return vol, None, None
    com = tuple(m1[i] / 24.0 / vol for i in range(3))
    for i in range(3):
        for j in range(i, 3):
            C[i][j] = C[i][j] / 120.0 - vol * com[i] * com[j]
            C[j][i] = C[i][j]
    tr = C[0][0] + C[1][1] + C[2][2]
    I = [[(tr if i == j else 0.0) - C[i][j] for j in range(3)] for i in range(3)]
    return vol, add(com, origin), I


def eig_sym3(A):
    """Jacobi eigen-decomposition; ascending eigenvalues, right-handed eigenvector columns as rows."""
    a = [row[:] for row in A]
    v = [[1.0 if i == j else 0.0 for j in range(3)] for i in range(3)]
    scale_ = abs(a[0][0]) + abs(a[1][1]) + abs(a[2][2]) + 1e-300
    for _ in range(60):
        if abs(a[0][1]) + abs(a[0][2]) + abs(a[1][2]) < 1e-15 * scale_:
            break
        for p, q in ((0, 1), (0, 2), (1, 2)):
            if abs(a[p][q]) < 1e-300:
                continue
            theta = (a[q][q] - a[p][p]) / (2.0 * a[p][q])
            t = (1.0 if theta >= 0 else -1.0) / (abs(theta) + math.sqrt(theta * theta + 1.0))
            c = 1.0 / math.sqrt(t * t + 1.0)
            s = t * c
            J = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
            J[p][p] = J[q][q] = c
            J[p][q], J[q][p] = s, -s
            a = mat_mul(mat_t(J), mat_mul(a, J))
            v = mat_mul(v, J)
    order = sorted(range(3), key=lambda i: a[i][i])
    vals = [a[i][i] for i in order]
    vecs = [tuple(v[r][i] for r in range(3)) for i in order]
    if dot(cross(vecs[0], vecs[1]), vecs[2]) < 0:
        vecs[2] = scale(vecs[2], -1.0)
    return vals, vecs


# ---------------------------------------------------------------- convex hull (quickhull)
def convex_hull(P):
    n = len(P)
    lo = [min(p[k] for p in P) for k in range(3)]
    hi = [max(p[k] for p in P) for k in range(3)]
    eps = 1e-7 * math.sqrt(sum((hi[k] - lo[k]) ** 2 for k in range(3)))
    i0 = min(range(n), key=lambda i: P[i][0])
    i1 = max(range(n), key=lambda i: norm(sub(P[i], P[i0])))
    d01 = sub(P[i1], P[i0])
    i2 = max(range(n), key=lambda i: norm(cross(d01, sub(P[i], P[i0]))))
    nrm = cross(d01, sub(P[i2], P[i0]))
    i3 = max(range(n), key=lambda i: abs(dot(nrm, sub(P[i], P[i0]))))
    if abs(dot(nrm, sub(P[i3], P[i0]))) <= eps * norm(nrm):
        return None
    cen = scale(add(add(P[i0], P[i1]), add(P[i2], P[i3])), 0.25)
    edge_face = {}

    def new_face(a, b, c):
        nv = cross(sub(P[b], P[a]), sub(P[c], P[a]))
        ln = norm(nv)
        nv = scale(nv, 1.0 / ln)
        f = [a, b, c, nv, dot(nv, P[a]), [], True]
        for e in ((a, b), (b, c), (c, a)):
            edge_face[e] = f
        return f

    faces = []
    for a, b, c in ((i0, i1, i2), (i0, i1, i3), (i0, i2, i3), (i1, i2, i3)):
        nv = cross(sub(P[b], P[a]), sub(P[c], P[a]))
        faces.append(new_face(a, c, b) if dot(nv, sub(cen, P[a])) > 0 else new_face(a, b, c))
    simplex = {i0, i1, i2, i3}
    for i in range(n):
        if i in simplex:
            continue
        for f in faces:
            if dot(f[3], P[i]) - f[4] > eps:
                f[5].append(i)
                break
    pending = [f for f in faces if f[5]]
    while pending:
        f = pending.pop()
        if f[6] is not True or not f[5]:
            continue
        far = max(f[5], key=lambda i: dot(f[3], P[i]))
        fp = P[far]
        f[6] = "v"
        visible, stack, horizon = [f], [f], []
        while stack:
            g = stack.pop()
            for e in ((g[0], g[1]), (g[1], g[2]), (g[2], g[0])):
                h = edge_face[(e[1], e[0])]
                if h[6] == "v":
                    continue
                if dot(h[3], fp) - h[4] > eps:
                    h[6] = "v"
                    visible.append(h)
                    stack.append(h)
                else:
                    horizon.append(e)
        orphans = []
        for g in visible:
            g[6] = False
            orphans.extend(g[5])
            for e in ((g[0], g[1]), (g[1], g[2]), (g[2], g[0])):
                if edge_face.get(e) is g:
                    del edge_face[e]
        new = [new_face(a, b, far) for a, b in horizon]
        faces.extend(new)
        for i in orphans:
            if i == far:
                continue
            for g in new:
                if dot(g[3], P[i]) - g[4] > eps:
                    g[5].append(i)
                    break
        pending.extend(g for g in new if g[5])
    live = [f for f in faces if f[6] is True]
    vol = sum(dot(sub(P[f[0]], cen), cross(sub(P[f[1]], cen), sub(P[f[2]], cen))) for f in live) / 6.0
    area = sum(norm(cross(sub(P[f[1]], P[f[0]]), sub(P[f[2]], P[f[0]]))) for f in live) / 2.0
    verts = sorted({i for f in live for i in f[:3]})
    normals = [(f[3], norm(cross(sub(P[f[1]], P[f[0]]), sub(P[f[2]], P[f[0]]))) / 2.0) for f in live]
    return {"volume": vol, "area": area, "faces": len(live), "vertex_ids": verts, "normals": normals}


# ---------------------------------------------------------------- oriented bounding box
def extents(points, axes):
    out = []
    for ax in axes:
        proj = [dot(p, ax) for p in points]
        out.append(max(proj) - min(proj))
    return out


def rotate_pair(axes, i, j, deg):
    a, b = axes[i], axes[j]
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    new = list(axes)
    new[i] = add(scale(a, c), scale(b, s))
    new[j] = add(scale(a, -s), scale(b, c))
    return new


def prod3(e): return e[0] * e[1] * e[2]


def frame_from_normal(n):
    a = (1.0, 0.0, 0.0) if abs(n[0]) < 0.9 else (0.0, 1.0, 0.0)
    u = cross(n, a)
    u = scale(u, 1.0 / norm(u))
    return [u, cross(n, u), n]


def obb(points, start_axes, hull_normals):
    """Approximate minimum-volume OBB.

    Candidate frames: principal axes, world axes, and the 24 largest distinct hull-face
    normals (a minimum OBB has a face flush with a hull face) with a coarse in-plane sweep.
    The four best candidates are refined by coordinate descent on all hull points.
    """
    sample = points[::max(1, len(points) // 400)]
    starts = [list(start_axes), [(1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)]]
    seen = set()
    for n, _ in sorted(hull_normals, key=lambda f: -f[1]):
        if n[0] < -1e-9 or (abs(n[0]) <= 1e-9 and (n[1] < -1e-9 or (abs(n[1]) <= 1e-9 and n[2] < 0))):
            n = scale(n, -1.0)
        key = tuple(round(x, 2) + 0.0 for x in n)
        if key in seen:
            continue
        seen.add(key)
        base = frame_from_normal(n)
        starts.append(min((rotate_pair(base, 0, 1, 6.0 * k) for k in range(15)),
                          key=lambda ax: prod3(extents(sample, ax))))
        if len(seen) >= 24:
            break
    starts.sort(key=lambda ax: prod3(extents(sample, ax)))
    return min((refine_obb(points, ax) for ax in starts[:4]), key=lambda r: prod3(r[0]))


def refine_obb(points, start_axes):
    axes = list(start_axes)
    best = extents(points, axes)
    best_vol = best[0] * best[1] * best[2]
    for step in (5.0, 1.0, 0.2, 0.05):
        improved = True
        while improved:
            improved = False
            for i, j in ((0, 1), (0, 2), (1, 2)):
                for sgn in (1.0, -1.0):
                    cand = rotate_pair(axes, i, j, sgn * step)
                    e = extents(points, cand)
                    if e[0] * e[1] * e[2] < best_vol * (1 - 1e-9):
                        axes, best, best_vol, improved = cand, e, e[0] * e[1] * e[2], True
    return best, axes


# ---------------------------------------------------------------- descriptors and classification
def planar_fraction(V, F, area_total, min_share=0.03):
    bins = {}
    for a, b, c in F:
        n = cross(sub(V[b], V[a]), sub(V[c], V[a]))
        ln = norm(n)
        if ln == 0:
            continue
        key = tuple(round(x / ln, 3) + 0.0 for x in n)
        bins[key] = bins.get(key, 0.0) + ln / 2.0
    return sum(v for v in bins.values() if v >= min_share * area_total) / area_total


def classify(d):
    labels = []
    e = sorted(d["obb_extents_mm"], reverse=True)
    if d["obb_fill"] >= 0.90:
        labels.append("box-like")
    if d["solidity"] >= 0.98:
        labels.append("convex")
    elif d["solidity"] >= 0.90:
        labels.append("mildly concave")
    else:
        labels.append("strongly concave")
    if e[2] / e[1] < 0.10:
        labels.append("thin")
    elif e[2] / e[1] < 0.25:
        labels.append("plate-like")
    if e[0] / e[1] > 1.8:
        labels.append("elongated")
    if d["planar_area_fraction"] < 0.25:
        labels.append("curved")
    elif d["planar_area_fraction"] > 0.95:
        labels.append("planar-faceted")
    pm = d["principal_moments_unit_density_mm5"]
    symmetric = abs(pm[1] - pm[0]) / pm[2] < 0.02 or abs(pm[2] - pm[1]) / pm[2] < 0.02
    if d["solidity"] < 0.90 and d["planar_area_fraction"] < 0.25 and not symmetric:
        labels.append("highly irregular")
    if (d["genus_total"] or 0) > 0:
        labels.append("through-hole (genus %d)" % d["genus_total"])
    if d["components"] > 1:
        labels.append("multi-body")
    return labels


def rel_err(a, b):
    return abs(a - b) / abs(b) if b else abs(a - b)


def frob(A): return math.sqrt(sum(A[i][j] ** 2 for i in range(3) for j in range(3)))


def analyze(path, density):
    t0 = time.perf_counter()
    raw, fmt = read_stl(path)
    V, F = weld(raw)
    topo = topology(V, F)
    lo = tuple(min(p[k] for p in V) for k in range(3))
    hi = tuple(max(p[k] for p in V) for k in range(3))
    area = sum(norm(cross(sub(V[b], V[a]), sub(V[c], V[a]))) for a, b, c in F) / 2.0
    out = {"format": fmt, "triangles": len(F), "vertices": len(V), **topo,
           "aabb_min_mm": lo, "aabb_extents_mm": sub(hi, lo), "surface_area_mm2": area}
    mid = scale(add(lo, hi), 0.5)
    vol, com, I = mass_props(V, F, mid)
    out["signed_volume_mm3"] = vol
    if not topo["consistently_oriented"]:
        out["mass_properties"] = "WITHHELD: mesh is not closed and consistently oriented"
    elif vol <= 0:
        out["mass_properties"] = "WITHHELD: closed but inverted (normals point inward); repair winding first"
    else:
        vals, vecs = eig_sym3(I)
        hull = convex_hull(V)
        hull_pts = [V[i] for i in hull["vertex_ids"]]
        ext, axes = obb(hull_pts, vecs, hull["normals"])
        aabb = out["aabb_extents_mm"]
        out.update({
            "mass_properties": "OK",
            "volume_mm3": vol, "centroid_mm": com, "inertia_about_com_unit_density_mm5": I,
            "principal_moments_unit_density_mm5": vals, "principal_axes": vecs,
            "mass_kg": vol * 1e-9 * density,
            "principal_moments_kg_m2": [x * density * 1e-15 for x in vals],
            "convex_hull_volume_mm3": hull["volume"], "convex_hull_faces": hull["faces"],
            "solidity": vol / hull["volume"],
            "obb_extents_mm": ext, "obb_axes": axes,
            "aabb_fill": vol / (aabb[0] * aabb[1] * aabb[2]), "obb_fill": vol / (ext[0] * ext[1] * ext[2]),
            "sphericity": math.pi ** (1.0 / 3.0) * (6.0 * vol) ** (2.0 / 3.0) / area,
            "planar_area_fraction": planar_fraction(V, F, area)})
        out["labels"] = classify(out)
    out["analysis_seconds"] = time.perf_counter() - t0
    return out


def compare(res, analytic):
    if not analytic or res.get("mass_properties") != "OK":
        return None
    Ia = analytic["inertia_about_com_unit_density_mm5"]
    Ic = res["inertia_about_com_unit_density_mm5"]
    diff = [[Ic[i][j] - Ia[i][j] for j in range(3)] for i in range(3)]
    return {"basis": analytic["basis"],
            "volume_rel_err": rel_err(res["volume_mm3"], analytic["volume_mm3"]),
            "com_err_mm": norm(sub(res["centroid_mm"], tuple(analytic["com_mm"]))),
            "inertia_rel_err_frobenius": frob(diff) / frob(Ia),
            "tensor_asymmetry_rel": max(abs(Ic[i][j] - Ic[j][i]) for i in range(3) for j in range(3)) / frob(Ic)}


def main(folder, out_path, density=2700.0):
    manifest = {}
    mpath = os.path.join(folder, "manifest.json")
    if os.path.exists(mpath):
        with open(mpath, encoding="utf-8") as fh:
            manifest = {p["file"]: p for p in json.load(fh)["parts"]}
    results = {}
    for root, _, files in os.walk(folder):
        for name in sorted(files):
            if name.lower().endswith(".stl"):
                path = os.path.join(root, name)
                rel = os.path.relpath(path, folder).replace(os.sep, "/")
                res = analyze(path, density)
                ref = manifest.get(rel, {})
                res["role"] = ref.get("role", "unknown")
                res["intended_labels"] = ref.get("intended_labels")
                res["analytic_check"] = compare(res, ref.get("analytic"))
                results[rel] = res
                print("%-36s %-9s %6d tris %s" % (rel, res["mass_properties"][:9], res["triangles"],
                                                   ",".join(res.get("labels", []))))
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump({"density_kg_m3": density, "results": results}, fh, indent=1)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], float(sys.argv[3]) if len(sys.argv) > 3 else 2700.0)
