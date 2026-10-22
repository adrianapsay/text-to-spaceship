"""M10: layout report (Markdown / HTML), placed-STL ZIP and the Fusion 360 export package.

Every number in these files is read from the archived layout (validator, mass-property integrator, search), the
part records or the proof certificate; nothing is re-estimated here. The Fusion 360 package is prepared only:
FUSION 360 VALIDATION: NOT CONFIGURED, and no Fusion 360 API call is made by this app.
"""
from __future__ import annotations

import html
import io
import json
import re
import zipfile
from datetime import datetime, timezone

import numpy as np

from ..collision.geom import to_world
from ..core.rotations import ROTATIONS_F
from ..geometry.stl_io import stl_bytes
from ..objectives.metrics import ENCLOSURE_HI, ENCLOSURE_LO

FUSION_STATUS = "FUSION 360 VALIDATION: NOT CONFIGURED"
STAGE_LABEL = {1: "IDEALIZED — geometry-only packing in the 3U envelope; not an engineering design",
               2: "ENGINEERING-CONSTRAINED — ASSUMED frame and rules; not flight-qualified"}
MFG_LABEL = "manufacturing concept — assumed cost model, not a quote; brackets not stress-analysed"
DEFERRED_FUSION = [
    "Install and configure Autodesk Fusion 360 (not done by this app; it waits for your confirmation).",
    "Review, then run the DRAFT script fusion_import_t2s.py inside Fusion 360 (it has never been run) to load the "
    "placed meshes, one component per part.",
    "Convert the meshes to solid bodies in Fusion 360 and run its interference analysis; compare with the app's "
    "exact-mesh validation (pairs, minimum clearance).",
    "Compare Fusion 360 physical properties (mass, COM, inertia) with assembly.json, using the same densities.",
    "Return the Fusion 360 result to the CAD Validation tab (result ingestion is not built yet).",
]
PALETTE = ["#4e79a7", "#f28e2b", "#59a14f", "#e15759", "#76b7b2", "#edc948", "#b07aa1", "#ff9da7", "#9c755f",
           "#bab0ac", "#86bcb6", "#d37295", "#8cd17d", "#a0cbe8", "#ffbe7d", "#f1ce63", "#499894", "#fabfd2",
           "#d4a6c8", "#79706e"]
HW_COLOUR = {"metal_am": "#c2185b", "sheet": "#607d8b", "machined": "#8d6e63", "catalogue": "#455a64",
             "direct": "#9e9e9e", "standoff": "#78909c"}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _n(x, nd: int = 1, unit: str = "") -> str:
    if x is None:
        return "—"
    try:
        x = float(x)
    except (TypeError, ValueError):
        return str(x)
    if not np.isfinite(x):
        return "—"
    return f"{x:,.{nd}f}{(' ' + unit) if unit else ''}"


def _vec(v, nd: int = 2, unit: str = "mm") -> str:
    if v is None:
        return "—"
    return "(" + ", ".join(f"{float(x):.{nd}f}" for x in v) + f") {unit}"


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", name).strip("._") or "part"


def _orient_text(o: int) -> str:
    R = ROTATIONS_F[o]
    names = []
    for i in range(3):
        j = int(np.argmax(np.abs(R[i])))
        names.append(f"{'+' if R[i, j] > 0 else '-'}{'xyz'[j]}")
    return f"#{o}: world x,y,z = part {', '.join(names)}"


