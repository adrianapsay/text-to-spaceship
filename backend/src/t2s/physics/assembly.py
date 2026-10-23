"""Assembly mass properties (protocol §E.3).

Units: positions in mm (world frame), masses in kg, inertia in kg·m² about the assembly COM, tensor convention
I = ∫(|r|²E − r rᵀ) dm. Part inertia is rotated with R I Rᵀ (exact for the 24 signed permutations) and shifted
with the parallel-axis theorem. An origin-referenced accumulator gives O(1) updates for single-part edits.
"""
from dataclasses import dataclass

import numpy as np

from ..core.rotations import ROTATIONS_F
from ..massprops.core import misalignment_deg, principal

MM2_TO_M2 = 1e-6


@dataclass
class PartPhys:
    mass_kg: float
    com_can_mm: np.ndarray       # COM in the part's canonical frame
    inertia_com_kgm2: np.ndarray # about the part COM, canonical frame


@dataclass
class AssemblyProps:
    mass_kg: float
    com_mm: np.ndarray
    inertia_kgm2: np.ndarray


def part_world(p: PartPhys, orient: int, t_mm: np.ndarray, rot: np.ndarray | None = None):
    r = ROTATIONS_F[orient] if rot is None else rot
    return r @ p.com_can_mm + np.asarray(t_mm, float), r @ p.inertia_com_kgm2 @ r.T


def assembly(parts: list[PartPhys], orients: list[int], t_mm: np.ndarray, extras: list[tuple] = ()) -> AssemblyProps:
    """extras: (mass_kg, com_world_mm, inertia_kgm2_world_about_own_com) for brackets, frame, etc."""
    items = []
    for p, o, t in zip(parts, orients, np.asarray(t_mm, float)):
        c, i = part_world(p, o, t)
        items.append((p.mass_kg, c, i))
    items.extend(extras)
    m = np.array([x[0] for x in items])
    c = np.array([x[1] for x in items])
    total = float(m.sum())
    com = (m[:, None] * c).sum(axis=0) / total
    inertia = np.zeros((3, 3))
    for mi, ci, ii in items:
        d = (ci - com) * 1e-3
        inertia += ii + mi * (np.dot(d, d) * np.eye(3) - np.outer(d, d))
    return AssemblyProps(total, com, 0.5 * (inertia + inertia.T))


class Accumulator:
    """Origin-referenced sums for O(1) edits: Q = Σ[I_i + m_i(|c_i|²E − c_i c_iᵀ)] (c in metres)."""

    def __init__(self):
        self.m = 0.0
        self.mc = np.zeros(3)
        self.q = np.zeros((3, 3))
        self.terms: dict[str, tuple[float, np.ndarray, np.ndarray]] = {}

    @staticmethod
    def _term(mass, com_mm, inertia):
        c = np.asarray(com_mm, float) * 1e-3
        return mass * c, inertia + mass * (np.dot(c, c) * np.eye(3) - np.outer(c, c))

    def set(self, key: str, mass: float, com_mm: np.ndarray, inertia: np.ndarray):
        self.remove(key)
        mc, q = self._term(mass, com_mm, inertia)
        self.m += mass
        self.mc += mc
        self.q += q
        self.terms[key] = (mass, np.asarray(com_mm, float).copy(), np.asarray(inertia, float).copy())

    def remove(self, key: str):
        if key in self.terms:
            mass, com, inertia = self.terms.pop(key)
            mc, q = self._term(mass, com, inertia)
            self.m -= mass
            self.mc -= mc
            self.q -= q

    def props(self) -> AssemblyProps:
        com_m = self.mc / self.m
        i_c = self.q - self.m * (np.dot(com_m, com_m) * np.eye(3) - np.outer(com_m, com_m))
        return AssemblyProps(self.m, com_m * 1e3, 0.5 * (i_c + i_c.T))


def inertia_metrics(inertia: np.ndarray) -> dict:
    w, axes, degenerate = principal(inertia)
    off = np.array([inertia[0, 1], inertia[0, 2], inertia[1, 2]])
    diag = np.diag(inertia)
    kappa = max(abs(inertia[0, 1]) / np.sqrt(diag[0] * diag[1]), abs(inertia[0, 2]) / np.sqrt(diag[0] * diag[2]),
                abs(inertia[1, 2]) / np.sqrt(diag[1] * diag[2]))
    return {
        "principal_kgm2": w.tolist(),
        "principal_axes": axes.T.tolist(),          # rows = axes
        "axes_degenerate": bool(degenerate),
        "lambda_max_kgm2": float(w[-1]),
        "trace_kgm2": float(np.trace(inertia)),
        "products_norm_kgm2": float(np.linalg.norm(off)),
        "kappa": float(kappa),
        "tilt_deg": misalignment_deg(axes),
        "gravity_gradient_index_kgm2": float(w[-1] - w[0]),
    }


def com_box_check(com_mm: np.ndarray, target_mm=(0.0, 0.0, 0.0), box_mm=None) -> dict:
    if box_mm is None:                       # the CDS box of the active form factor (3U: ±20 / ±20 / ±70 mm)
        from ..core.formfactor import COM_BOX
        box_mm = COM_BOX
    d = np.asarray(com_mm, float) - np.asarray(target_mm, float)
    margin = np.asarray(box_mm, float) - np.abs(np.asarray(com_mm, float))
    return {"com_error_mm": float(np.linalg.norm(d)), "com_box_ok": bool(np.all(margin >= 0)),
            "com_box_margin_mm": margin.tolist()}
