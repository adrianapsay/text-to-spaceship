"""The CubeSat Builder's analysis engine: from a design's requirements and selections to an orbit, an architecture
(one pick per slot), every calculation, the budgets and the compatibility checks.

Each step uses only what the steps before it fixed:
1. Orbit: the user's choice, or the recommendation — sun-synchronous, at the lowest altitude (400–660 km in 10 km
   steps) whose natural lifetime is at least 1.5 × the mission for this satellite's mass and mean area. The orbit and
   the mass depend on each other, so steps 1–3 repeat until the altitude settles (at most three passes).
2. For each CubeSat size up to the launch limit: the structure and the payload; the attitude hardware for the pointing
   the payload needs; the computer and GNSS; a UHF radio for commands, and a data radio when UHF cannot return the
   daily data (S-band first, X-band when S-band cannot); propulsion when the lifetime or the disposal rule asks for
   it; the EPS (the one that supplies most of the parts' voltages); the fewest solar panels for a positive margin on
   the worst day; the battery for the longest eclipse.
3. The analyses and budgets of that architecture, and the compatibility checks.
4. The smallest size whose hard checks pass is the recommendation (or the user's size); every size is kept for the
   trade study.

The user's own selections replace the architect's pick for their slot; the architect's pick is still shown.
"""
from __future__ import annotations

import hashlib
import json
import threading

from . import catalog as K
from . import compat as C
from . import questions as Q
from . import recommend as RC
from .analysis import adcs as AD
from .analysis import budgets as B
from .analysis import comms as CM
from .analysis import imaging as IM
from .analysis import orbit as O
from .analysis import power as PW
from .analysis import propulsion as PR
from .analysis import refs as R
from .analysis import structure as S
from .analysis import thermal as TH
from .model import clone, now_iso

ENGINE_VERSION = "3.0-m2"
ALT_SCAN = tuple(range(400, 661, 10))       # km, the recommended-orbit search (ASSUMED bounds)
DATA_MARGIN = 1.2                           # a radio must return 1.2 × the daily data to be enough (ASSUMED)
GEO_DAYS = 7.0                              # days simulated for region access and station passes
FIRST_MASS_SHARE = 0.5                      # first mass guess: half the size's CDS limit (replaced by the budget)
DEFAULT_LTDN_H = 10.5

GROUPS = (
    ("orbit", "Orbit", "orbit."), ("payload", "Payload", "imaging."), ("power", "Power", "power."),
    ("adcs", "Attitude control", "adcs."), ("comms", "Communications", "comms."),
    ("thermal", "Thermal", "thermal."), ("propulsion", "Propulsion and disposal", "propulsion."),
    ("structure", "Structure", "structure."), ("budgets", "Budgets", "budget."),
)


# ============================================================================================ helpers
def req_values(design: dict) -> dict:
    return {k: r["value"] for k, r in (design.get("requirements") or {}).items()}


def mission_years(rv: dict, prefs: dict) -> float:
    if prefs.get("lifetime_years") is not None:
        return float(prefs["lifetime_years"])
    return float(rv.get("mission.lifetime_years") or 2.0)