# ================================================================================================ report content
def report_blocks(c, e, version: str, proof: dict | None = None, proof_error: str | None = None) -> list:
    """The report as neutral blocks, rendered to Markdown or HTML. `c` is the Coordinator, `e` a LayoutEntry."""
    lj = c.layout_json(e)
    m = e.metrics or {}
    v = e.validation or {}
    B: list = []
    B.append(("h1", f"TEXT-TO-SPACESHIP layout report — {e.id}"))
    B.append(("note", STAGE_LABEL.get(e.stage, "") + (f" · {MFG_LABEL}" if e.mode == "manufacturable" else "")))
    B.append(("note", f"{FUSION_STATUS} — no Fusion 360 cross-check has been made."))
    revs = e.revs or {}
    B.append(("table", ["Item", "Value"], [
        ["Layout", f"{e.id} (hash {e.hash})"],
        ["Status", e.status + (f" — {lj['verdict']}" if lj.get("verdict") else "")],
        ["Stage / mode", f"Stage {e.stage} · {e.mode}"],
        ["Current for the project inputs", "yes" if lj.get("current") else "no (inputs changed since)"],
        ["Created", e.created], ["Report generated", _now()], ["App version", version],
        ["Revisions", " · ".join(f"{k.replace('_rev', '')} r{revs.get(k, 0)}"
                                 for k in ("parts_rev", "constraint_rev", "mass_rev", "weights_rev"))],
    ]))

    # ---- summary
    B.append(("h2", "1  Key results"))
    rows = [
        ["Length used (from the −Z end plate)", _n(m.get("length_used_mm"), 1, "mm"),
         "compactness definition (decision: used Z length)"],
        ["Free length at the +Z end", _n(m.get("free_length_mm"), 1, "mm"), ""],
        ["Parts placed", str(m.get("parts_placed", "—")), ""],
        ["Space used (solid volume / envelope)", _n(100 * m["space_used"], 1, "%") if m.get("space_used") is not None
         else "—", "envelope 100 × 100 × 340.5 mm"],
        ["Minimum clearance (exact meshes)", _n(m.get("min_clearance_mm"), 3, "mm"),
         f"required {_n(m.get('required_clearance_mm'), 1, 'mm')}"],
        ["Mass of the parts", _n(m.get("mass_kg"), 3, "kg"), m.get("mass_note", "")],
    ]
    if m.get("hardware_mass_kg") is not None:
        rows.append(["Mounting hardware", _n(m.get("hardware_mass_kg"), 3, "kg"), "included in COM and inertia"])
    if m.get("frame_mass_kg") is not None:
        rows.append(["ASSUMED frame (walls + rails)", _n(m.get("frame_mass_kg"), 3, "kg"),
                     "excluded from the COM box check (decision U7)"])
    rows += [
        ["Centre of mass", _vec(m.get("com_mm")), "origin at the envelope centre"],
        ["CDS COM box |x| ≤ 20, |y| ≤ 20, |z| ≤ 70 mm (Rev 14.1, “shall”)",
         m.get("com_box_verdict") or ("PASS" if m.get("com_box_ok") else ("FAIL" if m.get("com_box_ok") is False else "—")),
         "margins " + _vec(m.get("com_box_margin_mm"), 1) if m.get("com_box_margin_mm") else ""],
        ["COM distance from the target", _n(m.get("com_error_mm"), 2, "mm"), ""],
        ["Principal moments of inertia", _vec(m.get("principal_kgm2"), 6, "kg·m²"), "about the COM"],
        ["Inertia trace / largest moment", f"{_n(m.get('trace_kgm2'), 6)} / {_n(m.get('lambda_max_kgm2'), 6)} kg·m²", ""],
        ["Products of inertia (norm)", _n(m.get("products_norm_kgm2"), 7, "kg·m²"), ""],
    ]
    total = sum(x for x in (m.get("mass_kg"), m.get("hardware_mass_kg"), m.get("frame_mass_kg")) if x is not None)
    if m.get("mass_kg") is not None:
        rows.append(["CDS 3U mass note (6.00 kg, “Note”)", "below" if total <= 6.0 else "ABOVE",
                     f"parts + hardware + frame = {total:.3f} kg"])
    if m.get("hardware_cost_rel") is not None:
        rows.append(["Hardware relative cost", _n(m.get("hardware_cost_rel"), 1), "ASSUMED cost model; catalogue part = 1"])
    B.append(("table", ["Quantity", "Value", "Note"], rows))
    if lj.get("violations_engineering"):
        B.append(("p", "Engineering violations (the layout is reported, not hidden):"))
        B.append(("ul", list(lj["violations_engineering"])))

    # ---- figure (HTML only)
    B.append(("svg", _views_svg(c, e)))

    # ---- inputs
    B.append(("h2", "2  Input parts"))
    prow = []
    levels = (c.ctx.levels if c.ctx is not None else {}) or {}
    for pid, o, t in e.poses:
        r = c.records.get(pid)
        pe = c.store.entries.get(pid)
        if r is None:
            prow.append([pid, "(no longer in the project)", "", "", "", "", "", ""])
            continue
        lv = levels.get(pid) or {}
        prow.append([r.name, pid, (pe.sha256 if pe else r.sha256)[:16], r.units,
                     _n((r.volume_mm3 or 0) / 1e3, 2, "cm³") if r.volume_mm3 else "WITHHELD",
                     _n(r.mass_kg, 4, "kg") if r.mass_kg is not None else "WITHHELD",
                     f"{r.mass_source} ({r.density_kg_m3:.0f} kg/m³)" if r.mass_source != "USER_MASS" else r.mass_source,
                     " × ".join(f"{x:.1f}" for x in r.obb_extents_mm) + " mm",
                     ", ".join(f"{k}: {x}" for k, x in lv.items()) if lv else "F0"])
    B.append(("table", ["Part", "ID", "SHA-256 (16)", "Units", "Volume", "Mass", "Mass source", "Extents (OBB)",
                        "Detail level in use"], prow))
    B.append(("p", "Density 2,700 kg/m³ is ASSUMED unless a mass or density was entered for the part."))

    # ---- algorithm
    B.append(("h2", "3  Algorithm"))
    a = e.algorithm or {}
    sl = (c.store.settings or {}).get("sliders", {})
    B.append(("table", ["Item", "Value"], [
        ["Algorithm", a.get("label", "—")], ["Why", a.get("reason", "—")],
        ["Search / decoder", f"{a.get('search', '—')} / {a.get('decoder', '—')}"],
        ["Detail", a.get("detail", "—")],
        ["Slider settings now", ", ".join(f"{k} {float(x):.0f}" for k, x in sl.items())],
        ["Score (scalarised, lower is better)", _n(e.g, 4) + f" (normaliser epoch {e.norm_epoch})"],
    ]))

    # ---- placements
    B.append(("h2", "4  Placements"))
    B.append(("p", "World frame: origin at the envelope centre; x, y ∈ [−50, 50] mm, z ∈ [−170.25, 170.25] mm. "
                   "Each part's canonical vertices v map to world as R·v + t."))
    rows = []
    for pid, o, t in e.poses:
        r = c.records.get(pid)
        b = r.orient_bounds[o] if r is not None else None
        rows.append([r.name if r else pid, _orient_text(o), _vec(t, 3),
                     _vec(b[:3] + t, 1) if b is not None else "—", _vec(b[3:] + t, 1) if b is not None else "—"])
    B.append(("table", ["Part", "Orientation", "Translation t", "World box min", "World box max"], rows))

    # ---- validation
    B.append(("h2", "5  Validation"))
    B.append(("table", ["Item", "Value"], [
        ["Certified (exact-mesh validator)", "yes" if v.get("certified") else "NO"],
        ["Validator version / tolerance", f"{v.get('validator_version', '—')} / {_n(v.get('tolerance_mm'), 3, 'mm')}"],
        ["Part pairs checked / frame checks", f"{v.get('pairs', '—')} / {v.get('statics', '—')}"],
        ["Levels used", json.dumps(v.get("levels"), default=str) if v.get("levels") is not None else "—"],
        ["Minimum clearance", _n(v.get("min_clearance_mm"), 3, "mm")],
        ["Checked at", v.get("checked_at", "—")],
        ["Rules relaxed to report an overflow", "yes" if v.get("relaxed_rules") else "no"],
    ]))
    if v.get("violations"):
        B.append(("p", "Validator findings:"))
        B.append(("ul", [json.dumps(x, default=str) if not isinstance(x, str) else x for x in v["violations"][:20]]))
    st2 = lj.get("stage2")
    if st2:
        B.append(("h3", "Stage 2 rules (ASSUMED)"))
        B.append(("ul", list(st2.get("assumed", []))))
        mrows = []
        for pid, info in (st2.get("mounts") or {}).items():
            r = c.records.get(pid)
            mrows.append([r.name if r else pid, "yes" if info.get("ok") else "NO", info.get("how", "")])
        if mrows:
            B.append(("table", ["Part", "Mounted", "How"], mrows))
        B.append(("table", ["Item", "Value"], [
            ["Harness mode / corridor", f"{st2.get('mode', '—')} / {st2.get('corridor') or '—'}"],
            ["Cable channel blocked fraction", _n(st2.get("cable_blocked_fraction"), 3)],
            ["Overflow beyond the end plate", _n(st2.get("overflow_mm"), 1, "mm")],
            ["Insertion order", " → ".join(c.records[p].name if p in c.records else p
                                           for p in (st2.get("insertion_order") or [])) or "—"],
        ]))

    # ---- hardware
    items = lj.get("extra_items") or []
    if items:
        B.append(("h2", "6  Mounting hardware"))
        if e.mode == "manufacturable":
            B.append(("note", MFG_LABEL + ". Metal 3D-printed (AM) brackets are listed first and drawn hatched."))
        rows = []
        for it in sorted(items, key=lambda x: x.get("process") != "metal_am"):
            r = c.records.get(it.get("for_part"))
            rows.append([it["id"], ("AM — " if it.get("process") == "metal_am" else "") + str(it.get("process")),
                         r.name if r else it.get("for_part"), it.get("label", ""), it.get("material") or "—",
                         _n(1000 * it["mass_kg"], 1, "g") if it.get("mass_kg") is not None else "—",
                         _n(it.get("cost_rel"), 1)])
        B.append(("table", ["Item", "Process", "For part", "Type", "Material", "Mass", "Relative cost"], rows))
        mfg = (v.get("brackets") or [])
        if mfg:
            ok = sum(1 for x in mfg if x.get("ok"))
            B.append(("p", f"Exact bracket clearance checks (≥ 1.2 mm from every part they do not hold): "
                           f"{ok} of {len(mfg)} pass."))

    # ---- proof
    B.append(("h2", "7  Proof that the parts fit"))
    if proof is not None:
        cert = proof.get("certificate") or {}
        B.append(("p", f"Full re-validation with separating-plane certificates: "
                       f"{'VALID' if proof.get('valid') else 'NOT VALID'}. The certificate "
                       f"(certificate_{e.id}.json) can be re-checked independently with tools/check_certificate.py; "
                       f"{len(cert.get('pairs', []))} pair certificates, {len(cert.get('statics', []))} frame certificates."))
        B.append(("md", proof.get("markdown", "")))
    else:
        B.append(("p", "The proof was not generated for this report" + (f": {proof_error}" if proof_error else ".")))

    # ---- limitations and deferred work
    B.append(("h2", "8  Assumptions and limitations"))
    lim = [
        "CubeSat Design Specification Rev 14.1 for 3U: 100 × 100 × 340.5 mm envelope; COM box ±20/±20/±70 mm "
        "(“shall”); 6.00 kg is a “Note”.",
        "Parts are rigid STL solids in millimetres; masses use the ASSUMED density 2,700 kg/m³ unless entered.",
        "Search orientations are the 24 axis-aligned ones (the protocol's free-rotation experiment is not "
        "implemented).",
        "The search decoders work on box or height-map proxies; every reported layout was re-checked on the exact "
        "meshes, and only that check certifies it.",
    ]
    if e.stage == 2:
        lim.append("Stage 2 rules (frame, rails, clearances 2.2 / 1.2 mm, PC/104 stack, 3 mm mounting layer, 10 mm "
                   "harness) are ASSUMED engineering stand-ins, not a qualified structure; no loads, thermal or "
                   "vibration analysis.")
    if e.mode == "manufacturable":
        lim.append("Brackets are concepts: no stress analysis, no fastener holes in the meshes, relative cost units "
                   "from an ASSUMED model (not a quote); AlSi10Mg is ASSUMED for metal AM.")
    B.append(("ul", lim))
    B.append(("h2", "9  Deferred: Fusion 360 validation"))
    B.append(("note", FUSION_STATUS))
    B.append(("ol", DEFERRED_FUSION))
    return B


