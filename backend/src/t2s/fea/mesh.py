"""Shared quadratic tetrahedral meshing (gmsh) and consistent surface loads for the FEA solvers.

Every solver gets the same `nodes` / `tets` (10-node, gmsh ordering, straight edges: `Mesh.SecondOrderLinear = 1`),
so mid-side nodes are exact edge midpoints; `check_tet10` verifies the ordering instead of trusting documentation.
Meshing runs single-threaded with a fixed seed by default: multi-threaded gmsh gave a different mesh on every call.
"""
from __future__ import annotations

import threading

import numpy as np

from .problem import GMSH_TET10_EDGES

_LOCK = threading.Lock()          # gmsh keeps global state: one model at a time per process


def _start(h: float, threads: int):
    import gmsh
    if not gmsh.isInitialized():
        gmsh.initialize(interruptible=False)
    gmsh.clear()
    gmsh.option.setNumber("General.Terminal", 0)
    gmsh.option.setNumber("General.NumThreads", threads)   # 1 (default): the same input gives the same mesh
    gmsh.option.setNumber("Mesh.RandomSeed", 1)
    gmsh.option.setNumber("Mesh.CharacteristicLengthMin", h * 0.5)
    gmsh.option.setNumber("Mesh.CharacteristicLengthMax", h)
    gmsh.option.setNumber("Mesh.SecondOrderLinear", 1)
    gmsh.option.setNumber("Mesh.Algorithm3D", 1)       # Delaunay
    return gmsh


def _extract_tet10(gmsh) -> tuple[np.ndarray, np.ndarray]:
    gmsh.model.mesh.generate(3)
    gmsh.model.mesh.setOrder(2)
    tags, xyz, _ = gmsh.model.mesh.getNodes()
    nodes = xyz.reshape(-1, 3)
    index = {int(t): i for i, t in enumerate(tags)}
    etypes, _, enodes = gmsh.model.mesh.getElements(3)
    tets = []
    for et, en in zip(etypes, enodes):
        if et == 11:                                        # 10-node tetrahedron
            tets.append(np.array([index[int(t)] for t in en], dtype=np.int64).reshape(-1, 10))
    if not tets:
        raise ValueError("gmsh produced no quadratic tetrahedra")
    tets = np.vstack(tets)
    used = np.unique(tets)                                  # drop nodes of lower-dimensional entities not in tets
    remap = -np.ones(len(nodes), dtype=np.int64)
    remap[used] = np.arange(len(used))
    nodes, tets = nodes[used], remap[tets]
    _orient(nodes, tets)
    check_tet10(nodes, tets)
    return nodes.astype(float), tets


def _orient(nodes, tets) -> None:
    """Make every tet positively oriented (swap corners 1 and 2 with their edge nodes where needed)."""
    p = nodes[tets[:, :4]]
    vol = np.einsum("ij,ij->i", p[:, 1] - p[:, 0], np.cross(p[:, 2] - p[:, 0], p[:, 3] - p[:, 0]))
    neg = vol < 0
    if neg.any():
        t = tets[neg]
        # swapping corners 1<->2 maps edges (0,1)<->(2,0) [4<->6], (1,2) stays [5], (3,1)<->(3,2) [9<->8]
        tets[neg] = t[:, [0, 2, 1, 3, 6, 5, 4, 7, 9, 8]]


def check_tet10(nodes: np.ndarray, tets: np.ndarray, tol: float = 1e-6) -> None:
    """Mid-side nodes must be the midpoints of the edges GMSH_TET10_EDGES names (straight-sided quadratic tets)."""
    for k, (a, b) in enumerate(GMSH_TET10_EDGES):
        mid = 0.5 * (nodes[tets[:, a]] + nodes[tets[:, b]])
        err = np.abs(nodes[tets[:, 4 + k]] - mid).max()
        if err > tol * max(1.0, float(np.abs(nodes).max())):
            raise ValueError(f"tet10 node {4 + k} is not the midpoint of edge {a}-{b} (error {err:.3g} mm)")


