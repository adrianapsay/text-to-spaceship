"""Any-STL-anytime: files generated at test time, never seen during development (Addendum 2.1)."""
import numpy as np
import pytest

from t2s.geometry.stl_io import write_binary_stl
from t2s.parts.build import build_part


def cone(n=80, r=20.0, h=35.0):
    ang = 2 * np.pi * np.arange(n) / n
    v = np.vstack([np.c_[r * np.cos(ang), r * np.sin(ang), np.zeros(n)], [[0, 0, h], [0, 0, 0]]])
    f = []
    for i in range(n):
        j = (i + 1) % n
        f += [[i, j, n], [n + 1, j, i]]
    return v, np.array(f)


def to_bytes(tmp_path, v, f, name):
    p = tmp_path / name
    write_binary_stl(p, v, f)
    return p.read_bytes()


def test_new_shape(tmp_path):
    v, f = cone()
    rec = build_part(to_bytes(tmp_path, v, f, "cone.stl"), "cone", "n1")
    assert rec.status == "VALID"
    vol = np.pi * 20 ** 2 * 35 / 3
    assert 0 < (vol - rec.volume_mm3) / vol < 2e-3
    assert rec.boxes_certified and rec.cover.certified


def test_inch_file_is_flagged(tmp_path):
    v, f = cone()
    data = to_bytes(tmp_path, v / 25.4, f, "cone_in.stl")
    rec = build_part(data, "cone_in", "n2", units="mm", units_confirmed=False)
    assert rec.status == "NEEDS_UNITS" and rec.suggested_units == "in"
    rec2 = build_part(data, "cone_in", "n2", units="in", units_confirmed=True)
    assert abs(rec2.volume_mm3 - build_part(to_bytes(tmp_path, v, f, "c.stl"), "c", "n3").volume_mm3) < 1e-6 * rec2.volume_mm3


def test_ascii_file(tmp_path):
    v, f = cone(24)
    lines = ["solid cone"]
    for t in v[f]:
        lines += ["  facet normal 0 0 0", "    outer loop"] + [f"      vertex {a:.6e} {b:.6e} {c:.6e}" for a, b, c in t] \
            + ["    endloop", "  endfacet"]
    lines.append("endsolid cone")
    rec = build_part("\n".join(lines).encode(), "cone_ascii", "n4")
    assert rec.status == "VALID" and rec.volume_mm3 > 0


def test_multibody_file(tmp_path):
    v1, f1 = cone(30)
    v2 = v1 + [60.0, 0, 0]
    rec = build_part(to_bytes(tmp_path, np.vstack([v1, v2]), np.vstack([f1, f1 + len(v1)]), "two.stl"), "two", "n5")
    assert rec.status == "VALID" and rec.topology.components == 2


def test_broken_file_is_explained_not_crashing(tmp_path):
    v, f = cone()
    rec = build_part(to_bytes(tmp_path, v, f[:-5], "broken.stl"), "broken", "n6")
    assert rec.status == "WITHHELD" and "open mesh" in rec.status_detail
    with pytest.raises(ValueError):
        build_part(b"this is not an stl file at all", "junk", "n7")


@pytest.mark.slow
def test_large_file(tmp_path):
    # ~200k triangles: a finely tessellated torus
    nu, nv = 500, 200
    u = 2 * np.pi * np.arange(nu) / nu
    w = 2 * np.pi * np.arange(nv) / nv
    uu, ww = np.meshgrid(u, w, indexing="ij")
    R, r = 30.0, 8.0
    pts = np.stack([(R + r * np.cos(ww)) * np.cos(uu), (R + r * np.cos(ww)) * np.sin(uu), r * np.sin(ww)], -1).reshape(-1, 3)
    idx = np.arange(nu * nv).reshape(nu, nv)
    a = idx
    b = np.roll(idx, -1, axis=0)
    c = np.roll(np.roll(idx, -1, axis=0), -1, axis=1)
    d = np.roll(idx, -1, axis=1)
    f = np.vstack([np.stack([a, b, c], -1).reshape(-1, 3), np.stack([a, c, d], -1).reshape(-1, 3)])
    rec = build_part(to_bytes(tmp_path, pts, f, "big.stl"), "big_torus", "n8")
    assert rec.status in ("VALID", "REPAIRED") and rec.cover.certified
