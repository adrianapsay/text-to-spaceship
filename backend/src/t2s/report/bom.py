"""Bill of materials of one layout (V2 WS6): the single source for the Bill of Materials tab, its CSV download and the
parts list of the engineering drawings (GET /api/layouts/{id}/bom).

Every mass is what the layout's data says, with its source:
* parts: the part record at the layout's part size (density ASSUMED unless entered, mass or density entered by the
  user, or WITHHELD: no mass properties);
* brackets: the designed solid (gd.design, checked with two FEA solvers), the exact solid built from boxes (machined
  block, sheet bracket), the catalogue figure (tube clamp, ASSUMED) or the ESTIMATE from the reserved box (cradle and
  metal-AM bracket until designed);
* fasteners, spacer washers, standoffs: the ASSUMED values of mfg.rules / mfg.brackets.

A V2 bracket's mass in the layout includes its fasteners (mfg.brackets.v2_bracket, gd.design.design_bracket). Here
each bracket row is the solid alone and the fasteners are one aggregated row, so nothing is counted twice and
parts + hardware equals the layout's metrics.mass_kg. The ASSUMED frame (walls and corner rails) is listed in its own
group and, as in the metrics, not included in that total; PC/104 rods that are only keep-outs (no mass model) are
listed without a mass. Item kinds this module does not know (for example rods or spacers carried as extra items by a
later model) are listed in the hardware group with the mass they carry.
"""
from __future__ import annotations

import csv
import io
import math
import re

GROUPS = [{"id": "parts", "label": "Parts"}, {"id": "brackets", "label": "Brackets"},
          {"id": "hardware", "label": "Fasteners & hardware"}, {"id": "structure", "label": "Structure (frame)"}]
STATUS = "ENGINEERING-CONSTRAINED — not flight-qualified; not for manufacture without review"
FASTENER_NAME = "M3 × 8 screw with washer"     # what mfg.rules.FASTENER_MASS_KG is (its comment: ASSUMED)
MATCH_TOL_KG = 1e-6                             # BOM total vs the layout's metrics.mass_kg
SUBSYSTEM = {"power": "Power", "electronics": "Electronics", "adcs": "ADCS", "tanks": "Tanks",
             "payload": "Payload / sensors", "structure": "Structure", "unknown": "Unknown"}
KIND_NAME = {"direct": "Direct mount", "machined": "Machined spacer block", "sheet": "Sheet-metal Z-bracket",
             "clamp": "Tube clamp", "cradle": "Machined cradle", "metal_am": "Metal 3D-printed bracket"}
KIND_PROCESS = {"metal_am": "L-PBF metal AM", "cradle": "CNC machined (5-axis)", "machined": "CNC machined",
                "sheet": "sheet metal, 2 bends", "clamp": "catalogue", "direct": "catalogue"}
PROCESS = {"metal_am": "L-PBF metal AM", "machined": "CNC machined", "sheet": "sheet metal", "catalogue": "catalogue",
           "direct": "catalogue", "standoff": "catalogue"}


def _f(x) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _mm(v: float) -> str:
    return f"{v:.1f}".rstrip("0").rstrip(".") if abs(v - round(v, 1)) < 1e-9 else f"{v:.2f}"


def _dims(d) -> str:
    return " × ".join(_mm(float(x)) for x in d)


def part_info(rec) -> dict:
    """What the BOM needs of a part record (already at the layout's part size, see Coordinator.rec_at)."""
    v = getattr(rec, "v", None)
    ext = None
    if v is not None and len(v):
        ext = [float(x) for x in (v.max(0) - v.min(0))]
    return {"name": rec.name, "mass_kg": _f(rec.mass_kg), "mass_source": getattr(rec, "mass_source", "ASSUMED"),
            "density_kg_m3": _f(getattr(rec, "density_kg_m3", None)), "subsystem": getattr(rec, "subsystem", None),
            "extents_mm": ext}


def _row(group: str, kind: str, name: str, **kw) -> dict:
    r = {"item_no": 0, "group": group, "kind": kind, "name": name, "part_id": None, "for_parts": [], "qty": 1,
         "material": "—", "process": "—", "unit_mass_kg": None, "total_mass_kg": None, "mass_source": "not modelled",
         "in_total": False, "description": "", "item_ids": []}
    r.update(kw)
    if r["unit_mass_kg"] is not None and kw.get("total_mass_kg") is None:
        r["total_mass_kg"] = r["unit_mass_kg"] * r["qty"]
    return r


