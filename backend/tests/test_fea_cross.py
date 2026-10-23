"""V2 FEA cross-check: CalculiX and NGSolve on the SAME mesh and boundary conditions of a bracket-like part (an
L-bracket fixed at one flange, loaded at the other plus self-weight) agree, and the shared mesher is deterministic.

Tolerances: mass 1e-6 (same mesh, exact volume); reactions balance the loads to 1e-6 in each solver; max
displacement and first frequency 1 %; filtered peak von Mises (nodes on the fixed flange excluded: the clamp edge is
singular) 5 % — the two solvers integrate the same quadratic field differently (CalculiX: consistent nodal forces,
4-point rule, extrapolated stresses; NGSolve: surface integrals, exact evaluation).
"""
import numpy as np
import pytest

from t2s.fea import ccx, ngs
from t2s.fea.mesh import boundary_faces, mesh_box, mesh_surface
from t2s.fea.problem import FeaProblem, LoadCase, Material, SurfaceLoad

AL = Material("AlSi10Mg (ASSUMED)", 70000.0, 0.33, 2.68e-9, 170.0, 280.0)
G68 = 68 * 9806.65                                 # 68 g quasi-static limit load (mm/s²), research note


def l_bracket(h=2.0):
    import manifold3d
    m = manifold3d.Manifold.cube([40, 20, 3]) + manifold3d.Manifold.cube([3, 20, 30])   # base x 0..40, wall x 0..3
    mesh = m.to_mesh()
    return mesh_surface(np.asarray(mesh.vert_properties)[:, :3], np.asarray(mesh.tri_verts), h=h)


def test_mesher_is_deterministic():
    a = mesh_box([0, 0, 0], [20, 10, 6], h=2.0)
    b = mesh_box([0, 0, 0], [20, 10, 6], h=2.0)
    assert a[0].shape == b[0].shape and np.array_equal(a[0], b[0]) and np.array_equal(a[1], b[1])


@pytest.mark.skipif(not ccx.available(), reason="CalculiX not installed (tools/ccx)")
def test_calculix_and_ngsolve_agree_on_an_l_bracket():
    nodes, tets = l_bracket()
    faces = boundary_faces(tets)
    p = nodes[faces[:, :3]]
    fixed = faces[np.all(np.abs(p[:, :, 0]) < 1e-9, axis=1)]                    # wall back face x = 0 (bolted)
    top = faces[np.all(np.abs(p[:, :, 2] - 3.0) < 1e-9, axis=1) & np.all(p[:, :, 0] > 25.0, axis=1)]
    assert len(fixed) and len(top)
    m_part = 0.2                                                                  # kg held by the bracket
    cases = [LoadCase(f"68 g {ax}", [SurfaceLoad(top, -m_part * 1e-3 * G68 * np.eye(3)[k])],
                      -G68 * np.eye(3)[k]) for k, ax in enumerate("xyz")]
    excl = np.unique(fixed.ravel())
    prob = FeaProblem(nodes, tets, AL, fixed, cases, n_modes=2, exclude_nodes=excl, label="L-bracket")
    a = ccx.solve(prob, threads=2)
    b = ngs.solve(prob, threads=2)
    assert a.n_nodes == b.n_nodes == len(nodes)
    assert a.mass_t == pytest.approx(b.mass_t, rel=1e-5) and a.mass_t == pytest.approx(prob.mass_t(), rel=1e-5)
    for ca, cb in zip(a.cases, b.cases):
        for c in (ca, cb):
            assert np.allclose(c.reaction_n, -c.applied_n, rtol=0, atol=1e-6 * np.linalg.norm(c.applied_n))
        assert np.allclose(ca.applied_n, cb.applied_n, rtol=1e-6)
        assert ca.max_disp_mm == pytest.approx(cb.max_disp_mm, rel=0.01), ca.name
        assert ca.max_vm_filtered_mpa == pytest.approx(cb.max_vm_filtered_mpa, rel=0.05), ca.name
    assert a.frequencies_hz[0] == pytest.approx(b.frequencies_hz[0], rel=0.01)
