"""gd.sparse: the solvers used where Intel MKL (PARDISO) does not exist — CHOLMOD and NGSolve's sparse Cholesky —
agree with a reference direct solve on the optimiser's own stiffness matrices, keep their analysis across value
updates of one pattern, and are chosen as PARDISO's stand-ins."""
import numpy as np
import pytest
import scipy.sparse as sp
import scipy.sparse.linalg as sla

from t2s.gd import simp, sparse

KINDS = ["ngsolve"] + (["cholmod"] if sparse.cholmod_available() else [])


def _box(n: int = 8, x: float = 0.3):
    """The SIMP stiffness (upper triangle) and three load cases of an n³ voxel box clamped on one face."""
    shape = (n, n, n)
    active = np.ones(shape, bool)
    solid = np.zeros(shape, bool)
    solid[-1] = True
    fixed = np.zeros(shape, bool)
    fixed[0] = True
    forces = []
    for k in range(3):
        F = np.zeros(shape + (3,))
        F[-1, :, :, k] = -1.0
        forces.append(F)
    p = simp.framed_problem(np.ones(3), active, solid, fixed, forces, 0.33, 2.0, None)
    rng = np.random.default_rng(0)
    xs = [np.clip(x + 0.2 * rng.standard_normal(p.ne), 0.01, 1.0) for _ in range(2)]
    return p, [p.stiffness(p.filt(xi), 3.0) for xi in xs], np.stack(p.loads, axis=1)


def _reference(A_upper, B):
    full = (A_upper + sp.triu(A_upper, 1).T).tocsc()
    return sla.splu(full).solve(np.asarray(B, float))


def _make(kind: str, upper: bool):
    return sparse.CholmodCholesky(upper) if kind == "cholmod" else sparse.NgsCholesky(upper)


@pytest.mark.parametrize("kind", KINDS)
def test_the_cholesky_matches_a_reference_solve_and_refactorises(kind):
    _, (A1, A2), B = _box()
    c = _make(kind, upper=True)
    for A in (A1, A2):                                         # one pattern, two sets of values
        c.set(A)
        X = c.solve(B)
        ref = _reference(A, B)
        assert np.abs(X - ref).max() <= 1e-9 * np.abs(ref).max()
        x1 = c.solve(B[:, 0])                                  # one right-hand side: a vector back
        assert x1.shape == (B.shape[0],) and np.allclose(x1, X[:, 0], rtol=0, atol=1e-12 * np.abs(X).max())
    assert c.forecast_mb > 0
    c.free()


@pytest.mark.parametrize("kind", KINDS)
def test_the_whole_matrix_form_matches_the_upper_triangle_form(kind):
    _, (A, _), B = _box(6)
    full = (A + sp.triu(A, 1).T).tocsr()
    u, w = _make(kind, upper=True), _make(kind, upper=False)
    u.set(A)
    w.set(full)
    assert np.abs(u.solve(B) - w.solve(B)).max() <= 1e-10 * np.abs(u.solve(B)).max()


@pytest.mark.parametrize("kind", KINDS)
def test_spsolve_reuses_the_factorisation_for_the_same_matrix(kind, monkeypatch):
    monkeypatch.setenv("T2S_SPARSE_SOLVER", kind)
    _, (A, A2), B = _box(6)
    full, full2 = ((M + sp.triu(M, 1).T).tocsr() for M in (A, A2))
    f = sparse.Spsolve()
    calls = []
    real = f.chol.set
    monkeypatch.setattr(f.chol, "set", lambda M: (calls.append(1), real(M)))
    for j in range(3):                                         # the three load cases of one iteration
        assert np.allclose(f(full, B[:, j]), _reference(A, B[:, j]), rtol=1e-9, atol=0)
    assert len(calls) == 1
    f(full2, B[:, 0])                                          # the next iteration's matrix: refactorised
    assert len(calls) == 2


def test_the_backend_falls_back_when_pardiso_is_missing(monkeypatch):
    monkeypatch.delenv("T2S_SPARSE_SOLVER", raising=False)
    monkeypatch.setattr(sparse, "pardiso_available", lambda: False)
    monkeypatch.setattr(sparse, "cholmod_available", lambda: True)
    assert sparse.backend() == "cholmod"
    monkeypatch.setattr(sparse, "cholmod_available", lambda: False)
    assert sparse.backend() == "ngsolve" and sparse.speed_factor() > 1.0
    assert isinstance(simp.make_solver(), simp.CholeskySolver)
    monkeypatch.setattr(sparse, "pardiso_available", lambda: True)
    assert sparse.backend() == "pardiso" and sparse.speed_factor() == 1.0
    monkeypatch.setenv("T2S_SPARSE_SOLVER", "ngsolve")
    assert sparse.backend() == "ngsolve"                       # forced, to compare the solvers on one machine


@pytest.mark.skipif(not sparse.pardiso_available(), reason="Intel MKL (PARDISO) is not available on this machine")
@pytest.mark.parametrize("kind", KINDS)
def test_the_cholesky_matches_pardiso(kind):
    _, (A, _), B = _box()
    pa = simp.Pardiso()
    ref = pa.solve(A.copy(), B)
    pa.free()
    c = _make(kind, upper=True)
    c.set(A)
    assert np.abs(c.solve(B) - ref).max() <= 1e-9 * np.abs(ref).max()


def test_the_optimiser_runs_on_the_fallback_and_lowers_the_compliance(monkeypatch):
    monkeypatch.setenv("T2S_SPARSE_SOLVER", KINDS[-1])
    p, _, _ = _box(8, 0.3)
    r = simp.run_oc(p, 0.3, maxloop=8)
    assert r["iterations"] == 8 and r["history"][-1] < r["history"][0]
