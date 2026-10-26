"""The CubeSat Builder's component catalog: real, commercially available CubeSat hardware.

data/*.json were compiled on 2026-10-25 from the manufacturers' own pages and datasheets (read-only web research):
every value cites a source of its entry (`sources`, with URL and access date); a value that is not published is
null — never estimated. Prices appear only where publicly listed ("kind": "listed"); everything else is
"quote". CAD availability is recorded as found ("public" link, "registration", "on request", "unknown"); nothing was
downloaded.

Power fields as the entries hold them: `typical` the normal operating draw (for radios: idle / receive), `peak` the
largest stated draw (for radios: transmit), `standby` an idle mode when published separately.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

DATA = Path(__file__).resolve().parent / "data"
CATEGORIES = {
    "camera": "Camera / optical payload", "adcs_unit": "Integrated ADCS", "reaction_wheel": "Reaction wheel",
    "magnetorquer": "Magnetorquer", "star_tracker": "Star tracker", "sun_sensor": "Sun sensor", "eps": "EPS / power "
    "distribution", "battery": "Battery", "solar_panel": "Solar panel", "radio": "Radio", "antenna": "Antenna",
    "gnss": "GNSS receiver", "obc": "On-board computer", "structure": "Structure", "propulsion": "Propulsion",
    "thermal": "Thermal",
}


@lru_cache(maxsize=1)
def _load() -> tuple:
    out = []
    for p in sorted(DATA.glob("*.json")):
        for c in json.loads(p.read_text(encoding="utf-8")):
            c = dict(c)
            c["_file"] = p.name
            out.append(c)
    return tuple(out)


def components() -> list[dict]:
    return list(_load())


def by_id(cid: str) -> dict | None:
    return next((c for c in _load() if c["id"] == cid), None)


def by_category(cat: str) -> list[dict]:
    return [c for c in _load() if c["category"] == cat]


# ---------------------------------------------------------------------------------------------- accessors
def _num(x):
    try:
        return None if x is None else float(x)
    except (TypeError, ValueError):
        return None


def mass_kg(c: dict) -> float | None:
    return _num((c.get("mass_kg") or {}).get("value"))


def dims_mm(c: dict) -> tuple | None:
    d = c.get("dimensions_mm") or {}
    v = tuple(_num(d.get(k)) for k in "xyz")
    return None if any(x is None for x in v) else v


def volume_cm3(c: dict) -> float | None:
    d = dims_mm(c)
    return None if d is None else d[0] * d[1] * d[2] / 1000.0


def power_w(c: dict, kind: str = "typical") -> float | None:
    return _num((c.get("power_w") or {}).get(kind))


def perf(c: dict, key: str):
    """A performance value (number, text, list or dict as published), or None."""
    f = (c.get("performance") or {}).get(key)
    return f.get("value") if isinstance(f, dict) else f


def perf_field(c: dict, key: str) -> dict:
    f = (c.get("performance") or {}).get(key)
    return f if isinstance(f, dict) else {"value": f}


def price(c: dict) -> dict:
    p = c.get("price") or {}
    return {"value": _num(p.get("value")), "currency": p.get("currency"), "kind": p.get("kind") or "quote",
            "note": p.get("note") or ""}


def temp_range(c: dict) -> tuple | None:
    t = c.get("operating_temp_c") or {}
    lo, hi = _num(t.get("min")), _num(t.get("max"))
    return None if lo is None or hi is None else (lo, hi)


def data_interfaces(c: dict) -> list[str]:
    return [str(x) for x in ((c.get("interfaces") or {}).get("data") or [])]


def voltage_text(c: dict) -> str | None:
    v = (c.get("supply_voltage_v") or {}).get("value")
    return None if v in (None, "") else str(v)


def source_of(c: dict, field: str) -> dict | None:
    """The source record a top-level field cites (dimensions_mm, mass_kg, …)."""
    f = c.get(field) or {}
    s = f.get("source") if isinstance(f, dict) else None
    return (c.get("sources") or {}).get(s) if s else None


def summary(c: dict) -> dict:
    """The catalog entry as the app lists it (the full record is available by id)."""
    pr = price(c)
    return {"id": c["id"], "category": c["category"], "category_name": CATEGORIES.get(c["category"], c["category"]),
            "manufacturer": c["manufacturer"], "product": c["product"], "description": c.get("description"),
            "fits": c.get("fits"), "mass_kg": mass_kg(c), "dims_mm": dims_mm(c), "power_w": {k: power_w(c, k) for k in (
                "typical", "peak", "standby")}, "price": pr, "cad": (c.get("cad") or {}).get("available", "unknown"),
            "datasheet_url": c.get("datasheet_url"), "url": next(iter((c.get("sources") or {}).values()), {}).get("url")}


def validate() -> list[str]:
    """Problems in the catalog data (an empty list when every non-empty value cites a listed source)."""
    problems = []
    seen = set()
    for c in _load():
        cid = c.get("id")
        if cid in seen:
            problems.append(f"duplicate id {cid}")
        seen.add(cid)
        if c.get("category") not in CATEGORIES:
            problems.append(f"{cid}: unknown category {c.get('category')}")
        sources = c.get("sources") or {}
        for s, d in sources.items():
            if not d.get("url") or not d.get("accessed"):
                problems.append(f"{cid}: source {s} lacks a url or an access date")
        fields = {k: c.get(k) for k in ("dimensions_mm", "mass_kg", "power_w", "supply_voltage_v", "interfaces",
                                         "operating_temp_c", "price", "availability", "cad")}
        fields.update({f"performance.{k}": v for k, v in (c.get("performance") or {}).items()})
        for name, f in fields.items():
            if not isinstance(f, dict):
                continue
            if name == "price":
                vals = [f.get("value")]
            elif name == "cad":
                vals = [f.get("url"), None if f.get("available") == "unknown" else f.get("available")]
            elif name == "availability":
                vals = [f.get("text")]
            else:
                vals = [v for k, v in f.items() if k not in ("source", "note", "unit", "condition")]
            if any(v not in (None, [], "", {}) for v in vals) and f.get("source") not in sources:
                problems.append(f"{cid}: {name} has a value without a listed source")
    return problems
