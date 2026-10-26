"""Radio link budget and daily data return (conceptual).

Eb/N0 = EIRP − L_fs − L_other + G/T − k − 10·log10(R), with EIRP from the selected radio's largest stated RF power
and the selected antenna's gain, L_fs the free-space loss at the longest range of a pass (the station's elevation
mask), and the ground station's G/T computed from an ASSUMED antenna and system noise temperature per band. The data
rate the link closes at with a 3 dB margin over uncoded BPSK's 9.6 dB (BER 1e-5), limited by the radio's own
largest rate, times the contact time per day and an ASSUMED usable fraction, gives the daily data return.
"""
from __future__ import annotations

import math

from ..catalog import parse as P
from . import refs as R
from .calc import calc, inp, missing

LINE_LOSS_DB = 1.0                  # satellite cable and connector loss (ASSUMED)
OTHER_LOSS_DB = 3.0                 # atmosphere, polarisation and pointing together (ASSUMED)
LINK_MARGIN_DB = 3.0                # margin kept over the required Eb/N0 (ASSUMED)
CONTACT_USE = 0.8                   # share of each pass usable for data (acquisition, overheads; ASSUMED)
# ground stations per band (ASSUMED): antenna gain (computed for dishes) and system noise temperature
GROUND = {"uhf": {"name": "UHF Yagi antenna", "gain_dbi": 14.0, "tsys_k": 500.0},
          "vhf": {"name": "VHF Yagi antenna", "gain_dbi": 12.0, "tsys_k": 1000.0},
          "s": {"name": "3 m dish", "dish_m": 3.0, "eff": 0.55, "tsys_k": 150.0},
          "x": {"name": "3.7 m dish", "dish_m": 3.7, "eff": 0.55, "tsys_k": 150.0}}


def ground_gt(band: str, f_mhz: float) -> tuple[float, str]:
    g = GROUND[band]
    if "dish_m" in g:
        lam = R.C_LIGHT / (f_mhz * 1e6)
        gain = 10 * math.log10(g["eff"] * (math.pi * g["dish_m"] / lam) ** 2)
        what = f"{g['name']}, efficiency {g['eff']}, {gain:.1f} dBi"
    else:
        gain = g["gain_dbi"]
        what = f"{g['name']}, {gain:g} dBi"
    return gain - 10 * math.log10(g["tsys_k"]), f"{what}, T_sys {g['tsys_k']:g} K (ASSUMED)"


def link_calcs(ctx: dict, radio_slot: str, antenna_slot: str, label: str) -> dict:
    """The downlink of one radio/antenna pair. ctx: passes (max_range_km, minutes_per_day), sel."""
    cid = f"comms.{radio_slot}"
    sel = ctx["sel"]
    r = (sel.get(radio_slot) or [None])[0]
    a = (sel.get(antenna_slot) or [None])[0]
    if r is None:
        return {cid: missing(cid, label, "Mbit/day", f"select a radio ({radio_slot})")}
    radio = r[0]
    bands = P.band(radio) or {"uhf"}
    band = "x" if "x" in bands else "s" if "s" in bands else "uhf" if "uhf" in bands else "vhf"
    f = P.frequency_mhz(radio, "tx")
    p = P.rf_power_w(radio)
    rate, rate_note = P.data_rate_bps(radio)
    if f is None or p is None:
        return {cid: missing(cid, label, "Mbit/day", f"{radio['product']} lacks a published frequency or RF power")}
    gain = P.gain_dbi(a[0], "tx") if a is not None else None
    gain_src = f"{a[0]['product']} (catalog)" if gain is not None else "0 dBi (no antenna gain published: ASSUMED)"
    gain = gain if gain is not None else 0.0
    passes = ctx.get("passes") or {}
    d_km = passes.get("max_range_km")
    if d_km is None:
        return {cid: missing(cid, label, "Mbit/day", "no passes over the ground station in the simulated days")}
    eirp = 10 * math.log10(p) - LINE_LOSS_DB + gain
    lfs = 20 * math.log10(4 * math.pi * d_km * 1e3 * f * 1e6 / R.C_LIGHT)
    gt, gt_src = ground_gt(band, f)
    c_n0 = eirp - lfs - OTHER_LOSS_DB + gt - R.K_DB
    need = R.EBN0_BPSK_1E5 + LINK_MARGIN_DB
    r_link = 10 ** ((c_n0 - need) / 10.0)
    r_use = min(r_link, rate) if rate else r_link
    minutes = passes.get("minutes_per_day") or 0.0
    per_day = r_use * minutes * 60.0 * CONTACT_USE
    margin_at_max = (c_n0 - 10 * math.log10(rate) - R.EBN0_BPSK_1E5) if rate else None
    return {cid: calc(
        cid, label, per_day / 1e6, "Mbit/day",
        "Eb/N0 = EIRP − L_fs − L + G/T − k − 10·log R; R_max at Eb/N0 = 9.6 + 3 dB; data = R · contact · use",
        {"P_tx": inp(p, "W", f"{radio['manufacturer']} {radio['product']}"),
         "G_tx": inp(gain, "dBi", gain_src), "f": inp(f, "MHz", "radio (transmit range centre)"),
         "range": inp(d_km, "km", "longest range of a pass (elevation mask)"),
         "L_fs": inp(lfs, "dB", "20·log10(4π·d·f/c)"), "G/T": inp(gt, "dB/K", gt_src),
         "k": inp(R.K_DB, "dBW/K/Hz", "Boltzmann"), "R_link": inp(r_link / 1e3, "kbit/s", "closes with 3 dB margin"),
         "R_radio": inp(rate / 1e3 if rate else None, "kbit/s", "radio's largest rate" + (f"; {rate_note}" if rate_note
                                                                                         else "")),
         "contact": inp(minutes, "min/day", "passes over the station")},
        [(f"cable loss {LINE_LOSS_DB} dB, other losses {OTHER_LOSS_DB} dB, margin {LINK_MARGIN_DB} dB, "
          f"{int(CONTACT_USE * 100)} % of each pass usable (ASSUMED)"),
         "uncoded BPSK at BER 1e-5 as the reference modulation (coding would improve it)"],
        refs=["nist_k", "bpsk"], extra={"band": band, "rate_bps": r_use, "margin_at_max_rate_db": margin_at_max,
                                        "link_limited": rate is not None and r_link < rate})}
