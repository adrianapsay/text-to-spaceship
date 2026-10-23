"""Solver-independent FEA problem and result (the contract every solver module implements).

A problem is ONE quadratic tetrahedral mesh (10-node tets, gmsh node ordering, straight edges) plus boundary conditions
given as sets of boundary faces (6-node triangles from `mesh.boundary_faces`), and a list of static load cases. Every
solver receives exactly the same mesh and face sets and applies them in its own way (CalculiX: nodal constraints and
consistent nodal forces; NGSolve: Dirichlet regions and surface integrals), so differences between solvers are
solver differences, not set-up differences.

Units: mm, N, MPa, tonne/mm³, s.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

# gmsh 10-node tetrahedron ordering: corners 0-3, then edge mid-nodes (0-1), (1-2), (2-0), (3-0), (3-2), (3-1).
# (CalculiX C3D10 uses (0-1), (1-2), (2-0), (0-3), (1-3), (2-3): positions 8 and 9 are swapped relative to gmsh.)
GMSH_TET10_EDGES = ((0, 1), (1, 2), (2, 0), (3, 0), (3, 2), (3, 1))


@dataclass
class Material:
    name: str
    E_mpa: float                    # Young's modulus
    nu: float                       # Poisson's ratio
    rho_t_mm3: float                # density, tonne / mm³
    yield_mpa: float | None = None  # allowable inputs for margins (not used by the solvers)
    ultimate_mpa: float | None = None


@dataclass
class SurfaceLoad:
    """A total force (N) spread as a uniform traction (force per area) over a set of boundary faces."""
    faces: np.ndarray                 # (k, 6) boundary 6-node triangles (mesh.boundary_faces rows)
    total_force_n: np.ndarray         # (3,)


@dataclass
class LoadCase:
    """Static load case: surface loads (a part supported by the bracket = its mass × acceleration over the contact
    faces) plus an optional uniform body acceleration (mm/s²) acting on the bracket's own mass."""
    name: str
    surface_loads: list[SurfaceLoad] = field(default_factory=list)
    body_accel_mm_s2: np.ndarray | None = None                          # (3,) applied to the bracket mass


@dataclass
class FeaProblem:
    nodes: np.ndarray                 # (n, 3) mm
    tets: np.ndarray                  # (m, 10) int, gmsh ordering (see GMSH_TET10_EDGES)
    material: Material
    fixed_faces: np.ndarray           # (k, 6) boundary faces whose nodes are fully fixed (all three displacements 0)
    load_cases: list[LoadCase]
    n_modes: int = 3                  # natural frequencies wanted (0 = none)
    exclude_nodes: np.ndarray | None = None   # nodes excluded from the "filtered" peak stress (singular edges)
    label: str = ""
    # non-structural mass: list of (faces (k, 6) boundary faces, mass_t float), each spread uniformly over its faces
    # (mass per area = mass_t / face area). MASS matrix only (modal analysis); load cases do NOT apply body
    # acceleration to it (a held part's inertia load is given separately as a SurfaceLoad).
    added_masses: list = field(default_factory=list)

    def added_mass_t(self) -> float:
        return float(sum(float(m) for _, m in self.added_masses))

    def fixed_nodes(self) -> np.ndarray:
        return np.unique(self.fixed_faces.ravel()) if len(self.fixed_faces) else np.zeros(0, np.int64)

    def volume_mm3(self) -> float:
        p = self.nodes[self.tets[:, :4]]
        return float(np.abs(np.einsum("ij,ij->i", p[:, 1] - p[:, 0],
                                      np.cross(p[:, 2] - p[:, 0], p[:, 3] - p[:, 0]))).sum() / 6.0)

    def mass_t(self) -> float:
        return self.volume_mm3() * self.material.rho_t_mm3


@dataclass
class CaseResult:
    """Stresses are NODAL von Mises values: at every mesh node (corners and mid-sides), the stress TENSOR of each
    element sharing the node, evaluated at the node, is averaged component-wise, and von Mises is taken of that
    averaged tensor (both solvers)."""
    name: str
    max_disp_mm: float                # max |u| over all nodes
    max_vm_mpa: float                 # max nodal von Mises (may be a singular peak)
    max_vm_filtered_mpa: float        # max nodal von Mises over nodes not in exclude_nodes
    reaction_n: np.ndarray            # (3,) force exerted BY the supports ON the part: reaction_n = -applied_n
    applied_n: np.ndarray             # (3,) sum of applied forces incl. body load


@dataclass
class FeaResult:
    solver: str                       # e.g. "CalculiX 2.23" / "NGSolve 6.2.2608"
    cases: list[CaseResult]
    frequencies_hz: list[float]       # lowest natural frequencies, fixed boundary
    mass_t: float
    n_nodes: int
    n_elements: int
    seconds: float
    notes: list[str] = field(default_factory=list)

    def worst(self) -> CaseResult:
        return max(self.cases, key=lambda c: c.max_vm_filtered_mpa)
