"""The spacecraft architect's component choices (V3 CubeSat Builder).

For each slot of the design the architect takes the catalog entries of that kind, drops the ones that cannot do the
job (hard rules: too big for the CubeSat size, the wrong radio band, short of the pixel size when another camera
reaches it…) and ranks the rest by the user's priorities (the sliders): listed price, mass, power, performance,
volume, and how much of each entry's data its maker publishes. A value that is not published counts as unknown —
never as good — so entries whose numbers can be checked rank first. Each pick says why, and every other entry says
why it was not picked.

The picks are recommendations for a conceptual design: they rest on the catalog's published values and the analyses,
not on flight heritage, availability or export rules, which the user must still confirm with the makers.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass

from . import catalog as K
from .analysis import imaging as IM
from .analysis import structure as S
from .analysis.propulsion import thruster_dv
from .catalog import parse as P
from .compat import eps_outputs, ifaces, supply_text, volt_values


@dataclass(frozen=True)
class Slot:
    id: str
    label: str
    categories: tuple
    place: str                  # "internal" (packed), "external" (on a face, not packed) or "frame"


SLOTS = (
    Slot("payload", "Payload", ("camera", "radio"), "internal"),
    Slot("adcs", "Attitude control unit", ("adcs_unit",), "internal"),
    Slot("wheels", "Reaction wheels", ("reaction_wheel",), "internal"),
    Slot("magnetorquer", "Magnetorquers", ("magnetorquer",), "internal"),
    Slot("star_tracker", "Star tracker", ("star_tracker",), "internal"),
    Slot("sun_sensor", "Sun sensors", ("sun_sensor",), "external"),
    Slot("gnss", "GNSS receiver", ("gnss",), "internal"),
    Slot("obc", "On-board computer", ("obc",), "internal"),
    Slot("eps", "Power system (EPS)", ("eps",), "internal"),
    Slot("battery", "Battery", ("battery",), "internal"),
    Slot("solar", "Solar panels", ("solar_panel",), "external"),
    Slot("radio_ttc", "UHF radio (commands and telemetry)", ("radio",), "internal"),
    Slot("antenna_ttc", "UHF antenna", ("antenna",), "external"),
    Slot("radio_data", "Data downlink radio", ("radio",), "internal"),
    Slot("antenna_data", "Data downlink antenna", ("antenna",), "external"),
    Slot("propulsion", "Propulsion", ("propulsion",), "internal"),
    Slot("structure", "Structure", ("structure",), "frame"),
)
SLOT = {s.id: s for s in SLOTS}

# the trade sliders (0 … 1) and their defaults
SLIDERS = {
    "cost_performance": {"label": "Cost ↔ performance", "low": "Lowest cost", "high": "Best performance",
                         "default": 0.5},
    "mass_capability": {"label": "Mass ↔ capability", "low": "Lightest", "high": "Most capable", "default": 0.5},
    "power_efficiency": {"label": "Power efficiency", "low": "Ignore power", "high": "Least power", "default": 0.5},
    "reliability_cost": {"label": "Cost ↔ reliability", "low": "Single string", "high": "Redundant",
                         "default": 0.0},
    "imaging": {"label": "Imaging performance", "low": "Just meet it", "high": "Sharpest", "default": 0.5},
    "packaging": {"label": "Packaging efficiency", "low": "Ignore volume", "high": "Smallest parts",
                  "default": 0.3},
}


def prefs_of(design: dict) -> dict:
    p = dict(design.get("prefs") or {})
    out = {k: float(p.get(k, v["default"])) for k, v in SLIDERS.items()}
    out = {k: min(1.0, max(0.0, v)) for k, v in out.items()}
    if p.get("lifetime_years") is not None:
        out["lifetime_years"] = float(p["lifetime_years"])
    return out


def weights(prefs: dict) -> dict:
    cp, mc = prefs["cost_performance"], prefs["mass_capability"]
    return {"cost": 1.0 - cp, "performance": 0.5 * (cp + mc), "mass": 1.0 - mc, "power": prefs["power_efficiency"],
            "packaging": prefs["packaging"], "data": 0.6}


# ============================================================================================ reading entries
def stated_sizes(text) -> list[tuple[float, float]]:
    """The CubeSat sizes a maker's fit statement names, as (lo, hi) ranges ("6-12U", "up to 6U", "as small as 2U",
    "1U and larger"); payload volumes, module and face sizes are not host sizes and are skipped."""
    t = " " + str(text or "").lower() + " "
    t = re.sub(r"[^()]*variant[^()]*", " ", t)
    t = re.sub(r"(\d+(?:\.\d+)?)\s*u\s*(?:payload|module|face|of|format|volume|surface|stationary|solar)", " ", t)
    out: list = []

    def eat(pat, mk):
        nonlocal t
        out.extend(mk(m) for m in re.finditer(pat, t))
        t = re.sub(pat, " ", t)
    eat(r"(?:up to|upto)\s*(\d+(?:\.\d+)?)\s*u", lambda m: (1.0, float(m[1])))
    eat(r"(?:starting from|from|as small as|at least)\s*(\d+(?:\.\d+)?)\s*u", lambda m: (float(m[1]), 99.0))
    eat(r"(\d+(?:\.\d+)?)\s*u\s*(?:and|or)\s*(?:larger|up\b|upwards|bigger)", lambda m: (float(m[1]), 99.0))
    eat(r"(\d+(?:\.\d+)?)\s*u?\s*(?:-|–|to)\s*(\d+(?:\.\d+)?)\s*u", lambda m: (float(m[1]), float(m[2])))
    eat(r"(?<![\d.])(\d+(?:\.\d+)?)\s*u(?:xl)?\b", lambda m: (float(m[1]), float(m[1])))
    return [r for r in out if r[1] >= 1.0]


def size_ok(c: dict, size) -> bool | None:
    """Whether the maker's fit statement includes this size (None: it names none)."""
    rs = stated_sizes(c.get("fits"))
    if not rs:
        return None
    return any(lo - 1e-9 <= size <= hi + 1e-9 for lo, hi in rs)


