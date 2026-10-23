"""Generative-design contest: every entrant designs the same metal-AM bracket problems; every design is meshed and
checked with CalculiX and NGSolve under the same loads and pass criteria (gd.evaluate).

Problems (ASSUMED part masses; the parts come from the synthetic test set, the brackets are typical of what the V2
packing reserves):
  P1 flat box 60 × 40 × 30 mm, 0.35 kg, −X side 20 mm from the wall (a long-gap flat mount);
  P2 capsule tank (gas_tank_capsule), 0.30 kg, held on its curved side 12 mm from the wall, bracket wraps 8 mm;
  P3 spherical tank (propellant_tank_sphere), 0.40 kg, 25 mm from the wall, bracket wraps 10 mm.

Each generative entrant runs a volume-fraction ladder (lightest first) and stops at the first design that passes;
the lightest passing design is its result. Ranking: problems passed (more is better), then total mass, where a failed
problem counts as the machined-block reference mass (the heaviest sensible bracket). The two references (machined
block, sheet Z-bracket) are shown for scale and cannot win.
"""
from __future__ import annotations

import importlib
import json
import time
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from .domain import (
    F1_PASS,
    F1_TARGET,
    FOS_ULT,
    FOS_YIELD,
    LIMIT_G,
    MATERIAL,
    box_part_domain,
    domain_from_bracket,
)

ENTRANTS = {   # key -> (module, display name source)
    "baseline": ("t2s.gd.entrants.baseline_shell", "generate", "V1 rule (SDF shell + plate + ribs), this project"),
    "pymoto": ("t2s.gd.entrants.pymoto_simp", "generate", "pyMOTO 2.0.1 (TU Delft), SIMP + MMA"),
    "pytopo3d": ("t2s.gd.entrants.pytopo3d_simp", "generate", "pytopo3d 0.3.0, 3D SIMP"),
    "beso": ("t2s.gd.entrants.beso_ccx", "generate", "BESO for CalculiX (calculix/beso)"),
}
REFERENCES = {
    "block": ("t2s.gd.entrants.baseline_shell", "machined_block", "reference: whole reserved space solid"),
    "sheet": ("t2s.gd.entrants.baseline_shell", "sheet_bracket", "reference: 1.5 mm sheet Z-bracket"),
}
VOL_LADDER = (0.12, 0.2, 0.3, 0.45)
CRITERIA = [f"{LIMIT_G:.0f} g quasi-static in X, Y, Z separately (part inertia on the contact faces + bracket self-weight)",
            f"FoS {FOS_YIELD} yield / {FOS_ULT} ultimate on {MATERIAL['yield_mpa']:.0f} / {MATERIAL['ultimate_mpa']:.0f} MPa "
            f"(AlSi10Mg L-PBF stress-relieved)",
            f"first frequency with the part ≥ {F1_PASS:.0f} Hz (target {F1_TARGET:.0f} Hz), E = {MATERIAL['E_mpa'] / 1000:.0f} GPa",
            "peak von Mises over both solvers, nodes on the bolted face excluded (constraint singularity)",
            "solid inside the reserved box, joined to the wall and the part"]


def _load_part(name: str):
    from ..parts.build import build_part
    data = Path(__file__).resolve().parents[4] / "data" / "synthetic"
    man = json.loads((data / "manifest.json").read_text())
    p = next(x for x in man["parts"] if x["name"] == name)
    return build_part((data / p["file"]).read_bytes(), name, name, file=p["file"])


def _curved_problem(name: str, part: str, mass: float, gap: float, wrap: float, foot: float, h: float, axis: int = 0):
    """Part `part` (canonical orientation 0) with its −`axis` bounding-box side `gap` mm from a wall at 0; the reserved
    box covers `foot` of that side, centred, and reaches `wrap` mm into the bounding box."""
    rec = _load_part(part)
    lo, hi = rec.v.min(0), rec.v.max(0)
    t = -0.5 * (lo + hi)
    t[axis] = gap - lo[axis]
    plo, phi = lo + t, hi + t
    r = np.concatenate([plo, phi])
    r[axis], r[3 + axis] = 0.0, gap + wrap
    for k in range(3):
        if k != axis:
            mid, half = 0.5 * (plo[k] + phi[k]), 0.5 * foot * (phi[k] - plo[k])
            r[k], r[3 + k] = mid - half, mid + half
    b = {"name": name, "reserve": r.tolist(), "axis": axis, "neg": True, "plane_mm": 0.0}
    return domain_from_bracket(b, rec, 0, t, h, mass, 0.2, name)


