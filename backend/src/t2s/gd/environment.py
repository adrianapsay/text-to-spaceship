"""Launch environments for the bracket check: sourced presets (random, quasi-static, sine, shock, design factors,
first-frequency guidance) and the spectrum arithmetic they need.

Presets (every value carries its source string; the PDFs were read for this module):

* `gevs` (default) — NASA GSFC-STD-7000B (GEVS), launch vehicle unknown. Random limit = component ACCEPTANCE level
  (Table 2.4-3, 10.0 Grms); qualification = acceptance + 3 dB (Table 2.2-2; Table 2.4-3 qualification column,
  14.1 Grms) enveloped with the minimum workmanship level (Table 2.4-4, 6.8 Grms; App. B: "the cubesat protoflight
  vibration environment should therefore be derived as the envelope of limit level + 3dB and minimum
  workmanship"). Quasi-static: GSFC mass acceleration curve. Sine: no generalized level (§2.4.3) — a flag when f1 is
  below 1.5 × the launch vehicle's upper sine frequency (App. B 2.4.3). Shock: no generalized level; LSP-REQ-317.01B
  Table 1 note 3 says when random covers it. Factors: Table 2.2-3 (metallic).
* `spacex` — SpaceX Rideshare Payload User's Guide v11, containerised CubeSat. Random limit = MPE (Table 4-6,
  5.57 Grms); qualification = MPE + 3 dB (Table 6-2, qualification unit; protoflight is tested at MPE).
  Quasi-static: the GSFC MAC (Table 4-1 / Figure 4-1 are CubeSat- and payload-level and "shall not be utilized for
  individual internal components"). Sine 5–100 Hz, 1.4 g axial / 1.5 g lateral (Table 4-2). Shock SRS (Table 4-5).
  Factors 1.10 / 1.25 (Table 5-1).
* `nanoracks` — NanoRacks CubeSat Deployer IDD NR-NRCSD-S0003, hard-mount test. Random qualification = the
  hard-mount test profile (Table 4.3.2.1-1, 9.47 Grms; it "envelopes the MEFL+3dB and a minimum workmanship level");
  limit = that profile − 3 dB (GEVS Table 2.2-3 note 5, ASSUMED derivation). Quasi-static: the larger of Table
  4.3.1-1 and the MAC. No sine; no shock test (§4.3.3). Factors: GEVS.

Design policy (plan, review item 2) — no double counting of margin:
  (a) the LIMIT level × the preset's factors (yield, ultimate) — the design rule;
  (b) the QUALIFICATION test level (limit + 3 dB) against yield with NO extra factor and against ultimate with 1.25.
  The quasi-static (MAC) and random checks stay separate load cases: never added.

The input acts at the bracket base and the chassis is rigid (ASSUMED, stated in the app).
"""
from __future__ import annotations

import itertools
import math
from dataclasses import dataclass

import numpy as np

G0 = 9806.65                       # mm/s²

GEVS = "GSFC-STD-7000B (GEVS, 2021-04-28)"
SPACEX = "SpaceX Rideshare Payload User's Guide v11"
NANORACKS = "NanoRacks CubeSat Deployer IDD NR-NRCSD-S0003"
LSP = "LSP-REQ-317.01B (NASA LSP CubeSat/dispenser requirements, 2014)"


