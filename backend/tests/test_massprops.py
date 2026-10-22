"""M1: mass properties against analytic solutions and the independent implementation (protocol tests T-M)."""
import numpy as np
import pytest

from t2s.core.rotations import ROTATIONS_F
from t2s.massprops.core import integrate, principal
from t2s.massprops.ref import unit_mass_props_ref
from t2s.physics.assembly import Accumulator, PartPhys, assembly, inertia_metrics


def tetra():
    v = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]], float)
    f = np.array([[0, 2, 1], [0, 1, 3], [0, 3, 2], [1, 2, 3]])
    return v, f


def prism(n, r, h):
    ang = 2 * np.pi * np.arange(n) / n
    ring = np.c_[r * np.cos(ang), r * np.sin(ang)]
    v = np.vstack([np.c_[ring, np.zeros(n)], np.c_[ring, np.full(n, h)], [[0, 0, 0], [0, 0, h]]])
    f = []
    for i in range(n):
        j = (i + 1) % n
        f += [[i, j, n + j], [i, n + j, n + i], [2 * n, j, i], [2 * n + 1, n + i, n + j]]
    return v, np.array(f)


def test_canonical_tetrahedron():
    p = integrate(*tetra())
    assert abs(p.volume_mm3 - 1 / 6) < 1e-15
    assert np.allclose(p.com_mm, [0.25] * 3, atol=1e-15)
    # I_C for unit density: diagonal 1/80 * V*... closed form: diag = 1/80, off = +1/480 (tensor sign, -∫xy)
    assert np.allclose(np.diag(p.j_mm5), 1 / 80, rtol=1e-12)
    assert np.allclose(p.j_mm5[0, 1], 1 / 480, rtol=1e-12)


def test_inscribed_prism_exact_formula():
    n, r, h = 96, 25.0, 25.0
    p = integrate(*prism(n, r, h))
    vol = n / 2 * r * r * np.sin(2 * np.pi / n) * h
    jz = vol * r * r * (2 + np.cos(2 * np.pi / n)) / 6
    jx = jz / 2 + vol * h * h / 12
    assert abs(p.volume_mm3 - vol) / vol < 1e-12
    assert abs(p.j_mm5[2, 2] - jz) / jz < 1e-12
    assert abs(p.j_mm5[0, 0] - jx) / jx < 1e-12
    cont = np.pi * r * r * h
    assert abs((cont - vol) / cont - 7.14e-4) < 1e-5          # matches the dataset's observed 96-segment error


def test_reference_implementation_agrees():
    v, f = prism(64, 12.0, 7.0)
    v = v @ ROTATIONS_F[7].T + [3.0, -4.0, 5.0]
    p = integrate(v, f)
    rv, rc, rj = unit_mass_props_ref(v, f)
    assert abs(rv - p.volume_mm3) / p.volume_mm3 < 1e-12
    assert np.allclose(rc, p.com_mm, atol=1e-10)
    assert np.allclose(rj, p.j_mm5, rtol=1e-10, atol=1e-10 * np.abs(p.j_mm5).max())


def test_precision_guard_origin_shift():
    """Integration far from the origin must not lose precision (bbox-centre shift), for identical geometry."""
    v, f = prism(48, 10.0, 30.0)
    far = (v + 1000.0).astype(np.float32).astype(np.float64)    # float32 STL vertices 1 m from the origin
    near = far - 1000.0                                          # the same geometry, exactly, near the origin
    a, b = integrate(far, f), integrate(near, f)
    assert abs(a.volume_mm3 - b.volume_mm3) / b.volume_mm3 < 1e-12
    assert np.allclose(a.com_mm - 1000.0, b.com_mm, atol=1e-9)
    assert np.abs(a.j_mm5 - b.j_mm5).max() / np.abs(b.j_mm5).max() < 1e-10
    # naive float32 accumulation about the world origin would fail this (documented in the protocol)
    tri = far[f].astype(np.float32)
    d = np.einsum("ij,ij->i", tri[:, 0], np.cross(tri[:, 1], tri[:, 2])).astype(np.float32)
    naive_vol = float(d.sum(dtype=np.float32) / 6)
    assert abs(naive_vol - b.volume_mm3) / b.volume_mm3 > 1e-6


