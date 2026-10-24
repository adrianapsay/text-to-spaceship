"""Fit-proof rules and certificate entries of a layout under a bracket layout (M4): one bracket per part (unchanged),
combined per wall, or one piece.

* per_part: constraints.stage2_model.Stage2Model.spec, unchanged; one certificate entry per bracket.
* combined: the per-part reserved boxes stay frame items (the packing certified them); every combined bracket with a
  designed solid adds its bridging boxes as frame items (kind "bracket"). A bridge keeps 1.2 mm from every part except
  the two it joins (exempt), from every box of every other bracket and from every keep-out except the target rail
  (static pairs, box arithmetic). Its certificate entry lists all its boxes and its solid's vertices and faces
  (mfg.brackets.cert_entry_combined). A group whose design built no solid is left as per-part brackets.
* one_piece: the boxes of the brackets the piece replaces are no longer frame items (nothing occupies them); a
  bracket the piece does not replace (a part on a corner rail) keeps its rules. The piece's entry
  (mfg.brackets.cert_entry_one_piece) carries its solid; the checker proves it clear of every frame item and every
  part it does not hold.
"""
from __future__ import annotations

import numpy as np

CLEAR = 1.2


def _corners(lo, hi):
    from ..constraints import stage2 as s2
    return s2.box_corners(np.asarray(lo, float), np.asarray(hi, float))


def designed_groups(layout: dict | None) -> list[dict]:
    """The combined brackets of a combined layout result that have a solid (vertices and faces on file)."""
    if not layout:
        return []
    return [d for d in (layout.get("designs") or {}).values() if d.get("mass_kg") is not None and d.get("boxes")]


def spec_for_layout(model, meta: dict, mode: str, layout: dict | None, relaxed: bool = False):
    """The validator's rules for a layout under a bracket layout (module docstring)."""
    from ..collision.validate import StaticItem
    spec = model.spec(meta, relaxed)
    if mode == "combined":
        groups = designed_groups(layout)
        if not groups:
            return spec
        statics = list(spec.statics)
        kinds = {s.name: s.kind for s in statics}
        exempt = set(spec.exempt)
        pairs = list(spec.static_pairs)
        for g in groups:
            members = {b["name"] for b in g["boxes"] if b["role"] == "member"}
            own = {b["name"] for b in g["boxes"]}
            rails = set(g.get("target_statics") or [])
            for b in g["boxes"]:
                if b["role"] != "bridge":
                    continue
                r = np.asarray(b["box"], float)
                statics.append(StaticItem(b["name"], _corners(r[:3], r[3:]), "bracket"))
                exempt |= {(p, b["name"]) for p in b.get("ends") or []}
                for s in spec.statics:                   # every other bracket's box and every keep-out
                    if s.name in own or s.name in members:
                        continue
                    if kinds.get(s.name) == "rail" and s.name in rails:
                        continue
                    pairs.append((b["name"], s.name, CLEAR))
        for i, g in enumerate(groups):                       # the bridges of different combined brackets
            for b in [x for x in g["boxes"] if x["role"] == "bridge"]:
                for h in groups[i + 1:]:
                    for o in h["boxes"]:
                        if o["role"] == "bridge":
                            pairs.append((b["name"], o["name"], CLEAR))
        spec.statics, spec.exempt, spec.static_pairs = statics, exempt, _dedupe(pairs)
        return spec
    if mode == "one_piece":
        rec = (layout or {}).get("designs", {}).get("one_piece") or {}
        if rec.get("mass_kg") is None:
            return spec
        held = set(rec.get("parts") or [])
        gone = {b["name"] for b in meta.get("brackets") or [] if b["pid"] in held}
        spec.statics = [s for s in spec.statics if s.name not in gone]
        spec.exempt = {e for e in spec.exempt if e[1] not in gone}
        spec.static_pairs = [p for p in spec.static_pairs if p[0] not in gone and p[1] not in gone]
        return spec
    return spec


def _dedupe(pairs):
    seen, out = set(), []
    for a, b, c in pairs:
        k = frozenset((a, b))
        if k in seen or a == b:
            continue
        seen.add(k)
        out.append((a, b, c))
    return out


def certificate_brackets(meta: dict, mode: str, layout: dict | None, per_part_vertices, solid_of) -> list[dict]:
    """The certificate's bracket entries under a bracket layout. per_part_vertices(bracket) → designed vertices or
    None; solid_of(record) → (vertices, faces) of a combined bracket or the one piece (from the job's files)."""
    from ..mfg.brackets import cert_entry, cert_entry_combined, cert_entry_one_piece
    brs = meta.get("brackets") or []
    out = []
    if mode == "combined":
        groups = []
        for g in designed_groups(layout):
            sol = solid_of(g)
            if sol is not None:
                groups.append((g, sol))
        held = {p for g, _ in groups for p in g["parts"]}
        out += [cert_entry(b, per_part_vertices(b)) for b in brs if b["pid"] not in held]
        out += [cert_entry_combined(g, *sol) for g, sol in groups]
        return out
    if mode == "one_piece":
        rec = (layout or {}).get("designs", {}).get("one_piece") or {}
        sol = solid_of(rec) if rec.get("mass_kg") is not None else None
        if sol is not None:
            held = set(rec.get("parts") or [])
            out += [cert_entry(b, per_part_vertices(b)) for b in brs if b["pid"] not in held]
            out.append(cert_entry_one_piece(rec, *sol))
            return out
    return [cert_entry(b, per_part_vertices(b)) for b in brs]
