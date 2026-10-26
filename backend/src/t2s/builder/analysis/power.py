"""Electrical power analysis (conceptual): loads from the selected components with their duty cycles, the energy the
solar panels must deliver per orbit (with path efficiencies), what the selected panels deliver over the orbit and the
year (face-by-face geometry in the orbit frame), and the battery the eclipse needs.

Geometry: the satellite points its camera (−radial) at the Earth (nadir pointing, LVLH attitude). A panel's output is
its rated power × max(0, n·s) in sunlight, with s the Sun direction in the orbit frame for beta angle β and orbit angle
θ: s·r̂ = cos β cos θ, s·v̂ = −cos β sin θ, s·n̂ = sin β. Body panels sit on the four long faces (±v̂, ±n̂);
deployable panels face the zenith (+r̂) (ASSUMED). Panel ratings are taken as their output at normal incidence in
sunlight at the beginning of life (degradation not modelled).
"""
from __future__ import annotations

import numpy as np

from .. import catalog as K
from . import orbit as O
from . import refs as R
from .calc import calc, inp, missing

FACES_BODY = ("+v", "-v", "+n", "-n")


def face_factors(betas, eclipse_fracs, samples: int = 720) -> dict[str, np.ndarray]:
    """Orbit average of max(0, n·s) for each face, zero in eclipse (the shadow arc 2π·f centred on θ = π), for each
    (β, f) pair."""
    th = np.linspace(0.0, 2.0 * np.pi, samples, endpoint=False)[None, :]
    b = np.atleast_1d(np.asarray(betas, float))[:, None]
    f = np.atleast_1d(np.asarray(eclipse_fracs, float))[:, None]
    cb, sb = np.cos(b), np.sin(b)
    lit = np.abs(th - np.pi) >= np.pi * f
    comps = {"+r": cb * np.cos(th), "-r": -cb * np.cos(th), "+v": -cb * np.sin(th), "-v": cb * np.sin(th),
             "+n": np.broadcast_to(sb, lit.shape), "-n": np.broadcast_to(-sb, lit.shape)}
    return {k: np.mean(np.maximum(v, 0.0) * lit, axis=1) for k, v in comps.items()}


def face_factor(face: str, beta: float, eclipse_frac: float, samples: int = 720) -> float:
    """Orbit average of max(0, n·s) for one face at one β (see face_factors)."""
    return float(face_factors([beta], [eclipse_frac], samples)[face][0])


def loads(ctx: dict) -> dict:
    """{"items": [{name, w_on, duty, w_avg, eclipse_w, source}], "missing": [...]} for the selected components."""
    sel = ctx["sel"]
    items, miss = [], []
    t_day = 1440.0

    def add(name, w_on, duty, eclipse, note):
        items.append({"name": name, "w_on": w_on, "duty": duty, "w_avg": w_on * duty, "eclipse_w": eclipse,
                      "note": note})

    img_min = (ctx.get("calcs", {}).get("imaging.time_per_day") or {}).get("value") or 0.0
    down_min = ctx.get("downlink_min_per_day") or 0.0
    pass_min = (ctx.get("passes") or {}).get("minutes_per_day") or 0.0
    for slot, entries in sel.items():
        for c, qty in entries:
            if c.get("_placeholder"):
                w = c["power_w"]["typical"] or 0.0
                duty = (c.get("_duty_pct") or 50.0) / 100.0
                add(f"{c['product']} ×{qty}", w * qty, duty, w * qty * duty, "your payload (placeholder)")
                continue
            cat = c["category"]
            typ, peak, stby = K.power_w(c, "typical"), K.power_w(c, "peak"), K.power_w(c, "standby")
            name = f"{c['manufacturer']} {c['product']}" + (f" ×{qty}" if qty > 1 else "")
            if cat in ("battery", "solar_panel", "structure", "antenna", "eps"):
                continue                                         # no load of its own in this model (eps: noted)
            if cat == "propulsion":
                continue                                         # off in normal operations (ASSUMED)
            if cat == "camera":
                on = typ if typ is not None else peak
                if on is None:
                    miss.append(name)
                    continue
                duty = min(img_min / t_day, 1.0)
                add(name + " (imaging)", on * qty, duty, 0.0, "imaging time per day / 24 h; off between imaging "
                                                              "sessions (ASSUMED; keep-warm heating not modelled)")
                continue
            if cat == "radio":
                idle = typ if typ is not None else stby
                tx = peak if peak is not None else typ
                if idle is None or tx is None:
                    miss.append(name)
                    continue
                data_radio = slot == "radio_data"
                tx_min = down_min if data_radio else pass_min
                duty = min(tx_min / t_day, 1.0)
                if data_radio:
                    add(name + " (transmitting)", tx * qty, duty, tx * qty * duty, "downlink minutes per day / 24 h; "
                                                                                 "off between passes (ASSUMED)")
                else:
                    add(name + " (receiving)", idle * qty, 1.0, idle * qty, "always listening (ASSUMED)")
                    add(name + " (transmitting)", (tx - idle) * qty, duty, (tx - idle) * qty * duty,
                        "pass minutes per day / 24 h")
                continue
            if typ is None:
                miss.append(name)
                continue
            add(name, typ * qty, 1.0, typ * qty, "always on (ASSUMED)")
    return {"items": items, "missing": miss}


