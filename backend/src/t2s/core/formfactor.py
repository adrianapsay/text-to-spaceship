"""V2 CubeSat form factor (3U / 6U / 12U): the envelope and COM box every module uses.

Values from CDS Rev 14.1 (Cal Poly CP-CDS-R14.1, 2022; docs/research/v2-6u-12u-envelopes.md): rail envelope
3U 100 × 100 × 340.5 mm, 6U 226.3 × 100 × 366 mm, 12U 226.3 × 226.3 × 366 mm (the 226.3 mm axis is X); COM box
("shall") ±20/±20/±70, ±45/±20/±70, ±45/±45/±70 mm; mass ("note") 6, 12, 24 kg. The frame model (2 mm walls, solid
8.5 mm corner rails, no mid-face rails) is the 3U one applied to every size (ASSUMED).

The arrays below are shared: `set_form_factor` changes them IN PLACE, so every module that imported them (directly or
through stage2.ENVELOPE / metrics.ENCLOSURE_LO / ENCLOSURE_HI) sees the new size. Every process sets it: the app
from its settings, search workers from the context they receive, pool jobs through `call_with`.
"""
from __future__ import annotations

import os

import numpy as np

FORM_FACTORS = {
    "3U": {"envelope_mm": (100.0, 100.0, 340.5), "com_box_mm": (20.0, 20.0, 70.0), "mass_note_kg": 6.0,
           "drawing": "CDS-14-004"},
    "6U": {"envelope_mm": (226.3, 100.0, 366.0), "com_box_mm": (45.0, 20.0, 70.0), "mass_note_kg": 12.0,
           "drawing": "CDS-14-007"},
    "12U": {"envelope_mm": (226.3, 226.3, 366.0), "com_box_mm": (45.0, 45.0, 70.0), "mass_note_kg": 24.0,
            "drawing": "CDS-14-008"},
}
DEFAULT = "3U"

ENVELOPE = np.array(FORM_FACTORS[DEFAULT]["envelope_mm"], float)        # shared, changed in place
COM_BOX = np.array(FORM_FACTORS[DEFAULT]["com_box_mm"], float)
_current = [DEFAULT]


def current() -> str:
    return _current[0]


def info(name: str | None = None) -> dict:
    n = name or current()
    return {"name": n, **{k: list(v) if isinstance(v, tuple) else v for k, v in FORM_FACTORS[n].items()}}


def set_form_factor(name: str) -> str:
    """Make `name` the active form factor in this process (no-op when it already is)."""
    if name not in FORM_FACTORS:
        raise ValueError(f"unknown form factor {name!r} (3U, 6U or 12U)")
    if name == _current[0]:
        return name
    ff = FORM_FACTORS[name]
    env = np.array(ff["envelope_mm"], float)
    ENVELOPE[:] = env
    COM_BOX[:] = ff["com_box_mm"]
    from ..objectives import metrics
    metrics.ENCLOSURE_LO[:] = -env / 2
    metrics.ENCLOSURE_HI[:] = env / 2
    _current[0] = name
    os.environ["T2S_FORM_FACTOR"] = name          # inherited by subprocess studies started from here
    return name


def call_with(name: str, fn, *args, **kwargs):
    """Run a pool job under form factor `name` (pool processes start with the default)."""
    set_form_factor(name)
    return fn(*args, **kwargs)


def _init_from_env() -> None:
    n = os.environ.get("T2S_FORM_FACTOR")
    if n in FORM_FACTORS and n != DEFAULT:
        set_form_factor(n)
