"""Entrant: BESO (Bi-directional Evolutionary Structural Optimisation) for CalculiX — github.com/calculix/beso,
commit 5056d30 (2025-04-03, LGPL-3.0), unmodified, driving the project's CalculiX 2.23 (tools/ccx/ccx.exe).

What BESO is (read from its source, tools/beso/beso-<commit>/): a set of Python scripts, `beso_main.py` (the loop, run as
a script; it exec()s `beso_conf.py` from its OWN folder), `beso_lib.py` (reads the .inp, writes one .inp per iteration
with every optimised element set split into per-state sets DESIGN0 / DESIGN1 with their own material, reads ENER from
the .dat, switches element states), `beso_filters.py`, `beso_plots.py` (matplotlib). Element states are discrete:
state 0 = "void" (soft-kill: E and rho scaled by VOID), state 1 = solid. For optimization_base = "stiffness" the
sensitivity of an element is its strain-energy density, max over the load steps; filtered ("simple": weighted average
of the neighbours within r, weights r - d); averaged with the previous iteration (sensitivity_averaging, Huang & Xie);
each iteration removes `mass_removal_ratio` and adds `mass_addition_ratio` of the current mass (ratio_type "relative")
until the target mass, then the ratios decay (exp(-0.2 k)) and the loop stops when the mass-weighted mean energy
density changes < `tolerance` over 5 iterations, at `iterations_limit`, or on a 2-cycle oscillation.

How this entrant drives it (BESO's files are never modified):
1. The voxel model is written as a CalculiX deck (`write_deck`): C3D8 hexahedra (full integration; C3D8I selectable,
   BESO reads both as hexa8), one per non-void voxel, nodes shared on the voxel lattice (node id = lattice index + 1,
   element id = flat voxel index + 1, so states map straight back to the grid). Element sets DESIGN (optimised) and
   PASSIVE (fixed + contact, never optimised; it is listed in the BESO config as a non-optimised domain only so that
   BESO also prints its ENER, which gives the true compliance), NFIX = the target-plane face nodes of the fixed voxels
   (*BOUNDARY 1-3). Material MAT = domain.material (E, nu, rho). One *STATIC step per load case (SPOOLES up to
   SPOOLES_MAX_DOF unknowns, else ccx's ITERATIVE SCALING, see pick_solver): *CLOAD OP=NEW with the case's contact
   force split evenly over the contact voxels (1/8 of each voxel's share to each of its 8 nodes), *DLOAD OP=NEW
   EALL,GRAV with the 68 g body acceleration (the design elements' GRAV load follows their state's density, so
   self-weight is design-dependent), and an output request that BESO replaces by its *EL PRINT ENER requests.
2. A `beso_conf.py` with these settings is written to a fresh work folder, and a small driver (`_DRIVER`, written next
   to it) runs BESO's unmodified `beso_main.py` with `python -I` via exec(compile(source)), with `__file__` pointing
   into the work folder, so BESO reads OUR beso_conf.py, and with the work folder as working directory (BESO's
   path = "."), so BESO writes its files there. The driver monkeypatches (in its own process only):
   - beso_plots.plotshow / replot -> no-ops (no figures);
   - subprocess.call (BESO's ccx call, `shell=True` on Windows) -> ccx.exe -i job called directly, its output checked
     ("Job finished", no *ERROR), a failed run re-run up to twice (ccx 2.23 crashed once, intermittently, right after
     its banner, with 0xC0000005 on a deck that solves when re-run), the last time with SPOOLES;
   - beso_lib.import_FI_int_pt -> the original plus bookkeeping: compliance per load case = 2 * sum(ENER * V) over all
     elements, a state snapshot, and the wall-clock guard: when the next iteration would overrun the budget it sets
     BESO's `iterations_limit` to the current iteration, so BESO's own loop ends cleanly;
   - beso_lib.switching -> the original, but while the target mass is not yet reached and the remaining budget would
     not get there at the configured rate, `mass_removal_ratio` is raised just enough (at most RATE_MAX) to reach it
     with RESERVE_IT iterations to spare (re-evaluated every iteration from the measured time per iteration, from the
     second FE iteration on; the configured ratio again once the target mass is reached).
3. The final element states (state 1 -> 1.0) go back on the grid; void = 0, passives = 1.

Design voxels with no other design voxel within the filter radius (BESO's "simple" filter divides by zero there and
then silently skips filtering for the WHOLE domain) are made passive solid; `mass_goal_ratio` is adjusted so that
solid design voxels / all design voxels = domain.vol_frac.
"""
from __future__ import annotations

