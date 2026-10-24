"""Base-excitation response of bracket + part by modal superposition (replaces "Miles at one mode").

Notation (gd.evaluate.ritz): mass-normalised Ritz modes k with angular frequency ω_k, participation factor Γ_kj for
base excitation along axis j, and per mode the voxel stress tensors S⁽ᵏ⁾ = Σᵢ Cᵢₖ Sᵢ (Sᵢ: the voxel-averaged stress
of trial case i — stress is linear in the displacement, and mode k is Σᵢ Cᵢₖ × trial shape i). A base acceleration
a_b(t) along j drives the modal coordinates as q̈_k + 2ζω_k q̇_k + ω_k² q_k = −Γ_kj a_b, i.e.
q_k(ω) = −Γ_kj H_k(ω) a_b(ω), H_k = 1 / (ω_k² − ω² + 2iζω_kω), ζ = 1/(2Q).

Random (one-sided base ASD W(f), g²/Hz): the modal covariance
    I_kl = Γ_k Γ_l ∫ Re[H_k H_l*] W(f) df        (full CQC: the cross terms are kept)
is integrated over the spectrum's DEFINED band only (20–2000 Hz for the presets), on a log grid with Δf/f ≤ ζ/10
(composite Simpson in ln f, the spectrum's breakpoints on the grid). The voxel stress covariance is
C_v = Σ_kl S_v⁽ᵏ⁾ S_v⁽ˡ⁾ᵀ I_kl and the RMS von Mises stress follows exactly (Segalman, Fulcher, Reese, Field,
J. Sound Vib. 230(2), 2000): E[σ_vm²] = tr(A C_v), A the von Mises quadratic form (σ_vm² = σᵀAσ). The design value is
the 3σ peak. The same I_kl gives the part's pseudo-acceleration (Σ_k p_k ω_k² q_k, the equivalent quasi-static load
factor that Miles' equation estimates) and the bolt forces. Miles at the dominant mode is kept as a cross-check.

Sine (amplitude A in g over a band): q_k(f) = −Γ_kj H_k(f) A; the peak of the von Mises stress over a cycle of the
complex stress σ̂ = σ_r + iσ_i is √((a + b)/2 + √(((a − b)/2)² + c²)), a = σ_rᵀAσ_r, b = σ_iᵀAσ_i, c = σ_rᵀAσ_i,
maximised over the band (grid Δf/f ≤ ζ/10, modal frequencies inside the band added).

Shock (ESTIMATE): modal peaks q_k = Γ_kj SRS(f_k) / ω_k² (SRS in g, Q = 1/(2ζ)), combined over all modes by CQC on the
von Mises quadratic form: σ_vm,peak² ≈ Σ_kl ρ_kl q_k q_l S⁽ᵏ⁾ᵀ A S⁽ˡ⁾, ρ_kl Der Kiureghian's coefficient.

Units: mm, N, t, s, MPa; accelerations enter in g and are converted with G0.
"""
from __future__ import annotations

import itertools
import math

import numpy as np

from .environment import G0, Spectrum, Srs

VOIGT = ("xx", "yy", "zz", "xy", "yz", "zx")
# σ_vm² = σᵀ A σ for σ = (xx, yy, zz, xy, yz, zx)
VM_A = np.array([[1.0, -0.5, -0.5, 0, 0, 0], [-0.5, 1.0, -0.5, 0, 0, 0], [-0.5, -0.5, 1.0, 0, 0, 0],
                 [0, 0, 0, 3.0, 0, 0], [0, 0, 0, 0, 3.0, 0], [0, 0, 0, 0, 0, 3.0]])


def voigt(S: np.ndarray) -> np.ndarray:
    """(..., 3, 3) tensors → (..., 6) in VOIGT order (symmetric part)."""
    S = np.asarray(S, float)
    s = 0.5 * (S + np.swapaxes(S, -1, -2))
    return np.stack([s[..., 0, 0], s[..., 1, 1], s[..., 2, 2], s[..., 0, 1], s[..., 1, 2], s[..., 2, 0]], -1)


def von_mises_voigt(s: np.ndarray) -> np.ndarray:
    s = np.asarray(s, float)
    return np.sqrt(np.maximum(np.einsum("...a,ab,...b->...", s, VM_A, s), 0.0))


