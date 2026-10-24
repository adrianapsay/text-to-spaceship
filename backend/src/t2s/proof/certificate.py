"""Fit proof (Addendum 3.2b): machine-checkable certificate + human-readable proof for a VALIDATED layout.

The certificate references the ORIGINAL STL files by SHA-256 and gives, per part, the authored->canonical transform,
the pose, and the cut-plane cells of its cover pieces. Each pair carries separating planes. The stand-alone checker
(tools/check_certificate.py, standard library only) re-derives every vertex set from the STL files and re-evaluates
every inequality; it never trusts numbers computed by the app.

Version 2 (Stage 2, v2.5): a `frame` block states the true inner planes of the walls and end plates, every frame item
(name, kind, corners: rails, PC/104 rods, harness, stack reserve, standoffs, bracket boxes), the mounting rules, the
stack boards and the end plate their rods run to; each bracket entry states its target face (axis, neg, plane_mm,
target_kind) and the parts it holds. The checker then also proves that every part is fixed to the chassis.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import numpy as np

from ..core.rotations import ROTATIONS
from ..geometry.proxies import COVER_DELTA

CERT_VERSION = 2          # 2: Stage 2 frame block and bracket attachment (version 1 certificates still verify)


def _r(x, nd=12):
    return [round(float(v), nd) for v in np.ravel(x)]


def build_certificate(layout_id: str, report, records: dict, poses, spec, files: dict, extra: dict | None = None,
                      brackets: list | None = None):
    """records: part_id -> PartRecord; poses: [(part_id, orient, t_mm)]; files: part_id -> (relative path, sha256).
    brackets (V2 Stage 2, mfg.brackets.cert_entry): [{name, part, kind, target, target_kind, axis, neg, plane_mm,
    reserve (lo+hi), solid_vertices, estimate, held_parts, exempt_parts, target_statics}]. A Stage 2 spec
    (constraints.stage2_model.Stage2Spec) adds the frame block."""
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
        elif p.level in ("G1", "G4"):
            e.update(method="numeric", note=f"verified by {p.level}: {p.detail or 'exact mesh distance'}")
        else:
            e.update(method="aabb")
        statics.append(e)
    named = {s.name: s for s in spec.statics}
    static_pairs = [{"a": p.a, "b": p.b, "corners_a": named[p.a].corners.tolist(),
                     "corners_b": named[p.b].corners.tolist(), "required_mm": p.required_mm, "gap_mm": p.gap_lb_mm}
                    for p in getattr(report, "static_pairs", [])]
    frame = None
    if getattr(spec, "frame", None):            # Stage 2: what the frame is, so that attachment can be checked
        frame = dict(spec.frame)
        frame["items"] = [{"name": s.name, "kind": s.kind, "corners": s.corners.tolist()} for s in spec.statics]
    return {
        "certificate_version": CERT_VERSION, "layout_id": layout_id, "stage": spec.stage,
        "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "enclosure_vertex_bounds_mm": {"lo": _r(spec.lo, 9), "hi": _r(spec.hi, 9)},
        "cover_delta_mm": COVER_DELTA, "parts": parts, "pairs": pairs, "statics": statics,
        "static_pairs": static_pairs, "brackets": brackets or [], "frame": frame,
        "exempt": sorted([list(x) for x in spec.exempt]),
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
    if cert.get("brackets"):
        L.append("\n## Lemma 4 — brackets fit\n")
        L.append("Every bracket lies inside its reserved box B: each vertex of its solid satisfies the box bounds, and a "
                 "box is convex, so the whole solid does. The boxes are listed with the frame items above, so Lemma 2 "
                 "(with the box corners as one point set) shows every part keeps the required gap from every bracket "
                 "it does not belong to. Two axis-aligned boxes are at least g apart when, on some axis, the low face "
                 "of one is at least g beyond the high face of the other; this is checked for every bracket against "
                 "every other bracket and every keep-out except the corner rail it is fixed to. A bracket touches "
                 "only the parts it holds and the chassis structure it is fixed to.\n")
        if any(b.get("multi") for b in cert["brackets"]):
            L.append("A **combined bracket** holds several parts and has several boxes: its members' reserved boxes "
                     "and the bridging boxes between them, each a frame item checked like any reserved box. Every box "
                     "starts on the target plane and extends to the same side, the solid's surface is closed and "
                     "every triangle of it lies in one of the boxes; a point outside the boxes cannot be enclosed by "
                     "them (moving away from the plane leaves every box), so the solid lies in their union and the "
                     "box arithmetic above holds for it. A member box may touch only its own part, a bridge only the "
                     "two parts it joins.\n")
        if any(b.get("one_piece") for b in cert["brackets"]):
            L.append("The **one piece** (exploratory) holds every part it lists. No triangle of its closed surface "
                     "meets any frame item, or the bounding box of any part it does not hold, grown by 1.2 mm "
                     "(separating-axis test, exact), and none of them lies inside it (winding number), so it keeps "
                     "1.2 mm from all of them; every vertex lies within the inner planes. Its distance to the parts "
                     "it holds is numeric (FCL), listed below, not proven.\n")
        L.append("| Bracket | part | type | fixed to | reserved box (mm) | solid |\n|---|---|---|---|---|---|")
        for b in cert["brackets"]:
            if b.get("one_piece"):
                nd = (b.get("numeric") or {}).get("held_part_distance_mm") or {}
                dmin = min((x for x in nd.values() if x is not None), default=None)
                L.append(f"| one piece | {', '.join(nm(p) for p in b['held_parts'])} | one piece | "
                         f"{len(b.get('bolted') or [])} bolted pads | — | {len(b['solid_faces'])} triangles, clear of "
                         "every frame item by 1.2 mm" + (f"; nearest held part {dmin:.3f} mm (numeric)" if dmin is not
                                                       None else "") + " |")
                continue
            r = np.asarray(b["reserve"], float)
            size = " × ".join(f"{x:.1f}" for x in r[3:] - r[:3])
            if b.get("multi"):
                L.append(f"| {b['name']} | {', '.join(nm(p) for p in b['held_parts'])} | combined | {b['target']} | "
                         f"{len(b['boxes'])} boxes in {size} | {len(b['solid_faces'])} triangles, each inside one box |")
                continue
            L.append(f"| {b['name']} | {nm(b['part'])} | {b['kind']} | {b['target']} | {size} | "
                     + ("box only — solid not designed yet (estimate)" if b.get("estimate") else
                        f"{len(b['solid_vertices'])} vertices inside the box") + " |")
        if cert.get("static_pairs"):
            worst = min(cert["static_pairs"], key=lambda p: p["gap_mm"] - p["required_mm"])
            L.append(f"\n{len(cert['static_pairs'])} box–box conditions hold; the tightest is {worst['a']} – "
                     f"{worst['b']}: {worst['gap_mm']:.4f} mm ≥ {worst['required_mm']:.3f} mm.")
    L += _mounting_lemma(cert, nm)
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
            # the layout keeps the part ids in order (coordinator geo); (part, direction) pairs give the direction too
            def step(x):
                return f"{nm(x[0])} ({x[1]})" if isinstance(x, (list, tuple)) and len(x) == 2 else nm(x)
            L.append("\nInsertion order (each part slides straight in along ±Z without meeting an installed part): "
                     + ", ".join(step(x) for x in metrics["insertion_order"]) + ".")
        if metrics.get("lower_bounds"):
            L.append("\n## Why it cannot be much shorter\n")
            for name, val, why in metrics["lower_bounds"]:
                L.append(f"- **{val:.1f} mm** — {name}: {why}")
    L.append("\n---\nIndependent check: run `python check_certificate.py certificate.json <folder with the STL files>`. "
             "It uses only the Python standard library, reloads the original STL files, verifies their SHA-256, "
             "re-applies every transform and re-evaluates every inequality above.")
    return "\n".join(L) + "\n"


def _mounting_lemma(cert: dict, nm) -> list[str]:
    """Lemma 5 (Stage 2, v2.5 rules): every part is fixed to chassis structure."""
    fr = cert.get("frame")
    if not fr:
        return []
    if fr.get("rules") != "v2.5":
        return ["\n## Mounting\n", ("This layout was found under the mounting rules before v2.5, which let a bracket "
                                    "be fixed to the PC/104 deck; Lemma 5 (chassis-only mounting) does not apply.")]
    pl = fr["planes_mm"]
    out = ["\n## Lemma 5 — every part is fixed to the chassis\n",
           (f"The inner wall planes are x = {pl['x'][0]:.3f} and {pl['x'][1]:.3f}, y = {pl['y'][0]:.3f} and "
            f"{pl['y'][1]:.3f} mm; the end plates are at z = {pl['z'][0]:.3f} and {pl['z'][1]:.3f} mm; the corner "
            "rails are frame items. Every bracket's reserved box has its target face on one of these planes, or on the "
            "face of a corner rail it overlaps, so each bracket is fixed to chassis structure and never to another "
            "part. Every part except the PC/104 boards and edge-on boards has a bracket, and a bracket may touch only "
            "the parts it holds (its exemptions are exactly those parts).")]
    if fr.get("stack_ids"):
        z = pl["z"][0] if fr.get("rod_end") == "-z" else pl["z"][1]
        out.append(f"The PC/104 boards ({', '.join(nm(p) for p in fr['stack_ids'])}) are held by four rods with "
                   f"spacer tubes that run from the {fr.get('rod_end')} end plate (z = {z:.3f} mm) through every board, "
                   "inside each board's outline; only the boards are exempt from the rods.")
    if any(i["kind"] == "standoff" for i in fr.get("items", [])):
        out.append("Edge-on boards stand on M3 standoffs that reach a side wall.")
    if cert.get("brackets"):
        out.append("\n| Bracket | holds | fixed to | target plane (mm) |\n|---|---|---|---|")
        for b in cert["brackets"]:
            if b.get("one_piece"):
                planes = sorted({f"{'xyz'[x['axis']]} = {x['plane_mm']:.3f}" for x in b.get("bolted") or []})
                out.append(f"| one piece | {', '.join(nm(p) for p in b.get('held_parts', []))} | each part's own wall "
                           f"or end plate, under its footprint | {', '.join(planes)} |")
                continue
            out.append(f"| {b['name']} | {', '.join(nm(p) for p in b.get('held_parts', [b['part']]))} | "
                       f"{b.get('target_kind', '?').replace('_', ' ')} ({b['target']}) | "
                       f"{'xyz'[b['axis']]} = {b['plane_mm']:.3f} |")
    return out


def write_certificate(path, cert):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(cert, fh, indent=1)
