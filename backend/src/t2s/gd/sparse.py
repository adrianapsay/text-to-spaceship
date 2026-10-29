"""The sparse symmetric positive definite solver behind the optimisers and the whole-satellite check.

* PARDISO (Intel MKL, through pypardiso) wherever MKL exists: Windows and x86-64 Linux. Its callers keep their own
  wrappers (gd.simp.Pardiso, gd.frame_eval.Factor, the entrants' pypardiso use), unchanged.
* Where it does not — macOS on Apple silicon has no MKL build, so pypardiso fails at import — a sparse Cholesky
  (cholesky()): CHOLMOD (SuiteSparse, through cvxopt: a dependency on macOS 15+) when installed, else NGSolve's (a
  dependency already; fea.ngs uses the same factorisation). Both keep the symbolic analysis while the matrix pattern
  stays the same and only refactorise the values, as PARDISO's phases 22 / 23 do.

  Measured on an M1 Pro (SIMP stiffness of a 24 × 24 × 24 voxel box, 46 875 unknowns, refactorisation + three
  right-hand sides): CHOLMOD 0.45 s, NGSolve 4.5 s; the PARDISO cost model the budgets are planned with
  (gd.simp.seconds_per_iteration) says 0.23 s. NGSolve's is a correct but ~10× slower fallback: with the same wall-clock
  budget the optimisers get fewer iterations (BACKEND_SPEED scales their cost models so the caps stay honest).

backend() picks one: T2S_SPARSE_SOLVER=pardiso|cholmod|ngsolve forces it (to compare them on one machine), otherwise
PARDISO when pypardiso imports, then CHOLMOD, then NGSolve. All three are direct solvers: their solutions agree to
round-off on a well-conditioned matrix (tests/test_sparse_backends.py); with SIMP's Emin = 1e-9 near-void voxels the
difference can grow to ~1e-6 of the displacement there, so optimised designs agree in compliance, not bit for bit.

Memory: PARDISO forecasts its own peak after its analysis phase; the others do not, so forecast_mb below is a model
of the factor's size in the number of unknowns (ASSUMED until measured on the Mac: PARDISO's forecasts on the 3U
frame grid, docs/V2.md — 585 MB at 136 k unknowns, 1257 MB at 207 k — as a power law).
"""
from __future__ import annotations

import contextlib
import functools
import os

import numpy as np

SOLVERS = ("pardiso", "cholmod", "ngsolve")
# seconds of an optimiser iteration relative to PARDISO's (the cost models' reference): measured, module docstring
BACKEND_SPEED = {"pardiso": 1.0, "cholmod": 2.0, "ngsolve": 20.0}
NGS_INVERSE = "sparsecholesky"
FORECAST_MB_AT = (136_000, 585.0)       # (unknowns, MB) — ASSUMED, see the module docstring
FORECAST_EXP = 1.82                     # growth with the unknowns: ln(1257 / 585) / ln(207 / 136)
TM_MIN_DOFS = 50_000                    # below this NGSolve factorises single-threaded (fea.ngs: faster there)


@functools.cache
def pardiso_available() -> bool:
    try:
        import pypardiso  # noqa: F401 — loads MKL (and fails without it)
        return True
    except Exception:  # noqa: BLE001 — ImportError, or OSError from a broken MKL
        return False


@functools.cache
def cholmod_available() -> bool:
    try:
        from cvxopt import cholmod  # noqa: F401
        return True
    except Exception:  # noqa: BLE001
        return False


def backend() -> str:
    """'pardiso', 'cholmod' or 'ngsolve' (module docstring)."""
    forced = os.environ.get("T2S_SPARSE_SOLVER", "").strip().lower()
    if forced in SOLVERS:
        return forced
    if pardiso_available():
        return "pardiso"
    return "cholmod" if cholmod_available() else "ngsolve"


def speed_factor() -> float:
    """The backend's iteration time relative to PARDISO's, for the optimisers' cost models."""
    return BACKEND_SPEED[backend()]


def forecast_mb(ndof: int) -> float:
    """Model of the factorisation's peak (MB) for `ndof` unknowns (module docstring)."""
    n0, mb0 = FORECAST_MB_AT
    return float(mb0 * (max(int(ndof), 1) / n0) ** FORECAST_EXP)


def cholesky(upper: bool = True, threads: int = 1):
    """The sparse Cholesky where PARDISO is not used: CHOLMOD, or NGSolve's (backend())."""
    return CholmodCholesky(upper) if backend() == "cholmod" else NgsCholesky(upper, threads)


def _sorted_csr(A):
    A = A.tocsr()
    if not A.has_sorted_indices:
        A.sort_indices()
    return A


