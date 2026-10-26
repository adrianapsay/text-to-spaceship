"""Reading the catalog's published values, which come in the shapes the manufacturers use: a number, a {min, max}
range, a list of labelled entries, or text ("±10 (2 axes); ±25 (3rd axis)"), each with its unit. Every reader returns
a number in the stated SI-ish unit or None — it never guesses a value that is not there."""
from __future__ import annotations

import re

from . import perf_field

_NUM = re.compile(r"[-+]?\d+(?:[.,]\d+)?")


def numbers(text) -> list[float]:
    """Every number in a text (commas as decimal points when between digits)."""
    if text is None:
        return []
    return [float(x.replace(",", ".")) for x in _NUM.findall(str(text))]


def _largest(v, key: str | None = None) -> float | None:
    """The largest number in a value: a number, a {min, max}, a list of numbers or of dicts (key), or text."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, dict):
        if key and v.get(key) is not None:
            return _largest(v[key])
        for k in ("max", "value"):
            if v.get(k) is not None:
                return _largest(v[k])
        nums = [x for x in (_largest(x) for x in v.values()) if x is not None]
        return max(nums) if nums else None
    if isinstance(v, list):
        nums = [x for x in (_largest(x, key) for x in v) if x is not None]
        return max(nums) if nums else None
    nums = numbers(v)
    return max(nums) if nums else None


def _scale(unit: str | None, table: dict) -> float:
    u = (unit or "").strip().lower()
    for k, f in table.items():
        if u.startswith(k):
            return f
    return 1.0


def frequency_mhz(c: dict, prefer: str = "tx") -> float | None:
    """Centre of the transmit range (or of the first range) in MHz."""
    f = perf_field(c, "frequency_mhz")
    v, unit = f.get("value"), f.get("unit")
    k = 1000.0 if (unit or "").strip().lower().startswith("ghz") else 1.0
    if v is None:
        return None
    ranges = v if isinstance(v, list) else [v]
    pick = next((r for r in ranges if isinstance(r, dict) and prefer in str(r.get("label", "")).lower()), ranges[0])
    if isinstance(pick, dict) and pick.get("min") is not None and pick.get("max") is not None:
        return k * 0.5 * (float(pick["min"]) + float(pick["max"]))
    x = _largest(pick)
    return None if x is None else k * x


def rf_power_w(c: dict) -> float | None:
    """The largest stated RF output power, in W."""
    f = perf_field(c, "rf_output_power")
    v, unit = f.get("value"), (f.get("unit") or "").lower()
    x = _largest(v, "dbm")
    if x is None:
        return None
    if "dbm" in unit or (isinstance(v, list) and v and isinstance(v[0], dict) and "dbm" in v[0]):
        return 10 ** ((x - 30.0) / 10.0)
    if unit.startswith("mw"):
        return x / 1000.0
    return x                                                   # W


def data_rate_bps(c: dict) -> tuple[float | None, str]:
    """The largest stated data rate in bit/s, and a note (symbol rates are taken as bit rates: ASSUMED)."""
    f = perf_field(c, "data_rate")
    v, unit = f.get("value"), f.get("unit")
    if v is None:
        return None, ""
    note = ""
    if isinstance(v, list) and v and isinstance(v[0], dict):
        best = 0.0
        for e in v:
            if e.get("bps") is not None:
                best = max(best, float(e["bps"]))
            elif e.get("max_MBd") is not None:
                best = max(best, float(e["max_MBd"]) * 1e6)
                note = "a symbol rate taken as the bit rate (ASSUMED: one bit per symbol)"
            elif e.get("max_kBd") is not None:
                best = max(best, float(e["max_kBd"]) * 1e3)
                note = "a symbol rate taken as the bit rate (ASSUMED: one bit per symbol)"
        return (best or None), note
    x = _largest(v)
    if x is None:
        return None, ""
    k = _scale(unit, {"gbit": 1e9, "gbps": 1e9, "mbit": 1e6, "mbps": 1e6, "kbit": 1e3, "kbps": 1e3, "bps": 1.0,
                      "bit": 1.0})
    return x * k, note


def gain_dbi(c: dict, prefer: str = "tx") -> float | None:
    """The antenna's stated gain (dBi), the transmit entry when labelled."""
    f = perf_field(c, "gain_dbi")
    v = f.get("value")
    if v is None:
        return None
    if isinstance(v, list):
        pick = next((e for e in v if isinstance(e, dict) and prefer in str(e.get("label", "")).lower()), None)
        if pick is not None:
            return numbers(pick.get("dbi"))[0] if numbers(pick.get("dbi")) else None
        vals = [numbers(e.get("dbi"))[0] for e in v if isinstance(e, dict) and numbers(e.get("dbi"))]
        return max(vals) if vals else None
    n = numbers(v)
    return n[0] if n else None


def band(c: dict) -> set[str]:
    """Bands named by an entry: {"uhf", "vhf", "s", "x"}."""
    v = str(perf_field(c, "band").get("value") or "").lower()
    out = set()
    for b in ("uhf", "vhf"):
        if b in v:
            out.add(b)
    for b in ("s", "x"):
        if re.search(rf"(^|[^a-z]){b}(-band|[^a-z]|$)", v):
            out.add(b)
    return out


def angle_deg(c: dict, key: str) -> float | None:
    """The worst (largest) stated angle of a pointing figure, in degrees (arcsec/arcmin converted)."""
    f = perf_field(c, key)
    x = _largest(f.get("value"))
    if x is None:
        return None
    unit = (f.get("unit") or "").lower()
    if "arcsec" in unit or unit in ('"', "asec"):
        return x / 3600.0
    if "arcmin" in unit:
        return x / 60.0
    return x


def voltages(text) -> list[float]:
    """Voltages named in a text such as '3.3 V, 5 V, 12 V' (the numbers followed by V)."""
    if text is None:
        return []
    return [float(x.replace(",", ".")) for x in re.findall(r"(\d+(?:[.,]\d+)?)\s*V\b", str(text))]


def supply_range(text) -> tuple[float, float] | None:
    """A supply voltage text as a (lo, hi) range: '5' → (5, 5); '6-16' → (6, 16); '3.3/5' → (3.3, 5)."""
    nums = numbers(text)
    if not nums:
        return None
    return (min(nums), max(nums))