# ================================================================================================ renderers
def _md_cell(x) -> str:
    return str(x).replace("|", "\\|").replace("\n", " ")


def render_markdown(blocks) -> str:
    out = []
    for b in blocks:
        k = b[0]
        if k == "h1":
            out.append(f"# {b[1]}\n")
        elif k == "h2":
            out.append(f"## {b[1]}\n")
        elif k == "h3":
            out.append(f"### {b[1]}\n")
        elif k == "p":
            out.append(b[1] + "\n")
        elif k == "note":
            out.append(f"> **{b[1]}**\n")
        elif k in ("ul", "ol"):
            out.append("\n".join((f"{i + 1}. " if k == "ol" else "- ") + str(x) for i, x in enumerate(b[1])) + "\n")
        elif k == "table":
            out.append("| " + " | ".join(_md_cell(h) for h in b[1]) + " |")
            out.append("|" + "|".join("---" for _ in b[1]) + "|")
            out += ["| " + " | ".join(_md_cell(x) for x in row) + " |" for row in b[2]]
            out.append("")
        elif k == "md":
            out.append(_demote(b[1]) + "\n")
        elif k == "svg":
            out.append("*(The HTML report adds top, front and side views of the layout.)*\n")
    return "\n".join(out)


def _demote(md: str) -> str:
    """Embed a Markdown document under a level-2 heading (its headings move down two levels)."""
    return re.sub(r"^(#{1,4}) ", lambda mt: "#" * min(6, len(mt.group(1)) + 2) + " ", md, flags=re.M)


