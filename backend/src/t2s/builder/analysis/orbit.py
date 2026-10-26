"""Orbit analyses of the CubeSat Builder (circular orbits; numpy only).

* Basics: period, speed, Sun-synchronous inclination (J2 nodal precession = the mean Sun's), the nodal rate.
* Eclipse: the cylindrical-shadow eclipse fraction for the Sun's beta angle, over a year (sampled daily; the Sun
  from the low-precision almanac formulae).
* Lifetime: circular-orbit decay da/dt = −ρ(h)·(C_D·A/m)·√(μ·a) in the static exponential atmosphere (Vallado),
  integrated until 180 km; solar activity is not modelled.
* Ground track: two-body circular motion with the J2 secular drift of the node and the Earth's rotation, sampled every
  `dt` seconds: access to a target region (within the off-nadir reach, in daylight) and passes over a ground station
  (above its elevation mask).

Units: SI inside (m, s, rad); results in km, min, h, deg as labelled. Fidelity: conceptual (circular orbits,
spherical Earth for geometry, J2 only, static atmosphere).
"""
from __future__ import annotations

import math

import numpy as np

from . import refs as R
from .calc import calc, inp

OBLIQUITY_DEG = 23.4392794          # IERS Conventions (2010): ε0 = 84381.406″ (J2000)
DEORBIT_KM = 180.0                  # the decay integration stops here (re-entry within days below it; ASSUMED)
C_D = 2.2                           # drag coefficient (ASSUMED: the conventional value, not verified here)
DAYLIGHT_SUN_ELEV_DEG = 10.0        # optical imaging needs the Sun at least this high (ASSUMED)


# ================================================================================================== basics
def semi_major(alt_km: float) -> float:
    return R.RE + 1e3 * float(alt_km)


def mean_motion(alt_km: float) -> float:
    a = semi_major(alt_km)
    return math.sqrt(R.MU / a ** 3)


def period_s(alt_km: float) -> float:
    return 2.0 * math.pi / mean_motion(alt_km)


def nodal_rate(alt_km: float, inc_deg: float) -> float:
    """dΩ/dt (rad/s) from J2 for a circular orbit."""
    a = semi_major(alt_km)
    return -1.5 * mean_motion(alt_km) * R.J2 * (R.RE / a) ** 2 * math.cos(math.radians(inc_deg))


def sso_inclination(alt_km: float) -> float:
    """Inclination (deg) whose J2 nodal precession equals the mean Sun's apparent motion; ValueError above the
    altitude where no such inclination exists."""
    a = semi_major(alt_km)
    c = -R.SSO_RATE / (1.5 * mean_motion(alt_km) * R.J2 * (R.RE / a) ** 2)
    if not -1.0 <= c <= 1.0:
        raise ValueError(f"no sun-synchronous inclination at {alt_km:g} km")
    return math.degrees(math.acos(c))


# ================================================================================================== the Sun
def days_since_j2000(year: int, month: int, day: int, hour: float = 12.0) -> float:
    """Days after J2000.0 (2000-01-01 12:00) of a calendar date (UTC taken as TT; seconds do not matter here)."""
    import datetime as _dt
    utc = _dt.UTC
    return ((_dt.datetime(year, month, day, tzinfo=utc) - _dt.datetime(2000, 1, 1, 12, tzinfo=utc)).total_seconds()
            / 86400.0 + hour / 24.0)


EPOCH_D = days_since_j2000(2027, 3, 20)     # analyses start at the March 2027 equinox (ASSUMED season)


def sun_radec(d: np.ndarray | float):
    """Right ascension and declination (rad) of the Sun, d days after J2000.0 (2000-01-01 12:00 TT): the
    low-precision almanac formulae (about 0.01° accuracy, adequate here)."""
    d = np.asarray(d, float)
    L = np.radians(280.460 + 0.9856474 * d)
    g = np.radians(357.528 + 0.9856003 * d)
    lam = L + np.radians(1.915) * np.sin(g) + np.radians(0.020) * np.sin(2 * g)
    eps = np.radians(OBLIQUITY_DEG - 0.0000004 * d)
    ra = np.arctan2(np.cos(eps) * np.sin(lam), np.cos(lam))
    dec = np.arcsin(np.sin(eps) * np.sin(lam))
    return ra, dec


