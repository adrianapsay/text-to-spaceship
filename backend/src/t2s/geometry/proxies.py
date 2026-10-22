"""Conservative proxies for collision search (protocol §D.3, naming G0-G4).

G1  compound boxes (<= 6 AABBs in the canonical frame) containing the part
G2  convex hull of the vertices (the part lies inside conv(V))
G3  planar-cut convex cover: a cut tree of half-spaces; each leaf cell's solid piece lies inside the convex
    hull of the part's boundary fragments clipped to that cell (this is what the fit-proof checker re-derives)

Every proxy carries a containment certificate result; uncertified proxies are never used to prove separation.
"""
from dataclasses import dataclass, field
from itertools import permutations

import numpy as np
from scipy.spatial import ConvexHull

from .mesh import ray_parity_inside
from .voxel import conservative_voxels

EPS_BOX = 1e-6   # mm: inflation of proxy boxes to keep containment strict
COVER_DELTA = 1e-4  # mm (0.1 µm): convex covers are certified to contain the part up to this L∞ inflation;
                    # separation proofs built on cover pieces add 2·COVER_DELTA to the required gap


# ----------------------------------------------------------------------------- G1 compound boxes
def _clusters(vals: np.ndarray, tol: float = 1e-5):
    """Group sorted coordinates closer than tol; returns (lows, highs) per group."""
    s = np.sort(vals)
    groups_lo, groups_hi = [s[0]], [s[0]]
    for x in s[1:]:
        if x - groups_hi[-1] <= tol:
            groups_hi[-1] = x
        else:
            groups_lo.append(x)
            groups_hi.append(x)
    return np.array(groups_lo), np.array(groups_hi)


def is_rectilinear(v: np.ndarray, f: np.ndarray, tol: float = 1e-6) -> bool:
    n = np.cross(v[f[:, 1]] - v[f[:, 0]], v[f[:, 2]] - v[f[:, 0]])
    n /= np.linalg.norm(n, axis=1, keepdims=True)
    a = np.abs(n)
    return bool(np.all((np.abs(a - 1) < tol) | (a < tol)))


def _greedy_boxes(occ: np.ndarray) -> list[tuple[np.ndarray, np.ndarray]]:
    remaining = occ.copy()
    boxes = []
    shape = np.array(occ.shape)
    while remaining.any():
        seed = np.argwhere(remaining)[0]
        best = None
        for order in permutations(range(3)):
            lo = seed.copy()
            hi = seed + 1
            for ax in order:
                for direction in (1, -1):
                    while True:
                        if direction == 1 and hi[ax] >= shape[ax]:
                            break
                        if direction == -1 and lo[ax] <= 0:
                            break
                        sl = [slice(lo[k], hi[k]) for k in range(3)]
                        sl[ax] = slice(hi[ax], hi[ax] + 1) if direction == 1 else slice(lo[ax] - 1, lo[ax])
                        if occ[tuple(sl)].all():
                            if direction == 1:
                                hi[ax] += 1
                            else:
                                lo[ax] -= 1
                        else:
                            break
            vol = int(np.prod(hi - lo))
            if best is None or vol > best[2]:
                best = (lo.copy(), hi.copy(), vol)
        lo, hi, _ = best
        remaining[lo[0]:hi[0], lo[1]:hi[1], lo[2]:hi[2]] = False
        boxes.append((lo, hi))
    return boxes


