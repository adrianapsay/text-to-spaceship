"""Orbit lifetime, disposal and propulsion (conceptual).

* Lifetime: the circular-orbit decay of orbit.lifetime_years (Vallado's static exponential atmosphere, C_D 2.2) for
  the satellite's mean cross-section (surface area / 4; the smallest and largest faces bound it). Solar activity
  changes the upper atmosphere's density several-fold, so the lifetime is uncertain by about that factor.
* Disposal: the FCC requires a satellite in low Earth orbit to be disposed of within five years of the end of its
  mission (89 FR 65217, for satellites launched after 29 September 2024): the natural decay must take at most
  mission + 5 years, or the satellite needs a way down (a thruster or a drag device).
* Δv: holding the altitude against drag for the mission (Δv = a_drag · t), lowering the orbit to one that decays in
  five years (Hohmann transfer, conservative), and what a selected thruster gives (Δv = I_total / m, or the rocket
  equation from its propellant).
"""
from __future__ import annotations

import math
import re

from .. import catalog as K
from ..catalog import parse as P
from . import orbit as O
from . import refs as R
from .calc import calc, inp, missing

LIFETIME_MARGIN = 1.5          # natural lifetime ≥ this × the mission (solar activity uncertainty; ASSUMED)
YEAR_S = 365.25 * 86400.0


def drag_accel(alt_km: float, mass_kg: float, area_m2: float, cd: float = O.C_D) -> float:
    v = math.sqrt(R.MU / O.semi_major(alt_km))
    return 0.5 * O.density(alt_km) * v * v * cd * area_m2 / mass_kg


def altitude_for_lifetime(years: float, mass_kg: float, area_m2: float, lo: float = 250.0, hi: float = 1000.0) -> float:
    """The circular altitude (km) whose natural lifetime is `years` (bisection; lo/hi when out of range)."""
    if O.lifetime_years(lo, mass_kg, area_m2) >= years:
        return lo
    if O.lifetime_years(hi, mass_kg, area_m2) <= years:
        return hi
    for _ in range(40):
        mid = 0.5 * (lo + hi)
        if O.lifetime_years(mid, mass_kg, area_m2) < years:
            lo = mid
        else:
            hi = mid
        if hi - lo < 0.5:
            break
    return 0.5 * (lo + hi)


def hohmann_dv(alt1_km: float, alt2_km: float) -> float:
    """Δv (m/s) of a two-burn Hohmann transfer between circular orbits."""
    r1, r2 = O.semi_major(alt1_km), O.semi_major(alt2_km)
    a = 0.5 * (r1 + r2)
    v1, v2 = math.sqrt(R.MU / r1), math.sqrt(R.MU / r2)
    vp, va = math.sqrt(R.MU * (2 / r1 - 1 / a)), math.sqrt(R.MU * (2 / r2 - 1 / a))
    return abs(vp - v1) + abs(v2 - va)


def thruster_dv(c: dict, m0_kg: float) -> tuple[float | None, str, bool]:
    """Δv (m/s) a thruster gives a satellite of m0_kg, how it was found, and whether it is computed for this mass
    (a maker's Δv for a mass it does not state is not comparable)."""
    itot = P._largest(K.perf(c, "total_impulse_Ns"))
    if itot:
        return itot / m0_kg, f"I_total {itot:g} N·s / {m0_kg:.2f} kg (propellant mass neglected)", True
    isp = P._largest(K.perf(c, "isp_s"))
    m = re.search(r"propellant mass\s*(\d+(?:\.\d+)?)\s*(g|kg)", str(K.perf(c, "propellant") or ""), re.IGNORECASE)
    if isp and m:
        mp = float(m.group(1)) / (1000.0 if m.group(2).lower() == "g" else 1.0)
        how = f"Isp {isp:g} s, propellant {mp:g} kg (rocket equation)"
        return isp * R.G0 * math.log(m0_kg / (m0_kg - mp)), how, True
    f = K.perf_field(c, "delta_v")
    if f.get("value") is not None:
        k = 1000.0 if str(f.get("unit") or "").lower().startswith("km") else 1.0
        return float(f["value"]) * k, "the maker's stated Δv (for a spacecraft mass it does not state)", False
    return None, "no total impulse, propellant mass or Δv published", False