# ================================================================================================== spectra
@dataclass(frozen=True)
class Spectrum:
    """Acceleration spectral density (g²/Hz) as breakpoints joined by straight lines on log-log axes — how the
    standards tabulate it (levels at breakpoints, constant dB/octave slopes between them). Zero outside the first and
    last breakpoint: the analysis integrates only over the defined band (the old code continued the GEVS curve at
    −6 dB/oct above 2 kHz, which is unconservative for stiff modes)."""
    points: tuple                       # ((f_hz, asd_g2_hz), ...), f increasing
    source: str
    grms_published: float | None = None

    @property
    def band(self) -> tuple[float, float]:
        return float(self.points[0][0]), float(self.points[-1][0])

    @property
    def breakpoints(self) -> np.ndarray:
        return np.array([p[0] for p in self.points], float)

    def asd(self, f) -> np.ndarray:
        """ASD at f (g²/Hz), 0 outside the band."""
        f = np.asarray(f, float)
        x, y = np.log(self.breakpoints), np.log(np.array([p[1] for p in self.points], float))
        out = np.exp(np.interp(np.log(np.clip(f, 1e-300, None)), x, y))
        return np.where((f >= self.band[0]) & (f <= self.band[1]), out, 0.0)

    def mean_square(self) -> float:
        """∫ ASD df over the band (g²), exact for power-law segments."""
        tot = 0.0
        for (f1, a1), (f2, a2) in itertools.pairwise(self.points):
            n = math.log(a2 / a1) / math.log(f2 / f1)
            tot += a1 * f1 * math.log(f2 / f1) if abs(n + 1.0) < 1e-12 else (a2 * f2 - a1 * f1) / (n + 1.0)
        return tot

    def grms(self) -> float:
        return math.sqrt(self.mean_square())

    def scaled_db(self, db: float, source: str) -> Spectrum:
        k = 10.0 ** (db / 10.0)
        return Spectrum(tuple((f, a * k) for f, a in self.points), source)

    def envelope(self, other: Spectrum, source: str, grms_published: float | None = None) -> Spectrum:
        """Point-wise maximum, exact: piecewise linear in log-log, so the breakpoints of the envelope are the union
        of both sets plus the crossings inside each interval. Outside a spectrum's band its level is 0."""
        lo, hi = min(self.band[0], other.band[0]), max(self.band[1], other.band[1])
        fs = sorted({float(f) for f in np.concatenate([self.breakpoints, other.breakpoints]) if lo <= f <= hi})
        pts = []
        for f1, f2 in itertools.pairwise(fs):
            pts.append(f1)
            a = [float(s.asd(f1 * (1 + 1e-12))) for s in (self, other)]
            b = [float(s.asd(f2 * (1 - 1e-12))) for s in (self, other)]
            if min(a + b) > 0 and (a[0] - a[1]) * (b[0] - b[1]) < 0:      # the lines cross inside (f1, f2)
                d1, d2 = math.log(a[0] / a[1]), math.log(b[0] / b[1])
                t = d1 / (d1 - d2)
                pts.append(math.exp(math.log(f1) + t * (math.log(f2) - math.log(f1))))
        pts.append(fs[-1])
        out = []
        for f in pts:
            out.append((f, max(float(self.asd(f)), float(other.asd(f)))))
        return Spectrum(tuple(out), source, grms_published)


# ================================================================================================== quasi-static
MAC_TABLE = ((1.0, 68.0), (5.0, 49.0), (10.0, 39.8), (200.0, 12.0))      # (kg, g)
MAC_SOURCE = ("GSFC mass acceleration curve, GDC-PYLD-REQ-0004 Table 2-1 (via docs/research/v2-bracket-loads-"
              "materials.md): ≤ 1 kg 68 g, 5 kg 49 g, 10 kg 39.8 g, 200 kg 12 g, each axis separately; log-log "
              "interpolation between the points (ASSUMED); the held part's mass (the bracket's own mass would lower "
              "the value: leaving it out is conservative)")


def mac_g(mass_kg: float) -> float:
    """Quasi-static limit load factor (g) of the GSFC MAC for a component mass, log-log between the table points,
    68 g at or below 1 kg, held at the last point above 200 kg."""
    m = float(mass_kg)
    if m <= MAC_TABLE[0][0]:
        return MAC_TABLE[0][1]
    if m >= MAC_TABLE[-1][0]:
        return MAC_TABLE[-1][1]
    x = np.log([p[0] for p in MAC_TABLE])
    y = np.log([p[1] for p in MAC_TABLE])
    return float(np.exp(np.interp(math.log(m), x, y)))


# ================================================================================================== presets
@dataclass(frozen=True)
class Factors:
    yield_: float
    ult: float
    source: str


@dataclass(frozen=True)
class Sine:
    """Sinusoidal base input (g, peak) over a band, the same level on every axis (the bracket's orientation in the
    launch vehicle is not tracked: the larger of axial and lateral, conservative)."""
    f_lo: float
    f_hi: float
    level_g: float
    source: str