def _inline(s: str) -> str:
    s = html.escape(s)
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    return s


def _md_to_html(md: str) -> str:
    """Small Markdown subset (headings, lists, tables, code fences, paragraphs) for the embedded proof text."""
    out, para, i = [], [], 0
    lines = md.splitlines()

    def flush():
        if para:
            out.append("<p>" + _inline(" ".join(para)) + "</p>")
            para.clear()
    while i < len(lines):
        ln = lines[i]
        if ln.startswith("```"):
            flush()
            j = i + 1
            while j < len(lines) and not lines[j].startswith("```"):
                j += 1
            out.append("<pre>" + html.escape("\n".join(lines[i + 1:j])) + "</pre>")
            i = j + 1
            continue
        mt = re.match(r"^(#{1,6}) (.*)", ln)
        if mt:
            flush()
            lv = min(6, len(mt.group(1)) + 2)
            out.append(f"<h{lv}>{_inline(mt.group(2))}</h{lv}>")
        elif ln.startswith("|"):
            flush()
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                cells = [x.strip() for x in lines[i].strip().strip("|").split("|")]
                if not all(re.fullmatch(r":?-{2,}:?", x) for x in cells):
                    rows.append(cells)
                i += 1
            if rows:
                out.append("<table><thead><tr>" + "".join(f"<th>{_inline(x)}</th>" for x in rows[0]) + "</tr></thead><tbody>"
                           + "".join("<tr>" + "".join(f"<td>{_inline(x)}</td>" for x in r) + "</tr>" for r in rows[1:])
                           + "</tbody></table>")
            continue
        elif re.match(r"^\s*([-*]|\d+\.) ", ln):
            flush()
            items = []
            while i < len(lines) and re.match(r"^\s*([-*]|\d+\.) ", lines[i]):
                items.append(re.sub(r"^\s*([-*]|\d+\.) ", "", lines[i]))
                i += 1
            out.append("<ul>" + "".join(f"<li>{_inline(x)}</li>" for x in items) + "</ul>")
            continue
        elif not ln.strip():
            flush()
        else:
            para.append(ln.strip())
        i += 1
    flush()
    return "\n".join(out)