def _merge_boxes(boxes: np.ndarray, k: int) -> np.ndarray:
    """Merge (n, 6) [min, max] boxes pairwise by smallest union-volume increase until <= k remain."""
    boxes = boxes.copy()
    while len(boxes) > k:
        lo = np.minimum(boxes[:, None, :3], boxes[None, :, :3])
        hi = np.maximum(boxes[:, None, 3:], boxes[None, :, 3:])
        uv = np.prod(hi - lo, axis=2)
        vol = np.prod(boxes[:, 3:] - boxes[:, :3], axis=1)
        cost = uv - vol[:, None] - vol[None, :]
        np.fill_diagonal(cost, np.inf)
        i, j = np.unravel_index(np.argmin(cost), cost.shape)
        merged = np.concatenate([np.minimum(boxes[i, :3], boxes[j, :3]), np.maximum(boxes[i, 3:], boxes[j, 3:])])
        keep = [m for m in range(len(boxes)) if m not in (i, j)]
        boxes = np.vstack([boxes[keep], merged[None]])
        # drop boxes fully inside another
        inside = np.zeros(len(boxes), dtype=bool)
        for a in range(len(boxes)):
            for b in range(len(boxes)):
                if a != b and not inside[b] and np.all(boxes[a, :3] >= boxes[b, :3] - 1e-12) \
                        and np.all(boxes[a, 3:] <= boxes[b, 3:] + 1e-12):
                    inside[a] = True
                    break
        boxes = boxes[~inside]
    return boxes


def compound_boxes(v: np.ndarray, f: np.ndarray, k: int = 6) -> tuple[np.ndarray, str]:
    """Return ((m, 6) boxes [xmin, ymin, zmin, xmax, ymax, zmax] in mm, method)."""
    if is_rectilinear(v, f):
        groups = [_clusters(v[:, a]) for a in range(3)]
        if all(len(g[0]) <= 40 for g in groups):
            mids = [0.5 * (g[0] + g[1]) for g in groups]
            cx, cy, cz = (0.5 * (m[1:] + m[:-1]) for m in mids)
            centres = np.stack(np.meshgrid(cx, cy, cz, indexing="ij"), axis=-1).reshape(-1, 3)
            inside = ray_parity_inside(centres, v, f) > 0.5
            occ = inside.reshape(len(cx), len(cy), len(cz))
            raw = _greedy_boxes(occ)
            # lower box faces use the group minimum, upper faces the group maximum: exact and containing
            boxes = np.array([[groups[0][0][lo[0]], groups[1][0][lo[1]], groups[2][0][lo[2]],
                               groups[0][1][hi[0]], groups[1][1][hi[1]], groups[2][1][hi[2]]] for lo, hi in raw])
            boxes = _merge_boxes(boxes, k)
            return _inflate(boxes), "exact-rectilinear" if len(raw) <= k else "rectilinear-merged"
    return _inflate(slab_boxes(v, f, k)), "slab-stack"


def slab_boxes(v: np.ndarray, f: np.ndarray, k: int = 6) -> np.ndarray:
    """Optimal stack of <= k axis-aligned slabs along the best axis (dynamic programming).

    Each slab box is the exact AABB of the part's surface clipped to the slab, so the stack contains the part.
    """
    tri = v[f]
    tlo, thi = tri.min(axis=1), tri.max(axis=1)
    best = None
    for axis in range(3):
        lo_a, hi_a = float(v[:, axis].min()), float(v[:, axis].max())
        n_layers = 48
        cuts = np.linspace(lo_a, hi_a, n_layers + 1)
        # conservative AABB of the surface within each layer: union of the AABBs of the triangles touching
        # the layer, clamped to the layer along the slab axis (contains the exact clipped AABB)
        lay = np.full((n_layers, 6), np.nan)
        for i in range(n_layers):
            m = (thi[:, axis] >= cuts[i]) & (tlo[:, axis] <= cuts[i + 1])
            if m.any():
                lay[i, :3] = tlo[m].min(axis=0)
                lay[i, 3:] = thi[m].max(axis=0)
                lay[i, axis] = max(lay[i, axis], cuts[i])
                lay[i, 3 + axis] = min(lay[i, 3 + axis], cuts[i + 1])
        valid = ~np.isnan(lay[:, 0])

        def seg_box(a, b):
            sub = lay[a:b][valid[a:b]]
            if len(sub) == 0:
                return None, 0.0
            bx = np.concatenate([sub[:, :3].min(axis=0), sub[:, 3:].max(axis=0)])
            return bx, float(np.prod(bx[3:] - bx[:3]))

        cost = np.full((n_layers + 1, k + 1), np.inf)
        arg = np.zeros((n_layers + 1, k + 1), dtype=np.int64)
        cost[0, 0] = 0.0
        segv = {}
        for b in range(1, n_layers + 1):
            for a in range(b):
                segv[(a, b)] = seg_box(a, b)[1]
        for j in range(1, k + 1):
            for b in range(1, n_layers + 1):
                for a in range(b):
                    c = cost[a, j - 1] + segv[(a, b)]
                    if c < cost[b, j]:
                        cost[b, j] = c
                        arg[b, j] = a
        j = int(np.argmin(cost[n_layers, 1:])) + 1
        segs, b = [], n_layers
        while b > 0:
            a = arg[b, j]
            segs.append((a, b))
            b, j = a, j - 1
        boxes = [seg_box(a, b)[0] for a, b in reversed(segs)]
        boxes = np.array([bx for bx in boxes if bx is not None])
        vol = float(np.prod(boxes[:, 3:] - boxes[:, :3], axis=1).sum())
        if best is None or vol < best[0]:
            best = (vol, boxes)
    return best[1]