def completeness(c: dict) -> float:
    """Share of the key values its maker publishes (mass, size, power, price, temperature range)."""
    have = [K.mass_kg(c) is not None, K.dims_mm(c) is not None,
            any(K.power_w(c, k) is not None for k in ("typical", "peak")), K.price(c)["value"] is not None,
            K.temp_range(c) is not None]
    return sum(have) / len(have)


def power_on(c: dict) -> float | None:
    t = K.power_w(c, "typical")
    return t if t is not None else K.power_w(c, "peak")


def name(c: dict) -> str:
    return f"{c['manufacturer']} {c['product']}"


def velocity_limit_ms(c: dict) -> float | None:
    """The lowest velocity limit a GNSS entry states (m/s), or None."""
    text = str(K.perf(c, "max_altitude_or_velocity_limits") or "")
    vals = []
    for m in re.finditer(r"(\d+(?:\.\d+)?)\s*(km/s|m/s)", text):
        vals.append(float(m[1]) * (1000.0 if m[2] == "km/s" else 1.0))
    return min(vals) if vals else None


# ============================================================================================ ranking
def rank(cands: list[dict], w: dict, perf=None, extra=None) -> list[tuple[float, dict, dict]]:
    """(score, entry, parts) best first. perf(c) -> a number, higher better (None: unknown); extra(c) -> {name: (0…1,
    weight)} more criteria. Lower-better criteria: listed price, mass, power, volume. Unknown values score 0."""
    listed = [K.price(c)["currency"] for c in cands if K.price(c)["value"] is not None]
    cur = max(set(listed), key=listed.count) if listed else None        # prices compare only in one currency

    def cost(c):
        p = K.price(c)
        return p["value"] if p["currency"] == cur else None
    crit = {"cost": (cost, "low"), "mass": (K.mass_kg, "low"), "power": (power_on, "low"),
            "packaging": (K.volume_cm3, "low")}
    if perf is not None:
        crit["performance"] = (perf, "high")
    vals = {k: [f(c) for c in cands] for k, (f, _) in crit.items()}
    out = []
    for i, c in enumerate(cands):
        parts = {}
        for k, (_, sense) in crit.items():
            known = [v for v in vals[k] if v is not None]
            v = vals[k][i]
            if v is None or not known:
                s = 0.0
            elif max(known) == min(known):
                s = 1.0
            else:
                s = (max(known) - v) / (max(known) - min(known)) if sense == "low" else \
                    (v - min(known)) / (max(known) - min(known))
            parts[k] = (s, w.get(k, 0.0))
        parts["data"] = (completeness(c), w.get("data", 0.6))
        for k, sw in (extra(c) if extra else {}).items():
            parts[k] = sw
        total = sum(s * wt for s, wt in parts.values()) / max(sum(wt for _, wt in parts.values()), 1e-9)
        out.append((total, c, parts))
    out.sort(key=lambda x: (-x[0], x[1]["id"]))
    return out


def _why_parts(parts: dict) -> str:
    good = [k for k, (s, wt) in sorted(parts.items(), key=lambda kv: -kv[1][0] * kv[1][1]) if s >= 0.75 and wt > 0]
    words = {"cost": "a low listed price", "mass": "low mass", "power": "low power", "packaging": "a small volume",
             "performance": "the best performance", "data": "published data", "size": "its maker's stated size",
             "fit": "a clean fit", "family": "the same maker as the EPS", "links": "direct links to the parts",
             "voltages": "supplying the parts' voltages", "supply": "a supply voltage common EPS boards give",
             "bands": "naming the bands you asked for"}
    return ", ".join(words.get(k, k) for k in good[:3])


