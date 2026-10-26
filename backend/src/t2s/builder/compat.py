"""Compatibility checks of a Builder design.

Every rule compares published catalog values or analysis results, and gives one of four statuses:

* "compatible" — verified from the published values and the analyses;
* "assumptions" — compatible with stated assumptions or modifications (a configurable output, a converter, a thinner
  wall…), which the detail names;
* "incompatible" — the published values or the analyses rule it out;
* "unknown" — insufficient information to verify: a value is not published. Never treated as compatible.

Values read from makers' text (supply voltages, interfaces) are shown as parsed, so the reasoning can be checked.
"""
from __future__ import annotations

import re

from . import catalog as K
from .analysis import structure as S
from .catalog import parse as P

STATUS = {"compatible": "Compatible", "assumptions": "Compatible with assumptions or modifications",
          "incompatible": "Incompatible", "unknown": "Insufficient information to verify"}
ORDER = {"incompatible": 0, "unknown": 1, "assumptions": 2, "compatible": 3}


def check(rule: str, status: str, title: str, detail: str, items=(), fix: str = "", source: str = "") -> dict:
    if status not in STATUS:
        raise ValueError(status)
    return {"rule": rule, "status": status, "status_text": STATUS[status], "title": title, "detail": detail,
            "items": list(items), "fix": fix, "source": source}


def worst(statuses) -> str:
    s = list(statuses)
    return min(s, key=lambda x: ORDER[x]) if s else "unknown"


# ============================================================================================ reading text
_V3V3 = re.compile(r"(\d+)V(\d+)")
_RANGE = re.compile(r"(\d+(?:[.,]\d+)?)\s*V?\s*(?:-|–|to)\s*(\d+(?:[.,]\d+)?)\s*V(?:DC)?\b", re.IGNORECASE)
_SINGLE = re.compile(r"(?<![\d.,])(\d+(?:[.,]\d+)?)\s*V(?:DC)?\b", re.IGNORECASE)


def _f(x: str) -> float:
    return float(x.replace(",", "."))


def volt_values(text) -> tuple[list[float], list[tuple[float, float]]]:
    """Single voltages and ranges named in a text ("3V3" is 3.3 V)."""
    t = _V3V3.sub(r"\1.\2 V", str(text or ""))
    ranges = [(_f(a), _f(b)) for a, b in _RANGE.findall(t)]
    singles = [_f(x) for x in _SINGLE.findall(_RANGE.sub(" ", t))]
    return singles, ranges


def eps_outputs(eps: dict) -> tuple[list[float], list[tuple[float, float]]]:
    texts = [K.perf(eps, "bus_voltages"), K.perf(eps, "outputs")]
    singles, ranges = [], []
    for t in texts:
        s, r = volt_values(t)
        singles += s
        ranges += r
    return sorted(set(singles)), sorted(set(ranges))


def supply_text(c: dict) -> str | None:
    """A part's supply voltage text; a bare number or range ("5", "11.5-20") is in volts, as the field
    (supply_voltage_v) is."""
    v = K.voltage_text(c)
    if v and not re.search(r"[A-Za-z]", v):
        return f"{v} V"
    return v


def supply_match(c: dict, eps: dict) -> tuple[str, str]:
    """(status, detail) of a part's supply voltages against the EPS outputs."""
    need_s, need_r = volt_values(supply_text(c))
    if not need_s and not need_r:
        return "unknown", f"{c['product']} publishes no supply voltage"
    out_s, out_r = eps_outputs(eps)
    if not out_s and not out_r:
        return "unknown", f"{eps['product']} publishes no output voltages"
    fixed, assumed, missed = [], [], []
    for v in need_s:
        if any(abs(v - e) <= 0.05 * v for e in out_s):
            fixed.append(f"{v:g} V")
        elif any(lo <= v <= hi for lo, hi in out_r):
            assumed.append(f"{v:g} V")
        else:
            missed.append(f"{v:g} V")
    for lo, hi in need_r:
        if any(lo <= e <= hi for e in out_s):
            fixed.append(f"{lo:g}–{hi:g} V")
        elif any(a <= hi and b >= lo for a, b in out_r):
            assumed.append(f"{lo:g}–{hi:g} V")
        else:
            missed.append(f"{lo:g}–{hi:g} V")
    parsed = (f"needs {', '.join(fixed + assumed + missed)}; {eps['product']} gives "
              f"{', '.join(f'{v:g} V' for v in out_s)}" + (f" and {', '.join(f'{a:g}–{b:g} V' for a, b in out_r)} "
                                                           "(configurable or unregulated)" if out_r else ""))
    if not missed and not assumed:
        return "compatible", parsed
    if not missed:
        return "assumptions", parsed + f"; {', '.join(assumed)} from a configurable or unregulated output"
    if fixed or assumed:
        return "assumptions", parsed + f"; no output for {', '.join(missed)} (a converter, or a value that is not a " \
                                       "supply rail)"
    return "incompatible", parsed + "; none of its supplies is available (a converter is needed)"


