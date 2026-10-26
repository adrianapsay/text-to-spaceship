"""Earth-observation payload sizing (conceptual): what the requested pixel size needs (aperture, focal length),
what a selected camera gives at the design altitude, the daily data volume, the pointing it asks of the attitude
control, and a rough signal-to-noise estimate.

Assumptions are listed in each Calc. Representative wavelengths per band and the scene model are ASSUMED; camera
values come from the catalog (their sources) and scale with altitude for nadir viewing (GSD ∝ h).
"""
from __future__ import annotations

import math
import re

from .. import catalog as K
from . import orbit as O
from . import refs as R
from .calc import calc, inp, missing

# representative (longest) wavelength per requested band, m (ASSUMED)
BAND_WAVELENGTH = {"rgb": 550e-9, "pan": 550e-9, "red_edge": 720e-9, "nir": 850e-9, "swir": 1600e-9,
                   "tir": 10e-6, "hyper": 900e-9}
BAND_COUNT = {"rgb": 3, "pan": 1, "red_edge": 1, "nir": 1, "swir": 1, "tir": 1, "hyper": 32}
# camera band names that cover a requested band (case-insensitive substrings)
BAND_WORDS = {"rgb": ("rgb", "red", "green", "blue", "vnir", "visible", "multispectral"), "pan": ("pan",),
              "nir": ("nir", "near-infrared", "near infrared", "vnir"), "red_edge": ("red edge", "red-edge"),
              "swir": ("swir", "short-wave"), "tir": ("thermal", "lwir", "tir"), "hyper": ("hyperspectral", "hyper")}
APERTURE_FIT_MM = {1: 90.0, 1.5: 90.0, 2: 90.0, 3: 90.0, 6: 90.0, 12: 210.0}   # through the end face (ASSUMED)
SCENE_SQUARE = True                     # a scene is swath × swath (ASSUMED)
TARGET_OVERHEAD_S = 60.0                # slewing and settling per target (ASSUMED)
SNR_SCENE = {"reflectance": 0.3, "sun_elev_deg": 30.0, "atm_transmission": 0.8, "optics_transmission": 0.8,
             "qe": 0.5, "band_nm": 60.0, "read_noise_e": 10.0, "tdi_stages": 8}      # rough SNR model (ASSUMED)


def camera_at(cam: dict, alt_km: float) -> dict:
    """A camera's GSD and swath at alt_km, scaled from its reference altitude (nadir: both ∝ h)."""
    g = K.perf_field(cam, "gsd_m")
    s = K.perf_field(cam, "swath_km")
    out = {}
    if g.get("value") is not None and g.get("altitude_km"):
        out["gsd_m"] = float(g["value"]) * alt_km / float(g["altitude_km"])
    if s.get("value") is not None and s.get("altitude_km"):
        out["swath_km"] = float(s["value"]) * alt_km / float(s["altitude_km"])
    return out


BAND_CENTRE_NM = {"rgb": 550.0, "pan": 600.0, "red_edge": 720.0, "nir": 850.0, "swir": 1600.0, "tir": 10000.0}


def band_cover(cam: dict, wanted: list) -> dict:
    """{band: True | False | None} — whether the camera's published bands cover each requested band: True when a band
    name says so, False when the published wavelength range (e.g. "450-900 nm") leaves it out, None when the maker
    does not say (e.g. "6 x MS")."""
    bands = K.perf(cam, "bands") or []
    names = " ".join(str(b.get("name", b)) if isinstance(b, dict) else str(b) for b in bands).lower()
    if not names.strip():
        return dict.fromkeys(wanted)
    ranges = [(float(lo), float(hi)) for lo, hi in re.findall(r"(\d{3,5})\s*[-–]\s*(\d{3,5})\s*nm", names)]
    out = {}
    for b in wanted:
        if any(w in names for w in BAND_WORDS.get(b, (b,))):
            out[b] = True
        elif ranges and b in BAND_CENTRE_NM:
            out[b] = any(lo <= BAND_CENTRE_NM[b] <= hi for lo, hi in ranges)
        else:
            out[b] = None
    return out


