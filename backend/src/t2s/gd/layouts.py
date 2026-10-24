"""Bracket layouts (M4): three ways to hold the parts of one Stage 2 layout, to compare and choose from.

* per_part — one bracket per part (the design job of gd.design; unchanged, the default);
* combined — neighbouring metal-AM brackets on one wall (or corner rail) joined into one print (gd.multi);
* one_piece — one printed piece that holds every part except the PC/104 boards (gd.multi; exploratory).

The jobs here run in the coordinator's process pool, one at a time (as the per-part design job), and write
progress.json after every step: one row per combined bracket, or the phases of the one piece, for the progress bars.
Each design runs the volume-fraction ladder of the per-part designs (lightest first, the first passing rung is the
FEA minimum) or one set value, in the bracket's material, with the minimum member thickness as the filter radius and
the plate / skin thickness (combined; the one piece uses it for the filter and the joins).

Comparison numbers per layout (summary): the bracket mass in total (every bracket of that layout, fasteners included,
the PC/104 rods and standoffs left out as they are the same in every layout), the worst margin and its check, the
system's first natural frequency (the lowest over the brackets with their parts), the number of printed pieces and
the largest one's size, checked against an L-PBF build volume of 250 × 250 × 325 mm (ASSUMED: a typical metal L-PBF
machine, mfg.brackets.BUILD_VOLUME).
"""
from __future__ import annotations

import contextlib
import json
import os
import pickle
import threading
import time
from pathlib import Path

import numpy as np

MODES = ("per_part", "combined", "one_piece")
MODE_NAMES = {"per_part": "one bracket per part", "combined": "combined per wall", "one_piece": "one piece"}
# a solve must leave this much memory available (the user's machine has 16 GB); T2S_MEM_RESERVE_MB overrides it
MEM_RESERVE_MB = float(os.environ.get("T2S_MEM_RESERVE_MB", "2000"))
# memory per 1000 dofs, measured on a combined bracket of L-2002 (p17 + p10, 67 023 tet10 nodes, 201 069 dofs;
# docs/notes/m4.md): the whole job process peaked at 1099 MB with NGSolve's 18 cases (5.5 MB / kdof), CalculiX's
# ccx.exe at 742 MB (3.7 MB / kdof, 4.5 taken: fill-in grows faster than the dofs)
MB_PER_KDOF = {"NGSolve": 5.5, "CalculiX": 4.5,
               # CalculiX's iterative Cholesky on the same mesh: 441 MB for the whole process tree, 201 MB before
               # (1.2 MB / kdof; 2.0 taken)
               "CalculiX-iterative": 2.0,
               # the optimiser's fine level (gd.simp): measured on the one piece of L-2002's coarse level, 39 828 dofs,
               # about 5.1 MB / kdof above the domain; 9.0 ASSUMED at ~270 k dofs (the factorisation's fill grows
               # faster than the dofs)
               "SIMP": 9.0}
COMBINED_H_MAX = 1.5          # mm: a combined bracket's voxel (as a per-part bracket's, design_h)
COMBINED_MAX_VOXELS = 400_000


def build_volume() -> tuple:
    from ..mfg.brackets import BUILD_VOLUME
    return tuple(float(x) for x in BUILD_VOLUME)


def fits_build_volume(size) -> bool:
    """A print fits when its bounding box, in some orientation, fits the build volume (sorted extents)."""
    s = sorted(float(x) for x in size)
    b = sorted(build_volume())
    return all(x <= y + 1e-9 for x, y in zip(s, b))


# =================================================================================================== memory
class MemWatch:
    """Peak resident memory of this process and its children (CalculiX), sampled every 0.5 s."""

    def __init__(self):
        self.peak_mb = 0.0
        self._stop = threading.Event()
        self._t = threading.Thread(target=self._run, daemon=True)

    def _rss(self) -> float:
        try:
            import psutil
            p = psutil.Process()
            tot = p.memory_info().rss
            for c in p.children(recursive=True):
                with contextlib.suppress(psutil.Error):          # a child that just ended
                    tot += c.memory_info().rss
            return tot / 2 ** 20
        except Exception:  # noqa: BLE001 - no psutil: no measurement
            return 0.0

    def _run(self):
        while not self._stop.is_set():
            self.peak_mb = max(self.peak_mb, self._rss())
            self._stop.wait(0.5)

    def __enter__(self):
        self._t.start()
        return self

    def __exit__(self, *a):
        self._stop.set()
        self._t.join(timeout=2.0)
        self.peak_mb = max(self.peak_mb, self._rss())