CSS = """
:root{--bg:#ffffff;--fg:#1d2330;--muted:#5b6475;--line:#d9dee7;--panel:#f5f7fa;--accent:#2f5d9e;--warn-bg:#fff4e0;
--warn-fg:#7a4b00}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){--bg:#12161d;--fg:#e4e8ef;--muted:#9aa3b2;
--line:#2c3340;--panel:#1a2029;--accent:#8fb3ec;--warn-bg:#3a2b10;--warn-fg:#f3cf8f}}
:root[data-theme="dark"]{--bg:#12161d;--fg:#e4e8ef;--muted:#9aa3b2;--line:#2c3340;--panel:#1a2029;--accent:#8fb3ec;
--warn-bg:#3a2b10;--warn-fg:#f3cf8f}
body{background:var(--bg);color:var(--fg);font:14px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif;margin:0}
main{max-width:1100px;margin:0 auto;padding:24px 16px 48px}
h1{font-size:22px;margin:0 0 12px}h2{font-size:18px;margin:28px 0 8px;border-bottom:1px solid var(--line);padding-bottom:4px}
h3{font-size:15px;margin:18px 0 6px}h4,h5,h6{font-size:14px;margin:14px 0 4px}
.note{background:var(--warn-bg);color:var(--warn-fg);padding:8px 12px;border-radius:6px;margin:6px 0;font-weight:600}
.tw{overflow-x:auto}table{border-collapse:collapse;margin:8px 0;font-size:13px;min-width:50%}
th,td{border:1px solid var(--line);padding:4px 8px;text-align:left;vertical-align:top}
th{background:var(--panel)}pre{background:var(--panel);padding:8px;overflow-x:auto;font-size:12px}
code{font-size:12px}figure{margin:12px 0}figcaption{color:var(--muted);font-size:12px}
svg text{fill:var(--fg);font-size:11px}.legend span{display:inline-block;margin:2px 10px 2px 0;font-size:12px}
.sw{display:inline-block;width:10px;height:10px;margin-right:4px;vertical-align:middle;border:1px solid var(--line)}
"""


def render_html(blocks, title: str) -> str:
    out = []
    for b in blocks:
        k = b[0]
        if k in ("h1", "h2", "h3"):
            out.append(f"<{k}>{html.escape(b[1])}</{k}>")
        elif k == "p":
            out.append(f"<p>{_inline(b[1])}</p>")
        elif k == "note":
            out.append(f'<div class="note">{html.escape(b[1])}</div>')
        elif k in ("ul", "ol"):
            out.append(f"<{k}>" + "".join(f"<li>{_inline(str(x))}</li>" for x in b[1]) + f"</{k}>")
        elif k == "table":
            out.append('<div class="tw"><table><thead><tr>' + "".join(f"<th>{html.escape(str(h))}</th>" for h in b[1])
                       + "</tr></thead><tbody>" + "".join("<tr>" + "".join(f"<td>{html.escape(str(x))}</td>" for x in row)
                                                          + "</tr>" for row in b[2]) + "</tbody></table></div>")
        elif k == "md":
            out.append(_md_to_html(b[1]))
        elif k == "svg":
            out.append(b[1])
    return ("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
            f"<title>{html.escape(title)}</title><style>{CSS}</style></head><body><main>"
            + "\n".join(out) + "</main></body></html>")