def _part_row(pid: str, info: dict | None, scale: float, excluded: set) -> dict:
    if info is None:
        return _row("parts", "part", pid, part_id=pid, for_parts=[pid], mass_source="WITHHELD", item_ids=[pid],
                    description="not in the project any more (removed after this layout was found)")
    src = info.get("mass_source") or "ASSUMED"
    m = _f(info.get("mass_kg"))
    d = _f(info.get("density_kg_m3"))
    if m is None:
        src, material = "WITHHELD", "unknown (mass properties withheld)"
    elif src == "USER_MASS":
        material = "unspecified (mass entered by the user)"
    elif src == "USER_DENSITY":
        material = f"unspecified, density {d:,.0f} kg/m³ (entered by the user)" if d else "unspecified"
    else:
        material = f"unspecified, density {d:,.0f} kg/m³ (ASSUMED)" if d else "unspecified (ASSUMED density)"
    desc = [SUBSYSTEM.get(info.get("subsystem") or "", info.get("subsystem") or "unknown")]
    if info.get("extents_mm"):
        desc.append(f"bounding box {_dims(info['extents_mm'])} mm" + (f" at {100 * scale:.0f} % size" if scale != 1 else ""))
    in_total = m is not None and pid not in excluded
    if m is not None and pid in excluded:
        desc.append("not in the layout's mass properties (no centre of mass), so not in the total")
    return _row("parts", "part", info.get("name") or pid, part_id=pid, for_parts=[pid], material=material,
                process="as supplied", unit_mass_kg=m, mass_source=src, in_total=in_total, description="; ".join(desc),
                item_ids=[pid])


def _bracket_index(item_id: str) -> int | None:
    m = re.search(r"-br(\d+)$", str(item_id))
    return int(m.group(1)) if m else None


def _washer_stacks(b: dict, solid: float) -> list[tuple[tuple, float]] | None:
    """The spacer-washer stacks of a direct mount as modelled by mfg.brackets.v2_bracket (steel boxes): their
    envelopes (two lateral sides sorted, then the height along the mount axis) and masses. None if they do not add up
    to the solid mass (then the mount is listed as one washer set)."""
    try:
        import numpy as np

        from ..mfg.brackets import STEEL, v2_bracket
        br = v2_bracket(b.get("name", "bracket"), b.get("pid", ""), b)
        ax = int(b["axis"])
        out = []
        for v, _ in br.meshes:
            d = np.asarray(v, float).max(0) - np.asarray(v, float).min(0)
            lat = sorted(float(d[k]) for k in range(3) if k != ax)
            out.append(((round(lat[1], 3), round(lat[0], 3), round(float(d[ax]), 3)), STEEL * float(np.prod(d)) * 1e-9))
    except Exception:  # noqa: BLE001 - an older / newer bracket record: one washer set per mount instead
        return None
    if not out or abs(sum(m for _, m in out) - solid) > 1e-9:
        return None
    return out