def available_mb() -> float | None:
    try:
        import psutil
        return psutil.virtual_memory().available / 2 ** 20
    except Exception:  # noqa: BLE001
        return None


def mem_guard(ndof: int, what: str) -> None:
    """Raise MemoryError when a solve of `ndof` degrees of freedom would leave less than MEM_RESERVE_MB available
    (the predicted need: MB_PER_KDOF, ASSUMED until measured)."""
    need = MB_PER_KDOF.get(what, 9.0) * ndof / 1000.0
    avail = available_mb()
    if avail is not None and avail - need < MEM_RESERVE_MB:
        raise MemoryError(f"{what} with {ndof} dofs needs about {need:.0f} MB; {avail:.0f} MB available, "
                          f"{MEM_RESERVE_MB:.0f} MB must stay free")


# =================================================================================================== solids
def _mesh_bin(v, f) -> bytes:
    v = np.asarray(v, "<f4")
    f = np.asarray(f, "<u4")
    return np.array([len(v), len(f)], "<u4").tobytes() + v.tobytes() + f.tobytes()


def solid_props(v, f, material):
    from .design import solid_props as sp
    return sp(v, f, material)


def thicken(dom, mm: float) -> tuple[float, float]:
    """Combined bracket: bolted plate and contact skin at least `mm` thick (passive layers behind the bolted layer,
    away from the wall, and behind the contact layer, toward it; never into the void). Returns their thickness."""
    ax = int(dom.axis)
    h = float(dom.h[ax])
    n = int(max(1, np.ceil(float(mm) / h - 1e-9)))

    def behind(layer, toward_wall):
        up = bool(dom.neg) != toward_wall
        out = np.zeros(dom.shape, bool)
        for k in range(1, min(n, dom.shape[ax])):
            s = np.roll(layer, k if up else -k, axis=ax)
            idx = [slice(None)] * 3
            idx[ax] = slice(0, k) if up else slice(dom.shape[ax] - k, None)
            s[tuple(idx)] = False
            out |= s
        return out & ~dom.void
    plate = behind(dom.fixed, False)
    skin = behind(dom.contact, True)
    dom.plate = plate if plate.any() else None
    dom.skin = skin if skin.any() else None
    return n * h, n * h


def _design_ladder(dom, vol_frac, rmin_mm: float, budget_s: float, threads: int, env: str | None, log, join_width=None,
                   progress=None) -> tuple[dict, list]:
    """The volume-fraction ladder (or one value) on a multi-part domain: SIMP (gd.simp), the one piece joined
    (gd.multi.join), the two-solver check (gd.multi_eval). Returns (best record, rungs)."""
    from . import multi_eval
    from .contest import VOL_LADDER
    from .multi import join
    from .simp import solve
    ladder = (float(vol_frac),) if vol_frac is not None else VOL_LADDER
    best, rungs = None, []
    empty = [p.pid for p in dom.parts if p.contact is None or not p.contact.any()]
    if empty:                                       # no material use can hold a part with no contact voxel
        h = np.round(np.asarray(dom.h, float), 3).tolist()
        reason = (f"no contact voxels for {', '.join(empty)} on {h} mm voxels (the part's side is too close to its "
                  "neighbours or to the wall at this voxel size)")
        return {"passed": False, "reason": reason}, [{"vol_frac": None, "passed": False, "reason": reason}]
    for vf in ladder:
        t0 = time.perf_counter()
        F = [dom.contact_voxel_forces(c) for c in dom.load_cases()]
        try:
            s = solve(~dom.void, dom.passive_solid(), dom.fixed, F, dom.h, float(dom.material["nu"]), vf,
                      rmin_mm=rmin_mm, budget_s=budget_s, threads=threads, mem_check=mem_guard,
                      progress=None if progress is None else
                      (lambda lv, i, c, d, vf=vf: progress("simp", vf, lv, i)))
        except MemoryError as exc:                  # the optimiser itself would not fit (no coarse level to keep)
            rungs.append({"vol_frac": vf, "passed": False, "reason": f"not solved: optimiser: {exc}"[:200]})
            break
        except Exception as exc:  # noqa: BLE001
            rungs.append({"vol_frac": vf, "passed": False, "reason": f"optimiser failed: {exc!r}"[:200]})
            break
        joined, joins = None, []
        if dom.kind == "one_piece":
            sol = (s["density"] >= 0.5) | dom.passive_solid()
            joined, joins = join(dom, sol, width=join_width or 1)
        if progress is not None:
            progress("fea", vf, None, None)
        ev = multi_eval.evaluate(dom, s["density"], threads=threads, env=env, joined=joined, mem_guard=mem_guard)
        ev["vol_frac"] = vf
        ev["simp"] = {k: s[k] for k in ("seconds", "levels", "notes", "ndof", "elements")}
        ev["joins"] = joins
        ev["seconds"] = time.perf_counter() - t0
        rungs.append({"vol_frac": vf, "passed": bool(ev.get("passed")), "mass_g": ev.get("mass_g"),
                      "ms_yield": ev.get("ms_yield"), "ms_ult": ev.get("ms_ult"), "f1_hz": ev.get("f1_hz"),
                      "governing": ev.get("governing"), "reason": str(ev.get("reason") or "")[:200],
                      "seconds": ev["seconds"]})
        log(f"[layout] {dom.name} vf={vf}: mass {ev.get('mass_g')} g, MS {ev.get('ms_yield')}, f1 {ev.get('f1_hz')}")
        if ev.get("mesh") is not None and (best is None or (ev.get("passed") and not best.get("passed")) or
                                           (not best.get("passed") and (ev.get("ms_yield") or -9) >
                                            (best.get("ms_yield") or -9))):
            best = ev
        if ev.get("passed"):
            break
        if ev.get("reason", "").startswith("not solved"):
            break                                   # memory: a heavier rung would not fit either
    if best is None:
        best = {"passed": False, "reason": rungs[-1].get("reason") if rungs else "no design"}
    return best, rungs