def pick(slot: str, ranked: list, why: str, rejected: list | None = None, qty: int = 1, need: str = "",
         flags: list | None = None) -> dict:
    """A slot's pick: the best-ranked entry whose budget values are all published (when one is; else the
    best-ranked), the reasons and the alternatives."""
    flags = list(flags or [])
    full = [r for r in ranked if not unpublished(r[1])]
    order = (full + [r for r in ranked if r not in full]) if full else ranked
    alts = []
    for s, c, _ in order[1:]:
        miss = unpublished(c)
        alts.append({"id": c["id"], "name": name(c), "score": round(s, 3),
                     "reason": (f"does not publish its {', '.join(miss)} (the budgets could not be checked)"
                                if full and miss else "ranked lower")})
    alts += [{"id": c["id"], "name": name(c), "score": None, "reason": r} for c, r in (rejected or [])]
    if not order:
        return {"slot": slot, "label": SLOT[slot].label, "items": [], "status": "missing", "why": why, "need": need,
                "alternatives": alts, "flags": flags}
    s, c, parts = order[0]
    if unpublished(c):
        flags.append(f"{name(c)} does not publish its {', '.join(unpublished(c))}: that budget cannot be verified "
                     "(ask the maker)")
    reason = _why_parts(parts)
    return {"slot": slot, "label": SLOT[slot].label, "items": [(c, qty)], "status": "recommended",
            "why": why + (f" Ranked first for {reason}." if reason else ""), "need": need, "alternatives": alts,
            "score": round(s, 3), "flags": flags}


def none_needed(slot: str, why: str) -> dict:
    return {"slot": slot, "label": SLOT[slot].label, "items": [], "status": "none", "why": why, "need": "",
            "alternatives": [], "flags": []}


UNPOWERED = ("structure", "antenna", "solar_panel", "battery", "eps")


def unpublished(c: dict) -> list[str]:
    """The budget values an entry does not publish: mass; size (internal parts); power (parts that draw it)."""
    out = []
    if K.mass_kg(c) is None:
        out.append("mass")
    if c["category"] not in ("antenna", "solar_panel", "sun_sensor") and K.dims_mm(c) is None:
        out.append("size")
    if c["category"] not in UNPOWERED and power_on(c) is None:
        out.append("power")
    return out


def _fits(c: dict, size) -> str | None:
    return S.fit(K.dims_mm(c), size)


def _split_fit(cands: list[dict], size) -> tuple[list, list]:
    """Drop entries too big for the size, and entries whose size is not published when their maker names other
    sizes (the fit cannot be checked, and the maker's word is all there is)."""
    keep, rejected = [], []
    for c in cands:
        f = _fits(c, size)
        if f == "too_big":
            rejected.append((c, f"too big for a {S.label(size)} ({_dims_text(c)})"))
        elif f is None and size_ok(c, size) is False:
            rng = ", ".join(f"{lo:g}U" if lo == hi else f"{lo:g}U and up" if hi >= 99 else f"{lo:g}–{hi:g}U"
                            for lo, hi in stated_sizes(c.get("fits")))
            rejected.append((c, f"its size is not published and its maker names {rng}"))
        else:
            keep.append(c)
    return keep, rejected


def _dims_text(c: dict) -> str:
    d = K.dims_mm(c)
    return "size not published" if d is None else " × ".join(f"{x:g}" for x in d) + " mm"


def _fit_extra(size):
    def f(c):
        fit = _fits(c, size)
        sz = size_ok(c, size)
        return {"fit": ({"fits": 1.0, "tight": 0.4, None: 0.2}.get(fit, 0.0), 0.8),
                "size": ({True: 1.0, None: 0.5, False: 0.0}[sz], 0.6)}
    return f


