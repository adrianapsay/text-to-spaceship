# V2 generative-design contest: independent structural check

Verifier note, 2026-10-23. Checked against `data/gd_contest/results.json` (run 2026-10-23T09:53:57Z) and
`docs/V2-GD-CONTEST.md`. I built a separate model for this check and did not use `t2s/fea/*` or `t2s/gd/evaluate.py`
for any number here. From `t2s` I only imported `t2s.gd.contest.problems(h=1.5)`, to get the part meshes, the voxel
grids, the wall plane and the app's passive masks. I wrote my own STL reader. Every number below comes from a script
I ran (listed at the end). Approximate values are labelled as such.

Designs checked: the winner, pytopo3d, on P1, P2 and P3, plus the P1 designs of the baseline, pyMOTO and BESO
(the STL file named in each results row).

## 1. Bottom line

1. **The mass is right.** Signed-tetrahedron volume × 2680 kg/m³ reproduces `mass_g` to all printed digits for all
   six designs. My voxelised masses are within −0.2 … +0.6 % at 0.375 mm.
2. **The app's FE is right for the problem as it is set up.** I loaded the same faces the app loads. My hex8 model
   then gives the app's f1 to within −2.7 … +9.8 % and its maximum displacements to within ±10 %; pytopo3d P3 is the
   exception at +14 … +25 % (a local effect on the curved shell). The reaction equals 68 g × (part + bracket)
   exactly. On P1 the FE bending moment at every slice equals the hand moment F·(x_load − x) to within 3.5 %.
3. **The stress numbers are credible under the app's own load model, roughly −30 … +20 %.** My 1.5 mm voxel
   averages come out *lower* than the app's on 5 of 6 designs (−13 … −31 %). pytopo3d P3 is the exception: mine is
   108 MPa against the app's 91 MPa (+19 %), so MS yield is about +0.25, not +0.49. With 0.75 mm averaging it is
   123 MPa, MS yield +0.10. One caveat: averaging the stress tensor over a 1.5 mm voxel removes the bending stress in
   members only one or two voxels thick. I demonstrated this (§3.2): for a member one voxel deep, the voxel average
   is 4 % of the surface bending stress. The margins are therefore resolution-limited, not peak-stress margins. The
   contest notes say this too.
4. **The main problem is the load model.** The app applies the part's 68 g inertia as a uniform traction on the
   contact faces, and its modal mass is smeared on the same faces. That leaves out the part's centre of mass, which
   sits 22–31 mm beyond the contact faces (§7). The project's own research note
   (`docs/research/v2-bracket-loads-materials.md` §2.2) prescribes the part as a mass at its CG, tied to the
   interface by an RBE3-type link. I ran that model (B), and as a cross-check a rigid part (C, RBE2):
   * f1 falls by 1.8–4.4×: pytopo3d P1 695 → 160 Hz, BESO P1 728 → 167 Hz. All six still clear 100 Hz; two miss the
     200 Hz target.
   * The 1.5 mm voxel-average stress rises to 1.5–6.6× the app's reported σ.
   * The yield margin goes **negative for 4 of the 6 designs**: pytopo3d P1 −0.14, pytopo3d P3 −0.46, pyMOTO P1
     −0.29, BESO P1 −0.57. Only pytopo3d P2 (+1.03) and the baseline P1 (+1.43) still pass.
   * The rigid-part model C gives the same verdict (pytopo3d P3 is borderline in C at −0.03).

   If each part really hangs on one bracket, as P1–P3 are posed, the reported margins and f1 are optimistic by these
   factors and the contest outcome (pass/fail and probably the ranking) is not reliable.
5. **pytopo3d P2 does not contain the passive contact layer it is credited with.** 556 of the 1312 contact voxels are
   missing from the reported STL: all of the 8 mm wrap, x 14.25–18.75 mm, 5.03 g. On a curved part the contact layer
   is two 6-connected pieces (one 26-connected piece). pytopo3d did not join the wrap piece to the structure, so the
   app's island filter (`solid_from_density`, 6-connectivity) dropped it without a message. The other entrants'
   designs keep it. This breaks the contest note "every design keeps the passive 1.5 mm bolted and contact layers",
   and it accounts for most of pytopo3d's mass lead on P2: 18.8 g, against BESO 23.5 g and pyMOTO 24.0 g. In every
   P3 design except the block, a 68-voxel (0.62 g) disc of contact layer in front of the sphere's pole is also
   missing, for the same reason.
6. **One load case from the research note is not applied:** the random-vibration loads (LC4–6). At the app's own f1
   the note's Miles 3σ factor would govern the yield load, by 1.28–1.71× over 1.25 × 68 g (arithmetic only, §9). At
   the model-B frequencies it mostly does not.

Units, signs and load directions are consistent: −x, −y and −z at 68 g on both the part and the bracket, in mm, N,
MPa, t and s. The bolted face is all-DOF fixed in both models.

## 2. Method (independent model)

* **Geometry.** I read the binary STL with my own reader, computed the signed volume, and voxelised it at 0.75 mm
  and 0.375 mm (½ and ¼ of the design voxel, on the same origin). A voxel is solid when the winding number of its
  centre, from +z ray crossings with signed triangle normals, is non-zero. Ray positions are jittered by about 1e-6 mm
  to avoid edge hits. No winding number had |w| > 1, and every design was a single island.
* **Elements.** Trilinear 8-node hexahedra with full 2×2×2 Gauss integration. E 65 GPa, ν 0.33, ρ 2680 kg/m³. Lumped
  mass: ⅛ of each element's mass per node. The global matrix is assembled in COO form, the fixed DOFs are eliminated,
  and the solve is MKL Pardiso SPD (mtype 2, upper triangle, 2 threads). The modes use scipy `eigsh` in shift-invert
  mode around 0, with Pardiso as OPinv.
* **Supports.** All DOFs are fixed on the nodes of the wall plane (x = 0, within half a voxel).
* **Contact zone (my definition).** Solid voxels whose centroid lies within 2.0 mm of the part surface. Distances are
  measured to dense surface samples (≤ 0.1 mm spacing). In P1 this is exactly the 1.5 mm contact plate,
  x 18–19.5 mm. The nodes of these voxels are the contact nodes.
* **Part-load models.** Self-weight at 68 g is applied in every model.

