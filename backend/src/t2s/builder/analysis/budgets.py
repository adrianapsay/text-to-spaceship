"""Budgets of a Builder design (conceptual): mass, volume, cost and data.

* Mass: every selected part with its published mass (a part whose mass is not published is listed, never
  estimated), plus two allowances, both ASSUMED and named: harness and fasteners (5 % of the parts) and a design
  margin by fidelity (concept 20 %, preliminary 15 %, flight-intended 10 %). The CubeSat Design Specification's mass
  limit for the size is the check.
* Volume: the bounding boxes of the parts inside the structure (external hardware — solar panels, antennas, sun
  sensors — is counted in mass and power but not packed, and says so).
* Cost: listed prices only, totalled per currency (no exchange rates); every other part is "quote required".
* Data: the daily data against what the radios return per day.
"""
from __future__ import annotations

from .. import catalog as K
from . import refs as R
from .calc import calc, inp

HARNESS_PCT = 5.0
MARGIN_PCT = {"conceptual": 20.0, "preliminary": 15.0, "flight": 10.0}


def _mass(c: dict) -> float | None:
    return K.mass_kg(c)


def mass_budget(sel: dict, places: dict, size, fidelity: str) -> dict:
    rows, miss = [], []
    total = 0.0
    for slot, items in sel.items():
        for c, q in items:
            m = _mass(c)
            name = f"{c['manufacturer']} {c['product']}"
            if m is None:
                miss.append(name)
                rows.append({"slot": slot, "name": name, "qty": q, "each_kg": None, "kg": None,
                             "place": places.get(slot), "source": "not published"})
                continue
            total += m * q
            rows.append({"slot": slot, "name": name, "qty": q, "each_kg": m, "kg": m * q, "place": places.get(slot),
                         "source": "your answer (placeholder)" if c.get("_placeholder") else "catalog"})
    harness = total * HARNESS_PCT / 100.0
    margin_pct = MARGIN_PCT.get(fidelity, 20.0)
    dry = total + harness
    with_margin = dry * (1.0 + margin_pct / 100.0)
    limit = R.CDS_MASS_KG[size]
    return calc("budget.mass", "Mass budget", dry, "kg", "Σ parts + harness allowance; × (1 + margin) for the check",
                {"parts": inp(total, "kg", f"{len(rows) - len(miss)} parts with a published mass"),
                 "harness": inp(harness, "kg", f"{HARNESS_PCT:g} % of the parts (ASSUMED)"),
                 "margin": inp(margin_pct, "%", f"design margin at {fidelity} level (ASSUMED)"),
                 "limit": inp(limit, "kg", "CubeSat Design Specification Rev 14.1")},
                [f"harness and fasteners {HARNESS_PCT:g} % (ASSUMED)",
                 f"design margin {margin_pct:g} % for the {fidelity} level (ASSUMED)"] +
                ([f"not published (not counted): {', '.join(miss)}"] if miss else []), refs=["cds"],
                extra={"rows": rows, "parts_kg": total, "harness_kg": harness, "margin_pct": margin_pct,
                       "with_margin_kg": with_margin, "limit_kg": limit, "missing_items": miss,
                       "ok": with_margin <= limit and not miss},
                explain=(f"{dry:.2f} kg, {with_margin:.2f} kg with the design margin, against the {limit:g} kg "
                         f"limit." + (f" {len(miss)} part(s) have no published mass." if miss else "")))


def internal_volume_cm3(sel: dict, places: dict) -> tuple[float, list[str]]:
    vol, miss = 0.0, []
    for slot, items in sel.items():
        if places.get(slot) != "internal":
            continue
        for c, q in items:
            d = K.dims_mm(c)
            if d is None:
                miss.append(f"{c['manufacturer']} {c['product']}")
                continue
            vol += d[0] * d[1] * d[2] / 1000.0 * q
    return vol, miss


def cost_budget(sel: dict) -> dict:
    totals: dict[str, float] = {}
    rows, quotes = [], []
    for slot, items in sel.items():
        for c, q in items:
            if c.get("_placeholder"):
                continue
            p = K.price(c)
            name = f"{c['manufacturer']} {c['product']}"
            if p["value"] is None:
                quotes.append(name)
                rows.append({"slot": slot, "name": name, "qty": q, "price": None, "currency": None,
                             "kind": "quote", "note": p["note"]})
                continue
            totals[p["currency"]] = totals.get(p["currency"], 0.0) + p["value"] * q
            rows.append({"slot": slot, "name": name, "qty": q, "price": p["value"], "currency": p["currency"],
                         "kind": "listed", "note": p["note"]})
    text = "; ".join(f"{v:,.0f} {k}" for k, v in sorted(totals.items())) or "none listed"
    return calc("budget.cost", "Listed hardware prices", text, None, "Σ listed prices (per currency)",
                {k: inp(v, k, "listed prices") for k, v in totals.items()},
                [("listed prices only, as published (VAT, shipping, options and minimum orders vary — see each "
                  "note); no exchange rates applied; no estimates for parts that need a quote")],
                extra={"totals": totals, "rows": rows, "quotes": quotes, "text": text},
                explain=f"Listed: {text}. {len(quotes)} part(s) need a quote from the maker.")


def data_budget(need_mbit_day: float | None, returns: dict) -> dict | None:
    if need_mbit_day is None:
        return None
    got = sum(v for v in returns.values() if v is not None)
    pct = 100.0 * got / need_mbit_day if need_mbit_day > 0 else 100.0
    return calc("budget.data", "Daily data returned by the downlink", pct, "%", "returned / produced",
                {"produced": inp(need_mbit_day, "Mbit/day", "payload data per day"),
                 **{k: inp(v, "Mbit/day", "link budget") for k, v in returns.items()}},
                extra={"ok": got >= need_mbit_day, "returned_mbit_day": got, "need_mbit_day": need_mbit_day},
                explain=("The radios return all the data each day." if got >= need_mbit_day else
                         "The radios cannot return all the data: a faster radio, more ground stations, or fewer "
                         "images."))