# ============================================================================================ the slots
def pick_camera(ctx: dict) -> dict:
    size, alt, req = ctx["size"], ctx["alt_km"], ctx["req"]
    gsd_need = float(req.get("imaging.gsd_m") or 10.0)
    bands = list(req.get("imaging.bands") or ["rgb"])
    cams, rejected = _split_fit(K.by_category("camera"), size)
    info = {}
    for c in cams:
        at = IM.camera_at(c, alt)
        cover = IM.band_cover(c, bands)
        info[c["id"]] = (at.get("gsd_m"), cover)
    meets = [c for c in cams if info[c["id"]][0] is not None and info[c["id"]][0] <= gsd_need * 1.0001
             and False not in info[c["id"]][1].values()]
    flags = []
    pool = meets
    if not meets:
        # the closest the catalog comes: the cameras covering the bands (if any do), within 10 % of the sharpest
        covering = [c for c in cams if False not in info[c["id"]][1].values()] or cams
        known = [c for c in covering if info[c["id"]][0] is not None]
        best = min((info[c["id"]][0] for c in known), default=None)
        pool = [c for c in known if info[c["id"]][0] <= 1.1 * best] if best is not None else covering
        flags.append(f"no camera in the catalog reaches {gsd_need:g} m with the requested bands at {alt:.0f} km "
                     f"in a {S.label(size)}: the closest one is recommended")
    for c in cams:
        if c not in pool:
            g, cover = info[c["id"]]
            missing_b = [b for b, ok in cover.items() if ok is False]
            reason = (f"its pixel is {g:.1f} m at {alt:.0f} km (need {gsd_need:g} m)" if g is not None and
                      g > gsd_need * 1.0001 else f"does not cover {', '.join(missing_b)}" if missing_b else
                      "does not publish its pixel size with an altitude")
            rejected.append((c, reason))
    w = weights(ctx["prefs"])
    w["performance"] = 0.3 + ctx["prefs"]["imaging"]

    def perf(c):
        g = info[c["id"]][0]
        return None if g is None else -g

    def extra(c):
        e = _fit_extra(size)(c)
        cover = info[c["id"]][1]
        e["bands"] = (sum(1.0 for v in cover.values() if v) / max(len(cover), 1), 1.0)   # named, not just possible
        return e
    ranked = rank(pool, w, perf, extra)
    if ranked:
        c = ranked[0][1]
        g = info[c["id"]][0]
        why = (f"Reaches {g:.2f} m pixels at {alt:.0f} km (you asked for {gsd_need:g} m) and covers "
               f"{', '.join(bands)}." if g is not None else "The best available camera.")
    else:
        why = f"No camera in the catalog fits a {S.label(size)}."
    return pick("payload", ranked, why, rejected, need=f"{gsd_need:g} m pixels in {', '.join(bands)}", flags=flags)


def placeholder_payload(req: dict) -> dict:
    """The user's own instrument as a clearly labelled block (their numbers, ASSUMED shape)."""
    vol_u = float(req.get("payload.volume_u") or 0.5)
    length = min(max(vol_u * 100.0, 10.0), 340.0)
    return {"id": "user-payload", "category": "payload", "manufacturer": "Your", "product": "payload (placeholder)",
            "_placeholder": True, "_duty_pct": float(req.get("payload.duty_pct") or 50.0),
            "mass_kg": {"value": float(req.get("payload.mass_kg") or 0.5)},
            "dimensions_mm": {"x": 90.0, "y": 90.0, "z": length},
            "power_w": {"typical": float(req.get("payload.power_w") or 2.0)},
            "price": {"kind": "quote"}, "fits": "your own instrument: a 90 × 90 mm block of your volume (ASSUMED shape)",
            "description": "Your payload, from your answers (mass, power, volume, data rate, duty cycle)."}


def pick_payload(ctx: dict) -> dict:
    req = ctx["req"]
    mt = req.get("mission.type")
    if mt == "earth_observation":
        return pick_camera(ctx)
    if mt == "communications":
        service = req.get("comms.service") or "store_forward"
        if service == "ais_adsb":
            return {"slot": "payload", "label": SLOT["payload"].label, "items": [], "status": "missing",
                    "why": "The catalog has no AIS or ADS-B receiver yet: add your own receiver as a custom part.",
                    "need": "an AIS/ADS-B receiver", "alternatives": [], "flags": []}
        band = "s" if service == "relay" else "uhf"
        radios = [c for c in K.by_category("radio") if band in P.band(c)]
        radios, rejected = _split_fit(radios, ctx["size"])
        ranked = rank(radios, weights(ctx["prefs"]), lambda c: P.data_rate_bps(c)[0], _fit_extra(ctx["size"]))
        return pick("payload", ranked, f"A {band.upper()} radio carries the {service.replace('_', '-')} service.",
                    rejected, need=f"{band.upper()} service radio")
    ph = placeholder_payload(req)
    return {"slot": "payload", "label": SLOT["payload"].label, "items": [(ph, 1)], "status": "placeholder",
            "why": "Your own instrument, from your answers: a placeholder block of its mass, power and volume.",
            "need": "", "alternatives": [], "flags": ["placeholder: replace with your instrument's real data and CAD"]}


