"""V2 frame-bracing one piece: the frame model (gd.frame) — the thin-wall brick, the walls, end plates and rails on the
one-piece grid, and the rail-end supports."""
import numpy as np
import pytest
import scipy.sparse as sp
import scipy.sparse.linalg as spla

from t2s.constraints import stage2 as s2
from t2s.gd.frame import LOCAL, frame_layer, hex8_im_stiffness
from t2s.gd.simp import hex8_stiffness


def _cantilever_tip(KE_fn, L=80.0, t=2.0, n=30, E=70000.0, nu=0.33, P=1.0):
    """Tip deflection of a square-section cantilever (t × t, length L along x) of n bricks, one across the section,
    clamped at x = 0, a total force P along z at the tip (shared by its four nodes)."""
    dims = np.array([L / n, t, t])
    KE = KE_fn(dims, E, nu)
    def nid(i, j, k):
        return i + (n + 1) * (j + 2 * k)

    rows, cols, vals = [], [], []
    for e in range(n):
        nodes = [nid(e + dx, dy, dz) for dx, dy, dz in LOCAL]
        dofs = np.array([[3 * a, 3 * a + 1, 3 * a + 2] for a in nodes]).ravel()
        rows.append(np.repeat(dofs, 24))
        cols.append(np.tile(dofs, 24))
        vals.append(KE.ravel())
    N = 3 * (n + 1) * 4
    K = sp.csr_matrix((np.concatenate(vals), (np.concatenate(rows), np.concatenate(cols))), shape=(N, N))
    fixed = np.array([3 * nid(0, j, k) + d for j in (0, 1) for k in (0, 1) for d in range(3)])
    free = np.setdiff1d(np.arange(N), fixed)
    f = np.zeros(N)
    for j in (0, 1):
        for k in (0, 1):
            f[3 * nid(n, j, k) + 2] = P / 4
    u = np.zeros(N)
    u[free] = spla.spsolve(K[free][:, free].tocsc(), f[free])
    return float(np.mean([u[3 * nid(n, j, k) + 2] for j in (0, 1) for k in (0, 1)]))


def test_the_incompatible_mode_brick_has_six_rigid_body_modes_and_is_symmetric():
    K = hex8_im_stiffness([2.7, 2.7, 2.0], 68300.0, 0.33)
    w = np.linalg.eigvalsh(K)
    assert np.allclose(K, K.T)
    assert np.sum(np.abs(w) < 1e-8 * w.max()) == 6 and w.min() > -1e-8 * w.max()


def test_one_layer_of_incompatible_mode_bricks_bends_as_beam_theory_says():
    """A 2 × 2 mm cantilever, 80 mm long, one brick across (bricks 2.67 mm long, as a wall cell): beam theory gives
    P L³ / (3 E I) (shear deformation adds 0.1 %). The incompatible-mode brick is within 5 %; the trilinear brick locks
    in shear and comes out almost twice as stiff (measured: 53 % of the deflection)."""
    L, t, E = 80.0, 2.0, 70000.0
    exact = 1.0 * L ** 3 / (3 * E * t ** 4 / 12)
    im = _cantilever_tip(hex8_im_stiffness, L, t, E=E)
    lin = _cantilever_tip(hex8_stiffness, L, t, E=E)
    assert abs(im / exact - 1.0) < 0.05
    assert lin / exact < 0.6


