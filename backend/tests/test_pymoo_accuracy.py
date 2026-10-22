"""Decision U1: pymoo / moocore are used only if they pass these accuracy checks (else we write our own)."""
import itertools

import numpy as np
import pytest


def brute_fronts(F):
    left = list(range(len(F)))
    fronts = []
    while left:
        front = [i for i in left if not any(np.all(F[j] <= F[i]) and np.any(F[j] < F[i]) for j in left if j != i)]
        fronts.append(sorted(front))
        left = [i for i in left if i not in front]
    return fronts


@pytest.mark.parametrize("seed", [0, 1, 2])
def test_nondominated_sorting_matches_brute_force(seed):
    from pymoo.util.nds.non_dominated_sorting import NonDominatedSorting
    rng = np.random.default_rng(seed)
    F = rng.integers(0, 6, size=(150, 3)).astype(float)      # many ties and duplicates on purpose
    got = [sorted(f.tolist()) for f in NonDominatedSorting().do(F)]
    assert got == brute_fronts(F)


def staircase_area(P, ref):
    """Exact 2-D dominated area for a non-dominated set (minimisation)."""
    P = P[np.argsort(P[:, 0])]
    area, prev_y = 0.0, ref[1]
    for x, y in P:
        if y < prev_y:
            area += (ref[0] - x) * (prev_y - y)
            prev_y = y
    return area


def test_hypervolume_exact():
    import moocore
    from pymoo.indicators.hv import HV
    rng = np.random.default_rng(5)
    for _ in range(20):
        x = np.sort(rng.random(12))
        P = np.column_stack([x, 1.0 - np.sqrt(x)])            # a non-dominated 2-D set
        ref = np.array([1.2, 1.2])
        exact = staircase_area(P, ref)
        assert abs(HV(ref_point=ref)(P) - exact) < 1e-12
        assert abs(moocore.hypervolume(P, ref=ref) - exact) < 1e-12
    # 3-D: unit cubes on a grid, exact volume by inclusion of a known union
    P = np.array([[0, 0, 1], [0, 1, 0], [1, 0, 0]], float)
    ref = np.array([2.0, 2.0, 2.0])
    exact = 0.0
    for cell in itertools.product((0, 1), repeat=3):
        lo = np.array(cell, float)
        if any(np.all(p <= lo) for p in P):
            exact += 1.0
    assert abs(moocore.hypervolume(P, ref=ref) - exact) < 1e-12
    assert abs(HV(ref_point=ref)(P) - exact) < 1e-12


def test_nsga2_converges_on_zdt1():
    from pymoo.algorithms.moo.nsga2 import NSGA2
    from pymoo.indicators.igd import IGD
    from pymoo.optimize import minimize
    from pymoo.problems import get_problem
    problem = get_problem("zdt1")
    res = minimize(problem, NSGA2(pop_size=100), ("n_gen", 200), seed=1, verbose=False)
    igd = IGD(problem.pareto_front())(res.F)
    assert igd < 0.01, igd


def test_ask_tell_matches_island_use():
    """The ask/tell loop used by the NSGA-II island keeps feasible points and honours the constraint."""
    from pymoo.algorithms.moo.nsga2 import NSGA2
    from pymoo.core.evaluator import Evaluator
    from pymoo.core.problem import Problem
    from pymoo.problems.static import StaticProblem
    prob = Problem(n_var=4, n_obj=2, n_ieq_constr=1, xl=np.zeros(4), xu=np.ones(4))
    alg = NSGA2(pop_size=40)
    alg.setup(prob, termination=("n_gen", 10 ** 9), seed=3, verbose=False)
    for _ in range(40):
        pop = alg.ask()
        X = pop.get("X")
        F = np.column_stack([X[:, 0], 1 - X[:, 0] + X[:, 1:].sum(axis=1)])
        G = (0.3 - X[:, 0])[:, None]                             # feasible only when x0 >= 0.3
        Evaluator().eval(StaticProblem(prob, F=F, G=G), pop)
        alg.tell(infills=pop)
    X = alg.opt.get("X")
    assert len(X) > 5 and np.all(X[:, 0] >= 0.3 - 1e-12)
