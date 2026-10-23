# V2 generative-design contest — metal 3D-printed brackets

Results of `scripts/gd_contest.py` (2026-10-23T11:39:53+00:00, status DONE). Every design is meshed (quadratic tetrahedra) and solved with **CalculiX 2.23 and NGSolve 6.2.2608** under the same loads; margins use the larger voxel-averaged stress and the lower first frequency of the two. Every saved design was re-checked on 2026-10-23T13:22:09+00:00 with `scripts/gd_reevaluate.py` (see *Re-check with the modal analysis*).

## Criteria (ASSUMED)

* 68 g quasi-static in X, Y, Z separately: the part's inertia acting at its centre of mass (force + moment on the contact faces, RBE3-like) + the bracket's self-weight
* natural modes by Rayleigh–Ritz on six static deflections (the three 68 g cases and three pure torques on the contact faces), the part a rigid mass with its inertia at its centre of mass
* random vibration: Miles 3σ load on the GEVS acceptance spectrum, Q = 10; per axis the larger of Miles at the mode with the largest effective mass along it and the SRSS of all modes' base forces
* design loads: yield max(1.25 × 68 g, 1.6 × 3σ), ultimate max(1.4 × 68 g, 1.8 × 3σ) on 170 / 280 MPa (AlSi10Mg L-PBF stress-relieved)
* first frequency (the lowest mode of any kind, a twisting part included) ≥ 100 Hz (target 200 Hz), E = 65 GPa
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
| Rule-based shell + ribs (V1 baseline) | — | 15.9 g | 41 MPa | 51 MPa | 68 g y, random (129 g) | +1.20 | +2.22 | 571 Hz (part moves along y) | 0.0007 % | 12 s | PASS |
| pyMOTO SIMP | 0.08 | 12.7 g | 39 MPa | 106 MPa | 68 g z, random (133 g) | +1.23 | +2.27 | 613 Hz (part moves along z) | 0.0008 % | 24 s | PASS |
| pytopo3d SIMP | 0.05 | 11.6 g | 82 MPa | 194 MPa | 68 g y, random (133 g) | +0.08 | +0.58 | 460 Hz (part moves along z) | 0.0007 % | 40 s | PASS |
| BESO + CalculiX | 0.08 | 12.7 g | 48 MPa | 155 MPa | 68 g y, random (147 g) | +0.74 | +1.55 | 653 Hz (part moves along z) | 0.0008 % | 213 s | PASS |
| Machined block (reference) | — | 44.9 g | 4 MPa | 6 MPa | 68 g z, random (92 g) | +34.04 | +50.30 | 2167 Hz (part moves along z) | 0.0009 % | 64 s | PASS |
| Sheet Z-bracket (reference) | — | 13.0 g | 304 MPa | 378 MPa | 68 g y, quasi-static (85 g) | -0.55 | -0.34 | 68 Hz (part moves along y) | 0.0007 % | 9 s | FAIL: MS yield -0.55; MS ultimate -0.34; f1 68 Hz < 100 |

### P2 capsule tank, 12 mm gap

| Generator | Vol. frac. | Mass | σ at 68 g (voxel avg) | raw nodal peak | governing load | MS yield | MS ult. | f1 (with part) | σ agreement | Time | Result |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Rule-based shell + ribs (V1 baseline) | — | 38.7 g | 13 MPa | 14 MPa | 68 g y, random (121 g) | +6.58 | +10.10 | 1271 Hz (part moves along y) | 0.0006 % | 46 s | PASS |
| pyMOTO SIMP | 0.03 | 29.5 g | 23 MPa | 29 MPa | 68 g y, random (148 g) | +2.34 | +3.88 | 848 Hz (part moves along y) | 0.0008 % | 97 s | PASS |
| pytopo3d SIMP | 0.05 | 30.9 g | 22 MPa | 29 MPa | 68 g y, random (136 g) | +2.82 | +4.59 | 1006 Hz (part moves along y) | 0.0009 % | 119 s | PASS |
| BESO + CalculiX | 0.03 | 29.3 g | 67 MPa | 76 MPa | 68 g y, random (146 g) | +0.18 | +0.72 | 864 Hz (part moves along y) | 0.0007 % | 324 s | PASS |
| Machined block (reference) | — | 97.1 g | 1 MPa | 1 MPa | 68 g y, quasi-static (85 g) | +193.98 | +285.73 | 8168 Hz (part moves along y) | 0.0009 % | 162 s | PASS |
| Sheet Z-bracket (reference) | — | 35.4 g | 105 MPa | 118 MPa | 68 g y, quasi-static (85 g) | +0.29 | +0.90 | 159 Hz (part moves along y) | 0.0007 % | 35 s | PASS |