| Model | Part force | Part mass (modal) |
|---|---|---|
| **A** (as specified for this check) | equal nodal forces on all contact nodes | lumped equally on the contact nodes |
| **A'** (the app's load faces) | uniform traction on exposed voxel faces whose centre is < 0.3 + 1.5 mm from the part (the app's face rule, used to separate load-introduction effects) | — (static only) |
| **B** (part at its CG, RBE3) | 68 g × m at the part CG, spread to the contact nodes by an equal-weight RBE3 link (least-squares rigid fit). Check: Σf = F, moment about the CG = 0 to 1e-10 | m and the rotary inertia of a uniform solid part, at the CG through the same link (a rank-6 mass) |
| **C** (rigid part, RBE2) | the contact nodes slaved rigidly to a 6-DOF CG node; force there | m and inertia at the CG |

* **Stress measures.**
  * Element-centroid von Mises: a hex8 centroid stress is the natural average over its own voxel.
  * von Mises of the tensor averaged over aligned 1.5 mm blocks: the app's design voxel, so this is the like-for-like
    comparison with the app's "voxel σ".
  * The same with 0.75 mm blocks.
  * The 99.9th percentile of the element values.

## 3. Solver checks

### 3.1 Textbook cantilever: clamped at x = 0, tip load 10 N, E 65 GPa, ν 0.33

| L × section | h (elements through depth) | tip δ FE / Timoshenko | σ_xx at L/2, outer element centroid, FE / beam | f1 FE / theory |
|---|---|---|---|---|
| 30 × 3×3 mm | 0.75 (4) | 0.1970 / 0.2067 mm = 0.953 | 0.963 | 2699 / 2652 Hz = 1.018 |
| 30 × 3×3 mm | 0.375 (8) | 0.2028 / 0.2067 = 0.981 | 0.990 | 2660 / 2652 = 1.003 |
| 30 × 1.5×1.5 mm | 0.75 (2) | 2.850 / 3.288 = 0.867 | 0.867 | 1423 / 1326 = 1.073 |
| 30 × 1.5×1.5 mm | 0.375 (4) | 3.154 / 3.288 = 0.959 | 0.963 | 1353 / 1326 = 1.020 |
| 30 × 6×6 mm | 0.75 (8) | 0.01285 / 0.01322 = 0.972 (EB 1.002) | 0.990 | 5231 / 5304 = 0.986 |
| 18 × 3×3, 5 g tip mass | 0.75 (4) | 0.945 | 0.963 | 1073 / 1059 = 1.014 |
| 18 × 3×3, 5 g tip mass | 0.375 (8) | 0.975 | 0.990 | 1057 / 1059 = 0.999 |
| 18 × 1.5×1.5, 1 g tip mass | 0.75 (2) | 0.862 | 0.867 | 633 / 590 = 1.073 |

Notes on the theory column:
* Timoshenko deflection with κ = 10(1+ν)/(12+11ν).
* Frequency without a tip mass is Euler–Bernoulli, 1.8751².
* With a tip mass, it is the exact root of the EB tip-mass frequency equation (no rotary inertia of the tip mass).
* The reaction is 10.000 N in every case.

As expected for fully integrated hex8, the elements lock in bending. With two elements through a member (a 1.5 mm
member at 0.75 mm) they are about 13 % too stiff and read about 13 % low in bending stress. With four elements
(0.375 mm) the error is about 4 %. I therefore treat the 0.375 mm runs as the reference and the 0.75 mm runs as a
convergence step.

### 3.2 What a 1.5 mm voxel average does to bending (0.375 mm hex8, L = 18 mm, tip load 10 N, slice at x = 6–7.5 mm)

| Member (design voxels deep) | Beam surface σ | Max element vM | Max 1.5 mm block-average vM | Ratio |
|---|---|---|---|---|
| 1.5 × 1.5 mm (1) | 200.0 MPa | 152.3 | 7.7 | 0.04 |
| 3 × 3 mm (2) | 25.0 | 22.8 | 12.5 | 0.50 |
| 6 × 6 mm (4) | 3.1 | 3.1 | 2.4 | 0.76 |

Averaging the tensor over a voxel that spans the member's depth cancels the bending part, leaving roughly 1 − 1/n of
it plus the shear. The passive bolted and contact layers are exactly one voxel thick, and many SIMP members at low
volume fraction are one or two voxels thick. In practice the app's voxel σ still came out at or above my 1.5 mm
block averages on 5 of 6 designs (§6), probably because its tet nodes do not line up with member boundaries.

## 4. Mass

| Design | STL file | App mass | STL volume × ρ (mine) | Voxel mass 0.75 mm | Voxel mass 0.375 mm |
|---|---|---|---|---|---|
| pytopo3d P1 | `pytopo3d_P1_vf0.12.stl` | 10.704 g | 10.704 g | 10.61 g (-0.9 %) | 10.68 g (-0.2 %) |
| pytopo3d P2 | `pytopo3d_P2_vf0.03.stl` | 18.799 g | 18.799 g | 18.76 g (-0.2 %) | 18.78 g (-0.1 %) |
| pytopo3d P3 | `pytopo3d_P3_vf0.03.stl` | 18.690 g | 18.690 g | 18.66 g (-0.1 %) | 18.66 g (-0.2 %) |
| baseline P1 | `baseline_P1_vfNone.stl` | 13.025 g | 13.025 g | 13.02 g (+0.0 %) | 13.02 g (+0.0 %) |
| pyMOTO P1 | `pymoto_P1_vf0.05.stl` | 8.349 g | 8.349 g | 8.44 g (+1.2 %) | 8.40 g (+0.6 %) |
| BESO P1 | `beso_P1_vf0.08.stl` | 9.535 g | 9.535 g | 9.55 g (+0.2 %) | 9.55 g (+0.1 %) |

I checked whether the passive voxels are present by testing each 1.5 mm design-voxel centre against the STL:
* The bolted layer is complete in every design.
* The contact layer is complete in all four P1 designs.
* pytopo3d P2 is missing 556 / 1312 contact voxels (x 14.25–18.75 mm, 5.03 g).
* Every P3 design except the machined block (baseline, pyMOTO, pytopo3d, BESO and the sheet reference) misses
  68 / 980 (x = 23.25 mm, 0.62 g).
* The P2 contact layer is two 6-connected pieces and the P3 contact layer is two; each is one 26-connected piece.

## 5. Reaction (hand calculation a)

68 g = 666.85 m/s²; reaction = 666.85 N/kg × (part + bracket mass).

| Design | Hand, app mass | My FE reaction (model A, 0.75 mm), x / y / z | App imbalance, ccx / ngs |
|---|---|---|---|
| pytopo3d P1 | 240.54 N | 240.47 / 240.47 / 240.47 N | 8e-08 / 5e-13 |
| pytopo3d P2 | 212.59 N | 212.57 / 212.57 / 212.57 N | 2e-07 / 6e-13 |
| pytopo3d P3 | 279.20 N | 279.19 / 279.19 / 279.19 N | 8e-08 / 6e-12 |
| baseline P1 | 242.08 N | 242.08 / 242.08 / 242.08 N | 7e-08 / 2e-12 |
| pyMOTO P1 | 238.97 N | 239.03 / 239.03 / 239.03 N | 2e-07 / 2e-12 |
| BESO P1 | 239.76 N | 239.77 / 239.77 / 239.77 N | 1e-07 / 1e-12 |

The differences come only from the voxel mass of the bracket (≤ 0.07 N). My reaction balance is better than 1e-9
relative in every case and every model, and better than 1e-10 in all 0.375 mm runs.

## 6. Displacement and stress, comparison per design

### 6.1 Maximum displacement |u| (mm)

Each percentage is relative to the app's value.

| Design | Case | App | Mine A 0.75 | Mine A' 0.75 | Mine A 0.375 | Mine A' 0.375 | Mine B 0.375 (part at CG) |
|---|---|---|---|---|---|---|---|
| pytopo3d P1 | 68 g x | 0.0352 | 0.0305 (-13 %) | 0.0353 (+0 %) | 0.0315 (-10 %) | 0.0381 (+8 %) | 0.0309 |
| pytopo3d P1 | 68 g y | 0.0154 | 0.0125 (-18 %) | 0.0155 (+1 %) | 0.0135 (-12 %) | 0.0167 (+9 %) | 0.1641 |
| pytopo3d P1 | 68 g z | 0.0199 | 0.0254 (+28 %) | 0.0205 (+3 %) | 0.0268 (+35 %) | 0.0218 (+10 %) | 0.2856 |
| pytopo3d P2 | 68 g x | 0.0110 | 0.0117 (+6 %) | 0.0113 (+2 %) | 0.0128 (+16 %) | 0.0117 (+6 %) | 0.0124 |
| pytopo3d P2 | 68 g y | 0.0095 | 0.0084 (-12 %) | 0.0099 (+4 %) | 0.0087 (-8 %) | 0.0101 (+7 %) | 0.0888 |
| pytopo3d P2 | 68 g z | 0.0105 | 0.0092 (-12 %) | 0.0103 (-1 %) | 0.0098 (-7 %) | 0.0111 (+6 %) | 0.0309 |
| pytopo3d P3 | 68 g x | 0.0181 | 0.0308 (+70 %) | 0.0291 (+60 %) | 0.0259 (+43 %) | 0.0226 (+25 %) | 0.0242 |
| pytopo3d P3 | 68 g y | 0.0513 | 0.0568 (+11 %) | 0.0613 (+19 %) | 0.0561 (+9 %) | 0.0594 (+16 %) | 0.2526 |
| pytopo3d P3 | 68 g z | 0.0497 | 0.0524 (+5 %) | 0.0555 (+12 %) | 0.0521 (+5 %) | 0.0564 (+14 %) | 0.2331 |
| baseline P1 | 68 g x | 0.0098 | 0.0078 (-21 %) | 0.0099 (+0 %) | 0.0074 (-25 %) | 0.0105 (+6 %) | 0.0071 |
| baseline P1 | 68 g y | 0.0418 | 0.0405 (-3 %) | 0.0423 (+1 %) | 0.0420 (+0 %) | 0.0438 (+5 %) | 0.0928 |
| baseline P1 | 68 g z | 0.0035 | 0.0033 (-5 %) | 0.0037 (+6 %) | 0.0032 (-9 %) | 0.0037 (+5 %) | 0.0354 |
| pyMOTO P1 | 68 g x | 0.0207 | 0.0203 (-2 %) | 0.0204 (-2 %) | 0.0213 (+3 %) | 0.0214 (+4 %) | 0.0213 |
| pyMOTO P1 | 68 g y | 0.0866 | 0.0815 (-6 %) | 0.0813 (-6 %) | 0.0878 (+1 %) | 0.0876 (+1 %) | 0.0515 |
| pyMOTO P1 | 68 g z | 0.0540 | 0.0515 (-5 %) | 0.0514 (-5 %) | 0.0550 (+2 %) | 0.0548 (+1 %) | 0.1179 |
| BESO P1 | 68 g x | 0.0352 | 0.0296 (-16 %) | 0.0333 (-5 %) | 0.0314 (-11 %) | 0.0366 (+4 %) | 0.0313 |
| BESO P1 | 68 g y | 0.0185 | 0.0186 (+0 %) | 0.0189 (+2 %) | 0.0186 (+0 %) | 0.0191 (+3 %) | 0.1012 |
| BESO P1 | 68 g z | 0.0164 | 0.0140 (-15 %) | 0.0178 (+8 %) | 0.0133 (-19 %) | 0.0177 (+8 %) | 0.2634 |

* With the app's load faces (A'), my maximum displacements agree with the app's within ±10 %; pytopo3d P3 is the
  exception.