def problems(h: float = 1.0):
    out = [
        (box_part_domain(gap=20.0, foot=(36.0, 24.0), mass_kg=0.35, h=h, name="P1 flat box, 20 mm gap"),
         "60 × 40 × 30 mm box, 0.35 kg, flat side 20 mm from the wall"),
        (_curved_problem("P2 capsule tank, 12 mm gap", "gas_tank_capsule", 0.30, 12.0, 8.0, 0.8, h),
         "capsule tank 0.30 kg on its curved side, 12 mm gap, bracket wraps 8 mm"),
        (_curved_problem("P3 spherical tank, 25 mm gap", "propellant_tank_sphere", 0.40, 25.0, 10.0, 0.8, h),
         "spherical tank 0.40 kg, 25 mm gap, bracket wraps 10 mm"),
    ]
    return out


def _fn(spec):
    mod, fn, _ = spec
    m = importlib.import_module(mod)
    return getattr(m, fn), m


def run_contest(out_dir: str | Path, h: float = 1.0, budget_s: float = 240.0, threads: int = 2,
                entrants=None, log=print) -> dict:
    from .evaluate import evaluate
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    probs = problems(h)
    rows, entrant_info, meshes = [], [], {}
    keys = list(entrants or ENTRANTS)
    for key in keys + list(REFERENCES):
        spec = ENTRANTS.get(key) or REFERENCES[key]
        try:
            fn, mod = _fn(spec)
            avail = bool(getattr(mod, "available", lambda: True)())
            name = getattr(mod, "NAME", key) if key in ENTRANTS else None
            note = None if avail else "not available on this machine"
        except Exception as exc:  # noqa: BLE001
            fn, avail, name, note = None, False, key, f"import failed: {exc!r}"
        entrant_info.append({"key": key, "name": name or key, "source": spec[2], "available": avail, "note": note,
                             "reference": key in REFERENCES})
        if not avail:
            log(f"[contest] {key}: skipped ({note})")
            continue
        for dom, _ in probs:
            ladder = VOL_LADDER if key in ENTRANTS and key != "baseline" else (None,)
            best = None
            for vf in ladder:
                if vf is not None:
                    dom.vol_frac = vf
                t0 = time.perf_counter()
                try:
                    g = fn(dom, budget_s=budget_s, threads=threads)
                except Exception as exc:  # noqa: BLE001
                    log(f"[contest] {key} on {dom.name} vf={vf}: generator failed {exc!r}")
                    best = best or {"problem": dom.name, "generator": name or key, "key": key, "ok": False,
                                    "passed": False, "reason": f"generator failed: {exc!r}"}
                    break
                ev = evaluate(dom, g, threads=threads)
                row = ev.summary()
                row.update(problem=dom.name, generator=g.generator, vol_frac=vf, key=key,
                           iterations=g.iterations, notes=g.notes)
                row["solvers"] = ev.solvers
                log(f"[contest] {key} {dom.name} vf={vf}: mass {row['mass_g']} g, σ {row['sigma_mpa']}, "
                    f"f1 {row['f1_hz']}, passed {row['passed']} ({time.perf_counter() - t0:.0f} s)")
                if ev.mesh is not None:
                    row["stl"] = f"{key}_{dom.name.split()[0]}_vf{vf}.stl"
                    _write_stl(out_dir / row["stl"], *ev.mesh)
                    meshes[(key, dom.name, vf)] = ev.mesh
                if best is None or (row["passed"] and not best.get("passed")) or \
                        (not best.get("passed") and (row.get("ms_yield") or -9) > (best.get("ms_yield") or -9)):
                    best = row
                if row["passed"]:
                    break
            rows.append(best)
            _save(out_dir, probs, entrant_info, rows, "RUNNING")
    res = _save(out_dir, probs, entrant_info, rows, "DONE")
    if res["winner"]:                       # mesh-refinement check of the winner's designs
        from .domain import GenResult
        conv = []
        for dom, _ in probs:
            r = next((x for x in rows if x.get("key") == res["winner"]["key"] and x["problem"] == dom.name), None)
            mesh = meshes.get((res["winner"]["key"], dom.name, r.get("vol_frac"))) if r else None
            if mesh is None or not r.get("ok"):
                continue
            if r.get("vol_frac") is not None:
                dom.vol_frac = r["vol_frac"]
            fine = evaluate(dom, GenResult(None, 0.0, r["generator"], mesh=mesh), threads=threads, h_fea=0.75 * dom.h)
            conv.append({"problem": dom.name, "note": "surface triangles split in four, interior element size 0.75 h",
                         "sigma_mpa": [r["sigma_mpa"], fine.sigma_mpa],
                         "f1_hz": [r["f1_hz"], fine.f1_hz], "n_nodes": [r.get("n_nodes"), fine.n_nodes],
                         "sigma_change": (fine.sigma_mpa - r["sigma_mpa"]) / r["sigma_mpa"] if fine.sigma_mpa else None,
                         "f1_change": (fine.f1_hz - r["f1_hz"]) / r["f1_hz"] if fine.f1_hz else None,
                         "passed_fine": fine.passed})
            log(f"[contest] refinement {dom.name}: σ {r['sigma_mpa']:.1f} → {fine.sigma_mpa}, f1 {r['f1_hz']:.0f} → "
                f"{fine.f1_hz}")
        res["winner"]["refinement"] = conv
        (out_dir / "results.json").write_text(json.dumps(res, indent=1, default=float), encoding="utf-8")
    return res


