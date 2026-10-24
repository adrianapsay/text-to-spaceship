"""V2 random / sine / shock response by modal superposition (t2s.gd.vibration), checked against closed forms and a
direct frequency-response solution:

* one mode on a flat spectrum: the pseudo-acceleration RMS equals Miles' √(π/2 f Q W) (the band is wide enough for
  the truncated tails to be < 1e-5); the absolute acceleration is larger by √(1 + 4ζ²);
* a stiff 20 kHz mode returns the input Grms (10.0 g acceptance, 14.1 g qualification), where Miles at the mode
  (the spectrum is 0 above 2 kHz) gives nothing;
* a 2-DOF chain with modal damping: the CQC covariance equals the direct frequency-response integral to 1e-6, for
  widely spaced and for close (ratio 1.02) modes; SRSS (cross terms dropped) differs in the close case;
* rotating the basis inside a degenerate pair of modes leaves the covariance and the RMS stress unchanged;
* von Mises of the covariance (Segalman): σxx = −σyy → √3 s; σxx in one mode and τxy in another → σxx² + 3τxy².
"""
import math

import numpy as np
import pytest

from t2s.gd import environment as env
from t2s.gd import vibration as vib

G0 = env.G0
Z = 0.05


def flat(lo, hi, w=0.04):
    return env.Spectrum(((lo, w), (hi, w)), "flat test spectrum")


def test_one_mode_matches_miles_pseudo_exact_absolute_by_1_plus_4_zeta_squared():
    fn = 300.0
    spec = flat(fn * 1e-4, fn * 1e3)
    I = vib.modal_covariance([fn], [1.0], spec, Z)
    pseudo = math.sqrt(I[0, 0]) * (2 * math.pi * fn) ** 2 / G0
    miles = math.sqrt(math.pi / 2 * fn * (1 / (2 * Z)) * 0.04)
    assert pseudo == pytest.approx(miles, rel=1e-5)
    ab = vib.abs_accel_rms([1.0], [1.0], [fn], spec, Z, True)
    assert ab == pytest.approx(miles * math.sqrt(1 + 4 * Z * Z), rel=1e-5)
    assert vib.miles_3sigma_g(fn, spec, 10.0) == pytest.approx(3 * miles)


@pytest.mark.parametrize("spec, grms", [(env.GEVS_ACCEPTANCE, 10.0), (env.GEVS_QUALIFICATION, 14.1)])
def test_a_stiff_mode_returns_the_input_grms(spec, grms):
    f = 20000.0
    I = vib.modal_covariance([f], [1.0], spec, Z)
    pseudo = math.sqrt(I[0, 0]) * (2 * math.pi * f) ** 2 / G0
    assert pseudo == pytest.approx(grms, rel=0.005)          # quasi-static: (f/f_k)² ≤ 1 % at the top of the band
    assert vib.abs_accel_rms([1.0], [1.0], [f], spec, Z, True) == pytest.approx(grms, rel=0.005)
    assert vib.miles_3sigma_g(f, spec, 10.0) == 0.0          # the old cross-check sees nothing above 2 kHz


def two_dof(mu, kappa):
    """Chain ground – m1 – m2 (m2 = μ m1, k2 = κ k1); returns (M, K, modes Φ mass-normalised, ω)."""
    from scipy.linalg import eigh
    m1, k1 = 1.0, 4.0e6
    M = np.diag([m1, mu * m1])
    K = np.array([[k1 + kappa * k1, -kappa * k1], [-kappa * k1, kappa * k1]])
    lam, Phi = eigh(K, M)
    return M, K, Phi, np.sqrt(lam)


