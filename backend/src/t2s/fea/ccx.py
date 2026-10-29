"""CalculiX (ccx 2.23) solver for the V2 FEA contract: `solve(FeaProblem) -> FeaResult`.

Set-up (independent of the NGSolve module; both start from the same mesh and face sets, see problem.py):
- C3D10 elements: the gmsh 10-node tets with mid-nodes 8 and 9 swapped (gmsh (3-2),(3-1) -> C3D10 (1-3),(2-3)).
- Linear elastic isotropic material with density.
- Every node of `fixed_faces` fixed in x, y and z (*BOUNDARY).
- One *STATIC step per load case: surface loads as *CLOAD nodal forces from `mesh.consistent_surface_load`
  (uniform traction on straight 6-node triangles: 1/3 of each face's share at each mid-side node), body acceleration
  as *DLOAD GRAV on all elements. Loads are replaced (OP=NEW) in every step, so the cases are independent.
- A *FREQUENCY step (SPOOLES + ARPACK shift-invert) for `n_modes` natural frequencies of the fixed, unloaded part.
- Added non-structural mass (`problem.added_masses`): each mass lumped to the nodes of its faces with the consistent
  weights of a uniform traction (corners 0, mid-side nodes share) as CalculiX MASS point elements in their own element
  sets, outside EALL: they enter the frequency step's mass matrix only (no GRAV, not in EMAS / FeaResult.mass_t).

Results:
- displacements from the .dat file (*NODE PRINT, 7 significant digits),
- nodal stresses from the .frd file (*EL FILE S, 6 significant digits): CalculiX extrapolates each element's
  integration-point stresses to the element's nodes (C3D10: exact linear extrapolation from the 4 Gauss points to the
  corners, mid-nodes the mean of their two corners, i.e. the element's linear stress field evaluated at the node)
  and averages the tensor component-wise over the elements sharing the node; von Mises of that averaged tensor,
- reactions at the fixed nodes (*NODE PRINT, NSET=NFIX, TOTALS=YES: every node's RF and the total): RF is the
  internal nodal force at the constrained nodes, which leaves out external load applied directly AT those nodes (the
  consistent body load of the elements touching the support, and any *CLOAD on a fixed node). The reported total
  reaction is therefore RF minus that load, computed exactly here (straight 10-node tet: integral of N_i over the
  element = -V/20 at corners, V/5 at mid-nodes, which CalculiX's 4-point rule integrates exactly), so reaction +
  applied = 0; the per-node RF is kept (CaseResult.support_forces_n) for the bolt loads (gd.bolts),
- total mass (*EL PRINT TOTALS=ONLY EMAS),
- eigenfrequencies in cycles per second (the units mm, N, t, s are consistent).

Threads: `threads` is passed to every CalculiX thread variable (OMP_NUM_THREADS, NUMBER_OF_CPUS, CCX_NPROC_*);
BLAS/LAPACK is the single-threaded netlib build. threads = 1 is bitwise repeatable. More threads change the
floating-point summation order of the stiffness assembly (CCX_NPROC_STIFFNESS) and of the SPOOLES factorisation
(CCX_NPROC_EQUATION_SOLVER), so displacements move in the last printed digit (measured on a slender cantilever: up to
4.7e-7 of max |u|), and two multi-threaded runs are not always bitwise identical either.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .mesh import consistent_surface_load
from .problem import CaseResult, FeaProblem, FeaResult

ROOT = Path(__file__).resolve().parents[4]
CCX_DIR = ROOT / "tools" / "ccx"
# Windows: ccx.exe with its DLLs beside it; macOS: bin/ccx, its dylibs in lib/ (its rpath; core.toolchain)
CCX_EXE = CCX_DIR / "ccx.exe" if sys.platform == "win32" else CCX_DIR / "bin" / "ccx"
SOLVER = "CalculiX 2.23"
JOB = "job"

GMSH_TO_C3D10 = np.array([0, 1, 2, 3, 4, 5, 6, 7, 9, 8])          # positions 8 and 9 swapped
THREAD_VARS = ("OMP_NUM_THREADS", "NUMBER_OF_CPUS", "CCX_NPROC_EQUATION_SOLVER", "CCX_NPROC_STIFFNESS",
               "CCX_NPROC_RESULTS", "CCX_NPROC_CFD", "CCX_NPROC_SENS", "CCX_NPROC_VIEWFACTOR")


def available() -> bool:
    return CCX_EXE.is_file()


@dataclass
class CcxFields:
    """Full nodal fields (node order of problem.nodes), one entry per load case."""
    displacement: list[np.ndarray] = field(default_factory=list)   # (n, 3) mm
    stress: list[np.ndarray] = field(default_factory=list)         # (n, 6) MPa: xx, yy, zz, xy, yz, zx
    von_mises: list[np.ndarray] = field(default_factory=list)      # (n,) MPa
    workdir: str | None = None                                     # kept work files (None: deleted)


# ---------------------------------------------------------------------------------------------------- deck writing
def _num(x: float) -> str:
    """CalculiX reads at most 20 characters per numeric field: 13 significant digits, at most 19 characters."""
    x = float(x)
    if not np.isfinite(x):
        raise ValueError(f"non-finite number {x} in the CalculiX deck")
    if abs(x) < 1e-90:
        return "0."
    if abs(x) >= 1e90:
        raise ValueError(f"number {x} out of range for the CalculiX deck")
    return f"{x:.12e}"


def _id_lines(ids, per_line: int = 16) -> list[str]:
    ids = [str(int(i)) for i in ids]
    return [",".join(ids[k:k + per_line]) for k in range(0, len(ids), per_line)]


def case_nodal_loads(problem: FeaProblem, case) -> dict[int, np.ndarray]:
    """Consistent nodal forces (0-based node -> (3,) N) of a load case's surface loads."""
    out: dict[int, np.ndarray] = {}
    for sl in case.surface_loads:
        if len(sl.faces) == 0:
            if np.any(np.asarray(sl.total_force_n, float) != 0):
                raise ValueError(f"load case {case.name!r}: a surface load of {sl.total_force_n} N has no faces")
            continue
        for n, f in consistent_surface_load(problem.nodes, np.asarray(sl.faces), sl.total_force_n,
                                            getattr(sl, "moment_nmm", None)).items():
            out[n] = out.get(n, np.zeros(3)) + f
    return out