def gmst(d: np.ndarray | float):
    """Greenwich mean sidereal time (rad), d days after J2000.0 (the usual linear approximation)."""
    return np.radians((280.46061837 + 360.98564736629 * np.asarray(d, float)) % 360.0)


# ================================================================================================== eclipse
def eclipse_fraction(alt_km: float, beta_rad):
    """Fraction of a circular orbit in the Earth's (cylindrical) shadow for Sun beta angle β."""
    h, rad = 1e3 * float(alt_km), R.RE + 1e3 * float(alt_km)
    beta = np.abs(np.asarray(beta_rad, float))
    beta_star = math.asin(R.RE / rad)
    cosb = np.cos(beta)
    x = math.sqrt(h * h + 2.0 * R.RE * h) / (rad * np.maximum(cosb, 1e-12))
    f = np.where(beta < beta_star, np.arccos(np.clip(x, -1.0, 1.0)) / math.pi, 0.0)
    return f


def beta_over_year(alt_km: float, inc_deg: float, ltdn_h: float | None, epoch_d: float, days: int = 365,
                   sso: bool = False):
    """The Sun's beta angle (rad), sampled daily for `days` days from epoch_d (days after J2000). A sun-synchronous
    orbit keeps its descending node at the local solar time ltdn_h (Ω − α_sun = 15°·ltdn_h); any other orbit's node
    drifts relative to the Sun at the J2 rate minus the Sun's (starting from ltdn_h when given, else from 0)."""
    t = epoch_d + np.arange(days, dtype=float)
    _, dec = sun_radec(t)
    inc = math.radians(inc_deg)
    dOmega0 = math.radians(15.0 * ltdn_h) if ltdn_h is not None else 0.0        # Ω − α_sun at the epoch
    if sso:
        dOmega = np.full_like(t, dOmega0)
    else:
        drift = (nodal_rate(alt_km, inc_deg) - R.SSO_RATE) * 86400.0                # rad/day relative to the Sun
        dOmega = dOmega0 + drift * (t - epoch_d)
    return np.arcsin(np.cos(dec) * np.sin(inc) * np.sin(dOmega) + np.sin(dec) * np.cos(inc))


# ================================================================================================== lifetime
def density(alt_km: float) -> float:
    """Static exponential atmosphere (Vallado) at alt_km; below 300 km the 300 km row is extended (ASSUMED)."""
    rows = R.ATMOSPHERE
    row = rows[0]
    for r in rows:
        if alt_km >= r[0]:
            row = r
    h0, rho0, H = row
    return rho0 * math.exp(-(alt_km - h0) / H)


def lifetime_years(alt_km: float, mass_kg: float, area_m2: float, cd: float = C_D, max_step_days: float = 30.0,
                   cap_years: float = 300.0) -> float:
    """Years until a circular orbit decays from alt_km to DEORBIT_KM (integration of da/dt with steps of at most
    max_step_days and at most 1 km of decay); inf beyond cap_years."""
    a = semi_major(alt_km)
    B = cd * area_m2 / mass_kg
    t = 0.0
    limit = semi_major(DEORBIT_KM)
    while a > limit:
        h_km = (a - R.RE) / 1e3
        dadt = -density(h_km) * B * math.sqrt(R.MU * a)          # m/s
        step = min(max_step_days * 86400.0, 1000.0 / max(-dadt, 1e-30))
        a += dadt * step
        t += step
        if t > cap_years * 365.25 * 86400:
            return float("inf")
    return t / (365.25 * 86400.0)


# ================================================================================================== ground track
def _unit_ecef(lat, lon):
    return np.stack([np.cos(lat) * np.cos(lon), np.cos(lat) * np.sin(lon), np.sin(lat)], axis=-1)