def test_signed_permutation_rotation_is_exact():
    v, f = prism(17, 9.0, 4.0)
    p = integrate(v, f)
    for k, r in enumerate(ROTATIONS_F):
        q = integrate(v @ r.T, f)
        assert np.allclose(q.j_mm5, r @ p.j_mm5 @ r.T, rtol=1e-12, atol=1e-12 * np.abs(p.j_mm5).max())


def test_assembly_matches_merged_mesh():
    va, fa = prism(40, 10.0, 20.0)
    vb, fb = prism(6, 15.0, 5.0)
    pa, pb = integrate(va, fa), integrate(vb, fb)
    dens = 2700.0
    parts = [PartPhys(pa.volume_mm3 * 1e-9 * dens, pa.com_mm, dens * pa.j_mm5 * 1e-15),
             PartPhys(pb.volume_mm3 * 1e-9 * dens, pb.com_mm, dens * pb.j_mm5 * 1e-15)]
    orients, t = [3, 17], np.array([[10.0, -5.0, 30.0], [-20.0, 7.0, -40.0]])
    a = assembly(parts, orients, t)
    wa = va @ ROTATIONS_F[3].T + t[0]
    wb = vb @ ROTATIONS_F[17].T + t[1]
    merged = integrate(np.vstack([wa, wb]), np.vstack([fa, fb + len(va)]))
    assert abs(a.mass_kg - merged.volume_mm3 * 1e-9 * dens) / a.mass_kg < 1e-12
    assert np.allclose(a.com_mm, merged.com_mm, atol=1e-9)
    ref = dens * merged.j_mm5 * 1e-15
    assert np.abs(a.inertia_kgm2 - ref).max() / np.abs(ref).max() < 1e-9


def test_accumulator_drift_and_mass_override():
    rng = np.random.default_rng(0)
    acc = Accumulator()
    items = {}
    for k in range(19):
        m = rng.uniform(0.01, 0.5)
        c = rng.uniform(-100, 100, 3)
        a = rng.normal(size=(3, 3))
        i = (a @ a.T) * 1e-5
        items[str(k)] = (m, c, i)
        acc.set(str(k), m, c, i)
    for _ in range(10000):
        k = str(rng.integers(19))
        m, c, i = items[k]
        c = c + rng.normal(scale=1.0, size=3)
        items[k] = (m, c, i)
        acc.set(k, m, c, i)
    full = Accumulator()
    for k, (m, c, i) in items.items():
        full.set(k, m, c, i)
    a, b = acc.props(), full.props()
    assert abs(a.mass_kg - b.mass_kg) < 1e-12
    assert np.allclose(a.com_mm, b.com_mm, atol=1e-9)
    assert np.abs(a.inertia_kgm2 - b.inertia_kgm2).max() / np.abs(b.inertia_kgm2).max() < 1e-12


def test_mass_override_scales_inertia_not_com(dataset_parts):
    _, rec = dataset_parts["battery_pack"]
    i0, c0, m0 = rec.inertia_com_kgm2(), rec.com_can_mm.copy(), rec.mass_kg
    rec.mass_override_kg = 2 * m0
    try:
        assert np.array_equal(rec.com_can_mm, c0)
        assert np.allclose(rec.inertia_com_kgm2(), 2 * i0, rtol=1e-15)
        assert abs(rec.effective_density - 2 * 2700.0) < 1e-9
    finally:
        rec.mass_override_kg = None


def test_principal_axes_recover_tilted_box(dataset_parts):
    """The payload box was authored in a tilted frame; its principal moments are those of a 60x40x30 box."""
    _, rec = dataset_parts["payload_electronics_box"]
    m = rec.mass_kg
    expected = sorted([m * (40 ** 2 + 30 ** 2) / 12, m * (60 ** 2 + 30 ** 2) / 12, m * (60 ** 2 + 40 ** 2) / 12])
    w, _, _ = principal(rec.inertia_com_kgm2())
    assert np.allclose(w, np.array(expected) * 1e-6, rtol=1e-6)


def test_inertia_metrics_conventions():
    i = np.array([[2.0, -0.1, 0.0], [-0.1, 3.0, 0.0], [0.0, 0.0, 1.0]]) * 1e-3
    m = inertia_metrics(i)
    assert m["lambda_max_kgm2"] == pytest.approx(np.linalg.eigvalsh(i)[-1])
    assert m["trace_kgm2"] == pytest.approx(6e-3)
    assert m["products_norm_kgm2"] == pytest.approx(1e-4)
    assert 0 < m["kappa"] < 1