# ================================================================================================ figure
def _hull2d(pts: np.ndarray) -> np.ndarray:
    from scipy.spatial import ConvexHull
    try:
        h = ConvexHull(pts)
        return pts[h.vertices]
    except Exception:  # noqa: BLE001 - degenerate projection: its bounding rectangle
        lo, hi = pts.min(0), pts.max(0)
        return np.array([[lo[0], lo[1]], [hi[0], lo[1]], [hi[0], hi[1]], [lo[0], hi[1]]])


def _hardware_points(c, e) -> list:
    out = []
    for it in c._extra_items(e):
        try:
            buf = c.item_mesh(it["id"])
        except KeyError:
            continue
        nv = int(np.frombuffer(buf[:4], "<u4")[0])
        out.append((it, np.frombuffer(buf[8:8 + 12 * nv], "<f4").reshape(-1, 3).astype(float)))
    return out


def _views_svg(c, e) -> str:
    """Top, front and side projections of the convex hull of every part (concave parts look fuller than they are)
    and of the hardware; numbers on the frame are millimetres."""
    s = 1.25                                    # px per mm
    lo, hi = ENCLOSURE_LO, ENCLOSURE_HI
    # (title, horizontal axis, vertical axis, depth axis, sign so that farther shapes sort first)
    views = [("Top (looking down −Z)", 0, 1, 2, 1.0), ("Front (looking along +Y)", 0, 2, 1, -1.0),
             ("Side (looking along −X)", 1, 2, 0, 1.0)]
    shapes = []
    for k, (pid, o, t) in enumerate(e.poses):
        g = c.geoms.get(pid)
        if g is None:
            continue
        shapes.append((c.records[pid].name if pid in c.records else pid, PALETTE[k % len(PALETTE)], False,
                       to_world(g.hull_pts, o, np.asarray(t, float))))
    for it, pts in _hardware_points(c, e):
        shapes.append((it["id"], HW_COLOUR.get(it.get("process"), "#666"), it.get("process") == "metal_am", pts))
    pad, gap = 24, 30
    x0 = pad
    parts_svg = []
    for title, a, b, dax, sgn in views:
        w, h = (hi[a] - lo[a]) * s, (hi[b] - lo[b]) * s
        y0 = pad + 14

        def X(u, a=a, x0=x0):
            return x0 + (u - lo[a]) * s

        def Y(u, b=b, y0=y0, h=h):
            return y0 + h - (u - lo[b]) * s
        g = [f'<text x="{x0:.1f}" y="{pad:.1f}">{html.escape(title)}</text>',
             f'<rect x="{x0:.1f}" y="{y0:.1f}" width="{w:.1f}" height="{h:.1f}" fill="none" stroke="currentColor" '
             f'stroke-opacity="0.6"/>']
        for name, col, am, pts in sorted(shapes, key=lambda sh, d=dax, k=sgn: k * float(sh[3][:, d].mean())):
            poly = _hull2d(pts[:, [a, b]])
            d = " ".join(f"{X(p[0]):.1f},{Y(p[1]):.1f}" for p in poly)
            fill = "url(#am)" if am else col
            g.append(f'<polygon points="{d}" fill="{fill}" fill-opacity="{0.85 if am else 0.55}" stroke="{col}" '
                     f'stroke-width="1"><title>{html.escape(name)}</title></polygon>')
        g.append(f'<text x="{x0:.1f}" y="{y0 + h + 14:.1f}">{"xyz"[a]} {lo[a]:g}…{hi[a]:g}, '
                 f'{"xyz"[b]} {lo[b]:g}…{hi[b]:g} mm</text>')
        parts_svg.append("".join(g))
        x0 += w + gap
    H = pad + 14 + (hi[2] - lo[2]) * s + 24
    W = x0 - gap + pad
    defs = ('<defs><pattern id="am" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">'
            f'<rect width="6" height="6" fill="{HW_COLOUR["metal_am"]}"/><line x1="0" y1="0" x2="0" y2="6" '
            'stroke="#ffffff" stroke-width="2"/></pattern></defs>')
    legend = "".join(f'<span><i class="sw" style="background:{col}"></i>{html.escape(name)}'
                     f'{" (metal AM, hatched)" if am else ""}</span>' for name, col, am, _ in shapes)
    return (f'<figure><svg viewBox="0 0 {W:.0f} {H:.0f}" width="100%" style="max-width:{W:.0f}px" role="img" '
            f'aria-label="Top, front and side views of the layout">{defs}{"".join(parts_svg)}</svg>'
            f'<figcaption>Convex-hull silhouettes of each part (concave parts look fuller than they are) and the '
            f'mounting hardware, projected on three planes.</figcaption><div class="legend">{legend}</div></figure>')