import contextlib
import json
import math
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

from ..domain import DesignDomain, GenResult

NAME = "BESO + CalculiX"
ROOT = Path(__file__).resolve().parents[5]
BESO_COMMIT = "5056d301c2675df9ac1af771af4f1cbea642e4ad"
BESO_DATE = "2025-04-03"
BESO_DIR = ROOT / "tools" / "beso" / f"beso-{BESO_COMMIT}"
BESO_FILES = ("beso_main.py", "beso_lib.py", "beso_filters.py", "beso_plots.py", "beso_separate.py")
CCX_EXE = ROOT / "tools" / "ccx" / "ccx.exe"
THREAD_VARS = ("OMP_NUM_THREADS", "NUMBER_OF_CPUS", "CCX_NPROC_EQUATION_SOLVER", "CCX_NPROC_STIFFNESS",
               "CCX_NPROC_RESULTS", "CCX_NPROC_CFD", "CCX_NPROC_SENS", "CCX_NPROC_VIEWFACTOR",
               "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS")

ELEMENT = "C3D8"           # or "C3D8I" (incompatible modes; BESO reads both as hexa8)
VOID = 1e-6                # state-0 ("void") E and rho as a fraction of the solid (BESO's default contrast)
REMOVAL, ADDITION = 0.05, 0.015    # BESO mass_removal_ratio / mass_addition_ratio (relative to the current mass)
RATE_MAX = 0.30            # cap of the budget-driven removal ratio
EXTRA_IT = 20              # iterations allowed after the target mass is (nominally) reached
RESERVE_IT = 6             # iterations kept for convergence when the removal rate is raised for the budget
TOLERANCE = 1e-3           # BESO: relative change of the mean energy density over 5 iterations to stop
DECAY = -0.2               # BESO decay_coefficient after the target mass
SPOOLES_MAX_DOF = 20000    # larger models use ccx's ITERATIVE SCALING solver (see pick_solver)
CORNERS = np.array([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0), (0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1)])


def available() -> bool:
    return CCX_EXE.is_file() and all((BESO_DIR / f).is_file() for f in BESO_FILES)


def filter_radius(h: float) -> float:
    """BESO 'simple' filter radius (mm): 2 voxels (BESO's "auto" = 2 x mean element size), at least 3 mm."""
    return max(2.0 * h, 3.0)


# ---------------------------------------------------------------------------------------------------- model
def _f(x: float) -> str:
    x = float(x)
    if not math.isfinite(x):
        raise ValueError(f"non-finite number {x} in the CalculiX deck")
    return "0." if abs(x) < 1e-90 else f"{x:.12e}"


def _id_lines(ids, per_line: int = 16) -> list[str]:
    ids = [str(int(i)) for i in ids]
    return [",".join(ids[k:k + per_line]) for k in range(0, len(ids), per_line)]


