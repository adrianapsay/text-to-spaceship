"""Bracket materials: one table for the FE check, the mass and the relative cost of a bracket inside `t2s.gd`.

Every value is a vendor minimum or typical value — NOT a design allowable. NASA-STD-6030 §6.3 requires a Material
Usage Agreement (part-agnostic and part-specific) before an AM material flies; flight use also needs build witness
coupons (research note docs/research/v2-bracket-loads-materials.md, caveats). Values not found in a source are
labelled ASSUMED.

* AlSi10Mg L-PBF, stress-relieved — the metal-AM default (and the contest's material).
* Ti-6Al-4V L-PBF, heat treated — the second AM choice (per bracket, WS4).
* 6061-T6 — machined cradles and tube-clamp bands (they were checked with AlSi10Mg values before).

`cost_factor` multiplies the relative cost model of `mfg.rules.bracket_cost` (ASSUMED relative units, no quotes):
no sourced price ratio between the alloys exists in this project, so every factor is 1.0 until a quote is available.
"""
from __future__ import annotations

ALLOWABLES = ("vendor minimum / typical values, not design allowables (NASA-STD-6030 §6.3 requires a Material Usage "
              "Agreement)")
_NOTE = "docs/research/v2-bracket-loads-materials.md §1 (Materials)"

MATERIALS: dict[str, dict] = {
    "AlSi10Mg": {
        "id": "AlSi10Mg", "name": "AlSi10Mg L-PBF stress-relieved (ASSUMED)", "process": "metal_am",
        "E_mpa": 65000.0, "nu": 0.33, "rho_t_mm3": 2.68e-9, "yield_mpa": 170.0, "ultimate_mpa": 280.0,
        "cost_factor": 1.0,
        "source": (f"{_NOTE}: lowest Z-direction stress-relieved values of the Renishaw, Gränges, EOS M290 and AddUp "
                   "data sheets — Fty 170 MPa, Ftu 280 MPa, 2.68 g/cm³; E 70 GPa nominal, the 65 GPa lower value "
                   "used (frequency); ν 0.33 typical"),
    },
    "Ti-6Al-4V": {
        "id": "Ti-6Al-4V", "name": "Ti-6Al-4V L-PBF heat-treated (ASSUMED)", "process": "metal_am",
        "E_mpa": 110000.0, "nu": 0.31, "rho_t_mm3": 4.41e-9, "yield_mpa": 860.0, "ultimate_mpa": 930.0,
        "cost_factor": 1.0,
        "source": ("EOS Titanium Ti64 400W material data sheet 07.2022 (EOS M 290 400W, heat treated 800 °C 4 h): "
                   "Rp0.2 min 860 MPa, Rm min 930 MPa (minimum values, ASTM F1472), density 4.41 g/cm³, E typ. "
                   "110 ± 15 GPa (the typical value; the AlSi10Mg entry uses its lowest value, so a Ti-6Al-4V f1 is "
                   "up to 8 % less conservative); ν 0.31 ASSUMED (not in the data sheet)"),
    },
    "6061-T6": {
        "id": "6061-T6", "name": "aluminium 6061-T6 machined (ASSUMED)", "process": "machined",
        "E_mpa": 68300.0, "nu": 0.33, "rho_t_mm3": 2.71e-9, "yield_mpa": 240.0, "ultimate_mpa": 290.0,
        "cost_factor": 1.0,
        "source": (f"{_NOTE}: ASTM B209M-14 Table 3 (sheet / T651 plate) — Fty 240 MPa, Ftu 290 MPa, 2.71 g/cm³, "
                   "E 68.3 GPa; ν 0.33 ASSUMED"),
    },
}
DEFAULT_AM = "AlSi10Mg"          # metal-AM brackets (and the contest)
MACHINED = "6061-T6"             # machined cradles and tube-clamp bands
FEA_KEYS = ("name", "E_mpa", "nu", "rho_t_mm3", "yield_mpa", "ultimate_mpa")


def material(key: str | None = None) -> dict:
    """The table entry (a copy) for `key` (an id such as "Ti-6Al-4V"; None: the AM default)."""
    k = key or DEFAULT_AM
    if k not in MATERIALS:
        raise KeyError(f"unknown bracket material {k!r} (known: {', '.join(MATERIALS)})")
    return dict(MATERIALS[k])


def fea_material(key: str | None = None) -> dict:
    """What the FE check and the domain use: name, E, ν, ρ (t/mm³), Fty, Ftu, plus the id and the allowables label."""
    m = material(key)
    return {**{k: m[k] for k in FEA_KEYS}, "id": m["id"], "allowables": ALLOWABLES}


def density_kg_m3(key: str | None = None) -> float:
    """Density for the mass of a bracket — the same number the FE check uses (t/mm³ × 1e12)."""
    return material(key)["rho_t_mm3"] * 1e12


def for_kind(kind: str, am_material: str | None = None) -> str:
    """Material id of a designed bracket: metal-AM brackets get the chosen AM material, machined cradles and clamp
    bands 6061-T6."""
    if kind == "metal_am":
        m = material(am_material)
        if m["process"] != "metal_am":
            raise ValueError(f"{m['id']} is not an AM material")
        return m["id"]
    return MACHINED
