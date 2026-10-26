"""The CubeSat Builder design record (plain JSON-ready dicts).

A design holds
* `answers`: {question id: {"value", "unknown", "at"}} — what the user answered ("unknown": "I don't know");
* `requirements`: {key: {"value", "unit", "source", "note", "qid"}} — what the answers set. `source` is one of
  SOURCES: "user" (answered), "statement" (read from the user's mission statement, confirmed by answering),
  "default" (the user did not know: the question's default, ASSUMED, `note` says why), "derived" (computed from other
  requirements);
* `selections`: {slot: {"component": id or None, "qty": n}} — the user's own parts (None: left out); every other
  slot follows the architect's recommendation (engine.py);
* `prefs`: the trade sliders (0 … 1) and an optional `lifetime_years`; `size_u`: a CubeSat size the user fixed;
* `sent`: [{"project", "at", "version"}] — each Send to Optimization;
* `history`: [{"version", "at", "what"}] — every change, newest last (the version counts them).
"""
from __future__ import annotations

import copy
import re
import secrets
import time

SOURCES = ("user", "statement", "default", "derived")


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())


def new_design(name: str = "", statement: str = "") -> dict:
    t = now_iso()
    did = time.strftime("D-%Y%m%d-", time.localtime()) + secrets.token_hex(3)
    return {"id": did, "name": name or "New mission", "created": t, "updated": t, "version": 1,
            "statement": statement, "answers": {}, "requirements": {}, "selections": {}, "sent": [],
            "history": [{"version": 1, "at": t, "what": "created"}]}


def req(value, source: str, unit: str | None = None, note: str = "", qid: str | None = None) -> dict:
    if source not in SOURCES:
        raise ValueError(f"unknown requirement source {source!r}")
    return {"value": value, "unit": unit, "source": source, "note": note, "qid": qid}


def value(design: dict, key: str, default=None):
    """The value of requirement `key` (default when it is not set)."""
    r = design.get("requirements", {}).get(key)
    return default if r is None else r["value"]


def touch(design: dict, what: str) -> dict:
    """Record a change: version + 1, its time and what changed."""
    design["version"] = int(design.get("version", 0)) + 1
    design["updated"] = now_iso()
    design.setdefault("history", []).append({"version": design["version"], "at": design["updated"], "what": what})
    return design


def slug(text: str, n: int = 32) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")
    return (s[:n].rstrip("-")) or "mission"


def clone(design: dict) -> dict:
    return copy.deepcopy(design)