### P3 spherical tank, 25 mm gap

| Generator | Vol. frac. | Mass | σ at 68 g (voxel avg) | raw nodal peak | governing load | MS yield | MS ult. | f1 (with part) | σ agreement | Time | Result |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Rule-based shell + ribs (V1 baseline) | — | 42.5 g | 49 MPa | 49 MPa | 68 g y, random (128 g) | +0.85 | +1.72 | 570 Hz (part moves along y) | 0.0006 % | 50 s | PASS |
| pyMOTO SIMP | 0.08 | 35.2 g | 15 MPa | 23 MPa | 68 g z, random (130 g) | +5.08 | +7.90 | 1093 Hz (part moves along y) | 0.0007 % | 164 s | PASS |
| pytopo3d SIMP | 0.03 | 25.8 g | 52 MPa | 284 MPa | 68 g z, random (134 g) | +0.67 | +1.44 | 345 Hz (part rotates about x) | 0.0010 % | 158 s | PASS |
| BESO + CalculiX | 0.03 | 30.5 g | 65 MPa | 94 MPa | 68 g z, random (127 g) | +0.39 | +1.04 | 560 Hz (part moves along z) | 0.0007 % | 319 s | PASS |
| Machined block (reference) | — | 186.9 g | 1 MPa | 2 MPa | 68 g y, quasi-static (85 g) | +109.17 | +161.01 | 4588 Hz (part moves along z) | 0.0009 % | 955 s | PASS |
| Sheet Z-bracket (reference) | — | 34.5 g | 233 MPa | 402 MPa | 68 g z, quasi-static (85 g) | -0.42 | -0.14 | 70 Hz (part moves along y) | 0.0008 % | 32 s | FAIL: MS yield -0.42; MS ultimate -0.14; f1 70 Hz < 100 |

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

## Re-check with the modal analysis

The first version took each axis's frequency from Rayleigh's quotient on that axis's static deflection alone. The independent verification found that this misses modes in which the part twists (P3: 332 Hz in the verifier's eigen solve, reported as 573 Hz). Every saved design was evaluated again (scripts/gd_reevaluate.py; the same solids — every mass matched the recorded one) with Rayleigh–Ritz on six deflections (the three 68 g cases and three torques) and an exact RBE3 fit of the part's motion. Each axis's random load is now the larger of Miles at its dominant mode and the SRSS of all modes' base forces. The axis frequencies below are those of the dominant modes ("—" for rungs whose per-axis values were not recorded).