IFACES = {"I2C": r"i2c|i²c|smbus", "UART": r"uart|usart|rs-?232", "RS-422": r"(?<!\d)422(?!\d)",
          "RS-485": r"(?<!\d)485(?!\d)", "CAN": r"\bcan\b|can[- ]?fd|canbus", "SPI": r"\bq?spi\b",
          "LVDS": r"lvds|camera ?link", "SpaceWire": r"spacewire", "Ethernet": r"ethernet|base-t|gbase",
          "USB": r"\busb\b"}


def ifaces(c: dict, prefix: str | None = None) -> set[str]:
    """The data interfaces an entry lists (only those whose text starts with `prefix`, e.g. "Data")."""
    out = set()
    for t in K.data_interfaces(c):
        if prefix and not t.lower().startswith(prefix.lower()):
            continue
        for k, pat in IFACES.items():
            if re.search(pat, t, re.IGNORECASE):
                out.add(k)
    return out


# ============================================================================================ the rules
PASSIVE = ("structure", "solar_panel")


def check_design(d: dict) -> list[dict]:
    """d: size, sel {slot: [(entry, qty)]}, calcs, places {slot: place}, thermal, req, picks."""
    out = []
    sel, calcs, size = d["sel"], d["calcs"], d["size"]
    flat = [(slot, c, q) for slot, items in sel.items() for c, q in items]
    real = [(slot, c, q) for slot, c, q in flat if not c.get("_placeholder")]
    eps = (sel.get("eps") or [(None, 0)])[0][0]
    obc = (sel.get("obc") or [(None, 0)])[0][0]

    # supply voltages
    for slot, c, _ in real:
        if c["category"] in ("eps", "structure", "antenna", "battery") or slot == "solar":
            continue
        if eps is None:
            out.append(check("voltage", "unknown", f"{c['product']}: supply voltage", "no EPS selected", [c["id"]]))
            continue
        st, detail = supply_match(c, eps)
        out.append(check("voltage", st, f"{c['product']}: supply voltage", detail, [c["id"], eps["id"]],
                         fix="add a converter or pick an EPS with that output" if st == "incompatible" else ""))
    # data interfaces with the computer
    for slot, c, _ in real:
        if c["category"] in ("obc", "structure", "solar_panel") or c is obc:
            continue
        mine = ifaces(c)
        if not mine:
            if c["category"] in ("antenna", "magnetorquer"):
                continue                           # RF or driven coils: no data link of their own
            listed = K.data_interfaces(c)
            out.append(check("data_interface", "unknown", f"{c['product']}: data link",
                             f"its interfaces ({'; '.join(listed)}) are not ones the Builder recognises" if listed
                             else "its data interface is not published", [c["id"]]))
            continue
        if obc is None:
            out.append(check("data_interface", "unknown", f"{c['product']}: data link", "no computer selected",
                             [c["id"]]))
            continue
        common = mine & ifaces(obc)
        out.append(check("data_interface", "compatible" if common else "incompatible", f"{c['product']}: data link",
                         (f"both have {', '.join(sorted(common))}" if common else
                          f"{c['product']} has {', '.join(sorted(mine))}; {obc['product']} has "
                          f"{', '.join(sorted(ifaces(obc))) or 'none listed'}: no common interface for a direct "
                          "connection (an interface board could bridge them)"), [c["id"], obc["id"]]))
    cam = next((c for slot, c, _ in real if c["category"] == "camera"), None)
    if cam is not None and obc is not None:
        fast = ifaces(cam, "data")
        common = fast & ifaces(obc)
        out.append(check("image_path", "compatible" if common else "assumptions" if fast else "unknown",
                         "Image data path (camera → computer)",
                         (f"full-rate image data over {', '.join(sorted(common))}" if common else
                          f"the camera's image interfaces ({', '.join(sorted(fast))}) are not on {obc['product']}: "
                          "images stay in the camera's own storage and move over a control link at a lower rate, or "
                          "a payload data processor is needed" if fast else "the camera's image interface is not "
                                                                             "published"), [cam["id"], obc["id"]]))
    # mechanical fit and the optimiser's packing model
    for slot, c, _ in flat:
        if d["places"].get(slot) != "internal":
            continue
        dims = K.dims_mm(c) if not c.get("_placeholder") else tuple(c["dimensions_mm"][k] for k in "xyz")
        f = S.fit(dims, size)
        st = {"fits": "compatible", "tight": "assumptions", "too_big": "incompatible", None: "unknown"}[f]
        detail = {"fits": f"fits the {S.label(size)} inner space ({_dims(dims)})",
                  "tight": f"{_dims(dims)} fits the {S.label(size)} rail envelope but not the 2 mm-wall frame "
                           "model: it needs a structure with thinner walls or an opening",
                  "too_big": f"{_dims(dims)} does not fit a {S.label(size)}",
                  None: "its dimensions are not published"}[f]
        out.append(check("mechanical", st, f"{c['product']}: fits the structure", detail, [c["id"]]))
        if size in S.PACKED_SIZES and dims is not None:
            pf = S.packing_fit(dims, size)
            if pf == "stage1":
                out.append(check("packing_model", "assumptions", f"{c['product']}: optimiser packing model",
                                 f"{_dims(dims)} fits the optimiser's idealized Stage 1 (the rail envelope) but not "
                                 "its Stage 2 frame model (2 mm walls, 8.5 mm corner rails, 1.2 mm clearances): "
                                 "Stage 2 cannot place it as a box", [c["id"]],
                                 fix="import the maker's CAD (its real outline), or check the fit in the real "
                                     "structure"))
            elif pf == "too_big":
                out.append(check("packing_model", "incompatible", f"{c['product']}: optimiser packing model",
                                 f"{_dims(dims)} is not smaller than the {S.label(size)} rail envelope "
                                 f"({_dims(S.outer(size))}): the optimiser keeps every part strictly inside it, so "
                                 "it cannot place this one", [c["id"]],
                                 fix="a larger size, another part, or the maker's CAD if its true outline is smaller"))
    # external hardware against the CDS protrusion allowance
    for slot, c, q in flat:
        if d["places"].get(slot) != "external" or c.get("_placeholder"):
            continue
        dims = K.dims_mm(c)
        if dims is None:
            out.append(check("clearance", "unknown", f"{c['product']}: stowed thickness", "its dimensions are not "
                             "published", [c["id"]]))
            continue
        t = min(dims)
        out.append(check("clearance", "compatible" if t <= 6.5 else "assumptions",
                         f"{c['product']}: stowed thickness",
                         f"{t:g} mm thick" + (" — within the 6.5 mm the CubeSat Design Specification allows beyond "
                                              "the rails" if t <= 6.5 else " — more than the 6.5 mm allowed on the "
                                                                           "side faces: it must sit on an end face "
                                                                           "or in a recess"),
                         [c["id"]], source="cds"))
    # thermal ranges
    nom = (calcs.get("thermal.nominal") or {}).get("value")
    hot = (calcs.get("thermal.hot") or {}).get("value")
    cold = (calcs.get("thermal.cold") or {}).get("value")
    for slot, c, _ in real:
        rng = K.temp_range(c)
        if rng is None:
            if c["category"] not in ("structure",):
                out.append(check("thermal", "unknown", f"{c['product']}: temperature range",
                                 "its operating temperature range is not published", [c["id"]]))
            continue
        lo, hi = rng
        if nom is None:
            continue
        if not lo <= nom <= hi:
            st, why = "incompatible", f"the nominal {nom:.1f} °C is outside its {lo:g} to {hi:g} °C"
        elif cold is not None and hot is not None and (cold < lo or hot > hi):
            st, why = "assumptions", (f"nominal {nom:.1f} °C is inside {lo:g} to {hi:g} °C, but the bounds "
                                      f"({cold:.1f} to {hot:.1f} °C) are not: needs thermal control (heaters, "
                                      "coatings or radiators)")
        else:
            st, why = "compatible", f"{lo:g} to {hi:g} °C covers {cold:.1f} to {hot:.1f} °C"
        out.append(check("thermal", st, f"{c['product']}: temperature range", why, [c["id"]]))
    # budgets and performance against the requirements
    out += _calc_checks(calcs)
    # GNSS velocity limits
    for slot, c, _ in real:
        if c["category"] != "gnss":
            continue
        text = str(K.perf(c, "max_altitude_or_velocity_limits") or "")
        vals = [float(m[1]) * (1000.0 if m[2] == "km/s" else 1.0)
                for m in re.finditer(r"(\d+(?:\.\d+)?)\s*(km/s|m/s)", text)]
        v_orbit = (calcs.get("orbit.speed") or {}).get("value")
        if not vals or v_orbit is None:
            out.append(check("gnss_limits", "unknown", f"{c['product']}: works at orbital speed",
                             "no velocity limit published", [c["id"]]))
        elif min(vals) >= v_orbit * 1000.0:
            out.append(check("gnss_limits", "compatible", f"{c['product']}: works at orbital speed",
                             f"limit {min(vals) / 1000:g} km/s ≥ {v_orbit:.2f} km/s", [c["id"]]))
        else:
            st = "assumptions" if "no cocom" in text.lower() else "incompatible"
            out.append(check("gnss_limits", st, f"{c['product']}: works at orbital speed",
                             f"a {min(vals):g} m/s limit is stated" + (" for the standard receiver; the maker says "
                                                                        "the space version has none (confirm)" if
                                                                        st == "assumptions" else ""), [c["id"]]))
    # EPS input power
    gen = calcs.get("power.generation") or {}
    if eps is not None and gen.get("value") is not None:
        pin = P._largest(K.perf(eps, "input_power_max_w"))
        peak = gen.get("panel_w")
        if pin is None or peak is None:
            out.append(check("eps_input", "unknown", "Solar input within the EPS rating",
                             f"{eps['product']} publishes no maximum input power" if pin is None else
                             "panel power unknown", [eps["id"]]))
        else:
            out.append(check("eps_input", "compatible" if peak <= pin else "incompatible",
                             "Solar input within the EPS rating", f"panels up to {peak:.0f} W; EPS input up to "
                                                                  f"{pin:g} W", [eps["id"]]))
    return sorted(out, key=lambda x: (ORDER[x["status"]], x["rule"]))


