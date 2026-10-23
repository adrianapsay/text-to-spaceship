"""Contest entrant pyMOTO SIMP (t2s.gd.entrants.pymoto_simp) on the self-contained box-part domain (h = 2 mm)."""
import numpy as np
import pytest
from scipy import ndimage
from threadpoolctl import threadpool_limits

from t2s.gd.domain import box_part_domain
from t2s.gd.entrants import pymoto_simp as ps


@pytest.fixture(scope="module")
def run():
    dom = box_part_domain(h=2.0)
    return dom, ps.generate(dom, budget_s=45.0, threads=2)


def test_result_fields(run):
    dom, res = run
    assert res.generator == ps.NAME == "pyMOTO SIMP"
    assert res.density.shape == tuple(dom.shape) and res.density.dtype.kind == "f"
    assert np.isfinite(res.density).all() and res.density.min() >= 0.0 and res.density.max() <= 1.0
    assert res.iterations == len(res.history) > 0 and res.seconds > 0.0
    assert any("self-weight included" in n for n in res.notes)


def test_passives_exact(run):
    dom, res = run
    assert (res.density[dom.void] == 0.0).all()
    assert (res.density[dom.fixed] == 1.0).all()
    assert (res.density[dom.contact] == 1.0).all()


def test_volume_fraction(run):
    """The evaluator's view — share of design voxels with density ≥ 0.5 — is within 0.02 of vol_frac; the continuous
    mean of the design voxels (what MMA constrains) within 0.03 as a sanity check."""
    dom, res = run
    des = dom.design()
    assert abs(float((res.density[des] >= 0.5).mean()) - dom.vol_frac) <= 0.02
    assert abs(float(res.density[des].mean()) - dom.vol_frac) <= 0.03


def test_load_path_connected(run):
    """One 6-connected component of the thresholded solid touches both the clamped and the loaded voxels."""
    dom, res = run
    lab, _ = ndimage.label(res.density >= 0.5)          # default structure = face (6-) connectivity
    shared = (set(np.unique(lab[dom.fixed])) & set(np.unique(lab[dom.contact]))) - {0}
    assert shared


def test_objective_decreased(run):
    _, res = run
    assert res.history[-1] < 0.5 * res.history[0]


def test_sensitivities_match_finite_differences():
    """Adjoint gradient through filter, projection, SIMP (with its linear tail), self-weight load and the 3-RHS solve
    against central differences, on a tiny grid."""
    dom = box_part_domain(h=4.0)
    with threadpool_limits(limits=2):
        P = ps.build(dom)
        P.heaviside.beta = 4.0
        rng = np.random.default_rng(0)
        x0 = rng.random(P.x.state.size) ** 2

        def response(x):
            P.x.state = x.copy()
            P.fn.response()
            return np.array([float(P.compliance.state), float(P.volume.state)])

        grads = []
        for sig in (P.compliance, P.volume):
            response(x0)
            P.fn.reset()
            sig.sensitivity = 1.0
            P.fn.sensitivity()
            grads.append(P.x.sensitivity.copy())
            P.fn.reset()
        for i in rng.choice(x0.size, 8, replace=False):
            e = np.zeros_like(x0)
            e[i] = 1e-6
            fd = (response(x0 + e) - response(x0 - e)) / 2e-6
            for g, f in zip(grads, fd):
                assert abs(g[i] - f) <= 1e-5 * abs(f) + 1e-12


def test_deterministic():
    dom = box_part_domain(h=4.0)
    a = ps.generate(dom, budget_s=600.0, threads=2)
    b = ps.generate(dom, budget_s=600.0, threads=2)
    assert np.array_equal(a.density, b.density)
    assert a.history == b.history and a.iterations == b.iterations