@pytest.mark.parametrize("case", ["wide", "close"])
def test_two_dof_chain_cqc_equals_direct_frequency_response(case):
    """Base excitation of a 2-DOF chain, modal damping ζ on both modes: the response covariance of the relative
    displacements (and of a 'stress' σ = s·x) by CQC equals the integral of the direct frequency response
    (K − ω²M + iωC) X = −M r a over the same grid, to 1e-6. Wide: m2/m1 = 0.5, k2/k1 = 0.3 (ω2/ω1 ≈ 1.9).
    Close: a light second stage (m2/m1 = 1e-4) tuned to ω2/ω1 = 1.02 — there SRSS is wrong."""
    from scipy.optimize import brentq
    if case == "wide":
        mu, kappa = 0.5, 0.3
    else:
        mu = 1e-4
        lo = mu / (1 + mu)                                       # the tuning of the smallest frequency ratio

        def excess(k):
            w = two_dof(mu, k)[3]
            return w[1] / w[0] - 1.02
        kappa = brentq(excess, lo, 10 * lo)
    M, K, Phi, w = two_dof(mu, kappa)
    assert (w[1] / w[0] > 1.5) if case == "wide" else (w[1] / w[0] == pytest.approx(1.02))
    fk = w / (2 * math.pi)
    r = np.ones(2)
    gamma = Phi.T @ M @ r
    C = M @ Phi @ np.diag(2 * Z * w) @ Phi.T @ M                  # modal damping
    spec = flat(fk.min() / 50, fk.max() * 50, 0.02)
    f, ww = vib.spectrum_grid(spec, Z)
    s = np.array([3.0, -1.0])                                     # a linear "stress" read-out
    # modal CQC
    I = vib.modal_covariance(fk, gamma, spec, Z)
    cov_x = Phi @ I @ Phi.T
    var_s = s @ cov_x @ s
    # direct frequency response
    om = 2 * math.pi * f
    X = np.array([np.linalg.solve(K - o * o * M + 1j * o * C, -M @ r) for o in om])       # (n_f, 2)
    cov_d = np.real(np.einsum("fi,fj,f->ij", X, np.conj(X), ww))
    assert np.allclose(cov_x, cov_d, rtol=1e-6, atol=1e-6 * np.abs(cov_d).max())
    assert var_s == pytest.approx(float(s @ cov_d @ s), rel=1e-6)
    srss = s @ Phi @ np.diag(np.diag(I)) @ Phi.T @ s
    ratio = w[1] / w[0]
    if ratio < 1.05:
        assert abs(srss / var_s - 1) > 0.05, (ratio, srss, var_s)       # SRSS is wrong for close modes
    else:
        assert abs(srss / var_s - 1) < 0.05


def test_two_close_modes_on_separate_oscillators_cqc_vs_direct():
    """Two uncoupled oscillators read out by one combined quantity, ω2/ω1 = 1.02 exactly: CQC = direct to 1e-6;
    SRSS misses the strong correlation."""
    m = np.array([1.0, 1.0])
    w = 2 * math.pi * np.array([400.0, 408.0])
    M, K = np.diag(m), np.diag(m * w ** 2)
    Phi = np.diag(1 / np.sqrt(m))
    gamma = Phi.T @ M @ np.ones(2)
    C = M @ Phi @ np.diag(2 * Z * w) @ Phi.T @ M
    spec = flat(20.0, 20000.0)
    f, ww = vib.spectrum_grid(spec, Z)
    I = vib.modal_covariance(w / (2 * math.pi), gamma, spec, Z)
    s = np.array([1.0, 1.0])
    om = 2 * math.pi * f
    X = np.array([np.linalg.solve(K - o * o * M + 1j * o * C, -M @ np.ones(2)) for o in om])
    cov_d = np.real(np.einsum("fi,fj,f->ij", X, np.conj(X), ww))
    var = s @ Phi @ I @ Phi.T @ s
    assert var == pytest.approx(float(s @ cov_d @ s), rel=1e-6)
    srss = s @ Phi @ np.diag(np.diag(I)) @ Phi.T @ s
    assert srss / var < 0.8                                      # the cross term carries much of the response