def resolve_orbit(rv: dict, years: float, mass_kg: float, area_m2: float) -> dict:
    choice = rv.get("orbit.choice") or "recommend"
    ltdn = rv.get("orbit.ltdn_h")
    if choice == "iss":
        return {"choice": choice, "alt_km": R.ISS_ALTITUDE_KM, "inc_deg": R.ISS_INCLINATION_DEG, "ltdn_h": None,
                "sso": False, "flags": [], "src": {"alt": "ISS orbit (NASA; altitude ASSUMED in its 370–460 km band)"},
                "why": f"Deployed from the ISS: {R.ISS_INCLINATION_DEG}° inclination and about "
                       f"{R.ISS_ALTITUDE_KM:g} km (NASA)."}
    if choice in ("sso", "custom"):
        alt = float(rv.get("orbit.altitude_km") or 500.0)
        inc = rv.get("orbit.inclination_deg") if choice == "custom" else None
        sso = inc is None
        try:
            inc = O.sso_inclination(alt) if sso else float(inc)
        except ValueError:
            inc, sso = 98.0, False
        lt = (DEFAULT_LTDN_H if ltdn is None else float(ltdn)) if sso else None
        return {"choice": choice, "alt_km": alt, "inc_deg": inc, "ltdn_h": lt, "sso": sso, "flags": [],
                "src": {"alt": "your requirement", "inc": "your requirement"},
                "why": (f"Your orbit: {alt:g} km" + (f", sun-synchronous ({inc:.2f}°), crossing the equator "
                                                     f"southbound at {lt:g} h local time." if sso else
                                                     f", {inc:g}° inclination."))}
    lt = DEFAULT_LTDN_H if ltdn is None else float(ltdn)
    need = PR.LIFETIME_MARGIN * years
    alt = next((h for h in ALT_SCAN if O.lifetime_years(h, mass_kg, area_m2) >= need), None)
    flags = []
    if alt is None:
        alt = ALT_SCAN[-1]
        flags.append(f"even {alt} km decays before {need:g} years: the orbit needs propulsion to last the mission")
    return {"choice": "recommend", "alt_km": float(alt), "inc_deg": O.sso_inclination(alt), "ltdn_h": lt,
            "sso": True, "flags": flags, "src": {"alt": "recommended (lifetime rule)"},
            "why": (f"Sun-synchronous, so every pass sees the same local time (equator southbound at {lt:g} h). "
                    f"{alt} km is the lowest altitude (400–660 km in 10 km steps) whose natural lifetime is at least "
                    f"{PR.LIFETIME_MARGIN:g} × the {years:g}-year mission for this satellite's mass and area: low "
                    "for sharp images and short radio links, high enough to last.")}


_GEO: dict = {}
_GEO_LOCK = threading.Lock()


def geometry(orbit: dict, region: dict | None, station: dict | None, off_nadir: float, daylight: bool) -> dict:
    """Beta angles and eclipses over the year, face factors, region access and station passes (cached)."""
    rk = None if not region or region.get("lat_min") is None else (
        region["lat_min"], region["lat_max"], region["lon_min"], region["lon_max"])
    sk = None if not station else (station["lat"], station["lon"], station.get("min_elev_deg", 10.0))
    key = (round(orbit["alt_km"], 3), round(orbit["inc_deg"], 6), orbit["ltdn_h"], orbit["sso"], rk, sk,
           round(off_nadir, 3), daylight)
    with _GEO_LOCK:
        hit = _GEO.get(key)
    if hit is not None:
        return hit
    alt, inc, lt = orbit["alt_km"], orbit["inc_deg"], orbit["ltdn_h"]
    betas = O.beta_over_year(alt, inc, lt, O.EPOCH_D, sso=orbit["sso"])
    ecl = O.eclipse_fraction(alt, betas)
    g = {"betas": betas, "ecl": ecl, "ff": PW.face_factors(betas, ecl),
         "access": O.region_access(alt, inc, lt, region, off_nadir, O.EPOCH_D, GEO_DAYS, daylight=daylight)
         if rk else None,
         "passes": O.station_passes(alt, inc, lt, station, O.EPOCH_D, GEO_DAYS) if sk else None}
    with _GEO_LOCK:
        if len(_GEO) > 64:
            _GEO.clear()
        _GEO[key] = g
    return g


def user_pick(design: dict, slot: str) -> dict | None:
    s = (design.get("selections") or {}).get(slot)
    if not s:
        return None
    label = RC.SLOT[slot].label
    cid = s.get("component")
    if cid is None:
        return {"slot": slot, "label": label, "items": [], "status": "none", "why": "Removed by you.", "need": "",
                "alternatives": [], "flags": []}
    c = K.by_id(cid)
    if c is None:
        return {"slot": slot, "label": label, "items": [], "status": "missing", "need": "", "alternatives": [],
                "why": f"{cid} is not in the catalog any more.", "flags": [f"{cid} not found"]}
    return {"slot": slot, "label": label, "items": [(c, max(1, int(s.get("qty") or 1)))], "status": "user",
            "why": "Chosen by you.", "need": "", "alternatives": [], "flags": []}


def _sel(picks: dict) -> dict:
    return {slot: list(p["items"]) for slot, p in picks.items() if p["items"]}