def test_the_frame_layer_has_the_frame_volume_and_mass():
    """Walls, end plates (outer box − inner box) and the rails' inner part: the same volume as
    constraints.stage2.frame_mass_props (exact), the mass within 1 % (6061-T6 at 2,710 against 2,700 kg/m³)."""
    lo, hi = s2.inner_box()
    from t2s.gd.multi import one_piece_grid
    origin, h, shape = one_piece_grid(lo, hi, False, even=True)
    layer = frame_layer(origin, h, shape)
    assert all(n % 2 == 0 for n in shape)
    m_ref = s2.frame_mass_props()[0]
    vol = layer.cell_volumes().sum() + int(layer.rail.sum()) * float(np.prod(h)) * layer.rail_scale
    assert vol == pytest.approx(m_ref / s2.AL_DENSITY * 1e9, rel=1e-9)
    assert layer.mass_t() * 1e3 == pytest.approx(m_ref, rel=0.01)
    env = s2.ENVELOPE
    assert layer.cell_volumes().sum() == pytest.approx(np.prod(env) - np.prod(hi - lo), rel=1e-12)


def _tiny(with_part=True):
    """A 20 × 20 × 24 mm frame (its 8.5 mm rails nearly fill it) with a small bracket on the −y wall holding a part."""
    from t2s.gd.frame_eval import Rigid, assemble
    from t2s.gd.multi import one_piece_grid
    env = np.array([20.0, 20.0, 24.0])
    lo, hi = -(env / 2 - s2.WALL), env / 2 - s2.WALL
    origin, h, shape = one_piece_grid(lo, hi, False, even=True)
    block = np.zeros(shape, bool)
    block[2:4, 0:3, 2:4] = True
    solids = [(block, "AlSi10Mg", "test bracket")] if with_part else []
    centre = origin + (np.array([3.0, 1.5, 3.0])) * h
    parts = [Rigid("p", 0.05, centre + np.array([0.5, 2.0, -0.3]), np.diag([2e-6, 3e-6, 4e-6]), block)] \
        if with_part else []
    return env, origin, h, shape, solids, parts, assemble(origin, h, shape, solids, parts, env)


def test_the_modal_effective_masses_add_up_to_the_total_mass():
    """Every mode of a small model (dense solve): Σ_k Γ_kj² equals the free mass rᵀ M r along each axis, the rigid
    part's 50 g included (it is tied RBE3-like: mass, no stiffness)."""
    import scipy.linalg as sl
    *_, md = _tiny()
    p = md.p
    Ku = md.K.toarray()
    K = Ku + Ku.T - np.diag(np.diag(Ku))
    n = p.ndof
    M = np.stack([md.mass_mv(np.eye(n)[:, i]) for i in range(n)], axis=1)
    free = ~p.cons
    w, phi = sl.eigh(K[np.ix_(free, free)], M[np.ix_(free, free)])
    assert w.min() > 0
    for j in range(3):
        r = np.zeros(n)
        r[3 * np.arange(p.nn) + j] = 1.0
        r[p.cons] = 0.0
        g = phi.T @ (M[np.ix_(free, free)] @ r[free])
        assert np.sum(g ** 2) == pytest.approx(r @ M @ r, rel=1e-9)
    part_only = md.total_mass_kg() - md.mnode.sum() * 1e3
    assert part_only == pytest.approx(0.05)