def mesh_box(lo, hi, h: float, threads: int = 1):
    with _LOCK:
        gmsh = _start(h, threads)
        lo, hi = np.asarray(lo, float), np.asarray(hi, float)
        gmsh.model.occ.addBox(*lo, *(hi - lo))
        gmsh.model.occ.synchronize()
        return _extract_tet10(gmsh)


def mesh_hollow_cylinder(ri: float, ro: float, length: float, h: float, threads: int = 1):
    """Axis along +z from z = 0 to z = length."""
    with _LOCK:
        gmsh = _start(h, threads)
        outer = gmsh.model.occ.addCylinder(0, 0, 0, 0, 0, length, ro)
        inner = gmsh.model.occ.addCylinder(0, 0, 0, 0, 0, length, ri)
        gmsh.model.occ.cut([(3, outer)], [(3, inner)])
        gmsh.model.occ.synchronize()
        return _extract_tet10(gmsh)


def mesh_surface(v: np.ndarray, f: np.ndarray, h: float, threads: int = 1, remesh: bool = True):
    """Tetrahedralise a closed, consistently oriented triangle mesh (a bracket STL). remesh=False keeps the given
    surface triangles as the boundary of the tet mesh (the solid meshed is exactly the solid given — used for designed
    brackets, whose surface is the certified one)."""
    import os
    import tempfile
    from ..geometry.stl_io import write_binary_stl
    with _LOCK:
        gmsh = _start(h, threads)
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "surface.stl")
            write_binary_stl(p, np.asarray(v, float), np.asarray(f, np.int64))
            gmsh.merge(p)
        if remesh:
            gmsh.model.mesh.classifySurfaces(40 * np.pi / 180, True, True, np.pi)
            gmsh.model.mesh.createGeometry()
        surfaces = [s[1] for s in gmsh.model.getEntities(2)]
        loop = gmsh.model.geo.addSurfaceLoop(surfaces)
        gmsh.model.geo.addVolume([loop])
        gmsh.model.geo.synchronize()
        return _extract_tet10(gmsh)


def boundary_faces(tets: np.ndarray) -> np.ndarray:
    """Boundary 6-node triangles as (k, 6): corners (a, b, c) outward-ordered, then mid-nodes (ab, bc, ca)."""
    corner = {0: (1, 2, 3), 1: (0, 3, 2), 2: (0, 1, 3), 3: (0, 2, 1)}       # face opposite each vertex, outward
    edge_node = {}
    for k, (a, b) in enumerate(GMSH_TET10_EDGES):
        edge_node[(a, b)] = 4 + k
        edge_node[(b, a)] = 4 + k
    faces = {}
    for opp, (a, b, c) in corner.items():
        tri = tets[:, [a, b, c, edge_node[(a, b)], edge_node[(b, c)], edge_node[(c, a)]]]
        for row in tri:
            key = tuple(sorted(row[:3].tolist()))
            if key in faces:
                del faces[key]
            else:
                faces[key] = row
    return np.array(list(faces.values()), dtype=np.int64).reshape(-1, 6)


def consistent_surface_load(nodes: np.ndarray, faces: np.ndarray, total_force) -> dict[int, np.ndarray]:
    """Spread a total force over the given 6-node boundary triangles as a uniform traction (force per area):
    for a straight-sided quadratic triangle the consistent nodal loads are 0 at the corners and 1/3 of the face's
    share at each mid-side node."""
    total_force = np.asarray(total_force, float)
    p = nodes[faces[:, :3]]
    area = 0.5 * np.linalg.norm(np.cross(p[:, 1] - p[:, 0], p[:, 2] - p[:, 0]), axis=1)
    out: dict[int, np.ndarray] = {}
    share = area / area.sum()
    for fi in range(len(faces)):
        for n in faces[fi, 3:]:
            out[int(n)] = out.get(int(n), np.zeros(3)) + total_force * share[fi] / 3.0
    return out


def nodes_where(nodes: np.ndarray, mask_fn) -> np.ndarray:
    return np.flatnonzero(mask_fn(nodes))