def added_nodal_masses(problem: FeaProblem) -> dict[int, float]:
    """Non-structural masses (problem.added_masses) lumped to nodes (0-based node -> t) with the consistent weights of
    a uniform traction: corners 0, each mid-side node 1/3 of its face's area share. On straight 6-node triangles this
    reproduces the total mass, centroid and second moments of the uniformly smeared mass exactly (the 3-mid-point
    rule integrates quadratics exactly)."""
    out: dict[int, float] = {}
    for faces, mass in getattr(problem, "added_masses", None) or []:
        mass = float(mass)
        if mass < 0 or not np.isfinite(mass):
            raise ValueError(f"added mass {mass} t must be finite and >= 0")
        if mass == 0:
            continue
        faces = np.asarray(faces, np.int64).reshape(-1, 6)
        if len(faces) == 0:
            raise ValueError(f"added mass of {mass} t has no faces")
        for n, w in consistent_surface_load(problem.nodes, faces, [1.0, 0.0, 0.0]).items():
            out[n] = out.get(n, 0.0) + mass * float(w[0])
    return out


STATIC_SOLVERS = ("SPOOLES", "ITERATIVE CHOLESKY")   # direct (default); preconditioned CG (M4: memory-light)


def write_deck(problem: FeaProblem, path: Path, solver: str = "SPOOLES") -> None:
    if solver not in STATIC_SOLVERS:
        raise ValueError(f"unknown CalculiX static solver {solver!r} ({', '.join(STATIC_SOLVERS)})")
    nodes, tets = np.asarray(problem.nodes, float), np.asarray(problem.tets, np.int64)
    mat = problem.material
    fixed = problem.fixed_nodes()
    title = (problem.label or "bracket").encode("ascii", "replace").decode("ascii")[:60]
    out: list[str] = ["*HEADING", f"T2S {title} (CalculiX C3D10, units mm N t s)"]
    out.append("*NODE, NSET=NALL")
    out += [f"{i + 1},{_num(x)},{_num(y)},{_num(z)}" for i, (x, y, z) in enumerate(nodes)]
    out.append("*ELEMENT, TYPE=C3D10, ELSET=EALL")
    conn = tets[:, GMSH_TO_C3D10] + 1
    out += [f"{e + 1}," + ",".join(map(str, row)) for e, row in enumerate(conn.tolist())]
    out.append("*NSET, NSET=NFIX")
    out += _id_lines(fixed + 1)
    out += ["*MATERIAL, NAME=MAT", "*ELASTIC", f"{_num(mat.E_mpa)},{_num(mat.nu)}",
            "*DENSITY", _num(mat.rho_t_mm3),
            "*SOLID SECTION, ELSET=EALL, MATERIAL=MAT"]
    # added (non-structural) mass: MASS point elements, one element set per distinct value, kept outside EALL so
    # that neither *DLOAD GRAV nor the EMAS total includes them
    groups: dict[str, list[int]] = {}
    for nid, m in sorted(added_nodal_masses(problem).items()):
        if m > 0:
            groups.setdefault(_num(m), []).append(nid)
    eid = len(tets)
    for g, (mstr, nids) in enumerate(groups.items(), start=1):
        out.append(f"*ELEMENT, TYPE=MASS, ELSET=EADDM{g}")
        for nid in nids:
            eid += 1
            out.append(f"{eid},{nid + 1}")
        out += [f"*MASS, ELSET=EADDM{g}", mstr]
    out += ["*BOUNDARY", "NFIX,1,3"]
    if problem.n_modes > 0:
        # first, so that no output request of a static step carries over into it
        out += ["*STEP", "*FREQUENCY, SOLVER=SPOOLES", str(int(problem.n_modes)), "*END STEP"]
    for k, case in enumerate(problem.load_cases):
        out += ["*STEP", f"*STATIC, SOLVER={solver}", "*CLOAD, OP=NEW"]
        loads = case_nodal_loads(problem, case)
        lines = [f"{n + 1},{d + 1},{_num(f[d])}" for n, f in sorted(loads.items()) for d in range(3) if f[d] != 0.0]
        out += lines or ["1,1,0."]
        out.append("*DLOAD, OP=NEW")
        a = None if case.body_accel_mm_s2 is None else np.asarray(case.body_accel_mm_s2, float)
        if a is not None and np.linalg.norm(a) > 0:
            g = float(np.linalg.norm(a))
            out.append(f"EALL,GRAV,{_num(g)},{_num(a[0] / g)},{_num(a[1] / g)},{_num(a[2] / g)}")
        else:
            out.append("EALL,GRAV,0.,0.,0.,-1.")
        out += ["*NODE PRINT, NSET=NALL", "U",
                "*NODE PRINT, NSET=NFIX, TOTALS=YES", "RF",
                "*EL PRINT, ELSET=EALL, TOTALS=ONLY", "EMAS",
                "*EL FILE", "S",
                "*END STEP"]
    path.write_text("\n".join(out) + "\n", encoding="ascii")


