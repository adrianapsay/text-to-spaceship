"""Attitude determination and control (conceptual): worst-case disturbance torques (gravity gradient, solar
pressure, aerodynamic drag, residual magnetic dipole), the momentum the wheels must store per orbit and for the
imaging slews, and how the selected hardware compares.

The satellite is a uniform box of its mass and size (moments of inertia m(b² + c²)/12). Centre-of-pressure offsets
are bounded by the CubeSat Design Specification's centre-of-gravity ranges; the residual dipole, surface
reflectivity and slew time are ASSUMED (each named in the Calc).
"""
from __future__ import annotations

import math

from .. import catalog as K
from ..catalog import parse as P
from . import orbit as O
from . import refs as R
from .calc import calc, inp, missing

RESIDUAL_DIPOLE = 0.01        # A·m² (ASSUMED: measured only on the real satellite)
REFLECTIVITY = 0.6            # surface reflectance factor q (ASSUMED)
SLEW_S = 60.0                 # time for one imaging slew (ASSUMED, as imaging.TARGET_OVERHEAD_S)
STEADY_OFF_DEG = 1.0          # gravity-gradient angle when only holding nadir (ASSUMED)


def inertia(mass_kg: float, dims_m: tuple) -> tuple:
    a, b, c = dims_m
    return (mass_kg * (b * b + c * c) / 12.0, mass_kg * (a * a + c * c) / 12.0, mass_kg * (a * a + b * b) / 12.0)


