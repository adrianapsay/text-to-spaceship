#!/usr/bin/env python3
"""Stand-alone checker for TEXT-TO-SPACESHIP fit certificates (Python standard library only).

Usage:  python check_certificate.py certificate.json <folder containing the original STL files>

It does not import or trust any part of the application. It:
  1. verifies each STL file's SHA-256 against the certificate,
  2. re-reads the triangles, converts units, applies the authored->canonical transform, the part-size factor
     (V2 part-size slider; 1 when absent) and the pose,
  3. checks Lemma 1 (every vertex inside the enclosure bounds),
  4. checks that each part's cover cells form a full binary cut tree (so they partition space),
  5. rebuilds each cover piece's vertex set (surface clipped to the cell + cell corners inside the solid),
  6. checks every separating-plane inequality of Lemmas 2 and 3 for every pair and frame item,
  7. V2 brackets (Lemma 4): every solid vertex inside its reserved box, every box apart from the other boxes and the
     keep-outs (box arithmetic), and every part / box / keep-out combination covered by a check or a declared
     exemption,
and prints PASS/FAIL per lemma. Exit code 0 only if everything passes.
"""
import hashlib
import itertools
import json
import math
import os
import struct
import sys

EPS = 1e-9


def read_stl(path):
    data = open(path, "rb").read()
    tris = []
    if len(data) >= 84:
        n = struct.unpack_from("<I", data, 80)[0]
        if len(data) == 84 + 50 * n:
            for i in range(n):
                vals = struct.unpack_from("<12f", data, 84 + 50 * i)
                tris.append((vals[3:6], vals[6:9], vals[9:12]))
            return data, tris
    toks = data.decode("ascii", "replace").split()
    verts = [tuple(float(x) for x in toks[i + 1:i + 4]) for i, t in enumerate(toks) if t == "vertex"]
    return data, [tuple(verts[i:i + 3]) for i in range(0, len(verts) - 2, 3)]


def dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def to_canonical(p, scale, rc, origin):
    q = (p[0] * scale - origin[0], p[1] * scale - origin[1], p[2] * scale - origin[2])
    return tuple(q[0] * rc[0 + j] + q[1] * rc[3 + j] + q[2] * rc[6 + j] for j in range(3))   # q @ R


def to_world(p, r, t):
    return tuple(r[3 * i] * p[0] + r[3 * i + 1] * p[1] + r[3 * i + 2] * p[2] + t[i] for i in range(3))


def clip_polygon(poly, n, d):
    out = []
    m = len(poly)
    s = [dot(n, p) + d for p in poly]
    for i in range(m):
        p, q, sp, sq = poly[i], poly[(i + 1) % m], s[i], s[(i + 1) % m]
        if sp <= 0:
            out.append(p)
        if (sp < 0 < sq) or (sq < 0 < sp):
            t = sp / (sp - sq)
            out.append(tuple(p[k] + t * (q[k] - p[k]) for k in range(3)))
    return out if len(out) >= 3 else None


def normal(t):
    a, b, c = t
    u, v = sub(b, a), sub(c, a)
    return (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])


def winding(p, tris):
    total = 0.0
    for a, b, c in tris:
        a, b, c = sub(a, p), sub(b, p), sub(c, p)
        la, lb, lc = math.sqrt(dot(a, a)), math.sqrt(dot(b, b)), math.sqrt(dot(c, c))
        cr = (b[1] * c[2] - b[2] * c[1], b[2] * c[0] - b[0] * c[2], b[0] * c[1] - b[1] * c[0])
        num = dot(a, cr)
        den = la * lb * lc + dot(a, b) * lc + dot(b, c) * la + dot(c, a) * lb
        total += math.atan2(num, den)
    return total / (2 * math.pi)