# ---------------------------------------------------------------------------------------------------- running
CCX_TIMEOUT_S = 900.0   # a safeguard (no run has hung so far): a bracket solve takes seconds to minutes, so one still
#                         running after 15 min is killed and fails like any other run (evaluate.py tries it once more)


def run_ccx(workdir: Path, threads: int = 2, job: str = JOB, timeout_s: float | None = None) -> str:
    if not available():
        raise FileNotFoundError(f"CalculiX not found at {CCX_EXE} (see tools/toolchain.lock.json, 'ccx')")
    env = dict(os.environ)
    for v in THREAD_VARS:
        env[v] = str(int(threads))
    env["PATH"] = str(CCX_EXE.parent) + os.pathsep + env.get("PATH", "")
    limit = CCX_TIMEOUT_S if timeout_s is None else float(timeout_s)
    try:
        proc = subprocess.run([str(CCX_EXE), "-i", job], cwd=str(workdir), env=env, capture_output=True, text=True,
                              errors="replace", check=False, timeout=limit)
    except subprocess.TimeoutExpired as exc:          # subprocess.run has killed it
        raise RuntimeError(f"ccx did not finish within {limit:.0f} s in {workdir} (killed)") from exc
    log = proc.stdout + proc.stderr
    (workdir / f"{job}.log").write_text(log, encoding="utf-8")
    if proc.returncode != 0 or "*ERROR" in log or "Job finished" not in log:
        tail = "\n".join(log.strip().splitlines()[-25:])
        raise RuntimeError(f"ccx failed (exit code {proc.returncode}) in {workdir}:\n{tail}")
    return log