@dataclass(frozen=True)
class Srs:
    """Shock response spectrum (g, Q = 10) as log-log breakpoints; below the first point the first segment's slope
    is continued, above the last point the level is held (ASSUMED)."""
    points: tuple                       # ((f_hz, g), ...)
    source: str

    def at(self, f) -> np.ndarray:
        f = np.asarray(f, float)
        x = np.log([p[0] for p in self.points])
        y = np.log([p[1] for p in self.points])
        lf = np.log(np.clip(f, 1e-300, None))
        out = np.exp(np.interp(lf, x, y))
        s0 = (y[1] - y[0]) / (x[1] - x[0])
        return np.where(lf < x[0], np.exp(y[0] + s0 * (lf - x[0])), out)

    def scaled_db(self, db: float) -> Srs:
        k = 10.0 ** (db / 20.0)                 # SRS is an amplitude: +6 dB = × 2
        return Srs(tuple((f, a * k) for f, a in self.points), self.source + f" + {db:g} dB")


@dataclass(frozen=True)
class Environment:
    id: str
    name: str
    random_limit: Spectrum
    random_qual: Spectrum
    static_source: str
    static_floor_g: float               # the preset's own quasi-static table (0: MAC only)
    factors: dict                       # case -> Factors: "static", "sine", "random", "shock"
    qual_factors: Factors               # check (b): the qualification test level
    q: float                            # amplification for random / SRS (ζ = 1/(2Q))
    q_source: str
    f1_guidance_hz: float
    f1_source: str
    sine: Sine | None = None
    sine_flag_hz: float | None = None   # flag (no analysis) when f1 is below this
    sine_note: str = ""
    shock: Srs | None = None
    shock_qual_db: float = 0.0          # qualification shock = MPE + this
    shock_note: str = ""
    notes: tuple = ()
    analysis_only: bool = False         # GEVS Table 2.2-3 note 3 no-test factors on static / sine
    response_of: str | None = None      # same spectra / sine / shock as this preset (only the factors differ)

    @property
    def zeta(self) -> float:
        return 1.0 / (2.0 * self.q)

    @property
    def response_id(self) -> str:
        """Key of the stored responses (presets that differ only in factors share them)."""
        return self.response_of or self.id

    def static_g(self, mass_kg: float) -> float:
        """Quasi-static limit load (g) for each axis separately: the MAC, or the preset's own table if larger."""
        return max(mac_g(mass_kg), self.static_floor_g)

    def summary(self) -> dict:
        """JSON view for records and the app."""
        def fac(f):
            return {"yield": f.yield_, "ultimate": f.ult, "source": f.source}
        return {"id": self.id, "name": self.name,
                "random_limit": {"points": [list(p) for p in self.random_limit.points],
                                 "grms": self.random_limit.grms(), "source": self.random_limit.source},
                "random_qual": {"points": [list(p) for p in self.random_qual.points],
                                "grms": self.random_qual.grms(), "source": self.random_qual.source},
                "static": self.static_source, "factors": {k: fac(v) for k, v in self.factors.items()},
                "qual_factors": fac(self.qual_factors), "q": self.q, "q_source": self.q_source,
                "f1_guidance_hz": self.f1_guidance_hz, "f1_source": self.f1_source,
                "sine": None if self.sine is None else {"f_lo": self.sine.f_lo, "f_hi": self.sine.f_hi,
                                                        "level_g": self.sine.level_g, "source": self.sine.source},
                "sine_flag_hz": self.sine_flag_hz, "sine_note": self.sine_note,
                "shock": None if self.shock is None else {"points": [list(p) for p in self.shock.points],
                                                          "source": self.shock.source,
                                                          "qual_db": self.shock_qual_db},
                "shock_note": self.shock_note, "notes": list(self.notes), "analysis_only": self.analysis_only,
                "static_floor_g": self.static_floor_g}


# ---------------------------------------------------------------------------------------------------- GEVS
GEVS_ACCEPTANCE = Spectrum(((20.0, 0.013), (50.0, 0.08), (800.0, 0.08), (2000.0, 0.013)),
                           f"{GEVS} Table 2.4-3, components ≤ 22.7 kg, acceptance: 0.013 g²/Hz at 20 Hz, +6 dB/oct, "
                           "0.08 g²/Hz 50–800 Hz, −6 dB/oct, 0.013 at 2000 Hz", 10.0)