def _inflate(boxes: np.ndarray) -> np.ndarray:
    out = boxes.astype(np.float64).copy()
    out[:, :3] -= EPS_BOX
    out[:, 3:] += EPS_BOX
    return out


def certify_boxes(v: np.ndarray, f: np.ndarray, boxes: np.ndarray) -> tuple[bool, str]:
    inside_any = np.zeros(len(v), dtype=bool)
    for b in boxes:
        inside_any |= np.all((v >= b[:3]) & (v <= b[3:]), axis=1)
    if not inside_any.all():
        return False, f"{int((~inside_any).sum())} vertices outside the boxes"
    try:
        import manifold3d as m3d
        part = _to_manifold(v, f)
        union = None
        for b in boxes:
            cube = m3d.Manifold.cube(list(b[3:] - b[:3])).translate(list(b[:3]))
            union = cube if union is None else union + cube
        diff = part - union
        ntri = diff.num_tri()
        if ntri != 0:
            return False, f"boolean difference part − boxes is not empty ({ntri} triangles, " \
                          f"volume {diff.volume():.3g} mm³)"
    except Exception as exc:  # noqa: BLE001
        return False, f"boolean check unavailable: {exc}"
    return True, "every vertex inside a box and part − boxes is empty"


def _to_manifold(v: np.ndarray, f: np.ndarray):
    import manifold3d as m3d
    if hasattr(m3d, "Mesh64"):
        mesh = m3d.Mesh64(vert_properties=np.asarray(v, dtype=np.float64), tri_verts=np.asarray(f, dtype=np.uint64))
    else:
        mesh = m3d.Mesh(vert_properties=np.asarray(v, dtype=np.float32), tri_verts=np.asarray(f, dtype=np.uint32))
    man = m3d.Manifold(mesh)
    status = man.status()
    if str(status) not in ("Error.NoError", "NoError") and "NoError" not in str(status):
        raise ValueError(f"manifold status {status}")
    return man


# ----------------------------------------------------------------------------- G3 planar-cut covers
@dataclass
class CoverPiece:
    planes: list[tuple[np.ndarray, float]]     # half-spaces n·x + d <= 0 defining the cell
    vertices: np.ndarray                       # fragment vertices of the part inside the cell (V-rep)
    hull_volume: float


@dataclass
class Cover:
    pieces: list[CoverPiece] = field(default_factory=list)
    certified: bool = False
    detail: str = ""
    total_hull_volume: float = 0.0


COPLANAR_TOL = 1e-9


def _clip_poly(poly: np.ndarray, n: np.ndarray, d: float) -> np.ndarray | None:
    s = poly @ n + d
    res = []
    m = len(poly)
    for i in range(m):
        p, q = poly[i], poly[(i + 1) % m]
        sp, sq = s[i], s[(i + 1) % m]
        if sp <= 0:
            res.append(p)
        if (sp < 0 < sq) or (sq < 0 < sp):
            res.append(p + (sp / (sp - sq)) * (q - p))
    return np.array(res) if len(res) >= 3 else None