def _deploy_area(sel: dict) -> tuple[float, list[str]]:
    area, unknown = 0.0, []
    for c, q in sel.get("solar", []):
        if str(K.perf(c, "deployable") or "").lower().startswith("y"):
            d = K.dims_mm(c)
            if d is None:
                unknown.append(c["product"])
            else:
                s = sorted(d)
                area += s[1] * s[2] / 1e6 * q
    return area, unknown


# ============================================================================================ one size
def build(design: dict, size, rv: dict, prefs: dict, years: float) -> dict:
    """The architecture and analyses of the design at one CubeSat size.

    The orbit follows the mass (the lifetime rule) and the payload follows the orbit (the pixel size scales with the
    altitude), so the passes repeat until neither changes. When they flip between payloads instead (a light camera
    meets the pixel size only low, where its light satellite decays too soon; a heavy one allows the low orbit…),
    each of those payloads is held fixed in turn and the consistent design that passes the most checks is kept."""
    st, seen = _iterate(design, size, rv, prefs, years, None)
    if st["settled"] or len(seen) < 2 or user_pick(design, "payload") is not None:
        return st
    options = []
    for k, cid in enumerate(seen[:5]):
        o, _ = _iterate(design, size, rv, prefs, years, cid)
        options.append((len(failures(o, rv)), not o["settled"], k, o))
    best = min(options, key=lambda x: x[:3])[3]
    others = [K.by_id(c) for c in seen[:5] if c != best["picks"]["payload"]["items"][0][0]["id"]]
    best["picks"]["payload"]["flags"].append(
        "the orbit and the payload depend on each other here: the architect compared "
        + ", ".join(f"{c['manufacturer']} {c['product']}" for c in others if c) + " and kept this consistent design")
    return best


def _iterate(design, size, rv, prefs, years, lock: str | None) -> tuple[dict, list[str]]:
    """Fixed-point passes (orbit ← mass, parts ← orbit); returns the last state and the payloads worth comparing:
    those the passes chose, then the next two each pass ranked (they met the same hard rules)."""
    places = {s.id: s.place for s in RC.SLOTS}
    mass = FIRST_MASS_SHARE * R.CDS_MASS_KG[size]
    orbit = resolve_orbit(rv, years, mass, S.mean_cross_section_m2(size))
    state, seen, runners = None, [], []
    for _ in range(4):
        state = _pass(design, size, rv, prefs, years, orbit, mass, places, lock)
        for c, _q in state["picks"]["payload"]["items"]:
            if c.get("category") == "camera" and c["id"] not in seen:
                seen.append(c["id"])
        ranked = [a["id"] for a in state["picks"]["payload"]["alternatives"] if a["reason"] == "ranked lower"]
        runners += [cid for cid in ranked[:2] if cid not in runners]
        mass_new = state["calcs"]["budget.mass"]["value"]
        orbit_new = resolve_orbit(rv, years, mass_new, S.mean_cross_section_m2(size, state["deploy_area"]))
        state["settled"] = (abs(orbit_new["alt_km"] - orbit["alt_km"]) < 1e-6 and
                            abs(mass_new - mass) < 0.05 * max(mass_new, 1e-9))
        if state["settled"]:
            break
        mass, orbit = mass_new, orbit_new
    return state, seen + [cid for cid in runners if cid not in seen]