def split_domain(dom: DesignDomain, r_mm: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(design, passive, isolated): design voxels BESO optimises, passive solid voxels (fixed + contact + isolated
    design voxels), and the isolated design voxels (no other design voxel closer than r_mm)."""
    design = dom.design()
    passive = dom.passive_solid() & ~dom.void
    isolated = np.zeros(dom.shape, bool)
    idx = np.argwhere(design)
    if len(idx):
        from scipy.spatial import cKDTree
        c = (idx + 0.5) * dom.h
        n = cKDTree(c).query_ball_point(c, r_mm * (1 - 1e-9), return_length=True)
        lone = idx[np.asarray(n) <= 1]
        isolated[tuple(lone.T)] = True
    return design & ~isolated, passive | isolated, isolated


def pick_solver(n_nodes: int) -> str:
    """SPOOLES (direct) for small models; ccx's diagonally scaled CG for large ones (h = 1 mm box, 18.5k nodes: 7 s
    instead of 31-40 s per 3-step analysis, displacements within 2e-4 of SPOOLES; PARDISO is not linked in this ccx)."""
    return "SPOOLES" if 3 * n_nodes <= SPOOLES_MAX_DOF else "ITERATIVE SCALING"


def write_deck(dom: DesignDomain, path: Path, design: np.ndarray, passive: np.ndarray,
               element: str = ELEMENT, solver: str = "auto") -> dict:
    """CalculiX deck of the voxel model (see the module docstring). Returns the model's bookkeeping."""
    nx, ny, nz = dom.shape
    solid = design | passive
    vox = np.argwhere(solid)                                            # C order = increasing element id
    eid = np.ravel_multi_index(vox.T, dom.shape) + 1
    lat = (nx + 1, ny + 1, nz + 1)
    conn = np.ravel_multi_index((vox[:, None, :] + CORNERS[None]).transpose(2, 0, 1), lat) + 1   # (n, 8)
    used = np.unique(conn)
    nc = np.stack(np.unravel_index(used - 1, lat), axis=1) * dom.h + dom.origin
    ax = dom.axis
    face = CORNERS[:, ax] == (0 if dom.neg else 1)
    fixed_vox = dom.fixed[tuple(vox.T)] & passive[tuple(vox.T)]
    nfix = np.unique(conn[fixed_vox][:, face])
    if len(nfix) == 0:
        raise ValueError(f"domain {dom.name!r}: no fixed voxels — the bracket would be unsupported")
    cont = dom.contact[tuple(vox.T)]
    if not cont.any():
        raise ValueError(f"domain {dom.name!r}: no contact voxels to load")
    cont_nodes = conn[cont]                                             # (nc, 8)
    if solver == "auto":
        solver = pick_solver(len(used))
    mat = dom.material
    title = str(dom.name).encode("ascii", "replace").decode("ascii")[:60]
    out = ["*HEADING", f"T2S BESO voxel model {title} ({element}, h = {dom.h} mm; units mm N t s)",
           "*NODE, NSET=NALL"]
    out += [f"{n},{_f(x)},{_f(y)},{_f(z)}" for n, (x, y, z) in zip(used.tolist(), nc.tolist())]
    out.append(f"*ELEMENT, TYPE={element}, ELSET=EALL")
    out += [f"{e}," + ",".join(map(str, row)) for e, row in zip(eid.tolist(), conn.tolist())]
    is_design = design[tuple(vox.T)]
    out.append("*ELSET, ELSET=DESIGN")
    out += _id_lines(eid[is_design])
    out.append("*ELSET, ELSET=PASSIVE")
    out += _id_lines(eid[~is_design])
    out.append("*NSET, NSET=NFIX")
    out += _id_lines(nfix)
    out += ["*MATERIAL, NAME=MAT", "*ELASTIC", f"{_f(mat['E_mpa'])},{_f(mat['nu'])}", "*DENSITY",
            _f(mat["rho_t_mm3"]),
            "*SOLID SECTION, ELSET=PASSIVE, MATERIAL=MAT",
            "*BOUNDARY", "NFIX,1,3"]
    cases = dom.load_cases()
    for case in cases:
        # the part's force at its centre of mass, as force + moment over the contact voxels
        # (domain.contact_voxel_forces), each voxel's share split 1/8 to its nodes
        fv = dom.contact_voxel_forces(case)[tuple(vox[cont].T)]            # (nc, 3), same rows as cont_nodes
        loads = np.zeros((len(used), 3))
        pos = np.searchsorted(used, cont_nodes.ravel())
        np.add.at(loads, pos, np.repeat(fv / 8.0, 8, axis=0))
        out += [f"** load case {case['name']}", "*STEP", f"*STATIC, SOLVER={solver}", "*CLOAD, OP=NEW"]
        lines = [f"{n},{d + 1},{_f(v[d])}" for n, v in zip(used.tolist(), loads.tolist()) for d in range(3)
                 if v[d] != 0.0]
        out += lines or ["1,1,0."]
        out.append("*DLOAD, OP=NEW")
        a = np.asarray(case.get("body_accel_mm_s2", np.zeros(3)), float)
        g = float(np.linalg.norm(a))
        out.append(f"EALL,GRAV,{_f(g)},{_f(a[0] / g)},{_f(a[1] / g)},{_f(a[2] / g)}" if g > 0
                   else "EALL,GRAV,0.,0.,0.,-1.")
        out += ["*NODE FILE", "U", "*END STEP"]          # BESO replaces the output request by *EL PRINT ENER
    path.write_text("\n".join(out) + "\n", encoding="ascii")
    return {"elements": len(eid), "design": int(is_design.sum()), "passive": int((~is_design).sum()),
            "nodes": len(used), "fixed_nodes": len(nfix), "contact_voxels": len(cont_nodes), "solver": solver,
            "eid": eid, "vox": vox, "is_design": is_design, "cases": [c["name"] for c in cases]}