def _cell_vertices(tri: np.ndarray, planes) -> np.ndarray:
    """Vertices of the boundary fragments of the triangles inside the cell {n·x + d <= 0 for all planes}.

    A triangle lying in a cut plane belongs to the cell only when its outward normal points out of the cell
    (n_tri · n > 0): the solid it bounds is then on the cell's side. The fit-proof checker applies the same rule.
    Triangles that straddle one plane are clipped vectorised; those straddling several are clipped exactly
    with Sutherland-Hodgman.
    """
    if not planes or len(tri) == 0:
        return tri.reshape(-1, 3)
    nrm = np.array([np.asarray(n, float) for n, _ in planes])
    off = np.array([float(d) for _, d in planes])
    s = np.einsum("tvi,ki->tkv", tri, nrm) + off[None, :, None]          # (T, k, 3)
    wn = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    tol = COPLANAR_TOL
    cop = np.all(np.abs(s) <= tol, axis=2)
    facing = (wn @ nrm.T) > 0
    inside = (np.all(s <= tol, axis=2) & ~cop) | (cop & facing)
    straddle = ~cop & np.any(s < -tol, axis=2) & np.any(s > tol, axis=2)
    out = ~inside & ~straddle
    drop = np.any(out, axis=1)
    nstr = straddle.sum(axis=1)
    whole_mask = ~drop & (nstr == 0)
    one_mask = ~drop & (nstr == 1)
    many_mask = ~drop & (nstr >= 2)
    parts = [tri[whole_mask].reshape(-1, 3)]
    if one_mask.any():
        t1 = tri[one_mask]
        k1 = np.argmax(straddle[one_mask], axis=1)
        s1 = s[one_mask][np.arange(len(t1)), k1]                           # (m, 3)
        keep_v = s1 <= 0
        parts.append(t1[keep_v])
        for i, j in ((0, 1), (1, 2), (2, 0)):
            si, sj = s1[:, i], s1[:, j]
            cross = (si < 0) & (sj > 0) | (si > 0) & (sj < 0)
            if cross.any():
                ti = si[cross] / (si[cross] - sj[cross])
                pi, pj = t1[cross, i], t1[cross, j]
                parts.append(pi + ti[:, None] * (pj - pi))
    if many_mask.any():
        for t, tn in zip(tri[many_mask], wn[many_mask]):
            poly = t
            for n, d in planes:
                sp = poly @ n + d
                if np.all(np.abs(sp) <= tol):
                    if tn @ n > 0:
                        continue
                    poly = None
                    break
                poly = _clip_poly(poly, n, d)
                if poly is None:
                    break
            if poly is not None:
                parts.append(poly)
    parts = [p for p in parts if len(p)]
    return np.concatenate(parts) if parts else np.zeros((0, 3))


def cell_corners(planes) -> np.ndarray:
    """Intersection points of every triple of cell planes that satisfy all the cell's half-spaces.

    A cell bounded by three or more planes can have a corner inside the solid; such a corner is a vertex of the
    solid piece but lies on no surface triangle, so it must be added to the piece's vertex set.
    """
    from itertools import combinations
    if len(planes) < 3:
        return np.zeros((0, 3))
    nrm = np.array([np.asarray(n, float) for n, _ in planes])
    off = np.array([float(d) for _, d in planes])
    out = []
    for i, j, k in combinations(range(len(planes)), 3):
        a = nrm[[i, j, k]]
        if abs(np.linalg.det(a)) < 1e-9:
            continue
        x = np.linalg.solve(a, -off[[i, j, k]])
        if np.all(nrm @ x + off <= 1e-7 * max(1.0, float(np.abs(x).max()))):
            out.append(x)
    return np.array(out) if out else np.zeros((0, 3))