* Spreading the load over all nodes of the contact layer (A) instead of its faces puts |u| up to 35 % away from the
  app's value (up to 23 % away from my own A'). This is a local plate-deflection effect: |u| is a point value at the
  load introduction.
* The P3 x-case excess shrinks with refinement (+60 → +25 %). The cause is the staircase representation of the thin
  curved contact shell, where voxels touching only at an edge act as hinges. It is my model's error, not the app's.

### 6.2 von Mises stress (MPa)

The app's "voxel σ" is the max over voxels of the von Mises of the 1.5 mm voxel average.

| Design | Case | App voxel σ (ccx / ngs) | App raw nodal peak | Mine 1.5 mm block avg A / A' (0.75) | Mine block avg A / A' (0.375) | Mine max element A' 0.75 / 0.375 | Mine block avg B / C (0.375) |
|---|---|---|---|---|---|---|---|
| pytopo3d P1 | x | 45.0 / 45.0 | 62 | 19.9 / 22.7 | 32.7 / 35.9 | 37 / 56 | 32 / 15 |
| pytopo3d P1 | y | 52.4 / 52.4 | 67 | 25.6 / 26.8 | 26.2 / 27.7 | 37 / 58 | 111 / 111 |
| pytopo3d P1 | z | 53.6 / 53.6 | 114 | 38.5 / 37.2 | 42.7 / 40.1 | 64 / 105 | 158 / 162 |
| pytopo3d P2 | x | 16.2 / 16.2 | 22 | 9.8 / 9.4 | 15.1 / 16.2 | 13 / 19 | 15 / — |
| pytopo3d P2 | y | 26.3 / 26.4 | 30 | 9.4 / 9.1 | 19.0 / 19.9 | 15 / 27 | 67 / — |
| pytopo3d P2 | z | 12.4 / 12.4 | 23 | 10.6 / 10.7 | 11.0 / 11.2 | 14 / 20 | 40 / — |
| pytopo3d P3 | x | 47.1 / 47.1 | 58 | 31.5 / 30.6 | 49.9 / 50.8 | 46 / 74 | 51 / — |
| pytopo3d P3 | y | 91.1 / 91.1 | 122 | 66.6 / 67.8 | 104.5 / 107.4 | 94 / 164 | 239 / — |
| pytopo3d P3 | z | 90.5 / 90.5 | 105 | 67.2 / 67.7 | 104.0 / 108.5 | 98 / 150 | 250 / — |
| baseline P1 | x | 14.3 / 14.3 | 19 | 8.3 / 10.7 | 10.6 / 14.1 | 11 / 16 | 11 / 2 |
| baseline P1 | y | 34.6 / 34.6 | 46 | 19.7 / 20.2 | 28.6 / 29.4 | 27 / 35 | 55 / 19 |
| baseline P1 | z | 7.5 / 7.5 | 10 | 7.4 / 7.6 | 6.8 / 7.1 | 9 / 10 | 56 / 18 |
| pyMOTO P1 | x | 49.5 / 49.5 | 49 | 31.6 / 30.9 | 40.3 / 35.9 | 52 / 65 | 40 / 36 |
| pyMOTO P1 | y | 124.5 / 124.5 | 125 | 81.3 / 80.6 | 86.2 / 85.5 | 81 / 117 | 94 / 96 |
| pyMOTO P1 | z | 99.1 / 99.1 | 111 | 61.7 / 61.1 | 69.1 / 68.3 | 76 / 109 | 191 / 185 |
| BESO P1 | x | 47.6 / 47.6 | 51 | 35.9 / 39.8 | 37.4 / 41.5 | 40 / 53 | 37 / 22 |
| BESO P1 | y | 25.7 / 25.7 | 32 | 23.4 / 23.5 | 29.1 / 29.2 | 26 / 35 | 98 / 80 |
| BESO P1 | z | 29.3 / 29.4 | 35 | 21.2 / 23.3 | 29.7 / 32.9 | 29 / 39 | 314 / 229 |

I ran model C at 0.375 mm only for P1; P2/P3 C values are in §8 (0.75 mm). The block averages rise from 0.75 to
0.375 mm (hex8 locking and staircase geometry, §3.1). For P1 the change is mostly small; for pytopo3d P3 it is
+58 %, so my 0.75 mm P3 numbers should not be used.

**Stress against averaging scale** (0.375 mm runs, maximum over the three cases):

| Design | App voxel σ | Mine A': 1.5 mm avg | 0.75 mm avg | 0.375 mm element | 99.9th pct element | Mine B: 1.5 mm avg | B: 0.75 mm avg |
|---|---|---|---|---|---|---|---|
| pytopo3d P1 | 54 | 40 | 54 | 105 | 36 | 158 | 273 |
| pytopo3d P2 | 26 | 20 | 21 | 27 | 15 | 67 | 105 |
| pytopo3d P3 | 91 | 108 | 123 | 164 | 81 | 250 | 262 |
| baseline P1 | 35 | 29 | 29 | 35 | 33 | 56 | 57 |
| pyMOTO P1 | 124 | 86 | 93 | 117 | 89 | 191 | 234 |
| BESO P1 | 48 | 41 | 44 | 53 | 31 | 314 | 334 |

* The single-element maxima grow by about 1.5× each time the mesh is halved, the signature of the corner
  singularities the contest notes describe.
* The 99.9th percentile is below the 1.5 mm average, so the peaks are a handful of voxels.
* The governing blocks mostly sit in the struts, at x ≈ 7–17 mm, not on the bolted face or the load patch.
  Exceptions:
  * pyMOTO A' (y/z cases) peaks at x = 1.8 mm, at the edge of the bolted plate.
  * BESO A' (x case), BESO B (y case) and baseline B peak at x ≈ 17.7–17.8 mm, where the struts join the contact
    plate.

## 7. Where the part's mass actually sits

| Problem | Part CG x | Contact-zone centroid x (mine) | App-rule load-face centroid x | CG beyond the load centroid |
|---|---|---|---|---|
| P1 | 50.0 mm | 18.7 mm | 19.3 mm | 30.7 mm |
| P2 | 34.5 mm | 11.7 mm | 12.1 mm | 22.4 mm |
| P3 | 55.0 mm | 29.4 mm | 29.9 mm | 25.1 mm |