def _record(dom, ev: dict, rungs: list, settings: dict, kind_label: str) -> dict:
    """What the layout keeps of a designed multi-part bracket (JSON-ready; the mesh goes to files)."""
    from ..mfg.brackets import _combine, _fastener_items
    from ..mfg.rules import FASTENER_MASS_KG
    from . import materials as mats
    rec = {k: ev.get(k) for k in ("passed", "reason", "ms_yield", "ms_ult", "ms_bolt", "f1_hz", "modes", "governing",
                                   "margins", "flags", "environment", "environment_name", "agreement", "solvers",
                                   "n_nodes", "n_tets", "volume_cm3", "parts_detail", "accel3_g_parts", "load_path",
                                   "held_part_distance_mm", "vol_frac", "simp", "joins", "checks", "bolt_checks",
                                   "factor_sources", "axes", "ccx_skipped", "ccx_failed", "triangles_per_box",
                                   "trial_cases", "ccx_solver", "ngs_seconds", "ccx_seconds", "mesh_seconds",
                                   "fea_seconds", "surface_pieces", "islands_dropped_voxels", "pulled_back",
                                   "subtracted_parts")}
    rec.update(name=dom.name, kind=dom.kind, label=kind_label, parts=[p.pid for p in dom.parts],
               generator="active-element SIMP (gd.simp: the contest winner's method on the free voxels only)",
               material=dom.material.get("id"), material_name=mats.material(dom.material.get("id"))["name"],
               settings=settings, ladder=rungs,
               min_vol_frac=(next((r["vol_frac"] for r in rungs if r["passed"]), None)
                             if settings.get("vol_frac") == "auto" else None))
    if ev.get("mesh") is not None:
        v, f = ev["mesh"]
        m, com, inertia, _ = solid_props(v, f, dom.material.get("id"))
        fpts = [np.asarray(b, float) for b in dom.bolts]
        m2, c2, i2 = _combine([(m, com, inertia)] + _fastener_items(fpts))
        size = (np.asarray(v).max(0) - np.asarray(v).min(0)).tolist()
        rec["bbox_mm"] = [*np.asarray(v).min(0).tolist(), *np.asarray(v).max(0).tolist()]
        rec.update(mass_kg=float(m2), solid_mass_kg=float(m), com_mm=np.asarray(c2).tolist(),
                   inertia_kgm2=np.asarray(i2).tolist(), fastener_mass_kg=len(fpts) * FASTENER_MASS_KG,
                   fasteners=len(fpts), bolts=[np.asarray(p, float).tolist() for p in fpts], size_mm=size,
                   fits_build_volume=fits_build_volume(size), build_volume_mm=list(build_volume()))
    return rec