def piece_vertices(v: np.ndarray, f: np.ndarray, planes) -> np.ndarray:
    """Conservative V-representation of the solid piece P = solid ∩ cell.

    Every vertex of P is the meeting point of three bounding facets, each a surface triangle or a cell plane, so it
    is one of: (a) a mesh vertex in the closed cell, (b) a mesh edge crossing a cell plane, (c) a cell edge line
    (two planes) crossing a surface triangle, (d) a cell corner (three planes) in the closed solid. All candidates
    in the closed cell are kept, so conv(result) ⊇ P. Extra points only make the cover more conservative.
    The fit-proof checker re-derives the same set with the same rule.
    """
    from .mesh import ray_parity_inside
    if not planes:
        return v.copy()
    nrm = np.array([np.asarray(n, float) for n, _ in planes])
    off = np.array([float(d) for _, d in planes])
    scale = max(1.0, float(np.abs(v).max()))
    tol = 1e-9 * scale

    def inside(p):
        return np.all(p @ nrm.T + off <= tol, axis=1)

    out = [v[inside(v)]]
    e = np.unique(np.sort(f[:, [0, 1, 1, 2, 2, 0]].reshape(-1, 2), axis=1), axis=0)
    p0, p1 = v[e[:, 0]], v[e[:, 1]]
    for n, d in zip(nrm, off):
        s0, s1 = p0 @ n + d, p1 @ n + d
        cross = s0 * s1 < 0
        if cross.any():
            t = s0[cross] / (s0[cross] - s1[cross])
            q = p0[cross] + t[:, None] * (p1[cross] - p0[cross])
            out.append(q[inside(q)])
    tri = v[f]
    for i in range(len(planes)):
        for j in range(i + 1, len(planes)):
            direc = np.cross(nrm[i], nrm[j])
            if np.linalg.norm(direc) < 1e-12:
                continue
            x0 = np.linalg.solve(np.vstack([nrm[i], nrm[j], direc]), np.array([-off[i], -off[j], 0.0]))
            q = _line_triangles(x0, direc, tri)
            if len(q):
                out.append(q[inside(q)])
    corners = cell_corners(planes)
    if len(corners):
        wn = ray_parity_inside(corners, v, f)
        out.append(corners[wn > 1e-6])          # closure of the solid (boundary corners included)
    pts = np.concatenate([o for o in out if len(o)]) if any(len(o) for o in out) else np.zeros((0, 3))
    return np.unique(np.round(pts, 12), axis=0) if len(pts) else pts


def _line_triangles(x0: np.ndarray, d: np.ndarray, tri: np.ndarray, eps: float = 1e-12) -> np.ndarray:
    """Intersections of the infinite line x0 + t·d with triangles (closed, Möller–Trumbore, t unrestricted)."""
    e1 = tri[:, 1] - tri[:, 0]
    e2 = tri[:, 2] - tri[:, 0]
    h = np.cross(d, e2)
    a = np.einsum("ij,ij->i", e1, h)
    ok = np.abs(a) > eps * np.linalg.norm(e1, axis=1) * np.linalg.norm(e2, axis=1) * np.linalg.norm(d)
    if not ok.any():
        return np.zeros((0, 3))
    inv = 1.0 / a[ok]
    s = x0 - tri[ok, 0]
    u = inv * np.einsum("ij,ij->i", s, h[ok])
    q = np.cross(s, e1[ok])
    w = inv * (q @ d)
    t = inv * np.einsum("ij,ij->i", e2[ok], q)
    tol = 1e-9
    hit = (u >= -tol) & (w >= -tol) & (u + w <= 1 + tol)
    return x0 + t[hit, None] * d


def clip_triangles(tri: np.ndarray, planes) -> np.ndarray:
    return _cell_vertices(tri, planes)


def _hull_vol(pts: np.ndarray) -> float:
    if len(pts) < 4:
        return 0.0
    try:
        return float(ConvexHull(pts).volume)
    except Exception:  # noqa: BLE001
        return 0.0


