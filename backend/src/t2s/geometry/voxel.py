"""Conservative voxel covers: every cell the solid touches is marked occupied.

Method: sample every triangle with spacing s < h, mark the samples' cells, dilate by one cell (any surface
point lies within s of a sample, hence in a 26-neighbour of a marked cell), then fill the enclosed interior.
"""
import numpy as np
from scipy import ndimage


def surface_samples(v: np.ndarray, f: np.ndarray, spacing: float) -> np.ndarray:
    tri = v[f]
    lens = np.max(np.linalg.norm(tri - np.roll(tri, 1, axis=1), axis=2), axis=1)
    nseg = np.maximum(1, np.ceil(lens / spacing).astype(np.int64))
    out = [tri.reshape(-1, 3)]
    for n in np.unique(nseg):
        idx = np.flatnonzero(nseg == n)
        i, j = np.meshgrid(np.arange(n + 1), np.arange(n + 1), indexing="ij")
        keep = (i + j) <= n
        u = (i[keep] / n)[None, :, None]
        w = (j[keep] / n)[None, :, None]
        t = tri[idx]
        pts = t[:, None, 0] + u * (t[:, None, 1] - t[:, None, 0]) + w * (t[:, None, 2] - t[:, None, 0])
        out.append(pts.reshape(-1, 3))
    return np.concatenate(out)


def conservative_voxels(v: np.ndarray, f: np.ndarray, h: float):
    """Return (origin, h, occupancy bool grid) with the solid contained in the occupied cells."""
    lo = v.min(axis=0) - 1.5 * h
    hi = v.max(axis=0) + 1.5 * h
    shape = np.ceil((hi - lo) / h).astype(np.int64) + 1
    pts = surface_samples(v, f, 0.45 * h)
    idx = np.floor((pts - lo) / h).astype(np.int64)
    occ = np.zeros(shape, dtype=bool)
    occ[idx[:, 0], idx[:, 1], idx[:, 2]] = True
    occ = ndimage.binary_dilation(occ, structure=np.ones((3, 3, 3), dtype=bool))
    occ = ndimage.binary_fill_holes(occ)
    return lo, h, occ
