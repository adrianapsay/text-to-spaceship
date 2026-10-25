"""The CubeSat frame as a structure (V2 frame-bracing one piece): walls, end plates and corner rails as finite
elements on the one-piece grid, held at the ends of the rails.

* Grid: the one-piece grid (gd.multi.one_piece_grid, with even voxel counts so that its 2 × 2 × 2 coarse level lies
  on the same planes) lies exactly on the six inner planes. The frame adds one layer of cells outside them — the walls
  and end plates, constraints.stage2.WALL thick, closed at the edges and corners — sharing the grid's boundary nodes:
  an extended node numbering in which index 0 and n + 2 are the outer planes of the walls.
* Wall cells: Wilson–Taylor incompatible-mode bricks (three bubble modes per displacement component, condensed per
  element), so that one 2 mm layer bends like the plate it is; a trilinear brick through the thickness of a thin wall
  locks in shear and is far too stiff in bending (tests).
* Rails (constraints.stage2.rails): the part of each 8.5 mm corner rail inside the inner box is a column of grid voxels,
  the voxel count across the nearest to the true 6.5 mm; their modulus and density are scaled by the true over the
  voxelised cross-section (axial stiffness and mass exact, the column's own bending approximate). The rails stay
  keep-outs for the one piece (1.2 mm): it bonds to the walls and end plates only, whose faces lie on the grid planes.
* Supports (ASSUMED, the user's choice): the satellite is held at the ends of its four rails — every node of the
  8.5 × 8.5 mm rail-end squares on the outer faces of both end plates is clamped.
* Material: 6061-T6 (gd.materials), the frame's assumed aluminium (constraints.stage2 uses 2,700 kg/m³ for its mass).

Units: mm, N, t, s, MPa.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .materials import fea_material

FRAME_MATERIAL = "6061-T6"
LOCAL = np.array([[n & 1, (n >> 1) & 1, (n >> 2) & 1] for n in range(8)])      # local node n = dx + 2 dy + 4 dz


def _elasticity(E: float, nu: float) -> np.ndarray:
    lam, mu = E * nu / ((1 + nu) * (1 - 2 * nu)), E / (2 * (1 + nu))
    D = np.zeros((6, 6))
    D[:3, :3] = lam
    D[np.arange(3), np.arange(3)] += 2 * mu
    D[3:, 3:] = np.eye(3) * mu
    return D


def _b_rows(B: np.ndarray, col: int, g: np.ndarray) -> None:
    """Strain rows (xx, yy, zz, xy, yz, zx) of one vector-valued shape function with gradient g at dofs col..col+2."""
    B[0, col], B[1, col + 1], B[2, col + 2] = g
    B[3, col], B[3, col + 1] = g[1], g[0]
    B[4, col + 1], B[4, col + 2] = g[2], g[1]
    B[5, col], B[5, col + 2] = g[2], g[0]


def _node_gradients(p: np.ndarray, dims: np.ndarray) -> np.ndarray:
    """(8, 3) gradients of the trilinear shape functions at natural point p ∈ [−1, 1]³ of a brick with edges dims."""
    s = 2.0 * LOCAL - 1.0
    f = 1.0 + s * p
    dndp = np.stack([s[:, 0] * f[:, 1] * f[:, 2], f[:, 0] * s[:, 1] * f[:, 2], f[:, 0] * f[:, 1] * s[:, 2]], axis=1)
    return dndp / 8.0 * (2.0 / dims)


def hex8_im_stiffness(dims, E: float = 1.0, nu: float = 0.3) -> np.ndarray:
    """24 × 24 stiffness of a rectangular brick with edges dims = (a, b, c) and the Wilson–Taylor incompatible modes
    (1 − ξ², 1 − η², 1 − ζ² for every displacement component), condensed (2 × 2 × 2 Gauss points). Local node
    n = dx + 2 dy + 4 dz and dofs 3n + (0, 1, 2), as gd.simp.hex8_stiffness."""
    dims = np.asarray(dims, float).reshape(3)
    D = _elasticity(E, nu)
    g = 1.0 / np.sqrt(3.0)
    K = np.zeros((33, 33))
    w = float(np.prod(dims)) / 8.0                           # det J × the unit Gauss weights
    for a in (-g, g):
        for b in (-g, g):
            for c in (-g, g):
                p = np.array([a, b, c])
                B = np.zeros((6, 33))
                for n, gn in enumerate(_node_gradients(p, dims)):
                    _b_rows(B, 3 * n, gn)
                for m in range(3):                               # bubble m: d(1 − p_m²)/dx_m only
                    gb = np.zeros(3)
                    gb[m] = -2.0 * p[m] * 2.0 / dims[m]
                    for d in range(3):                           # the bubble for each displacement component
                        e = np.zeros((6, 3))
                        _b_rows(e, 0, gb)
                        B[:, 24 + 3 * m + d] = e[:, d]
                K += B.T @ D @ B * w
    Kuu, Kua, Kaa = K[:24, :24], K[:24, 24:], K[24:, 24:]
    Kc = Kuu - Kua @ np.linalg.solve(Kaa, Kua.T)
    return 0.5 * (Kc + Kc.T)


def centre_strain_matrix(dims) -> np.ndarray:
    """6 × 24 strain–displacement matrix at the centre of a brick (the bubble modes have zero gradient there, so this
    is the stress point of both the trilinear and the incompatible-mode brick)."""
    dims = np.asarray(dims, float).reshape(3)
    B = np.zeros((6, 24))
    for n, gn in enumerate(_node_gradients(np.zeros(3), dims)):
        _b_rows(B, 3 * n, gn)
    return B


def elasticity(E: float, nu: float) -> np.ndarray:
    return _elasticity(E, nu)


@dataclass
class FrameLayer:
    """The frame on one grid (module docstring). Extended node index i_e along axis k: 0 is the outer wall plane,
    1 … n_k + 1 the grid's planes, n_k + 2 the opposite outer wall plane; extended cell (a, b, c) spans nodes a … a + 1;
    grid voxel (i, j, k) is extended cell (i + 1, j + 1, k + 1)."""
    origin: np.ndarray
    h: np.ndarray
    shape: tuple
    wall: float
    envelope: np.ndarray
    cells: np.ndarray            # (m, 3) extended cells of the walls, end plates, edges and corners
    cls: np.ndarray              # (m,) bit k set: the cell is the wall thickness along axis k
    rail: np.ndarray             # (nx, ny, nz) bool: grid voxels of the rails
    rail_scale: float            # modulus and density of a rail voxel × this (true / voxelised cross-section)
    rail_voxels_across: tuple    # voxels across a rail (x, y)
    supports: np.ndarray         # extended node ids, clamped
    material: dict

    @property
    def n_ext(self) -> np.ndarray:
        return np.asarray(self.shape, np.int64) + 3

    def node_id(self, ijk: np.ndarray) -> np.ndarray:
        ijk = np.asarray(ijk, np.int64)
        n = self.n_ext
        return ijk[..., 0] + n[0] * (ijk[..., 1] + n[1] * ijk[..., 2])

    def node_xyz(self, ids: np.ndarray) -> np.ndarray:
        ids = np.asarray(ids, np.int64)
        n = self.n_ext
        ijk = np.stack([ids % n[0], (ids // n[0]) % n[1], ids // (n[0] * n[1])], axis=-1)
        out = np.empty(ijk.shape, float)
        for k in range(3):
            i = ijk[..., k]
            x = self.origin[k] + (i - 1) * self.h[k]
            x = np.where(i == 0, self.origin[k] - self.wall, x)
            x = np.where(i == self.shape[k] + 2, self.origin[k] + self.shape[k] * self.h[k] + self.wall, x)
            out[..., k] = x
        return out

    def class_dims(self) -> np.ndarray:
        """(8, 3) cell edges per class (bit k: the wall thickness along axis k, else the grid's h)."""
        bits = (np.arange(8)[:, None] >> np.arange(3)[None, :]) & 1
        return np.where(bits == 1, self.wall, self.h[None, :])

    def cell_enodes(self) -> np.ndarray:
        """(m, 8) extended node ids of the frame cells (local node n = dx + 2 dy + 4 dz)."""
        return self.node_id(self.cells[:, None, :] + LOCAL[None, :, :])

    def grid_enodes(self, idx: np.ndarray) -> np.ndarray:
        """(k, 8) extended node ids of grid voxels idx (k, 3)."""
        return self.node_id(np.asarray(idx, np.int64)[:, None, :] + 1 + LOCAL[None, :, :])

    def cell_volumes(self) -> np.ndarray:
        return np.prod(self.class_dims()[self.cls], axis=1)

    def cell_masses_t(self) -> np.ndarray:
        return self.cell_volumes() * float(self.material["rho_t_mm3"])

    def rail_voxel_mass_t(self) -> float:
        return float(np.prod(self.h)) * float(self.material["rho_t_mm3"]) * self.rail_scale

    def mass_t(self) -> float:
        """Walls, end plates and rails (the rails' voxels with their density scale)."""
        return float(self.cell_masses_t().sum() + int(self.rail.sum()) * self.rail_voxel_mass_t())


@dataclass
class FrameSpec:
    """What the optimiser (gd.simp.solve / framed_problem) needs to put the frame into every level of its grid: the
    grid's origin (the inner box's low corner), the envelope, the acceleration of each load case (mm/s², the frame's
    own weight), the frame's modulus over the design material's (the optimiser's E is 1) and its Poisson ratio."""
    origin: np.ndarray
    accel: list
    e_ratio: float
    nu: float
    envelope: np.ndarray | None = None

    def layer(self, h, shape) -> FrameLayer:
        return frame_layer(self.origin, h, shape, self.envelope)


def frame_spec(origin, accel, design_material: dict, envelope=None) -> FrameSpec:
    m = fea_material(FRAME_MATERIAL)
    return FrameSpec(np.asarray(origin, float), [np.asarray(a, float) for a in accel],
                     float(m["E_mpa"]) / float(design_material["E_mpa"]), float(m["nu"]), envelope)


def frame_layer(origin, h, shape, envelope=None, wall: float | None = None, rail: float | None = None,
                material: str = FRAME_MATERIAL) -> FrameLayer:
    """The frame (module docstring) on the grid (origin, h, shape) lying on the inner planes of `envelope` (default:
    the current CubeSat size, core.formfactor via constraints.stage2)."""
    from ..constraints import stage2 as s2
    origin = np.asarray(origin, float).reshape(3)
    h = np.asarray(h, float).reshape(3)
    shape = tuple(int(x) for x in shape)
    env = np.asarray(s2.ENVELOPE if envelope is None else envelope, float).reshape(3)
    wall = float(s2.WALL if wall is None else wall)
    rail = float(s2.RAIL if rail is None else rail)
    n = np.asarray(shape, np.int64)
    a, b, c = np.meshgrid(np.arange(n[0] + 2), np.arange(n[1] + 2), np.arange(n[2] + 2), indexing="ij")
    ext = np.stack([a.ravel(), b.ravel(), c.ravel()], axis=1)
    thin = (ext == 0) | (ext == n[None, :] + 1)
    cells = ext[thin.any(axis=1)]
    cls = (thin[thin.any(axis=1)] * (1 << np.arange(3))[None, :]).sum(axis=1).astype(np.int64)
    # rails: the part inside the inner box, as the nearest whole number of voxels across, at the corners
    inward = rail - wall
    nr = [max(1, round(float(inward / h[k]))) for k in range(2)]
    rmask = np.zeros(shape, bool)
    xs = [np.arange(nr[0]), np.arange(n[0] - nr[0], n[0])]
    ys = [np.arange(nr[1]), np.arange(n[1] - nr[1], n[1])]
    for xi in xs:
        for yi in ys:
            rmask[np.ix_(xi, yi, np.arange(n[2]))] = True
    scale = inward * inward / (nr[0] * h[0] * nr[1] * h[1])
    half = env / 2.0
    layer = FrameLayer(origin, h, shape, wall, env, cells, cls, rmask, float(scale), tuple(nr), np.zeros(0, np.int64),
                       fea_material(material))
    # supports: the rail-end squares on the outer faces of both end plates
    ni, nj = np.meshgrid(np.arange(n[0] + 3), np.arange(n[1] + 3), indexing="ij")
    ids = []
    for kz in (0, int(n[2]) + 2):
        ijk = np.stack([ni.ravel(), nj.ravel(), np.full(ni.size, kz)], axis=1)
        nid = layer.node_id(ijk)
        xyz = layer.node_xyz(nid)
        sq = (np.abs(xyz[:, 0]) >= half[0] - rail - 1e-9) & (np.abs(xyz[:, 1]) >= half[1] - rail - 1e-9)
        ids.append(nid[sq])
    layer.supports = np.unique(np.concatenate(ids))
    return layer