GEVS_QUALIFICATION = Spectrum(((20.0, 0.026), (50.0, 0.16), (800.0, 0.16), (2000.0, 0.026)),
                              f"{GEVS} Table 2.4-3, components ≤ 22.7 kg, qualification (= acceptance + 3 dB, "
                              "Table 2.2-2): 0.026 g²/Hz at 20 Hz, +6 dB/oct, 0.16 g²/Hz 50–800 Hz, −6 dB/oct, 0.026 "
                              "at 2000 Hz", 14.1)
GEVS_WORKMANSHIP = Spectrum(((20.0, 0.01), (80.0, 0.04), (500.0, 0.04), (2000.0, 0.01)),
                            f"{GEVS} Table 2.4-4, minimum workmanship, ≤ 45.4 kg: 0.01 g²/Hz at 20 Hz, +3 dB/oct, "
                            "0.04 g²/Hz 80–500 Hz, −3 dB/oct, 0.01 at 2000 Hz", 6.8)
GEVS_FACTORS = {
    "static": Factors(1.25, 1.4, f"{GEVS} Table 2.2-3, metallic, static column (yield 1.25, ultimate 1.4)"),
    "sine": Factors(1.25, 1.4, f"{GEVS} Table 2.2-3, metallic, sine column (yield 1.25, ultimate 1.4)"),
    "random": Factors(1.6, 1.8, f"{GEVS} Table 2.2-3, metallic, random/acoustic column (yield 1.6, ultimate 1.8; "
                                "note 4: on the ≥ 3σ peak; note 5: assumes qualification at acceptance + 3 dB)"),
}
GEVS_ANALYSIS_ONLY = Factors(2.0, 2.6, f"{GEVS} Table 2.2-3 note 3: qualified by analysis only — yield 2.0, "
                                       "ultimate 2.6")
QUAL_FACTORS = Factors(1.0, 1.25, "ASSUMED project rule (plan, review item 2): the qualification test level must not "
                                  "yield (factor 1.0 — NASA-STD-5001B Table 1 note *: no detrimental yielding) and "
                                  "keeps an ultimate factor of 1.25 (the ultimate factor of SpaceX Rideshare v11 "
                                  "Table 5-1 and LSP-REQ-317.01B Table 2 structural test), not the limit-level factors "
                                  "on top of the +3 dB (that would count the margin twice)")
Q_DEFAULT = 10.0
Q_SOURCE = ("Q = 10 (ζ = 5 %): research note §1 (Rocket Lab PSC §10; GEVS Table 2.2-3 note 4); GEVS §2.4.3: "
            "typical assumed Q 10 to 20")
F1_GUIDANCE = 100.0
F1_SOURCE = (f"{GEVS} App. B (CubeSats): a test-verified model is usually needed only below 100 Hz; random vibration "
             "is the primary structural load above 100 Hz — guidance, adopted as this project's pass criterion "
             "(unchanged); CDS Rev 14.1 sets no frequency requirement")
SINE_UPPER_HZ = 100.0               # upper frequency of a launch vehicle's sine environment (ASSUMED, see below)


def _gevs(analysis_only: bool = False) -> Environment:
    qual = GEVS_QUALIFICATION.envelope(
        GEVS_WORKMANSHIP, f"envelope of {GEVS} Table 2.4-3 qualification (acceptance + 3 dB) and Table 2.4-4 "
                          "workmanship (App. B, CubeSats); workmanship lies below the qualification level at every "
                          "frequency for ≤ 22.7 kg components, so the envelope is the 14.1 Grms qualification level",
        14.1)
    fac = dict(GEVS_FACTORS)
    if analysis_only:
        fac["static"] = fac["sine"] = GEVS_ANALYSIS_ONLY
    return Environment(
        "gevs" + ("_analysis" if analysis_only else ""),
        "GEVS (GSFC-STD-7000B), qualification check" + (", analysis only" if analysis_only else ""),
        GEVS_ACCEPTANCE, qual, MAC_SOURCE, 0.0, fac, QUAL_FACTORS, Q_DEFAULT, Q_SOURCE, F1_GUIDANCE, F1_SOURCE,
        sine=None, sine_flag_hz=1.5 * SINE_UPPER_HZ,
        sine_note=(f"{GEVS} §2.4.3: no generalized sine levels (mission-specific); App. B 2.4.3: a sine test is needed "
                   "only if the resonance is below 1.5 × the upper frequency of the launch vehicle's sine environment; "
                   f"{SINE_UPPER_HZ:.0f} Hz ASSUMED for that upper frequency (e.g. {SPACEX} Table 4-2: 5–100 Hz) — "
                   "a flag, not analysed"),
        shock=None,
        shock_note=(f"{GEVS} §2.4.4: no generalized shock level (from the launch vehicle / dispenser ICD). {LSP} Table 1 "
                    "note 3: a shock test is not required when the qualification random spectrum's equivalent SRS "
                    "(3σ, Q = 10) exceeds the qualification shock SRS below 2000 Hz — the record lists that random-"
                    "equivalent SRS to compare with the launch vehicle's shock spec"),
        notes=("the input acts at the bracket base; the chassis is rigid (ASSUMED)",
               "random fatigue is flagged, not analysed"),
        analysis_only=analysis_only, response_of="gevs" if analysis_only else None)


