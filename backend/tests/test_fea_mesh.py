"""V2 FEA: the shared quadratic-tet mesher and consistent surface loads (both solvers rely on them)."""
import numpy as np
import pytest

from t2s.fea.mesh import boundary_faces, check_tet10, consistent_surface_load, mesh_box, mesh_hollow_cylinder, mesh_surface
from t2s.fea.problem import FeaProblem, Material

AL = Material("AlSi10Mg (ASSUMED)", 70000.0, 0.33, 2.67e-9)


def test_box_mesh_volume_area_and_ordering():
    nodes, tets = mesh_box([0, 0, 0], [20, 10, 6], h=3.0)
    assert tets.shape[1] == 10
    check_tet10(nodes, tets)
    p = nodes[tets[:, :4]]
    vol = np.einsum("ij,ij->i", p[:, 1] - p[:, 0], np.cross(p[:, 2] - p[:, 0], p[:, 3] - p[:, 0])) / 6
    assert (vol > 0).all() and vol.sum() == pytest.approx(20 * 10 * 6, rel=1e-9)
    faces = boundary_faces(tets)
    q = nodes[faces[:, :3]]
    area = 0.5 * np.linalg.norm(np.cross(q[:, 1] - q[:, 0], q[:, 2] - q[:, 0]), axis=1).sum()
    assert area == pytest.approx(2 * (20 * 10 + 20 * 6 + 10 * 6), rel=1e-9)
    # outward normals: the face centroid minus the box centre points along the normal
    n = np.cross(q[:, 1] - q[:, 0], q[:, 2] - q[:, 0])
    assert (np.einsum("ij,ij->i", n, q.mean(axis=1) - np.array([10, 5, 3])) > 0).all()
    prob = FeaProblem(nodes, tets, AL, np.zeros((0, 6), int), [])
    assert prob.mass_t() == pytest.approx(1200 * 2.67e-9)


def test_consistent_load_balances_and_skips_corners():
    nodes, tets = mesh_box([0, 0, 0], [20, 10, 6], h=3.0)
    faces = boundary_faces(tets)
    top = faces[np.all(np.isclose(nodes[faces[:, :3]][:, :, 2], 6.0), axis=1)]
    loads = consistent_surface_load(nodes, top, [0, 0, -100.0])
    total = sum(loads.values())
    assert np.allclose(total, [0, 0, -100.0])
    corners = set(top[:, :3].ravel().tolist())
    assert not (set(loads) & corners)


def test_cylinder_and_surface_meshes():
    nodes, tets = mesh_hollow_cylinder(10.0, 20.0, 30.0, h=3.0)
    p = nodes[tets[:, :4]]
    vol = (np.einsum("ij,ij->i", p[:, 1] - p[:, 0], np.cross(p[:, 2] - p[:, 0], p[:, 3] - p[:, 0])) / 6).sum()
    assert vol == pytest.approx(np.pi * (20 ** 2 - 10 ** 2) * 30, rel=0.02)    # faceted circle
    # a closed triangle surface (an L-shaped bracket made of two boxes) is tetrahedralised
    import manifold3d
    m = manifold3d.Manifold.cube([30, 20, 3]) + manifold3d.Manifold.cube([3, 20, 25])
    mesh = m.to_mesh()
    v = np.asarray(mesh.vert_properties)[:, :3]
    f = np.asarray(mesh.tri_verts)
    n2, t2 = mesh_surface(v, f, h=2.0)
    p = n2[t2[:, :4]]
    vol = (np.einsum("ij,ij->i", p[:, 1] - p[:, 0], np.cross(p[:, 2] - p[:, 0], p[:, 3] - p[:, 0])) / 6).sum()
    assert vol == pytest.approx(m.volume(), rel=1e-6)