def _write_stl(path: Path, v, f):
    from ..geometry.stl_io import write_binary_stl
    write_binary_stl(str(path), np.asarray(v, float), np.asarray(f, np.int64))


def standings(rows, entrant_info):
    block = {r["problem"]: r.get("mass_g") for r in rows if r.get("key") == "block"}
    out = []
    for e in entrant_info:
        if e["reference"] or not e["available"]:
            continue
        mine = [r for r in rows if r.get("key") == e["key"]]
        passed = sum(1 for r in mine if r.get("passed"))
        total = sum((r["mass_g"] if r.get("passed") else (block.get(r["problem"]) or 1e9)) for r in mine)
        out.append({"generator": e["name"], "key": e["key"], "passed": passed, "problems": len(mine),
                    "total_mass_g": total if mine else None})
    out.sort(key=lambda s: (-s["passed"], s["total_mass_g"] if s["total_mass_g"] is not None else 1e18))
    for i, s in enumerate(out):
        s["rank"] = i + 1
    return out


def contest_markdown(res: dict) -> str:
    """docs/V2-GD-CONTEST.md from results.json: every number below is read from the measured results."""
    def n(x, fmt=".1f", unit=""):
        return "—" if x is None else f"{x:{fmt}}{unit}"
    L = ["# V2 generative-design contest — metal 3D-printed brackets", "",
         f"Results of `scripts/gd_contest.py` ({res['created']}, status {res['status']}). Every design is meshed "
         "(quadratic tetrahedra) and solved with **CalculiX 2.23 and NGSolve 6.2.2608** under the same loads; margins "
         "use the larger peak stress and the lower first frequency of the two.", "", "## Criteria (ASSUMED)", ""]
    L += [f"* {c}" for c in res["criteria"]]
    L += ["", "## Entrants", "", "| Entrant | Source | Run |", "|---|---|---|"]
    for e in res["entrants"]:
        L.append(f"| {e['name']} | {e['source']} | {'yes' if e['available'] else 'no — ' + (e.get('note') or '')}"
                 f"{' (reference, cannot win)' if e.get('reference') else ''} |")
    L += ["", "## Problems", "", "| Problem | Description | Part mass | Voxel grid |", "|---|---|---|---|"]
    for p in res["problems"]:
        L.append(f"| {p['name']} | {p['description']} | {p['part_mass_kg']:.2f} kg | "
                 f"{' × '.join(map(str, p['grid']))} at {p['voxel_mm']} mm |")
    L += ["", "## Results", ""]
    for p in res["problems"]:
        L += [f"### {p['name']}", "", "| Generator | Vol. frac. | Mass | Peak σ | MS yield | MS ult. | f1 (with part) | "
              "σ agreement | Time | Result |", "|---|---|---|---|---|---|---|---|---|---|"]
        for r in [x for x in res["rows"] if x["problem"] == p["name"]]:
            ag = (r.get("agreement") or {}).get("sigma_rel")
            t = (r.get("gen_seconds") or 0) + (r.get("fea_seconds") or 0)
            L.append(f"| {r['generator']} | {n(r.get('vol_frac'), '.2f')} | {n(r.get('mass_g'), '.1f', ' g')} | "
                     f"{n(r.get('sigma_mpa'), '.0f', ' MPa')} | {n(r.get('ms_yield'), '+.2f')} | {n(r.get('ms_ult'), '+.2f')} | "
                     f"{n(r.get('f1_hz'), '.0f', ' Hz')} | {n(None if ag is None else 100 * ag, '.4f', ' %')} | "
                     f"{t:.0f} s | {'PASS' if r.get('passed') else ('FAIL' if r.get('ok') else 'NO DESIGN')}"
                     f"{(': ' + r['reason']) if r.get('reason') else ''} |")
        L.append("")
    L += ["## Standings", "", "| Rank | Generator | Passed | Total mass (failed problem = machined block) |",
          "|---|---|---|---|"]
    for s in res["standings"]:
        L.append(f"| {s['rank']} | {s['generator']} | {s['passed']}/{s['problems']} | {n(s['total_mass_g'], '.1f', ' g')} |")
    w = res.get("winner")
    L += ["", "## Winner", "", f"**{w['generator']}** — {w['why']}." if w else "No entrant passed a problem.", ""]
    if w and w.get("refinement"):
        L += ["Mesh-refinement check of the winner's designs (surface triangles split in four, finer interior):", "",
              "| Problem | Peak σ (base → fine) | f1 (base → fine) | Still passes |", "|---|---|---|---|"]
        for c in w["refinement"]:
            s0, s1 = c["sigma_mpa"]
            f0, f1 = c["f1_hz"]
            L.append(f"| {c['problem']} | {n(s0, '.0f')} → {n(s1, '.0f')} MPa ({n(None if c['sigma_change'] is None else 100 * c['sigma_change'], '+.1f', ' %')}) | "
                     f"{n(f0, '.0f')} → {n(f1, '.0f')} Hz ({n(None if c['f1_change'] is None else 100 * c['f1_change'], '+.1f', ' %')}) | "
                     f"{'yes' if c['passed_fine'] else 'NO'} |")
        L.append("")
    L += ["## Notes", "",
          "* The two solvers solve the same discrete problem exactly, so their agreement verifies the implementations; "
          "mesh accuracy is checked by the refinement above and by the analytical benchmarks in the solver tests.",
          "* Peak stresses exclude only the nodes on the bolted face (the clamp is singular there); fasteners, bearing "
          "and fillets are not modelled (hand calculations per the research note).",
          "* Generators get the same time budget per run; their own settings are in their module docstrings. "
          "The volume-fraction ladder stops at the first passing design, so the reported design is the lightest "
          "passing one on that ladder.",
          "* Material values are typical datasheet values, not A/B-basis allowables; ASSUMED, not flight-qualified.", ""]
    return "\n".join(L)


def _save(out_dir: Path, probs, entrant_info, rows, status) -> dict:
    st = standings(rows, entrant_info)
    win = None
    if st and status == "DONE" and st[0]["passed"]:
        w = st[0]
        why = (f"passed {w['passed']}/{w['problems']} problems with the lowest total mass "
               f"({w['total_mass_g']:.1f} g; a failed problem counts as the machined block)")
        win = {"generator": w["generator"], "key": w["key"], "why": why}
    res = {"created": datetime.now(UTC).isoformat(timespec="seconds"), "status": status, "criteria": CRITERIA,
           "problems": [{"name": d.name, "description": desc, "part_mass_kg": d.part_mass_kg,
                         "reserve_mm": [round(float(x), 3) for x in d.reserve], "voxel_mm": d.h,
                         "grid": list(d.shape)} for d, desc in probs],
           "entrants": entrant_info, "rows": rows, "standings": st, "winner": win}
    (out_dir / "results.json").write_text(json.dumps(res, indent=1, default=float), encoding="utf-8")
    return res