def track(alt_km: float, inc_deg: float, ltdn_h: float | None, epoch_d: float, days: float, dt_s: float = 10.0):
    """Sub-satellite latitude and longitude (rad), the satellite position in Earth-fixed axes (m), and the time
    (days after J2000), sampled every dt_s seconds for `days` days. Starts at the ascending node."""
    n = mean_motion(alt_km)
    a = semi_major(alt_km)
    inc = math.radians(inc_deg)
    t = np.arange(0.0, days * 86400.0, dt_s)
    d = epoch_d + t / 86400.0
    ra_sun0, _ = sun_radec(epoch_d)
    raan0 = float(ra_sun0) + (math.radians(15.0 * ltdn_h) if ltdn_h is not None else 0.0)
    raan = raan0 + nodal_rate(alt_km, inc_deg) * t
    u = n * t
    # inertial position (circular orbit), then rotate by GMST into Earth-fixed axes
    x = np.cos(raan) * np.cos(u) - np.sin(raan) * np.cos(inc) * np.sin(u)
    y = np.sin(raan) * np.cos(u) + np.cos(raan) * np.cos(inc) * np.sin(u)
    z = np.sin(inc) * np.sin(u)
    th = gmst(d)
    xe = np.cos(th) * x + np.sin(th) * y
    ye = -np.sin(th) * x + np.cos(th) * y
    lat = np.arcsin(np.clip(z, -1.0, 1.0))
    lon = np.arctan2(ye, xe)
    pos = a * np.stack([xe, ye, z], axis=-1)
    return t, d, lat, lon, pos


def reach_angle(alt_km: float, off_nadir_deg: float) -> float:
    """Earth central angle (rad) to the farthest ground point seen at off_nadir_deg from nadir (spherical Earth)."""
    rho = math.asin(R.RE / semi_major(alt_km))                 # angular radius of the Earth seen from orbit
    eta = math.radians(min(off_nadir_deg, math.degrees(rho) - 1e-6))
    eps = math.acos(math.sin(eta) / math.sin(rho))           # elevation angle at the target
    return math.pi / 2.0 - eta - eps


def _sun_elevation(lat, lon, d):
    ra, dec = sun_radec(d)
    ha = gmst(d) + lon - ra
    return np.arcsin(np.sin(lat) * np.sin(dec) + np.cos(lat) * np.cos(dec) * np.cos(ha))


def _dist_to_box(lat, lon, box):
    """Great-circle angle (rad) from points to the nearest point of a lat/lon box (box in degrees)."""
    la0, la1 = math.radians(box["lat_min"]), math.radians(box["lat_max"])
    lo0, lo1 = math.radians(box["lon_min"]), math.radians(box["lon_max"])
    clat = np.clip(lat, la0, la1)
    # longitude clamp on the circle
    mid = 0.5 * (lo0 + lo1)
    dl = (lon - mid + math.pi) % (2 * math.pi) - math.pi
    half = 0.5 * (lo1 - lo0)
    clon = mid + np.clip(dl, -half, half)
    p = _unit_ecef(lat, lon)
    q = _unit_ecef(clat, clon)
    return np.arccos(np.clip(np.einsum("ij,ij->i", p, q), -1.0, 1.0))


def _intervals(mask: np.ndarray, t: np.ndarray, dt: float) -> list[tuple[float, float]]:
    """Contiguous true runs of `mask` as (start, end) times."""
    if not mask.any():
        return []
    m = mask.astype(np.int8)
    edges = np.flatnonzero(np.diff(np.concatenate([[0], m, [0]])))
    return [(float(t[s]), float(t[e - 1] + dt)) for s, e in zip(edges[0::2], edges[1::2])]


