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
  8. Stage 2 frame (certificate version 2): every frame item (rails, PC/104 rods, harness, stack reserve, standoffs,
     bracket boxes) listed once with the same corners wherever it is used, the four rails full length in their
     corners, the harness on its wall over the whole length except the stack break, every part checked against every
     item unless the exemption follows from a rule (a bracket's held parts, the stack boards for the rods and the
     stack reserve, a board for its own standoffs),
  9. Lemma 5 (v2.5 mounting rules): every bracket's target face lies on a wall or end-plate plane, or on the face of a
     corner rail it overlaps, and its solid touches that plane; brackets touch rails only; every part except the
     boards is held by a bracket, exempt_parts == held_parts; the PC/104 rods end on the true end plane, cover every
     stack board in z and stand inside each board's outline box; edge-on boards' standoffs reach a side wall,
 10. M4 brackets that hold several parts:
     a combined bracket (several column boxes on one target plane: its members' reserved boxes and its bridging
     boxes, each a frame item) — its solid's surface is closed (every edge in exactly two triangles, once each way),
     every triangle has its three vertices in one of its boxes, and every box starts on the target plane and extends
     to the same side; then no point outside the boxes is enclosed by them, so the solid lies in their union and the
     box arithmetic of 7 holds for it. A member box is exempt for its own part only, a bridge for its two end parts;
     every box is apart from every other bracket's boxes and the keep-outs;
     the one piece (exploratory) — its surface is closed, every vertex lies within the inner planes, no triangle
     meets any frame item or any part it does not hold grown by 1.2 mm (exact triangle–box separation, the part by
     its bounding box re-derived from its STL file) and none of them lies inside the solid (winding number), it
     touches every bolted plane it states (walls and end plates only) under that part's footprint. Its distance to
     the parts it holds is numeric (the app's FCL distance), listed, not re-checked,
and prints PASS/FAIL per lemma. Exit code 0 only if everything passes. Certificates of version 1 (before the frame
block) and layouts found under the mounting rules before v2.5 skip 8–9 / 9, with a NOTE.
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


TOL = 1e-6          # mm: a face "on" a plane (all coordinates are given to 1e-9 mm)
TOL_SOLID = 1e-5    # mm: a designed solid's bolted face on its plane (voxel grid on the plane)


def bounds(points):
    return [min(p[k] for p in points) for k in range(3)], [max(p[k] for p in points) for k in range(3)]


def same_corners(ca, cb):
    return len(ca) == len(cb) and all(abs(a - b) <= 1e-9 for p, q in zip(ca, cb) for a, b in zip(p, q))


def bracket_boxes(b):
    """The boxes of a bracket entry: [(static name, lo, hi, role, parts it is exempt for)] — one reserved box, or the
    boxes of a combined bracket (M4); none for the one piece."""
    if b.get("one_piece"):
        return []
    if b.get("multi"):
        out = []
        for bx in b.get("boxes", []):
            ex = [bx.get("part")] if bx.get("role") == "member" else list(bx.get("ends") or [])
            out.append((bx["name"], bx["box"][:3], bx["box"][3:], bx.get("role"), [p for p in ex if p]))
        return out
    return [(b["name"], b["reserve"][:3], b["reserve"][3:], "reserve", list(b.get("exempt_parts", [])))]


def closed_surface(faces):
    """Every undirected edge in exactly two triangles, used once in each direction."""
    und, dire = {}, set()
    for f in faces:
        for a, b in ((f[0], f[1]), (f[1], f[2]), (f[2], f[0])):
            if (a, b) in dire:
                return False
            dire.add((a, b))
            k = (a, b) if a < b else (b, a)
            und[k] = und.get(k, 0) + 1
    return all(c == 2 for c in und.values())


def in_box(v, lo, hi, eps=EPS):
    return all(lo[k] - eps <= v[k] <= hi[k] + eps for k in range(3))


def tri_box_separated(tri, lo, hi, eps=EPS):
    """True when the triangle does not enter the open box (lo, hi) — touching its boundary counts as separated
    (separating-axis test: the 3 box axes, the triangle normal and the 9 edge × axis directions)."""
    c = [(lo[k] + hi[k]) / 2 for k in range(3)]
    e = [(hi[k] - lo[k]) / 2 for k in range(3)]
    v = [sub(p, c) for p in tri]
    for k in range(3):
        if min(p[k] for p in v) >= e[k] - eps or max(p[k] for p in v) <= -e[k] + eps:
            return True
    f = [sub(v[1], v[0]), sub(v[2], v[1]), sub(v[0], v[2])]
    axes = [cross3(f[0], f[1])]
    for k in range(3):
        u = [0.0, 0.0, 0.0]
        u[k] = 1.0
        axes += [cross3(u, fj) for fj in f]
    for a in axes:
        na = math.sqrt(dot(a, a))
        if na < 1e-15:
            continue
        p = [dot(a, x) for x in v]
        r = e[0] * abs(a[0]) + e[1] * abs(a[1]) + e[2] * abs(a[2])
        if min(p) >= r - eps * na or max(p) <= -r + eps * na:
            return True
    return False


def multi_solid_checks(b, results, msgs):
    """Check 10 for a combined bracket: closed surface, every triangle in one of its boxes, boxes are columns on the
    target plane (the plane check itself is in Lemma 5)."""
    verts = [tuple(x) for x in b.get("solid_vertices") or []]
    faces = [tuple(x) for x in b.get("solid_faces") or []]
    if not verts or not faces:
        results["bracket_solids_in_boxes"] = False
        msgs.append(f"FAIL {b['name']}: a combined bracket without its solid's vertices and faces")
        return
    if any(not (0 <= i < len(verts)) for f in faces for i in f):
        results["bracket_solids_in_boxes"] = False
        msgs.append(f"FAIL {b['name']}: a face refers to no vertex")
        return
    if not closed_surface(faces):
        results["bracket_solids_in_boxes"] = False
        msgs.append(f"FAIL {b['name']}: its surface is not closed")
    boxes = [(lo, hi) for _, lo, hi, _, _ in bracket_boxes(b)]
    ax, neg, plane = b["axis"], b["neg"], b["plane_mm"]
    for name, lo, hi, _, _ in bracket_boxes(b):
        face = lo[ax] if neg else hi[ax]
        if abs(face - plane) > TOL or ((hi[ax] <= plane + TOL) if neg else (lo[ax] >= plane - TOL)):
            results["bracket_solids_in_boxes"] = False
            msgs.append(f"FAIL {b['name']}: box {name} is not a column on the target plane")
    inside = [[in_box(v, lo, hi) for lo, hi in boxes] for v in verts]
    for f in faces:
        if not any(inside[f[0]][k] and inside[f[1]][k] and inside[f[2]][k] for k in range(len(boxes))):
            results["bracket_solids_in_boxes"] = False
            msgs.append(f"FAIL {b['name']}: triangle {list(f)} lies in none of its boxes")
            break


def one_piece_checks(b, cert, frame, parts, results, msgs):
    """Check 10 for the one piece."""
    results["one_piece_clear"] = True

    def fail(text):
        results["one_piece_clear"] = False
        msgs.append("FAIL " + text)
    verts = [tuple(x) for x in b.get("solid_vertices") or []]
    faces = [tuple(x) for x in b.get("solid_faces") or []]
    if not verts or not faces or not frame:
        fail("the one piece without its solid or without the frame block")
        return
    if any(not (0 <= i < len(verts)) for f in faces for i in f) or not closed_surface(faces):
        fail("the one piece's surface is not closed")
        return
    planes = frame["planes_mm"]
    lo, hi = [planes[a][0] for a in "xyz"], [planes[a][1] for a in "xyz"]
    if any(not in_box(v, lo, hi) for v in verts):
        fail("a vertex of the one piece lies outside the inner planes")
    tris = [(verts[f[0]], verts[f[1]], verts[f[2]]) for f in faces]
    tlo = [[min(t[0][k], t[1][k], t[2][k]) for k in range(3)] for t in tris]
    thi = [[max(t[0][k], t[1][k], t[2][k]) for k in range(3)] for t in tris]
    slo, shi = bounds(verts)
    c = float(b.get("clearance_mm", 1.2))
    held = set(b.get("held_parts", []))
    obstacles = [(f"frame item {it['name']}", *bounds(it["corners"])) for it in frame.get("items", [])]
    obstacles += [(f"part {pid}", *bounds(p["verts"])) for pid, p in parts.items() if pid not in held]
    for name, olo, ohi in obstacles:
        glo, ghi = [olo[k] - c for k in range(3)], [ohi[k] + c for k in range(3)]
        if any(ghi[k] <= slo[k] or glo[k] >= shi[k] for k in range(3)):
            continue                                       # the grown box misses the solid's bounding box
        for t, a, z in zip(tris, tlo, thi):
            if any(z[k] <= glo[k] + EPS or a[k] >= ghi[k] - EPS for k in range(3)):
                continue
            if not tri_box_separated(t, glo, ghi):
                fail(f"the one piece comes within {c} mm of {name}")
                break
        else:
            centre = tuple((glo[k] + ghi[k]) / 2 for k in range(3))
            if winding(centre, tris) > 0.5:
                fail(f"{name} lies inside the one piece")
    for bp in b.get("bolted", []):
        ax, plane, fp = bp["axis"], bp["plane_mm"], bp["footprint"]
        want = lo[ax] if bp["neg"] else hi[ax]
        if abs(plane - want) > TOL:
            fail(f"the one piece is bolted to {'xyz'[ax]} = {plane:.6f} for {bp['part']}, not a wall or end plate")
        lat = [k for k in range(3) if k != ax]
        if not any(abs(v[ax] - plane) <= TOL_SOLID and all(fp[k] - TOL <= v[k] <= fp[3 + k] + TOL for k in lat)
                   for v in verts):
            fail(f"the one piece does not touch its bolted plane under {bp['part']}")
    if results["one_piece_clear"]:
        msgs.append(f"NOTE one piece: its distance to the {len(held)} parts it holds is numeric "
                    f"({b.get('numeric', {}).get('method', 'app')}), not re-checked")


def frame_checks(cert, frame, parts, results, msgs):
    """Checks 8 and 9 of the module docstring. parts: id -> {"verts": world vertices re-derived from the STL}."""
    planes = frame["planes_mm"]
    lo, hi = [planes[a][0] for a in "xyz"], [planes[a][1] for a in "xyz"]
    v25 = frame.get("rules") == "v2.5"
    items = {}
    for it in frame.get("items", []):
        if it["name"] in items:
            results["frame_items_complete"] = False
            msgs.append(f"FAIL frame item {it['name']} listed twice")
        items[it["name"]] = it

    def fail(key, text):
        results[key] = False
        msgs.append("FAIL " + text)
    results["frame_items_complete"] = results.get("frame_items_complete", True)
    results["exemptions_follow_rules"] = True
    # --- 8. one set of corners per item, wherever it is used
    for s in cert["statics"]:
        if s["method"] == "numeric":           # certified by the app; its corners are not used here
            continue
        if s["static"] not in items or not same_corners(items[s["static"]]["corners"], s["corners"]):
            fail("frame_items_complete", f"{s['part']} vs {s['static']}: corners differ from the frame item")
    for sp in cert.get("static_pairs", []):
        for name, c in ((sp["a"], sp["corners_a"]), (sp["b"], sp["corners_b"])):
            if name not in items or not same_corners(items[name]["corners"], c):
                fail("frame_items_complete", f"{sp['a']} vs {sp['b']}: corners of {name} differ from the frame item")
    # every part against every item: a check, or an exemption that follows from a rule
    checked = {(s["part"], s["static"]) for s in cert["statics"]}
    exempt = {(a, b) for a, b in cert.get("exempt", [])}
    owner = {}                                 # box name -> (bracket entry, the parts that box may be exempt for)
    for b in cert.get("brackets", []):
        for name, _, _, role, ex in bracket_boxes(b):
            owner[name] = (b, ex if role != "reserve" else None)
    stack_ids = list(frame.get("stack_ids") or [])
    part_ids = [p["id"] for p in cert["parts"]]
    for pid in part_ids:
        for name in items:
            if (pid, name) not in checked and (pid, name) not in exempt:
                fail("frame_items_complete", f"{pid} vs {name}: no clearance check")
    for pid, name in sorted(exempt):
        it = items.get(name)
        kind = it["kind"] if it else None
        if kind == "bracket":
            b, ex = owner.get(name, (None, None))
            if b is not None and ex is not None:        # a box of a combined bracket: its own part / its two ends
                ok = pid in ex
            else:
                ok = b is not None and pid in (b.get("held_parts", []) if v25 else b.get("exempt_parts", []))
        elif kind in ("rod", "stack"):
            ok = pid in stack_ids
        elif kind == "standoff":
            ok = name.split(":", 1)[-1] == pid
        else:
            ok = False
        if not ok:
            fail("exemptions_follow_rules", f"exemption of {pid} from {name} ({kind or 'unknown item'}) follows from no rule")
    # the four rails: full length, each in its own corner
    rails = [it for it in items.values() if it["kind"] == "rail"]
    corners_seen = set()
    for r in rails:
        rlo, rhi = bounds(r["corners"])
        if rlo[2] > lo[2] + TOL or rhi[2] < hi[2] - TOL:
            fail("frame_items_complete", f"rail {r['name']} does not run the full length")
        side = []
        for k in (0, 1):
            if rlo[k] <= lo[k] + TOL and rhi[k] < hi[k]:
                side.append(-1)
            elif rhi[k] >= hi[k] - TOL and rlo[k] > lo[k]:
                side.append(1)
        if len(side) != 2:
            fail("frame_items_complete", f"rail {r['name']} is not in a corner of the frame")
        corners_seen.add(tuple(side))
    if len(rails) != 4 or len(corners_seen) != 4:
        fail("frame_items_complete", f"{len(rails)} corner rails in {len(corners_seen)} corners (4 required)")
    # the stack and its rods
    board_box = {}
    for pid in stack_ids:
        if pid not in parts:
            fail("frame_items_complete", f"stack board {pid} is not a part of the layout")
            continue
        board_box[pid] = bounds(parts[pid]["verts"])
    rods = [it for it in items.values() if it["kind"] == "rod"]
    stacks = [it for it in items.values() if it["kind"] == "stack"]
    if stack_ids:
        if len(rods) != 4 or len(stacks) != 1:
            fail("frame_items_complete", f"PC/104 stack with {len(rods)} rods and {len(stacks)} stack reserves (4, 1)")
        for s in stacks:
            slo, shi = bounds(s["corners"])
            for pid, (blo, bhi) in board_box.items():
                if any(blo[k] < slo[k] - TOL_SOLID or bhi[k] > shi[k] + TOL_SOLID for k in range(3)):
                    fail("frame_items_complete", f"stack reserve does not contain board {pid}")
    elif rods or stacks:
        fail("frame_items_complete", "rods or a stack reserve without stack boards")
    # the harness on its wall, over the whole length except the break across the stack
    hw = frame.get("harness_wall")
    segs = [bounds(it["corners"]) for it in items.values() if it["kind"] == "harness"]
    if hw:
        ax = "xyz".index(hw[1])
        if not segs:
            fail("frame_items_complete", f"no harness item on the {hw} wall")
        for slo, shi in segs:
            if (shi[ax] < hi[ax] - TOL) if hw[0] == "+" else (slo[ax] > lo[ax] + TOL):
                fail("frame_items_complete", f"a harness segment is off the {hw} wall")
        brk = None
        if stacks:
            slo, shi = bounds(stacks[0]["corners"])
            g = float(frame.get("harness_break_mm", 0.0))
            brk = (slo[2] - g - TOL, shi[2] + g + TOL)
        z = lo[2]
        for a, b in sorted((s[0][2], s[1][2]) for s in segs) + [(hi[2], hi[2])]:
            if a > z + TOL and (brk is None or z < brk[0] or a > brk[1]):
                fail("frame_items_complete", f"the harness leaves z = {z:.3f} … {a:.3f} mm open outside the stack break")
            z = max(z, b)
    elif segs:
        fail("frame_items_complete", "harness items without a harness wall")
    if not v25:
        msgs.append(f"NOTE  mounting rules '{frame.get('rules')}' (before v2.5): brackets could be fixed to the PC/104 "
                    "deck; Lemma 5 (chassis-only attachment, rods to the end plate) is not checked")
        return
    # --- 9. Lemma 5
    results["brackets_fixed_to_chassis"] = True
    results["every_part_held"] = True
    results["stack_rods_to_end_plate"] = True
    held = {}
    for b in cert.get("brackets", []):
        if b.get("one_piece"):                         # bolted to walls / end plates: checked in one_piece_checks
            hp = list(b.get("held_parts", []))
            if not hp or sorted(set(b.get("exempt_parts", []))) != sorted(set(hp)):
                fail("every_part_held", f"{b['name']}: exempt parts are not its held parts")
            for p in hp:
                held.setdefault(p, []).append(b["name"])
            continue
        name, kind, ax, neg, plane = b["name"], b.get("target_kind"), b.get("axis"), b.get("neg"), b.get("plane_mm")
        if kind not in ("wall", "end_plate", "rail") or ax not in (0, 1, 2) or plane is None or neg is None:
            fail("brackets_fixed_to_chassis", f"{name} is fixed to {kind or 'nothing stated'}, not to the chassis")
            continue
        for bname, blo, bhi, _, _ in bracket_boxes(b):
            r = [*blo, *bhi]
            face = r[ax] if neg else r[3 + ax]
            if abs(face - plane) > TOL or ((r[3 + ax] <= plane + TOL) if neg else (r[ax] >= plane - TOL)):
                fail("brackets_fixed_to_chassis", f"{name}: its box {bname} does not start on its target plane")
        r = b["reserve"]
        ts = list(b.get("target_statics", []))
        if kind in ("wall", "end_plate"):
            want = (lo[ax] if neg else hi[ax])
            if (kind == "wall") != (ax in (0, 1)) or abs(plane - want) > TOL or ts:
                fail("brackets_fixed_to_chassis", f"{name}: {'xyz'[ax]} = {plane:.6f} is not the "
                                                  f"{'-' if neg else '+'}{'xyz'[ax]} {kind.replace('_', ' ')}")
        else:
            rail = items.get(ts[0]) if len(ts) == 1 else None
            if rail is None or rail["kind"] != "rail" or ax == 2:
                fail("brackets_fixed_to_chassis", f"{name}: fixed to a rail that is not one corner rail ({ts})")
            else:
                rlo, rhi = bounds(rail["corners"])
                for bname, blo, bhi, _, _ in bracket_boxes(b):          # every box of it on the rail's face
                    rb = [*blo, *bhi]
                    lap = all(min(rb[3 + k], rhi[k]) - max(rb[k], rlo[k]) > TOL for k in range(3) if k != ax)
                    if abs((rhi[ax] if neg else rlo[ax]) - plane) > TOL or not lap:
                        fail("brackets_fixed_to_chassis", f"{name}: {bname} is not on the face of {ts[0]} it overlaps")
        if any(items.get(t, {}).get("kind") != "rail" for t in ts):
            fail("brackets_fixed_to_chassis", f"{name} may touch {ts}: only a corner rail may be touched")
        sv = b.get("solid_vertices") or []
        if sv and min(abs(v[ax] - plane) for v in sv) > TOL_SOLID:
            fail("brackets_fixed_to_chassis", f"{name}: its solid does not touch its target plane")
        hp = list(b.get("held_parts", []))
        if not hp or sorted(set(b.get("exempt_parts", []))) != sorted(set(hp)) or b.get("part") not in hp:
            fail("every_part_held", f"{name}: exempt parts {b.get('exempt_parts')} are not its held parts {hp}")
        for p in hp:
            held.setdefault(p, []).append(name)
    standoff_parts = set()
    for it in items.values():
        if it["kind"] != "standoff":
            continue
        pid = it["name"].split(":", 1)[-1]
        standoff_parts.add(pid)
        slo, shi = bounds(it["corners"])
        if not any(slo[k] <= lo[k] + TOL or shi[k] >= hi[k] - TOL for k in (0, 1)):
            fail("every_part_held", f"{it['name']} does not reach a side wall")
    for pid in part_ids:
        if pid not in held and pid not in stack_ids and pid not in standoff_parts:
            fail("every_part_held", f"{pid} is held by no bracket, rod or standoff")
    for pid in held:
        if pid not in part_ids:
            fail("every_part_held", f"a bracket holds {pid}, which is not a part of the layout")
    if stack_ids:
        end = frame.get("rod_end")
        if end not in ("-z", "+z"):
            fail("stack_rods_to_end_plate", f"PC/104 rods run to no end plate ({end})")
            return
        plane = lo[2] if end == "-z" else hi[2]
        for r in rods:
            rlo, rhi = bounds(r["corners"])
            if abs((rlo[2] if end == "-z" else rhi[2]) - plane) > TOL:
                fail("stack_rods_to_end_plate", f"{r['name']} ends short of the {end} end plate (z = {plane:.3f})")
            for pid, (blo, bhi) in board_box.items():
                if rlo[2] > blo[2] + TOL or rhi[2] < bhi[2] - TOL:
                    fail("stack_rods_to_end_plate", f"{r['name']} does not cover board {pid} in z")
                if any(rlo[k] < blo[k] - TOL or rhi[k] > bhi[k] + TOL for k in (0, 1)):
                    fail("stack_rods_to_end_plate", f"{r['name']} stands outside the outline of board {pid}")


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
        if s["method"] == "numeric":       # certified by the app (compound boxes / exact distance): counted below
            continue
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
    names = [x[0] for b in cert.get("brackets", []) for x in bracket_boxes(b)]     # every bracket box
    for b in cert.get("brackets", []):
        if b.get("one_piece"):
            continue                                   # check 10, after the frame checks
        own = bracket_boxes(b)
        own_names = {x[0] for x in own}
        for name, lo, hi, role, ex in own:
            c = static_corners.get(name)
            if c is None or any(abs(min(p[k] for p in c) - lo[k]) > 1e-6 or abs(max(p[k] for p in c) - hi[k]) > 1e-6
                                for k in range(3)):
                results["bracket_checks_complete"] = False
                msgs.append(f"FAIL {b['name']}: its box {name} differs from the box used in the clearance checks")
            for p in cert["parts"]:      # every part except those the box may touch is checked against it
                if p["id"] in ex:
                    if (p["id"], name) not in exempt:
                        results["bracket_checks_complete"] = False
                        msgs.append(f"FAIL {name}: exemption of {p['id']} not declared")
                elif (p["id"], name) not in checked:
                    results["bracket_checks_complete"] = False
                    msgs.append(f"FAIL {p['id']} vs {name}: no clearance check")
            keepouts = [n for n in static_corners if n not in names and n not in b.get("target_statics", [])]
            for o in [n for n in names if n not in own_names] + keepouts:
                if frozenset((o, name)) not in pair_set:
                    results["bracket_checks_complete"] = False
                    msgs.append(f"FAIL {name} vs {o}: no box-gap check")
        if b.get("multi"):
            multi_solid_checks(b, results, msgs)
        else:
            lo, hi = b["reserve"][:3], b["reserve"][3:]
            for v in b["solid_vertices"]:
                if any(v[k] < lo[k] - EPS or v[k] > hi[k] + EPS for k in range(3)):
                    results["bracket_solids_in_boxes"] = False
                    msgs.append(f"FAIL {b['name']}: solid vertex {v} outside its reserved box")
                    break
        if b.get("estimate"):
            msgs.append(f"NOTE {b['name']}: {b['kind']} not designed yet — its reserved box is certified, no solid")
    # Stage 2 frame and Lemma 5 (certificate version 2)
    frame = cert.get("frame")
    if cert.get("stage") == 2 and int(cert.get("certificate_version", 1)) >= 2 and not frame:
        results["frame_items_complete"] = False
        msgs.append("FAIL Stage 2 certificate of version 2 without its frame block")
    elif frame:
        frame_checks(cert, frame, parts, results, msgs)
    elif cert.get("stage") == 2:
        msgs.append("NOTE  certificate version 1 (no frame block): frame items and bracket attachment not checked")
    for b in cert.get("brackets", []):                 # check 10: the one piece (M4)
        if b.get("one_piece"):
            one_piece_checks(b, cert, frame, parts, results, msgs)
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
