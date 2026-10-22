"""Multi-label geometric classification from descriptors (protocol §C)."""
import numpy as np

from .mesh import face_areas


def planar_area_fraction(v: np.ndarray, f: np.ndarray, min_share: float = 0.03) -> float:
    n = np.cross(v[f[:, 1]] - v[f[:, 0]], v[f[:, 2]] - v[f[:, 0]])
    ln = np.linalg.norm(n, axis=1)
    ok = ln > 0
    n = n[ok] / ln[ok, None]
    a = 0.5 * ln[ok]
    keys = np.round(n, 3) + 0.0
    _, inv = np.unique(keys, axis=0, return_inverse=True)
    sums = np.bincount(inv.ravel(), weights=a)
    total = a.sum()
    return float(sums[sums >= min_share * total].sum() / total) if total > 0 else 0.0


def descriptors(v, f, volume, hull_volume, obb_extents, principal_moments, genus, components) -> dict:
    area = float(face_areas(v, f).sum())
    e = np.sort(np.asarray(obb_extents, float))[::-1]
    aabb = v.max(axis=0) - v.min(axis=0)
    pm = np.sort(np.asarray(principal_moments, float))
    return {
        "surface_area_mm2": area,
        "solidity": float(volume / hull_volume) if hull_volume > 0 else None,
        "obb_fill": float(volume / np.prod(e)) if np.prod(e) > 0 else None,
        "aabb_fill": float(volume / np.prod(aabb)) if np.prod(aabb) > 0 else None,
        "sphericity": float(np.pi ** (1 / 3) * (6 * volume) ** (2 / 3) / area) if area > 0 else None,
        "thinness": float(e[2] / e[1]) if e[1] > 0 else None,
        "elongation": float(e[0] / e[1]) if e[1] > 0 else None,
        "planar_area_fraction": planar_area_fraction(v, f),
        "symmetric": bool(abs(pm[1] - pm[0]) / pm[2] < 0.02 or abs(pm[2] - pm[1]) / pm[2] < 0.02) if pm[2] > 0 else False,
        "genus": genus,
        "components": components,
    }


def labels(d: dict) -> list[str]:
    out = []
    if d["obb_fill"] is not None and d["obb_fill"] >= 0.90:
        out.append("box-like")
    s = d["solidity"]
    if s is not None:
        if s >= 0.98:
            out.append("convex")
        elif s >= 0.90:
            out.append("mildly concave")
        else:
            out.append("strongly concave")
    if d["thinness"] is not None:
        if d["thinness"] < 0.10:
            out.append("thin")
        elif d["thinness"] < 0.25:
            out.append("plate-like")
    if d["elongation"] is not None and d["elongation"] > 1.8:
        out.append("elongated")
    if d["planar_area_fraction"] < 0.25:
        out.append("curved")
    elif d["planar_area_fraction"] > 0.95:
        out.append("planar-faceted")
    if s is not None and s < 0.90 and d["planar_area_fraction"] < 0.25 and not d["symmetric"]:
        out.append("highly irregular")
    if (d["genus"] or 0) > 0:
        out.append(f"through-hole (genus {d['genus']})")
    if d["components"] > 1:
        out.append("multi-body")
    return out


SUBSYSTEM_KEYWORDS = [
    ("power", ("battery", "eps", "power", "solar")),
    ("electronics", ("pcb", "obc", "electronics", "board", "computer", "radio", "transceiver")),
    ("adcs", ("wheel", "magnetorquer", "torquer", "magnetometer", "gyro", "imu", "sun_sensor", "adcs")),
    ("tanks", ("tank", "propellant", "thruster", "gas")),
    ("payload", ("camera", "payload", "sensor", "optics", "baffle", "lens", "telescope")),
    ("structure", ("bracket", "hub", "frame", "channel", "rail", "gear", "mechanism", "structure")),
]


def suggest_subsystem(name: str) -> str:
    low = name.lower()
    for sub, keys in SUBSYSTEM_KEYWORDS:
        if any(k in low for k in keys):
            return sub
    return "unknown"
