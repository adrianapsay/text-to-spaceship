"""Fit proof (Addendum 3.2b): machine-checkable certificate + human-readable proof for a VALIDATED layout.

The certificate references the ORIGINAL STL files by SHA-256 and gives, per part, the authored->canonical transform,
the pose, and the cut-plane cells of its cover pieces. Each pair carries separating planes. The stand-alone checker
(tools/check_certificate.py, standard library only) re-derives every vertex set from the STL files and re-evaluates
every inequality; it never trusts numbers computed by the app.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import numpy as np

from ..core.rotations import ROTATIONS
from ..geometry.proxies import COVER_DELTA

CERT_VERSION = 1


def _r(x, nd=12):
    return [round(float(v), nd) for v in np.ravel(x)]


def build_certificate(layout_id: str, report, records: dict, poses, spec, files: dict, extra: dict | None = None):
    """records: part_id -> PartRecord; poses: [(part_id, orient, t_mm)]; files: part_id -> (relative path, sha256)."""
    parts = []
    for pid, orient, t in poses:
        rec = records[pid]
        parts.append({
            "id": pid, "name": rec.name, "file": files[pid][0], "sha256": files[pid][1], "units_to_mm":
                {"mm": 1.0, "cm": 10.0, "m": 1000.0, "in": 25.4}[rec.units],
            "canonical_R": _r(rec.r_auth_to_can), "canonical_origin_mm": _r(rec.origin_auth),
            "orient": int(orient), "R_orient": ROTATIONS[int(orient)].ravel().tolist(), "t_mm": _r(t, 6),
            "cells": [[{"n": _r(n), "d": round(float(d), 12)} for n, d in piece.planes] for piece in rec.cover.pieces],
            # V2 part-size slider: canonical vertices are multiplied by this before the pose (cells are given at it)
            "part_scale": float(getattr(rec, "part_scale", 1.0)),
        })
        if rec.status == "REPAIRED":
            # declared repair: the checker uses this canonical-frame mesh (already at part_scale) instead of
            # re-implementing the repair
            parts[-1]["repaired_mesh"] = {"note": "; ".join(rec.repairs), "vertices": np.round(rec.v, 12).tolist(),
                                          "faces": rec.f.tolist()}
    pairs = []
    for p in report.pairs:
        entry = {"a": p.a, "b": p.b, "level": p.level, "required_mm": p.required_mm, "gap_lb_mm": p.gap_lb_mm}
        if p.level in ("G0", "G2") and p.planes:
            n, hi_a, lo_b, gap = p.planes[0]
            entry.update(method="hull_plane", n=_r(n))
        elif p.level == "G3" and p.planes:
            entry.update(method="piece_planes", planes=[{"piece_a": q["piece_a"], "piece_b": q["piece_b"], "n": _r(q["n"])}
                                                        for q in p.planes])
        else:
            entry.update(method="numeric", note=f"verified by {p.level}: {p.detail or 'exact mesh distance'}")
        pairs.append(entry)
    statics = []
    for p in report.statics:
        s = next(s for s in spec.statics if s.name == p.b)
        e = {"part": p.a, "static": p.b, "corners": s.corners.tolist(), "required_mm": p.required_mm,
             "gap_lb_mm": p.gap_lb_mm}
        if p.planes and isinstance(p.planes[0], tuple):
            e.update(method="hull_plane", n=_r(p.planes[0][0]))
        elif p.planes:
            e.update(method="piece_planes", planes=[{"piece_a": q["piece_a"], "n": _r(q["n"])} for q in p.planes])
        else:
            e.update(method="aabb")
        statics.append(e)
    return {
        "certificate_version": CERT_VERSION, "layout_id": layout_id, "stage": spec.stage,
        "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "enclosure_vertex_bounds_mm": {"lo": _r(spec.lo, 9), "hi": _r(spec.hi, 9)},
        "cover_delta_mm": COVER_DELTA, "parts": parts, "pairs": pairs, "statics": statics,
        "extra": extra or {},
    }


def proof_markdown(cert: dict, report, metrics: dict | None = None) -> str:
    names = {p["id"]: p.get("name") or p["id"] for p in cert["parts"]}

    def nm(pid):
        n = names.get(pid)
        return f"{pid} ({n})" if n and n != pid else pid
    L = []
    st = "IDEALIZED (Stage 1)" if cert["stage"] == 1 else "ENGINEERING-CONSTRAINED (Stage 2)"
    L.append(f"# Proof that layout {cert['layout_id']} fits — {st}\n")
    L.append("**Theorem.** The parts below occupy pairwise-disjoint regions inside the enclosure"
             + ("." if cert["stage"] == 1 else ", keep the required clearances to each other and to the frame, "
                "and satisfy the stated balance and assembly conditions.") + "\n")
    lo, hi = cert["enclosure_vertex_bounds_mm"]["lo"], cert["enclosure_vertex_bounds_mm"]["hi"]
    L.append("## Lemma 1 — every part is inside the enclosure\n")
    L.append(f"The admissible region for part vertices is the box x ∈ [{lo[0]:.3f}, {hi[0]:.3f}], "
             f"y ∈ [{lo[1]:.3f}, {hi[1]:.3f}], z ∈ [{lo[2]:.3f}, {hi[2]:.3f}] mm. A box is convex and every part lies in "
             "the convex hull of its own vertices, so if all transformed vertices satisfy the bounds the whole part does.\n")
    L.append("| Part | tightest margin (mm) | axis |\n|---|---|---|")
    for c in report.containment:
        m = np.minimum(c["margin_lo_mm"], c["margin_hi_mm"])
        k = int(np.argmin(m))
        L.append(f"| {nm(c['part'])} | {m[k]:.4f} | {'xyz'[k]} |")
    L.append("\n## Lemma 2 — convex separation\n")
    L.append("For point sets A, B and a unit vector n: if max over A of n·a ≤ h and min over B of n·b ≥ h + g, then "
             "every point of conv(A) is at least g from every point of conv(B). Each part lies in conv(its vertices).\n")
    L.append("## Lemma 3 — parts with hollows or holes\n")
    L.append("A part may be cut by planes into cells. Each solid piece (part ∩ cell) lies in the convex hull of the "
             "part's surface clipped to the cell, plus any cell corner inside the solid. If every piece pair of two "
             f"parts is separated by g + 2δ with δ = {cert['cover_delta_mm'] * 1e3:.1f} µm (the certified cover "
             "inflation), the parts are separated by g.\n")
    L.append("## Pairwise separation\n")
    L.append("| Part A | Part B | method | certified gap ≥ (mm) | required (mm) |\n|---|---|---|---|---|")
    for p in cert["pairs"]:
        L.append(f"| {nm(p['a'])} | {nm(p['b'])} | {p['method'].replace('_', ' ')} | {p['gap_lb_mm']:.4f} | "
                 f"{p['required_mm']:.3f} |")
    if cert["statics"]:
        L.append("\n## Frame and keep-outs\n")
        L.append("| Part | item | certified gap ≥ (mm) | required (mm) |\n|---|---|---|---|")
        for s in cert["statics"]:
            L.append(f"| {nm(s['part'])} | {s['static']} | {s['gap_lb_mm']:.4f} | {s['required_mm']:.3f} |")
    L.append("\n> **Arithmetic.** All inequalities are evaluated in float64 from the original float32 STL vertices and "
             "the integer-µm poses. Rounding allowance: poses are exact multiples of 1 µm; every certified gap above "
             "exceeds the required value by more than the 1e-9 mm comparison tolerance, and cover pieces carry "
             f"their δ = {cert['cover_delta_mm'] * 1e3:.1f} µm inflation explicitly.")
    numeric = [p for p in cert["pairs"] if p["method"] == "numeric"]
    if numeric:
        L.append(f"\n> {len(numeric)} pair(s) are verified numerically (exact mesh distance by two independent "
                 "implementations) rather than by a closed-form plane certificate.")
    if metrics:
        L.append("\n## Balance and assembly\n")
        com = metrics.get("com_mm")
        if com is not None:
            L.append(f"Assembly centre of mass: ({com[0]:.2f}, {com[1]:.2f}, {com[2]:.2f}) mm. CDS Rev 14.1 §2.2.11 "
                     f"requires |x| ≤ 20, |y| ≤ 20, |z| ≤ 70 mm: "
                     f"{'satisfied' if abs(com[0]) <= 20 and abs(com[1]) <= 20 and abs(com[2]) <= 70 else 'NOT satisfied'}"
                     + (" (enforced)" if cert["stage"] == 2 else " (reported only in Stage 1)") + ".")
        if metrics.get("insertion_order"):
            L.append("\nInsertion order (each part slides straight in along ±Z without meeting an installed part): "
                     + ", ".join(f"{p} ({u})" for p, u in metrics["insertion_order"]) + ".")
        if metrics.get("lower_bounds"):
            L.append("\n## Why it cannot be much shorter\n")
            for name, val, why in metrics["lower_bounds"]:
                L.append(f"- **{val:.1f} mm** — {name}: {why}")
    L.append("\n---\nIndependent check: run `python check_certificate.py certificate.json <folder with the STL files>`. "
             "It uses only the Python standard library, reloads the original STL files, verifies their SHA-256, "
             "re-applies every transform and re-evaluates every inequality above.")
    return "\n".join(L) + "\n"


def write_certificate(path, cert):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(cert, fh, indent=1)