# ---------------------------------------------------------------------------------------------------- SpaceX
SPACEX_MPE = Spectrum(((20.0, 0.01), (50.0, 0.015), (700.0, 0.015), (800.0, 0.03), (925.0, 0.03),
                       (2000.0, 0.00644)),
                      f"{SPACEX} Table 4-6, random vibration MPE (P95/50), all axes: 20 Hz 0.01, 50–700 Hz 0.015, "
                      "800–925 Hz 0.03, 2000 Hz 0.00644 g²/Hz", 5.57)
SPACEX_FACTORS = Factors(1.10, 1.25, f"{SPACEX} Table 5-1: yield (flight, ground) 1.10, ultimate (flight) 1.25")


def _spacex() -> Environment:
    return Environment(
        "spacex", "SpaceX Rideshare v11 (containerised CubeSat)",
        SPACEX_MPE,
        SPACEX_MPE.scaled_db(3.0, f"{SPACEX} Table 6-2 (containerised CubeSat), qualification unit: MPE + 3 dB, 2 min "
                                  "per axis (protoflight and acceptance: MPE, 1 min)"),
        MAC_SOURCE + f"; {SPACEX} Table 4-1 / Figure 4-1 are CubeSat- and payload-level loads that \"shall not be "
                     "utilized for individual internal components\"", 0.0,
        {k: SPACEX_FACTORS for k in ("static", "sine", "random", "shock")}, QUAL_FACTORS, Q_DEFAULT,
        Q_SOURCE + f"; {SPACEX} §4.1.1 allows payload Q between 10 and 50 (Q = 50 would raise random responses by up "
                   "to √5)",
        40.0, f"{SPACEX} §4.1.1: no elastic natural frequency below 40 Hz (requirement); the project's 100 Hz rule "
              "still applies",
        sine=Sine(5.0, 100.0, 1.5, f"{SPACEX} Table 4-2, sine MPE 5–100 Hz: 1.4 g axial, 1.5 g lateral (1.5 g on "
                                   "every axis, orientation not tracked); Table 6-2: no sine test for containerised "
                                   "CubeSats"),
        shock=Srs(((100.0, 30.0), (1000.0, 1000.0), (10000.0, 1000.0)),
                  f"{SPACEX} Table 4-5, shock SRS MPE (Q = 10) at the payload mechanical interface: 100 Hz 30 g, "
                  "1000 Hz 1000 g, 10 kHz 1000 g"),
        shock_qual_db=6.0,
        shock_note=(f"{SPACEX} Table 6-2: shock test advised, qualification MPE + 6 dB (protoflight + 3 dB). The SRS "
                    "applies at the payload interface and is applied here at the bracket base with no attenuation — "
                    "an ESTIMATE (modal SRS × participation, CQC), reported, not a pass criterion"),
        notes=("the input acts at the bracket base; the chassis is rigid (ASSUMED)",
               "random fatigue is flagged, not analysed"))


# ---------------------------------------------------------------------------------------------------- NanoRacks
NANORACKS_HARD_MOUNT = Spectrum(((20.0, 0.057), (153.0, 0.057), (190.0, 0.099), (250.0, 0.099), (750.0, 0.055),
                                 (2000.0, 0.018)),
                                f"{NANORACKS} Table 4.3.2.1-1, hard-mount test profile (60 s per axis; it envelopes "
                                "the MEFL + 3 dB and a minimum workmanship level): 20–153 Hz 0.057, 190–250 Hz 0.099, "
                                "750 Hz 0.055, 2000 Hz 0.018 g²/Hz", 9.47)