def region_access(alt_km: float, inc_deg: float, ltdn_h: float | None, region: dict, off_nadir_deg: float,
                  epoch_d: float, days: float = 7.0, dt_s: float = 10.0, daylight: bool = True) -> dict:
    """Times the region is within reach (off-nadir ≤ off_nadir_deg) — in daylight for optical imaging — over `days`.
    Returns the access windows and the revisit statistics."""
    t, d, lat, lon, _ = track(alt_km, inc_deg, ltdn_h, epoch_d, days, dt_s)
    reach = reach_angle(alt_km, off_nadir_deg)
    ok = _dist_to_box(lat, lon, region) <= reach + 1e-7           # a point inside the box is at distance ~0
    if daylight:
        ok &= _sun_elevation(lat, lon, d) >= math.radians(DAYLIGHT_SUN_ELEV_DEG)
    win = _intervals(ok, t, dt_s)
    starts = np.array([w[0] for w in win])
    gaps = np.diff(starts) / 3600.0 if len(starts) > 1 else np.array([])
    return {"windows": len(win), "per_day": len(win) / days,
            "minutes_per_day": sum(w[1] - w[0] for w in win) / 60.0 / days,
            "mean_gap_h": float(gaps.mean()) if len(gaps) else None,
            "max_gap_h": float(gaps.max()) if len(gaps) else None, "reach_km": reach * R.RE / 1e3,
            "days": days}


def station_passes(alt_km: float, inc_deg: float, ltdn_h: float | None, station: dict, epoch_d: float,
                   days: float = 7.0, dt_s: float = 10.0) -> dict:
    """Passes over a ground station above its elevation mask: count per day, minutes per day, mean pass length."""
    t, _, _, _, pos = track(alt_km, inc_deg, ltdn_h, epoch_d, days, dt_s)
    lat, lon = math.radians(station["lat"]), math.radians(station["lon"])
    g = R.RE * _unit_ecef(np.array([lat]), np.array([lon]))[0]
    up = g / np.linalg.norm(g)
    rel = pos - g
    rng = np.linalg.norm(rel, axis=1)
    elev = np.arcsin(np.clip(rel @ up / rng, -1.0, 1.0))
    ok = elev >= math.radians(station.get("min_elev_deg", 10.0))
    win = _intervals(ok, t, dt_s)
    dur = [(e - s) / 60.0 for s, e in win]
    return {"passes_per_day": len(win) / days, "minutes_per_day": sum(dur) / days,
            "mean_pass_min": float(np.mean(dur)) if dur else None, "max_pass_min": float(max(dur)) if dur else None,
            "max_range_km": float(rng[ok].max() / 1e3) if ok.any() else None, "days": days}


# ================================================================================================== calcs
def orbit_calcs(alt_km: float, inc_deg: float | None, ltdn_h: float | None, sso: bool, src: dict) -> dict:
    """The basic orbit calcs. src: {"alt": where the altitude came from, ...}."""
    out = {}
    T = period_s(alt_km)
    v = math.sqrt(R.MU / semi_major(alt_km))
    out["orbit.period"] = calc("orbit.period", "Orbital period", T / 60.0, "min", "T = 2π·√(a³/μ), a = R_E + h",
                               {"h": inp(alt_km, "km", src["alt"]), "μ": inp(R.MU, "m³/s²", "WGS 84"),
                                "R_E": inp(R.RE / 1e3, "km", "WGS 84")}, refs=["wgs84"], fidelity="preliminary",
                               explain="How long one trip around the Earth takes.")
    out["orbit.speed"] = calc("orbit.speed", "Orbital speed", v / 1e3, "km/s", "v = √(μ/a)",
                              {"h": inp(alt_km, "km", src["alt"])}, refs=["wgs84"], fidelity="preliminary")
    if sso:
        i = sso_inclination(alt_km)
        out["orbit.inclination"] = calc(
            "orbit.inclination", "Sun-synchronous inclination", i, "deg",
            "cos i = −Ω̇_sun / (3/2 · n · J2 · (R_E/a)²), Ω̇_sun = 0.9856°/day",
            {"h": inp(alt_km, "km", src["alt"]), "J2": inp(R.J2, None, "NASA NSSDCA"),
             "n": inp(mean_motion(alt_km), "rad/s", "√(μ/a³)")}, refs=["wgs84", "nssdca_earth", "sso_rate"],
            fidelity="preliminary",
            explain="The tilt that makes the orbit turn with the Sun, so every pass sees the same local time.")
    elif inc_deg is not None:
        out["orbit.inclination"] = calc("orbit.inclination", "Inclination", inc_deg, "deg",
                                        inputs={"i": inp(inc_deg, "deg", src.get("inc", "you"))},
                                        fidelity="preliminary")
    return out