def adcs_calcs(ctx: dict) -> dict:
    """ctx: alt_km, mass_kg, size_u, dims_m (outer), deploy_area_m2, off_nadir_deg, sel, calcs (imaging)."""
    out = {}
    alt, m = ctx["alt_km"], ctx["mass_kg"]
    dims = ctx["dims_m"]
    Ix, Iy, Iz = inertia(m, dims)
    Imax, Imin = max(Ix, Iy, Iz), min(Ix, Iy, Iz)
    rad = O.semi_major(alt)
    theta = math.radians(max(ctx.get("off_nadir_deg") or 0.0, STEADY_OFF_DEG))
    t_gg = 1.5 * R.MU / rad ** 3 * (Imax - Imin) * abs(math.sin(2 * theta))
    faces = sorted([dims[0] * dims[1], dims[1] * dims[2], dims[0] * dims[2]])
    area = faces[-1] + (ctx.get("deploy_area_m2") or 0.0)
    cg = R.CDS_CG_CM.get(ctx.get("size_u") or 3, (2, 2, 7))
    offset = max(cg[0], cg[1]) / 100.0                         # m: lateral CG range bounds the offset
    t_sp = R.S0 / R.C_LIGHT * area * (1.0 + REFLECTIVITY) * offset
    v = math.sqrt(R.MU / rad)
    rho = O.density(alt)
    t_aero = 0.5 * rho * O.C_D * area * v * v * offset
    b_field = 2.0 * R.EARTH_DIPOLE / rad ** 3
    t_mag = RESIDUAL_DIPOLE * b_field
    total = t_gg + t_sp + t_aero + t_mag
    out["adcs.disturbance"] = calc(
        "adcs.disturbance", "Worst-case disturbance torque", total * 1e6, "µN·m",
        "T = T_gg + T_sp + T_aero + T_mag (all aligned: worst case)",
        {"gravity gradient": inp(t_gg * 1e6, "µN·m", f"3μ/(2R³)·|I_max−I_min|·sin 2θ, θ = {math.degrees(theta):g}°"),
         "solar pressure": inp(t_sp * 1e6, "µN·m", f"(S/c)·A·(1+q)·Δ, A = {area:.3f} m², q = {REFLECTIVITY}"),
         "aerodynamic": inp(t_aero * 1e6, "µN·m", f"½ρC_D·A·v²·Δ, ρ = {rho:.3g} kg/m³"),
         "magnetic": inp(t_mag * 1e6, "µN·m", f"D·B, D = {RESIDUAL_DIPOLE} A·m² (ASSUMED), B = 2M/R³"),
         "Δ (cp − cg)": inp(offset * 100, "cm", "CDS centre-of-gravity range (bound)")},
        [f"residual dipole {RESIDUAL_DIPOLE} A·m² (ASSUMED)", f"reflectivity factor {REFLECTIVITY} (ASSUMED)",
         "the satellite as a uniform box; the CDS CG ranges bound the centre-of-pressure offset"],
        refs=["wgs84", "tsi", "vallado_atm", "igrf14", "cds_cg_secondary"],
        extra={"parts": {"gravity_gradient": t_gg, "solar": t_sp, "aero": t_aero, "magnetic": t_mag}})
    T = O.period_s(alt)
    h_dist = total * T / 4.0
    slew = math.radians(ctx.get("off_nadir_deg") or 0.0)
    h_slew = Imax * 2.0 * slew / SLEW_S if slew > 0 else 0.0
    t_slew = 4.0 * slew * Imax / SLEW_S ** 2 if slew > 0 else 0.0
    out["adcs.momentum_need"] = calc(
        "adcs.momentum_need", "Momentum the wheels must store", (h_dist + h_slew) * 1e3, "mN·m·s",
        "h = T_d · P/4 + I_max · 2θ/t_slew",
        {"disturbance": inp(h_dist * 1e3, "mN·m·s", "a quarter orbit of the worst-case torque"),
         "slew": inp(h_slew * 1e3, "mN·m·s", f"{math.degrees(slew):g}° in {SLEW_S:g} s (peak rate, bang-bang)"),
         "I_max": inp(Imax, "kg·m²", "uniform box")},
        [f"one slew to the largest off-nadir angle in {SLEW_S:g} s (ASSUMED)"],
        extra={"torque_need_mNm": (t_slew + total) * 1e3})
    sel = ctx["sel"]
    unit = (sel.get("adcs") or [None])[0]
    wheels = sel.get("wheels") or []
    if unit is not None:
        c = unit[0]
        h_have = P._largest(K.perf(c, "momentum_mNms"))
        tq = P._largest(K.perf(c, "torque_mNm"))
        src = f"{c['manufacturer']} {c['product']}"
    elif wheels:
        c = wheels[0][0]
        h_have = P._largest(K.perf(c, "momentum_mNms"))
        tq = P._largest(K.perf(c, "torque_mNm"))
        src = f"{c['manufacturer']} {c['product']} (per wheel, one per axis)"
    else:
        out["adcs.momentum"] = missing("adcs.momentum", "Wheel momentum selected", "mN·m·s",
                                       "select an ADCS unit or reaction wheels")
        h_have = None
    if unit is not None or wheels:
        need = (h_dist + h_slew) * 1e3
        out["adcs.momentum"] = calc(
            "adcs.momentum", "Wheel momentum selected", h_have, "mN·m·s", "from the catalog",
            {"selected": inp(h_have, "mN·m·s", src)},
            extra={"need": need, "ok": None if h_have is None else h_have >= need,
                   "torque_mNm": tq, "torque_ok": None if tq is None else tq >= (t_slew + total) * 1e3},
            missing=None if h_have is not None else f"{src} does not publish its momentum")
    req_pt = (ctx.get("calcs", {}).get("imaging.pointing_req") or {}).get("value")
    if unit is not None and req_pt is not None:
        acc = P.angle_deg(unit[0], "pointing_accuracy")
        out["adcs.pointing"] = calc(
            "adcs.pointing", "Pointing accuracy of the selected ADCS", acc, "deg", "from the catalog (worst axis)",
            {"selected": inp(acc, "deg", f"{unit[0]['manufacturer']} {unit[0]['product']}")},
            extra={"need": req_pt, "ok": None if acc is None else acc <= req_pt},
            missing=None if acc is not None else "the unit does not publish its pointing accuracy")
    req_kn = (ctx.get("calcs", {}).get("imaging.knowledge_req") or {}).get("value")
    tracker = (sel.get("star_tracker") or [None])[0]
    if req_kn is not None and (unit is not None or tracker is not None):
        if unit is not None:
            c = unit[0]
            kn = P.angle_deg(c, "pointing_knowledge")
            how = "the unit's stated knowledge"
        else:
            c = tracker[0]
            vals = [P.angle_deg(c, k) for k in ("accuracy_cross_boresight_arcsec", "accuracy_roll_arcsec")]
            vals = [v for v in vals if v is not None]
            kn = max(vals) if vals else None
            how = "the star tracker's worst axis"
        kn_as = None if kn is None else kn * 3600.0
        out["adcs.knowledge"] = calc(
            "adcs.knowledge", "Attitude knowledge of the selected hardware", kn_as, "arcsec", "from the catalog",
            {"selected": inp(kn_as, "arcsec", f"{c['manufacturer']} {c['product']} ({how})")},
            extra={"need": req_kn, "ok": None if kn_as is None else kn_as <= req_kn},
            missing=None if kn_as is not None else f"{c['product']} does not publish its attitude knowledge")
    mtq = sel.get("magnetorquer") or []
    if mtq:
        dip = P._largest(K.perf(mtq[0][0], "dipole_Am2"))
        b_min = R.EARTH_DIPOLE / rad ** 3
        if dip is not None:
            out["adcs.dumping"] = calc(
                "adcs.dumping", "Magnetorquer torque at the equator", dip * b_min * 1e6, "µN·m", "T = m·B_min",
                {"m": inp(dip, "A·m²", mtq[0][0]["product"]), "B_min": inp(b_min * 1e9, "nT", "M/R³ (equator)")},
                refs=["igrf14"], extra={"ok": dip * b_min >= total})
    return out