The part CG and inertia come from the part mesh, assuming a uniform solid. For the P1 box,
I_xx / I_yy / I_zz = 0.073 / 0.131 / 0.152 t·mm² (× 10⁶ for g·mm²).

The FE section moments in §10 confirm that the app's lateral load acts at x ≈ 19.3 mm. The P1 root moment is then
F × 19 mm. With the part's CG it would be F × 50 mm, 2.6× larger. The extra moment F·e at the interface is simply
missing from the app's model, in the static cases and in the modal mass (no CG offset, no rotary inertia).

## 8. Frequencies, margins and the load model

### 8.1 First frequency (Hz)

| Design | App f1 (ccx / ngs) | App f1, fine mesh | Mine A 0.75 | Mine A 0.375 | Rayleigh (A, static shape, min over cases) | 1-DOF √(k/m) (A, min) | Mine B (RBE3, part at CG) | Mine C (RBE2, rigid part) |
|---|---|---|---|---|---|---|---|---|
| pytopo3d P1 | 695 / 695 | 683 | 718 (+3.3 %) | 711 (+2.2 %) | 897 | 1057 | 160 | 188 |
| pytopo3d P2 | 1264 / 1264 | 1242 | 1255 (-0.7 %) | 1230 (-2.7 %) | 1721 | 2113 | 340 | 703 (0.75) |
| pytopo3d P3 | 410 / 410 | 398 | 431 (+5.2 %) | 412 (+0.5 %) | 613 | 642 | 218 | 254 (0.75) |
| baseline P1 | 660 / 660 | — | 688 (+4.2 %) | 674 (+2.1 %) | 677 | 706 | 353 | 874 |
| pyMOTO P1 | 446 / 446 | — | 459 (+3.0 %) | 442 (-0.9 %) | 442 | 459 | 248 | 296 |
| BESO P1 | 728 / 728 | — | 797 (+9.4 %) | 799 (+9.8 %) | 1072 | 1217 | 167 | 262 |

**Hand calculation (c).**
* The 1-DOF estimate is √(k/m_part)/2π with k = F_part / mean contact displacement along the load (part load only,
  0.375 mm). Taking the softest axis, it is +4 % (pyMOTO), +5 % (baseline) and +49 … +72 % (the pytopo3d designs
  and BESO) above the eigenvalue. It ignores the bracket mass, rotation and coupling between axes.
* The Rayleigh quotient f·u / uᵀMu with the static 68 g shape is an upper bound. Where the first mode is a single
  translation it is within 0–0.4 % of f1: baseline (y), pyMOTO (y). It is 26–49 % high where the mode couples axes
  or adds a rotation that one static case does not reproduce: pytopo3d P1 (y + z), P2 (y with rotation about z),
  P3, and BESO.
* For model B, the 1-DOF value √(k_cg/m) for pytopo3d P1 z is 195 Hz (k_cg = 528 N/mm at the CG). The part's rotary
  inertia brings this down to the 160 Hz eigenvalue.
* The model-B first modes are a lateral translation of the CG combined with a rotation about the orthogonal axis:
  the part "nods" on the bracket.

### 8.2 Margins (MS = allowable / (FoS · σ) − 1; 170 / 280 MPa; FoS 1.25 / 1.4)

| Design | App σ → MS yield / ult | Mine A' 1.5 mm avg, 0.375 (max case) → MS y / u | Mine B 1.5 mm avg, 0.375 → MS y / u | Mine C 1.5 mm avg → MS y / u |
|---|---|---|---|---|
| pytopo3d P1 | 54 MPa → +1.54 / +2.73 | 40 MPa → +2.39 / +3.98 | 158 MPa → **-0.14** / +0.27 | 162 MPa → **-0.16** / +0.23 |
| pytopo3d P2 | 26 MPa → +4.16 / +6.59 | 20 MPa → +5.82 / +9.03 | 67 MPa → +1.03 / +1.99 | 30 MPa → +3.52 / +5.64 (0.75) |
| pytopo3d P3 | 91 MPa → +0.49 / +1.20 | 108 MPa → +0.25 / +0.84 | 250 MPa → **-0.46** / **-0.20** | 140 MPa → **-0.03** / +0.43 (0.75) |
| baseline P1 | 35 MPa → +2.93 / +4.78 | 29 MPa → +3.63 / +5.81 | 56 MPa → +1.43 / +2.57 | 19 MPa → +6.19 / +9.57 |
| pyMOTO P1 | 124 MPa → +0.09 / +0.61 | 86 MPa → +0.59 / +1.34 | 191 MPa → **-0.29** / +0.05 | 185 MPa → **-0.27** / +0.08 |
| BESO P1 | 48 MPa → +1.86 / +3.20 | 41 MPa → +2.28 / +3.82 | 314 MPa → **-0.57** / **-0.36** | 229 MPa → **-0.41** / **-0.13** |

The B and C margins use the same 1.5 mm voxel average as the app, so they share the bending caveat of §3.2. At a
0.75 mm averaging scale, model B is worse still (§6.2).

The two links bracket the interface. RBE3 lets the contact plate deform freely; RBE2 makes it rigid, which is
realistic for a stiff box bolted to the plate. The truth for a bolted part lies between them, and both give negative
yield margins for pytopo3d P1, pyMOTO P1 and BESO P1. For pytopo3d P3, RBE3 gives −0.46 and RBE2 −0.03.

## 9. Random vibration (research note LC4–6, not in the contest)

n3σ = 3·√(π/2 · f1 · Q · ASD(f1)), with Q = 10 and the GEVS acceptance spectrum: 0.08 g²/Hz from 50 to 800 Hz,
−6 dB/oct above 800 Hz. The yield load factor is max(1.25 × 68, 1.6 × n3σ). This is arithmetic on the note's
formula only; it is not an FE result.

| Design | At app f1 → n3σ → factor vs 85 g | At model-B f1 → n3σ → factor |
|---|---|---|
| pytopo3d P1 | 695 Hz → 89 g → ×1.67 | 160 Hz → 42 g → ×1.00 |
| pytopo3d P2 | 1264 Hz → 76 g → ×1.42 | 340 Hz → 62 g → ×1.17 |
| pytopo3d P3 | 410 Hz → 68 g → ×1.28 | 218 Hz → 50 g → ×1.00 |
| baseline P1 | 660 Hz → 86 g → ×1.63 | 353 Hz → 63 g → ×1.19 |
| pyMOTO P1 | 446 Hz → 71 g → ×1.34 | 248 Hz → 53 g → ×1.00 |
| BESO P1 | 728 Hz → 91 g → ×1.71 | 167 Hz → 43 g → ×1.00 |

On the app's own frequencies, the note's random load case would govern yield and cut every reported yield margin.
pyMOTO P1 would go from +0.09 to (1.09 / 1.34) − 1 ≈ −0.19, a linear scaling that is approximate.

## 10. Hand calculation (b): P1 sections

I sliced the 0.375 mm voxelisation at several distances from the wall. For each slice I computed the area, centroid
and second moments, and the beam stress σ = M·c/I, with c measured from the centroid to the outer voxel face. The
moment is M = F·(x_load − x) plus the self-weight of the bracket beyond the slice. The load centroid is either the
app-rule load-face centroid (x = 19.35 mm) or the part CG (x = 50 mm). F = 233.4 N.

**pytopo3d P1:**