# ================================================================================================ files
def _placed_parts(c, e):
    for pid, o, t in e.poses:
        r = c.records.get(pid)
        if r is None:
            continue
        yield pid, r, o, np.asarray(t, float)


def _hardware_meshes(c, e):
    for it in c._extra_items(e):
        try:
            buf = c.item_mesh(it["id"])
        except KeyError:
            continue
        nv, nf = (int(x) for x in np.frombuffer(buf[:8], "<u4"))
        v = np.frombuffer(buf[8:8 + 12 * nv], "<f4").reshape(-1, 3).astype(float)
        f = np.frombuffer(buf[8 + 12 * nv:8 + 12 * nv + 12 * nf], "<u4").reshape(-1, 3).astype(np.int64)
        name = ("AM_" if it.get("process") == "metal_am" else f"{it.get('process')}_") + _safe(it["id"])
        yield it, name, v, f


def stl_zip(c, e, version: str) -> bytes:
    """Every placed part (world coordinates, mm) and every hardware item as binary STL, plus the layout JSON."""
    buf = io.BytesIO()
    lj = c.layout_json(e)
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        names = []
        for pid, r, o, t in _placed_parts(c, e):
            fn = f"parts/{_safe(pid)}_{_safe(r.name)}.stl"
            z.writestr(fn, stl_bytes(to_world(r.v, o, t), r.f, f"t2s {e.id} {r.name} world mm"))
            names.append(fn)
        for it, name, v, f in _hardware_meshes(c, e):
            fn = f"hardware/{name}.stl"
            z.writestr(fn, stl_bytes(v, f, f"t2s {e.id} {it['id']} {it.get('process')}"))
            names.append(fn)
        z.writestr(f"layout_{e.id}.json", json.dumps(lj, indent=1))
        z.writestr("README.txt", "\n".join([
            f"TEXT-TO-SPACESHIP {version} — placed STL files for layout {e.id} (hash {e.hash})",
            STAGE_LABEL.get(e.stage, ""), (MFG_LABEL if e.mode == "manufacturable" else ""),
            f"Status: {e.status}. Units: millimetres. World frame: origin at the 3U envelope centre, "
            f"x,y in [-50, 50], z in [-170.25, 170.25].",
            "Metal 3D-printed brackets are the files hardware/AM_*.stl.",
            FUSION_STATUS, "", "Files:", *names, ""]))
    return buf.getvalue()


FUSION_SCRIPT = '''"""DRAFT - NEVER RUN. Autodesk Fusion 360 was not installed or configured when this package was made
(FUSION 360 VALIDATION: NOT CONFIGURED). Review it before use.

It only imports the placed meshes (millimetres, world coordinates) as mesh bodies, one new component per part or
hardware item. Interference analysis and physical-property comparison need solid bodies and are deferred tasks
(see README.md); this script does not do them.
"""
import json
import os
import traceback

import adsk.core
import adsk.fusion


def run(context):
    ui = None
    try:
        app = adsk.core.Application.get()
        ui = app.userInterface
        here = os.path.dirname(os.path.abspath(__file__))
        with open(os.path.join(here, "assembly.json"), encoding="utf-8") as fh:
            asm = json.load(fh)
        app.documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType)
        design = adsk.fusion.Design.cast(app.activeProduct)
        root = design.rootComponent
        parametric = design.designType == adsk.fusion.DesignTypes.ParametricDesignType
        items = asm["parts"] + asm["hardware"]
        for item in items:
            occ = root.occurrences.addNewComponent(adsk.core.Matrix3D.create())
            comp = occ.component
            comp.name = item["name"]
            path = os.path.join(here, item["file_world"])
            if parametric:
                base = comp.features.baseFeatures.add()
                base.startEdit()
                comp.meshBodies.add(path, adsk.fusion.MeshUnits.MillimeterMeshUnit, base)
                base.finishEdit()
            else:
                comp.meshBodies.add(path, adsk.fusion.MeshUnits.MillimeterMeshUnit)
        ui.messageBox("Imported %d meshes (mm). Validation steps are listed in README.md." % len(items))
    except Exception:
        if ui:
            ui.messageBox("Import failed:\\n" + traceback.format_exc())
'''