# =================================================================================================== combined
def group_key(pids) -> str:
    return "+".join(sorted(pids))


def plan_combined(snap: dict) -> list[dict]:
    """The groups (gd.multi.combine_groups) of a snapshot."""
    from .multi import combine_groups
    return combine_groups(snap["brackets"], {p: np.asarray(b, float) for p, b in snap["part_boxes"].items()},
                          [(n, k, np.asarray(b, float)) for n, k, b in snap["keepouts"]])


def combined_h(group: dict) -> float:
    """Voxel of a combined bracket: the finest its members' per-part designs use (gd.design.design_h), coarser in
    0.25 mm steps when the union's grid would exceed COMBINED_MAX_VOXELS, at most gd.multi.H_PRE."""
    from .design import design_h
    from .multi import H_PRE
    hs = [design_h(m["reserve"], int(m["axis"])) for m in group["members"]]
    h = min(min(hs), COMBINED_H_MAX)
    rs = np.array([m["reserve"] for m in group["members"]], float)
    ext = rs[:, 3:].max(0) - rs[:, :3].min(0)
    while np.prod(np.ceil(ext / h)) > COMBINED_MAX_VOXELS and h < H_PRE:
        h += 0.25
    return float(min(h, H_PRE))


def design_combined(group: dict, snap: dict, settings: dict, threads: int = 4, budget_s: float = 300.0,
                    log=print, progress=None) -> tuple[dict, tuple | None, object]:
    """One combined bracket: its domain, the ladder, its record. When the FE check would not fit the memory left
    (MEM_RESERVE_MB), the bracket is designed again on voxels 0.25 mm larger (up to gd.multi.H_PRE), and every attempt
    is listed in the record (voxel_attempts)."""
    from .multi import H_PRE, combined_domain
    mat = settings.get("material") or snap.get("material")
    mm = settings.get("min_member_mm")
    vf = settings.get("vol_frac")
    rmin = 0.5 * float(mm) if mm not in (None, "auto") else 3.0
    h = combined_h(group)
    attempts = []
    while True:
        dom = combined_domain(group, snap["records"], snap["poses"], snap["masses"], h, material=mat,
                              name=group["name"])
        plate = skin = h
        if mm not in (None, "auto"):
            plate, skin = thicken(dom, float(mm))
        ev, rungs = _design_ladder(dom, None if vf in (None, "auto") else float(vf), rmin, budget_s, threads,
                                   snap.get("environment"), log, progress=progress)
        memory = str(ev.get("reason") or "").startswith("not solved")
        attempts.append({"voxel_mm": h, "result": "memory: " + str(ev.get("reason")) if memory else
                         ("passed" if ev.get("passed") else str(ev.get("reason") or "failed"))})
        if not memory or h + 0.25 > H_PRE + 1e-9:
            break
        h += 0.25
    st = {"material": dom.material.get("id"), "vol_frac": "auto" if vf in (None, "auto") else float(vf),
          "min_member_mm": "auto" if mm in (None, "auto") else float(mm)}
    rec = _record(dom, ev, rungs, st, "combined metal-AM bracket")
    rec["voxel_attempts"] = attempts
    rec.update(voxel_mm=h, plate_mm=plate, skin_mm=skin, target=group["target"], target_kind=group["target_kind"],
               axis=group["axis"], neg=group["neg"], plane_mm=group["plane_mm"],
               target_statics=group["target_statics"], members=[m["name"] for m in group["members"]],
               boxes=[{"name": b["name"], "role": b["role"], "part": b.get("part"), "ends": b.get("ends"),
                       "box": np.asarray(b["box"], float).tolist()} for b in dom.boxes],
               domain_notes=dom.notes, key=group_key(group["pids"]))
    return rec, ev.get("mesh"), dom


def _write_mesh(out: Path, stem: str, mesh) -> dict:
    v, f = mesh
    (out / f"{stem}.bin").write_bytes(_mesh_bin(v, f))
    np.save(out / f"{stem}.npy", np.asarray(v, float))
    np.save(out / f"{stem}.faces.npy", np.asarray(f, np.int64))
    return {"mesh_file": f"{stem}.bin", "vertices_file": f"{stem}.npy", "faces_file": f"{stem}.faces.npy"}