def test_the_bare_frame_matches_ngsolve_on_quadratic_tets():
    """The bare 1U frame (100 × 100 × 113.5 mm) held at its rail ends: the voxel model (incompatible-mode wall bricks,
    rails as scaled voxels, lumped masses) against NGSolve on a quadratic-tet mesh of the true geometry (consistent
    masses): mass, first natural frequency and the largest 1 g deflection, each within 10 %."""
    from t2s.fea import ngs
    from t2s.fea.mesh import boundary_faces, mesh_frame
    from t2s.fea.problem import FeaProblem, LoadCase, Material
    from t2s.gd.environment import G0
    from t2s.gd.frame_eval import frame_check
    from t2s.gd.materials import fea_material
    from t2s.gd.multi import one_piece_grid
    env = np.array([100.0, 100.0, 113.5])
    lo, hi = -(env / 2 - s2.WALL), env / 2 - s2.WALL
    origin, h, shape = one_piece_grid(lo, hi, False, even=True)
    vox = frame_check(origin, h, shape, [], [], envelope=env, n_modes=6, threads=2)
    nodes, tets = mesh_frame(env, s2.WALL, s2.RAIL, 5.0)
    faces = boundary_faces(tets)
    p3 = nodes[faces[:, :3]]
    half = env / 2
    on_end = np.all(np.abs(np.abs(p3[:, :, 2]) - half[2]) < 1e-6, axis=1)
    in_sq = np.all((np.abs(p3[:, :, 0]) >= half[0] - s2.RAIL - 1e-6) &
                   (np.abs(p3[:, :, 1]) >= half[1] - s2.RAIL - 1e-6), axis=1)
    m = fea_material("6061-T6")
    prob = FeaProblem(nodes, tets, Material("6061-T6", m["E_mpa"], m["nu"], m["rho_t_mm3"]), faces[on_end & in_sq],
                      [LoadCase(f"1 g {a}", [], G0 * np.eye(3)[k]) for k, a in enumerate("xyz")], n_modes=3)
    res = ngs.solve(prob, threads=2)
    d_vox = vox["max_deflection_mm"] / vox["static_g"]
    d_tet = max(c.max_disp_mm for c in res.cases)
    print(f"\n[frame vs NGSolve] mass {vox['frame_mass_kg']:.4f} / {prob.mass_t() * 1e3:.4f} kg; f1 {vox['f1_hz']:.1f} / "
          f"{res.frequencies_hz[0]:.1f} Hz; 1 g deflection {d_vox:.3e} / {d_tet:.3e} mm; tets {len(tets)}")
    assert vox["frame_mass_kg"] == pytest.approx(prob.mass_t() * 1e3, rel=0.01)
    assert vox["f1_hz"] == pytest.approx(res.frequencies_hz[0], rel=0.10)
    assert d_vox == pytest.approx(d_tet, rel=0.10)


def test_the_modes_stop_where_memory_ends_and_the_rest_act_through_the_residual():
    """The memory guard sees PARDISO's forecast before the factorisation; when it refuses a larger eigensolver basis,
    the modes computed so far are kept and noted (the bare 1U frame, 2 modes first: below the 2.4 kHz the GEVS spectra
    need)."""
    from t2s.gd.frame_eval import frame_check
    from t2s.gd.multi import one_piece_grid
    env = np.array([100.0, 100.0, 113.5])
    lo, hi = -(env / 2 - s2.WALL), env / 2 - s2.WALL
    origin, h, shape = one_piece_grid(lo, hi, False, even=True)
    needs = []

    def guard(ndof, what, need_mb=None):
        needs.append(need_mb)
        if len(needs) > 1:
            raise MemoryError("no room for more modes")
    out = frame_check(origin, h, shape, [], [], envelope=env, n_modes=2, threads=2, mem_guard=guard)
    assert len(needs) == 2 and needs[0] > needs[1] > 0
    assert out["n_modes"] == 2 and out["highest_mode_hz"] < 2400.0
    assert any("modes limited to 2 by memory" in n for n in out["notes"])


def test_the_supports_are_the_rail_end_squares_of_both_end_plates():
    lo, hi = s2.inner_box()
    from t2s.gd.multi import one_piece_grid
    origin, h, shape = one_piece_grid(lo, hi, False, even=True)
    layer = frame_layer(origin, h, shape)
    xyz = layer.node_xyz(layer.supports)
    half = s2.ENVELOPE / 2
    assert np.allclose(np.abs(xyz[:, 2]), half[2])
    assert np.all(np.abs(xyz[:, 0]) >= half[0] - s2.RAIL - 1e-9) and np.all(np.abs(xyz[:, 1]) >= half[1] - s2.RAIL - 1e-9)
    corners = {(np.sign(x), np.sign(y), np.sign(z)) for x, y, z in xyz}
    assert len(corners) == 8
    per = len(layer.supports) // 8
    assert len(layer.supports) == 8 * per and per >= 9
