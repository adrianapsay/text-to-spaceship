# WS3 — NASA launch environment and vibration analysis (notes)

Branch `ws3-launch-vibration`. Scope: `backend/src/t2s/gd/*`, `backend/src/t2s/fea/*`, `backend/scripts/gd_reevaluate.py`,
tests. Every number below is either read from the cited source or measured by code in this branch; anything else is
labelled ASSUMED.

## 1. Sources (checked in the cached PDFs)

| Value | Source (verified text) |
|---|---|
| Random, components ≤ 22.7 kg: qualification 0.026 g²/Hz at 20 Hz, +6 dB/oct, 0.16 g²/Hz 50–800 Hz, −6 dB/oct, 0.026 at 2000 Hz, 14.1 Grms; acceptance 0.013 / 0.08 / 0.013, 10.0 Grms | GSFC-STD-7000B Table 2.4-3 (p. 2.4-19) |
| Workmanship: 0.01 at 20 Hz, +3 dB/oct, 0.04 g²/Hz 80–500 Hz, −3 dB/oct, 0.01 at 2000 Hz, 6.8 Grms | GSFC-STD-7000B Table 2.4-4 (p. 2.4-20) |
| Random qualification = limit + 3 dB (prototype 2 min/axis, protoflight 1 min/axis), acceptance = limit; "test level ≥ workmanship"; sine 1.25 × limit; shock 1.4 × limit | GSFC-STD-7000B Table 2.2-2 (p. 2.2-5) |
| Metallic factors: static yield 1.25 / ult 1.4, sine 1.25 / 1.4, random 1.6 / 1.8; note 3 analysis only 2.0 / 2.6; note 4 on ≥ 3σ peaks; note 5 factors assume qualification at acceptance + 3 dB, else apply to qualification − 3 dB | GSFC-STD-7000B Table 2.2-3 (p. 2.2-6) |
| CubeSat protoflight random = envelope of limit + 3 dB and workmanship; sine test only if the resonance < 1.5 × the LV's upper sine frequency; test-verified model only needed below 100 Hz | GSFC-STD-7000B App. B (pp. B-3, B-4) |
| No generalized sine levels (mission-specific) | GSFC-STD-7000B §2.4.3 |
| Shock test not required if the qualification random spectrum's equivalent SRS (3σ, Q = 10) exceeds the qualification shock SRS below 2000 Hz | LSP-REQ-317.01B Table 1 note 3 |
| Random MPE 20 Hz 0.01, 50–700 Hz 0.015, 800–925 Hz 0.03, 2000 Hz 0.00644 g²/Hz, 5.57 Grms | SpaceX Rideshare v11 Table 4-6 |
| Containerised CubeSat: random qualification MPE + 3 dB (2 min/axis), protoflight and acceptance MPE; shock advised, qualification MPE + 6 dB; no quasi-static or sine test | SpaceX Rideshare v11 Table 6-2 |
| Sine MPE 5–100 Hz: 1.4 g axial, 1.5 g lateral | SpaceX Rideshare v11 Table 4-2 |
| Shock SRS MPE (Q = 10): 100 Hz 30 g, 1000 Hz 1000 g, 10 kHz 1000 g | SpaceX Rideshare v11 Table 4-5 |
| Yield 1.10, ultimate 1.25 | SpaceX Rideshare v11 Table 5-1 |
| Payload quasi-static factors are not for internal components; no elastic mode < 40 Hz; Q 10–50 | SpaceX Rideshare v11 §4.1.1, §4.1.2 |
| Hard-mount random test profile (envelopes MEFL + 3 dB and a minimum workmanship level): 20–153 Hz 0.057, 190–250 Hz 0.099, 750 Hz 0.055, 2000 Hz 0.018 g²/Hz, 9.47 Grms, 60 s/axis | NR-NRCSD-S0003 Table 4.3.2.1-1 |
| Quasi-static Nx ±7.0, Ny ±4.0, Nz ±4.0 g, ±13.5 rad/s²; note "RSS of Ny and Nz is ±1.8 g" (inconsistent: RSS of 4 and 4 is 5.66 g — flagged) | NR-NRCSD-S0003 Table 4.3.1-1 |
| No shock test for CubeSats inside the NRCSD | NR-NRCSD-S0003 §4.3.3 |
| Ti-6Al-4V heat treated: Rm min 930 MPa, Rp0.2 min 860 MPa, E typ. 110 ± 15 GPa, 4.41 g/cm³ (ASTM F1472 minima) | EOS Titanium Ti64 400W data sheet 07.2022 |
| Metallic design/test factors (prototype ult 1.4, yield 1.0*; protoflight ult 1.4, yield 1.25) | NASA-STD-5001B Table 1 |
| AM material use needs a Material Usage Agreement | NASA-STD-6030 §6.3 |
| GSFC MAC ≤ 1 kg 68 g, 5 kg 49 g, 10 kg 39.8 g, 200 kg 12 g; AlSi10Mg, 6061-T6, M3 A2-70, fitting factor 1.15 | docs/research/v2-bracket-loads-materials.md (not re-read from the originals here) |