def combined_job(snapshot: str, out_dir: str, threads: int = 4) -> str:
    """Design every combined bracket of a layout (snapshot: see the coordinator's start_bracket_layout), one at a
    time (each uses `threads`), writing progress.json after each."""
    from ..core.fileio import atomic_write_text
    from . import environment as envs
    snap = pickle.loads(Path(snapshot).read_bytes())
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    lid = snap["layout_id"]
    groups = plan_combined(snap)
    rows = [{"k": k, "pid": g["name"], "kind": "combined", "label": f"{g['target']}: {', '.join(g['pids'])}",
             "parts": g["pids"], "status": "queued"} for k, g in enumerate(groups)]
    designs, t0 = {}, time.perf_counter()
    prog = out / "progress.json"

    def write(status, extra=None):
        now = time.perf_counter() - t0
        done = [r for r in rows if r["status"] == "done"]
        mean = float(np.mean([r["seconds"] for r in done])) if done else None
        left = sum(1 for r in rows if r["status"] != "done")
        atomic_write_text(prog, json.dumps({
            "status": status, "mode": "combined", "progress": len(done) / max(len(rows), 1), "layout_id": lid,
            "environment": envs.get(snap.get("environment")).id, "designs": designs, "seconds": now, "workers": 1,
            "n_total": len(rows), "n_done": len(done), "brackets": rows,
            "groups": [{"name": g["name"], "pids": g["pids"], "target": g["target"],
                        "bridges": [b["gap_box"] for b in g["bridges"]]} for g in groups],
            "eta_s": (mean * left if mean is not None else None) if status != "DONE" else 0.0, **(extra or {})},
            default=float))
    write("RUNNING")
    with MemWatch() as mw:
        for k, g in enumerate(groups):
            rows[k].update(status="running", started_s=time.perf_counter() - t0)
            write("RUNNING", {"peak_rss_mb": mw.peak_mb})
            key = group_key(g["pids"])
            st = dict((snap.get("overrides") or {}).get(key) or {})
            try:
                rec, mesh, _ = design_combined(g, snap, st, threads=threads, log=lambda m: None)
                if mesh is not None:
                    rec.update(_write_mesh(out, f"{lid}-cb{k}", mesh))
            except Exception as exc:  # noqa: BLE001 - one bracket's failure is that bracket's result
                rec = {"name": g["name"], "kind": "combined", "parts": g["pids"], "passed": False,
                       "reason": f"design failed: {exc!r}"[:300], "key": key, "target": g["target"]}
            rec["index"] = k
            designs[key] = rec
            now = time.perf_counter() - t0
            rows[k].update(status="done", seconds=now - rows[k]["started_s"], passed=bool(rec.get("passed")),
                           mass_g=1000.0 * rec["mass_kg"] if rec.get("mass_kg") is not None else None,
                           solid=rec.get("mass_kg") is not None, reason=str(rec.get("reason") or "")[:160])
            write("RUNNING", {"peak_rss_mb": mw.peak_mb})
    write("DONE", {"peak_rss_mb": mw.peak_mb, "seconds_total": time.perf_counter() - t0})
    return str(prog)


# =================================================================================================== one piece
def one_piece_domain_of(snap: dict, settings: dict):
    from .multi import one_piece_domain
    return one_piece_domain(snap["brackets"], snap["records"], snap["poses"], snap["masses"], snap["inner"],
                            [(n, k, np.asarray(b, float)) for n, k, b in snap["keepouts"]],
                            {p: np.asarray(b, float) for p, b in snap["nonheld_boxes"].items()},
                            material=settings.get("material") or snap.get("material"))


# measured model of the one piece's run time and memory (docs/notes/m4.md): per SIMP iteration (gd.simp) and per FE
# solve; ASSUMED until the measurement replaces them
ONE_PIECE_ITER = {"coarse": 40, "fine": 25}


def one_piece_estimate(snap: dict, settings: dict | None = None) -> dict:
    """Before starting: the grid, the free voxels, the optimiser's dofs at both levels and the predicted time and
    memory of one rung (SIMP coarse + fine, the joins, the FE check), from the cost models (gd.simp, MB_PER_KDOF)."""
    t0 = time.perf_counter()
    dom = one_piece_domain_of(snap, settings or {})
    out = estimate_from_domain(dom, snap, settings)
    out["domain_seconds"] = time.perf_counter() - t0
    return out