def _pass(design, size, rv, prefs, years, orbit, mass, places, lock: str | None = None) -> dict:
    alt = orbit["alt_km"]
    mt = rv.get("mission.type")
    eo = mt == "earth_observation"
    region = rv.get("target.region") if isinstance(rv.get("target.region"), dict) else None
    station = rv.get("comms.station") if isinstance(rv.get("comms.station"), dict) else None
    off = float(rv.get("imaging.off_nadir_deg") or (30.0 if eo else 0.0))
    geo = geometry(orbit, region, station, off, daylight=eo and not rv.get("imaging.night"))
    calcs: dict = {}
    calcs.update(O.orbit_calcs(alt, orbit["inc_deg"], orbit["ltdn_h"], orbit["sso"], orbit["src"]))
    calcs["orbit.eclipse"] = O.eclipse_calc(alt, geo["betas"])
    if geo["access"] is not None:
        calcs["orbit.access"] = O.access_calc(geo["access"], region, off, rv.get("target.revisit_h"),
                                              eo and not rv.get("imaging.night"))
    passes = geo["passes"] or {}
    if geo["passes"] is not None:
        calcs["orbit.passes"] = O.passes_calc(geo["passes"], station)
    fidelity = rv.get("mission.fidelity") or "conceptual"
    fidelity = fidelity if fidelity in B.MARGIN_PCT else "conceptual"
    ctx = {"size": size, "alt_km": alt, "req": rv, "prefs": prefs, "calcs": calcs, "mass_kg": mass,
           "margin_target_pct": B.MARGIN_PCT[fidelity]}
    picks: dict = {}

    def put(slot, rec):
        u = user_pick(design, slot)
        if u is not None:
            u["recommended"] = _brief(rec)
            picks[slot] = u
        else:
            picks[slot] = rec

    put("structure", RC.pick_structure(ctx))
    rec = RC.pick_payload(ctx)
    if lock is not None and K.by_id(lock) is not None:                # the architect holds this payload (see build)
        held = K.by_id(lock)
        if not (rec["items"] and rec["items"][0][0]["id"] == lock):
            g = IM.camera_at(held, alt).get("gsd_m")
            need = float(rv.get("imaging.gsd_m") or 10.0)
            rec = {**rec, "items": [(held, 1)], "status": "recommended", "flags": list(rec.get("flags", [])),
                   "why": (f"Reaches {g:.2f} m pixels at {alt:.0f} km (you asked for {need:g} m)." if g else
                           f"{held['manufacturer']} {held['product']}.") +
                          " Kept after comparing the payloads the orbit and the mass depend on."}
    put("payload", rec)
    cam = next((c for c, _ in picks["payload"]["items"] if c.get("category") == "camera"), None)
    if eo:
        calcs.update(IM.imaging_calcs({"alt_km": alt, "req": rv, "size_u": size, "camera": cam}))
    dims_m = tuple(d / 1000.0 for d in S.outer(size))
    pre = AD.adcs_calcs({"alt_km": alt, "mass_kg": mass, "size_u": size, "dims_m": dims_m, "deploy_area_m2": 0.0,
                         "off_nadir_deg": off if eo else 0.0, "sel": {}, "calcs": calcs})
    ctx["momentum_need_mNms"] = pre["adcs.momentum_need"]["value"]
    for slot, rec in RC.pick_adcs(ctx).items():
        put(slot, rec)
    put("gnss", RC.pick_gnss(ctx))
    put("radio_ttc", RC.pick_radio_ttc(ctx))
    put("antenna_ttc", RC.pick_antenna(ctx, "antenna_ttc", "uhf"))
    lctx = {"sel": _sel(picks), "passes": passes}
    ttc = CM.link_calcs(lctx, "radio_ttc", "antenna_ttc", "UHF downlink (commands and telemetry radio)")
    calcs.update(ttc)
    need_mbit = _data_need(rv, calcs)
    uhf_ret = ttc["comms.radio_ttc"].get("value") or 0.0
    band_ans = rv.get("comms.band") or "recommend"
    data_band = None
    if band_ans in ("s", "x"):
        data_band = band_ans
    elif band_ans == "recommend" and need_mbit is not None and uhf_ret < DATA_MARGIN * need_mbit:
        data_band = "s"
        for band in ("s", "x"):
            trial = dict(picks)
            trial["radio_data"] = RC.pick_radio_data(ctx, band)
            trial["antenna_data"] = RC.pick_antenna(ctx, "antenna_data", band)
            got = CM.link_calcs({"sel": _sel(trial), "passes": passes}, "radio_data", "antenna_data", "")
            v = got["comms.radio_data"].get("value") or 0.0
            data_band = band
            if uhf_ret + v >= DATA_MARGIN * need_mbit:
                break
    if data_band is None:
        why = ("UHF is enough for the daily data." if need_mbit is not None else
               "No payload data to download beyond telemetry.") if band_ans != "uhf" else "You chose UHF only."
        put("radio_data", RC.none_needed("radio_data", why))
        put("antenna_data", RC.none_needed("antenna_data", why))
    else:
        put("radio_data", RC.pick_radio_data(ctx, data_band))
        put("antenna_data", RC.pick_antenna(ctx, "antenna_data", data_band))
        if picks["adcs"]["status"] == "none" and not picks.get("wheels", {}).get("items"):
            ctx["needs_patch"] = True
            for slot, rec in RC.pick_adcs(ctx).items():
                put(slot, rec)
    if picks["radio_data"]["items"]:
        calcs.update(CM.link_calcs({"sel": _sel(picks), "passes": passes}, "radio_data", "antenna_data",
                                   f"{data_band.upper() if data_band else 'Data'} downlink (payload data)"))
    ctx["parts"] = [c for items in _sel(picks).values() for c, _ in items if not c.get("_placeholder")]
    put("obc", RC.pick_obc(ctx))
    # propulsion: from the lifetime and the disposal rule
    area_mean = S.mean_cross_section_m2(size)
    life = O.lifetime_years(alt, mass, area_mean)
    ans = rv.get("propulsion.need") or "recommend"
    hold = ans == "drag" or (ans == "recommend" and life < years)
    deorbit = ans == "deorbit" or (ans == "recommend" and life > years + R.FCC_DISPOSAL_YEARS)
    need_dv = None
    if hold or deorbit or ans == "maneuver":
        dvs = PR.propulsion_calcs({"alt_km": alt, "mass_kg": mass, "area_mean": area_mean, "mission_years": years,
                                   "sel": {}})
        need_dv = max(dvs["propulsion.dv_drag"]["value"] if hold else 0.0,
                      dvs["propulsion.dv_deorbit"]["value"] if deorbit else 0.0) or None
    why_p = ("You asked for a thruster." if ans in ("drag", "deorbit", "maneuver") else
             "The orbit decays before the mission ends: a thruster holds the altitude." if hold else
             "The orbit would outlast the five-year disposal rule: a thruster brings it down." if deorbit else
             "Not needed: the orbit lasts the mission and decays within five years after it." if ans == "recommend"
             else "You chose no thruster.")
    if ans in ("drag", "deorbit", "maneuver") and not need_dv:
        need_dv = 1.0
        why_p = ("You asked for a thruster to change orbit (the Δv is not specified: the best ranked is shown)."
                 if ans == "maneuver" else "You asked for a thruster; the analysis finds this orbit needs almost no "
                                           "Δv for that, so the best ranked one is shown.")
    put("propulsion", RC.pick_propulsion(ctx, need_dv, why_p))
    # EPS: the one that supplies most of the parts' voltages
    powered = [c for slot, items in _sel(picks).items() for c, _ in items
               if not c.get("_placeholder") and c["category"] not in ("structure", "antenna", "solar_panel",
                                                                     "battery", "eps")]

    def voltage_match(eps):
        if not powered:
            return 0.5
        score = {"compatible": 1.0, "assumptions": 0.5, "unknown": 0.25, "incompatible": 0.0}
        return sum(score[C.supply_match(c, eps)[0]] for c in powered) / len(powered)
    ctx["voltage_match"] = voltage_match
    put("eps", RC.pick_eps(ctx))
    # downlink time for the data radio's duty cycle
    down_min = passes.get("minutes_per_day", 0.0) * CM.CONTACT_USE if picks["radio_data"]["items"] else 0.0

    def power_with(solar_items):
        trial = _sel(picks)
        if solar_items:
            trial["solar"] = solar_items
        return PW.power_calcs({"alt_km": alt, "betas": geo["betas"], "sel": trial, "calcs": calcs,
                               "downlink_min_per_day": down_min, "passes": passes, "face_factors": geo["ff"],
                               "margin_target_pct": ctx["margin_target_pct"]})

    def margin_of(items):
        return (power_with(items).get("power.margin") or {}).get("value")
    put("solar", RC.pick_solar(ctx, margin_of))
    pw = power_with(picks["solar"]["items"])
    eps_c = (picks["eps"]["items"] or [(None, 0)])[0][0]
    put("battery", RC.pick_battery(ctx, pw["power.battery_need"]["value"], eps_c))
    sel = _sel(picks)
    # final analyses on the whole architecture
    deploy, deploy_unknown = _deploy_area(sel)
    calcs.update(PW.power_calcs({"alt_km": alt, "betas": geo["betas"], "sel": sel, "calcs": calcs,
                                 "downlink_min_per_day": down_min, "passes": passes, "face_factors": geo["ff"],
                                 "margin_target_pct": ctx["margin_target_pct"]}))
    unpowered = calcs["power.load_avg"].get("missing_parts") or []
    if unpowered and picks["solar"]["items"]:
        picks["solar"]["flags"].append(f"sized for the published loads only: {', '.join(unpowered)} does not publish "
                                       "its power, so more panels may be needed")
    calcs["budget.mass"] = B.mass_budget(sel, places, size, fidelity)
    dry = calcs["budget.mass"]["value"]
    vol, vol_missing = B.internal_volume_cm3(sel, places)
    calcs.update(S.structure_calcs({"size_u": size, "mass_kg": dry, "volume_cm3": vol}))
    if vol_missing:
        calcs["structure.volume"]["assumptions"].append(f"size not published (not counted): {', '.join(vol_missing)}")
        calcs["structure.volume"]["missing_parts"] = vol_missing
    calcs.update(AD.adcs_calcs({"alt_km": alt, "mass_kg": dry, "size_u": size, "dims_m": dims_m,
                                "deploy_area_m2": deploy, "off_nadir_deg": off if eo else 0.0, "sel": sel,
                                "calcs": calcs}))
    areas = S.area_m2(size)
    calcs.update(PR.lifetime_calcs({"alt_km": alt, "mass_kg": dry, "mission_years": years,
                                    "area_mean": S.mean_cross_section_m2(size, deploy), "area_min": areas["end"],
                                    "area_max": areas["side"] + deploy}))
    if deploy_unknown:
        calcs["orbit.lifetime"]["assumptions"].append(
            f"deployable area not published (left out of the drag area): {', '.join(deploy_unknown)}")
    calcs.update(PR.propulsion_calcs({"alt_km": alt, "mass_kg": dry, "area_mean": S.mean_cross_section_m2(size, deploy),
                                      "mission_years": years, "sel": sel, "hold": hold, "deorbit": deorbit}))
    load = calcs["power.load_avg"]
    calcs.update(TH.thermal_calcs({
        "alt_km": alt, "area_m2": areas["total"], "betas": geo["betas"], "ecl": geo["ecl"],
        "load_avg_w": load["value"], "base_w": load["eclipse_w"],
        "ranges": [(f"{c['manufacturer']} {c['product']}", *K.temp_range(c)) for c, _ in
                   (x for items in sel.values() for x in items) if not c.get("_placeholder") and K.temp_range(c)]}))
    calcs["budget.cost"] = B.cost_budget(sel)
    returns = {k.replace("comms.", ""): calcs[k].get("value") for k in ("comms.radio_ttc", "comms.radio_data")
               if k in calcs}
    data = B.data_budget(need_mbit, returns)
    if data is not None:
        calcs["budget.data"] = data
    checks = C.check_design({"size": size, "sel": sel, "calcs": calcs, "places": places, "req": rv})
    return {"size": size, "orbit": orbit, "picks": picks, "sel": sel, "calcs": calcs, "checks": checks,
            "deploy_area": deploy, "need_mbit": need_mbit, "geo": geo, "places": places}