| Slice x (mm) | A (mm²) | I_z / I_y (mm⁴) | M (N·mm) | FE section moment ∫σ_xx·y dA, case y (A') | Beam σ y / z (MPa) | FE max abs σ_xx in slice y / z (A') | CG load: M | CG load: beam σ y / z | CG load: FE max abs σ_xx y / z (B) |
|---|---|---|---|---|---|---|---|---|---|
| 0.94 | 854 | 90614 / 40811 | 4360 | 4360 | 0.9 / 1.3 | 14.3 / 18.7 | 11515 | 2.3 / 3.4 | 25.9 / 29.6 |
| 2.06 | 86 | 11052 / 10909 | 4092 | 4091 | 6.7 / 4.5 | 8.9 / 26.4 | 11247 | 18.4 / 12.4 | 39.1 / 119.2 |
| 3.94 | 93 | 12886 / 10960 | 3646 | 3646 | 5.0 / 4.0 | 12.5 / 14.3 | 10800 | 14.8 / 11.9 | 64.9 / 134.4 |
| 6.94 | 95 | 10410 / 7620 | 2933 | 2933 | 4.2 / 3.9 | 11.7 / 23.1 | 10087 | 14.5 / 13.5 | 42.7 / 64.9 |
| 9.94 | 92 | 5779 / 4587 | 2221 | 2221 | 5.6 / 4.2 | 16.4 / 18.3 | 9376 | 23.8 / 17.7 | 81.9 / 122.7 |
| 12.94 | 70 | 3574 / 1792 | 1511 | 1509 | 5.1 / 6.0 | 26.0 / 30.1 | 8666 | 29.2 / 34.5 | 144.7 / 289.5 |
| 15.94 | 90 | 4974 / 1025 | 802 | 803 | 1.9 / 5.6 | 24.2 / 49.0 | 7957 | 19.2 / 55.5 | 187.9 / 174.4 |
| 17.44 | 124 | 7901 / 1776 | 448 | 449 | 0.8 / 1.9 | 16.3 / 30.1 | 7603 | 13.0 / 32.1 | 93.4 / 147.5 |

**All four P1 designs:**

