"""The user's first free-text mission statement turned into answers they then confirm.

Rule-based (no language model): keywords pick the mission type (the type with the most matches; a tie decides
nothing), known region names set the target, and a few phrases set obvious imaging options. Each finding says which
words it came from, and the answers are stored with source "statement" so the app shows them as "from your
description" until the user confirms or changes them.
"""
from __future__ import annotations

import re

from . import questions, regions
from .model import now_iso, touch

KEYWORDS = {
    "earth_observation": ("photograph", "photo", "picture", "image", "imaging", "camera", "observe the earth",
                          "earth observation", "remote sensing", "map ", "mapping", "monitor", "satellite images",
                          "wildfire", "crops", "deforestation"),
    "communications": ("communicat", "relay", "message", "internet", "iot", "sensor network", "ais", "ads-b",
                       "ham radio", "amateur radio", "repeater", "store and forward"),
    "science": ("measure", "radiation", "magnetic field", "magnetometer", "upper atmosphere", "ionosphere",
                "space weather", "particle", "experiment", "biology"),
    "astronomy": ("star", "telescope", "astronom", "exoplanet", "galax", "nebula", "universe", "deep space"),
    "tech_demo": ("test ", "testing", "demonstrat", "prototype", "technology demo", "tech demo", "qualify"),
}


def _hits(text: str, words) -> list[str]:
    """The keywords found in the text, without one that only repeats a longer one ("photo" in "photograph")."""
    found = [w.strip() for w in words if w in text]
    return [w for w in found if not any(w != x and w in x for x in found)]


def read_statement(text: str) -> list[dict]:
    """Findings from a mission statement: [{"qid", "value", "why"}], in asking order."""
    t = f" {re.sub(r'\s+', ' ', str(text).lower())} "
    out = []
    scores = {k: _hits(t, ws) for k, ws in KEYWORDS.items()}
    best = max(scores.values(), key=len)
    leaders = [k for k, v in scores.items() if len(v) == len(best) and v]
    if len(leaders) == 1:
        k = leaders[0]
        out.append({"qid": "mission.type", "value": k, "why": f"from the words: {', '.join(scores[k][:4])}"})
    reg = regions.find_region(t)
    if reg is not None:
        out.append({"qid": "target.region", "value": reg["key"], "why": f"you named {reg['name']}"})
    if leaders == ["earth_observation"]:
        if re.search(r"\bat night\b|\bnight(time)?\b", t):
            out.append({"qid": "imaging.night", "value": True, "why": "you mentioned night"})
        if re.search(r"\bvideo\b", t):
            out.append({"qid": "imaging.video", "value": True, "why": "you mentioned video"})
        if "wildfire" in t or " fire" in t:
            out.append({"qid": "imaging.subject", "value": ["fire"], "why": "you mentioned fire"})
    return out


def apply_statement(design: dict, text: str) -> tuple[dict, list[dict]]:
    """Store the statement and its findings as answers (source "statement"); returns (design, findings)."""
    design["statement"] = str(text)
    found = []
    for f in read_statement(text):
        q = questions.BY_ID[f["qid"]]
        if not q.when(design.get("requirements", {})):
            continue
        try:
            val = questions._check(q, f["value"])
        except ValueError:
            continue
        design.setdefault("answers", {})[q.id] = {"value": val, "unknown": False, "at": now_iso(),
                                                  "source": "statement", "why": f["why"]}
        questions._apply_all(design)
        found.append(f)
    touch(design, "read the mission statement")
    return design, found