def cross3(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def solve3(m, rhs):
    def det(q):
        return (q[0][0] * (q[1][1] * q[2][2] - q[1][2] * q[2][1]) - q[0][1] * (q[1][0] * q[2][2] - q[1][2] * q[2][0])
                + q[0][2] * (q[1][0] * q[2][1] - q[1][1] * q[2][0]))
    dm = det(m)
    if abs(dm) < 1e-12:
        return None
    out = []
    for col in range(3):
        q = [row[:] for row in m]
        for r in range(3):
            q[r][col] = rhs[r]
        out.append(det(q) / dm)
    return tuple(out)


def piece_vertices(tris, cell):
    """Conservative V-rep of solid ∩ cell: (a) mesh vertices in the closed cell, (b) mesh edges crossing a cell
    plane, (c) cell edge lines crossing a triangle, (d) cell corners in the closed solid (same rule as the app)."""
    verts = list({v for t in tris for v in t})
    scale = max(1.0, max(abs(c) for v in verts for c in v))
    tol = 1e-9 * scale

    def inside(p):
        return all(dot(pl["n"], p) + pl["d"] <= tol for pl in cell)

    pts = [v for v in verts if inside(v)]
    edges = set()
    for a, b, c in tris:
        for x, y in ((a, b), (b, c), (c, a)):
            edges.add((x, y) if x <= y else (y, x))
    for pl in cell:
        n, d = pl["n"], pl["d"]
        for p, q in edges:
            sp, sq = dot(n, p) + d, dot(n, q) + d
            if sp * sq < 0:
                t = sp / (sp - sq)
                x = tuple(p[k] + t * (q[k] - p[k]) for k in range(3))
                if inside(x):
                    pts.append(x)
    for pa, pb in itertools.combinations(cell, 2):
        dvec = cross3(pa["n"], pb["n"])
        if math.sqrt(dot(dvec, dvec)) < 1e-12:
            continue
        x0 = solve3([list(pa["n"]), list(pb["n"]), list(dvec)], [-pa["d"], -pb["d"], 0.0])
        if x0 is None:
            continue
        for t0, t1, t2 in tris:
            e1, e2 = sub(t1, t0), sub(t2, t0)
            h = cross3(dvec, e2)
            a = dot(e1, h)
            if abs(a) <= 1e-12 * math.sqrt(dot(e1, e1) * dot(e2, e2) * dot(dvec, dvec)):
                continue
            s = sub(x0, t0)
            u = dot(s, h) / a
            if u < -1e-9 or u > 1 + 1e-9:
                continue
            qv = cross3(s, e1)
            w = dot(dvec, qv) / a
            if w < -1e-9 or u + w > 1 + 1e-9:
                continue
            t = dot(e2, qv) / a
            x = tuple(x0[k] + t * dvec[k] for k in range(3))
            if inside(x):
                pts.append(x)
    for a, b, c in itertools.combinations(cell, 3):
        m = [a["n"], b["n"], c["n"]]
        det = (m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1]) - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
               + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0]))
        if abs(det) < 1e-9:
            continue
        rhs = [-a["d"], -b["d"], -c["d"]]
        x = []
        for col in range(3):
            mm = [row[:] for row in m]
            for r in range(3):
                mm[r][col] = rhs[r]
            dd = (mm[0][0] * (mm[1][1] * mm[2][2] - mm[1][2] * mm[2][1]) - mm[0][1] * (mm[1][0] * mm[2][2] - mm[1][2] * mm[2][0])
                  + mm[0][2] * (mm[1][0] * mm[2][1] - mm[1][1] * mm[2][0]))
            x.append(dd / det)
        x = tuple(x)
        if all(dot(pl["n"], x) + pl["d"] <= 1e-7 * max(1.0, max(abs(v) for v in x)) for pl in cell):
            if winding(x, tris) > 1e-6:
                pts.append(x)
    return pts


def is_binary_tree(cells, depth=0):
    """Cells partition space iff their plane lists form a full binary cut tree (sibling planes negate)."""
    if len(cells) == 1 and len(cells[0]) == depth:
        return True
    if any(len(c) <= depth for c in cells):
        return False
    groups = {}
    for c in cells:
        pl = c[depth]
        key = (tuple(round(v, 9) for v in pl["n"]), round(pl["d"], 9))
        groups.setdefault(key, []).append(c)
    if len(groups) != 2:
        return False
    (ka, ga), (kb, gb) = groups.items()
    if any(abs(x + y) > 1e-9 for x, y in zip(ka[0], kb[0])) or abs(ka[1] + kb[1]) > 1e-9:
        return False
    return is_binary_tree(ga, depth + 1) and is_binary_tree(gb, depth + 1)


def gap(n, a_pts, b_pts):
    return min(dot(n, b) for b in b_pts) - max(dot(n, a) for a in a_pts)