def _data_need(rv: dict, calcs: dict) -> float | None:
    """Payload data per day (Mbit), or None when there is none to plan for."""
    v = (calcs.get("imaging.daily_volume") or {}).get("value")
    if v is not None:
        return v * 8000.0
    if rv.get("payload.data_kbps") is not None:
        return float(rv["payload.data_kbps"]) * float(rv.get("payload.duty_pct") or 50.0) / 100.0 * 86.4
    return None


def failures(state: dict, rv: dict) -> list[str]:
    """The hard checks a size fails (unknowns do not fail)."""
    c, out = state["calcs"], []
    p = state["picks"]
    if not p["payload"]["items"]:
        out.append("no payload fits")
    if not p["structure"]["items"]:
        out.append(f"no {S.label(state['size'])} structure in the catalog")
    if not p["solar"]["items"]:
        out.append("no solar panel in the catalog fits this size")
    if rv.get("mission.type") == "earth_observation":
        if (c.get("imaging.camera_gsd") or {}).get("meets") is False:
            out.append("the camera is coarser than the pixel size asked for")
        if (c.get("imaging.bands") or {}).get("ok") is False:
            out.append("the camera does not cover the bands asked for")
        if (c.get("imaging.aperture_fit") or {}).get("feasible") is False and \
                (c.get("imaging.camera_gsd") or {}).get("meets") is not True:
            out.append("the telescope needed does not fit this size")      # moot when a real camera meets the pixel
    if (c.get("power.margin") or {}).get("positive") is False:
        out.append("not enough solar power")
    if (c.get("budget.mass") or {}).get("value", 0.0) > R.CDS_MASS_KG[state["size"]]:
        out.append("over the mass limit")
    if (c.get("structure.volume") or {}).get("ok") is False:
        out.append("the parts fill too much of the volume")
    if (c.get("budget.data") or {}).get("ok") is False:
        out.append("the downlink cannot return the daily data")
    if (c.get("adcs.pointing") or {}).get("ok") is False:
        out.append("the attitude control cannot point accurately enough")
    if (c.get("orbit.lifetime") or {}).get("ok") is False and not p["propulsion"]["items"]:
        out.append("the orbit decays before the mission ends (and no thruster holds it)")
    if any(ch["rule"] == "mechanical" and ch["status"] == "incompatible" for ch in state["checks"]):
        out.append("a part does not fit the structure")
    return out