Not found in any source: ν of Ti-6Al-4V (0.31) and 6061-T6 (0.33), the bolt pattern, boss size, flange formulas and
the relative cost of the alloys — all labelled ASSUMED in code.

## 2. Presets (`gd/environment.py`)

| | GEVS (default) | SpaceX Rideshare v11 | NanoRacks NRCSD |
|---|---|---|---|
| Random limit | acceptance, 10.0 Grms | MPE, 5.57 Grms | hard-mount profile − 3 dB (6.70 Grms; GEVS note 5, ASSUMED derivation) |
| Random qualification | acceptance + 3 dB enveloped with workmanship, 14.1 Grms | MPE + 3 dB, 7.87 Grms | hard-mount profile, 9.47 Grms |
| Quasi-static | MAC by the part's mass | MAC | max(MAC, 7.0 g) |
| Sine | flag: f1 < 150 Hz (1.5 × 100 Hz, the 100 Hz upper LV sine frequency ASSUMED) | 1.5 g, 5–100 Hz, analysed | none |
| Shock | none defined; the record lists the random-equivalent SRS (LSP note 3) | SRS analysed as an ESTIMATE (not covered by random) | none (§4.3.3) |
| Factors (limit) | 1.25/1.4 static & sine, 1.6/1.8 random | 1.10/1.25 | GEVS |
| f1 | 100 Hz (guidance, kept as the project's pass rule) | 40 Hz requirement + the 100 Hz rule | 100 Hz |

`gevs_analysis` is GEVS with the no-test static/sine factors 2.0/2.6 (Table 2.2-3 note 3); it shares GEVS's responses.
Measured Grms of the coded spectra: 9.995, 14.136, 6.784, 5.568, 9.470 (all within 0.2 % of the published values).

## 3. Design policy (no double counting)

Per axis, each a separate load case (never added):

* static — MAC × the preset's static factors (FE cases run at the 68 g reference, scaled);
* (a) random limit — the 3σ von Mises on the LIMIT spectrum × the random factors (GEVS 1.6 / 1.8);
* (b) random qualification — the 3σ on the QUALIFICATION spectrum against yield with factor **1.0** and ultimate with
  **1.25** (ASSUMED project rule: the test level must not yield, NASA-STD-5001B Table 1 note *; 1.25 is the ultimate
  factor of SpaceX Table 5-1 / LSP-REQ-317.01B Table 2). Stacking 1.6 / 1.8 on the +3 dB level would count the margin
  twice (GEVS Table 2.2-3 note 5);
* sine (SpaceX) × the preset's factors; shock (SpaceX) limit × factors and qualification × (1.0, 1.25), ESTIMATE, not
  gating (flagged when negative);
* bolts: the same cases on per-bolt forces with the fitting factor 1.15.

With the GEVS qualification spectrum exactly 2 × the acceptance ASD, (b) is √2 × the limit stress: (a) governs
(1.6 > 1.41 on yield, 1.8 > 1.77 on ultimate). Under SpaceX (1.10 / 1.25), (b) outranks (a) whenever random
governs. The governing case is the gating check with the smallest margin (body yield, body ultimate or a bolt check).

## 4. Random response (`gd/vibration.py`, `gd/evaluate.py`)

* Ritz modes (`evaluate.ritz`) return C (modes as combinations of the 6 trial shapes, Cᵀ M C = I), Γ = Cᵀ L
  (L = Φᵀ M r, the work of the solvers' own load vectors), ω, the part's CG motion per mode. The bracket mass is now the
  consistent tet10 mass (`fea.mesh.tet10_mass_gram`; before: an equal share per node), so L and K are consistent and
  the static limit is exact: Σ_k S⁽ᵏ⁾ Γ_kj / ω_k² = the 1 g field — measured 7e-13 relative on the bar test.
* Per solver, the voxel-averaged stress tensors of all six trial cases are kept; S⁽ᵏ⁾ = Σᵢ Cᵢₖ Sᵢ.
* I_kl = Γ_k Γ_l ∫ Re[H_k H_l*] W df over the defined band only (20–2000 Hz), log grid Δf/f ≤ ζ/10, Simpson in ln f,
  the spectrum's breakpoints on the grid; ζ = 1/(2Q), Q = 10. Full CQC (cross terms kept).
* C_v = Σ_kl S_v⁽ᵏ⁾ S_v⁽ˡ⁾ᵀ I_kl; σ_vm,rms² = tr(A C_v) (Segalman et al., J. Sound Vib. 230(2), 2000); design value 3σ,
  max over voxels, per axis.
* The same I_kl gives the part's 3σ pseudo-acceleration (Σ p_k ω_k² q_k — the quantity Miles estimates) and the bolt
  force covariances. Miles' 3σ at the dominant mode is kept as a cross-check field (it is 0 for a mode above 2 kHz,
  where the modal integral gives the input Grms).
* Flag when an axis's summed effective mass is < 0.9.
* Sine: modal frequency response over the band (grid Δf/f ≤ ζ/10 plus the modal frequencies), peak von Mises over a
  cycle of the complex stress. Shock: q_k = Γ_k SRS(f_k)/ω_k², CQC (Der Kiureghian ρ_kl) on the von Mises quadratic
  form, ESTIMATE. Random fatigue: flagged with the 1σ stress, not analysed.

## 5. Ritz dependent-shape cutoff — the planned raise to 1e-8 was tested and NOT adopted

Before, the cutoff (1e-10) acted on the unscaled Gram matrix, so it depended on the arbitrary size of the torque
cases. Now the trial shapes are scaled to unit modal mass first (scale-free; tested by scaling one shape × 1e6). With
a seventh, nearly dependent trial shape (68 g y case + a 0.6 N mid-span force; normalised eigenvalue 2.3e-10), the
direction carries a genuine second bending mode (970 Hz vs 1206 Hz from the six standard shapes). Rounding all
displacements to CalculiX's 7 significant digits changed the modes by < 1e-4 at 2.3e-10 and by ~1e-3 near 5e-12.
A cutoff of 1e-8 drops the genuine 970 Hz mode, so the cutoff stays at 1e-10 (on the scaled shapes) — see
`test_ritz_cutoff_is_scale_free_and_above_the_noise_floor`.

## 6. Bolts (`gd/bolts.py`, `fea/ccx.py`, `fea/ngs.py`, `fea/mesh.py`)

* Pattern (ASSUMED): the bracket's fastener count (default 3) at the corners of the bolted face, inset 2 d = 6 mm;
  3 bolts: two at one end of the longer side, one at the middle of the other end. Bosses: passive solid within 4 mm
  of each bolt through the first 2 mm (whole voxel layers). The optimisers now treat bosses as passive solid
  (`DesignDomain.passive_solid()`, small edits in the four entrants).
* Per-node reactions: CalculiX `*NODE PRINT, NSET=NFIX, TOTALS=YES` (every node's RF and the total); NGSolve: the
  tet10 element internal forces of its displacement (`mesh.tet10_internal_forces`, exact 4-point rule). Measured on the
  L-bracket test: the two agree node by node within 1e-4 of the largest, and each node's reaction (RF − external load
  there) sums to −applied.
* Per bolt: nodes go to the nearest bolt; tension = the part pulling the bracket off the wall (± for the static
  cases), shear = the in-plane part; random: 3σ of the normal component and √tr of the in-plane covariance.
* Capacities: M3 A2-70 tension yield 2.26 kN, ultimate 3.52 kN, shear 1.88 kN; flange bearing d·t·Fty|Ftu and head
  pull-through π·5.5 mm·t·F/√3 (ISO 4762 M3 head 5.5 mm; no bearing increase credited — ASSUMED conservative), t = the
  solid's thickness at the bolt, at most 2 mm. Fitting factor 1.15 on all.

## 7. Materials (`gd/materials.py`)

AlSi10Mg (2.68 g/cm³, 65 GPa, 170/280 MPa), Ti-6Al-4V (4.41, 110, 860/930), 6061-T6 (2.71, 68.3, 240/290), each with
its source and "vendor minimum / typical values, not design allowables (NASA-STD-6030 §6.3 …)". One table for the FE
check, the mass (`design.solid_props`; the 2670 vs 2680 kg/m³ mismatch is gone) and the cost (factor 1.0 for all:
no sourced price ratio). `design_bracket(..., material=..., environment=...)`; the design job reads optional
`environment` and `materials {pid: id}` from its snapshot. Cradles and clamp bands are checked as 6061-T6.

## 8. Contest re-check (measured; `data/gd_contest/results.json` → `reevaluation`, `docs/V2-GD-CONTEST.md`)

`scripts/gd_reevaluate.py --env gevs --src <main checkout>/data/gd_contest` (21 saved designs + the winner's three
refinement checks, every mass matched, CalculiX and NGSolve). Bracket body MS yield / ultimate, before (Miles/SRSS)
→ now (GEVS policy), and the bolted joint's MS:

| Design (the result of each entrant) | MS yield | MS ult. | MS bolt | governing now |
|---|---|---|---|---|
| pytopo3d P1 vf 0.05 (winner) | +0.08 → +0.09 | +0.58 → +0.60 | +1.88 | random limit, y, yield |
| pytopo3d P2 vf 0.05 (winner) | +2.82 → +2.54 | +4.59 → +4.18 | +2.74 | random limit, y, yield |
| pytopo3d P3 vf 0.03 (winner) | +0.67 → +0.50 | +1.44 → +1.20 | +1.89 | random limit, y, yield |
| BESO P1 0.08 / P2 0.03 / P3 0.03 | +0.74→+0.69 / +0.18→+0.21 / +0.39→+0.41 | +1.55→+1.48 / +0.72→+0.77 / +1.04→+1.06 | +1.74 / +1.84 / +2.13 | random limit |
| pyMOTO P1 0.08 / P2 0.03 / P3 0.08 | +1.23→+1.14 / +2.34→+2.26 / +5.08→+4.80 | +2.27→+2.14 / +3.88→+3.77 / +7.90→+7.50 | +1.54 / +2.65 / +1.56 | random limit (P3: bolt tension) |
| baseline P1 / P2 / P3 | +1.20→+1.23 / +6.58→+6.21 / +0.85→+0.89 | +2.22→+2.27 / +10.10→+9.56 / +1.72→+1.77 | +0.98 / +2.90 / +1.22 | P1: bolt tension yield (random limit, y) |

* Nothing that passed before fails now, and nothing that failed passes: the standings, masses and the winner
  (pytopo3d, 68.3 g, 3/3) are unchanged. The winner's refinement check (0.75 h) still passes: MS yield +0.10, +2.39,
  +0.63.
* The qualification check (b) never governs under GEVS (it gives √2 × the limit stress against factors 1.0 / 1.25,
  while (a) applies 1.6 / 1.8), so the expected √2 drop did not appear.
* Stiff axes: Miles at a dominant mode above 2 kHz gives 0 g (the spectrum ends there), the modal integral gives
  ≈ 27–33 g 3σ (≈ 3 × the 10.0 Grms input) — e.g. most designs' x axis.
* Effective mass < 0.9 flagged on 3 designs (baseline P2 x 0.848; block P2 x 0.889; block P3 x 0.884, y and z 0.899).
* Re-scored from the same FE results (no new runs), every design that passes under GEVS also passes under SpaceX
  (governed by the static MAC case × 1.10 / 1.25, except BESO P2: random qualification) and under NanoRacks. The
  SpaceX shock ESTIMATE MS yield is negative for every design except the machined blocks (limit −0.09 … −0.87,
  qualification + 6 dB −0.50 … −0.93) — reported and flagged, not a pass criterion (the interface SRS is applied at the
  bracket base without attenuation).
* The lightest rungs that failed before still fail (pytopo3d P1 0.03: −0.50, static z; BESO P1 0.03: −0.47 and 0.05:
  −0.01, random limit z).

## 9. Record fields for the app

Design records (`bracket_designs[pid]`) and contest rows keep `ms_yield`, `ms_ult`, `f1_hz`, `passed`, `modes`,
`axes`, `sigma_mpa` and add: `environment`, `environment_name`, `material`, `material_name`, `material_allowables`,
`margins` {case → worst axis: ms_yield, ms_ult (or ms, check, bolt for "bolt: …"), gates}, `checks` (per case and
axis, with factors and sources), `bolt_checks`, `governing` {case, axis, check, ms, part}, `ms_bolt`, `flags`
[{code: effective_mass | sine | shock | shock_estimate | fatigue | source | bolts, text}], `bolts` (positions), and
per axis in `axes`: `random_3sigma_g` (CQC), `random_qual_3sigma_g`, `random_miles_g`, `sigma3_limit_mpa`,
`sigma3_qual_mpa`, `eff_mass_sum`, `static_g`, `governs`.
