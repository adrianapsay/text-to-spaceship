# V2 research: bracket loads, materials and pass/fail criteria (3U CubeSat components, 0.02–0.4 kg)

Research agent report, 2026-10-22. Research only: nothing installed or run. Sources marked **UNVERIFIED** were seen
only in a search excerpt (ecss.nl was down, matweb refused, some pages were paywalled). Every value the app uses from
this note is labelled **ASSUMED** in the app.

## 1. Values adopted (ASSUMED)

### Loads and frequency

| Parameter | Adopted | Range / alternatives | Source |
|---|---|---|---|
| Quasi-static limit load, any component ≤ 1 kg, launch vehicle unknown | **68 g in each axis separately** | MAC table: 5 kg → 49 g, 10 kg → 39.8 g, 200 kg → 12 g | NASA GSFC [GDC-PYLD-REQ-0004 Table 2-1](https://soma.larc.nasa.gov/lws/pdf_files/3.06%20GDC-PYLD-REQ-0004%20Rev-.pdf); MAC definition in [JPL PD-ED-1211](https://extapps.ksc.nasa.gov/Reliability/Documents/Preferred_Practices/1211.pdf) |
| CubeSat-level loads (context only — not for internal parts) | — | SpaceX dispenser 10 g axial / 17 g lateral ("shall not be utilized for individual internal components"); J-SSOD 18.1 g (Cygnus), 8.67 g (Dragon), 8.34 g (HTV) | [SpaceX Rideshare PUG §4.1.2](https://storage.googleapis.com/rideshare-static/Rideshare_Payload_Users_Guide.pdf); [JAXA JX-ESPC-101133-C §2.4.1](https://iss.jaxa.jp/kibouser/library/item/jx-espc_8c_en.pdf) |
| Random input, launch vehicle unknown | **GEVS component spectrum.** Qual: 0.026 g²/Hz at 20 Hz, +6 dB/oct, 0.16 g²/Hz 50–800 Hz, −6 dB/oct, 0.026 at 2000 Hz = 14.1 grms. Acceptance: same shape at 0.08 = 10.0 grms | Workmanship 6.8 grms; SpaceX MPE 5.57 grms | [GSFC-STD-7000B Tables 2.4-3/2.4-4](https://standards.nasa.gov/sites/default/files/standards/GSFC/B/0/gsfc-std-7000b_signature_cycle_04_28_2021_fixed_links.pdf); CDS Rev 14.1 §3 allows GEVS when the LV is unknown |
| Random-derived equivalent load | Miles: g_rms = √(π/2·fn·Q·ASD(fn)), **Q = 10**, peak **3σ** | — | [Rocket Lab PSC 2002367F §10](https://www.rocketlabusa.com/assets/Uploads/PSC/Rocket%20Lab%20PSC%20-%202002367F%20Payload%20Spec%20for%203U%206U%2012U.pdf); GEVS Table 2.2-3 note 4 |
| Factors of safety, metallic, tested at CubeSat level | **Yield 1.25, ultimate 1.4** | SpaceX 1.10/1.25; LSP 1.1/1.25; ECSS 1.1/1.25 × KQ 1.25 (UNVERIFIED) | GEVS-B Table 2.2-3; [NASA-STD-5001B Table 1](https://standards.nasa.gov/sites/default/files/standards/NASA/B-w/CHANGE-3/3/2022-10-24-NASA-STD-5001B-w-Change-3-Approved.pdf) |
| Factors of safety, analysis only | **Yield 2.0, ultimate 2.6** | LSP 1.6/2.0 | GEVS-B Table 2.2-3 note 3; [LSP-REQ-317.01B Table 2](https://explorers.larc.nasa.gov/APMIDEX2016/MO/pdf_files/11_LSP-REQ-317_Rev_B_final.pdf) |
| Factors on random-derived 3σ loads | **Yield 1.6, ultimate 1.8** | — | GEVS-B Table 2.2-3 |
| Fitting factor (lugs, bearing, bolts) | **1.15** | — | [ECSS-E-HB-32-23A §5.5.2](https://escies.org/ftp/ecss.nl/Handbooks/ECSS-E-HB-32-23A(16April2010).pdf) |
| First natural frequency, bracket + component | **Pass ≥ 100 Hz; target ≥ 200 Hz** | J-SSOD CubeSat ≥ 100 Hz; SpaceX no modes < 40 Hz; SSTL AM bracket > 140 Hz × 1.3 | JAXA §2.1.9; LSP 6.3.15; [Orme et al. 2018](https://www.mdpi.com/2411-9660/2/4/51); 200 Hz octave rule UNVERIFIED |

### Materials (design values; "typical" datasheet values are not for design)

| Material | ρ (g/cm³) | E (GPa) | Fty (MPa) | Ftu (MPa) | Elong. | Notes / sources |
|---|---|---|---|---|---|---|
| **AlSi10Mg L-PBF, stress-relieved** | **2.68** | **70 nominal; 65 for frequency** (64–85) | **170** | **280** | **4 %** | Lowest Z-direction stress-relieved values of [Renishaw](https://www.renishaw.com/media/pdf/en/0c48b4800c17480393f17ceaacb4ecdb.pdf), [Gränges](https://granges.com/contentassets/4931f1a18787412b848327d26ec5334e/240606-gpm-alsi10mg.pdf), [EOS M290](https://www.eos.info/metal-solutions/data-sheets/aluminium/pds-eos-aluminium-alsi10mg-eos-m-290-30um), [AddUp](https://addupsolutions.com/wp-content/uploads/2023/10/AlSi10Mg-Material-Data-Sheet.pdf). Typical, not A/B-basis; no MMPDS allowable found. As-built-surface fatigue: use 50 MPa. |
| **6061-T6** (sheet / T651 plate) | **2.71** | **68.3** | **240** | **290** | 8–10 % | [ASTM B209M-14 Table 3](https://metalphoto.com/wp-content/uploads/2025/04/B209M-14-ASTM-Aluminum-Standards.pdf); MMPDS-04 3.6.2.0(b1) (bearing e/D = 2: Fbry ≈ 400, Fbru ≈ 607 MPa) |
| **5052-H32, 1.5 mm** | **2.68** | **70.3** | **160** | **215** | 7 % | ASTM B209M-14 Table 2 (EN 485-2 sheet: 130 MPa, UNVERIFIED) |
| **M3 8.8 steel** (A_s = 5.03 mm²) | — | — | proof **2920 N** | ult **4020 N** | — | EN ISO 898-1 (via Optimas) |
| **M3 A2-70** | 8.0 | 193–200 | **2.26 kN** | **3.52 kN**; shear ≈ **1.88 kN** | — | ECSS-E-HB-32-23A Table D-2 (S-basis); governs over 8.8 |

## 2. Load cases adopted

1. **LC1–LC3 (quasi-static):** 68 g = 666.9 m/s² body acceleration along +X, +Y, +Z separately (linear analysis:
   the opposite sign gives the same von Mises).
2. **Mass:** bracket self-weight from density; component as a mass at its CG tied to the mounting interface by a
   distributing (RBE3-like) link — an RBE2 is stiff and unconservative for frequency. Hand check:
   F = 68·g₀·(m_component + m_bracket + m_fasteners).
3. **Boundary conditions:** fixed at the fastener footprints; read stresses away from constraint singularities;
   holes, bearing and bolts by hand calculation.
4. **LC4–LC6 (random, recommended):** n₃σ = 3·√(π/2·f1·10·ASD_accept(f1)) on the GEVS acceptance spectrum
   (≈ 34 g at 100 Hz, 48 g at 200 Hz, 58 g at 300 Hz, 75 g at 500 Hz, 95 g at 800 Hz). Yield
   n_y = max(1.25 × 68, 1.6 × n₃σ), ultimate n_u = max(1.4 × 68, 1.8 × n₃σ). Quasi-static governs up to f1 ≈ 250 Hz.
5. **No-test variant:** 2.0 / 2.6 instead of 1.25 / 1.4.

## 3. Pass / fail (NASA-STD-5001B §3.2 with a fitting factor)

* MS_yield = Fty / (FoS_y · FF · σ_limit) − 1 ≥ 0
* MS_ult = Ftu / (FoS_u · FF · σ_limit) − 1 ≥ 0
* FF = 1.0 for the bracket body, 1.15 for holes, lugs and bolts. Bolts: factored tension and shear against the
  M3 A2-70 loads.
* Stiffness: modal analysis with the component mass and E = 65 GPa for AlSi10Mg; pass f1 ≥ 100 Hz, target ≥ 200 Hz.

## 4. AM design rules (L-PBF AlSi10Mg)

| Rule | Value | Source |
|---|---|---|
| Minimum wall | 1 mm (standard), **2 mm recommended for structural walls** | [Materialise](https://www.materialise.com/en/academy/industrial/design-am/aluminum) |
| Minimum feature | 0.76 mm | [Protolabs DMLS guide](https://www.protolabs.com/media/bn1dvyuy/pl_3dp_dmls_design_guide_en.pdf) |
| Overhang | ≥ 45° from the build plate self-supporting | Materialise; Protolabs |
| Bridges | ≤ 2 mm | Protolabs |
| Minimum hole | 2 mm (powder removal) | Materialise |
| Fillets | ≥ 3 mm radius | Materialise |
| Tolerance | ±0.2 mm up to 30 mm; machine interface bores | Materialise |

## 5. Published topology-optimised satellite brackets (context)

* Orme et al. 2018 (SSTL star-tracker bracket): Ti 425 g → AlSi10Mg 89 g (−79 %); 120 g per axis; f1 > 140 Hz × 1.3;
  AM factor 1.5 on a 190 MPa allowable; flying.
* Hümbert et al., IAC 2019 (DLR): −30 % mass, +43 % f1.
* RUAG Sentinel-1 antenna bracket: 1.6 → 0.94 kg (UNVERIFIED, vendor material).

## Caveats

* ECSS factor tables were not readable (site down); ECSS values UNVERIFIED.
* AlSi10Mg values are typical, not A/B-basis; flight use needs build witness coupons or the 1.5 AM factor.
* 68 g is a GSFC envelope from large-spacecraft practice; real component inputs inside a CubeSat may be lower.