def write_conf(path: Path, mat: dict, mass_goal_ratio: float, r_mm: float, iterations_limit: int,
               threads: int, removal: float = REMOVAL, addition: float = ADDITION) -> dict:
    """BESO's beso_conf.py (executed by beso_main.py) for compliance minimisation of DESIGN."""
    E, nu, rho = float(mat["E_mpa"]), float(mat["nu"]), float(mat["rho_t_mm3"])

    def material(s: float) -> str:
        return f"*ELASTIC\n{_f(E * s)},{_f(nu)}\n*DENSITY\n{_f(rho * s)}"

    settings = {
        # path "." = the driver's working directory (the work folder): BESO hands ccx `path\fileNNN`, and ccx 2.23
        # refuses job names longer than 127 characters, so an absolute temp path can break it
        "path": ".", "path_calculix": str(CCX_EXE), "file_name": "beso.inp",
        "mass_goal_ratio": float(mass_goal_ratio), "continue_from": "", "filter_list": [["simple", float(r_mm)]],
        "optimization_base": "stiffness", "cpu_cores": int(threads), "FI_violated_tolerance": 1,
        "decay_coefficient": DECAY, "shells_as_composite": False, "reference_points": "integration points",
        "reference_value": "max", "sensitivity_averaging": True, "mass_addition_ratio": float(addition),
        "mass_removal_ratio": float(removal), "ratio_type": "relative", "compensate_state_filter": False,
        "steps_superposition": [], "iterations_limit": int(iterations_limit), "tolerance": TOLERANCE,
        "displacement_graph": [], "save_iteration_results": 0, "save_solver_files": "",
        "save_resulting_format": "inp"}
    lines = ["# written by t2s.gd.entrants.beso_ccx — BESO configuration (executed by beso_main.py)", ""]
    for dn, optimised, states in (("DESIGN", True, [VOID, 1.0]), ("PASSIVE", False, [1.0, 1.0])):
        lines += [f"elset_name = {dn!r}",
                  f"domain_optimized[elset_name] = {optimised!r}",
                  f"domain_density[elset_name] = {states!r}",
                  "domain_thickness[elset_name] = [1.0, 1.0]",
                  "domain_offset[elset_name] = 0.0",
                  "domain_orientation[elset_name] = []",
                  "domain_FI[elset_name] = []",
                  f"domain_material[elset_name] = {[material(s) for s in states]!r}",
                  "domain_same_state[elset_name] = False", ""]
    lines += [f"{k} = {v!r}" for k, v in settings.items()]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return settings


def iterations_to_goal(goal: float, removal: float, addition: float) -> int:
    """BESO's own 'auto' count (ratio_type relative) of iterations from full mass down to the goal."""
    m, it = 1.0, 0
    while m > goal and it < 10000:
        m -= m * (removal - addition)
        it += 1
    return it