def imaging_calcs(ctx: dict) -> dict:
    """ctx: alt_km, req (requirements values), size_u, camera (catalog entry or None), passes (orbit), period_s."""
    out = {}
    req = ctx["req"]
    h = ctx["alt_km"] * 1e3
    gsd = float(req.get("imaging.gsd_m") or 10.0)
    bands = list(req.get("imaging.bands") or ["rgb"])
    lam = max(BAND_WAVELENGTH.get(b, 550e-9) for b in bands)
    d_min = 1.22 * lam * h / gsd
    out["imaging.aperture_min"] = calc(
        "imaging.aperture_min", "Smallest aperture for the pixel size (diffraction)", d_min * 1e3, "mm",
        "D ≥ 1.22·λ·h / GSD (Rayleigh)",
        {"λ": inp(lam * 1e9, "nm", f"longest requested band ({', '.join(bands)}; ASSUMED wavelength)"),
         "h": inp(ctx["alt_km"], "km", "orbit"), "GSD": inp(gsd, "m", "your requirement")},
        ["representative band wavelengths (ASSUMED): visible 550 nm, NIR 850 nm, SWIR 1600 nm, thermal 10 µm"],
        fidelity="preliminary",
        explain="Light spreads out through a small opening; a sharper pixel needs a wider telescope.")
    fit = APERTURE_FIT_MM.get(ctx.get("size_u") or 3, 90.0)
    out["imaging.aperture_fit"] = calc(
        "imaging.aperture_fit", "Largest aperture that fits this CubeSat size", fit, "mm",
        "the end face of the size, less the structure (ASSUMED)",
        {"size": inp(ctx.get("size_u"), "U", "size recommendation")},
        ["about 90 mm through the 100 mm face up to 6U, about 210 mm for 12U (ASSUMED)",
         ("diffraction sets how sharp the image is, not the pixel size: a camera can have smaller pixels than its "
          "optics resolve (softer images)")],
        extra={"feasible": d_min * 1e3 <= fit},
        explain=(f"Optics that fit this size are diffraction-limited above {gsd:g} m at {lam * 1e9:.0f} nm: images "
                 "in that band are softer than the pixels." if d_min * 1e3 > fit else
                 "Optics that fit this size can resolve the requested pixel size."))
    v = math.sqrt(R.MU / O.semi_major(ctx["alt_km"]))
    vg = v * R.RE / O.semi_major(ctx["alt_km"])
    out["imaging.ground_speed"] = calc("imaging.ground_speed", "Ground track speed", vg / 1e3, "km/s",
                                       "v_g = v·R_E/a", {"v": inp(v / 1e3, "km/s", "orbit")}, refs=["wgs84"],
                                       fidelity="preliminary")
    cam = ctx.get("camera")
    if cam is None:
        out["imaging.camera_gsd"] = missing("imaging.camera_gsd", "Pixel size of the selected camera", "m",
                                            "select a camera")
        return out
    at = camera_at(cam, ctx["alt_km"])
    g_ref = K.perf_field(cam, "gsd_m")
    if "gsd_m" in at:
        out["imaging.camera_gsd"] = calc(
            "imaging.camera_gsd", f"Pixel size of the {cam['product']} at this altitude", at["gsd_m"], "m",
            "GSD = GSD_ref · h / h_ref (nadir)",
            {"GSD_ref": inp(g_ref["value"], "m", f"{cam['manufacturer']} (catalog)"),
             "h_ref": inp(g_ref["altitude_km"], "km", f"{cam['manufacturer']} (catalog)"),
             "h": inp(ctx["alt_km"], "km", "orbit")}, fidelity="preliminary",
            extra={"meets": at["gsd_m"] <= gsd * 1.0001},
            explain=("Meets the requested pixel size." if at["gsd_m"] <= gsd * 1.0001 else
                     f"Coarser than the requested {gsd:g} m."))
    else:
        out["imaging.camera_gsd"] = missing("imaging.camera_gsd", "Pixel size of the selected camera", "m",
                                            f"the {cam['product']} does not publish its GSD with an altitude")
    cover = band_cover(cam, bands)
    published = [str(b.get("name", b)) if isinstance(b, dict) else str(b) for b in (K.perf(cam, "bands") or [])]
    lacking = [b for b, ok in cover.items() if ok is False]
    out["imaging.bands"] = calc(
        "imaging.bands", f"Requested bands the {cam['product']} covers", sum(1 for v in cover.values() if v),
        f"of {len(bands)}", "the camera's published bands against yours",
        {"published": inp("; ".join(published) or "not published", None, f"{cam['manufacturer']} (catalog)"),
         "requested": inp(", ".join(bands), None, "your requirement")},
        ["band names matched by keyword (visible/VNIR covers colour; ASSUMED)"],
        extra={"cover": cover, "ok": None if None in cover.values() else not lacking},
        explain=("Covers every band you asked for." if not lacking and None not in cover.values() else
                 f"Does not cover {', '.join(lacking)}." if lacking else "The camera does not publish its bands."))
    swath = at.get("swath_km")
    gsd_c = at.get("gsd_m", gsd)
    if swath is not None:
        out["imaging.swath"] = calc("imaging.swath", "Swath width", swath, "km", "swath = swath_ref · h / h_ref",
                                    {"swath_ref": inp(K.perf_field(cam, "swath_km")["value"], "km", "catalog")},
                                    fidelity="preliminary")
    bits = float(K.perf(cam, "bit_depth") or 12)
    n_b = sum(BAND_COUNT.get(b, 1) for b in bands)
    comp = float(req.get("imaging.compression") or 2.0)
    if swath is not None:
        px = (swath * 1e3 / gsd_c) ** 2 if SCENE_SQUARE else 0
        scene_bits = px * n_b * bits / comp
        out["imaging.scene_size"] = calc(
            "imaging.scene_size", "Data per scene", scene_bits / 8e9, "GB",
            "bits = (swath/GSD)² · bands · bit depth / compression",
            {"swath": inp(swath, "km", "camera"), "GSD": inp(gsd_c, "m", "camera"), "bands": inp(n_b, None,
                                                                                                  "your bands"),
             "bit depth": inp(bits, "bit", "camera" if K.perf(cam, "bit_depth") else "ASSUMED 12"),
             "compression": inp(comp, ":1", "your requirement")},
            ["a scene is a square of one swath width (ASSUMED)"])
        need = req.get("imaging.need") or "targets"
        if need == "map":
            reg = req.get("target.region") or {}
            area = _box_area_km2(reg) if reg.get("lat_min") is not None else None
            if area is None:
                out["imaging.daily_volume"] = missing("imaging.daily_volume", "Data per day", "GB",
                                                      "a target region with a box to map")
                return out
            refresh = float(req.get("imaging.refresh_days") or 30.0)
            scenes = area / (swath * swath) / refresh
        else:
            scenes = float(req.get("imaging.targets_per_day") or 5.0)
            area = None
        vol = scenes * scene_bits / 8e9
        out["imaging.daily_volume"] = calc(
            "imaging.daily_volume", "Image data per day", vol, "GB",
            "volume = scenes per day · data per scene",
            {"scenes per day": inp(scenes, None, "map area / swath² / refresh days" if need == "map" else
                                   "your sites per day")},
            ["scenes are taken whole; no cloud screening on board"] + ([f"area mapped: {area:.0f} km² (box)"] if area
                                                                         else []),
            extra={"scenes_per_day": scenes})
        t_scene = swath * 1e3 / vg
        out["imaging.time_per_day"] = calc(
            "imaging.time_per_day", "Imaging time per day", scenes * (t_scene + TARGET_OVERHEAD_S) / 60.0, "min",
            "time = scenes · (swath/v_g + overhead)", {"overhead": inp(TARGET_OVERHEAD_S, "s",
                                                                       "slew and settle per scene (ASSUMED)")},
            extra={"scene_s": t_scene})
    # pointing the imaging asks for
    half = 0.25 * (swath if swath is not None else 10.0) * 1e3 / h
    out["imaging.pointing_req"] = calc(
        "imaging.pointing_req", "Pointing accuracy needed", math.degrees(half), "deg",
        "θ = (swath/4) / h: the site stays in the central half of the scene",
        {"swath": inp(swath, "km", "camera") if swath is not None else inp(10.0, "km", "ASSUMED")},
        ["the site must fall in the central half of the scene (ASSUMED)"])
    geo = float(req.get("imaging.geolocation_m") or 2.0 * gsd)
    out["imaging.knowledge_req"] = calc(
        "imaging.knowledge_req", "Attitude knowledge needed for geolocation", math.degrees(geo / h) * 3600, "arcsec",
        "θ = geolocation error / h", {"geolocation": inp(geo, "m", "your requirement or 2 pixels (ASSUMED)")},
        ["position error and timing error are neglected"])
    # rough SNR
    ap = K.perf(cam, "aperture_mm")
    fl = K.perf(cam, "focal_length_mm")
    pix = K.perf(cam, "pixel_um")
    if ap and fl and pix:
        s = SNR_SCENE
        lam0 = 550e-9
        L = R.SSI_550 * s["reflectance"] * math.sin(math.radians(s["sun_elev_deg"])) * s["atm_transmission"] / math.pi
        area_ap = math.pi * (float(ap) * 1e-3) ** 2 / 4.0
        omega = (float(pix) * 1e-6 / (float(fl) * 1e-3)) ** 2
        t_line = gsd_c / vg
        power = L * area_ap * omega * s["band_nm"] * s["optics_transmission"]
        electrons = power / (R.H_PLANCK * R.C_LIGHT / lam0) * s["qe"] * t_line * s["tdi_stages"]
        noise = math.sqrt(electrons + s["tdi_stages"] * s["read_noise_e"] ** 2)
        snr = electrons / noise
        goal = float(req.get("imaging.snr_min") or 100.0)
        out["imaging.snr"] = calc(
            "imaging.snr", "Signal-to-noise ratio (rough estimate)", snr, None,
            "S = (E_λ·ρ·sin(el)·τ_atm/π)·(π D²/4)·(p/f)²·Δλ·τ_opt·QE·t·N_tdi / (h c/λ); SNR = S/√(S + N·σ_read²)",
            {"D": inp(ap, "mm", "camera"), "f": inp(fl, "mm", "camera"), "p": inp(pix, "µm", "camera"),
             "E_λ": inp(R.SSI_550, "W/m²/nm", "TSIS-1 at 550 nm"), "t": inp(t_line * 1e3, "ms", "GSD / v_g")},
            [(f"scene: reflectance {s['reflectance']}, Sun {s['sun_elev_deg']:g}° high, atmosphere "
              f"{s['atm_transmission']}, optics {s['optics_transmission']}, QE {s['qe']}, band {s['band_nm']:g} nm, "
              f"read noise {s['read_noise_e']:g} e⁻, {s['tdi_stages']} TDI stages (all ASSUMED)")],
            refs=["tsis_ssi", "si"], extra={"goal": goal, "meets": snr >= goal},
            explain="A rough check only: real SNR depends on the scene, the band and the camera's own noise.")
    return out


def _box_area_km2(reg: dict) -> float:
    """Area of a lat/lon box on a sphere of radius R_E (km²)."""
    la0, la1 = math.radians(reg["lat_min"]), math.radians(reg["lat_max"])
    dlon = math.radians(reg["lon_max"] - reg["lon_min"])
    return (R.RE / 1e3) ** 2 * dlon * (math.sin(la1) - math.sin(la0))