def test_degenerate_pair_basis_rotation_leaves_the_result_unchanged():
    rng = np.random.default_rng(3)
    fk = np.array([350.0, 350.0, 900.0])
    gamma = np.array([0.4, -0.25, 0.1])
    S = rng.standard_normal((50, 6, 3))                          # voxel modal stress tensors
    spec = env.GEVS_QUALIFICATION
    I = vib.modal_covariance(fk, gamma, spec, Z)
    base = vib.vm_rms(S, I)
    for th in (0.3, 1.1, 2.5):
        R = np.eye(3)
        R[:2, :2] = [[math.cos(th), -math.sin(th)], [math.sin(th), math.cos(th)]]
        g2 = R @ gamma                                           # rotated pair: Γ' = Rᵀ… applied consistently
        S2 = S @ R.T                                             # S'(k) = Σ_l R_kl S(l)
        I2 = vib.modal_covariance(fk, g2, spec, Z)
        assert np.allclose(vib.vm_rms(S2, I2), base, rtol=1e-10)
    # SRSS would not be invariant
    srss = vib.vm_rms(S, np.diag(np.diag(I)))
    R = np.eye(3)
    R[:2, :2] = [[math.cos(0.7), -math.sin(0.7)], [math.sin(0.7), math.cos(0.7)]]
    I3 = vib.modal_covariance(fk, R @ gamma, spec, Z)
    assert not np.allclose(vib.vm_rms(S @ R.T, np.diag(np.diag(I3))), srss, rtol=1e-3)


def test_von_mises_of_the_covariance_special_cases():
    s = 7.0
    # one mode with σxx = s, σyy = −s (pure shear in principal axes): σ_vm = √3 s
    S = np.zeros((1, 6, 1))
    S[0, 0, 0], S[0, 1, 0] = s, -s
    I = np.array([[1.0]])
    assert vib.vm_rms(S, I)[0] == pytest.approx(math.sqrt(3) * s)
    assert vib.von_mises_voigt(S[0, :, 0]) == pytest.approx(math.sqrt(3) * s)
    # σxx in mode 1, τxy in mode 2, any correlation: σ_vm² = σxx² + 3 τxy²
    sx, txy = 5.0, 2.0
    S = np.zeros((1, 6, 2))
    S[0, 0, 0], S[0, 3, 1] = sx, txy
    for rho in (0.0, 0.6):
        I = np.array([[1.0, rho], [rho, 1.0]])
        assert vib.vm_rms(S, I)[0] ** 2 == pytest.approx(sx ** 2 + 3 * txy ** 2)


def test_sine_and_shock_responses_of_one_mode():
    """One mode at 300 Hz: a 1.5 g sine at 100 Hz gives the dynamic factor 1/(1 − (100/300)²) (ζ = 0.05: within
    0.1 %) on the static stress; the shock ESTIMATE of one mode is Γ SRS(f) / ω² on its stress."""
    fn = 300.0
    w = 2 * math.pi * fn
    S = np.zeros((1, 6, 1))
    S[0, 0, 0] = 2.0                                             # MPa per unit modal coordinate
    g = 0.7
    r = vib.sine_response(S, [g], [fn], Z, 5.0, 100.0, 1.5)
    static = 2.0 * g * 1.5 * G0 / w ** 2
    assert r["f_hz"] == pytest.approx(100.0) and r["sigma_peak_mpa"] == pytest.approx(
        static / abs(complex(1 - (100 / fn) ** 2, 2 * Z * 100 / fn)), rel=1e-9)
    srs = env.Srs(((100.0, 30.0), (1000.0, 1000.0), (10000.0, 1000.0)), "test")
    sh = vib.shock_response(S, [g], [fn], Z, srs)
    assert sh["sigma_peak_mpa"] == pytest.approx(2.0 * g * float(srs.at(fn)) * G0 / w ** 2) and sh["estimate"]
    assert vib.cqc_rho([fn, fn], Z) == pytest.approx(np.ones((2, 2)))