# ---------------------------------------------------------------------------------------------------- driver
_DRIVER = r'''"""Driver for BESO's unmodified beso_main.py, written by t2s.gd.entrants.beso_ccx (runs under python -I).
argv[1]: the JSON run configuration. Writes result.json (and state_snapshot.json each iteration) into the work folder."""
import json
import os
import sys
import time
import traceback


def main(cfg_path):
    with open(cfg_path, encoding="utf-8") as fh:
        cfg = json.load(fh)
    work, beso_dir = cfg["workdir"], cfg["beso_dir"]
    deadline, vol = float(cfg["deadline"]), float(cfg["h"]) ** 3
    sys.path.insert(0, beso_dir)
    main_path = os.path.join(beso_dir, "beso_main.py")
    sys.argv = [os.path.join(work, "beso_main.py")]         # no argv[1]: BESO keeps file_name from beso_conf.py
    import beso_lib
    import beso_plots
    ns = {"__name__": "__beso_main__", "__file__": os.path.join(work, "beso_main.py"), "__builtins__": __builtins__}
    rec = {"compliance": [], "t_fe": [], "t_ccx": [], "rate_changes": [], "ccx_failures": [],
           "stopped_by_budget": False, "status": "running"}
    t_start = time.time()

    def t_iter():
        t = rec["t_fe"]
        if len(t) >= 2:
            return (t[-1] - t[0]) / (len(t) - 1)
        return (t[-1] - t_start) if t else None

    def snapshot(states, path):
        design = set(ns["domains"]["DESIGN"])
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({str(en): int(s) for en, s in states.items() if en in design}, fh)
        os.replace(tmp, path)

    orig_fi = beso_lib.import_FI_int_pt

    def import_fi(*a, **k):
        out = orig_fi(*a, **k)
        now = time.time()
        rec["t_fe"].append(now)
        rec["compliance"].append([2.0 * vol * float(sum(d.values())) for d in out[1]])
        rec["n_ener"] = [len(d) for d in out[1]]
        snapshot(a[6], os.path.join(work, "state_snapshot.json"))
        ti = t_iter()
        lim = ns.get("iterations_limit")
        if ti is not None and isinstance(lim, int) and now + 1.25 * ti > deadline and ns.get("i", 0) < lim:
            ns["iterations_limit"] = ns.get("i", 0)          # BESO's own loop ends after this iteration
            rec["stopped_by_budget"] = True
        return out

    orig_sw = beso_lib.switching

    def switching(*a):
        # a[11] mass history, a[13] mass_addition_ratio, a[14] mass_removal_ratio, a[19] i_violated, a[20] i
        a = list(a)
        mass, add, i_violated, i = a[11], a[13], a[19], a[20]
        rem = float(cfg["removal"])
        t = rec["t_fe"]
        if cfg["adaptive"] and not i_violated and len(t) >= 2:      # timed from 2 FE iterations on (no setup)
            ti = (t[-1] - t[0]) / (len(t) - 1)
            m, g = mass[i - 1] / ns["mass_full"], float(ns["mass_goal_ratio"])
            n_aff = (deadline - time.time()) / ti - cfg["reserve_it"]
            if m > g:
                need = 1.0 - (g / m) ** (1.0 / max(n_aff, 1.0))
                rem = min(max(rem, add + need), cfg["rate_max"])
        if rem != a[14]:
            rec["rate_changes"].append([i, rem])
        a[14] = rem
        ns["mass_removal_ratio"] = rem
        return orig_sw(*a)

    import subprocess

    def ccx_call(args, **kw):
        """BESO's `subprocess.call([ccx, job], cwd=path, shell=True)` (Windows): ccx is called directly (no cmd.exe),
        its output is checked, and a failed run is retried (ccx 2.23 crashed once, intermittently, right after its
        banner); the last attempt falls back to the direct SPOOLES solver."""
        exe, job, cwd = args[0], args[-1], kw.get("cwd")
        st = 1
        for attempt in range(3):
            if attempt == 2 and cfg["solver"] != "SPOOLES":
                inp = os.path.join(cwd or ".", job + ".inp")
                with open(inp, encoding="ascii") as fh:
                    txt = fh.read()
                with open(inp, "w", encoding="ascii", newline="\n") as fh:
                    fh.write(txt.replace("SOLVER=" + cfg["solver"], "SOLVER=SPOOLES"))
            t_c = time.time()
            p = subprocess.run([exe, "-i", job], cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               text=True, errors="replace")
            rec["t_ccx"].append(time.time() - t_c)
            sys.stdout.write(p.stdout)
            sys.stdout.flush()
            st = p.returncode
            if st == 0 and "Job finished" in p.stdout and "*ERROR" not in p.stdout:
                return 0
            rec["ccx_failures"].append([ns.get("i"), attempt, st])
        return st or 1

    subprocess.call = ccx_call
    beso_lib.import_FI_int_pt = import_fi
    beso_lib.switching = switching
    beso_plots.plotshow = lambda *a, **k: None
    beso_plots.replot = lambda *a, **k: None
    code = compile(open(main_path, encoding="utf-8").read(), main_path, "exec")
    try:
        exec(code, ns)
        rec["status"] = "finished"
    except BaseException:
        rec["status"] = "error"
        rec["traceback"] = traceback.format_exc()
    design = set(ns.get("domains", {}).get("DESIGN", []))
    states = ns.get("elm_states", {})
    rec["states"] = {str(en): int(s) for en, s in states.items() if en in design}
    for key in ("i", "iterations_limit", "oscillations", "continue_iterations", "mass_full", "mass_goal_ratio",
                "mass_removal_ratio", "mass_addition_ratio", "i_violated"):
        v = ns.get(key)
        rec[key] = v if isinstance(v, (int, float, bool, str)) or v is None else str(v)
    rec["mass"] = [float(m) for m in ns.get("mass", [])]
    rec["energy_density_mean"] = [float(e) for e in ns.get("energy_density_mean", [])]
    rec["seconds"] = time.time() - t_start
    with open(os.path.join(work, "result.json"), "w", encoding="utf-8") as fh:
        json.dump(rec, fh)
    return 0 if rec["status"] == "finished" else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
'''