def _nudge(n: np.ndarray, d: float, v: np.ndarray, step: float = 7.31e-4) -> float:
    """Shift a cut plane so no mesh vertex lies within 1e-6 mm of it (removes coplanar degeneracies)."""
    for k in range(1, 50):
        if np.min(np.abs(v @ n + d)) > 1e-6:
            return d
        d = d + step * (1 if k % 2 else -1) * k
    return d


def _candidate_planes(v: np.ndarray, centre: np.ndarray, axis_hint: np.ndarray | None) -> list[tuple[np.ndarray, float]]:
    """Raw candidates moved off mesh vertices. A plane through a face is offered nudged to BOTH sides: one side
    leaves a 0.7 µm sliver of the face's own solid in the far cell (whose hull can then span a cavity), the other
    does not; the greedy search keeps whichever is better."""
    out = []
    for n, d in _candidate_planes_raw(v, centre, axis_hint):
        if np.min(np.abs(v @ n + d)) > 1e-6:
            out.append((n, d))
            continue
        for sign in (1.0, -1.0):
            dd = d + sign * 7.31e-4
            if np.min(np.abs(v @ n + dd)) > 1e-6:
                out.append((n, dd))
            else:
                out.append((n, _nudge(n, dd, v)))
    return out


def _candidate_planes_raw(v: np.ndarray, centre: np.ndarray, axis_hint: np.ndarray | None) -> list[tuple[np.ndarray, float]]:
    cands = []
    for a in range(3):
        n = np.zeros(3)
        n[a] = 1.0
        vals = np.unique(np.round(v[:, a], 6))
        if len(vals) > 18:
            vals = np.quantile(v[:, a], np.linspace(0.08, 0.92, 13))
        for x in vals[1:-1] if len(vals) > 2 else []:
            cands.append((n, -float(x)))
        cands.append((n, -float(centre[a])))
    if axis_hint is not None:
        ax = axis_hint / np.linalg.norm(axis_hint)
        ref = np.array([1.0, 0, 0]) if abs(ax[0]) < 0.9 else np.array([0, 1.0, 0])
        u = np.cross(ax, ref)
        u /= np.linalg.norm(u)
        w = np.cross(ax, u)
        for k in range(8):
            th = np.pi * k / 8
            n = np.cos(th) * u + np.sin(th) * w
            cands.append((n, -float(n @ centre)))
    # deduplicate
    out, seen = [], set()
    for n, d in cands:
        key = (tuple(np.round(n, 6)), round(d, 6))
        if key not in seen:
            seen.add(key)
            out.append((n, d))
    return out


def _sector_planes(axis: np.ndarray, centre: np.ndarray, k: int) -> list[list[tuple[np.ndarray, float]]]:
    """k = 2^m radial sectors about the axis, built as a binary cut tree (each split uses a plane and its exact
    negation), so the cells provably partition space; the fit-proof checker verifies the tree structure."""
    ax = axis / np.linalg.norm(axis)
    ref = np.array([1.0, 0, 0]) if abs(ax[0]) < 0.9 else np.array([0, 1.0, 0])
    u = np.cross(ax, ref)
    u /= np.linalg.norm(u)
    w = np.cross(ax, u)
    depth = int(round(np.log2(k)))
    phase = 1.37e-4               # rad: keeps sector planes off vertex columns of regularly tessellated parts

    def right_of(gamma):          # half-space of points with angle < gamma inside a wedge of width <= pi
        n = -np.sin(gamma + phase) * u + np.cos(gamma + phase) * w
        return n, -float(n @ centre)

    root_n = np.sin(phase) * u - np.cos(phase) * w             # left of ray 0: angles in [0, pi]
    root = (root_n, -float(root_n @ centre))
    leaves = [([root], 0.0, np.pi), ([(-root[0], -root[1])], np.pi, 2 * np.pi)]
    for _ in range(depth - 1):
        nxt = []
        for planes, a, b in leaves:
            g = 0.5 * (a + b)
            n, d = right_of(g)
            nxt.append((planes + [(n, d)], a, g))
            nxt.append((planes + [(-n, -d)], g, b))
        leaves = nxt
    return [p for p, _, _ in leaves]