def lifetime_calcs(ctx: dict) -> dict:
    """ctx: alt_km, mass_kg, size areas (mean, min, max m²), mission_years."""
    out = {}
    alt, m, yrs = ctx["alt_km"], ctx["mass_kg"], ctx["mission_years"]
    life = O.lifetime_years(alt, m, ctx["area_mean"])
    lo = O.lifetime_years(alt, m, ctx["area_max"])
    hi = O.lifetime_years(alt, m, ctx["area_min"])
    out["orbit.lifetime"] = calc(
        "orbit.lifetime", "Natural orbit lifetime", life, "years",
        "da/dt = −ρ(h)·(C_D·A/m)·√(μ·a), integrated down to 180 km",
        {"h": inp(alt, "km", "orbit"), "m": inp(m, "kg", "mass budget"),
         "A": inp(ctx["area_mean"], "m²", "mean cross-section (surface / 4)"), "C_D": inp(O.C_D, None, "ASSUMED")},
        ["static exponential atmosphere: solar activity can change the lifetime several-fold (not modelled)",
         f"tumbling (mean area); {lo:.1f} to {hi:.1f} years between the largest and the smallest face"],
        refs=["vallado_atm", "wgs84"],
        extra={"range_years": [lo, hi], "mission_years": yrs, "ok": life >= yrs},
        explain=(f"The orbit lasts about {life:.1f} years without propulsion, longer than the {yrs:g}-year mission."
                 if life >= yrs else f"The orbit decays in about {life:.1f} years, before the {yrs:g}-year mission "
                                     "ends: raise the orbit or add propulsion to hold it."))
    limit = yrs + R.FCC_DISPOSAL_YEARS
    out["orbit.disposal"] = calc(
        "orbit.disposal", "Disposal after the mission", life - yrs, "years",
        "decay time after the mission = lifetime − mission (must be ≤ 5 years)",
        {"lifetime": inp(life, "years", "orbit.lifetime"), "mission": inp(yrs, "years", "your requirement"),
         "rule": inp(R.FCC_DISPOSAL_YEARS, "years", "FCC five-year rule")}, refs=["fcc_5yr"],
        extra={"ok": life <= limit, "limit_years": limit},
        explain=("The satellite re-enters within five years of the mission's end, as the FCC rule requires." if
                 life <= limit else "The satellite would stay up more than five years after the mission: it "
                                    "needs a de-orbit thruster or drag device, or a lower orbit."))
    return out


def propulsion_calcs(ctx: dict) -> dict:
    """ctx: alt_km, mass_kg, area_mean, mission_years, life_years, sel."""
    out = {}
    alt, m, yrs = ctx["alt_km"], ctx["mass_kg"], ctx["mission_years"]
    a_d = drag_accel(alt, m, ctx["area_mean"])
    dv_hold = a_d * yrs * YEAR_S
    out["propulsion.dv_drag"] = calc(
        "propulsion.dv_drag", "Δv to hold the altitude for the mission", dv_hold, "m/s",
        "Δv = ½ρv²·C_D·A/m · t", {"ρ": inp(O.density(alt), "kg/m³", "Vallado exponential atmosphere"),
                                  "t": inp(yrs, "years", "your requirement")},
        ["mean atmosphere; solar maximum needs several times more (not modelled)"], refs=["vallado_atm"])
    h5 = altitude_for_lifetime(R.FCC_DISPOSAL_YEARS, m, ctx["area_mean"])
    dv_down = hohmann_dv(alt, h5) if h5 < alt else 0.0
    out["propulsion.dv_deorbit"] = calc(
        "propulsion.dv_deorbit", "Δv to lower the orbit to a five-year decay", dv_down, "m/s",
        "Hohmann transfer to the altitude that decays in 5 years",
        {"h_5yr": inp(h5, "km", "lifetime model"), "h": inp(alt, "km", "orbit")},
        ["a single perigee-lowering burn needs less (conservative)"], refs=["fcc_5yr", "vallado_atm"],
        extra={"h5_km": h5})
    sel = ctx["sel"].get("propulsion") or []
    if sel:
        c = sel[0][0]
        dv, how, _ = thruster_dv(c, m)
        need = max(dv_hold if ctx.get("hold") else 0.0, dv_down if ctx.get("deorbit") else 0.0)
        out["propulsion.dv"] = calc(
            "propulsion.dv", f"Δv of the {c['product']}", dv, "m/s", "Δv = I_total / m (or the rocket equation)",
            {"thruster": inp(dv, "m/s", how)}, extra={"need": need, "ok": None if dv is None else dv >= need},
            missing=None if dv is not None else how)
    elif ctx.get("hold") or ctx.get("deorbit"):
        out["propulsion.dv"] = missing("propulsion.dv", "Δv of the selected thruster", "m/s", "select a thruster")
    return out