def pointing_class(ctx: dict) -> tuple[str, float | None, str]:
    """("fine" | "medium" | "coarse", the pointing need in degrees, why)."""
    req, calcs = ctx["req"], ctx.get("calcs", {})
    mt = req.get("mission.type")
    if mt == "earth_observation":
        need = (calcs.get("imaging.pointing_req") or {}).get("value")
        if need is not None and need < 1.0:
            return "fine", need, f"imaging needs {need:.2f}° pointing"
        return "medium", need, "imaging needs the camera on its target"
    if mt == "astronomy":
        stab = float(req.get("astro.stability_arcsec") or 10.0)
        return "fine", stab / 3600.0, f"the telescope needs {stab:g}″ stability"
    p = req.get("payload.pointing")
    if p in ("nadir", "sun"):
        return "medium", 5.0, f"the payload points at the {'Earth' if p == 'nadir' else 'Sun'} (ASSUMED 5°)"
    if p == "inertial":
        return "fine", 0.1, "the payload points at fixed stars (ASSUMED 0.1°)"
    if ctx.get("needs_patch"):
        return "medium", 10.0, "the data antenna must face the ground station (ASSUMED 10°)"
    return "coarse", None, "no pointing need: detumbling and sun-pointing for power only"


def sun_sensor_count(c: dict) -> int:
    """At least 4π / Ω sensors to see the Sun from any attitude (Ω the field of view's solid angle; ASSUMED no overlap
    losses); the field of view is a full or half angle as the entry's unit says."""
    f = K.perf_field(c, "fov_deg")
    fov = P._largest(f.get("value"))
    if not fov:
        return 2
    half = fov if "half" in str(f.get("unit") or "") else fov / 2.0
    omega = 2 * math.pi * (1 - math.cos(math.radians(min(half, 90.0))))
    return max(1, math.ceil(4 * math.pi / omega - 1e-9))


def pick_adcs(ctx: dict) -> dict[str, dict]:
    """The attitude hardware for the pointing class: an integrated unit (fine), wheels + magnetorquers + sun sensors
    (medium), or magnetorquers + sun sensors (coarse)."""
    size = ctx["size"]
    cls, need, why = pointing_class(ctx)
    w = weights(ctx["prefs"])
    out = {}
    h_need = ctx.get("momentum_need_mNms")
    if cls == "fine":
        units, rejected = _split_fit(K.by_category("adcs_unit"), size)
        acc = {c["id"]: P.angle_deg(c, "pointing_accuracy") for c in units}
        meets = [c for c in units if acc[c["id"]] is not None and need is not None and acc[c["id"]] <= need]
        pool = meets
        if not meets:                              # the closest the catalog comes (within 10 % of the best)
            known = [acc[c["id"]] for c in units if acc[c["id"]] is not None]
            pool = [c for c in units if acc[c["id"]] is not None and acc[c["id"]] <= 1.1 * min(known)] if known \
                else units
        for c in units:
            if c not in pool:
                a = acc[c["id"]]
                rejected.append((c, f"points to {a:.3g}° (need {need:.3g}°)" if a is not None else
                                 "does not publish its pointing accuracy"))
        ranked = rank(pool, w, lambda c: None if acc[c["id"]] is None else -acc[c["id"]], _fit_extra(size))
        flags = [] if meets else [f"no unit in the catalog is published to reach {need:.3g}°"]
        out["adcs"] = pick("adcs", ranked, f"An integrated unit with a star tracker, because {why}.", rejected,
                           need=f"{need:.3g}° pointing" if need is not None else "", flags=flags)
        for s in ("wheels", "magnetorquer", "star_tracker", "sun_sensor"):
            out[s] = none_needed(s, "Inside the integrated attitude unit.")
        return out
    out["adcs"] = none_needed("adcs", f"Not needed: {why}.")
    out["star_tracker"] = none_needed("star_tracker", f"Not needed: {why}.")
    if cls == "medium":
        wheels, rejected = _split_fit(K.by_category("reaction_wheel"), size)
        hm = {c["id"]: P._largest(K.perf(c, "momentum_mNms")) for c in wheels}
        ok = [c for c in wheels if h_need is None or (hm[c["id"]] or 0) >= h_need]
        ranked = rank(ok or wheels, w, lambda c: hm[c["id"]], _fit_extra(size))
        out["wheels"] = pick("wheels", ranked, f"Three wheels (one per axis) hold the attitude, because {why}.",
                             rejected, qty=3, need=f"{h_need:.2f} mN·m·s each" if h_need else "")
    else:
        out["wheels"] = none_needed("wheels", f"Not needed: {why}.")
    mtq, rejected = _split_fit(K.by_category("magnetorquer"), size)

    def axes(c):
        return int(P._largest(K.perf(c, "axes")) or 1)
    ranked = rank(mtq, w, lambda c: P._largest(K.perf(c, "dipole_Am2")), _fit_extra(size))
    q = 3 // axes(ranked[0][1]) if ranked else 1
    out["magnetorquer"] = pick("magnetorquer", ranked, "Magnetorquers detumble the satellite after deployment and "
                               "unload the wheels.", rejected, qty=max(q, 1), need="three axes")
    sens = K.by_category("sun_sensor")
    ranked = rank(sens, w, lambda c: -(P._largest(K.perf(c, "accuracy_deg")) or 99.0))
    n = sun_sensor_count(ranked[0][1]) if ranked else 1
    out["sun_sensor"] = pick("sun_sensor", ranked, f"{n} sensors so the Sun is seen from any attitude (field of view; "
                             "ASSUMED no overlap losses).", qty=n, need="the Sun from any attitude")
    return out