def planar_cut_cover(v: np.ndarray, f: np.ndarray, volume: float, axis_hint: np.ndarray | None = None,
                     max_pieces: int = 16, target_overhead: float = 0.02) -> Cover:
    """Choose cut planes (on a simplified copy for large meshes), then build exact pieces on the full mesh."""
    planes_per_leaf = _choose_cuts(*_search_mesh(v, f), volume, axis_hint, max_pieces, target_overhead)
    pieces = []
    for planes in planes_per_leaf:
        pts = piece_vertices(v, f, planes)
        if len(pts) == 0:
            continue
        pieces.append(CoverPiece(planes=[(np.asarray(n, float), float(d)) for n, d in planes], vertices=pts,
                                 hull_volume=_hull_vol(pts)))
    cover = Cover(pieces=pieces, total_hull_volume=float(sum(p.hull_volume for p in pieces)))
    ok, why = verify_cover(v, f, pieces)
    cover.certified = ok
    cover.detail = (f"{len(pieces)} piece(s), hull volume {cover.total_hull_volume:.6g} mm³ "
                    f"(+{100 * (cover.total_hull_volume / volume - 1):.2f} % over the solid); {why}")
    return cover


def _search_mesh(v: np.ndarray, f: np.ndarray, max_tris: int = 6000):
    if len(f) <= max_tris:
        return v, f
    try:
        import fast_simplification
        vs, fs = fast_simplification.simplify(v.astype(np.float32), f.astype(np.int32), 1.0 - max_tris / len(f))
        return np.asarray(vs, float), np.asarray(fs, np.int64)
    except Exception:  # noqa: BLE001
        return v, f


def _choose_cuts(v, f, volume, axis_hint, max_pieces, target_overhead):
    centre = 0.5 * (v.min(axis=0) + v.max(axis=0))

    def _cell_vertices(_tri, planes):           # evaluate candidates with the same construction as the result
        return piece_vertices(v, f, planes)
    tri = None
    cands = _candidate_planes(v, centre, axis_hint)
    leaves = [[]]                                       # list of plane-lists
    leaf_vol = [_hull_vol(v)]
    if axis_hint is not None:
        # through-hole parts: a single cut never helps (a half ring's hull still spans the hole), so try a
        # radial sector split first and keep the best k that pays for its extra pieces
        for k in (4, 8, 16):
            if k > max_pieces:
                break
            cells = _sector_planes(axis_hint, centre, k)
            vols = [_hull_vol(_cell_vertices(tri, c)) for c in cells]
            if sum(vols) < sum(leaf_vol) - 0.01 * volume * (k - len(leaves)):
                leaves, leaf_vol = cells, vols
    while len(leaves) < max_pieces and sum(leaf_vol) > volume * (1 + target_overhead):
        best = None
        for li, planes in enumerate(leaves):
            pts_leaf = _cell_vertices(tri, planes)
            if len(pts_leaf) < 4:
                continue
            lo, hi = pts_leaf.min(axis=0), pts_leaf.max(axis=0)
            for n, d in cands:
                s = pts_leaf @ n + d
                if s.min() >= -1e-9 or s.max() <= 1e-9:
                    continue                       # plane does not cut this leaf
                pa = planes + [(n, d)]
                pb = planes + [(-n, -d)]
                va = _hull_vol(_cell_vertices(tri, pa))
                vb = _hull_vol(_cell_vertices(tri, pb))
                gain = leaf_vol[li] - (va + vb)
                if best is None or gain > best[0]:
                    best = (gain, li, pa, pb, va, vb)
            del lo, hi
        min_gain = 0.01 * volume if target_overhead >= 0.01 else 1e-9 * volume
        if best is None or best[0] < min_gain:
            break
        _, li, pa, pb, va, vb = best
        leaves[li:li + 1] = [pa, pb]
        leaf_vol[li:li + 1] = [va, vb]
    # Certification is by construction (the cells partition space and each solid piece lies in the hull of
    # its clipped boundary fragments); verify_cover() re-checks it numerically on the full mesh.
    return leaves