def estimate_from_domain(dom, snap: dict, settings: dict | None = None) -> dict:
    from .simp import seconds_per_iteration
    free = ~dom.void
    nf = int(free.sum())
    # nodes ≈ elements × 1.15 on a compact region (measured on the grid), dofs = 3 × nodes
    dof_fine = int(3 * 1.15 * nf)
    dof_coarse = int(dof_fine / 8)
    simp_s = ONE_PIECE_ITER["coarse"] * seconds_per_iteration(dof_coarse) + \
        ONE_PIECE_ITER["fine"] * seconds_per_iteration(dof_fine)
    budget = float((settings or {}).get("budget_s") or snap.get("budget_s") or 900.0)
    simp_s = min(simp_s, budget)
    # the FE mesh: the solid at the volume fraction plus the passive layers, tet10 nodes ≈ 1.8 per voxel of solid
    vf = (settings or {}).get("vol_frac")
    vf = 0.03 if vf in (None, "auto") else float(vf)
    solid_vox = int(dom.passive_solid().sum() + vf * int(dom.design().sum()))
    fe_dofs = int(3 * 1.8 * solid_vox * float(np.prod(dom.h)) / 1.5 ** 3 / 2.0)
    fe_s = 30.0 + fe_dofs / 2.0e4 * 10.0
    mem_mb = max(MB_PER_KDOF["CalculiX"] * fe_dofs / 1000.0, 400.0 + 0.004 * dof_fine)
    return {"grid": list(dom.shape), "h_mm": dom.h.tolist(), "free_voxels": nf, "held_parts": len(dom.parts),
            "kept_brackets": getattr(dom, "kept_brackets", []), "dofs_fine": dof_fine, "dofs_coarse": dof_coarse,
            "fe_dofs_estimate": fe_dofs, "seconds_estimate": float(simp_s + fe_s + 20.0),
            "simp_seconds_estimate": float(simp_s), "fe_seconds_estimate": float(fe_s),
            "memory_mb_estimate": float(mem_mb), "available_mb": available_mb(), "budget_s": budget,
            "notes": dom.notes, "model": "ASSUMED cost model until measured (docs/notes/m4.md)"}