| Design | f1 before → now (first mode now) | axis frequencies before → now | MS yield before → now | Result before → now |
|---|---|---|---|---|
| baseline_P1_vfNone.stl | 573 → 571 Hz (part moves along y) | 4418→4422 / 573→571 / 785→783 Hz | +1.20 → +1.20 | PASS → PASS |
| baseline_P2_vfNone.stl | 1275 → 1271 Hz (part moves along y) | 6699→6702 / 1275→1271 / 4567→4421 Hz | +6.59 → +6.58 | PASS → PASS |
| baseline_P3_vfNone.stl | 570 → 570 Hz (part moves along y) | 4206→4207 / 570→570 / 1310→1303 Hz | +0.85 → +0.85 | PASS → PASS |
| pymoto_P1_vf0.08.stl | 620 → 613 Hz (part moves along z) | 2799→2798 / 882→876 / 620→613 Hz | +1.22 → +1.23 | PASS → PASS |
| pymoto_P2_vf0.03.stl | 856 → 848 Hz (part moves along y) | 2981→2999 / 856→848 / 1477→1461 Hz | +2.35 → +2.34 | PASS → PASS |
| pymoto_P3_vf0.08.stl | 1106 → 1093 Hz (part moves along y) | 3562→3562 / 1106→1093 / 1106→1095 Hz | +5.11 → +5.08 | PASS → PASS |
| pytopo3d_P1_vf0.03.stl | 215 → 215 Hz (part moves along z) | —→1007 / —→353 / —→215 Hz | — → -0.50 | fail → fail |
| pytopo3d_P1_vf0.05.stl | 465 → 460 Hz (part moves along z) | 1878→1878 / 618→615 / 465→460 Hz | +0.08 → +0.08 | PASS → PASS |
| pytopo3d_P2_vf0.05.stl | 1013 → 1006 Hz (part moves along y) | 2865→2865 / 1013→1006 / 1802→1777 Hz | +2.83 → +2.82 | PASS → PASS |
| pytopo3d_P3_vf0.03.stl | 573 → 345 Hz (part rotates about x) | 1455→1456 / 573→615 / 573→616 Hz | +0.73 → +0.67 | PASS → PASS |
| beso_P1_vf0.03.stl | 190 → 189 Hz (part moves along y) | —→1442 / —→189 / —→256 Hz | — → -0.47 | fail → fail |
| beso_P1_vf0.05.stl | 444 → 418 Hz (part moves along z) | —→2139 / —→418 / —→418 Hz | — → -0.05 | fail → fail |
| beso_P1_vf0.08.stl | 665 → 653 Hz (part moves along z) | 2810→2993 / 738→749 / 665→653 Hz | +0.73 → +0.74 | PASS → PASS |
| beso_P2_vf0.03.stl | 880 → 864 Hz (part moves along y) | 1772→2099 / 880→864 / 1170→1150 Hz | +0.19 → +0.18 | PASS → PASS |
| beso_P3_vf0.03.stl | 596 → 560 Hz (part moves along z) | 1414→1396 / 615→667 / 596→560 Hz | +0.35 → +0.39 | PASS → PASS |
| block_P1_vfNone.stl | 2173 → 2167 Hz (part moves along z) | 14300→14304 / 3078→3066 / 2173→2167 Hz | +34.09 → +34.04 | PASS → PASS |
| block_P2_vfNone.stl | 8226 → 8168 Hz (part moves along y) | 30946→30950 / 8226→8168 / 12721→12566 Hz | +193.98 → +193.98 | PASS → PASS |
| block_P3_vfNone.stl | 4626 → 4588 Hz (part moves along z) | 16522→16522 / 4628→4595 / 4626→4588 Hz | +109.17 → +109.17 | PASS → PASS |
| sheet_P1_vfNone.stl | 68 → 68 Hz (part moves along y) | 69→1581 / 68→68 / 176→175 Hz | -0.55 → -0.55 | fail → fail |
| sheet_P2_vfNone.stl | 159 → 159 Hz (part moves along y) | 161→1728 / 159→159 / 395→385 Hz | +0.29 → +0.29 | PASS → PASS |
| sheet_P3_vfNone.stl | 71 → 70 Hz (part moves along y) | 72→937 / 71→70 / 129→128 Hz | -0.42 → -0.42 | fail → fail |

## Notes

* The two solvers solve the same discrete problem exactly, so their agreement verifies the implementations; mesh accuracy is checked by the refinement above and by the analytical benchmarks in the solver tests.
* Why the voxel average: a design made of voxels has sharp corners (the voxel staircase, the edge of the clamped face, the edge of the uniform load patch). Linear-elastic stress at a sharp re-entrant corner is singular, so the raw nodal peak grows each time the mesh is refined — in the refinement check above the raw peaks changed by +29 … +72 % while the voxel averages changed by -2 … +11 %. The voxel is the resolution of the design; fillets and local details belong to the detailed design, where the peak stresses must be checked again.
* Fasteners, bearing and the part–bracket interface are not modelled (hand calculations per the research note). Nodes on the bolted face are excluded.
* Generators get the same time budget per run; their own settings are in their module docstrings. The volume-fraction ladder stops at the first passing design, so the reported design is the lightest passing one on that ladder.
* Material values are typical datasheet values, not A/B-basis allowables; ASSUMED, not flight-qualified.
* Every design keeps the passive 1.5 mm bolted and contact layers, so the lightest possible design of a problem is never far below the mass of those layers.
* Generator failures are listed as they happened (e.g. a Pardiso zero-pivot in pyMOTO at the lowest volume fraction); a failed rung moves the entrant to the next one.