def power_calcs(ctx: dict) -> dict:
    out = {}
    T = O.period_s(ctx["alt_km"])
    betas = ctx["betas"]
    ef = O.eclipse_fraction(ctx["alt_km"], betas)
    f_ecl = float(ef.max())
    L = loads(ctx)
    p_avg = sum(i["w_avg"] for i in L["items"])
    p_ecl = sum(i["eclipse_w"] for i in L["items"])
    p_peak = sum(i["w_on"] for i in L["items"])
    note_missing = ([f"no published power for: {', '.join(L['missing'])} (left out)"] if L["missing"] else [])
    out["power.load_avg"] = calc(
        "power.load_avg", "Average power use", p_avg, "W", "P = Σ P_on · duty",
        {i["name"]: inp(i["w_avg"], "W", f"{i['w_on']:.2f} W × {i['duty']:.3f} ({i['note']})") for i in L["items"]},
        note_missing + ["the EPS's own consumption is not published for most boards (not included)"],
        extra={"items": L["items"], "missing_parts": L["missing"], "peak_w": p_peak, "eclipse_w": p_ecl})
    Te, Td = f_ecl * T, (1.0 - f_ecl) * T
    xe, xd = R.ASSUMED["path_eff_eclipse"][0], R.ASSUMED["path_eff_day"][0]
    e_need = (p_ecl * Te / xe + p_avg * Td / xd) / 3600.0
    out["power.energy_need"] = calc(
        "power.energy_need", "Energy the panels must deliver per orbit", e_need, "Wh",
        "E = (P_e·T_e / X_e + P_d·T_d / X_d)", {"P_e": inp(p_ecl, "W", "eclipse load"), "P_d": inp(p_avg, "W",
                                                                                                    "average load"),
                                               "T_e": inp(Te / 60, "min", "longest eclipse of the year"),
                                               "T_d": inp(Td / 60, "min", "orbit − eclipse"),
                                               "X_e": inp(xe, None, "ASSUMED"), "X_d": inp(xd, None, "ASSUMED")},
        [R.ASSUMED["path_eff_eclipse"][1], R.ASSUMED["path_eff_day"][1]],
        extra={"T_e_min": Te / 60, "T_d_min": Td / 60})
    panels = ctx["sel"].get("solar") or []
    if not panels:
        out["power.generation"] = missing("power.generation", "Solar energy per orbit", "Wh", "select solar panels")
    else:
        rated_total = 0.0
        details = []
        for c, qty in panels:
            p = K.perf(c, "power_w")
            dep = str(K.perf(c, "deployable") or "").lower().startswith("y")
            if p is None:
                details.append(f"{c['product']}: no published power (left out)")
                continue
            rated_total += float(p) * qty
            details.append(f"{c['product']} ×{qty}: {float(p):g} W each, {'deployable (zenith-facing)' if dep else 'body'}")
        ff = ctx.get("face_factors") or face_factors(betas, ef)
        e_gen = np.zeros(len(np.atleast_1d(betas)))
        nb = 0
        for c, qty in panels:
            p = K.perf(c, "power_w")
            if p is None:
                continue
            dep = str(K.perf(c, "deployable") or "").lower().startswith("y")
            for _ in range(int(qty)):
                if dep:
                    e_gen += float(p) * ff["+r"]
                else:
                    e_gen += float(p) * ff[FACES_BODY[nb % 4]]
                    nb += 1
        e_gen = e_gen * T / 3600.0
        worst = float(e_gen.min())
        out["power.generation"] = calc(
            "power.generation", "Solar energy per orbit (worst day of the year)", worst, "Wh",
            "E = Σ P_rated · ⟨max(0, n·s)⟩ · T, over the year's beta angles",
            {"panels": inp(rated_total, "W", "; ".join(details)), "T": inp(T / 60, "min", "orbit")},
            ["nadir-pointing attitude; body panels on the four long faces, deployables facing the zenith (ASSUMED)",
             "panel ratings at normal incidence, beginning of life; no degradation (ASSUMED)"],
            refs=["tsi"], extra={"mean_wh": float(e_gen.mean()), "best_wh": float(e_gen.max()),
                                 "panel_w": rated_total})
        margin = worst / e_need - 1.0 if e_need > 0 else None
        target = float(ctx.get("margin_target_pct") or 0.0)
        pct = 100.0 * margin if margin is not None else None
        out["power.margin"] = calc(
            "power.margin", "Energy margin (worst day)", pct, "%",
            "margin = E_generated / E_needed − 1", {"E_generated": inp(worst, "Wh", "power.generation"),
                                                   "E_needed": inp(e_need, "Wh", "power.energy_need"),
                                                   "target": inp(target, "%", "design margin (ASSUMED)")},
            [f"design margin target {target:g} % (ASSUMED, as for mass)"],
            extra={"ok": pct is not None and pct >= target, "positive": pct is not None and pct >= 0.0,
                   "target_pct": target},
            explain=("The panels cover the loads with the design margin." if pct is not None and pct >= target else
                     "The panels cover the loads, but with less than the design margin." if pct is not None and
                     pct >= 0 else
                     "The panels do not cover the loads: add panels, use deployables or reduce the duty cycles."))
    dod = R.ASSUMED["battery_dod"][0]
    c_req = p_ecl * Te / 3600.0 / dod
    out["power.battery_need"] = calc(
        "power.battery_need", "Battery capacity needed", c_req, "Wh", "C = P_e · T_e / DoD",
        {"P_e": inp(p_ecl, "W", "eclipse load"), "T_e": inp(Te / 60, "min", "longest eclipse"),
         "DoD": inp(dod, None, "ASSUMED")}, [R.ASSUMED["battery_dod"][1]], refs=["nasa_grc_liion"])
    bats = ctx["sel"].get("battery") or []
    if bats:
        cap = sum((K.perf(c, "capacity_wh") or 0.0) * q for c, q in bats)
        out["power.battery"] = calc(
            "power.battery", "Battery capacity selected", cap, "Wh", "Σ capacity",
            {c["product"]: inp(K.perf(c, "capacity_wh"), "Wh", c["manufacturer"]) for c, _ in bats},
            extra={"ok": cap >= c_req, "dod_actual": (p_ecl * Te / 3600.0 / cap) if cap else None})
    return out
