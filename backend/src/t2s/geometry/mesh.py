"""Indexed triangle meshes: welding, topology checks, lossless repair, self-intersection test."""
from dataclasses import dataclass, field

import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components


@dataclass
class Topology:
    boundary_edges: int
    nonmanifold_edges: int
    misoriented_edges: int
    degenerate_faces: int
    components: int
    euler_characteristic: int
    genus_total: int | None
    watertight: bool
    consistently_oriented: bool
    signed_volume_mm3: float
    component_volumes_mm3: list[float] = field(default_factory=list)


def weld(tri: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Exact-coordinate weld of a triangle soup (n, 3, 3) into (vertices, faces)."""
    pts = tri.reshape(-1, 3)
    verts, inverse = np.unique(pts, axis=0, return_inverse=True)
    return verts, inverse.reshape(-1, 3).astype(np.int64)


def face_areas(v: np.ndarray, f: np.ndarray) -> np.ndarray:
    return 0.5 * np.linalg.norm(np.cross(v[f[:, 1]] - v[f[:, 0]], v[f[:, 2]] - v[f[:, 0]]), axis=1)


def _edges(f: np.ndarray):
    e = f[:, [0, 1, 1, 2, 2, 0]].reshape(-1, 2)
    face_of = np.repeat(np.arange(len(f)), 3)
    lo = np.minimum(e[:, 0], e[:, 1])
    hi = np.maximum(e[:, 0], e[:, 1])
    fwd = e[:, 0] < e[:, 1]
    key = lo * (int(e.max()) + 1 if len(e) else 1) + hi
    return e, face_of, key, fwd


def face_components(f: np.ndarray) -> tuple[int, np.ndarray]:
    if len(f) == 0:
        return 0, np.zeros(0, dtype=np.int64)
    _, face_of, key, _ = _edges(f)
    order = np.argsort(key, kind="stable")
    k = key[order]
    fo = face_of[order]
    same = np.flatnonzero(k[1:] == k[:-1])
    rows = fo[same]
    cols = fo[same + 1]
    g = coo_matrix((np.ones(len(rows)), (rows, cols)), shape=(len(f), len(f)))
    return connected_components(g, directed=False)


def signed_volume(v: np.ndarray, f: np.ndarray, origin=None) -> float:
    o = v.mean(axis=0) if origin is None else origin
    a, b, c = v[f[:, 0]] - o, v[f[:, 1]] - o, v[f[:, 2]] - o
    return float(np.einsum("ij,ij->i", a, np.cross(b, c)).sum() / 6.0)


def topology(v: np.ndarray, f: np.ndarray) -> Topology:
    if len(f) == 0:
        return Topology(0, 0, 0, 0, 0, 0, None, False, False, 0.0, [])
    _, _, key, fwd = _edges(f)
    uk, inv, counts = np.unique(key, return_inverse=True, return_counts=True)
    fwd_counts = np.bincount(inv, weights=fwd.astype(np.float64), minlength=len(uk))
    rev_counts = counts - fwd_counts
    boundary = int(np.sum(counts == 1))
    nonmanifold = int(np.sum(counts > 2))
    misoriented = int(np.sum((counts == 2) & ((fwd_counts != 1) | (rev_counts != 1))))
    degenerate = int(np.sum((f[:, 0] == f[:, 1]) | (f[:, 1] == f[:, 2]) | (f[:, 0] == f[:, 2])
                            | (face_areas(v, f) == 0.0)))
    ncomp, labels = face_components(f)
    used = len(np.unique(f))
    chi = used - len(uk) + len(f)
    closed = boundary == 0 and nonmanifold == 0
    genus = (ncomp - chi // 2) if closed else None
    o = 0.5 * (v.min(axis=0) + v.max(axis=0))
    comp_vols = [signed_volume(v, f[labels == c], o) for c in range(ncomp)]
    return Topology(boundary, nonmanifold, misoriented, degenerate, int(ncomp), int(chi), genus, closed,
                    closed and misoriented == 0, float(sum(comp_vols)), comp_vols)


def _orient_component(f: np.ndarray, faces_idx: np.ndarray) -> np.ndarray | None:
    """Make winding consistent within one edge-connected component by BFS. None if non-orientable."""
    sub = f[faces_idx].copy()
    n = len(sub)
    edge_map: dict[tuple[int, int], list[int]] = {}
    for i, (a, b, c) in enumerate(sub):
        for x, y in ((a, b), (b, c), (c, a)):
            edge_map.setdefault((min(x, y), max(x, y)), []).append(i)
    flipped = np.zeros(n, dtype=bool)
    seen = np.zeros(n, dtype=bool)

    def directed(i):
        a, b, c = sub[i]
        if flipped[i]:
            a, b, c = a, c, b
        return ((a, b), (b, c), (c, a))

    for start in range(n):
        if seen[start]:
            continue
        seen[start] = True
        stack = [start]
        while stack:
            i = stack.pop()
            for x, y in directed(i):
                for j in edge_map[(min(x, y), max(x, y))]:
                    if j == i:
                        continue
                    same_dir = (x, y) in directed(j)
                    if not seen[j]:
                        seen[j] = True
                        flipped[j] = same_dir
                        stack.append(j)
                    elif same_dir:
                        return None
    out = sub.copy()
    out[flipped] = out[flipped][:, [0, 2, 1]]
    return out


def _winding_numpy(points, a0, b0, c0):
    out = np.empty(len(points))
    for k, p in enumerate(points):
        a, b, c = a0 - p, b0 - p, c0 - p
        la, lb, lc = np.linalg.norm(a, axis=1), np.linalg.norm(b, axis=1), np.linalg.norm(c, axis=1)
        num = np.einsum("ij,ij->i", a, np.cross(b, c))
        den = la * lb * lc + np.einsum("ij,ij->i", a, b) * lc + np.einsum("ij,ij->i", b, c) * la \
            + np.einsum("ij,ij->i", c, a) * lb
        out[k] = np.arctan2(num, den).sum() / (2.0 * np.pi)
    return out


try:
    from numba import njit

    @njit(cache=True, nogil=True, fastmath=False)
    def _winding_numba(points, a0, b0, c0):  # pragma: no cover - compiled
        n = points.shape[0]
        m = a0.shape[0]
        out = np.empty(n)
        for k in range(n):
            px, py, pz = points[k, 0], points[k, 1], points[k, 2]
            total = 0.0
            for i in range(m):
                ax, ay, az = a0[i, 0] - px, a0[i, 1] - py, a0[i, 2] - pz
                bx, by, bz = b0[i, 0] - px, b0[i, 1] - py, b0[i, 2] - pz
                cx, cy, cz = c0[i, 0] - px, c0[i, 1] - py, c0[i, 2] - pz
                la = np.sqrt(ax * ax + ay * ay + az * az)
                lb = np.sqrt(bx * bx + by * by + bz * bz)
                lc = np.sqrt(cx * cx + cy * cy + cz * cz)
                num = ax * (by * cz - bz * cy) + ay * (bz * cx - bx * cz) + az * (bx * cy - by * cx)
                den = la * lb * lc + (ax * bx + ay * by + az * bz) * lc + (bx * cx + by * cy + bz * cz) * la \
                    + (cx * ax + cy * ay + cz * az) * lb
                total += np.arctan2(num, den)
            out[k] = total / (2.0 * np.pi)
        return out
except Exception:  # noqa: BLE001 - numba unavailable
    _winding_numba = None


def ray_parity_inside(points: np.ndarray, v: np.ndarray, f: np.ndarray) -> np.ndarray:
    """Generalised winding number (solid-angle sum) for points; > 0.5 means inside a closed mesh."""
    points = np.ascontiguousarray(np.atleast_2d(points), dtype=np.float64)
    a0 = np.ascontiguousarray(v[f[:, 0]], dtype=np.float64)
    b0 = np.ascontiguousarray(v[f[:, 1]], dtype=np.float64)
    c0 = np.ascontiguousarray(v[f[:, 2]], dtype=np.float64)
    if _winding_numba is not None:
        return _winding_numba(points, a0, b0, c0)
    return _winding_numpy(points, a0, b0, c0)


@dataclass
class RepairResult:
    vertices: np.ndarray
    faces: np.ndarray
    repairs: list[str]
    status: str            # VALID | REPAIRED | WITHHELD
    detail: str


def _boundary_loops(f: np.ndarray) -> list[list[int]]:
    _, _, key, _ = _edges(f)
    e = f[:, [0, 1, 1, 2, 2, 0]].reshape(-1, 2)
    uk, inv, counts = np.unique(key, return_inverse=True, return_counts=True)
    single = counts[inv] == 1
    nxt: dict[int, int] = {}
    for a, b in e[single]:
        nxt[int(b)] = int(a)          # walk boundary opposite to face winding so the patch faces outward
    loops, used = [], set()
    for s in list(nxt):
        if s in used:
            continue
        loop, cur = [], s
        while cur not in used and cur in nxt:
            used.add(cur)
            loop.append(cur)
            cur = nxt[cur]
        if loop and cur == s:
            loops.append(loop)
        else:
            return []                  # tangled boundary: not a simple loop set
    return loops


def repair(v: np.ndarray, f: np.ndarray, hole_area_fraction: float = 1e-3) -> RepairResult:
    """Lossless fixes automatically; small holes filled and labelled; everything else WITHHELD."""
    repairs: list[str] = []
    areas = face_areas(v, f)
    bad = (f[:, 0] == f[:, 1]) | (f[:, 1] == f[:, 2]) | (f[:, 0] == f[:, 2]) | (areas == 0.0)
    if bad.any():
        f = f[~bad]
        repairs.append(f"removed {int(bad.sum())} degenerate triangle(s)")
    srt = np.sort(f, axis=1)
    _, first = np.unique(srt, axis=0, return_index=True)
    if len(first) < len(f):
        repairs.append(f"removed {len(f) - len(first)} duplicate triangle(s)")
        f = f[np.sort(first)]
    topo = topology(v, f)
    if topo.boundary_edges and not topo.nonmanifold_edges:
        loops = _boundary_loops(f)
        total_area = float(face_areas(v, f).sum())
        patch_tris, patch_area, new_v = [], 0.0, [v]
        nv = len(v)
        for loop in loops:
            pts = v[loop]
            cen = pts.mean(axis=0)
            ci = nv
            nv += 1
            new_v.append(cen[None])
            for i in range(len(loop)):
                a, b = loop[i], loop[(i + 1) % len(loop)]
                patch_tris.append((a, b, ci))
                patch_area += 0.5 * float(np.linalg.norm(np.cross(v[b] - v[a], cen - v[a])))
        if loops and patch_area <= hole_area_fraction * total_area:
            v = np.vstack(new_v)
            f = np.vstack([f, np.array(patch_tris, dtype=np.int64)])
            repairs.append(f"filled {len(loops)} small hole(s) ({patch_area:.3g} mm², "
                           f"{100 * patch_area / total_area:.3g} % of area)")
            topo = topology(v, f)
        else:
            return RepairResult(v, f, repairs, "WITHHELD",
                                f"open mesh — {len(loops) or 'tangled'} hole(s) with {topo.boundary_edges} "
                                f"boundary edges; patch would be {100 * patch_area / max(total_area, 1e-300):.3g} % "
                                f"of the surface (limit {100 * hole_area_fraction:g} %)")
    if topo.nonmanifold_edges:
        return RepairResult(v, f, repairs, "WITHHELD",
                            f"non-manifold mesh — {topo.nonmanifold_edges} edge(s) shared by more than two faces")
    if topo.misoriented_edges or any(cv < 0 for cv in topo.component_volumes_mm3):
        ncomp, labels = face_components(f)
        new_faces = []
        for c in range(ncomp):
            idx = np.flatnonzero(labels == c)
            oriented = _orient_component(f, idx)
            if oriented is None:
                return RepairResult(v, f, repairs, "WITHHELD", "non-orientable surface")
            new_faces.append(oriented)
        comps = new_faces
        vols = [signed_volume(v, cf, 0.5 * (v.min(0) + v.max(0))) for cf in comps]
        fixed = []
        for i, (cf, vol) in enumerate(zip(comps, vols)):
            if vol < 0:
                others = [comps[j] for j in range(len(comps)) if j != i]
                probe = v[cf[0, 0]]
                inside_other = any(ray_parity_inside(probe[None], v, o)[0] > 0.5 for o in others)
                if not inside_other:
                    cf = cf[:, [0, 2, 1]]
            fixed.append(cf)
        new_f = np.vstack(fixed)
        before = signed_volume(v, f)
        f = new_f
        after = signed_volume(v, f)
        repairs.append(f"made winding consistent (signed volume {before:.6g} → {after:.6g} mm³)")
        topo = topology(v, f)
    if not topo.consistently_oriented or topo.signed_volume_mm3 <= 0:
        return RepairResult(v, f, repairs, "WITHHELD", "could not produce a closed, outward-oriented solid")
    si = self_intersections(v, f, limit=1)
    if si:
        return RepairResult(v, f, repairs, "WITHHELD", "self-intersecting mesh — triangles cross each other")
    return RepairResult(v, f, repairs, "REPAIRED" if repairs else "VALID",
                        "; ".join(repairs) if repairs else "closed, consistently oriented, no self-intersections")


def self_intersections(v: np.ndarray, f: np.ndarray, limit: int = 10) -> list[tuple[int, int]]:
    """Edge-crossing test between non-adjacent triangles (uniform-grid broad phase)."""
    tri = v[f]
    lo, hi = tri.min(axis=1), tri.max(axis=1)
    edge_len = np.linalg.norm(tri[:, 1] - tri[:, 0], axis=1)
    cell = max(float(np.median(edge_len)) * 2.0, 1e-9)
    gmin = lo.min(axis=0)
    ilo = np.floor((lo - gmin) / cell).astype(np.int64)
    ihi = np.floor((hi - gmin) / cell).astype(np.int64)
    span = ihi - ilo + 1
    ncell = span.prod(axis=1)
    if ncell.max() > 64:          # very large triangles: widen the cell
        cell *= float(np.cbrt(ncell.max() / 8.0))
        ilo = np.floor((lo - gmin) / cell).astype(np.int64)
        ihi = np.floor((hi - gmin) / cell).astype(np.int64)
        span = ihi - ilo + 1
        ncell = span.prod(axis=1)
    reps = np.repeat(np.arange(len(f)), ncell)
    offs = np.concatenate([np.indices(tuple(s)).reshape(3, -1).T for s in span]) if len(f) else np.zeros((0, 3))
    cells = ilo[reps] + offs
    dims = cells.max(axis=0) + 1
    cid = (cells[:, 0] * dims[1] + cells[:, 1]) * dims[2] + cells[:, 2]
    order = np.argsort(cid, kind="stable")
    cid, reps = cid[order], reps[order]
    starts = np.flatnonzero(np.r_[True, cid[1:] != cid[:-1]])
    ends = np.r_[starts[1:], len(cid)]
    pa, pb = [], []
    for s, e in zip(starts, ends):
        if e - s < 2:
            continue
        members = reps[s:e]
        ii, jj = np.triu_indices(len(members), k=1)
        pa.append(members[ii])
        pb.append(members[jj])
    if not pa:
        return []
    pa = np.concatenate(pa)
    pb = np.concatenate(pb)
    pairs = np.unique(np.stack([np.minimum(pa, pb), np.maximum(pa, pb)], axis=1), axis=0)
    fa, fb = f[pairs[:, 0]], f[pairs[:, 1]]
    share = (fa[:, :, None] == fb[:, None, :]).any(axis=(1, 2))
    pairs = pairs[~share]
    if len(pairs) == 0:
        return []
    ov = np.all(lo[pairs[:, 0]] <= hi[pairs[:, 1]], axis=1) & np.all(lo[pairs[:, 1]] <= hi[pairs[:, 0]], axis=1)
    pairs = pairs[ov]
    hits = np.zeros(len(pairs), dtype=bool)
    for first, second in ((0, 1), (1, 0)):
        ta = tri[pairs[:, first]]
        tb = tri[pairs[:, second]]
        for e0, e1 in ((0, 1), (1, 2), (2, 0)):
            hits |= _segment_hits_triangle(ta[:, e0], ta[:, e1], tb)
    found = pairs[hits]
    return [tuple(map(int, p)) for p in found[:limit]]


def _segment_hits_triangle(p0, p1, t, eps=1e-12):
    d = p1 - p0
    e1 = t[:, 1] - t[:, 0]
    e2 = t[:, 2] - t[:, 0]
    h = np.cross(d, e2)
    a = np.einsum("ij,ij->i", e1, h)
    ok = np.abs(a) > eps * (np.linalg.norm(e1, axis=1) * np.linalg.norm(e2, axis=1) * np.linalg.norm(d, axis=1) + 1e-300)
    inv = np.where(ok, 1.0 / np.where(ok, a, 1.0), 0.0)
    s = p0 - t[:, 0]
    u = inv * np.einsum("ij,ij->i", s, h)
    q = np.cross(s, e1)
    w = inv * np.einsum("ij,ij->i", d, q)
    tt = inv * np.einsum("ij,ij->i", e2, q)
    tol = 1e-9
    return ok & (u > tol) & (w > tol) & (u + w < 1 - tol) & (tt > tol) & (tt < 1 - tol)
