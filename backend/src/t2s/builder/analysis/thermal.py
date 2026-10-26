"""Thermal analysis (conceptual): one-node, orbit-average temperatures.

The satellite is one isothermal node that exchanges heat by radiation only. It absorbs sunlight, Earth albedo and
Earth infrared on its mean projected area (a convex body's surface area / 4, the average over all orientations) and
dissipates its electrical power inside; it radiates from its whole surface:

    ε σ A T⁴ = (A/4)·[α S (1 − f_e) + α S a F cos β / π + ε E F] + Q_int,    F = (R_E / r)²

with f_e the eclipse fraction, β the Sun's beta angle (cos β / π: the orbit average of the lit Earth below), a the
albedo and E the Earth's infrared flux. Three cases: nominal (ECSS mean albedo and infrared, average power), hot
(ECSS largest albedo and infrared, the shortest eclipse, average power) and cold (ECSS smallest, the longest eclipse,
the base load only). ECSS gives the extremes for short times, so applying them to a whole orbit bounds the result
from both sides; heat capacity smooths the swing inside an orbit, which a one-node orbit average cannot show.
"""
from __future__ import annotations

import math

import numpy as np

from . import refs as R
from .calc import calc, inp

ALPHA = 0.90                 # solar absorptance of the outer surfaces (ASSUMED: mostly solar cells)
EPSILON = 0.85               # infrared emittance (ASSUMED: solar cells with cover glass)
K0 = 273.15


def node_temp_c(area_m2: float, alt_km: float, beta: float, f_ecl: float, albedo: float, ir: float, q_int: float,
                alpha: float = ALPHA, eps: float = EPSILON) -> float:
    F = (R.RE / (R.RE + 1e3 * alt_km)) ** 2
    q = area_m2 / 4.0 * (alpha * R.S0 * (1.0 - f_ecl) + alpha * R.S0 * albedo * F * math.cos(beta) / math.pi
                         + eps * ir * F) + q_int
    return (q / (eps * R.SIGMA * area_m2)) ** 0.25 - K0


def thermal_calcs(ctx: dict) -> dict:
    """ctx: alt_km, area_m2 (outer surface), betas (rad), ecl (eclipse fractions, same order), load_avg_w, base_w,
    ranges [(name, lo, hi)] of the selected components."""
    out = {}
    A, alt = ctx["area_m2"], ctx["alt_km"]
    betas, ecl = np.asarray(ctx["betas"]), np.asarray(ctx["ecl"])
    i_hot, i_cold = int(ecl.argmin()), int(ecl.argmax())
    common = {"A": inp(A, "m²", "outer surface of the envelope"), "α": inp(ALPHA, None, "ASSUMED"),
              "ε": inp(EPSILON, None, "ASSUMED")}
    nominal = node_temp_c(A, alt, float(np.median(betas)), float(np.median(ecl)), R.ALBEDO, R.EARTH_IR,
                          ctx["load_avg_w"])
    hot = node_temp_c(A, alt, float(betas[i_hot]), float(ecl[i_hot]), R.ALBEDO_RANGE[1], R.EARTH_IR_RANGE[1],
                      ctx["load_avg_w"])
    cold = node_temp_c(A, alt, float(betas[i_cold]), float(ecl[i_cold]), R.ALBEDO_RANGE[0], R.EARTH_IR_RANGE[0],
                       ctx["base_w"])
    eq = "ε σ A T⁴ = (A/4)·[α S (1 − f_e) + α S a F cos β/π + ε E F] + Q_int, F = (R_E/r)²"
    assumptions = [f"one isothermal node; surfaces α = {ALPHA}, ε = {EPSILON} (ASSUMED: mostly solar cells)",
                   "mean projected area A/4 (average over orientations); no conduction to deployables"]
    out["thermal.nominal"] = calc(
        "thermal.nominal", "Orbit-average temperature (nominal)", nominal, "°C", eq,
        {**common, "a": inp(R.ALBEDO, None, "ECSS mean albedo"), "E": inp(R.EARTH_IR, "W/m²", "ECSS mean"),
         "Q_int": inp(ctx["load_avg_w"], "W", "average electrical power (all becomes heat)")},
        assumptions, refs=["ecss_albedo", "ecss_ir", "tsi", "si"],
        explain="The average temperature of the whole satellite over an orbit with typical Earth conditions.")
    out["thermal.hot"] = calc(
        "thermal.hot", "Orbit-average temperature (hot bound)", hot, "°C", eq,
        {**common, "a": inp(R.ALBEDO_RANGE[1], None, "ECSS largest albedo"),
         "E": inp(R.EARTH_IR_RANGE[1], "W/m²", "ECSS largest"), "f_e": inp(float(ecl[i_hot]), None,
                                                                            "shortest eclipse of the year"),
         "Q_int": inp(ctx["load_avg_w"], "W", "average electrical power")},
        assumptions + ["ECSS extremes applied to a whole orbit (conservative)"], refs=["ecss_albedo", "ecss_ir", "tsi"])
    out["thermal.cold"] = calc(
        "thermal.cold", "Orbit-average temperature (cold bound)", cold, "°C", eq,
        {**common, "a": inp(R.ALBEDO_RANGE[0], None, "ECSS smallest albedo"),
         "E": inp(R.EARTH_IR_RANGE[0], "W/m²", "ECSS smallest"), "f_e": inp(float(ecl[i_cold]), None,
                                                                             "longest eclipse of the year"),
         "Q_int": inp(ctx["base_w"], "W", "base load (payload and transmitters off)")},
        assumptions + ["ECSS extremes applied to a whole orbit (conservative)"], refs=["ecss_albedo", "ecss_ir", "tsi"])
    ranges = [r for r in ctx.get("ranges", []) if r[1] is not None and r[2] is not None]
    if ranges:
        lo = max(ranges, key=lambda r: r[1])
        hi = min(ranges, key=lambda r: r[2])
        out["thermal.window"] = calc(
            "thermal.window", "Tightest operating range of the selected parts", hi[2] - lo[1], "°C",
            "max of the minimums to min of the maximums",
            {"lowest allowed": inp(lo[1], "°C", lo[0]), "highest allowed": inp(hi[2], "°C", hi[0])},
            extra={"lo_c": lo[1], "hi_c": hi[2], "lo_by": lo[0], "hi_by": hi[0],
                   "nominal_ok": lo[1] <= nominal <= hi[2], "bounds_ok": lo[1] <= cold and hot <= hi[2]},
            explain=("The nominal temperature is inside every part's range." if lo[1] <= nominal <= hi[2] else
                     "The nominal temperature is outside some part's range: the thermal design must change "
                     "(coatings, radiators or heaters)."))
    return out