def eclipse_calc(alt_km: float, betas) -> dict:
    """The longest and shortest eclipse over the year (cylindrical shadow)."""
    ef = eclipse_fraction(alt_km, betas)
    T = period_s(alt_km) / 60.0
    b = np.degrees(np.asarray(betas))
    return calc("orbit.eclipse", "Longest eclipse of the year", float(ef.max()) * T, "min",
                "f = arccos(√(h² + 2·R_E·h) / (r·cos β)) / π for |β| < arcsin(R_E/r); eclipse = f · T",
                {"β": inp(f"{b.min():.1f}° to {b.max():.1f}°", "deg", "the Sun's beta angle over the year"),
                 "T": inp(T, "min", "orbital period")},
                ["cylindrical Earth shadow (no penumbra); the year starts at the March 2027 equinox (ASSUMED)"],
                refs=["wgs84", "iers2010"], fidelity="preliminary",
                extra={"shortest_min": float(ef.min()) * T, "fraction_max": float(ef.max()),
                       "beta_min_deg": float(b.min()), "beta_max_deg": float(b.max())},
                explain="The longest time per orbit in the Earth's shadow, when the battery alone powers the "
                        "satellite.")


def access_calc(acc: dict, region: dict, off_nadir_deg: float, revisit_h: float | None, daylight: bool) -> dict:
    """The region's access windows (from region_access) as a calc, against the revisit you asked for."""
    gap = acc["mean_gap_h"]
    ok = None if gap is None or revisit_h is None else gap <= revisit_h
    return calc("orbit.access", f"Looks at {region.get('name', 'the region')} per day", acc["per_day"], "per day",
                "ground track (two-body + J2 node drift) within the off-nadir reach" +
                (", Sun ≥ 10° above the horizon" if daylight else ""),
                {"off-nadir": inp(off_nadir_deg, "deg", "your requirement or the default"),
                 "reach": inp(acc["reach_km"], "km", "ground distance seen at that angle"),
                 "simulated": inp(acc["days"], "days", "from the March 2027 equinox")},
                ["a box around the region (it also covers some land and sea around it)",
                 "spherical Earth for the viewing geometry; weather (clouds) not modelled"],
                refs=["wgs84", "nssdca_earth"], fidelity="preliminary",
                extra={"mean_gap_h": gap, "max_gap_h": acc["max_gap_h"], "minutes_per_day": acc["minutes_per_day"],
                       "revisit_h": revisit_h, "ok": ok},
                explain=(f"On average a new look every {gap:.0f} h (longest gap {acc['max_gap_h']:.0f} h)." if gap
                         else "Fewer than two looks in the simulated days."))


def passes_calc(p: dict, station: dict) -> dict:
    return calc("orbit.passes", f"Contact time with {station.get('name', 'the ground station')}",
                p["minutes_per_day"], "min/day", "elevation ≥ the station's mask, ground track as above",
                {"mask": inp(station.get("min_elev_deg", 10.0), "deg", station.get("source", "station")),
                 "passes": inp(p["passes_per_day"], "per day", "simulated"),
                 "simulated": inp(p["days"], "days", "from the March 2027 equinox")},
                ["spherical Earth; the station at sea level"], refs=["wgs84"], fidelity="preliminary",
                extra={"passes_per_day": p["passes_per_day"], "mean_pass_min": p["mean_pass_min"],
                       "max_pass_min": p["max_pass_min"], "max_range_km": p["max_range_km"]},
                explain="Minutes per day the satellite is above the station's horizon mask, for commands and "
                        "downloads.")
