"""Baseline entrant: the V1 rule-based conformal metal-AM bracket in voxel form — a 2 mm plate on the target plane,
a 2 mm shell following the part surface at the contact gap, and two 2.5 mm ribs joining them (no optimisation).
Also two non-generative references: a full machined block, and a sheet-metal Z-bracket."""
from __future__ import annotations

import time

import numpy as np

from ..domain import CONTACT_GAP, DesignDomain, GenResult

NAME = "Rule-based shell + ribs (V1 baseline)"
SHELL, PLATE, RIB = 2.0, 2.0, 2.5


def _part_distance(dom: DesignDomain) -> np.ndarray:
    from scipy.spatial import cKDTree

    from ...geometry.voxel import surface_samples
    c = dom.centres().reshape(-1, 3)
    dist, _ = cKDTree(surface_samples(dom.part_v, dom.part_f, dom.h / 4)).query(c)
    return dist.reshape(dom.shape)


def generate(dom: DesignDomain, budget_s: float = 60.0, threads: int = 2) -> GenResult:
    t0 = time.perf_counter()
    c = dom.centres()
    ax = dom.axis
    from_plane = np.abs(c[..., ax] - dom.plane_mm)
    dist = _part_distance(dom)
    plate = from_plane <= PLATE
    shell = (dist >= CONTACT_GAP) & (dist <= CONTACT_GAP + SHELL)
    b = [k for k in range(3) if k != ax][0]
    lo, hi = dom.reserve[b], dom.reserve[3 + b]
    ribs = np.zeros(dom.shape, bool)
    for frac in (0.25, 0.75):
        ribs |= np.abs(c[..., b] - (lo + frac * (hi - lo))) <= RIB / 2
    solid = (plate | shell | ribs) & ~dom.void
    solid |= dom.fixed | dom.contact
    return GenResult(solid.astype(float), time.perf_counter() - t0, NAME,
                     notes=[f"plate {PLATE} mm, shell {SHELL} mm at {CONTACT_GAP} mm, ribs {RIB} mm at 25 / 75 %"])


def machined_block(dom: DesignDomain, budget_s: float = 0.0, threads: int = 2) -> GenResult:
    """Reference: the whole design space solid (heaviest, stiffest)."""
    t0 = time.perf_counter()
    solid = ~dom.void
    return GenResult(solid.astype(float), time.perf_counter() - t0, "Machined block (reference)",
                     notes=["every non-void voxel solid"])


def sheet_bracket(dom: DesignDomain, budget_s: float = 0.0, threads: int = 2, t: float = 1.5) -> GenResult:
    """Reference: a sheet Z-bracket (two flanges and one web, 1.5 mm) — the simple bracket the V2 packing uses."""
    t0 = time.perf_counter()
    c = dom.centres()
    ax = dom.axis
    from_plane = np.abs(c[..., ax] - dom.plane_mm)
    dist = _part_distance(dom)
    flange_wall = from_plane <= max(t, dom.h * 0.51)
    flange_part = dom.contact | ((dist >= CONTACT_GAP) & (dist <= CONTACT_GAP + max(t, dom.h * 0.51)))
    b = [k for k in range(3) if k != ax][0]
    web = np.abs(c[..., b] - dom.reserve[b]) <= max(t, dom.h * 0.51) + 0.5 * dom.h
    solid = (flange_wall | flange_part | web) & ~dom.void
    solid |= dom.fixed | dom.contact
    return GenResult(solid.astype(float), time.perf_counter() - t0, "Sheet Z-bracket (reference)",
                     notes=[f"{t} mm sheet at the voxel resolution ({dom.h} mm)"])
