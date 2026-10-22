"""M1: rotations, STL I/O, topology and repair (protocol tests T-G)."""

import numpy as np

from t2s.core.rotations import ROTATIONS
from t2s.geometry import mesh as meshmod
from t2s.geometry.stl_io import read_stl_bytes, write_binary_stl
from t2s.parts.build import suggest_units


def box_mesh(lo, hi):
    x0, y0, z0 = lo
    x1, y1, z1 = hi
    v = np.array([[x0, y0, z0], [x1, y0, z0], [x1, y1, z0], [x0, y1, z0],
                  [x0, y0, z1], [x1, y0, z1], [x1, y1, z1], [x0, y1, z1]], float)
    f = np.array([[0, 2, 1], [0, 3, 2], [4, 5, 6], [4, 6, 7], [0, 1, 5], [0, 5, 4],
                  [1, 2, 6], [1, 6, 5], [2, 3, 7], [2, 7, 6], [3, 0, 4], [3, 4, 7]])
    return v, f


def stl_bytes(v, f, tmp_path, name="m.stl"):
    p = tmp_path / name
    write_binary_stl(p, v, f)
    return p.read_bytes()


def test_rotation_group():
    assert ROTATIONS.shape == (24, 3, 3)
    assert np.array_equal(ROTATIONS[0], np.eye(3, dtype=int))
    keys = {tuple(r.ravel()) for r in ROTATIONS}
    assert len(keys) == 24
    for r in ROTATIONS:
        assert round(np.linalg.det(r)) == 1
        assert set(np.abs(r).ravel()) <= {0, 1}
    for a in ROTATIONS[:6]:
        for b in ROTATIONS:
            assert tuple((a @ b).ravel()) in keys          # closed under composition


def test_binary_and_ascii_roundtrip(tmp_path):
    v, f = box_mesh((0, 0, 0), (2, 3, 4))
    tri_b, fmt_b = read_stl_bytes(stl_bytes(v, f, tmp_path))
    assert fmt_b == "binary" and tri_b.shape == (12, 3, 3)
    lines = ["solid t"]
    for t in v[f]:
        lines += ["facet normal 0 0 0", "outer loop"] + [f"vertex {a} {b} {c}" for a, b, c in t] + ["endloop", "endfacet"]
    lines.append("endsolid t")
    tri_a, fmt_a = read_stl_bytes("\n".join(lines).encode())
    assert fmt_a == "ascii" and np.allclose(tri_a, tri_b)


def test_binary_header_starting_with_solid_is_binary(tmp_path):
    v, f = box_mesh((0, 0, 0), (1, 1, 1))
    data = bytearray(stl_bytes(v, f, tmp_path))
    data[:5] = b"solid"
    tri, fmt = read_stl_bytes(bytes(data))
    assert fmt == "binary" and len(tri) == 12


def test_topology_of_box_and_open_box():
    v, f = box_mesh((0, 0, 0), (1, 1, 1))
    t = meshmod.topology(v, f)
    assert t.watertight and t.consistently_oriented and t.genus_total == 0 and abs(t.signed_volume_mm3 - 1) < 1e-12
    t2 = meshmod.topology(v, f[:-1])
    assert t2.boundary_edges == 3 and not t2.watertight


def test_repair_flips_inverted_and_withholds_large_hole():
    v, f = box_mesh((0, 0, 0), (30, 20, 10))
    r = meshmod.repair(v, f[:, [0, 2, 1]])
    assert r.status == "REPAIRED" and meshmod.signed_volume(r.vertices, r.faces) > 0
    r2 = meshmod.repair(v, f[:-1])
    assert r2.status == "WITHHELD" and "open mesh" in r2.detail


def test_small_hole_is_filled_and_labelled():
    # a fine cylinder with one tiny triangle removed from a cap: patch area << 0.1 % of the surface
    n = 512
    ang = np.linspace(0, 2 * np.pi, n, endpoint=False)
    ring0 = np.c_[50 * np.cos(ang), 50 * np.sin(ang), np.zeros(n)]
    ring1 = ring0 + [0, 0, 40]
    v = np.vstack([ring0, ring1, [[0, 0, 0], [0, 0, 40]]])
    f = []
    for i in range(n):
        j = (i + 1) % n
        f += [[i, j, n + j], [i, n + j, n + i], [2 * n, j, i], [2 * n + 1, n + i, n + j]]
    f = np.array(f)
    f = np.delete(f, 2, axis=0)            # remove one bottom-cap triangle
    r = meshmod.repair(v, f)
    assert r.status == "REPAIRED" and any("filled" in s for s in r.repairs)


def test_self_intersection_detected():
    va, fa = box_mesh((0, 0, 0), (10, 10, 10))
    vb, fb = box_mesh((5, 4, 3), (15, 13, 12))     # asymmetric: no crossing lies exactly on a diagonal
    v = np.vstack([va, vb])
    f = np.vstack([fa, fb + 8])
    assert meshmod.self_intersections(v, f)
    r = meshmod.repair(v, f)
    assert r.status == "WITHHELD" and "self-intersecting" in r.detail


def test_units_suggestion():
    assert suggest_units(80.0) == "mm"
    assert suggest_units(3.15) == "in"        # 80 mm part exported in inches
    assert suggest_units(0.08) == "m"
