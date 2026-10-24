# V2 generative-design contest — metal 3D-printed brackets

Results of `scripts/gd_contest.py` (2026-10-23T11:39:53+00:00, status DONE). Every design is meshed (quadratic tetrahedra) and solved with **CalculiX 2.23 and NGSolve 6.2.2608** under the same loads; margins use the larger voxel-averaged stress and the lower first frequency of the two. Every saved design was re-checked on 2026-10-24T11:16:22+00:00 with `scripts/gd_reevaluate.py` (see *Re-check with the modal analysis*).

## Criteria (ASSUMED)

* launch environment: GEVS (GSFC-STD-7000B), qualification check — 10.0 Grms limit, 14.1 Grms qualification (envelope of GSFC-STD-7000B (GEVS, 2021-04-28) Table 2.4-3 qualification (acceptance + 3 dB) and Table 2.4-4 workmanship (App. B, CubeSats); workmanship lies below the qualification level at every frequency for ≤ 22.7 kg components, so the envelope is the 14.1 Grms qualification level)
* quasi-static: GSFC mass acceleration curve (68 g at ≤ 1 kg) in X, Y, Z separately — the part's inertia acting at its centre of mass (force + moment on the contact faces, RBE3-like) + the bracket's self-weight; factors yield 1.25, ultimate 1.4 (GSFC-STD-7000B (GEVS, 2021-04-28) Table 2.2-3, metallic, static column (yield 1.25, ultimate 1.4))
* natural modes by Rayleigh–Ritz on six static deflections (the three 68 g cases and three pure torques on the contact faces), consistent bracket mass, the part a rigid mass with its inertia at its centre of mass
* random vibration by modal superposition: full CQC modal covariance over the defined 20–2000 Hz band (Q = 10), RMS von Mises per voxel (Segalman 2000), 3σ; (a) limit level × yield 1.6, ultimate 1.8; (b) qualification level × yield 1.0, ultimate 1.25 — never added to the quasi-static case; Miles at the dominant mode reported as a cross-check
* bolts: M3 A2-70 at the corners of the bolted face (pattern ASSUMED), per-bolt tension and shear from the per-node support reactions, fitting factor 1.15, flange bearing and head pull-through in the bracket material
* material: AlSi10Mg L-PBF stress-relieved (ASSUMED), Fty 170 / Ftu 280 MPa, E = 65 GPa — vendor minimum / typical values, not design allowables (NASA-STD-6030 §6.3 requires a Material Usage Agreement)
* first frequency (the lowest mode of any kind, a twisting part included) ≥ 100 Hz (target 200 Hz; GSFC-STD-7000B (GEVS, 2021-04-28) App. B (CubeSats): a test-verified model is usually needed only below 100 Hz; random vibration is the primary structural load above 100 Hz — guidance, adopted as this project's pass criterion (unchanged); CDS Rev 14.1 sets no frequency requirement)
* stress for the margins: von Mises of the stress averaged over each design voxel (peak over the voxels, the cases and both solvers); raw nodal peaks sit at singular sharp corners and grow with mesh refinement, so they are reported, not used
* solid inside the reserved box, joined to the wall, with the whole contact layer joined to the wall

## Entrants

| Entrant | Source | Run |
|---|---|---|
| Rule-based shell + ribs (V1 baseline) | V1 rule (SDF shell + plate + ribs), this project | yes |
| pyMOTO SIMP | pyMOTO 2.0.1 (TU Delft), SIMP + MMA | yes |
| pytopo3d SIMP | pytopo3d 0.3.0, 3D SIMP | yes |
| BESO + CalculiX | BESO for CalculiX (calculix/beso) | yes |
| block | reference: whole reserved space solid | yes (reference, cannot win) |
| sheet | reference: 1.5 mm sheet Z-bracket | yes (reference, cannot win) |

## Problems

| Problem | Description | Part mass | Voxel grid |
|---|---|---|---|
| P1 flat box, 20 mm gap | 60 × 40 × 30 mm box, 0.35 kg, flat side 20 mm from the wall | 0.35 kg | 13 × 24 × 16 at 1.5 mm |
| P2 capsule tank, 12 mm gap | capsule tank 0.30 kg on its curved side, 12 mm gap, bracket wraps 8 mm | 0.30 kg | 13 × 24 × 48 at 1.5 mm |
| P3 spherical tank, 25 mm gap | spherical tank 0.40 kg, 25 mm gap, bracket wraps 10 mm | 0.40 kg | 23 × 32 × 32 at 1.5 mm |

## Results

### P1 flat box, 20 mm gap

| Generator | Vol. frac. | Mass | σ at 68 g (voxel avg) | raw nodal peak | governing load | MS yield | MS ult. | f1 (with part) | σ agreement | Time | Result |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Rule-based shell + ribs (V1 baseline) | — | 15.9 g | 41 MPa | 51 MPa | random limit, y (bolt tension yield) | +1.23 | +2.27 | 571 Hz (part moves along y) | 0.0007 % | 15 s | PASS |
| pyMOTO SIMP | 0.08 | 12.7 g | 39 MPa | 106 MPa | random limit, z (yield) | +1.14 | +2.14 | 613 Hz (part moves along z) | 0.0008 % | 29 s | PASS |
| pytopo3d SIMP | 0.05 | 11.6 g | 82 MPa | 194 MPa | random limit, y (yield) | +0.09 | +0.60 | 460 Hz (part moves along z) | 0.0007 % | 47 s | PASS |
| BESO + CalculiX | 0.08 | 12.7 g | 48 MPa | 155 MPa | random limit, z (yield) | +0.69 | +1.48 | 653 Hz (part moves along z) | 0.0008 % | 218 s | PASS |
| Machined block (reference) | — | 44.9 g | 4 MPa | 6 MPa | static, y (bolt tension yield) | +37.12 | +55.06 | 2167 Hz (part moves along z) | 0.0009 % | 95 s | PASS |
| Sheet Z-bracket (reference) | — | 13.0 g | 304 MPa | 378 MPa | static, y (yield) | -0.55 | -0.34 | 68 Hz (part moves along y) | 0.0007 % | 12 s | FAIL: MS yield -0.55 (static, y); MS ultimate -0.34 (static, y); f1 68 Hz < 100 |

### P2 capsule tank, 12 mm gap

| Generator | Vol. frac. | Mass | σ at 68 g (voxel avg) | raw nodal peak | governing load | MS yield | MS ult. | f1 (with part) | σ agreement | Time | Result |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Rule-based shell + ribs (V1 baseline) | — | 38.7 g | 13 MPa | 14 MPa | random limit, y (flange bearing yield) | +6.21 | +9.56 | 1272 Hz (part moves along y) | 0.0006 % | 56 s | PASS |
| pyMOTO SIMP | 0.03 | 29.5 g | 23 MPa | 29 MPa | random limit, y (yield) | +2.26 | +3.77 | 848 Hz (part moves along y) | 0.0008 % | 108 s | PASS |
| pytopo3d SIMP | 0.05 | 30.9 g | 22 MPa | 29 MPa | random limit, y (yield) | +2.54 | +4.18 | 1006 Hz (part moves along y) | 0.0009 % | 142 s | PASS |
| BESO + CalculiX | 0.03 | 29.3 g | 67 MPa | 76 MPa | random limit, y (yield) | +0.21 | +0.77 | 864 Hz (part moves along y) | 0.0007 % | 340 s | PASS |
| Machined block (reference) | — | 97.1 g | 1 MPa | 1 MPa | static, y (flange bearing yield) | +193.98 | +285.73 | 8169 Hz (part moves along y) | 0.0009 % | 219 s | PASS |
| Sheet Z-bracket (reference) | — | 35.4 g | 105 MPa | 118 MPa | static, y (yield) | +0.29 | +0.90 | 159 Hz (part moves along y) | 0.0007 % | 43 s | PASS |

### P3 spherical tank, 25 mm gap

| Generator | Vol. frac. | Mass | σ at 68 g (voxel avg) | raw nodal peak | governing load | MS yield | MS ult. | f1 (with part) | σ agreement | Time | Result |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Rule-based shell + ribs (V1 baseline) | — | 42.5 g | 49 MPa | 49 MPa | random limit, y (yield) | +0.89 | +1.77 | 570 Hz (part moves along y) | 0.0006 % | 65 s | PASS |
| pyMOTO SIMP | 0.08 | 35.2 g | 15 MPa | 23 MPa | random limit, y (bolt tension yield) | +4.80 | +7.50 | 1093 Hz (part moves along y) | 0.0007 % | 175 s | PASS |
| pytopo3d SIMP | 0.03 | 25.8 g | 52 MPa | 284 MPa | random limit, y (yield) | +0.50 | +1.20 | 345 Hz (part rotates about x) | 0.0010 % | 180 s | PASS |
| BESO + CalculiX | 0.03 | 30.5 g | 65 MPa | 94 MPa | random limit, z (yield) | +0.41 | +1.06 | 560 Hz (part moves along z) | 0.0007 % | 339 s | PASS |
| Machined block (reference) | — | 186.9 g | 1 MPa | 2 MPa | static, y (bolt tension yield) | +109.17 | +161.01 | 4588 Hz (part moves along z) | 0.0009 % | 1135 s | PASS |
| Sheet Z-bracket (reference) | — | 34.5 g | 233 MPa | 402 MPa | static, z (yield) | -0.42 | -0.14 | 70 Hz (part moves along y) | 0.0008 % | 39 s | FAIL: MS yield -0.42 (static, z); MS ultimate -0.14 (static, z); f1 70 Hz < 100 |

## Weight vs strength: every rung of the volume-fraction ladder

Each optimiser was run from the lightest volume fraction up and stopped at the first design that passed.

**P1 flat box, 20 mm gap**

| Generator | Volume fraction → mass, σ (voxel avg), f1, result |
|---|---|
| pyMOTO SIMP | 0.03: generator failed: PardisoError · 0.05: generator failed: PardisoError · 0.08: 12.7 g, 39 MPa, 613 Hz, PASS |
| pytopo3d SIMP | 0.03: 10.8 g, 273 MPa, 215 Hz, fail · 0.05: 11.6 g, 82 MPa, 460 Hz, PASS |
| BESO + CalculiX | 0.03: 11.0 g, 254 MPa, 189 Hz, fail · 0.05: 11.6 g, 110 MPa, 418 Hz, fail · 0.08: 12.7 g, 48 MPa, 653 Hz, PASS |

**P2 capsule tank, 12 mm gap**

| Generator | Volume fraction → mass, σ (voxel avg), f1, result |
|---|---|
| pyMOTO SIMP | 0.03: 29.5 g, 23 MPa, 848 Hz, PASS |
| pytopo3d SIMP | 0.03: meshing failed: degenerate tetrahedra with every gmsh algorithm (best min quality 1.75e-06) · 0.05: 30.9 g, 22 MPa, 1006 Hz, PASS |
| BESO + CalculiX | 0.03: 29.3 g, 67 MPa, 864 Hz, PASS |

**P3 spherical tank, 25 mm gap**

| Generator | Volume fraction → mass, σ (voxel avg), f1, result |
|---|---|
| pyMOTO SIMP | 0.03: generator failed: PardisoError · 0.05: generator failed: PardisoError · 0.08: 35.2 g, 15 MPa, 1093 Hz, PASS |
| pytopo3d SIMP | 0.03: 25.8 g, 52 MPa, 345 Hz, PASS |
| BESO + CalculiX | 0.03: 30.5 g, 65 MPa, 560 Hz, PASS |

## Standings

| Rank | Generator | Passed | Total mass (failed problem = machined block) |
|---|---|---|---|
| 1 | pytopo3d SIMP | 3/3 | 68.3 g |
| 2 | BESO + CalculiX | 3/3 | 72.4 g |
| 3 | pyMOTO SIMP | 3/3 | 77.4 g |
| 4 | Rule-based shell + ribs (V1 baseline) | 3/3 | 97.1 g |

## Winner

**pytopo3d SIMP** — passed 3/3 problems with the lowest total mass (68.3 g; a failed problem counts as the machined block).

Mesh-refinement check of the winner's designs (surface triangles split in four, interior 0.75 h; about five times the nodes):

| Problem | σ voxel avg (base → fine) | raw nodal peak (base → fine) | f1 (base → fine) | Still passes |
|---|---|---|---|---|
| P1 flat box, 20 mm gap | 82 → 80 MPa (-1.9 %) | 194 → 334 MPa (+72.3 %) | 460 → 452 Hz (-1.6 %) | yes |
| P2 capsule tank, 12 mm gap | 22 → 23 MPa (+3.9 %) | 29 → 38 MPa (+28.5 %) | 1006 → 991 Hz (-1.5 %) | yes |
| P3 spherical tank, 25 mm gap | 52 → 57 MPa (+10.6 %) | 284 → 471 MPa (+65.6 %) | 345 → 340 Hz (-1.5 %) | yes |

## Re-check — GEVS (GSFC-STD-7000B), qualification check

WS3 re-check under the GEVS preset (gd.environment, the default): every saved design was evaluated again with scripts/gd_reevaluate.py (the same solids — every mass matched the recorded one). "Before" is the previous rule (Miles 3σ at the dominant mode or the SRSS of the modal base forces on the GEVS acceptance spectrum, continued at −6 dB/oct above 2 kHz; lumped bracket mass). "Now": random response by modal superposition (full CQC over the defined 20–2000 Hz band, RMS von Mises per voxel, 3σ) checked twice — (a) the acceptance (limit) level × 1.6 / 1.8 and (b) the qualification level (+3 dB, enveloped with workmanship) against yield × 1.0 and ultimate × 1.25 — and the 68 g MAC case × 1.25 / 1.4 separately; the consistent bracket mass in the Ritz modes; bolts (3 × M3 A2-70 at the corners of the bolted face, ASSUMED pattern; per-bolt forces from per-node reactions; fitting factor 1.15). The saved solids predate the bolt bosses: their flange is the 1.5 mm bolted layer. Because the GEVS qualification ASD is exactly twice the acceptance one, (b) gives √2 × the limit stress and (a) governs (1.6 > √2, 1.8 > 1.25 √2); "MS yield / MS ult." below are the bracket body's governing margins, "MS bolt" the bolted joint's.

| Design | f1 before → now (first mode now) | axis frequencies before → now | MS yield before → now | MS ult. before → now | MS bolt now | governing now | Result before → now |
|---|---|---|---|---|---|---|---|
| baseline_P1_vfNone.stl | 571 → 571 Hz (part moves along y) | 4422→4423 / 571→571 / 783→783 Hz | +1.20 → +1.23 | +2.22 → +2.27 | +0.98 | random limit, y (bolt tension yield) | PASS → PASS |
| baseline_P2_vfNone.stl | 1271 → 1272 Hz (part moves along y) | 6702→6711 / 1271→1272 / 4421→4422 Hz | +6.58 → +6.21 | +10.10 → +9.56 | +2.90 | random limit, y (flange bearing yield) | PASS → PASS |
| baseline_P3_vfNone.stl | 570 → 570 Hz (part moves along y) | 4207→4207 / 570→570 / 1303→1303 Hz | +0.85 → +0.89 | +1.72 → +1.77 | +1.22 | random limit, y (yield) | PASS → PASS |
| pymoto_P1_vf0.08.stl | 613 → 613 Hz (part moves along z) | 2798→2798 / 876→876 / 613→613 Hz | +1.23 → +1.14 | +2.27 → +2.14 | +1.54 | random limit, z (yield) | PASS → PASS |
| pymoto_P2_vf0.03.stl | 848 → 848 Hz (part moves along y) | 2999→3000 / 848→848 / 1461→1461 Hz | +2.34 → +2.26 | +3.88 → +3.77 | +2.65 | random limit, y (yield) | PASS → PASS |
| pymoto_P3_vf0.08.stl | 1093 → 1093 Hz (part moves along y) | 3562→3563 / 1093→1093 / 1095→1095 Hz | +5.08 → +4.80 | +7.90 → +7.50 | +1.56 | random limit, y (bolt tension yield) | PASS → PASS |
| pytopo3d_P1_vf0.03.stl | 215 → 215 Hz (part moves along z) | —→1007 / —→353 / —→215 Hz | — → -0.50 | — → -0.27 | +2.88 | static, z (yield) | fail → fail |
| pytopo3d_P1_vf0.05.stl | 460 → 460 Hz (part moves along z) | 1878→1878 / 615→615 / 460→460 Hz | +0.08 → +0.09 | +0.58 → +0.60 | +1.88 | random limit, y (yield) | PASS → PASS |
| pytopo3d_P2_vf0.05.stl | 1006 → 1006 Hz (part moves along y) | 2865→2866 / 1006→1006 / 1777→1777 Hz | +2.82 → +2.54 | +4.59 → +4.18 | +2.74 | random limit, y (yield) | PASS → PASS |
| pytopo3d_P3_vf0.03.stl | 345 → 345 Hz (part rotates about x) | 1456→1456 / 615→615 / 616→616 Hz | +0.67 → +0.50 | +1.44 → +1.20 | +1.89 | random limit, y (yield) | PASS → PASS |
| beso_P1_vf0.03.stl | 189 → 189 Hz (part moves along y) | —→1442 / —→189 / —→256 Hz | — → -0.47 | — → -0.23 | +1.78 | random limit, z (yield) | fail → fail |
| beso_P1_vf0.05.stl | 418 → 418 Hz (part moves along z) | —→2139 / —→418 / —→418 Hz | — → -0.01 | — → +0.45 | +2.43 | random limit, z (yield) | fail → fail |
| beso_P1_vf0.08.stl | 653 → 653 Hz (part moves along z) | 2993→2993 / 749→749 / 653→653 Hz | +0.74 → +0.69 | +1.55 → +1.48 | +1.74 | random limit, z (yield) | PASS → PASS |
| beso_P2_vf0.03.stl | 864 → 864 Hz (part moves along y) | 2099→2099 / 864→864 / 1150→1150 Hz | +0.18 → +0.21 | +0.72 → +0.77 | +1.84 | random limit, y (yield) | PASS → PASS |
| beso_P3_vf0.03.stl | 560 → 560 Hz (part moves along z) | 1396→1396 / 667→667 / 560→560 Hz | +0.39 → +0.41 | +1.04 → +1.06 | +2.13 | random limit, z (yield) | PASS → PASS |
| block_P1_vfNone.stl | 2167 → 2167 Hz (part moves along z) | 14304→14305 / 3066→3066 / 2167→2167 Hz | +34.04 → +37.12 | +50.30 → +55.06 | +2.34 | static, y (bolt tension yield) | PASS → PASS |
| block_P2_vfNone.stl | 8168 → 8169 Hz (part moves along y) | 30950→30957 / 8168→8169 / 12566→12568 Hz | +193.98 → +193.98 | +285.73 → +285.73 | +4.44 | static, y (flange bearing yield) | PASS → PASS |
| block_P3_vfNone.stl | 4588 → 4588 Hz (part moves along z) | 16522→16523 / 4595→4595 / 4588→4588 Hz | +109.17 → +109.17 | +161.01 → +161.01 | +2.33 | static, y (bolt tension yield) | PASS → PASS |
| sheet_P1_vfNone.stl | 68 → 68 Hz (part moves along y) | 1581→1581 / 68→68 / 175→175 Hz | -0.55 → -0.55 | -0.34 → -0.34 | +1.17 | static, y (yield) | fail → fail |
| sheet_P2_vfNone.stl | 159 → 159 Hz (part moves along y) | 1728→1728 / 159→159 / 385→385 Hz | +0.29 → +0.29 | +0.90 → +0.90 | +2.85 | static, y (yield) | PASS → PASS |
| sheet_P3_vfNone.stl | 70 → 70 Hz (part moves along y) | 937→937 / 70→70 / 128→128 Hz | -0.42 → -0.42 | -0.14 → -0.14 | +1.25 | static, z (yield) | fail → fail |

## Notes

* The two solvers solve the same discrete problem exactly, so their agreement verifies the implementations; mesh accuracy is checked by the refinement above and by the analytical benchmarks in the solver tests.
* Why the voxel average: a design made of voxels has sharp corners (the voxel staircase, the edge of the clamped face, the edge of the uniform load patch). Linear-elastic stress at a sharp re-entrant corner is singular, so the raw nodal peak grows each time the mesh is refined — in the refinement check above the raw peaks changed by +29 … +72 % while the voxel averages changed by -2 … +11 %. The voxel is the resolution of the design; fillets and local details belong to the detailed design, where the peak stresses must be checked again.
* Bolts: the bolted face is clamped in the FE model; each node's support reaction is given to the nearest bolt of the ASSUMED pattern (gd.bolts), which gives per-bolt tension and shear (fitting factor 1.15, M3 A2-70, flange bearing and head pull-through). Preload, prying and the part–bracket interface are not modelled. Nodes on the bolted face are excluded from the stress.
* Designs made before the bolt bosses existed (the saved contest STLs) are checked as they are: their flange is the 1.5 mm bolted layer, and the bearing and pull-through checks use that thickness.
* Generators get the same time budget per run; their own settings are in their module docstrings. The volume-fraction ladder stops at the first passing design, so the reported design is the lightest passing one on that ladder.
* Material values are typical datasheet values, not A/B-basis allowables; ASSUMED, not flight-qualified.
* Every design keeps the passive 1.5 mm bolted and contact layers, so the lightest possible design of a problem is never far below the mass of those layers.
* Generator failures are listed as they happened (e.g. a Pardiso zero-pivot in pyMOTO at the lowest volume fraction); a failed rung moves the entrant to the next one.