def one_piece_job(snapshot: str, out_dir: str, threads: int = 4) -> str:
    """Design the one piece of a layout (exploratory): the domain, the ladder (SIMP, joins, two-solver check)."""
    from ..core.fileio import atomic_write_text
    from . import environment as envs
    snap = pickle.loads(Path(snapshot).read_bytes())
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    lid = snap["layout_id"]
    st = dict(snap.get("settings") or {})
    t0 = time.perf_counter()
    prog = out / "progress.json"
    est = snap.get("estimate") or {}
    row = {"k": 0, "pid": "one piece", "kind": "one_piece", "label": "one piece (every part but the PC/104 boards)",
           "status": "running", "started_s": 0.0, "phase": "domain"}
    designs: dict = {}

    def write(status, extra=None):
        now = time.perf_counter() - t0
        eta = None
        if status != "DONE" and est.get("seconds_estimate"):
            eta = max(0.0, float(est["seconds_estimate"]) - now)
        atomic_write_text(prog, json.dumps({
            "status": status, "mode": "one_piece", "progress": 1.0 if status == "DONE" else min(0.95, now / max(
                float(est.get("seconds_estimate") or 600.0), 1.0)), "layout_id": lid,
            "environment": envs.get(snap.get("environment")).id, "designs": designs, "seconds": now, "workers": 1,
            "n_total": 1, "n_done": 1 if status == "DONE" else 0, "brackets": [row], "eta_s": eta if status != "DONE"
            else 0.0, "estimate": est, **(extra or {})}, default=float))
    write("RUNNING")
    with MemWatch() as mw:
        try:
            dom = one_piece_domain_of(snap, st)
            if not est:
                est.update(estimate_from_domain(dom, snap, st))
                est["seconds_estimate"] = float(est["seconds_estimate"]) + (time.perf_counter() - t0)
            row["phase"] = "optimising"
            write("RUNNING", {"peak_rss_mb": mw.peak_mb})

            def progress(what, vf, level, it):
                row["phase"] = (f"optimising at {100 * vf:.0f} %: {level} level, iteration {it}" if what == "simp"
                                else f"checking the {100 * vf:.0f} % design with CalculiX and NGSolve")
                if it is None or it % 5 == 0:
                    write("RUNNING", {"peak_rss_mb": mw.peak_mb})
            mm = st.get("min_member_mm")
            rmin = max(3.0, 0.5 * float(mm)) if mm not in (None, "auto") else 3.0
            width = 1 if mm in (None, "auto") else int(max(1, np.ceil(float(mm) / float(dom.h.min()) - 1e-9)))
            vf = st.get("vol_frac")
            budget = float(st.get("budget_s") or snap.get("budget_s") or 900.0)
            ev, rungs = _design_ladder(dom, None if vf in (None, "auto") else float(vf), rmin, budget, threads,
                                       snap.get("environment"), lambda m: None, join_width=width, progress=progress)
            settings = {"material": dom.material.get("id"), "vol_frac": "auto" if vf in (None, "auto") else float(vf),
                        "min_member_mm": "auto" if mm in (None, "auto") else float(mm), "budget_s": budget}
            rec = _record(dom, ev, rungs, settings, "one-piece metal-AM bracket (exploratory)")
            rec.update(voxel_mm=dom.h.tolist(), grid=list(dom.shape), domain_notes=dom.notes,
                       kept_brackets=getattr(dom, "kept_brackets", []), key="one_piece",
                       bolted=[{"part": p.pid, "axis": p.axis, "neg": p.neg, "plane_mm": p.plane,
                                "footprint": [float(x) for x in p.box]} for p in dom.parts])
            if ev.get("mesh") is not None:
                rec.update(_write_mesh(out, f"{lid}-op", ev["mesh"]))
        except Exception as exc:  # noqa: BLE001
            rec = {"name": "one piece", "kind": "one_piece", "passed": False, "reason": f"design failed: {exc!r}"[:300],
                   "key": "one_piece"}
        designs["one_piece"] = rec
        now = time.perf_counter() - t0
        row.update(status="done", seconds=now, passed=bool(rec.get("passed")), phase="done",
                   mass_g=1000.0 * rec["mass_kg"] if rec.get("mass_kg") is not None else None,
                   solid=rec.get("mass_kg") is not None, reason=str(rec.get("reason") or "")[:160])
    write("DONE", {"peak_rss_mb": mw.peak_mb, "seconds_total": time.perf_counter() - t0})
    return str(prog)


# =================================================================================================== summaries
def per_part_summary(brackets: list, designs: dict, sizes: dict | None = None) -> dict:
    """The per-part column: every bracket's mass (designed, exact or ESTIMATE), the worst margin over the designed
    ones, the lowest first frequency, the metal-AM brackets as the prints and the largest one's size (its designed
    solid, else its reserved box)."""
    mass, est, worst, f1, prints, largest = 0.0, 0, None, None, 0, None
    designed = 0
    for b in brackets:
        d = designs.get(b["pid"]) or {}
        if d.get("mass_kg") is not None:
            mass += float(d["mass_kg"])
            designed += 1
            g = d.get("governing") or {}
            if g.get("ms") is not None and (worst is None or g["ms"] < worst["ms"]):
                worst = {**g, "bracket": b["name"], "parts": [b["pid"]]}
            if d.get("f1_hz") is not None and (f1 is None or d["f1_hz"] < f1["f_hz"]):
                f1 = {"f_hz": float(d["f1_hz"]), "bracket": b["name"]}
        else:
            mass += float(b["mass_kg"])
            est += 0 if b.get("exact") else 1
        if b["kind"] == "metal_am":
            prints += 1
            size = (sizes or {}).get(b["pid"])
            if size is None:
                r = np.asarray(b["reserve"], float)
                size = (r[3:] - r[:3]).tolist()
            if largest is None or np.prod(size) > np.prod(largest):
                largest = [float(x) for x in size]
    return {"mode": "per_part", "bracket_mass_kg": mass, "estimates": est, "designed": designed,
            "worst": worst, "f1": f1, "prints": prints, "largest_print_mm": largest,
            "largest_fits": None if largest is None else fits_build_volume(largest), "build_volume_mm": list(build_volume()),
            "pieces": len(brackets)}