def bom_from_layout(layout: dict, parts: dict, part_order=(), frame_mass_kg: float | None = None) -> dict:
    """The bill of materials of a layout as Coordinator.layout_json gives it (full). `parts`: part_info() per part id
    at the layout's part size; `part_order`: the project's part order (item numbers follow it); `frame_mass_kg`: the
    ASSUMED frame (Stage 2), listed and not included in the total."""
    from ..mfg.rules import FASTENER_MASS_KG, MATERIAL
    F = float(FASTENER_MASS_KG)
    stage = int(layout.get("stage") or 1)
    scale = float(layout.get("part_scale") or 1.0)
    metrics = layout.get("metrics") or {}
    s2v = layout.get("stage2") or {}
    excluded = set(metrics.get("mass_excluded_parts") or [])
    poses = [p["part_id"] for p in layout.get("poses") or []]
    placed = set(poses)
    order, seen = [], set()
    for pid in [*part_order, *poses]:
        if pid in placed and pid not in seen:
            order.append(pid)
            seen.add(pid)
    names = {pid: (parts.get(pid) or {}).get("name") or pid for pid in order}
    rows = [_part_row(pid, parts.get(pid), scale, excluded) for pid in order]
    notes = []

    info = s2v.get("brackets") or []
    designs = s2v.get("bracket_designs") or {}
    brackets, fasteners, washers, standoffs, others = [], [], {}, {}, {}
    has_rod_items = False
    for it in layout.get("extra_items") or []:
        kind = str(it.get("kind") or "")
        pid = it.get("for_part")
        mass = _f(it.get("mass_kg"))
        if kind == "bracket" and it.get("bracket_kind"):                      # V2 Stage 2 bracket
            k = _bracket_index(it.get("id"))
            b = info[k] if k is not None and k < len(info) else next((x for x in info if x.get("pid") == pid), {})
            bk = str(it["bracket_kind"])
            nf = int(b.get("fasteners") or 0)
            d = designs.get(pid) if it.get("designed") else None
            d = d if d and d.get("mass_kg") is not None else None
            if d is not None:
                fast = _f(d.get("fastener_mass_kg"))
                fast = nf * F if fast is None else fast
                solid = _f(d.get("solid_mass_kg"))
                solid = (mass - fast) if solid is None and mass is not None else solid
                source = "designed"
            else:
                fast = nf * F
                solid = None if mass is None else mass - fast
                source = "ESTIMATE" if it.get("exact") is False else ("catalogue" if bk == "clamp" else "exact")
            split = solid is not None and solid > 0 and nf > 0
            if not split:
                solid = mass                       # fasteners stay inside the item's mass (listed, not split out)
            if bk == "direct":
                stacks = _washer_stacks(b, solid) if split and solid is not None else None
                if stacks:
                    for dims, m in stacks:
                        g = washers.setdefault(("stack", dims, round(m, 12)), {"dims": dims, "mass": m, "n": 0,
                                                                                "ids": [], "parts": []})
                        g["n"] += 1
                        g["ids"].append(it["id"])
                        g["parts"].append(pid)
                else:
                    washers[("set", it["id"])] = {"dims": None, "mass": solid, "n": 1, "ids": [it["id"]],
                                                  "parts": [pid], "included": 0 if split else nf}
            else:
                if d is not None:
                    proc = "metal_am" if bk == "metal_am" else "machined"
                    material = d.get("material") or MATERIAL[proc][0]
                    process = KIND_PROCESS["metal_am"] if bk == "metal_am" else "CNC machined"
                    label = d.get("label") or it.get("label") or ""
                    if not d.get("passed", False):
                        label += f" — did not pass: {d.get('reason') or 'see the Mounting Hardware tab'}"
                else:
                    material = it.get("material") or b.get("material") or "—"
                    process = KIND_PROCESS.get(bk, PROCESS.get(str(it.get("process")), str(it.get("process") or "—")))
                    label = it.get("label") or b.get("label") or ""
                desc = [label]
                if b.get("target"):
                    desc.append(f"fixed to the {b['target']}")
                if not split and nf:
                    desc.append(f"mass includes its {nf} fastener(s)")
                brackets.append(_row("brackets", "bracket", f"{KIND_NAME.get(bk, bk)} for {names.get(pid, pid)}",
                                     part_id=pid, for_parts=[pid], material=material, process=process,
                                     unit_mass_kg=solid, mass_source=source, in_total=solid is not None,
                                     description="; ".join(x for x in desc if x), item_ids=[it["id"]],
                                     bracket_kind=bk, designed=d is not None,
                                     passed=bool(d.get("passed")) if d is not None else None,
                                     target=b.get("target")))
            if split:
                fasteners.append((it["id"], pid, nf))
        elif kind == "standoff":
            box = it.get("box_mm") or []
            dims = tuple(sorted((round(float(box[k + 3]) - float(box[k]), 3) for k in range(3)), reverse=True)) \
                if len(box) == 6 else None
            g = standoffs.setdefault((dims, round(mass or 0.0, 12), it.get("label")),
                                     {"dims": dims, "mass": mass, "n": 0, "ids": [], "parts": [], "item": it})
            g["n"] += 1
            g["ids"].append(it["id"])
            g["parts"].append(pid)
        elif it.get("mount_type") is not None:           # Manufacturable Design: real solids, fasteners included
            mt = str(it.get("mount_type"))
            if kind == "bracket" and "spacer set" not in mt.lower():
                brackets.append(_row("brackets", "bracket", f"{mt[:1].upper()}{mt[1:]} for {names.get(pid, pid)}",
                                     part_id=pid, for_parts=[pid], material=it.get("material") or "—",
                                     process=PROCESS.get(str(it.get("process")), str(it.get("process") or "—")),
                                     unit_mass_kg=mass, mass_source="exact", in_total=mass is not None,
                                     description=f"{it.get('label') or mt}; mass includes its fasteners "
                                                 "(Manufacturable Design)", item_ids=[it["id"]],
                                     bracket_kind=str(it.get("process")), designed=False, passed=None))
            else:
                g = others.setdefault((kind, it.get("label") or mt, it.get("material"), it.get("process"),
                                       round(mass or 0.0, 12)), {"item": it, "n": 0, "ids": [], "parts": [],
                                                                 "mfg": True})
                g["n"] += 1
                g["ids"].append(it["id"])
                g["parts"].append(pid)
        else:                                            # kinds a later model adds (rods, spacers …)
            has_rod_items |= "rod" in kind.lower() or "rod" in str(it.get("label") or "").lower()
            g = others.setdefault((kind, it.get("label"), it.get("material"), it.get("process"), round(mass or 0.0, 12)),
                                  {"item": it, "n": 0, "ids": [], "parts": [], "mfg": False})
            g["n"] += 1
            g["ids"].append(it["id"])
            g["parts"].append(pid)

    # brackets in the order of the parts they hold
    pos = {pid: i for i, pid in enumerate(order)}
    brackets.sort(key=lambda r: (pos.get(r["part_id"], len(pos)), r["item_ids"][0]))
    hardware = []
    if fasteners:
        n = sum(x[2] for x in fasteners)
        hardware.append(_row("hardware", "fastener", FASTENER_NAME, qty=n, material="steel (ASSUMED)",
                             process="catalogue", unit_mass_kg=F, mass_source="ASSUMED", in_total=True,
                             for_parts=sorted({x[1] for x in fasteners}, key=lambda p: pos.get(p, len(pos))),
                             description=f"{n} on {len(fasteners)} bracket(s) and direct mounts; "
                                         f"{1000 * F:g} g each (ASSUMED, mfg.rules)",
                             item_ids=[x[0] for x in fasteners]))
    for key, g in sorted(washers.items(), key=lambda kv: (kv[0][0], str(kv[0][1]))):
        parts_ = sorted(set(g["parts"]), key=lambda p: pos.get(p, len(pos)))
        if g["dims"] is not None:
            a, b2, h = g["dims"]
            hardware.append(_row("hardware", "washer_stack", f"M3 spacer washer stack {_mm(a)} × {_mm(b2)} × {_mm(h)} mm",
                                 qty=g["n"], material="steel (ASSUMED)", process="catalogue", unit_mass_kg=g["mass"],
                                 mass_source="ASSUMED", in_total=True, for_parts=parts_,
                                 description=f"{_mm(a)} × {_mm(b2)} mm envelope, {_mm(h)} mm high (ASSUMED model), "
                                             f"under the direct mounts of {', '.join(names.get(p, p) for p in parts_)}",
                                 item_ids=sorted(set(g["ids"]))))
        else:
            inc = g.get("included", 0)
            hardware.append(_row("hardware", "washer_set", f"M3 spacer washers, direct mount of "
                                 f"{names.get(parts_[0], parts_[0]) if parts_ else '?'}", qty=1,
                                 material="steel (ASSUMED)", process="catalogue", unit_mass_kg=g["mass"],
                                 mass_source="ASSUMED", in_total=g["mass"] is not None, for_parts=parts_,
                                 description="washer stacks of one direct mount" +
                                             (f"; mass includes its {inc} fastener(s)" if inc else ""),
                                 item_ids=g["ids"]))
    for (dims, _, _), g in sorted(standoffs.items(), key=lambda kv: str(kv[0][0])):
        it = g["item"]
        parts_ = sorted(set(g["parts"]), key=lambda p: pos.get(p, len(pos)))
        hardware.append(_row("hardware", "standoff", "M3 standoff" + (f" {_dims(dims)} mm" if dims else ""), qty=g["n"],
                             material=it.get("material") or "aluminium (ASSUMED)", process="catalogue",
                             unit_mass_kg=g["mass"], mass_source="ASSUMED", in_total=g["mass"] is not None,
                             for_parts=parts_,
                             description=(f"{_dims(dims)} mm envelope (ASSUMED), " if dims else "") +
                                         f"for {', '.join(names.get(p, p) for p in parts_)}",
                             item_ids=g["ids"]))
    for (kind, label, material, process, _), g in others.items():
        it = g["item"]
        m = _f(it.get("mass_kg"))
        parts_ = sorted({p for p in g["parts"] if p}, key=lambda p: pos.get(p, len(pos)))
        desc = [str(label or kind)]
        if g["mfg"]:
            desc.append("mass includes its fasteners (Manufacturable Design)")
        if parts_:
            desc.append(f"for {', '.join(names.get(p, p) for p in parts_)}")
        hardware.append(_row("hardware", kind or "item", str(label or kind or "item"), qty=g["n"],
                             material=material or "—", process=PROCESS.get(str(process), str(process or "—")),
                             unit_mass_kg=m, mass_source="exact" if m is not None else "not modelled",
                             in_total=m is not None, for_parts=parts_, description="; ".join(desc),
                             item_ids=g["ids"]))
    if stage == 2 and not has_rod_items:
        rods = [f for f in s2v.get("frame") or [] if f.get("kind") == "rod"]
        if rods:
            lo, hi = rods[0]["min"], rods[0]["max"]
            w = min(float(hi[0]) - float(lo[0]), float(hi[1]) - float(lo[1]))
            length = float(hi[2]) - float(lo[2])
            hardware.append(_row("hardware", "rod", "PC/104 stack rod", qty=len(rods), material="—",
                                 process="catalogue", mass_source="not modelled", in_total=False,
                                 description=f"M3 rod keep-out {_mm(w)} × {_mm(w)} mm, {_mm(length)} mm long through "
                                             "the board stack (ASSUMED positions); no mass model yet, so not in "
                                             "the totals",
                                 item_ids=[str(f.get("id")) for f in rods]))
            notes.append("The PC/104 rods are keep-outs without a mass model: listed, not in the totals.")
    structure = []
    if stage == 2 and frame_mass_kg is not None:
        from ..constraints.stage2 import AL_DENSITY, RAIL, WALL
        structure.append(_row("structure", "frame", "CubeSat frame: walls and 4 corner rails",
                              material=f"aluminium, {AL_DENSITY:,.0f} kg/m³ (ASSUMED)", process="—",
                              unit_mass_kg=_f(frame_mass_kg), mass_source="ASSUMED", in_total=False,
                              description=f"{_mm(WALL)} mm walls and end plates, {_mm(RAIL)} × {_mm(RAIL)} mm corner "
                                          "rails (ASSUMED geometry); not in the layout's total mass (as in the "
                                          "metrics); drawn as an outline"))
    rows += brackets + hardware + structure
    for i, r in enumerate(rows):
        r["item_no"] = i + 1

    def total(pred) -> float:
        return float(sum(r["total_mass_kg"] for r in rows if pred(r) and r["in_total"] and r["total_mass_kg"] is not None))
    parts_kg = total(lambda r: r["group"] == "parts")
    hardware_kg = total(lambda r: r["group"] in ("brackets", "hardware"))
    assembly = parts_kg + hardware_kg
    frame_kg = structure[0]["total_mass_kg"] if structure else None
    mm = _f(metrics.get("mass_kg"))
    est = sum(r["total_mass_kg"] for r in rows if r["mass_source"] == "ESTIMATE" and r["total_mass_kg"] is not None)
    if est:
        notes.append(f"{sum(1 for r in rows if r['mass_source'] == 'ESTIMATE')} bracket mass(es) are ESTIMATES from "
                     "their reserved boxes until the brackets are designed.")
    if fasteners:
        notes.append("A bracket's mass in the layout includes its fasteners; here each bracket row is the solid alone "
                     f"and the fasteners are item {next(r['item_no'] for r in rows if r['kind'] == 'fastener')}, so "
                     "the total is unchanged.")
    if scale != 1.0:
        notes.append(f"Parts at {100 * scale:.0f} % of full size (part-size slider): computed masses scale with the "
                     "volume; masses entered by the user are kept.")
    if stage != 2:
        notes.append("Stage 1 (IDEALIZED): parts only; no brackets, fasteners or frame are modelled.")
    withheld = [r["name"] for r in rows if r["group"] == "parts" and r["total_mass_kg"] is None]
    if withheld:
        notes.append(f"No mass for {', '.join(withheld)} (mass properties withheld): not in the totals.")
    return {
        "layout_id": layout.get("id"), "stage": stage, "mode": layout.get("mode"), "part_scale": scale,
        "label": layout.get("label") or ("IDEALIZED (Stage 1)" if stage != 2 else STATUS),
        "status_line": STATUS, "groups": GROUPS, "items": rows, "notes": notes, "units": {"mass": "kg", "length": "mm"},
        "totals": {
            "parts_kg": parts_kg, "hardware_kg": hardware_kg, "assembly_kg": assembly, "frame_kg": frame_kg,
            "with_frame_kg": assembly + frame_kg if frame_kg is not None else None, "estimate_kg": float(est),
            "metrics_mass_kg": mm, "matches_metrics": None if mm is None else abs(assembly - mm) <= MATCH_TOL_KG,
            "difference_kg": None if mm is None else assembly - mm, "rows": len(rows),
            "pieces": int(sum(r["qty"] for r in rows)), "withheld": withheld,
            "not_modelled": [r["item_no"] for r in rows if r["total_mass_kg"] is None and r["group"] != "parts"],
            "included": "Parts and hardware (brackets, fasteners, washers, standoffs): the layout's total mass. The "
                        "frame and rows without a mass model are listed, not included.",
        },
    }


