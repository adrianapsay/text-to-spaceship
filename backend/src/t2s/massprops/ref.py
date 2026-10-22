"""Independent second mass-property implementation (Eberly's polyhedral integration via trimesh).

Used only as a cross-check of massprops.core; never for transforms (trimesh's parallel-axis branch of
transform_inertia uses R^T (I + mM) R, which is not what we want).
"""
import numpy as np
import trimesh


def unit_mass_props_ref(v: np.ndarray, f: np.ndarray):
    m = trimesh.Trimesh(vertices=np.asarray(v, dtype=np.float64), faces=np.asarray(f), process=False)
    props = m.mass_properties          # density 1
    return float(props.volume), np.asarray(props.center_mass, dtype=np.float64), np.asarray(props.inertia)