def mode_summary(mode: str, brackets: list, per_part_designs: dict, result: dict) -> dict:
    """Combined / one-piece column: the new prints' masses plus every bracket they leave as it was (its per-part design
    or simple solid), the worst margin over all designed ones, the lowest f1, the print count and the largest print."""
    designs = result.get("designs") or {}
    held = set()
    for d in designs.values():
        held |= set(d.get("parts") or [])
    rest = [b for b in brackets if b["pid"] not in held]
    base = per_part_summary(rest, per_part_designs) if rest else {"bracket_mass_kg": 0.0, "worst": None, "f1": None,
                                                                 "prints": 0, "largest_print_mm": None, "estimates": 0}
    mass = base["bracket_mass_kg"]
    worst, f1, prints, largest = base["worst"], base["f1"], base["prints"], base["largest_print_mm"]
    failed = []
    for key, d in designs.items():
        if d.get("mass_kg") is None:
            failed.append(key)
            continue
        mass += float(d["mass_kg"])
        prints += 1
        g = d.get("governing") or {}
        if g.get("ms") is not None and (worst is None or g["ms"] < worst["ms"]):
            worst = {**g, "bracket": d.get("name"), "parts": d.get("parts")}
        if d.get("f1_hz") is not None and (f1 is None or d["f1_hz"] < f1["f_hz"]):
            f1 = {"f_hz": float(d["f1_hz"]), "bracket": d.get("name")}
        size = d.get("size_mm")
        if size is not None and (largest is None or np.prod(size) > np.prod(largest)):
            largest = [float(x) for x in size]
    return {"mode": mode, "bracket_mass_kg": mass, "estimates": base.get("estimates", 0), "worst": worst, "f1": f1,
            "prints": prints, "largest_print_mm": largest,
            "largest_fits": None if largest is None else fits_build_volume(largest),
            "build_volume_mm": list(build_volume()), "pieces": len(rest) + len(designs), "failed": failed,
            "passed": all(bool(d.get("passed")) for d in designs.values()) if designs else None,
            "unchanged": [b["pid"] for b in rest]}


def build_snapshot(layout_id: str, records: dict, meta: dict, poses: list, masses: dict, mode: str,
                   environment: str | None, material: str | None, settings: dict | None = None,
                   overrides: dict | None = None, inner=None, budget_s: float | None = None) -> dict:
    """What a layout job needs (pickled by the coordinator, or built by a script): the brackets, the part records at
    the layout's size, the design poses (the decoder's orientation with the mounting pad), the masses, every keep-out
    of the layout (constraints.stage2_model statics: rails, rods, stack reserve, harness, standoffs — not the bracket
    boxes), each part's certified world boxes (G1), the inner box, and the parts the one piece does not hold (the
    PC/104 boards, parts on a corner rail) with their bounding boxes."""
    from ..constraints import stage2 as s2
    from ..constraints.stage2_model import Stage2Model
    from ..core.rotations import ROTATIONS_F
    from ..mfg.brackets import world_boxes
    pad_o = meta.get("pad_orients", {})
    design_poses = {pid: (int(pad_o.get(pid, o)), np.asarray(t, float)) for pid, o, t in poses}
    model = Stage2Model(records, meta.get("mode", "default"))
    keepouts = [(s.name, s.kind, np.concatenate([s.corners.min(0), s.corners.max(0)]).tolist())
                for s in model.statics(meta) if s.kind != "bracket"]
    part_boxes = {pid: world_boxes(records[pid], o, np.asarray(t, float)).tolist() for pid, o, t in poses}
    brackets = meta.get("brackets") or []
    held = {b["pid"] for b in brackets if (b.get("target_kind") or "wall") in ("wall", "end_plate")}
    nonheld = {}
    for pid, o, t in poses:
        if pid not in held:
            v = np.asarray(records[pid].v, float) @ ROTATIONS_F[int(o)].T + np.asarray(t, float)
            nonheld[pid] = np.concatenate([v.min(0), v.max(0)]).tolist()
    lo, hi = s2.inner_box() if inner is None else inner
    return {"layout_id": layout_id, "mode": mode, "brackets": brackets, "records": records, "poses": design_poses,
            "masses": masses, "environment": environment, "material": material, "settings": settings or {},
            "overrides": overrides or {}, "keepouts": keepouts, "part_boxes": part_boxes,
            "inner": (np.asarray(lo, float).tolist(), np.asarray(hi, float).tolist()), "nonheld_boxes": nonheld,
            "budget_s": budget_s}


def threads_default() -> int:
    """Threads of a layout job: at most 4 (the user's machine is shared), at most half the logical cores."""
    return max(1, min(4, (os.cpu_count() or 4) // 2))