def bom(coord, e) -> dict:
    """The bill of materials of archive entry `e` (Coordinator.layout_json, part records at the layout's size)."""
    lj = coord.layout_json(e)
    parts = {}
    for pid, _, _ in e.poses:
        rec = coord.rec_at(pid, e.part_scale)
        if rec is not None:
            parts[pid] = part_info(rec)
    order = list(getattr(getattr(coord, "store", None), "entries", None) or [])
    fm = None
    if e.stage == 2:
        fm = _f((e.metrics or {}).get("frame_mass_kg"))
        if fm is None:
            from ..constraints.stage2 import frame_mass_props
            fm = float(frame_mass_props()[0])
    return bom_from_layout(lj, parts, order, fm)


CSV_COLUMNS = ["item", "group", "name", "qty", "material", "process", "unit_mass_kg", "total_mass_kg", "mass_source",
               "in_total", "part_id", "description", "item_ids"]


def _num(v) -> str:
    return "" if v is None else f"{float(v):.6f}"


def bom_csv(b: dict) -> str:
    """CSV of a bill of materials (UTF-8 with a byte-order mark, so that spreadsheet programs read the × and ³)."""
    labels = {g["id"]: g["label"] for g in b.get("groups") or GROUPS}
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow([f"# Bill of materials, layout {b.get('layout_id')}: {b.get('label')}"])
    w.writerow([f"# Masses in kg as the layout data gives them (source per row). {b['totals']['included']}"])
    w.writerow(CSV_COLUMNS)
    for r in b["items"]:
        w.writerow([r["item_no"], labels.get(r["group"], r["group"]), r["name"], r["qty"], r["material"], r["process"],
                    _num(r["unit_mass_kg"]), _num(r["total_mass_kg"]), r["mass_source"],
                    "yes" if r["in_total"] else "no", r.get("part_id") or "", r["description"], ";".join(r["item_ids"])])
    t = b["totals"]
    w.writerow([])
    for label, v in (("parts", t["parts_kg"]), ("hardware", t["hardware_kg"]),
                     ("parts + hardware (the layout's total mass)", t["assembly_kg"]),
                     ("frame (listed, not included)", t["frame_kg"]), ("total with the frame", t["with_frame_kg"])):
        if v is not None:
            w.writerow(["", "TOTAL", label, "", "", "", "", _num(v), "", "", "", "", ""])
    return "﻿" + buf.getvalue()