def _dims(dims) -> str:
    return "size not published" if dims is None else " × ".join(f"{x:g}" for x in dims) + " mm"


def _calc_checks(calcs: dict) -> list[dict]:
    out = []

    def from_ok(cid, rule, title, good, bad, unknown="not computed (a value is missing)", ok_key="ok"):
        c = calcs.get(cid)
        if c is None:
            return
        if c.get("value") is None or c.get(ok_key) is None:
            out.append(check(rule, "unknown", title, c.get("missing") or unknown))
        else:
            out.append(check(rule, "compatible" if c[ok_key] else "incompatible", title,
                             good(c) if c[ok_key] else bad(c)))
    unpowered = (calcs.get("power.load_avg") or {}).get("missing_parts") or []
    pm = calcs.get("power.margin")
    if pm is not None and pm.get("value") is not None and pm["value"] >= 0 and unpowered:
        out.append(check("power", "unknown", "Power: generation covers the loads",
                         f"{pm['value']:+.0f} % energy margin on the worst day without {len(unpowered)} part(s) whose "
                         f"power is not published ({', '.join(unpowered)})", fix="ask the maker for the power"))
    elif pm is not None and pm.get("value") is not None and pm["value"] >= 0 and not pm.get("ok"):
        out.append(check("power", "assumptions", "Power: generation covers the loads",
                         f"{pm['value']:+.0f} % energy margin on the worst day: positive, but below the "
                         f"{pm['target_pct']:g} % design margin", fix="add panels or reduce the duty cycles"))
    else:
        from_ok("power.margin", "power", "Power: generation covers the loads",
                lambda c: f"{c['value']:+.0f} % energy margin on the worst day (target {c['target_pct']:g} %)",
                lambda c: f"{c['value']:+.0f} % energy margin on the worst day: not enough power")
    from_ok("power.battery", "battery", "Battery covers the eclipse",
            lambda c: f"{c['value']:g} Wh ≥ {calcs['power.battery_need']['value']:.1f} Wh needed",
            lambda c: f"{c['value']:g} Wh < {calcs['power.battery_need']['value']:.1f} Wh needed")
    from_ok("budget.data", "data", "Data: the downlink returns the daily data",
            lambda c: f"{c['value']:.0f} % of the daily data returned",
            lambda c: f"only {c['value']:.0f} % of the daily data can be downlinked")
    from_ok("adcs.pointing", "adcs_pointing", "Attitude control meets the pointing need",
            lambda c: f"{c['value']:.3g}° ≤ {c['need']:.3g}° needed",
            lambda c: f"{c['value']:.3g}° > {c['need']:.3g}° needed")
    from_ok("adcs.momentum", "adcs_momentum", "Wheels store the momentum needed",
            lambda c: f"{c['value']:g} mN·m·s ≥ {c['need']:.2f} needed",
            lambda c: f"{c['value']:g} mN·m·s < {c['need']:.2f} needed")
    from_ok("adcs.knowledge", "adcs_knowledge", "Attitude knowledge for image geolocation",
            lambda c: f"{c['value']:.3g}″ ≤ {c['need']:.3g}″ needed",
            lambda c: f"{c['value']:.3g}″ > {c['need']:.3g}″ needed")
    vol = calcs.get("structure.volume")
    if vol is not None and vol.get("ok") and vol.get("missing_parts"):
        out.append(check("volume", "unknown", "Volume: the parts fit with room to integrate",
                         f"{vol['value']:.0f} % of the usable volume without {len(vol['missing_parts'])} part(s) whose "
                         f"size is not published ({', '.join(vol['missing_parts'])})"))
    else:
        from_ok("structure.volume", "volume", "Volume: the parts fit with room to integrate",
                lambda c: f"{c['value']:.0f} % of the usable volume (≤ {c['fill_max']:.0%})",
                lambda c: f"{c['value']:.0f} % of the usable volume (> {c['fill_max']:.0%})")
    m = calcs.get("budget.mass")
    if m is not None:
        lim = m["limit_kg"]
        with_margin = m["with_margin_kg"]
        if m["value"] > lim:
            st, why = "incompatible", f"{m['value']:.2f} kg is over the {lim:g} kg limit"
        elif m.get("missing_items"):
            st, why = "unknown", (f"{m['value']:.2f} kg without {len(m['missing_items'])} part(s) whose mass is not "
                                  f"published ({', '.join(m['missing_items'])})")
        elif with_margin > lim:
            st, why = "assumptions", (f"{m['value']:.2f} kg is within {lim:g} kg, but not with the "
                                      f"{m['margin_pct']:g} % design margin ({with_margin:.2f} kg)")
        else:
            st, why = "compatible", f"{with_margin:.2f} kg with margin ≤ {lim:g} kg"
        out.append(check("mass", st, "Mass within the CubeSat limit", why, source="cds"))
    from_ok("orbit.lifetime", "lifetime", "The orbit lasts the mission",
            lambda c: f"about {c['value']:.1f} years ≥ {c['mission_years']:g}",
            lambda c: f"about {c['value']:.1f} years < {c['mission_years']:g}: needs a higher orbit or propulsion")
    from_ok("orbit.disposal", "disposal", "Re-entry within five years of the mission's end (FCC)",
            lambda c: f"decays {max(c['value'], 0):.1f} years after the mission",
            lambda c: f"stays up {c['value']:.1f} years after the mission: needs a way down")
    ap = calcs.get("imaging.aperture_fit")
    if ap is not None and ap.get("value") is not None:
        meets = (calcs.get("imaging.camera_gsd") or {}).get("meets")
        st = "compatible" if ap.get("feasible") else "assumptions" if meets else "incompatible"
        out.append(check("aperture", st, "The telescope needed fits the size",
                         ap["explain"] + (" The selected camera still reaches the pixel size it publishes." if
                                          st == "assumptions" else "")))
    from_ok("imaging.camera_gsd", "gsd", "The camera reaches the pixel size",
            lambda c: c["explain"], lambda c: c["explain"], ok_key="meets")
    from_ok("imaging.bands", "bands", "The camera covers the bands asked for",
            lambda c: c["explain"], lambda c: c["explain"], unknown="the camera does not publish its bands")
    from_ok("orbit.access", "revisit", "Revisit of the target region",
            lambda c: c["explain"], lambda c: c["explain"] + f" You asked for {c['revisit_h']:g} h.",
            unknown="fewer than two looks in the simulated week, or no revisit asked for")
    from_ok("propulsion.dv", "propulsion", "The thruster gives the Δv needed",
            lambda c: f"{c['value']:.0f} m/s ≥ {c['need']:.0f} m/s", lambda c: f"{c['value']:.0f} m/s < {c['need']:.0f} m/s")
    return out


def summary(checks: list[dict]) -> dict:
    counts = {k: 0 for k in STATUS}
    for c in checks:
        counts[c["status"]] += 1
    return {"counts": counts, "overall": worst(c["status"] for c in checks) if checks else "unknown"}