# ============================================================================================ the design
def _brief(p: dict) -> dict:
    return {"items": [{"id": c["id"], "name": f"{c['manufacturer']} {c['product']}", "qty": q}
                      for c, q in p["items"]], "status": p["status"], "why": p["why"]}


def _item_json(c: dict, q: int) -> dict:
    if c.get("_placeholder"):
        return {"id": c["id"], "name": f"{c['manufacturer']} {c['product']}", "qty": q, "placeholder": True,
                "category": "payload", "mass_kg": K.mass_kg(c), "dims_mm": K.dims_mm(c),
                "power_w": {"typical": K.power_w(c, "typical")}, "fits": c["fits"], "price": K.price(c),
                "cad": "none"}
    return {**K.summary(c), "name": f"{c['manufacturer']} {c['product']}", "qty": q}


def _pick_json(p: dict) -> dict:
    out = {k: v for k, v in p.items() if k != "items"}
    out["items"] = [_item_json(c, q) for c, q in p["items"]]
    out["place"] = RC.SLOT[p["slot"]].place
    return out


def _groups(calcs: dict) -> list[dict]:
    out, seen = [], set()
    for gid, label, prefix in GROUPS:
        ids = [k for k in calcs if k.startswith(prefix)]
        seen.update(ids)
        if ids:
            out.append({"id": gid, "label": label, "calcs": ids})
    rest = [k for k in calcs if k not in seen]
    if rest:
        out.append({"id": "other", "label": "Other", "calcs": rest})
    return out


