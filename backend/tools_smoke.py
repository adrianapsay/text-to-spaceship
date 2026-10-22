"""Import smoke test for the toolchain (protocol test T-T). Run: uv run python tools_smoke.py"""
import sys

import numpy as np


def check(name, fn):
    try:
        detail = fn()
        print(f"PASS {name}: {detail}")
        return True
    except Exception as exc:  # noqa: BLE001 - report every failure
        print(f"FAIL {name}: {type(exc).__name__}: {exc}")
        return False


def fcl_check():
    import fcl
    a = fcl.CollisionObject(fcl.Box(1, 1, 1), fcl.Transform())
    b = fcl.CollisionObject(fcl.Box(1, 1, 1), fcl.Transform(np.array([3.0, 0, 0])))
    res = fcl.DistanceResult()
    d = fcl.distance(a, b, fcl.DistanceRequest(), res)
    assert abs(d - 2.0) < 1e-9, d
    return f"box-box distance {d}"


def manifold_check():
    import manifold3d as m3d
    c = m3d.Manifold.cube([1, 1, 1])
    d = m3d.Manifold.cube([1, 1, 1]).translate([3, 0, 0])
    gap = c.min_gap(d, 10.0)
    assert abs(gap - 2.0) < 1e-9, gap
    return f"volume {c.volume()}, min_gap {gap}, split_by_plane {hasattr(c, 'split_by_plane')}"


def coacd_check():
    import coacd
    v = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]], float)
    f = np.array([[0, 2, 1], [0, 1, 3], [0, 3, 2], [1, 2, 3]], np.int32)
    parts = coacd.run_coacd(coacd.Mesh(v, f), threshold=0.1, preprocess_mode="off", seed=1)
    return f"{len(parts)} piece(s)"


def numba_check():
    from numba import njit

    @njit(cache=False, nogil=True)
    def s(x):
        t = 0.0
        for v in x:
            t += v
        return t
    return f"njit sum {s(np.arange(10.0))}"


def pymoo_check():
    from pymoo.algorithms.moo.nsga2 import NSGA2
    from pymoo.indicators.hv import HV
    from pymoo.optimize import minimize
    from pymoo.problems import get_problem
    res = minimize(get_problem("zdt1"), NSGA2(pop_size=40), ("n_gen", 40), seed=1, verbose=False)
    hv = HV(ref_point=np.array([1.1, 1.1, 1.1]))(np.eye(3))
    assert abs(hv - 0.331) < 1e-9, hv
    return f"ZDT1 front {len(res.F)} pts; HV(unit simplex corners)={hv:.6f}"


def ortools_check():
    from ortools.sat.python import cp_model
    m = cp_model.CpModel()
    x = m.new_int_var(0, 10, "x")
    m.maximize(x)
    s = cp_model.CpSolver()
    st = s.solve(m)
    return f"status {s.status_name(st)} x={s.value(x)}"


def trimesh_check():
    import trimesh
    b = trimesh.creation.box((2, 3, 4))
    return f"box volume {b.volume}"


ok = all([check("python-fcl", fcl_check), check("manifold3d", manifold_check), check("coacd (abi3 on 3.14)", coacd_check),
          check("numba", numba_check), check("pymoo+moocore", pymoo_check), check("ortools", ortools_check),
          check("trimesh", trimesh_check)])
print("Python", sys.version.split()[0], "ALL PASS" if ok else "FAILURES")
sys.exit(0 if ok else 1)