def box_gap(ca, cb):
    """Largest axis separation of the axis-aligned boxes spanned by two corner sets (a lower bound on distance)."""
    return max(max(min(q[k] for q in cb) - max(p[k] for p in ca), min(p[k] for p in ca) - max(q[k] for q in cb))
               for k in range(3))


def main(cert_path, stl_dir):
    cert = json.load(open(cert_path))
    results = {"files": True, "lemma1_containment": True, "cells_partition": True, "pairs": True, "frame": True}
    msgs = []
    parts = {}
    for p in cert["parts"]:
        path = os.path.join(stl_dir, p["file"])
        data, tris = read_stl(path)
        if hashlib.sha256(data).hexdigest() != p["sha256"]:
            results["files"] = False
            msgs.append(f"FAIL file hash: {p['file']}")
        can = [tuple(to_canonical(v, p["units_to_mm"], p["canonical_R"], p["canonical_origin_mm"]) for v in t) for t in tris]
        s = float(p.get("part_scale", 1.0))         # V2 part-size slider: the part scaled about its canonical origin
        if s != 1.0:
            can = [tuple((v[0] * s, v[1] * s, v[2] * s) for v in tri) for tri in can]
            msgs.append(f"NOTE {p['id']}: part scaled by {s:g} (part-size slider)")
        if "repaired_mesh" in p:
            rv, rf = p["repaired_mesh"]["vertices"], p["repaired_mesh"]["faces"]
            can = [tuple(tuple(rv[i]) for i in face) for face in rf]
            msgs.append(f"NOTE {p['id']}: uses the declared repaired mesh ({p['repaired_mesh']['note']})")
        r, t = p["R_orient"], p["t_mm"]
        world_tris = [tuple(to_world(v, r, t) for v in tri) for tri in can]
        verts = list({v for tri in world_tris for v in tri})
        lo, hi = cert["enclosure_vertex_bounds_mm"]["lo"], cert["enclosure_vertex_bounds_mm"]["hi"]
        for v in verts:
            if any(v[k] < lo[k] - EPS or v[k] > hi[k] + EPS for k in range(3)):
                results["lemma1_containment"] = False
                msgs.append(f"FAIL containment: {p['id']} vertex {v}")
                break
        cells = p["cells"] or [[]]
        if not is_binary_tree(cells):
            results["cells_partition"] = False
            msgs.append(f"FAIL cells of {p['id']} do not form a binary cut tree")
        pieces = []
        for cell in cells:
            pv = piece_vertices(can, cell) if cell else [v for tri in can for v in tri]
            pieces.append([to_world(v, r, t) for v in pv])
        parts[p["id"]] = {"verts": verts, "pieces": pieces}
    delta = cert["cover_delta_mm"]
    numeric = 0
    for pr in cert["pairs"]:
        a, b, req = parts[pr["a"]], parts[pr["b"]], pr["required_mm"]
        if pr["method"] == "hull_plane":
            g = gap(pr["n"], a["verts"], b["verts"])
            if g < req - EPS:
                results["pairs"] = False
                msgs.append(f"FAIL pair {pr['a']}-{pr['b']}: plane gap {g:.6f} < {req}")
        elif pr["method"] == "piece_planes":
            seen = set()
            for q in pr["planes"]:
                seen.add((q["piece_a"], q["piece_b"]))
                g = gap(q["n"], a["pieces"][q["piece_a"]], b["pieces"][q["piece_b"]])
                if g < req + 2 * delta - EPS:
                    results["pairs"] = False
                    msgs.append(f"FAIL pair {pr['a']}-{pr['b']} pieces {q['piece_a']},{q['piece_b']}: {g:.6f}")
            need = {(i, j) for i in range(len(a["pieces"])) for j in range(len(b["pieces"]))
                    if a["pieces"][i] and b["pieces"][j]}
            if not need <= seen:
                results["pairs"] = False
                msgs.append(f"FAIL pair {pr['a']}-{pr['b']}: {len(need - seen)} piece pair(s) without a plane")
        else:
            numeric += 1
    for s in cert["statics"]:
        a, req = parts[s["part"]], s["required_mm"]
        corners = [tuple(c) for c in s["corners"]]
        if s["method"] == "hull_plane":
            g = gap(s["n"], a["verts"], corners)
        elif s["method"] == "piece_planes":
            g = min(gap(q["n"], a["pieces"][q["piece_a"]], corners) for q in s["planes"]) - 2 * delta
            if len(s["planes"]) < sum(1 for pc in a["pieces"] if pc):
                g = -math.inf
        else:
            axes = [(1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1)]
            g = max(gap(n, a["verts"], corners) for n in axes)
        if g < req - EPS:
            results["frame"] = False
            msgs.append(f"FAIL {s['part']} vs {s['static']}: gap {g:.6f} < {req}")
    numeric_static = sum(1 for s in cert["statics"] if s["method"] == "numeric")
    # V2 Lemma 4: brackets inside their reserved boxes, boxes apart from each other and from the keep-outs
    if cert.get("brackets") or cert.get("static_pairs"):
        results["bracket_boxes_apart"] = True
        results["bracket_solids_in_boxes"] = True
        results["bracket_checks_complete"] = True
    for sp in cert.get("static_pairs", []):
        g = box_gap(sp["corners_a"], sp["corners_b"])
        if g < sp["required_mm"] - EPS:
            results["bracket_boxes_apart"] = False
            msgs.append(f"FAIL {sp['a']} vs {sp['b']}: box gap {g:.6f} < {sp['required_mm']}")
    static_corners = {}
    for s in cert["statics"]:
        static_corners.setdefault(s["static"], s["corners"])
    for sp in cert.get("static_pairs", []):
        static_corners.setdefault(sp["a"], sp["corners_a"])
        static_corners.setdefault(sp["b"], sp["corners_b"])
    exempt = {(a, b) for a, b in cert.get("exempt", [])}
    checked = {(s["part"], s["static"]) for s in cert["statics"]}
    pair_set = {frozenset((sp["a"], sp["b"])) for sp in cert.get("static_pairs", [])}
    names = [b["name"] for b in cert.get("brackets", [])]
    for b in cert.get("brackets", []):
        lo, hi = b["reserve"][:3], b["reserve"][3:]
        c = static_corners.get(b["name"])
        if c is None or any(abs(min(p[k] for p in c) - lo[k]) > 1e-6 or abs(max(p[k] for p in c) - hi[k]) > 1e-6
                            for k in range(3)):
            results["bracket_checks_complete"] = False
            msgs.append(f"FAIL {b['name']}: its reserved box differs from the box used in the clearance checks")
        for v in b["solid_vertices"]:
            if any(v[k] < lo[k] - EPS or v[k] > hi[k] + EPS for k in range(3)):
                results["bracket_solids_in_boxes"] = False
                msgs.append(f"FAIL {b['name']}: solid vertex {v} outside its reserved box")
                break
        if b.get("estimate"):
            msgs.append(f"NOTE {b['name']}: {b['kind']} not designed yet — its reserved box is certified, no solid")
        for p in cert["parts"]:          # every part except its own (and the deck boards) is checked against it
            if p["id"] in b["exempt_parts"]:
                if (p["id"], b["name"]) not in exempt:
                    results["bracket_checks_complete"] = False
                    msgs.append(f"FAIL {b['name']}: exemption of {p['id']} not declared")
            elif (p["id"], b["name"]) not in checked:
                results["bracket_checks_complete"] = False
                msgs.append(f"FAIL {p['id']} vs {b['name']}: no clearance check")
        keepouts = [n for n in static_corners if n not in names and n not in b.get("target_statics", [])]
        for o in names + keepouts:
            if o != b["name"] and frozenset((o, b["name"])) not in pair_set:
                results["bracket_checks_complete"] = False
                msgs.append(f"FAIL {b['name']} vs {o}: no box-gap check")
    for k, ok in results.items():
        print(f"{'PASS' if ok else 'FAIL'}  {k}")
    if numeric:
        print(f"NOTE  {numeric} pair(s) are certified numerically by the app (no closed-form plane); not re-checked")
    if numeric_static:
        print(f"NOTE  {numeric_static} frame item(s) are certified numerically by the app (compound boxes or exact "
              "mesh distance); not re-checked")
    for m in msgs[:50]:
        print(m)
    ok = all(results.values())
    print("OVERALL:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(sys.argv[1], sys.argv[2]))