def inputs_hash(design: dict) -> str:
    blob = json.dumps({"r": req_values(design), "s": design.get("selections") or {}, "p": design.get("prefs") or {},
                       "z": design.get("size_u"), "e": ENGINE_VERSION, "k": len(K.components())},
                      sort_keys=True, default=str)
    return hashlib.sha1(blob.encode()).hexdigest()[:16]


_CACHE: dict = {}
_CACHE_LOCK = threading.Lock()


def analyse(design: dict) -> dict:
    """The full analysis of a design (cached by its inputs). Questions still open take their documented defaults
    (ASSUMED, as "I don't know" would) on a copy of the design, and are listed in `open_questions`."""
    h = inputs_hash(design)
    with _CACHE_LOCK:
        hit = _CACHE.get(h)
    if hit is not None:
        return {**hit, "design_version": design.get("version"), "cached": True}
    work = clone(design)
    still_open = Q.pending(work, expert=True)
    Q.accept_defaults(work, expert=True)
    out = _analyse(work)
    reqs = work.get("requirements", {})
    out["open_questions"] = [{"qid": q.id, "prompt": q.prompt, "advanced": q.advanced,
                              "default": Q.display(q, reqs[q.key]["value"]) if q.key in reqs else "—",
                              "why": q.default_reason(reqs)} for q in still_open]
    out["inputs_hash"] = h
    with _CACHE_LOCK:
        if len(_CACHE) > 32:
            _CACHE.clear()
        _CACHE[h] = out
    return {**out, "design_version": design.get("version"), "cached": False}