# ---------------------------------------------------------------------------------------------------- parsing
_FLOAT = r"[-+]?\d*\.\d+(?:[EeDd][-+]?\d+)?"
_EIG_ROW = re.compile(rf"^\s*(\d+)\s+({_FLOAT})\s+({_FLOAT})\s+({_FLOAT})\s+({_FLOAT})\s*$")


@dataclass
class _DatStep:
    disp_ids: list[int] = field(default_factory=list)            # node ids (1-based)
    disp: list[tuple[float, float, float]] = field(default_factory=list)
    rf_ids: list[int] = field(default_factory=list)              # supported node ids (1-based)
    rf: list[tuple[float, float, float]] = field(default_factory=list)
    rf_total: np.ndarray | None = None
    mass: float | None = None
    eig_hz: list[float] = field(default_factory=list)
    eig_lambda: list[float] = field(default_factory=list)


def parse_dat(text: str) -> list[_DatStep]:
    lines = text.splitlines()
    steps: list[_DatStep] = []
    i, n = 0, len(lines)

    def next_data(j):                      # index of the next non-blank line
        while j < n and not lines[j].strip():
            j += 1
        return j

    while i < n:
        s = lines[i]
        if "S T E P" in s:
            steps.append(_DatStep())
            i += 1
            continue
        if not steps:
            i += 1
            continue
        st = steps[-1]
        if s.lstrip().startswith("displacements (vx,vy,vz) for set NALL"):
            j = next_data(i + 1)
            while j < n and lines[j].strip():
                t = lines[j].split()
                st.disp_ids.append(int(t[0]))
                st.disp.append((float(t[1]), float(t[2]), float(t[3])))
                j += 1
            i = j
            continue
        if s.lstrip().startswith("forces (fx,fy,fz) for set NFIX"):
            j = next_data(i + 1)
            while j < n and lines[j].strip():
                t = lines[j].split()
                st.rf_ids.append(int(t[0]))
                st.rf.append((float(t[1]), float(t[2]), float(t[3])))
                j += 1
            i = j
            continue
        if s.lstrip().startswith("total force (fx,fy,fz) for set NFIX"):
            j = next_data(i + 1)
            st.rf_total = np.array([float(v) for v in lines[j].split()[:3]])
            i = j + 1
            continue
        if s.lstrip().startswith("total mass for set EALL"):
            j = next_data(i + 1)
            st.mass = float(lines[j].split()[0])
            i = j + 1
            continue
        if "E I G E N V A L U E   O U T P U T" in s:
            j = i + 1
            started = False
            while j < n:
                m = _EIG_ROW.match(lines[j])
                if m:
                    started = True
                    st.eig_lambda.append(float(m.group(2)))
                    st.eig_hz.append(float(m.group(4)))           # (CYCLES/TIME)
                elif started:
                    break
                j += 1
            i = j
            continue
        i += 1
    return steps


def parse_frd_stress(text: str) -> list[tuple[list[int], list[list[float]]]]:
    """Every STRESS block of an ASCII .frd file, in file order: (node ids, rows of xx, yy, zz, xy, yz, zx).
    Records are fixed width (' -1', I10, 6 x E12.5); adjacent numbers may touch, so they are sliced, not split."""
    blocks: list[tuple[list[int], list[list[float]]]] = []
    cur = None
    for line in text.splitlines():
        if line.startswith(" -4"):
            cur = ([], []) if line.split()[1] == "STRESS" else None
            if cur is not None:
                blocks.append(cur)
        elif line.startswith(" -3"):
            cur = None
        elif cur is not None and line.startswith(" -1"):
            cur[0].append(int(line[3:13]))
            cur[1].append([float(line[13 + 12 * k:25 + 12 * k]) for k in range(6)])
    return blocks


def von_mises(s: np.ndarray) -> np.ndarray:
    """s: (..., 6) xx, yy, zz, xy, yz, zx."""
    xx, yy, zz, xy, yz, zx = (s[..., k] for k in range(6))
    return np.sqrt(0.5 * ((xx - yy) ** 2 + (yy - zz) ** 2 + (zz - xx) ** 2) + 3.0 * (xy ** 2 + yz ** 2 + zx ** 2))