def verify_cover(v: np.ndarray, f: np.ndarray, pieces: list[CoverPiece], n_interior: int = 400,
                 seed: int = 12345, tol: float = 1e-7) -> tuple[bool, str]:
    """Containment certificate for a convex cover.

    Primary: the exact boolean difference part − ∪hull(pieces) (manifold3d) must have no volume beyond
    1e-9 of the part (seams between adjacent pieces can leave zero-thickness slivers). Secondary: every vertex,
    dense surface samples and random interior points lie in some piece hull.
    """
    try:
        import manifold3d as m3d
        part = _to_manifold(v, f)
        union = None
        offs = np.vstack([np.eye(3), -np.eye(3)]) * COVER_DELTA
        for p in pieces:
            if len(p.vertices) >= 4:
                pts = (np.asarray(p.vertices, dtype=np.float64)[:, None, :] + offs[None]).reshape(-1, 3)
                h = m3d.Manifold.hull_points(pts)
                union = h if union is None else union + h
        if union is None:
            return False, "no valid piece hulls"
        diff = part - union
        dv = float(diff.volume())
        if diff.num_tri() > 0 and dv > 1e-12 * float(part.volume()):
            return False, f"exact boolean: {dv:.6g} mm³ of the part lies outside the δ-inflated pieces"
        boolean_note = f"exact boolean: part ⊆ ∪pieces ⊕ {COVER_DELTA * 1e3:.1f} µm (residual {dv:.2g} mm³)"
    except Exception as exc:  # noqa: BLE001
        return False, f"boolean certificate unavailable: {exc}"
    ok, why = _sample_cover(v, f, pieces, n_interior, seed, tol)
    return ok, f"{boolean_note}; {why}"


def _sample_cover(v, f, pieces, n_interior, seed, tol):
    from scipy.spatial import Delaunay
    hulls = []
    for p in pieces:
        if len(p.vertices) < 4:
            continue
        try:
            h = ConvexHull(p.vertices)
            hulls.append((Delaunay(p.vertices[h.vertices]), h.equations))
        except Exception:  # noqa: BLE001
            continue
    if not hulls:
        return False, "no valid piece hulls"
    from .voxel import surface_samples
    ext = float((v.max(0) - v.min(0)).max())
    surf = surface_samples(v, f, max(ext / 60.0, 0.05))
    rng = np.random.default_rng(seed)
    if len(surf) > 20000:
        surf = surf[rng.choice(len(surf), 20000, replace=False)]
    box = rng.uniform(v.min(0), v.max(0), size=(1500, 3))
    inside = ray_parity_inside(box, v, f) > 0.5
    interior = box[inside][:n_interior]
    pts = np.vstack([v, surf, interior])
    if len(pts) > 5000:                      # secondary check only: the exact boolean is the certificate
        pts = np.vstack([pts[rng.choice(len(pts) - len(interior), 5000 - len(interior), replace=False)], interior])
    covered = np.zeros(len(pts), dtype=bool)
    slack = tol * max(ext, 1.0) + COVER_DELTA
    for dl, eq in hulls:
        todo = np.flatnonzero(~covered)
        if len(todo) == 0:
            break
        hit = dl.find_simplex(pts[todo]) >= 0
        covered[todo[hit]] = True
    # points on a hull face can fall between simplices numerically: confirm the rest with half-spaces, in chunks
    for dl, eq in hulls:
        todo = np.flatnonzero(~covered)
        if len(todo) == 0:
            break
        for s in range(0, len(todo), 512):
            chunk = todo[s:s + 512]
            near = np.all(pts[chunk] @ eq[:, :3].T + eq[:, 3] <= slack, axis=1)
            covered[chunk[near]] = True
    if not covered.all():
        return False, f"{int((~covered).sum())} of {len(pts)} check points outside every piece"
    return True, f"verified: {len(pts)} vertex/surface/interior points all inside the pieces"