NANORACKS_STATIC_G = 7.0


def _nanoracks() -> Environment:
    return Environment(
        "nanoracks", "NanoRacks NRCSD (hard-mount test profile)",
        NANORACKS_HARD_MOUNT.scaled_db(-3.0, f"{NANORACKS} Table 4.3.2.1-1 hard-mount profile − 3 dB: the limit level "
                                             "for the factor check (GEVS Table 2.2-3 note 5: factors may be applied "
                                             "to the qualification level minus 3 dB; ASSUMED derivation)"),
        NANORACKS_HARD_MOUNT,
        (f"the larger of the MAC and {NANORACKS} Table 4.3.1-1 (Nx ±7.0, Ny ±4.0, Nz ±4.0 g at the item's CG, with "
         "±13.5 rad/s² about each axis; 7.0 g taken on every axis, orientation not tracked). FLAG: the table's note "
         "\"RSS of Ny and Nz is ±1.8 g\" is inconsistent with ±4.0 / ±4.0 g (RSS 5.66 g). " + MAC_SOURCE),
        NANORACKS_STATIC_G, dict(GEVS_FACTORS), QUAL_FACTORS, Q_DEFAULT, Q_SOURCE, F1_GUIDANCE, F1_SOURCE,
        sine=None, sine_flag_hz=None, sine_note=f"{NANORACKS} §4.3 defines no sine environment",
        shock=None, shock_note=f"{NANORACKS} §4.3.3: no shock test requirement for CubeSats launching inside the NRCSD",
        notes=("the input acts at the bracket base; the chassis is rigid (ASSUMED)",
               "the IDD gives no factors for CubeSat parts: GEVS Table 2.2-3 factors used (plan)",
               "random fatigue is flagged, not analysed"))


ENVIRONMENTS: dict[str, Environment] = {e.id: e for e in (_gevs(), _gevs(analysis_only=True), _spacex(), _nanoracks())}
DEFAULT = "gevs"


def get(env: str | Environment | None = None) -> Environment:
    if isinstance(env, Environment):
        return env
    k = env or DEFAULT
    if k not in ENVIRONMENTS:
        raise KeyError(f"unknown launch environment {k!r} (known: {', '.join(ENVIRONMENTS)})")
    return ENVIRONMENTS[k]


def random_equivalent_srs(spec: Spectrum, f_hz, q: float = Q_DEFAULT) -> np.ndarray:
    """3σ shock-response-equivalent of a random spectrum (g), Miles at each frequency: 3 √(π/2 · f · Q · ASD(f)) —
    LSP-REQ-317.01B Table 1 note 3 compares it with the qualification shock SRS below 2000 Hz."""
    f = np.asarray(f_hz, float)
    return 3.0 * np.sqrt(np.pi / 2.0 * f * q * spec.asd(f))


def shock_covered_by_random(env: Environment, f_hz=None) -> tuple[bool | None, str]:
    """LSP-REQ-317.01B Table 1 note 3 (part 1): shock is covered when the qualification random spectrum's 3σ
    equivalent SRS exceeds the qualification shock SRS at every frequency below 2000 Hz (checked from the shock
    spec's first breakpoint up). None when the preset has no shock spec."""
    if env.shock is None:
        return None, env.shock_note
    f0 = env.shock.points[0][0]
    f = np.geomspace(f0, 2000.0, 400) if f_hz is None else np.asarray(f_hz, float)
    rnd = random_equivalent_srs(env.random_qual, f, env.q)
    sh = env.shock.scaled_db(env.shock_qual_db).at(f)
    worst = int(np.argmin(rnd / sh))
    ok = bool(np.all(rnd >= sh))
    return ok, (f"{LSP} Table 1 note 3: the qualification random 3σ equivalent SRS is {rnd[worst]:.0f} g at "
                f"{f[worst]:.0f} Hz against a qualification shock SRS of {sh[worst]:.0f} g — "
                + ("shock covered by the random check" if ok else "NOT covered: shock estimated separately"))