# ---------------------------------------------------------------------------------------------------- integration
def quad_grid(band: tuple[float, float], zeta: float, breakpoints=()) -> tuple[np.ndarray, np.ndarray]:
    """Nodes and weights for ∫ g(f) df over `band`: composite Simpson in ln f on segments split at the breakpoints
    inside the band, each with an even number of intervals of Δ ln f ≤ ln(1 + ζ/10) (so Δf/f ≤ ζ/10)."""
    lo, hi = float(band[0]), float(band[1])
    cuts = sorted({lo, hi, *[float(b) for b in breakpoints if lo < float(b) < hi]})
    step = math.log1p(zeta / 10.0)
    fs, ws = [], []
    for a, b in itertools.pairwise(cuts):
        n = max(2, math.ceil(math.log(b / a) / step))
        n += n % 2
        x = np.linspace(math.log(a), math.log(b), n + 1)
        w = np.ones(n + 1)
        w[1:-1:2], w[2:-1:2] = 4.0, 2.0
        f = np.exp(x)
        fs.append(f)
        ws.append(w * (x[1] - x[0]) / 3.0 * f)                 # df = f d(ln f)
    return np.concatenate(fs), np.concatenate(ws)


def transfer(f_hz: np.ndarray, f_k: np.ndarray, zeta: float) -> np.ndarray:
    """H_k(f) = 1 / (ω_k² − ω² + 2iζω_kω), shape (n_modes, n_f)."""
    w = 2.0 * np.pi * np.asarray(f_hz, float)[None, :]
    wk = 2.0 * np.pi * np.asarray(f_k, float)[:, None]
    return 1.0 / (wk ** 2 - w ** 2 + 2j * zeta * wk * w)


def spectrum_grid(spec: Spectrum, zeta: float, band=None):
    """(f, w·W(f)·G0²): quadrature nodes over the spectrum's band (or `band` ∩ it) with the ASD in (mm/s²)²/Hz."""
    lo, hi = spec.band if band is None else (max(band[0], spec.band[0]), min(band[1], spec.band[1]))
    f, w = quad_grid((lo, hi), zeta, spec.breakpoints)
    return f, w * spec.asd(f) * G0 ** 2


def modal_covariance(f_k, gamma, spec: Spectrum, zeta: float, band=None) -> np.ndarray:
    """I_kl = Γ_k Γ_l ∫ Re[H_k H_l*] W(f) df over the band, W in (mm/s²)²/Hz: the covariance of the modal
    coordinates q_k (units of q², here (mm·√t)²)."""
    f, ww = spectrum_grid(spec, zeta, band)
    H = transfer(f, f_k, zeta)
    g = np.asarray(gamma, float)
    I = np.real((H * ww[None, :]) @ np.conj(H).T)
    return g[:, None] * g[None, :] * I


def vm_rms(S_modal: np.ndarray, I: np.ndarray) -> np.ndarray:
    """RMS von Mises per voxel (Segalman 2000): √tr(A C_v), C_v = Σ_kl S⁽ᵏ⁾ S⁽ˡ⁾ᵀ I_kl. S_modal (n_v, 6, n_m)."""
    T = S_modal @ I                                            # (n_v, 6, n_m)
    return np.sqrt(np.maximum(np.einsum("vam,ab,vbm->v", T, VM_A, S_modal), 0.0))


def vector_cov(V_modal: np.ndarray, I: np.ndarray) -> np.ndarray:
    """Covariance (…, 3, 3) of vector responses Σ_k V⁽ᵏ⁾ q_k; V_modal (…, 3, n_m)."""
    return V_modal @ I @ np.swapaxes(V_modal, -1, -2)


def pseudo_accel(part_t: np.ndarray, omega: np.ndarray) -> np.ndarray:
    """(3, n_m): the part's pseudo-acceleration per unit modal coordinate, p_k ω_k² (mm/s² per q)."""
    return np.asarray(part_t, float).T * np.asarray(omega, float)[None, :] ** 2


def abs_accel_rms(part_t_d, gamma, f_k, spec: Spectrum, zeta: float, same_axis: bool, band=None) -> float:
    """RMS absolute acceleration (g) of the part along d for base excitation W along j:
    ∫ |δ_dj + Σ_k p_dk Γ_kj ω² H_k|² W df (δ_dj = 1 when d = j)."""
    f, ww = spectrum_grid(spec, zeta, band)
    H = transfer(f, f_k, zeta)
    w2 = (2.0 * np.pi * f) ** 2
    T = (1.0 if same_axis else 0.0) + (np.asarray(part_t_d, float) * np.asarray(gamma, float)) @ H * w2
    return float(np.sqrt(np.sum(ww * np.abs(T) ** 2)) / G0)


def miles_3sigma_g(f_hz: float, spec: Spectrum, q: float) -> float:
    """Miles' equation, 3σ (g): 3 √(π/2 · f · Q · W(f)), W = 0 outside the spectrum's band (cross-check only)."""
    return float(3.0 * np.sqrt(np.pi / 2.0 * f_hz * q * float(spec.asd(f_hz))))


# ---------------------------------------------------------------------------------------------------- sine
def sine_grid(f_lo: float, f_hi: float, zeta: float, f_k=()) -> np.ndarray:
    n = max(2, math.ceil(math.log(f_hi / f_lo) / math.log1p(zeta / 10.0)))
    f = np.geomspace(f_lo, f_hi, n + 1)
    extra = [x for x in np.asarray(f_k, float) if f_lo < x < f_hi]
    return np.unique(np.concatenate([f, extra]))