def _kill_tree(proc: subprocess.Popen) -> None:
    """Kill the driver and its ccx child (BESO's ccx keeps running if only the driver dies)."""
    import psutil
    try:
        children = psutil.Process(proc.pid).children(recursive=True)
    except psutil.Error:
        children = []
    for c in children:
        with contextlib.suppress(psutil.Error):
            c.kill()
    with contextlib.suppress(OSError):
        proc.kill()


def _tail(path: Path, n: int = 30) -> str:
    try:
        return "\n".join(path.read_text(encoding="utf-8", errors="replace").strip().splitlines()[-n:])
    except OSError:
        return ""


# ---------------------------------------------------------------------------------------------------- entrant
def generate(dom: DesignDomain, budget_s: float = 300.0, threads: int = 2, element: str = ELEMENT,
             r_mm: float | None = None, solver: str = "auto", keep_workdir: str | None = None) -> GenResult:
    """Run BESO (stiffness, target mass = vol_frac of the design voxels) on the domain within `budget_s`."""
    t0 = time.perf_counter()
    wall0 = time.time()
    if not available():
        raise FileNotFoundError(f"BESO scripts ({BESO_DIR}) or CalculiX ({CCX_EXE}) missing; see "
                                "tools/toolchain.lock.json ('beso', 'ccx')")
    h = float(dom.h)
    r = float(r_mm) if r_mm is not None else filter_radius(h)
    design, passive, isolated = split_domain(dom, r)
    n_design_all = int(dom.design().sum())
    density = np.zeros(dom.shape)
    density[passive] = 1.0
    if not design.any():
        return GenResult(density, time.perf_counter() - t0, NAME,
                         notes=["no optimisable design voxels: passives only"], iterations=0)
    goal = (dom.vol_frac * n_design_all - int(isolated.sum())) / int(design.sum())
    goal = float(min(max(goal, 0.0), 1.0))
    it_goal = iterations_to_goal(goal, REMOVAL, ADDITION)
    it_limit = it_goal + EXTRA_IT

    tmp = None
    if keep_workdir is None:
        tmp = tempfile.TemporaryDirectory(prefix="t2s_beso_", ignore_cleanup_errors=True)
        work = Path(tmp.name)
    else:
        work = Path(keep_workdir)
        work.mkdir(parents=True, exist_ok=True)
    try:
        model = write_deck(dom, work / "beso.inp", design, passive, element, solver)
        write_conf(work / "beso_conf.py", dom.material, goal, r, it_limit, threads)
        (work / "beso_driver.py").write_text(_DRIVER, encoding="utf-8")
        elapsed = time.perf_counter() - t0
        deadline = wall0 + budget_s - 1.0
        cfg = {"workdir": str(work), "beso_dir": str(BESO_DIR), "deadline": deadline, "h": h, "adaptive": True,
               "reserve_it": RESERVE_IT, "rate_max": RATE_MAX, "removal": REMOVAL, "solver": model["solver"]}
        (work / "run.json").write_text(json.dumps(cfg), encoding="utf-8")
        env = dict(os.environ)
        for v in THREAD_VARS:
            env[v] = str(int(threads))
        env["MPLBACKEND"] = "Agg"
        env["PATH"] = str(CCX_EXE.parent) + os.pathsep + env.get("PATH", "")
        log_path = work / "beso_run.log"
        t_run = time.perf_counter()
        killed = False
        with open(log_path, "w", encoding="utf-8", errors="replace") as log:
            proc = subprocess.Popen([sys.executable, "-I", "-u", str(work / "beso_driver.py"), str(work / "run.json")],
                                    cwd=str(work), env=env, stdout=log, stderr=subprocess.STDOUT)
            try:
                proc.wait(timeout=max(budget_s - elapsed, 1.0) + 60.0)
            except subprocess.TimeoutExpired:
                _kill_tree(proc)
                proc.wait()
                killed = True
            except BaseException:            # interrupted: do not leave BESO / ccx running
                _kill_tree(proc)
                raise
        t_run = time.perf_counter() - t_run
        res_path = work / "result.json"
        if res_path.is_file():
            res = json.loads(res_path.read_text(encoding="utf-8"))
        elif killed and (work / "state_snapshot.json").is_file():
            res = {"status": "killed", "states": json.loads((work / "state_snapshot.json").read_text("utf-8")),
                   "compliance": [], "mass": [], "energy_density_mean": []}
        else:
            raise RuntimeError(f"BESO run failed (exit code {proc.returncode}) in {work}:\n{_tail(log_path)}")
        if res["status"] == "error":
            raise RuntimeError(f"BESO run failed in {work}:\n{res.get('traceback', '')}\n{_tail(log_path)}")
        states = res["states"]
    finally:
        if tmp is not None:
            tmp.cleanup()

    flat = density.reshape(-1)
    d_eid = model["eid"][model["is_design"]]
    st = np.array([states.get(str(int(e)), 1) for e in d_eid], float)
    missing = sum(1 for e in d_eid if str(int(e)) not in states)
    flat[d_eid - 1] = st
    density = flat.reshape(dom.shape)
    density[dom.void] = 0.0
    density[passive] = 1.0

    comp = [float(sum(c)) for c in res.get("compliance", [])]
    n_fe = len(res.get("compliance", []))
    sol = density[dom.design()]
    vf = float(sol.mean()) if sol.size else 0.0
    if res["status"] == "killed":
        stop = "killed at the hard time limit (last analysed states)"
    elif res.get("stopped_by_budget"):
        stop = "wall-clock budget"
    elif res.get("oscillations") is True:
        stop = "BESO oscillation check (state of 2 iterations back)"
    elif res.get("continue_iterations") is False:
        stop = f"converged (mean energy density change < {TOLERANCE} over 5 iterations)"
    else:
        stop = f"iteration limit {res.get('iterations_limit')}"
    edm = res.get("energy_density_mean", [])
    notes = [
        (f"BESO {BESO_COMMIT[:7]} ({BESO_DATE}, github.com/calculix/beso, unmodified) + CalculiX 2.23, "
         f"{threads} thread(s)"),
        (f"model: {model['elements']} {element} voxels (h = {h} mm; {model['design']} design, {model['passive']} "
         f"passive), {model['nodes']} nodes, {model['fixed_nodes']} clamped target-plane nodes, "
         f"{model['contact_voxels']} loaded contact voxels; 3 *STATIC steps ({', '.join(model['cases'])}, solver "
         f"{model['solver']}) with the contact force and *DLOAD GRAV self-weight"),
        (f"BESO: optimization_base stiffness, 2 states (void E, rho x {VOID:g}), mass_goal_ratio {goal:.4f}, "
         f"filter simple r = {r:g} mm, sensitivity_averaging, removal {REMOVAL} / addition {ADDITION} (relative), "
         f"decay {DECAY}, tolerance {TOLERANCE}, iterations_limit {it_limit}"),
        (f"{n_fe} FE iterations in {t_run:.1f} s, stop: {stop}; design volume fraction {vf:.4f} "
         f"(target {dom.vol_frac})"),
    ]
    if comp:
        notes.append(f"compliance c_x + c_y + c_z: {comp[0]:.4g} -> {comp[-1]:.4g} N mm (from ENER x V, all elements)")
    if edm:
        notes.append(f"BESO energy_density_mean: {edm[0]:.4g} -> {edm[-1]:.4g} MPa")
    raised = [(it, r_) for it, r_ in res.get("rate_changes", []) if r_ > REMOVAL]
    if raised:
        notes.append(f"budget: mass_removal_ratio raised above {REMOVAL} in {len(raised)} iteration(s) (iterations "
                     f"{raised[0][0]}-{raised[-1][0]}, max {max(r_ for _, r_ in raised):.3f}) to reach the target "
                     f"mass within the budget")
    if res.get("ccx_failures"):
        notes.append(f"ccx failed {len(res['ccx_failures'])} time(s) and was re-run ([iteration, attempt, exit code]: "
                     f"{res['ccx_failures'][:5]})")
    if int(isolated.sum()):
        notes.append(f"{int(isolated.sum())} isolated design voxel(s) (no design neighbour within {r:g} mm) set "
                     f"passive solid")
    if missing:
        notes.append(f"{missing} design element state(s) missing from BESO's output: kept solid")
    return GenResult(density, time.perf_counter() - t0, NAME, notes=notes, iterations=n_fe, history=comp)