class CholmodCholesky:
    """CHOLMOD's supernodal Cholesky (cvxopt) of a real symmetric positive definite matrix (scipy sparse): the upper
    triangle (`upper`, as PARDISO's mtype 2 takes it) or the whole matrix. set(A) loads a matrix — the symbolic
    analysis (AMD ordering) for a new pattern, then only the numeric factorisation — and solve(B) solves for one or
    several right-hand sides (columns of B)."""

    def __init__(self, upper: bool = True):
        self.upper = bool(upper)
        self.n = 0
        self.sym = None
        self._key = None
        self._lower = None          # the lower triangle's (rows, cols) and its entries' positions in A.data

    @property
    def name(self) -> str:
        import cvxopt
        return f"CHOLMOD (cvxopt {cvxopt.__version__})"

    def _pattern(self, A) -> None:
        coo = A.tocoo()
        pos = np.arange(A.nnz)
        keep = coo.row <= coo.col if self.upper else coo.row >= coo.col
        r, c, pos = coo.row[keep], coo.col[keep], pos[keep]
        if self.upper:                                  # CHOLMOD reads the lower triangle: the transpose
            r, c = c, r
        self._lower = (r.astype(int).tolist(), c.astype(int).tolist(), pos)
        self._key = (A.indptr.copy(), A.indices.copy())
        self.n, self.sym = A.shape[0], None

    def set(self, A) -> None:
        from cvxopt import cholmod, spmatrix
        A = _sorted_csr(A)
        if self._key is None or A.shape[0] != self.n or not (np.array_equal(A.indptr, self._key[0])
                                                             and np.array_equal(A.indices, self._key[1])):
            self._pattern(A)
        r, c, pos = self._lower
        K = spmatrix(A.data[pos].tolist(), r, c, (self.n, self.n))
        if self.sym is None:
            self.sym = cholmod.symbolic(K)
        cholmod.numeric(K, self.sym)

    def factorise(self) -> None:          # set() factorises
        pass

    def solve(self, B: np.ndarray) -> np.ndarray:
        from cvxopt import cholmod, matrix
        B = np.asarray(B, float)
        one = B.ndim == 1
        X = matrix(np.array(B[:, None] if one else B, dtype=float, order="F"))
        cholmod.solve(self.sym, X)
        X = np.array(X)
        return X[:, 0] if one else X

    @property
    def forecast_mb(self) -> float:
        return forecast_mb(self.n)

    def free(self) -> None:
        self.sym = self._lower = self._key = None


class NgsCholesky:
    """NGSolve's sparse Cholesky of a real symmetric positive definite matrix (scipy sparse): the upper triangle
    (`upper`, as PARDISO's mtype 2 takes it) or the whole matrix. set(A) loads a matrix — the first builds the
    pattern, later ones of the same pattern only their values — factorise() factorises (or refactorises), solve(B)
    solves for one or several right-hand sides (columns of B)."""

    def __init__(self, upper: bool = True, threads: int = 1):
        self.upper = bool(upper)
        self.threads = max(1, int(threads))
        self.mat = self.inv = None
        self.n = 0
        self._key = None            # (indptr, indices) of the loaded pattern
        self._take = None           # index into A.data of each of NGSolve's entries
        self._dirty = False

    @property
    def name(self) -> str:
        import ngsolve as ngs
        return f"NGSolve {ngs.__version__} {NGS_INVERSE}"

    def _tm(self):
        import ngsolve as ngs
        if self.threads > 1 and self.n >= TM_MIN_DOFS:
            ngs.SetNumThreads(self.threads)
            return ngs.TaskManager()
        return contextlib.nullcontext()

    def _build(self, A) -> None:
        import ngsolve as ngs
        import scipy.sparse as sp
        n = A.shape[0]
        pos = sp.csr_matrix((np.arange(1, A.nnz + 1, dtype=float), A.indices, A.indptr), shape=A.shape)
        full = (pos + sp.triu(pos, 1).T).tocoo() if self.upper else pos.tocoo()
        mat = ngs.la.SparseMatrixd.CreateFromCOO(full.row.astype(np.int64), full.col.astype(np.int64),
                                                 full.data, n, n)
        _, cols, ptr = mat.CSR()
        cols, ptr = np.asarray(cols, np.int64), np.asarray(ptr, np.int64)
        rows = np.repeat(np.arange(n, dtype=np.int64), np.diff(ptr))
        key = full.row.astype(np.int64) * n + full.col
        order = np.argsort(key)
        at = np.searchsorted(key[order], rows * n + cols)
        if len(cols) != full.nnz or not np.array_equal(key[order][at], rows * n + cols):
            raise RuntimeError("NGSolve's matrix pattern differs from the matrix given")
        self._take = full.data[order][at].astype(np.int64) - 1
        self.mat, self.inv, self.n = mat, None, n
        self._key = (A.indptr.copy(), A.indices.copy())

    def set(self, A) -> None:
        A = _sorted_csr(A)
        if self.mat is None or A.shape[0] != self.n or not (np.array_equal(A.indptr, self._key[0])
                                                            and np.array_equal(A.indices, self._key[1])):
            self._build(A)
        self.mat.AsVector().FV().NumPy()[:] = A.data[self._take]
        self._dirty = True

    def factorise(self) -> None:
        with self._tm():
            if self.inv is None:
                self.inv = self.mat.Inverse(inverse=NGS_INVERSE)
            else:
                self.inv.Update()
        self._dirty = False

    def solve(self, B: np.ndarray) -> np.ndarray:
        if self._dirty or self.inv is None:
            self.factorise()
        B = np.asarray(B, float)
        one = B.ndim == 1
        B2 = B[:, None] if one else B
        X = np.empty_like(B2)
        b, x = self.mat.CreateColVector(), self.mat.CreateColVector()
        bv, xv = b.FV().NumPy(), x.FV().NumPy()
        for j in range(B2.shape[1]):
            bv[:] = B2[:, j]
            x.data = self.inv * b
            X[:, j] = xv
        return X[:, 0] if one else X

    @property
    def forecast_mb(self) -> float:
        return forecast_mb(self.n)

    def free(self) -> None:
        self.mat = self.inv = None
        self._key = self._take = None


class Spsolve:
    """A solver_func for pytopo3d (x = f(A, b), A the whole matrix) on cholesky(): factorises when A's values change
    and reuses the factorisation while they do not — the three load cases of an iteration share one, as with
    pypardiso.spsolve."""

    def __init__(self, threads: int = 1):
        self.chol = cholesky(upper=False, threads=threads)
        self._data = None

    def __call__(self, A, b):
        A = _sorted_csr(A)
        if self._data is None or len(A.data) != len(self._data) or not np.array_equal(A.data, self._data):
            self.chol.set(A)
            self._data = A.data.copy()
        return self.chol.solve(b)