def body_load_weights(nodes: np.ndarray, tets: np.ndarray) -> np.ndarray:
    """Per node: integral of its shape function over the mesh (straight 10-node tets: -V/20 corners, V/5 mid-nodes).
    The consistent nodal body force of a uniform acceleration a is rho * a * weight."""
    p = nodes[tets[:, :4]]
    vol = np.einsum("ij,ij->i", p[:, 1] - p[:, 0], np.cross(p[:, 2] - p[:, 0], p[:, 3] - p[:, 0])) / 6.0
    w = np.zeros(len(nodes))
    np.add.at(w, tets[:, :4], -vol[:, None] / 20.0)
    np.add.at(w, tets[:, 4:], vol[:, None] / 5.0)
    return w


# ---------------------------------------------------------------------------------------------------- solve
def _field(ids, values, n: int, width: int, what: str) -> np.ndarray:
    ids = np.asarray(ids, np.int64) - 1
    values = np.asarray(values, float).reshape(-1, width)
    if len(ids) != n or not np.array_equal(np.sort(ids), np.arange(n)):
        raise RuntimeError(f"CalculiX {what}: {len(ids)} node values in the output for {n} mesh nodes")
    out = np.empty((n, width))
    out[ids] = values
    return out


def run(problem: FeaProblem, threads: int = 2, workdir: str | None = None,
        solver: str = "SPOOLES") -> tuple[FeaResult, CcxFields]:
    """Solve and also return the nodal fields. Work files are kept in `workdir` if given, else deleted. `solver`: the
    static steps' solver, SPOOLES (direct, default) or ITERATIVE CHOLESKY (M4: when the direct one would not fit)."""
    t0 = time.perf_counter()
    nodes, tets = np.asarray(problem.nodes, float), np.asarray(problem.tets, np.int64)
    n = len(nodes)
    fixed = problem.fixed_nodes()
    if len(fixed) == 0 and (problem.load_cases or problem.n_modes > 0):
        raise ValueError("CalculiX solve needs at least one fixed face (the part would be unsupported)")
    tmp = None
    if workdir is None:
        tmp = tempfile.TemporaryDirectory(prefix="t2s_ccx_")
        wd = Path(tmp.name)
    else:
        wd = Path(workdir)
        wd.mkdir(parents=True, exist_ok=True)
    try:
        write_deck(problem, wd / f"{JOB}.inp", solver)
        t_ccx = time.perf_counter()
        log = run_ccx(wd, threads)
        t_ccx = time.perf_counter() - t_ccx
        steps = parse_dat((wd / f"{JOB}.dat").read_text(encoding="ascii", errors="replace"))
        stress_blocks = parse_frd_stress((wd / f"{JOB}.frd").read_text(encoding="ascii", errors="replace")) \
            if problem.load_cases else []
    finally:
        if tmp is not None:
            tmp.cleanup()

    n_freq = 1 if problem.n_modes > 0 else 0
    if len(steps) != n_freq + len(problem.load_cases):
        raise RuntimeError(f"CalculiX .dat has {len(steps)} steps, expected {n_freq + len(problem.load_cases)}")
    if len(stress_blocks) != len(problem.load_cases):
        raise RuntimeError(f"CalculiX .frd has {len(stress_blocks)} stress blocks, "
                           f"expected {len(problem.load_cases)}")

    notes = [(f"ccx {CCX_EXE} with {threads} thread(s); {n} nodes, {len(tets)} C3D10 elements, "
              f"{len(fixed)} fixed nodes; ccx run {t_ccx:.2f} s; static solver {solver}"),
             ("nodal stress: CalculiX frd (Gauss-point stresses extrapolated per element, tensor averaged over the "
              "elements sharing the node), von Mises of the averaged tensor"),
             "reaction = CalculiX RF total at the fixed nodes minus the external load applied directly at them"]
    m = re.search(r"number of equations\s+(\d+)", log)
    if m:
        notes.append(f"{m.group(1)} equations")
    added = added_nodal_masses(problem)
    warnings = {ln.strip() for ln in log.splitlines() if "*WARNING" in ln}
    if added:
        # ccx stores each *MASS value as an internal material "MASS" and warns that it has no elastic constants
        # (MAT always has *ELASTIC, so the warning can only concern those)
        warnings = {w for w in warnings if "no elastic constants" not in w}
    notes += sorted(warnings)[:10]

    weights = body_load_weights(nodes, tets)
    w_fixed = float(weights[fixed].sum())
    is_fixed = np.zeros(n, bool)
    is_fixed[fixed] = True
    keep = np.ones(n, bool)
    if problem.exclude_nodes is not None and len(problem.exclude_nodes):
        keep[np.asarray(problem.exclude_nodes, np.int64)] = False
    mass_geom = problem.mass_t()
    rho = problem.material.rho_t_mm3

    fields = CcxFields(workdir=None if tmp is not None else str(wd))
    cases: list[CaseResult] = []
    mass_ccx = None
    for k, case in enumerate(problem.load_cases):
        st = steps[n_freq + k]
        u = _field(st.disp_ids, st.disp, n, 3, f"displacements of case {case.name!r}")
        s = _field(*stress_blocks[k], n, 6, f"stresses of case {case.name!r}")
        vm = von_mises(s)
        if st.rf_total is None:
            raise RuntimeError(f"CalculiX .dat has no reaction total for case {case.name!r}")
        if st.mass is not None:
            mass_ccx = st.mass
        loads = case_nodal_loads(problem, case)
        applied = sum((np.asarray(sl.total_force_n, float) for sl in case.surface_loads), np.zeros(3))
        at_fixed = sum((f for nid, f in loads.items() if is_fixed[nid]), np.zeros(3))
        if np.any(at_fixed != 0):
            notes.append(f"case {case.name!r}: surface load {at_fixed.tolist()} N acts on fixed nodes")
        a = np.zeros(3) if case.body_accel_mm_s2 is None else np.asarray(case.body_accel_mm_s2, float)
        applied = applied + mass_geom * a
        at_fixed = at_fixed + rho * a * w_fixed
        reaction = st.rf_total - at_fixed
        rf_ids = np.asarray(st.rf_ids, np.int64) - 1
        if len(rf_ids) != len(fixed) or not np.array_equal(np.sort(rf_ids), fixed):
            raise RuntimeError(f"CalculiX .dat has {len(rf_ids)} nodal reactions for case {case.name!r}, expected "
                               f"{len(fixed)} supported nodes")
        support = np.asarray(st.rf, float).reshape(-1, 3)[np.argsort(rf_ids)]   # fixed_nodes() order (sorted)
        fields.displacement.append(u)
        fields.stress.append(s)
        fields.von_mises.append(vm)
        cases.append(CaseResult(
            name=case.name,
            max_disp_mm=float(np.linalg.norm(u, axis=1).max()),
            max_vm_mpa=float(vm.max()),
            max_vm_filtered_mpa=float(vm[keep].max()) if keep.any() else 0.0,
            reaction_n=reaction,
            applied_n=applied,
            support_nodes=fixed.copy(),
            support_forces_n=support))
    if not keep.any():
        notes.append("every node is in exclude_nodes: filtered peak stress set to 0")

    freqs: list[float] = []
    if n_freq:
        freqs = sorted(steps[0].eig_hz)
        if len(freqs) < problem.n_modes:
            notes.append(f"CalculiX returned {len(freqs)} of {problem.n_modes} requested modes")
    if mass_ccx is not None and abs(mass_ccx - mass_geom) > 1e-6 * mass_geom:
        notes.append(f"CalculiX mass {mass_ccx:.7g} t differs from the mesh volume x density {mass_geom:.7g} t")
    if added:
        notes.append(f"added non-structural mass {sum(added.values()):.7g} t on {len(added)} nodes (CalculiX MASS "
                     f"elements; in the modal mass only, not in mass_t nor in body loads; ccx's 'no elastic "
                     f"constants' warnings for its internal MASS materials are expected and dropped)")
    return FeaResult(solver=SOLVER, cases=cases, frequencies_hz=freqs,
                     mass_t=float(mass_ccx if mass_ccx is not None else mass_geom),
                     n_nodes=n, n_elements=len(tets), seconds=time.perf_counter() - t0, notes=notes), fields


def solve(problem: FeaProblem, threads: int = 2, workdir: str | None = None) -> FeaResult:
    """Linear static load cases + natural frequencies with CalculiX (see the module docstring)."""
    return run(problem, threads, workdir)[0]