def pick_gnss(ctx: dict) -> dict:
    req = ctx["req"]
    if req.get("mission.type") != "earth_observation" and req.get("payload.pointing") != "nadir":
        return none_needed("gnss", "Not needed: no images to locate on the ground (ground tracking gives the orbit).")
    cands, rejected = _split_fit(K.by_category("gnss"), ctx["size"])
    keep, flags = [], []
    for c in cands:
        v = velocity_limit_ms(c)
        text = str(K.perf(c, "max_altitude_or_velocity_limits") or "").lower()
        if v is not None and v < 8000.0 and "no cocom" not in text:
            rejected.append((c, f"velocity limited to {v:g} m/s (orbit is about 7.6 km/s)"))
            continue
        if v is not None and v < 8000.0:
            flags.append(f"{name(c)}: its standard receiver is limited to {v:g} m/s; confirm the space version")
        keep.append(c)
    ranked = rank(keep, weights(ctx["prefs"]), None, _fit_extra(ctx["size"]))
    return pick("gnss", ranked, "Locates the images on the ground and times them.", rejected,
                need="position and time in orbit", flags=[f for f in flags if ranked and ranked[0][1]["product"] in f])


def pick_obc(ctx: dict) -> dict:
    """The computer that connects directly to most of the selected parts (their data interfaces; a camera's image
    interface counts double), then by the priorities."""
    cands, rejected = _split_fit(K.by_category("obc"), ctx["size"])
    heavy = bool(ctx["req"].get("data.onboard_processing"))
    w = weights(ctx["prefs"])
    if heavy:
        w["performance"] = 1.0
    parts = [c for c in ctx.get("parts", []) if ifaces(c)]

    def extra(c):
        e = _fit_extra(ctx["size"])(c)
        mine = ifaces(c)
        if parts:
            links = [1.0 if ifaces(p) & mine else 0.0 for p in parts]
            fast = [1.0 if ifaces(p, "data") & mine else 0.0 for p in parts if ifaces(p, "data")]
            e["links"] = ((sum(links) + 2 * sum(fast)) / (len(links) + 2 * len(fast)), 2.0)
        return e
    ranked = rank(cands, w, (lambda c: P._largest(K.perf(c, "clock_mhz"))) if heavy else None, extra)
    why = ("A strong processor for on-board image processing." if heavy else
           "Runs the satellite: commands, telemetry and the payload schedule.")
    return pick("obc", ranked, why, rejected, need="on-board processing" if heavy else "")


def pick_structure(ctx: dict) -> dict:
    size = ctx["size"]
    def size_of(c):
        return P._largest(K.perf(c, "size_u"))
    cands = [c for c in K.by_category("structure") if size_of(c) == float(size)]
    others = [(c, f"a {size_of(c):g}U structure" if size_of(c) else "size not published")
              for c in K.by_category("structure") if c not in cands]
    w = weights(ctx["prefs"])
    w["data"] = 2.0                                      # a structure with a published mass first
    w["packaging"] = 0.0                                 # every frame of a size has the same envelope
    ranked = rank(cands, w)
    why = f"The {S.label(size)} frame." if ranked else f"The catalog has no {S.label(size)} structure."
    return pick("structure", ranked, why, others, need=S.size_note(size))


def _uhf_band_ok(c: dict, licence: str) -> bool:
    f = K.perf_field(c, "frequency_mhz").get("value")
    ranges = f if isinstance(f, list) else [f]
    want = {"amateur": (435.0, 438.0), "commercial": (400.0, 403.0)}.get(licence)
    if want is None:
        return True
    return any(isinstance(r, dict) and r.get("min") is not None and r.get("max") is not None
               and float(r["min"]) <= want[1] and float(r["max"]) >= want[0] for r in ranges)


