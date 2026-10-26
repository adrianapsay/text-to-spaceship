"""The traceable result of one Builder calculation.

A Calc is a value with its unit, the equation it came from (plain text), its inputs (each with its value, unit and
where it came from), the assumptions it makes, the sources it rests on (refs.REFS keys) and its fidelity:
"conceptual" (rough sizing, simplified physics) or "preliminary" (traceable equation on verified data). A Calc that
cannot be computed carries value None and `missing` says what is needed.
"""
from __future__ import annotations


def calc(cid: str, label: str, value, unit: str | None, equation: str = "", inputs: dict | None = None,
         assumptions: list | None = None, refs: list | None = None, fidelity: str = "conceptual",
         explain: str = "", missing: str | None = None, extra: dict | None = None) -> dict:
    """One calculation result (JSON-ready)."""
    if fidelity not in ("conceptual", "preliminary"):
        raise ValueError(fidelity)
    v = value
    if isinstance(v, float):
        v = float(f"{v:.6g}")
    return {"id": cid, "label": label, "value": v, "unit": unit, "equation": equation,
            "inputs": inputs or {}, "assumptions": list(assumptions or []), "refs": list(refs or []),
            "fidelity": fidelity, "explain": explain, "missing": missing, **(extra or {})}


def inp(value, unit: str | None, source: str) -> dict:
    """An input of a Calc: its value, unit and where it came from (a requirement, another calc, a constant…)."""
    v = value
    if isinstance(v, float):
        v = float(f"{v:.6g}")
    return {"value": v, "unit": unit, "source": source}


def missing(cid: str, label: str, unit: str | None, what: str, explain: str = "") -> dict:
    return calc(cid, label, None, unit, explain=explain, missing=what)