| Design | Max deviation of the FE section moment from the hand M (all slices, both lateral cases) | Max beam σ, app load, x ≥ 2 mm | Max FE abs σ_xx (A'), same slices | FE / beam |
|---|---|---|---|---|
| pytopo3d P1 | 2.5 % | 6.7 MPa | 49.0 MPa | 7.3 |
| baseline P1 | 3.5 % | 6.6 MPa | 41.9 MPa | 6.3 |
| pyMOTO P1 | 3.5 % | 12.5 MPa | 120.1 MPa | 9.6 |
| BESO P1 | 0.6 % | 12.7 MPa | 37.4 MPa | 2.9 |

What this shows:
* **Statics are confirmed exactly.** The FE section moment equals the hand moment within 0.6–3.5 % at every slice.
  This checks the load's magnitude, direction and point of action independently of any stress measure.
* **Global beam bending is a small part of the stress.** These brackets are 20 mm long and 24–36 mm deep, so they
  are deep beams or frames, not slender beams. Their sections are not plane. The FE peaks are local: member bending,
  Vierendeel action at the strut junctions, and load introduction. They are 3–10× the composite-section M·c/I.
  Beam theory is therefore only a lower bound here and cannot certify the peak stress. The baseline's uniform ribbed
  section is the one case where it fits one axis: z at x = 6.94 mm gives 5.3 MPa from the beam against 5.5 MPa from
  the FE.
* **With the load at the part's CG**, the root moment is 2.6× (x = 2 mm) to 17× (x = 17.4 mm) the app's moment, and
  the FE σ_xx (model B) rises by about the same order.

## 11. Judgement per design

| Design | Mass | f1 (app's model) | σ / margins (app's model) | Under a part-at-CG model |
|---|---|---|---|---|
| pytopo3d P1 | correct | credible (mine +2 %) | credible, slightly conservative: my 1.5 mm avg 40 vs 54 MPa; at the 0.75 mm scale equal (54) | **fails yield** (MS −0.14 RBE3 / −0.16 RBE2); f1 160–188 Hz, below the 200 Hz target |
| pytopo3d P2 | correct, but the design lacks 5.0 g of the passive contact wrap, so it is not the same problem as its competitors | credible (−3 %) | credible, conservative: 20 vs 26 MPa | passes (MS +1.03); f1 340 Hz |
| pytopo3d P3 | correct (lacks a 0.6 g pole disc, as do the other P3 designs) | credible (+0.5 %) | **slightly optimistic**: 108 vs 91 MPa at 1.5 mm (+19 %), 123 at 0.75 mm (+35 %) → MS yield +0.25 / +0.10 instead of +0.49 | **fails** (MS −0.46 RBE3, −0.03 RBE2); f1 218–254 Hz |
| baseline P1 | correct | credible (+2 %) | credible, conservative: 29 vs 35 MPa | passes (MS +1.43); f1 353 Hz |
| pyMOTO P1 | correct | credible (−1 %) | conservative: 86 vs 124 MPa (the app's voxel value equals its raw nodal peak, 125) | **fails yield** (MS −0.29 / −0.27); f1 248–296 Hz |
| BESO P1 | correct | credible; mine is 10 % higher (799 Hz), so the app's value is the lower, conservative one, and part of the gap is hex8 locking | credible: 41 vs 48 MPa | **fails** (MS −0.57 / −0.41); f1 167–262 Hz |

Overall:
* The app's numbers are a faithful solution of the problem it poses. f1 is right within about 10 %; the voxel-average
  stress is within about −30 … +20 %, and the one optimistic case, P3, is +19 … +35 %.
* The problem it poses is optimistic: the part's inertia is put on the contact faces instead of at its CG. If the
  parts are carried by these brackets alone, the reported margins are too high by about 1.5–6.6× in stress, and f1
  by 1.8–4.4×. The winner's P1 and P3 brackets would then not pass yield.
* The reported stresses are resolution-limited voxel averages, as the contest notes say. Thin members and the
  1.5 mm passive plates can carry bending stresses those averages do not show.

Suggestions; none are applied, and I edited no app code:
* Load the part at its CG through an RBE3 link, for both the static cases and the modal mass, as the research note
  specifies.
* Make `solid_from_density` fail, or report, when passive contact voxels are dropped, or connect the passive layer
  with 26-connectivity.
* Add the random-vibration load case, which governs on the app's own f1.
* Re-rank the contest after these fixes.

## 12. Limitations of this check

* Hex8 with full integration still locks a little at 0.375 mm (about 4 % for a 1.5 mm member, §3.1).
* The 0.375 mm voxel model is a staircase of the marching-cubes surface. That matters locally on the curved P2/P3
  shells; it explains the P3 x-case displacement.
* My contact zone (voxels within 2 mm of the part) and the app's (faces within 1.8 mm) differ. Model A' isolates that
  difference.
* Models B and C assume a single bracket carries the whole part and that the part is a uniform solid; a tank's
  propellant may move. If the real installation shares the part between several brackets or other supports, the
  CG-offset effect is smaller. P1–P3 do not say so.
* I did not check P2/P3 for the baseline, pyMOTO and BESO. Model C for P2/P3 was run at 0.75 mm only, for memory.
* No hand calculation of the bolts or the interface.

## Reproduction

The scripts are outside the repository, in
`C:\Users\SEBAST~1\AppData\Local\Temp\claude\D--text-to-spaceship\f31514ae-f99c-42e6-a638-0f79b034a05a\scratchpad\verifier\`.
Run them with the project venv (`tools\env.cmd`, `uv run python`), with 2 threads.

| Script | What it does |
|---|---|
| `vfe.py` | the voxel hex8 solver |
| `cantilever.py` | §3.1 |
| `voxavg_demo.py` | §3.2 |
| `probe_problems.py` | saves `problems.pkl` from `t2s.gd.contest.problems(1.5)` |
| `run_design.py <stl> <h>` | per-design checks, writing `out/*.json` and `*.npz` |
| `check_passives.py` | passive-layer check (§4) |
| `avgscale.py` | stress against averaging scale (§6.2) |
| `handcalc_p1.py`, `handcalc_tables.py` | §10 |
| `tables.py` | generates the comparison tables above from the JSON outputs and `results.json` |

---

## Re-check after the fixes (2026-10-23)

This re-check covers the re-run contest (`data/gd_contest/results.json`, created 2026-10-23T11:39:53Z). I used the
same rules as before: my own voxel hex8 model, no app FE code for any number, 2 threads, and `t2s` imported only for
`t2s.gd.contest.problems(1.5)`. Designs checked:
* the four P1 designs: baseline, pyMOTO vf 0.08, pytopo3d vf 0.05, BESO vf 0.08;
* the winner's P2 (pytopo3d vf 0.05) and P3 (pytopo3d vf 0.03).

The sections above are left as they were. They describe the earlier run.

### R1. Bottom line

1. **The fixes are in the code and do what they claim.** The part's 68 g force now acts at its CG, as force plus
   moment on the contact faces. My own model reproduces the app's part-CG displacements within −2 … +8 % on all
   18 design-axis pairs. The reaction equals 68 g × (part + bracket) exactly.
2. **Mass and contact layers are right.** Mass is exact. Every contact layer is complete in every reported STL (0
   voxels missing), and every design is a single solid piece. Nothing lost a piece.
3. **The stresses are credible and mostly conservative.** My 1.5 mm voxel averages are 0–28 % below the app's on the
   P1 and P2 designs, and 1–7 % above on P3.
4. **The margins with random vibration included are credible.** The app's figures are conservative on five designs,
   by 0.09–0.75 in MS (yield), and slightly optimistic on pytopo3d P3 (+0.73 reported, +0.61 mine).
5. **f1 is credible for the four P1 designs and P2**: the app's per-axis Rayleigh values are 0.5–2.2 % above my
   eigen f1. **It is optimistic for P3**: 573 Hz reported against 332 Hz true first mode, a factor 1.73. The P3 bracket
   still passes 100 Hz and the 200 Hz target.
6. **Two caveats remain.**
   * Averaging over 0.75 mm instead of 1.5 mm takes the winner's P1 yield margin to −0.00 and P3 to +0.26 (§3.2 of
     the original note: voxel averages hide bending in thin members).
   * On four designs the governing voxel is in the bolted layer at the plate corner, where the all-DOF-fixed face is
     an idealisation.

### R2. What changed, confirmed by reading the code

1. **`evaluate.fea_problem` (load model).**
   * The load faces are boundary faces whose centroid lies within 0.3 + 1.0·h of the part, excluding the bolted face.
   * They carry F at `part_com` as force plus moment, M = (p − c) × F, taken about their area centroid c.
   * `mesh.traction_field` / `consistent_surface_load` turn this into a linear traction t = F/A + ω × (x − c) with
     ω = J⁻¹M, integrated exactly with a degree-5 rule. This is an area-weighted RBE3 and adds no stiffness.
2. **`evaluate.rayleigh_frequency` (frequency).**
   * For each axis, the Rayleigh quotient uᵀf / uᵀMu is taken on that axis's static deflection.
   * The part is a rigid mass with its inertia at the CG, moving with an area-weighted least-squares fit of the load
     faces. f1 is the minimum over axes and solvers.
   * By construction this is an upper bound on f1, and it cannot find a mode that has no translational effective
     mass (R5).
3. **`domain.miles_3sigma_g` (random vibration).**
   * GEVS acceptance: +6 dB/oct from 20 to 50 Hz, 0.08 g²/Hz from 50 to 800 Hz, −6 dB/oct above. Q = 10.
   * Factors: yield max(1.25·68, 1.6·3σ), ultimate max(1.4·68, 1.8·3σ), on each axis's own frequency. The stress
     scales linearly from 68 g.
   * This is the research note's §2 item 4.
4. **Contact layer.** `domain_from_bracket` now uses ~void & dist < 0.3 + 2.0·h, which makes the P1 contact plate two
   voxels (3 mm) thick. `solid_from_density` now rejects a design with any contact voxel not joined to the bolted
   layer, instead of dropping it.
5. **`DesignDomain.contact_voxel_forces`** gives the optimisers the same force and moment, as an equal-voxel-weight
   RBE3.
6. **`VOL_LADDER`** ends at 0.45.

### R3. My model for the re-check

* **Mesh.** The same hex8 code (`vfe.py`) at 0.375 mm for all six designs. The rigid-part model C for P2/P3 was run at
  0.75 mm, for memory.
* **Part mass properties.** I integrated them from the part mesh myself, assuming a uniform solid. They equal the
  app's `part_com` and inertia to the printed digits: P1 I = 0.0729 / 0.1313 / 0.1517 t·mm², P2 0.1837 / 0.1837 /
  0.0698, P3 0.1439 / 0.1439 / 0.1438.
* **Load models.** All three put the part force at the CG and include 68 g self-weight.

| Model | Link from the CG to the bracket |
|---|---|
| **B'** (like-for-like with the app) | voxel faces within 0.3 + 1.5 mm of the part, area-weighted RBE3, i.e. a linear traction about their centroid |
| **B** | my own contact zone (voxels within 2 mm of the part), equal-weight RBE3 |
| **C** | rigid part (RBE2) slaved to my contact zone |

  Check for every case: ΣF = F, and the moment about the CG is ≤ 7e-9 N·mm.
* **Frequencies.** I did a shift-invert eigen solve for six modes with the part's mass and inertia at the CG,
  through the B', B or C link, and computed the effective modal mass per axis. Each axis's frequency is that of the
  mode with the largest effective mass along it. For comparison I also computed the app's per-axis Rayleigh
  quotient on my model B'.
* **Margins.** I recomputed 3σ from *my* per-axis eigen frequency with the research-note formula. MS =
  allowable / (σ₆₈ · factor / 68) − 1, with σ₆₈ the max 1.5 mm voxel average per axis.

### R4. Mass, contact layers, reaction

**Mass and passive layers:**
* The domain contact layer recomputed by my own code (my winding-number inside test, my distances) equals the app's
  mask exactly for P1 (768 voxels) and P2 (1944). It differs in 8 of 1504 voxels for P3, at boundary cases.
* Each layer is now one 6-connected piece.
* The 1.5 mm design-voxel centres of each STL were tested against the domain's contact mask.

| Design | STL | App mass | STL volume × ρ (mine) | Voxel mass (0.375 mm) | Contact voxels missing / total | Solid pieces |
|---|---|---|---|---|---|---|
| baseline P1 | `baseline_P1_vfNone.stl` | 15.924 g | 15.924 g | 15.92 g | 0 / 768 | 1 |
| pyMOTO P1 | `pymoto_P1_vf0.08.stl` | 12.747 g | 12.747 g | 12.81 g | 0 / 768 | 1 |
| pytopo3d P1 | `pytopo3d_P1_vf0.05.stl` | 11.575 g | 11.575 g | 11.58 g | 0 / 768 | 1 |
| BESO P1 | `beso_P1_vf0.08.stl` | 12.668 g | 12.668 g | 12.68 g | 0 / 768 | 1 |
| pytopo3d P2 | `pytopo3d_P2_vf0.05.stl` | 30.865 g | 30.865 g | 30.86 g | 0 / 1944 | 1 |
| pytopo3d P3 | `pytopo3d_P3_vf0.03.stl` | 25.844 g | 25.844 g | 25.85 g | 0 / 1504 | 1 |

All other reported STLs (P2/P3 of the other entrants, block, sheet) also have 0 contact or bolted voxels missing and
are single pieces.

**Reaction:**

| Design | 68 g × (part + app mass) | My reaction B', x / y / z |
|---|---|---|
| baseline P1 | 244.02 N | 244.02 / 244.02 / 244.02 N |
| pyMOTO P1 | 241.90 N | 241.94 / 241.94 / 241.94 N |
| pytopo3d P1 | 241.12 N | 241.12 / 241.12 / 241.12 N |
| BESO P1 | 241.85 N | 241.85 / 241.85 / 241.85 N |
| pytopo3d P2 | 220.64 N | 220.64 / 220.64 / 220.64 N |
| pytopo3d P3 | 283.98 N | 283.98 / 283.98 / 283.98 N |

### R5. Part-CG displacement, stiffness and frequencies

**CG displacement along the load (68 g, including self-weight) and stress per axis.** Stress is the max von Mises of
the 1.5 mm voxel average, in MPa.

| Design | Axis | App CG displacement | Mine B' | Mine B | App σ | Mine B' 1.5 mm | Mine B 1.5 mm | Mine C 1.5 mm | Mine B' 0.75 mm avg |
|---|---|---|---|---|---|---|---|---|---|
| baseline P1 | x | 0.0009 mm | 0.0009 (+3 %) | 0.0007 | 5.5 | 5.7 (+3 %) | 4.7 | 1.7 | 5.7 |
| baseline P1 | y | 0.0469 mm | 0.0485 (+3 %) | 0.0445 | 40.8 | 37.9 (-7 %) | 36.5 | 18.5 | 37.9 |
| baseline P1 | z | 0.0225 mm | 0.0228 (+1 %) | 0.0217 | 27.8 | 27.7 (-1 %) | 24.2 | 18.2 | 28.4 |
| pyMOTO P1 | x | 0.0021 mm | 0.0021 (-1 %) | 0.0023 | 10.6 | 8.3 (-22 %) | 9.7 | 7.2 | 10.4 |
| pyMOTO P1 | y | 0.0208 mm | 0.0208 (-0 %) | 0.0196 | 33.8 | 30.8 (-9 %) | 30.8 | 26.6 | 38.6 |
| pyMOTO P1 | z | 0.0396 mm | 0.0390 (-2 %) | 0.0388 | 38.9 | 36.6 (-6 %) | 37.0 | 34.6 | 51.9 |
| pytopo3d P1 | x | 0.0048 mm | 0.0049 (+2 %) | 0.0053 | 23.1 | 19.2 (-17 %) | 19.4 | 18.6 | 22.7 |
| pytopo3d P1 | y | 0.0418 mm | 0.0428 (+2 %) | 0.0423 | 80.1 | 57.8 (-28 %) | 57.5 | 53.8 | 87.5 |
| pytopo3d P1 | z | 0.0763 mm | 0.0778 (+2 %) | 0.0788 | 81.8 | 67.4 (-18 %) | 67.7 | 67.8 | 95.1 |
| BESO P1 | x | 0.0019 mm | 0.0019 (+1 %) | 0.0021 | 14.4 | 11.2 (-22 %) | 10.2 | 10.0 | 13.1 |
| BESO P1 | y | 0.0295 mm | 0.0301 (+2 %) | 0.0300 | 45.1 | 43.3 (-4 %) | 43.8 | 40.8 | 54.1 |
| BESO P1 | z | 0.0356 mm | 0.0356 (-0 %) | 0.0347 | 48.1 | 40.6 (-16 %) | 41.1 | 40.6 | 53.3 |
| pytopo3d P2 | x | 0.0020 mm | 0.0020 (-2 %) | 0.0020 | 7.3 | 6.3 (-13 %) | 6.4 | 4.1 (0.75) | 8.5 |
| pytopo3d P2 | y | 0.0133 mm | 0.0137 (+3 %) | 0.0136 | 22.3 | 18.5 (-17 %) | 18.3 | 9.5 (0.75) | 25.1 |
| pytopo3d P2 | z | 0.0048 mm | 0.0052 (+8 %) | 0.0047 | 12.9 | 12.3 (-5 %) | 12.1 | 7.5 (0.75) | 16.5 |
| pytopo3d P3 | x | 0.0080 mm | 0.0082 (+2 %) | 0.0081 | 18.0 | 19.3 (+7 %) | 19.3 | 19.5 (0.75) | 24.7 |
| pytopo3d P3 | y | 0.0502 mm | 0.0516 (+3 %) | 0.0512 | 51.6 | 54.2 (+5 %) | 54.1 | 51.4 (0.75) | 67.1 |
| pytopo3d P3 | z | 0.0502 mm | 0.0509 (+1 %) | 0.0498 | 52.0 | 52.7 (+1 %) | 52.8 | 48.0 (0.75) | 69.0 |

CG stiffness k = F / δ_CG under the part load alone (model B', N/mm, x / y / z):

| Design | k_x | k_y | k_z |
|---|---|---|---|
| baseline P1 | 268570 | 4874 | 10279 |
| pyMOTO P1 | 112094 | 11384 | 6047 |
| pytopo3d P1 | 49134 | 5519 | 3045 |
| BESO P1 | 124175 | 7863 | 6644 |
| pytopo3d P2 | 108809 | 14862 | 40396 |
| pytopo3d P3 | 33917 | 5298 | 5371 |

Two more observations:
* The rigid-part model C is close to B' on the P1 designs, but much stiffer and much less stressed on P2. Making the
  curved saddle rigid over-stiffens it, so B' is the right comparison there.
* The 1.5 mm average excluding the bolted voxel layer is lower for pyMOTO P1 (y 30.8 → 24.2), BESO P1 (43.3 → 42.3)
  and pytopo3d P3 (54.2 → 42.3, x/y/z all governed at the corner of the bolted plate, y = z = ±23 mm). The
  governing voxel of those designs sits at the bolted-plate edge.

**Frequencies (Hz).** "Eff. mass" is the effective-mass fraction of the dominant mode along that axis.

| Design | Axis | App f (Rayleigh) | Mine, app's Rayleigh method on B' | Mine, eigen B' (dominant mode; eff. mass) | Mine, eigen B | Mine, eigen C |
|---|---|---|---|---|---|---|
| baseline P1 | x | 4418 | 4351 | 4353 (-1 %; 0.97) | 4746 | 6402 |
| baseline P1 | y | 573 | 563 | 562 (-2 %; 0.88) | 589 | 918 |
| baseline P1 | z | 785 | 779 | 777 (-1 %; 0.78) | 800 | 928 |
| pyMOTO P1 | x | 2799 | 2808 | 2810 (+0 %; 0.98) | 2677 | 3436 |
| pyMOTO P1 | y | 882 | 882 | 875 (-1 %; 0.91) | 899 | 1033 |
| pyMOTO P1 | z | 620 | 624 | 617 (-1 %; 0.83) | 616 | 714 |
| pytopo3d P1 | x | 1878 | 1858 | 1863 (-1 %; 0.99) | 1778 | 2281 |
| pytopo3d P1 | y | 618 | 611 | 608 (-2 %; 0.91) | 610 | 676 |
| pytopo3d P1 | z | 465 | 460 | 456 (-2 %; 0.91) | 452 | 515 |
| BESO P1 | x | 2810 | 2772 | 2983 (+6 %; 0.98) | 2862 | 3423 |
| BESO P1 | y | 738 | 730 | 744 (+1 %; 0.80) | 744 | 825 |
| BESO P1 | z | 665 | 665 | 651 (-2 %; 0.77) | 657 | 707 |
| pytopo3d P2 | x | 2865 | 2900 | 2898 (+1 %; 0.93) | 2851 | 5892 (0.75) |
| pytopo3d P2 | y | 1013 | 1003 | 996 (-2 %; 0.74) | 995 | 2138 (0.75) |
| pytopo3d P2 | z | 1802 | 1736 | 1712 (-5 %; 0.82) | 1796 | 3309 (0.75) |
| pytopo3d P3 | x | 1455 | 1438 | 1439 (-1 %; 0.98) | 1441 | 1742 (0.75) |
| pytopo3d P3 | y | 573 | 566 | 603 (+5 %; 0.78) | 604 | 753 (0.75) |
| pytopo3d P3 | z | 573 | 569 | 608 (+6 %; 0.78) | 612 | 760 (0.75) |

**First eigenfrequency (all modes, not just the dominant ones):**
* P1 and P2: the first mode is the translational one along the softest axis. My f1 (B') is 562 / 617 / 456 / 651 /
  996 Hz against the app's 573 / 620 / 465 / 665 / 1013 Hz, so the app is 0.5–2.2 % high. That fits Rayleigh being an
  upper bound; my hex8 is itself slightly stiff, so the true value may be a few percent lower still.
* The lowest mode with zero translational effective mass (torsion of the part about the wall normal) sits above the
  app's f1 in every P1/P2 design: 1790 / 934 / 656 / 862 / 2512 Hz.
* **P3 is different.** The first mode is at **332 Hz** (332 Hz in B and 352 Hz in C as well): the sphere twisting
  about the wall-normal x axis. In the B' modal solution the part's motion is θ_x only, with zero effective mass in
  x, y and z.
* P3 then has two rocking modes at 490–492 Hz (15–20 % effective mass in y/z) before the dominant y/z translations
  at 603 / 608 Hz.
* The app's per-axis Rayleigh method cannot represent the torsion mode, because no translational load case deflects
  the part in torsion. It reports f1 = 573 Hz, which is **1.73× too high**. The bracket still passes 100 Hz and the
  200 Hz target.
* Because the torsion mode has no translational effective mass, it does not change the per-axis Miles loads.

### R6. Margins including random vibration (yield / ultimate)

| Design | App f1 | Mine f1, eigen B' / B / C | App MS (governing axis) | Mine, B' σ, my per-axis f → 3σ | Mine, B σ | Mine, C σ | Mine, B' σ at 0.75 mm averaging |
|---|---|---|---|---|---|---|---|
| baseline P1 | 573 Hz | 562 / 589 / 918 Hz | +1.20 / +2.22 (y, 3σ 80 g) | +1.39 / +2.50 (y, 3σ 80 g) | +1.42 / +2.55 | +3.41 / +5.46 | +1.39 / +2.50 |
| pyMOTO P1 | 620 Hz | 617 / 616 / 714 Hz | +1.22 / +2.25 (z, 84 g) | +1.37 / +2.46 (z, 84 g) | +1.34 / +2.42 | +1.32 / +2.40 | +0.67 / +1.44 |
| pytopo3d P1 | 465 Hz | 456 / 452 / 515 Hz | +0.08 / +0.58 (y, 84 g) | +0.49 / +1.19 (z, 72 g) | +0.49 / +1.19 | +0.40 / +1.04 | **-0.00** / +0.46 (y) |
| BESO P1 | 665 Hz | 651 / 657 / 707 Hz | +0.73 / +1.53 (z, 87 g) | +0.82 / +1.67 (y, 92 g) | +0.80 / +1.63 | +0.89 / +1.77 | +0.45 / +1.13 |
| pytopo3d P2 | 1013 Hz | 996 / 995 / 2138 Hz | +2.83 / +4.61 (y, 85 g) | +3.58 / +5.71 (y, 85 g) | +3.62 / +5.76 | (+12.07; RBE2 over-stiff saddle) | +2.37 / +3.94 |
| pytopo3d P3 | 573 Hz | 332 / 332 / 352 Hz | +0.73 / +1.53 (z, 80 g) | **+0.61** / +1.36 (y, 83 g) | +0.61 / +1.36 | +0.52 / +1.23 (0.75) | +0.26 / +0.85 (z) |

The random load case governs every lateral (y, z) axis in both the app's evaluation and mine: 3σ = 63–94 g, i.e.
1.6 × 3σ = 101–151 g against 85 g. On the governing axes, my per-axis eigen frequencies give the same 3σ as the
app's Rayleigh frequencies to within ±2.5 g. The governing axis differs only for pytopo3d P1: the app's is y (84 g),
mine is z (72 g), because my σ_y is the lower one.

### R7. Verdict after the fixes

| Design | Mass | f1 | σ (1.5 mm voxel average) | MS incl. random |
|---|---|---|---|---|
| baseline P1 | exact | credible (app +2 % high) | credible (mine −7 … +3 %) | conservative: +1.20 reported, +1.39 mine |
| pyMOTO P1 | exact | credible (+0.5 %) | conservative (mine −6 … −22 %) | conservative: +1.22 / +1.37; +0.67 at 0.75 mm averaging |
| pytopo3d P1 | exact | credible (+2 %) | conservative (mine −17 … −28 %) | conservative at 1.5 mm (+0.08 / +0.49); **zero at 0.75 mm averaging** |
| BESO P1 | exact | credible (+2 %) | conservative (mine −4 … −22 %) | conservative: +0.73 / +0.82; +0.45 at 0.75 mm |
| pytopo3d P2 | exact | credible (+1.7 %) | conservative (mine −5 … −17 %) | conservative: +2.83 / +3.58 |
| pytopo3d P3 | exact | **optimistic: 573 reported, 332 Hz true (×1.73)**, still passes | slightly optimistic (mine +1 … +7 %) | **slightly optimistic: +0.73 reported, +0.61 mine**; +0.26 at 0.75 mm |

Remaining points; none is a pass/fail change at the contest's own 1.5 mm resolution:
* **f1 by per-axis Rayleigh** misses modes with no translational effective mass. In P3 this is torsion of the part
  about the bracket axis at 332 Hz. An eigen solve, or a torsional trial shape, would catch it.
* **Voxel averaging still hides bending** in members one or two voxels thick. At 0.75 mm averaging the winner's P1
  bracket is at MS yield −0.00 and P3 at +0.26, so both are marginal at a finer resolution.
* **The bolted layer.** On pyMOTO P1, BESO P1 and pytopo3d P3 the governing voxel sits in the bolted layer at the
  plate edge or corner, where the all-DOF-fixed face is an idealisation and the bolts are not modelled. pytopo3d P1
  (y case) also peaks in the wall layer, but its stress barely changes when that layer is excluded.
* **Passive material dominates the masses.** It is now 10.4 g (P1), 28.0 g (P2) and 22.9 g (P3): 61.3 g of the
  winner's 68.3 g. The P1 contact plate alone is 3 mm thick and weighs 6.9 g. The ranking (68.3 / 72.4 / 77.4 g) is
  therefore decided by a few grams of optimised material. This is an observation about the contest set-up, not an
  error.

Re-check scripts, in the same scratch folder under `recheck\`:

| Script | What it does |
|---|---|
| `probe_problems2.py` | saves the problem definitions to `problems2.pkl` |
| `run_design2.py <stl> <h> [noC]` | models B', B and C, eigen solves with effective masses, Rayleigh |
| `check_passives2.py` | contact-layer recomputation and passive-voxel check |
| `tables2.py` | generates the tables in this section from `recheck\out\*.json` and `results.json` |

## Follow-up (main agent, after this re-check)

Not part of the independent verification; recorded here so each finding has its outcome.

* **f1 missed the torsion mode.** Fixed. `gd/evaluate.py` adds three pure-torque load cases and finds the modes
  by Rayleigh–Ritz on all six static deflections (`ritz_modes`), with the part as a rigid mass and inertia at its
  CG. f1 is now the lowest mode of any kind. Each axis's random load is the larger of Miles at its dominant mode
  (as in R3) and the SRSS of all modes' base forces (`score`).
* **The RBE3 rotation fit was biased.** Found while testing the fix. The app sampled each contact face only at
  its centroid but divided by the exact polar moment, so it read the part's rotation about 4 % low on a 2.5 mm
  mesh. It now integrates exactly over the 6-node faces, and a bar's twist matches Saint-Venant to 0.4 % (2.5 mm)
  and 0.01 % (1.25 mm).
* **New tests** (`test_gd_evaluate.py`): a square bar carrying a tip inertia, with torsion within 1 % of
  k_t / (I + I_bar/3) and bending against Euler–Bernoulli with a tip mass. Plus the load rule on synthetic modes.
* **Re-check of the saved designs** (`scripts/gd_reevaluate.py`): every saved design was evaluated again from its
  STL, and every mass matched. Pytopo3d P3 now reports f1 = 345 Hz with the part rotating about x (R5: 332 Hz).
  The rocking modes are at 505 Hz and y/z at 615 / 616 Hz (R5: 490–492 / 603 / 608 Hz). Its margin is +0.67
  (was +0.73; R6: +0.61). No pass/fail result, mass or ranking changed.
* **Still open:** voxel averaging hides bending in members one or two voxels thick (P1 at about 0 margin with
  0.75 mm averaging), and the bolted layer is an all-DOF-fixed idealisation. Both are listed as limitations in
  `docs/V2.md`.