def fusion_package(c, e, version: str, report_md: str, proof: dict | None, checker_path=None) -> bytes:
    """Files a later Fusion 360 cross-check needs: placed and canonical meshes, transforms, the app's mass
    properties and validation results for comparison, the report, the proof certificate and a DRAFT import script."""
    phys = c._phys()
    buf = io.BytesIO()
    parts, hardware = [], []
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for pid, r, o, t in _placed_parts(c, e):
            base = f"{_safe(pid)}_{_safe(r.name)}"
            R = ROTATIONS_F[o]
            z.writestr(f"parts_world/{base}.stl", stl_bytes(to_world(r.v, o, t), r.f, f"t2s {r.name} world mm"))
            z.writestr(f"parts_canonical/{base}.stl", stl_bytes(r.v, r.f, f"t2s {r.name} canonical mm"))
            T = np.eye(4)
            T[:3, :3], T[:3, 3] = R, t
            p = phys.get(pid)
            pe = c.store.entries.get(pid)
            parts.append({
                "id": pid, "name": r.name, "source_file": pe.file if pe else r.file,
                "source_sha256": pe.sha256 if pe else r.sha256, "source_units": r.units,
                "file_world": f"parts_world/{base}.stl", "file_canonical": f"parts_canonical/{base}.stl",
                "canonical_to_world_4x4_mm": T.tolist(), "orientation_index": int(o), "translation_mm": t.tolist(),
                "density_kg_m3": r.density_kg_m3, "mass_source": r.mass_source,
                "app_mass_kg": p.mass_kg if p else None,
                "app_com_world_mm": (R @ p.com_can_mm + t).tolist() if p else None,
                "app_inertia_world_about_com_kgm2": (R @ p.inertia_com_kgm2 @ R.T).tolist() if p else None,
                "app_volume_mm3": r.volume_mm3,
            })
        for it, name, v, f in _hardware_meshes(c, e):
            z.writestr(f"hardware/{name}.stl", stl_bytes(v, f, f"t2s {it['id']} {it.get('process')}"))
            hardware.append({"id": it["id"], "name": name, "process": it.get("process"), "metal_am": it.get("process") == "metal_am",
                             "for_part": it.get("for_part"), "file_world": f"hardware/{name}.stl",
                             "material": it.get("material"), "app_mass_kg": it.get("mass_kg")})
        m = e.metrics or {}
        asm = {
            "format": "t2s-fusion-package/1", "app_version": version, "generated": _now(), "status": FUSION_STATUS,
            "layout": {"id": e.id, "hash": e.hash, "stage": e.stage, "mode": e.mode, "status": e.status,
                       "label": STAGE_LABEL.get(e.stage)},
            "units": "mm", "frame": {"origin": "3U envelope centre", "envelope_min_mm": ENCLOSURE_LO.tolist(),
                                     "envelope_max_mm": ENCLOSURE_HI.tolist()},
            "parts": parts, "hardware": hardware,
            "app_results": {k: m.get(k) for k in ("mass_kg", "hardware_mass_kg", "com_mm", "inertia_kgm2",
                                                  "principal_kgm2", "min_clearance_mm", "length_used_mm")}
            | {"validation": {k: (e.validation or {}).get(k) for k in ("certified", "pairs", "statics", "min_clearance_mm",
                                                                      "validator_version", "tolerance_mm")}},
            "deferred_tasks": DEFERRED_FUSION,
        }
        z.writestr("assembly.json", json.dumps(asm, indent=1, default=float))
        z.writestr("fusion_import_t2s.py", FUSION_SCRIPT)
        z.writestr(f"report_{e.id}.md", report_md)
        if proof is not None:
            z.writestr(f"proof_{e.id}.md", proof.get("markdown", ""))
            z.writestr(f"certificate_{e.id}.json", json.dumps(proof.get("certificate"), indent=1, default=float))
        if checker_path is not None and checker_path.exists():
            z.writestr("check_certificate.py", checker_path.read_bytes())
        z.writestr("README.md", "\n".join([
            f"# Fusion 360 export package — layout {e.id}", "", f"**{FUSION_STATUS}.** This package was prepared "
            "by TEXT-TO-SPACESHIP; no Fusion 360 API call has been made and nothing in it has been checked in "
            "Fusion 360.", "",
            f"- Layout {e.id} (hash {e.hash}), status {e.status}; {STAGE_LABEL.get(e.stage)}.",
            "- `parts_world/` — every part placed in world coordinates (mm); `parts_canonical/` — the same parts in "
            "their canonical frame, with `canonical_to_world_4x4_mm` in `assembly.json`.",
            "- `hardware/` — mounting hardware; metal 3D-printed brackets are `hardware/AM_*.stl`.",
            "- `assembly.json` — transforms, densities and the app's own mass properties and validation results "
            "(for comparison).",
            f"- `report_{e.id}.md`, `proof_{e.id}.md`, `certificate_{e.id}.json`, `check_certificate.py` — the "
            "app's report and its independently checkable proof.",
            "- `fusion_import_t2s.py` — a DRAFT Fusion 360 script that has never been run.", "",
            "## Deferred tasks", "", *[f"{i + 1}. {x}" for i, x in enumerate(DEFERRED_FUSION)], ""]))
    return buf.getvalue()