def pick_radio_ttc(ctx: dict) -> dict:
    licence = ctx["req"].get("comms.licence") or "unsure"
    cands, rejected = _split_fit([c for c in K.by_category("radio") if "uhf" in P.band(c)], ctx["size"])
    keep = []
    for c in cands:
        if _uhf_band_ok(c, licence):
            keep.append(c)
        else:
            rejected.append((c, f"no {licence} UHF band"))
    qty = 2 if ctx["prefs"]["reliability_cost"] >= 0.34 or ctx["req"].get("mission.reliability") != "single" else 1
    ranked = rank(keep, weights(ctx["prefs"]), lambda c: P.data_rate_bps(c)[0], _fit_extra(ctx["size"]))
    why = ("Commands and telemetry on UHF" + (f" in the {licence} band" if licence != "unsure" else "") + "." +
           (" Two, so one failure does not lose the satellite." if qty == 2 else ""))
    return pick("radio_ttc", ranked, why, rejected, qty=qty, need="UHF commands and telemetry")


def pick_antenna(ctx: dict, slot: str, band: str) -> dict:
    cands = [c for c in K.by_category("antenna") if band in P.band(c)]
    others = [(c, f"not {band.upper()}") for c in K.by_category("antenna") if c not in cands]
    ranked = rank(cands, weights(ctx["prefs"]), lambda c: P.gain_dbi(c), _fit_extra(ctx["size"]))
    return pick(slot, ranked, f"The {band.upper()} antenna.", others, need=f"{band.upper()} antenna")


def pick_radio_data(ctx: dict, band: str) -> dict:
    cands, rejected = _split_fit([c for c in K.by_category("radio") if band in P.band(c)], ctx["size"])
    w = weights(ctx["prefs"])
    w["performance"] = max(w["performance"], 0.8)
    ranked = rank(cands, w, lambda c: P.data_rate_bps(c)[0], _fit_extra(ctx["size"]))
    return pick("radio_data", ranked, f"An {band.upper()}-band downlink for the image data.", rejected,
                need=f"{band.upper()}-band downlink")


def pick_eps(ctx: dict) -> dict:
    size = ctx["size"]
    cands, rejected = _split_fit(K.by_category("eps"), size)
    match = ctx.get("voltage_match")                  # callable(c) -> share of the parts' supplies it provides

    def extra(c):
        e = _fit_extra(size)(c)
        if match is not None:
            e["voltages"] = (match(c), 1.5)
        return e
    ranked = rank(cands, weights(ctx["prefs"]), None, extra)
    return pick("eps", ranked, "Distributes and regulates the power for every part.", rejected,
                need="the supply voltages of the selected parts")


def pick_battery(ctx: dict, need_wh: float | None, eps: dict | None) -> dict:
    cands, rejected = _split_fit(K.by_category("battery"), ctx["size"])
    cap = {c["id"]: P._largest(K.perf(c, "capacity_wh")) for c in cands}
    ok = [c for c in cands if need_wh is None or (cap[c["id"]] or 0.0) >= need_wh]
    for c in cands:
        if c not in ok:
            rejected.append((c, f"{cap[c['id']] or '?'} Wh, less than the {need_wh:.1f} Wh needed"))
    maker = eps["manufacturer"] if eps else None

    def extra(c):
        e = _fit_extra(ctx["size"])(c)
        e["family"] = (1.0 if maker and c["manufacturer"] == maker else 0.0, 1.0)
        return e
    w = weights(ctx["prefs"])
    w["performance"] = 0.2
    ranked = rank(ok or cands, w, lambda c: -(cap[c["id"]] or 1e9), extra)
    flags = [] if ok else [f"no battery in the catalog stores {need_wh:.1f} Wh: use two packs or cut the eclipse load"]
    return pick("battery", ranked, f"Stores the {need_wh:.1f} Wh the eclipse needs." if need_wh else
                "Stores energy for the eclipse.", rejected, need=f"{need_wh:.1f} Wh" if need_wh else "", flags=flags)


def body_faces(size) -> int:
    """How many 3U-face body panels the long faces hold: one per 100 mm face, two side by side on a 226.3 mm face
    (ASSUMED panel width ≤ 100 mm); none below 3U (a 3U panel is too long)."""
    if size < 3:
        return 0
    a, b, _ = S.outer(size)
    return sum(2 if d > 200 else 1 for d in (a, a, b, b))


def solar_options(size) -> tuple[list, list]:
    """(body panels, deployable panels) of the catalog for this size, with a published power."""
    body, dep = [], []
    for c in K.by_category("solar_panel"):
        if K.perf(c, "power_w") is None:
            continue
        deployable = str(K.perf(c, "deployable") or "").lower().startswith("y")
        if deployable and size_ok(c, size):
            dep.append(c)
        elif not deployable and size >= 3:
            body.append(c)
    return body, dep


