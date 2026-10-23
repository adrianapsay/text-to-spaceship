"""pytopo3d SIMP entrant (t2s.gd.entrants.pytopo3d_simp) on the h = 2 mm box-part domain."""
import warnings

import numpy as np
import pytest
from scipy import ndimage

from t2s.gd.domain import DesignDomain, box_part_domain
from t2s.gd.entrants import pytopo3d_simp as P


@pytest.fixture(scope="module")
def dom():
    return box_part_domain(h=2.0)


@pytest.fixture(scope="module")
def res(dom):
    return P.generate(dom, budget_s=60.0, threads=2)


def test_density_shape_range_and_passives(dom, res):
    rho = res.density
    assert res.generator == P.NAME == "pytopo3d SIMP"
    assert rho.shape == dom.shape and rho.dtype.kind == "f" and np.isfinite(rho).all()
    assert rho.min() >= 0.0 and rho.max() <= 1.0
    assert (rho[dom.void] == 0.0).all()
    assert (rho[dom.fixed] == 1.0).all() and (rho[dom.contact] == 1.0).all()


def test_design_volume_fraction(dom, res):
    des = dom.design()
    # continuous: the OC constraint (held to its bisection tolerance), and the thresholded solid gd.evaluate builds
    assert abs(res.density[des].mean() - dom.vol_frac) < 0.03
    assert abs((res.density[des] >= 0.5).mean() - dom.vol_frac) < 0.03


def test_thresholded_solid_connects_fixed_to_contact(dom, res):
    lab, _ = ndimage.label(res.density >= 0.5, structure=ndimage.generate_binary_structure(3, 1))   # 6-connected
    both = (set(np.unique(lab[dom.fixed])) & set(np.unique(lab[dom.contact]))) - {0}
    assert both


def test_objective_decreased(res):
    h = np.asarray(res.history)
    assert res.iterations >= 10 and len(h) == res.iterations + 1      # one per iterate + the returned design
    assert np.isfinite(h).all() and h[-1] < 0.5 * h[0]
    assert h[-1] <= h[len(h) // 2] * 1.01


def test_axis_mapping_indices_supports_and_loads(dom):
    a = np.arange(np.prod(dom.shape)).reshape(dom.shape)
    p = P.to_p(a)
    i, j, k = 3, 7, 5
    assert p.shape == (dom.shape[1], dom.shape[0], dom.shape[2]) and p[j, i, k] == a[i, j, k]
    assert np.array_equal(P.from_p(p), a)

    prob, _ = P.problem_from_domain(dom)
    nely, nelx, nelz = prob.shape
    assert (nelx, nely, nelz) == dom.shape

    def node_xyz(dofs):                       # pytopo3d node id = iy + ix (nely+1) + iz (nelx+1)(nely+1)
        nid = np.unique(np.asarray(dofs) // 3)
        iz, rem = np.divmod(nid, (nelx + 1) * (nely + 1))
        ix, iy = np.divmod(rem, nely + 1)
        return dom.origin + np.stack([ix, iy, iz], 1) * dom.h

    def inside_voxels(xyz, mask):
        c = dom.centres()[mask]
        return np.all((xyz >= c.min(0) - dom.h / 2 - 1e-9) & (xyz <= c.max(0) + dom.h / 2 + 1e-9))

    # the wall is at x = 0 (fixed layer i = 0); the part side at x = 16..18 mm (contact layer i = 8)
    assert dom.fixed[0].all() and P.to_p(dom.fixed)[:, 0, :].all()
    clamped = node_xyz(prob.fixeddof0)
    assert inside_voxels(clamped, dom.fixed) and np.isclose(clamped[:, 0].min(), 0.0)
    for case, F in enumerate(prob.F):
        loaded = node_xyz(np.flatnonzero(F))
        assert inside_voxels(loaded, dom.contact)
        tot = np.array([F[c::3].sum() for c in range(3)]) * prob.scale     # DOF order (ux, uy, uz) = world x, y, z
        np.testing.assert_allclose(tot, dom.load_cases()[case]["contact_force_n"], atol=1e-9)


def _bar(axis: int, n_long: int = 16, n_cross: int = 3, h: float = 1.0) -> DesignDomain:
    shape = [n_cross] * 3
    shape[axis] = n_long
    shape = tuple(shape)
    fixed, contact = np.zeros(shape, bool), np.zeros(shape, bool)
    fixed[tuple(0 if a == axis else slice(None) for a in range(3))] = True
    contact[tuple(n_long - 1 if a == axis else slice(None) for a in range(3))] = True
    reserve = np.r_[np.zeros(3), np.array(shape) * h]
    return DesignDomain(f"bar {axis}", np.zeros(3), h, shape, np.zeros(shape, bool), fixed, contact, axis, True,
                        0.0, reserve, 0.1)


@pytest.mark.parametrize("axis", [0, 1, 2])
def test_axis_mapping_physics_slender_bar(axis):
    """A solid 16 x 3 x 3 bar along world `axis`, clamped at one end, loaded at the other: the load case along the
    bar is axial (stiff), the two others bend it (soft, and equal for the square section). A transposed axis map
    (or pytopo3d's pre-0.3.0 Fx/Fy swap) puts the stiff case on the wrong axis."""
    d = _bar(axis)
    prob, _ = P.problem_from_domain(d)
    _, _, _, cases = prob.evaluate(P.to_p(np.ones(d.shape)), 3.0)
    cases = np.asarray(cases)
    others = cases[[k for k in range(3) if k != axis]]
    assert np.argmin(cases) == axis and others.min() > 20 * cases[axis]
    np.testing.assert_allclose(others[0], others[1], rtol=1e-6)


def test_loop_reproduces_pytopo3d_top3d():
    """Without passive solid / void and with one load case, the entrant's loop is top3d()'s loop."""
    from pytopo3d.core.optimizer import top3d
    nelx, nely, nelz = 12, 6, 4
    shape = (nely, nelx, nelz)
    sup = np.zeros(shape, bool)
    sup[:, 0, :] = True
    ff = np.zeros(shape + (3,))
    ff[:, -1, 0, 2] = -1.0 / nely
    ff[:, -1, 0, 1] = 0.5 / nely
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        ref = top3d(nelx, nely, nelz, 0.3, 3.0, 1.5, 0.5, force_field=ff, support_mask=sup, tolx=0.01, maxloop=12)
    prob = P.Pytopo3dProblem(np.zeros(shape, bool), np.zeros(shape, bool), sup, [ff], 1.5, nu=0.3)
    out = P.run_oc(prob, 0.3, 3.0, 12, 0.01, final_eval=False)
    assert out["iterations"] == 12
    np.testing.assert_allclose(out["xPhys"], ref, rtol=0, atol=1e-9)


def test_deterministic_and_budget(dom):
    a = P.generate(dom, budget_s=60.0, max_iter=8)
    b = P.generate(dom, budget_s=60.0, max_iter=8)
    assert a.iterations == b.iterations == 8
    assert np.array_equal(a.density, b.density) and a.history == b.history
    budget = 3.0
    cap = P.iteration_cap(P.problem_from_domain(dom)[0].ndof, budget)
    assert 1 <= cap < 60
    g = P.generate(dom, budget_s=budget)
    assert g.iterations <= cap and g.seconds < budget + 3.0
    assert (g.density[dom.fixed] == 1.0).all() and (g.density[dom.void] == 0.0).all()