def _peak_vm(sr: np.ndarray, si: np.ndarray) -> np.ndarray:
    a = np.einsum("...a,ab,...b->...", sr, VM_A, sr)
    b = np.einsum("...a,ab,...b->...", si, VM_A, si)
    c = np.einsum("...a,ab,...b->...", sr, VM_A, si)
    return np.sqrt(np.maximum(0.5 * (a + b) + np.sqrt(0.25 * (a - b) ** 2 + c ** 2), 0.0))


def sine_response(S_modal, gamma, f_k, zeta: float, f_lo: float, f_hi: float, level_g: float,
                  part_t=None, axis: int | None = None, bolts_modal=None, chunk: int = 32) -> dict:
    """Peak response to a sine sweep of `level_g` (g, peak) over [f_lo, f_hi]: the largest voxel von Mises over the
    band (and where: voxel index, frequency), the part's absolute acceleration amplitude along the axis (g), and per
    bolt the largest force amplitude (N) of each component."""
    f = sine_grid(f_lo, f_hi, zeta, f_k)
    H = transfer(f, f_k, zeta)                                 # (n_m, n_f)
    Q = -(np.asarray(gamma, float)[:, None] * H) * level_g * G0   # modal amplitudes (n_m, n_f)
    best, at_v, at_f = -1.0, -1, float("nan")
    for s in range(0, len(f), chunk):
        q = Q[:, s:s + chunk]
        sig = np.einsum("vam,mf->vfa", S_modal, q)             # (n_v, n_f, 6) complex
        pk = _peak_vm(sig.real, sig.imag)
        v, j = np.unravel_index(int(np.argmax(pk)), pk.shape)
        if pk[v, j] > best:
            best, at_v, at_f = float(pk[v, j]), int(v), float(f[s + j])
    out = {"sigma_peak_mpa": best, "voxel": at_v, "f_hz": at_f, "f_lo": f_lo, "f_hi": f_hi, "level_g": level_g}
    if part_t is not None and axis is not None:
        w2 = (2.0 * np.pi * f) ** 2
        rel = (np.asarray(part_t, float)[:, axis][:, None] * Q).sum(0) * (-w2)   # q̈ = −ω² q
        out["part_accel_g"] = float(np.max(np.abs(level_g * G0 + rel)) / G0)
    if bolts_modal is not None and len(bolts_modal):
        amp = np.abs(np.einsum("bcm,mf->bcf", bolts_modal, Q))      # (n_b, 3, n_f)
        out["bolt_force_amp_n"] = amp.max(axis=2).tolist()
    return out


# ---------------------------------------------------------------------------------------------------- shock
def cqc_rho(f_k, zeta: float) -> np.ndarray:
    """Der Kiureghian (1981) modal correlation for equal damping: ρ_kl = 8ζ²(1 + r) r^1.5 / ((1 − r²)² +
    4ζ² r (1 + r)²), r = ω_l / ω_k (ρ_kk = 1)."""
    w = np.asarray(f_k, float)
    r = w[None, :] / w[:, None]
    return 8 * zeta ** 2 * (1 + r) * r ** 1.5 / ((1 - r ** 2) ** 2 + 4 * zeta ** 2 * r * (1 + r) ** 2)


def shock_modal_peaks(gamma, f_k, srs: Srs) -> np.ndarray:
    """Modal coordinate peaks q_k = Γ_k SRS(f_k) G0 / ω_k² (signed with Γ)."""
    w = 2.0 * np.pi * np.asarray(f_k, float)
    return np.asarray(gamma, float) * srs.at(f_k) * G0 / w ** 2


def shock_response(S_modal, gamma, f_k, zeta: float, srs: Srs, part_t=None, axis: int | None = None,
                   bolts_modal=None) -> dict:
    """ESTIMATE of the peak response to a shock SRS: modal peaks combined by CQC on the von Mises quadratic form
    (largest voxel), on the part's pseudo-acceleration along the axis and on each bolt force component."""
    q = shock_modal_peaks(gamma, f_k, srs)
    R = cqc_rho(f_k, zeta) * q[:, None] * q[None, :]           # "covariance" of the peaks
    vm = vm_rms(S_modal, R)
    v = int(np.argmax(vm))
    out = {"sigma_peak_mpa": float(vm[v]), "voxel": v, "estimate": True}
    if part_t is not None and axis is not None:
        w2 = (2.0 * np.pi * np.asarray(f_k, float)) ** 2
        p = np.asarray(part_t, float)[:, axis] * w2
        out["part_accel_g"] = float(np.sqrt(max(p @ R @ p, 0.0)) / G0)
    if bolts_modal is not None and len(bolts_modal):
        out["bolt_force_cov"] = vector_cov(bolts_modal, R)
    return out