def _analyse(design: dict) -> dict:
    rv = req_values(design)
    prefs = RC.prefs_of(design)
    years = mission_years(rv, prefs)
    cap = rv.get("launch.max_size_u")
    sizes = [s for s in S.SIZES if cap is None or s <= float(cap)]
    states = {s: build(design, s, rv, prefs, years) for s in sizes}
    fails = {s: failures(st, rv) for s, st in states.items()}
    chosen = design.get("size_u")
    if chosen not in states:
        ok = [s for s in sizes if not fails[s]]
        chosen = ok[0] if ok else min(sizes, key=lambda s: (len(fails[s]), s))
        size_why = (f"The smallest size that passes every hard check ({S.size_note(chosen)})." if ok else
                    f"No size passes every check; {S.label(chosen)} fails the fewest: {'; '.join(fails[chosen])}.")
    else:
        size_why = f"Your choice: {S.size_note(chosen)}."
    st = states[chosen]
    trade = []
    for s in sizes:
        x = states[s]
        c = x["calcs"]
        trade.append({"size_u": s, "label": S.label(s), "failures": fails[s], "feasible": not fails[s],
                      "alt_km": x["orbit"]["alt_km"], "mass_kg": c["budget.mass"]["value"],
                      "mass_limit_kg": R.CDS_MASS_KG[s], "margin_pct": (c.get("power.margin") or {}).get("value"),
                      "data_pct": (c.get("budget.data") or {}).get("value"),
                      "fill_pct": c["structure.volume"]["value"],
                      "cost": c["budget.cost"]["totals"], "quotes": len(c["budget.cost"]["quotes"]),
                      "payload": [i["name"] for i in _pick_json(x["picks"]["payload"])["items"]],
                      "gsd_m": (c.get("imaging.camera_gsd") or {}).get("value"),
                      "checks": C.summary(x["checks"])["counts"]})
    calcs = st["calcs"]
    fidelity = rv.get("mission.fidelity") or "conceptual"
    return {
        "engine": ENGINE_VERSION, "computed_at": now_iso(), "design_id": design.get("id"),
        "fidelity": fidelity, "mission_years": years, "prefs": prefs,
        "size_u": chosen, "size_label": S.label(chosen), "size_why": size_why, "size_user": chosen == design.get("size_u"),
        "orbit": {k: v for k, v in st["orbit"].items() if k != "src"},
        "picks": {slot: _pick_json(p) for slot, p in st["picks"].items()},
        "slots": [{"id": s.id, "label": s.label, "place": s.place} for s in RC.SLOTS],
        "calcs": calcs, "groups": _groups(calcs),
        "refs": {k: R.ref(k) for k in sorted({r for c in calcs.values() for r in c.get("refs", [])} |
                                             {c["source"] for c in st["checks"] if c.get("source")}) if k in R.REFS},
        "checks": st["checks"], "check_summary": C.summary(st["checks"]),
        "trade": trade, "failures": fails[chosen],
        "missing_hardware": _missing_hardware(st),
        "flags": st["orbit"]["flags"] + [f for p in st["picks"].values() for f in p.get("flags", [])],
        "sliders": RC.SLIDERS,
        "disclaimer": ("A conceptual design from published data and simplified physics. It is not flight-ready: a "
                       "flight design needs detailed analysis, environmental testing, licensing and an engineering "
                       "review." if fidelity != "flight" else
                       "Intended for flight, but not flight-ready: every assumption below must be verified by "
                       "analysis and test, and the design reviewed, before it can fly."),
    }


def _missing_hardware(st: dict) -> list[str]:
    out = []
    p = st["picks"]
    if (p.get("magnetorquer") or {}).get("items") and not (p.get("adcs") or {}).get("items"):
        out.append("a magnetometer to drive the magnetorquers (none in the catalog; some computers and attitude "
                   "boards include one — check)")
    if (p.get("gnss") or {}).get("items"):
        out.append("a GNSS antenna (the receivers in the catalog need an external one; not in the catalog)")
    for slot in ("structure", "payload", "eps", "battery", "obc"):
        if (p.get(slot) or {}).get("status") == "missing":
            out.append(f"{RC.SLOT[slot].label}: {p[slot]['why']}")
    return out