def pick_solar(ctx: dict, margin_of) -> dict:
    """Body panels first (as many as the faces hold), then deployable pairs, until the energy margin reaches the
    design margin. margin_of(items) -> the worst-day margin (%) for a panel set, or None."""
    size = ctx["size"]
    target = float(ctx.get("margin_target_pct") or 0.0)
    body, dep = solar_options(size)
    w = weights(ctx["prefs"])
    rb = rank(body, w, lambda c: float(K.perf(c, "power_w")))
    rd = rank(dep, w, lambda c: float(K.perf(c, "power_w")))
    n_faces = body_faces(size)
    sets = [[(rb[0][1], n)] for n in range(1, n_faces + 1)] if rb else []
    if rd:
        base = [(rb[0][1], n_faces)] if rb and n_faces else []
        sets += [base + [(rd[0][1], k)] for k in (2, 4)]
    tried = [(items, margin_of(items)) for items in sets]
    best = next((items for items, m in tried if m is not None and m >= target), None)
    flags = []
    if best is None:
        positive = [items for items, m in tried if m is not None and m >= 0]
        best = positive[0] if positive else (tried[-1][0] if tried else [])
        if positive:
            flags.append(f"the catalog's panels give a positive margin but not the {target:g} % design margin for "
                         "this size")
        elif tried:
            flags.append("the catalog's panels cannot cover the loads for this size: reduce the duty cycles, choose "
                         "a larger size or add panels")
    why = ("Body panels on the long faces" + (" plus deployable wings" if any(c in dep for c, _ in best) else "") +
           f": the fewest that reach the {target:g} % design margin on the worst day ({n_faces} faces hold body "
           "panels).")
    rejected = [(c, "no published power") for c in K.by_category("solar_panel") if K.perf(c, "power_w") is None]
    rejected += [(c, f"made for {', '.join(f'{lo:g}–{hi:g}U' for lo, hi in stated_sizes(c.get('fits')))}")
                 for c in K.by_category("solar_panel") if K.perf(c, "power_w") is not None and c not in body + dep]
    alts = [{"id": s[1]["id"], "name": name(s[1]), "score": round(s[0], 3), "reason": "ranked lower"}
            for s in (rb[1:] + rd[1:])]
    alts += [{"id": c["id"], "name": name(c), "score": None, "reason": r} for c, r in rejected]
    return {"slot": "solar", "label": SLOT["solar"].label, "items": best,
            "status": "recommended" if best else "missing",
            "why": why if best else f"No solar panel in the catalog fits a {S.label(size)}.",
            "need": f"a {target:g} % energy margin", "alternatives": alts, "flags": flags}


def pick_propulsion(ctx: dict, need_dv: float | None, why: str) -> dict:
    if not need_dv:
        return none_needed("propulsion", why)
    cands, rejected = _split_fit(K.by_category("propulsion"), ctx["size"])
    m0 = ctx.get("mass_kg") or 10.0
    dv = {c["id"]: thruster_dv(c, m0) for c in cands}
    ok = [c for c in cands if dv[c["id"]][0] is not None and dv[c["id"]][0] >= need_dv and dv[c["id"]][2]]
    unsure = [c for c in cands if c not in ok and dv[c["id"]][0] is not None and dv[c["id"]][0] >= need_dv]
    for c in cands:
        if c not in ok and c not in unsure:
            d = dv[c["id"]][0]
            rejected.append((c, f"Δv {d:.0f} m/s, less than {need_dv:.0f} m/s" if d is not None else
                             "Δv not published"))
    # thrusters the catalog's fully published EPS boards can supply directly (regulated outputs)
    fixed = {v for e in K.by_category("eps") if not unpublished(e) for v in eps_outputs(e)[0]}

    def powered(c):
        singles, ranges = volt_values(supply_text(c))
        hits = [any(abs(v - f) <= 0.05 * v for f in fixed) for v in singles] + \
               [any(lo <= f <= hi for f in fixed) for lo, hi in ranges]
        return {"supply": (1.0 if hits and all(hits) else 0.0, 1.5)}
    for c in unsure:
        rejected.append((c, f"{dv[c['id']][1]}: not comparable for this mass"))
    pool = ok or unsure
    ranked = rank(pool, weights(ctx["prefs"]), lambda c: dv[c["id"]][0] if dv[c["id"]][2] else None,
                  lambda c: {**_fit_extra(ctx["size"])(c), **powered(c)})
    flags = [] if ok else ([f"only a maker's Δv for an unstated mass suggests {need_dv:.0f} m/s is reachable"]
                           if unsure else [f"no thruster in the catalog gives {need_dv:.0f} m/s for this mass"])
    return pick("propulsion", ranked, why, [r for r in rejected if r[0] not in pool], need=f"{need_dv:.0f} m/s",
                flags=flags)
