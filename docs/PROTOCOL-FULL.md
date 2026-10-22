# TEXT-TO-SPACESHIP — Engineering and Implementation Protocol

| | |
|---|---|
| **Document status** | v1.2 — revised after your two reviews of 2026-10-22. **Addenda 1 and 2 (at the end) override any conflicting text; Addendum 2 wins over Addendum 1.** Nothing is implemented. |
| **Date** | 2026-10-21 |
| **Project folder** | `D:\text-to-spaceship` |
| **Dataset** | `data/synthetic/` — 19 packable parts + 3 validation fixtures, millimetres. Dataset SHA-256 `8dd5692792870f55a2e666a96555d7172e7e40adff351026d1eb17fa087e0f7f` |
| **Fusion 360 validation** | **NOT CONFIGURED** (see §N). No Fusion API call has been made. |
| **Basis** | The user's specification. The accepted defaults from the clarifying questionnaire (all defaults accepted, including the synthetic dataset). A read-only analysis of the dataset. 13 research agent reports plus a cross-check report. |

### How to read this document
- **§0** is a two-page summary plus the decisions you need to make.
- **§A–§P** follow the section order required by the specification.
- **Appendices:** the dataset analysis, the deferred-dependency register, the install list, the research-process disclosure, and key sources.

Labels used throughout:
- **ESTIMATE:** reasoned but not measured.
- **ASSUMED:** an engineering assumption made because data is missing.
- **UNVERIFIED:** a claim we could not confirm from a primary source.
- **MEASURED:** an actual computation on this machine.

No number in this document comes from an optimisation run of the proposed system. None has been run. See Appendix D for the two research agents that ran small in-memory prototypes.

---

## 0. Summary

### 0.1 What is proposed
A local web application (localhost only) with a Python geometry/optimisation backend and a React + three.js engineering front end.

**Pipeline.** The optimiser combines four stages:
1. a fast, *feasible-by-construction* box-proxy placement decoder;
2. a physics-aware memetic genetic algorithm (BRKGA islands with local search) that searches order, orientation and placement rules;
3. exact-geometry compaction that recovers space wasted by proxies, including cavities such as the torus hole and the U-channel;
4. a **sound exact-mesh validator**, which is the only component allowed to label a layout VALID.

**Interaction.**
- Moving a priority slider re-ranks an archive of already-validated layouts in under a millisecond (ESTIMATE). Something valid is therefore on screen immediately, while warm-started search streams better layouts.
- Editing a part's mass updates the centre of mass and inertia in O(1).
- Every message carries generation and revision numbers, so stale results can never overwrite newer ones.

**Fusion 360** is an optional, human-triggered, independent CAD cross-check. It is reached through a generated export package and script. It stays NOT CONFIGURED until you authorise it.

```
 STL files ─► ingest/validate/repair ─► mass properties (float64, exact for polyhedra) ─► classification ─► proxies
                                                                                                        │
     ┌──────────────────────────────── optimisation (12 threads) ──────────────────────────────────────┘
     │  constructive seeds (EP-BFL box decoder, CP-SAT box bounds) ─► BRKGA islands (physics-aware Tchebycheff)
     │        ─► memetic local search (re-orient / swap / push-to-wall / slack-shift)  ─► exact compaction
     │        ─► VALIDATOR (exact mesh, certificates, containment, clearance, insertion) ─► archive
     └─► WebSocket stream ─► browser: only VALIDATED layouts drawn solid; candidates = faint ghost "UNVERIFIED"
                                    background: own NSGA-II Pareto front ─► comparison workspace
```

### 0.2 Key findings that changed the plan

| # | Finding | Consequence |
|---|---|---|
| 1 | With all parts inside a fixed box, volume fraction is constant (31.7 %) for every layout | "Packing efficiency" = used length along Z (accepted). "Space Used" is display only |
| 2 | Under uniform density, the best arrangement does not depend on the density value | 2,700 kg/m³ is a placeholder. Arrangements change only when masses differ |
| 3 | CDS Rev 14.1, verified from the primary source: 3U COM within ±20 mm (X, Y) and ±70 mm (Z) is a *shall*. The 6.00 kg mass is a *Note* ("typical maximum") | COM box is hard in Stage 2. The mass limit is a reported dataset check |
| 4 | Packing at one end conflicts with centring the COM. Prototype layouts sat 48–78 mm off-centre along Z, some outside ±70 mm | The trade-off is real and is shown honestly: occupied span and a COM-box badge on every layout (decision U3) |
| 5 | Single convex hulls inflate part volume by +27.6 %, and single boxes by +72.4 %. Six concave parts cause 93 % of the hull overhead | Certified multi-piece proxies for those parts. The exact mesh is always the final authority |
| 6 | Under the ASSUMED Stage 2 hardware, a 10 mm side-wall harness channel cannot sit beside 90 mm PCBs (2 + 10 + 90 + 2 = 104 mm > 100 mm, even with zero clearance). Two independent estimates put a box-proxy Stage 2 layout at or above the 336.5 mm available length | Stage 2 assumptions need decisions U4–U7. Infeasibility is reported, never hidden |
| 7 | FCL's tolerances are absolute and its signed-distance/EPA has known failures at touching contacts | A validator that cannot falsely accept: separating-plane certificates, containment tests, a second implementation |
| 8 | There is no headless Fusion. Its interference and distance APIs reject mesh bodies; mesh→BRep conversion is a *preview* API with a ~10k-facet practical limit | Fusion = manual, deferred cross-check. The blob part must be decimated for it |
| 9 | Several popular libraries are excluded by the permissive-only licence rule | Our own NSGA-II and BRKGA loops. See Appendix B |

### 0.3 Decisions needed from you at approval
Each decision has a recommended default. "APPROVE" with no comments accepts every default below. Details are in §L.3.

| ID | Decision | Recommended default |
|---|---|---|
| U1 | Licence. pymoo ≥ 0.6.1.6 hard-requires **moocore (LGPL-2.1+)**. Verified on PyPI | **No waiver:** we implement NSGA-II, hypervolume and IGD+ ourselves, tested on ZDT/DTLZ and against optuna (MIT) |
| U2 | Licence wording. Read literally, "MIT/BSD/Apache/MPL/Zlib/ISC" would exclude NumPy (0BSD, CC0-1.0 parts), SciPy (bundled Qhull, BSL-1.0) and pydantic (typing-extensions, PSF-2.0) | **Amend the rule** to "permissive, non-copyleft, SPDX-listed", which adds BSL-1.0, PSF-2.0, Qhull, 0BSD, CC0-1.0 and Apache-2.0 WITH LLVM-exception. GPL, LGPL, AGPL, EPL and non-commercial licences stay excluded |
| U3 | Compactness definition (you accepted "free space at one end") | **Keep yours.** Also show "occupied span" and the CDS COM-box status on every layout, so the COM conflict is visible |
| U4 | Clearance arithmetic | **2.2 mm** part–part (2.0 + 0.2 tolerance per gap) and **1.2 mm** part–wall. Alternative: per-part stack-up, giving 2.4 mm part–part |
| U5 | Harness channel vs PCB stack: 2 + 10 + 90 + 2 = 104 mm > 100 mm, so Stage 2 is infeasible as specified | The channel runs along one side wall **except across the PCB stack's Z span**. There, wiring is ASSUMED to go through the PC/104 stack bus |
| U6 | Which face carries the 3 mm mounting layer (decisive for Stage 2 length) | **The optimiser chooses** a planar face (AABB face for curved parts) that touches a wall or rail. On that face only, the layer *replaces* the 1.2 mm wall clearance |
| U7 | Stage 2 frame mass (ASSUMED frame ≈ 0.876 kg) | **Exclude** it from the hard CDS COM check. This is conservative: a symmetric frame can only pull the COM toward the centre. Report the COM both with and without the frame |
| U8 | Interlocked placements (e.g. a rod through the torus hole) | **Allowed in Stage 1, flagged** "not assemblable along ±Z". **Forbidden in Stage 2** |
| U9 | Unattended run | Before you leave: project-scoped permission allowlist (Appendix C.4) + keep-awake. You set the permission mode in the app |

The following are recorded as engineering decisions (§L.4) and need no input. Say so if you disagree with any:
- Python 3.14 and Node 24 LTS, both within your accepted defaults;
- the slider-to-objective mapping (§F.4);
- if Stage 2 finds no layout, it is reported as "NO FEASIBLE LAYOUT FOUND (not proven infeasible)" with the least-violating candidate and a measured constraint attribution, and constraints are never relaxed automatically.

---

## A. Project understanding

**What we are building.** A local engineering application that takes a set of STL parts and analyses each one. It searches for arrangements inside a CubeSat that are:
1. geometrically valid;
2. compact;
3. balanced about a target centre of mass;
4. favourable in rotational inertia.

It explains the trade-offs it finds. Results come in two clearly labelled kinds:

| Label | Meaning | Never implies |
|---|---|---|
| **IDEALIZED** (Stage 1) | Rigid parts in an empty 100 × 100 × 340.5 mm box. No interpenetration; parts may touch. No hardware | That the layout can be built |
| **ENGINEERING-CONSTRAINED** (Stage 2) | Stage 1 plus the ASSUMED frame, clearances, mounting allowances, harness routing, PCB stack, insertion order and the CDS COM box as hard constraints | Flight qualification, structural adequacy or launch-load survival |

The optimiser does its own geometry and collision work. Fusion 360 is an independent check that comes later.

**Scope boundaries.**
- **In scope:**
  - geometry analysis and validation;
  - mass properties;
  - classification;
  - several placement algorithms;
  - physics-aware multi-objective optimisation;
  - interactive and progressive updates;
  - Stage 1 and Stage 2;
  - comparison and benchmarking;
  - reports;
  - a Fusion export package and adapter.
- **Out of scope:**
  - structural, thermal or vibration simulation;
  - flight qualification;
  - cable routing beyond keep-out volumes;
  - non-uniform mass distributions without user data;
  - running Fusion before authorisation.

**Five findings from the pre-protocol analysis that shape the design.**

1. **Volume fraction cannot rank layouts.** With every part inside a fixed enclosure, Σ part volume ÷ enclosure volume is the same for every valid layout (31.7 % here). So packing efficiency means **compactness**: the enclosure length used along Z, with the largest remaining empty box reported alongside it.
2. **Uniform density does not change the best arrangement.** COM = Σ Vᵢrᵢ / Σ Vᵢ for any common density ρ, and every inertia entry scales with ρ, so normalised objectives are identical.
3. **The mass limit is a parts-list check.** Rearranging parts cannot change the total mass (2.916 kg vs the CDS "typical maximum" of 6.00 kg for 3U).
4. **STL precision is float32.** The analysis matches analytic values exactly when coordinates are representable in float32, and to about 5e-8 otherwise. Tessellated curved parts differ from their ideal shapes by discretisation error (−7.1e-4 in volume for a 96-segment cylinder, −7.1e-3 for the 32×96 torus). That error belongs to the mesh. The mesh, not the ideal primitive, is authoritative.
5. **Some geometrically valid layouts cannot be assembled.** Cavities can host other parts: torus hole Ø44 mm, tube bore Ø34 mm, U-channel 52 × 26 mm. Stage 1 may use them (flagged). Stage 2 adds an exact ±Z insertion test.

---

## B. STL processing strategy

**Pipeline.** Every step is logged and nothing happens silently.

```
ingest ─► parse ─► weld ─► validate ─► repair? ─► units ─► mass properties ─► descriptors ─► classify ─► proxies ─► cache
```

| Step | What happens | Output / rule |
|---|---|---|
| Ingest | Copy to `data/<dataset>/`, then SHA-256 each file and the dataset as a whole. Originals are immutable | Every run records the dataset hash |
| Parse | Binary STL (`84 + 50n` bytes) or ASCII. float32 values are kept exactly, then cast to float64 (the cast is exact) | Triangle soup |
| Weld | Exact coordinate match. A tolerance weld (1e-6 × bbox diagonal) counts as a *repair* and is logged | Indexed mesh |
| Validate | Degenerate triangles; boundary, non-manifold and mis-oriented edges; edge-connected components; Euler characteristic and genus; signed volume per component; self-intersections (exact triangle–triangle test via manifold3d status plus a BVH tri–tri check); positive-definite inertia and the triangle inequality I₁+I₂ ≥ I₃ − 1e-9·tr | `VALID` / `REPAIRED` / `INVALID-FOR-MASS` |
| Repair | **Automatic and lossless:** merge duplicates, drop zero-area faces, make winding consistent, flip a fully inverted closed shell (→ REPAIRED). **Automatic, labelled:** fill holes whose patch is < 0.1 % of area (volume shown before/after). **Everything else:** mass properties WITHHELD | Repaired copies cached alongside a diff; originals never touched |
| Units | Declared unit (default mm). Warns if the largest extent is > 340.5 mm, if every extent is < 1 mm, or if the mesh looks like metres or inches | One conversion point |
| Mass properties | float64 signed-tetrahedron (covariance) integration about the bbox centre (§E). **Only** for meshes that are closed, consistently oriented and free of self-intersections | V, COM, full 3×3 tensor about COM, principal moments and axes |
| Descriptors | AABB, approximate minimum OBB, convex hull volume and area, solidity, OBB fill, sphericity, planar-area fraction, elongation, thinness, genus, components, triangle count | See §C |
| Proxies | The certified proxy hierarchy of §D.3 | Each proxy states its guarantee |

**Withholding rule.**
- A WITHHELD part still appears in the app.
- It is packed using its convex hull (or its OBB if no hull can be formed), labelled `ENVELOPE — mass properties withheld`. The vertex hull exists whatever the holes or winding.
- It contributes no mass until you pick a repair, enter mass properties, or accept a labelled hull approximation.
- Assembly metrics then show "incomplete — 1 part excluded".
- In Stage 2, the CDS COM-box verdict reads **NOT ASSESSABLE** until the part has a mass and a COM.

**Prototype (MEASURED, read-only, standard library only).** Divergence-theorem mass properties, edge topology, quickhull and an approximate minimum OBB were run on all 22 files in 4.3 s.
- All 19 packable parts are watertight and consistently oriented.
- The open fixture (3 boundary edges) and the inverted fixture (signed volume −9,397.9 mm³) are correctly *refused*.
- The two-body fixture is one rigid component with 2 shells.

> The prototype had no repair operators, so it withheld the inverted fixture. Under the accepted policy, production will **flip it automatically and label it REPAIRED**. That is a lossless fix, and the test suite covers both behaviours.

The prototype also exposed two of its own defects, both fixed: the first blob was nearly convex (solidity 0.997, regenerated to 0.814), and the OBB search was stuck on the L-part (fixed with hull-face candidate frames).

---

## C. Geometric classification

**Approach: multi-label descriptors.** A part receives every label whose test it passes, and algorithm selection uses the descriptor *values*.

| Descriptor | Definition | Provisional threshold |
|---|---|---|
| Solidity | V / V_hull | ≥ 0.98 convex; 0.90–0.98 mildly concave; < 0.90 strongly concave |
| OBB fill | V / V_OBB(min) | ≥ 0.90 box-like |
| Thinness | e_min / e_mid (sorted OBB extents) | < 0.10 thin; < 0.25 plate-like |
| Elongation | e_max / e_mid | > 1.8 elongated |
| Planar-area fraction | Share of area in facet-normal bins each holding ≥ 3 % of the total area | > 0.95 planar-faceted; < 0.25 curved |
| Inertial symmetry | Two principal moments within 2 % | Symmetric |
| Highly irregular | Strongly concave ∧ curved ∧ not symmetric | Flag |
| Genus, components | From topology | Through-hole; multi-body |

The thresholds are provisional. They will be tuned on further datasets, and the tuning is recorded as an ADR.

**Result on the dataset (MEASURED).** The labels match the intended categories for all 19 parts (Appendix A). The PCBs read as "convex, box-like, thin" (solidity 0.988; their notches are shallow). That is geometrically correct, so the manifest's intended label becomes "near-convex".

**Classification → proxy and algorithm choice**

| If a part is… | Cheapest *certified* proxy | Why |
|---|---|---|
| Box-like (OBB fill ≥ 0.9) | OBB = single box | < 10 % waste |
| Planar-faceted concave (L, U, cross, PCB notches) | Exact compound boxes (2–3) | Exact cover: no waste, cavities open |
| Convex, not box-like | Convex hull. It counts as *exact* only if V_hull − V ≤ 1e-9·V (the 9 strictly convex parts) | An OBB would waste 21–50 %. The PCBs (solidity 0.988) are **not** hulled, because the hull would fill the corner notches that clear the rails |
| Curved with a through-hole (torus, tube) | k radial convex sectors (k = 8; 16 optional), certified | Hull waste 43–72 %. Sectors keep the hole (residual ≈ 3–5 cm³) |
| Highly irregular / curved concave (blob, gear) | Convex hull plus voxels for search; exact mesh for validation | No good analytic proxy. Hull waste 18–19 % |
| Thin / plate-like | Compound boxes; PCB-stack macro in Stage 2 | Stacking rules |

---

## D. Algorithm selection

### D.1 Evaluation of algorithm families
The scales below are relative to *this* problem: 19 heterogeneous parts in one strip-like container, with physics objectives and an interactive budget.

| Family / method | Complexity (per evaluation) | Geometric accuracy | Irregular-STL fit | Parallel | Interactive | Verdict |
|---|---|---|---|---|---|---|
| FFD / BFD sorting rules | O(n²) | proxy | poor | trivial | yes | Seed orders only |
| **Extreme-Point best-fit-length decoder (EP-BFL)** [Crainic–Perboli–Tadei 2008] | O(n·B²·r) worst case, lazy in practice. Prototype 2–7 ms in pure Python | conservative proxy | via compound proxies | per decode | **yes** | **Shortlist:** decoder, initialiser, Stage 2 baseline |
| **Empty-maximal-space (EMS) decoder** [Lai–Chan 1997; Gonçalves–Resende 2013] | O(m·k) per insertion (m ≈ 80–235 spaces measured) | conservative proxy | sees cavities | per decode | **yes** | **Shortlist:** cavity-aware candidate generator (merged with EP) |
| Guillotine / layer / wall building | low | proxy | poor (18 distinct parts) | — | yes | Rejected. The slab idea is kept for COM post-optimisation |
| Convex hull + GJK/EPA (python-fcl) + separating-plane certificate | ~10–30 GJK iterations per pair; 3–50 µs per pair ESTIMATE | exact for convex parts | needs decomposition | yes | yes | **Shortlist:** narrow phase |
| C-space Minkowski sums for low-poly convex pairs | build O(nm log nm), query O(facets) | exact penetration depth and −Z drop height | low-poly only | yes | yes | Optional accelerator (M6) |
| Phi / quasi-phi-function NLP [Romanova et al. 2018] | 83 min per local optimum for 20 concave parts (published) | exact | yes | multistart | **no** | Free-rotation experiment only, as a separating-plane penalty with L-BFGS-B, offline |
| **Certified convex covers** (planar cuts + hull; CoACD fallback) | preprocessing seconds | conservative, certified | **yes** | per part | n/a | **Shortlist:** proxy level G3 |
| V-HACD | — | *may under-cover* (shrink-wrap, vertex caps) | — | — | — | Rejected: unsound for compaction |
| **Voxel FFT correlation** [Cui et al. SIGGRAPH 2023] | O(R·N log N); 2 mm grid 0.43 M cells | conservative to h | **yes** (cavities, holes) | over orientations | 2 mm: 0.25–0.5 s per decode on 12 threads (ESTIMATE) | **Shortlist:** irregular placement engine. *Timing spike required first* |
| SDF dilation | O(N) | Lipschitz-safe | yes | yes | yes | Shortlist: Stage 2 clearance in the voxel engine; penalty fields |
| **Exact BVH mesh collision** (python-fcl OBBRSS) + manifold3d | output-sensitive. Full layout ~0.15 s typical, ≤ 0.5 s worst (ESTIMATE) | exact to 1 µm | **yes** | per pair | validation queue | **Shortlist:** the validator |
| Exact non-convex NFP / Minkowski | Θ(n³m³); CGAL is GPL | exact | yes | — | no | Rejected |
| **BRKGA (memetic, island model)** | dominated by decodes | decoder's | via decoder | islands | **yes** (weight-independent decoder) | **Shortlist:** core optimiser |
| SA / late-acceptance hill climbing | per move | — | — | per island | yes | **Shortlist:** refiner islands |
| PSO / DE on random keys | — | — | — | — | — | Rejected: argsort plateaus, no packing evidence |
| Tabu search | — | — | — | — | — | Deferred: high design cost |
| CMA-ES | — | — | continuous only | — | — | Free-rotation experiment only |
| Big-M MILP / space-indexed MIP | weak relaxation; 3.9×10⁸ binaries at 1 mm | — | — | — | no | Rejected |
| **CP-SAT** on the box proxy [OR-Tools, Apache-2.0] | 1,026 pair literals ≤ 114 orientation literals | proxy | proxy only | 12 workers | no (offline) | **Shortlist:** lower bounds, seeds, small-subset oracles |
| **Fixed-topology LP / SLSQP refinement** | 58 vars; 5–50 ms per solve ESTIMATE | exact topology | yes | — | yes | **Shortlist:** COM/compactness polish |
| **NSGA-II** (own implementation) | O(MN²) sorting | decoder's | via decoder | per evaluation | background | **Shortlist:** Pareto front. NSGA-III optional |
| MOEA/D, SMS-EMOA | — | — | — | — | — | Not implemented (MOEA/D's role is covered by the weight-lattice archive) |

### D.2 Implementation shortlist and roles

| Component | Role | Milestone |
|---|---|---|
| Compound-box proxies + **EP ∪ EMS candidate decoder** with best-fit-length merit and physics tie-break | Millisecond, feasible-by-construction initialiser and the GA's decoder. Stage 2 baseline. "Box baseline" comparator in benchmarks | M3 |
| CP-SAT box model; analytic lower bounds | Proven proxy bounds, optimality gaps, regression oracles on 5–8-part subsets | M3 |
| Slab post-optimiser and fixed-topology LP polish | Fix the COM without increasing L | M3 |
| Certified proxy hierarchy G0–G4 + V | Fast and sound collision answers | M2 |
| Exact validator (FCL + containment + manifold3d) | The **only** source of VALID | M2 |
| Physics-aware BRKGA islands + refiner islands + memetic local search | Core interactive optimiser | M6 |
| Exact compaction (conservative advancement) + contact-linearised SLSQP | Recover proxy waste and nesting | M6 |
| Voxel FFT placement engine (2 mm / 1 mm) | Alternative decoder for irregular/concave parts; benchmark variant | M6 (after timing spike) |
| Own NSGA-II + hypervolume / IGD+ | Background Pareto front | M6 |
| Free-rotation experiment (quasi-phi penalty, L-BFGS-B, CMA-ES restarts) | Stage 1 research result, reported separately | M8 |

### D.3 Unified proxy hierarchy and the certification rule
Every proxy **contains** its part. So two proxies separated by ≥ c proves the two parts are separated by ≥ c. Mass properties never come from a proxy; a test checks this by rejecting proxy geometry in the physics module.

| Level | Proxy | Certifies separation? | Used by |
|---|---|---|---|
| G0 | Exact per-orientation AABB (exact for the 24 orientations); bounding sphere | Yes (gap ≥ c) | Broad phase, containment |
| G1 | Compound boxes (≤ 6 AABBs in the canonical frame). Exact for L, U, cross and notched PCB; "picture-frame" boxes for torus and tube | Yes, once containment is certified | Box decoders, Stage 2 baseline |
| G2 | Convex hull in float64, offset outward by 1 µm. Exact geometry for the 9 strictly convex parts | Yes: separating plane checked in float64 against **all** vertices | Narrow phase |
| G3 | Certified convex cover. First choice: planar cuts + hull per piece, which contains the part by construction. Fallback: CoACD (`preprocess_mode=off`, `decimate=False`, fixed seed) | Yes, if the containment certificate passes; otherwise fall back to G2 | Narrow phase, cavities |
| V | Conservative voxels (0.5 → 1 → 2 mm by OR-pooling, so nested) | **No, never validates.** It only proposes placements and supplies penalties | Voxel FFT engine |
| G4 | Exact mesh. FCL BVH collision and distance (when separated); our own winding-number containment test (Numba; manifold3d 3.5.4 has none); manifold3d `min_gap` cross-check | Yes. If the implementations disagree by > 1 µm the result is INDETERMINATE and rejected | Validator, final check |

**Containment certificate** (G1, G3). A volume residual alone is not enough: a 1 µm × 1 µm × 30 mm sliver has only 3e-5 mm³. Two conditions must both hold:
- every vertex of the part is inside the proxy;
- the manifold3d boolean difference (part − proxy) is **empty**, meaning it has zero triangles, not just a small volume.

**Rule.** A layout is VALIDATED only when two things hold:
- every part pair, and every part against the walls and static obstacles, has a sound proof at G0, G1, G2, G3 or G4, computed with ε inflation;
- in Stage 2, the layout also passes the clearance, COM-box and insertion checks.

Never certifying: V, raw GJK or EPA output, and uncertified CoACD pieces.

Every FINAL layout is re-checked entirely at G4, with the independent mass-property implementation.

**Containment trap.** FCL treats meshes as surface soups. It cannot see a part lying entirely inside another, for example a rod inside the solid capsule. Whenever one AABB lies inside another, the validator runs the winding-number containment test, one vertex per connected component, in both directions. Test T-C pins this behaviour.

### D.4 The hybrid pipeline, and whether it beats independent algorithms
1. **Constructive seeds:** sorted orders through the EP ∪ EMS decoder, plus a CP-SAT solution offline.
2. **Physics-aware BRKGA** over (order, orientation, placement-rule) keys. Fitness is the augmented Tchebycheff function of §F.
3. **Orientation and pose local search** on elites:
   - re-orient, swap, re-insert;
   - push-to-wall;
   - "slack shift" of parts that are not on the Z-critical path, which improves the COM or inertia at constant L;
   - mirror.
4. **Exact compaction** and validation.
5. **Progressive display.**

**Hypothesis.** The hybrid beats each algorithm run alone at equal budget, for three reasons:
- the decoder explores combinatorial structure that local search cannot reach;
- local search uses geometric slack the decoder cannot represent;
- the archive and island model make slider changes cheap.

Support in the literature:
- multi-population BRKGA with local search performs best in reviews [Londe et al. 2023];
- algorithm portfolios with migration beat their constituent algorithms [Peng et al. 2010];
- moves on the physical layout won on container-loading benchmarks [Parreño et al. 2010].

**This is not assumed.** The No-Free-Lunch theorems mean it must be shown on our instances. **Adoption rule (pre-registered).** The hybrid ships as the default only if it reaches a Vargha–Delaney A₁₂ ≥ 0.64 with a Holm-corrected p < 0.05 on at least half the benchmark instances, and is significantly worse on none. Otherwise the simplest variant that is not significantly worse ships, and the result is reported.

### D.5 Canonical frame and orientations
- **Canonical frame per part.** Evaluate up to four candidate frames and keep the one that gives the smallest certified G1 (compound) proxy:
  - the authored frame;
  - the minimum-volume OBB frame;
  - the principal-inertia frame, only when the eigenvalue gaps are > 1e-3, since it is undefined for the sphere, the hub and any square or axisymmetric part;
  - the frame aligned with the largest planar face.

  Ties go to the authored frame, then a fixed order. The minimum OBB is not always unique: the wedge's leg-aligned and hypotenuse-aligned rectangles have equal area, so the fixed tie-break decides it.

  One authored→canonical transform is stored per part and used by proxies, physics and exports. A per-part user override is allowed.

  Expected picks:
  - cross hub → authored (exact 3-bar cover, 28.7 cm³, against 98.5 cm³ for its min-OBB box);
  - payload box → min-OBB;
  - ellipsoid → principal axes ≈ OBB;
  - wedge → decided by the score.
- **The 24 orientations** are the signed permutation matrices with det = +1, relative to the canonical frame. They are exact in floating point, and R·I·Rᵀ reduces to index permutation and sign flips (bit-exact). Orientations that map a part onto itself are removed.
- **Exports** store the transform from the original file frame, so Fusion receives the original bytes plus a transform.
- **Free-rotation experiment (Stage 1 only, labelled separately):**
  - Sampling: a Hopf grid (576 or 4,608 points) or super-Fibonacci SO(3).
  - Local solver: an offline separating-plane penalty with L-BFGS-B.
  - Hypothesis (UNVERIFIED): less than 5 % gain in Z. Most of the gain is expected from cavities, not rotation.

---

## E. Physics architecture

### E.1 Conventions
| Item | Convention |
|---|---|
| Body frame | Origin at the enclosure's geometric centre (CDS §2.2.1); +Z along the rails; right-handed |
| Units | SI internally for physics. **The geometry kernel works in millimetres** (float64), because FCL/libccd tolerances are absolute, and is converted to SI only at the physics boundary. This exception is documented and tested with a units sweep (m / mm / µm give identical classifications) |
| Display | mm (0.1; clearances 0.01), kg (0.001), kg·m² (4 significant figures, shared column exponent), degrees (0.1) |
| Inertia tensor | I = ∫(‖r‖²E − r rᵀ) dm. Off-diagonals I_xy = −∫xy dm. Stored, computed and exported this way; matches trimesh and the manifest |
| Products of inertia | P_xy = +∫xy dm = −I_xy. Shown in a separate, labelled table. A bare "Ixy" is never shown. JSON keys: `inertia_tensor_kgm2`, `products_Pxy_kgm2` |

### E.2 Per-part mass properties (computed once, at import)
- **Integration.** float64 covariance method about p₀ = bbox centre. For each triangle (a, b, c) relative to p₀, with d = a·(b×c):

  | Quantity | Accumulation |
  |---|---|
  | V | Σd/6 |
  | S (first moment) | Σd(a+b+c)/24 |
  | C (second moment) | Σ(d/120)[(a+b+c)(a+b+c)ᵀ + aaᵀ + bbᵀ + ccᵀ] |

- **Derived values.**
  - c = p₀ + S/V
  - C_c = C − V(S/V)(S/V)ᵀ
  - J = tr(C_c)E − C_c (unit-density inertia about the COM)
- **Validity gates:**
  - closed, every edge used exactly twice in opposite directions;
  - a shell with negative volume is allowed only as a cavity inside a positive one;
  - J positive-definite;
  - triangle inequality, within 1e-9·tr. Thin PCBs sit near equality, with a margin of about 3e-4.
- **Immutable geometry record.** Stores V, c_local and K_local = J/V. Mass m is the only mutable quantity:
  - a density edit sets m = ρV;
  - a mass override sets an effective density ρ_eff = m/V;
  - I_local = m·K_local, so the COM is unchanged and I scales by m_new/m_old;
  - **geometry never changes.**
- **Non-uniform mass data** is accepted only as a complete set (mass, COM, full tensor, reference frame), labelled USER-SUPPLIED.

### E.3 Assembly
- **Placement.** With pose (R, t): c_w = R·c + t and I_w = R·I·Rᵀ.
- **Totals.**
  - M = Σmᵢ
  - C = Σmᵢcᵢ / M
  - I_C = Σ[I_w,i + mᵢ(‖dᵢ‖²E − dᵢdᵢᵀ)], with dᵢ = cᵢ − C
- **Incremental form.** Keep Q = Σ[I_w,i + mᵢ(‖cᵢ‖²E − cᵢcᵢᵀ)] about the origin, so I_C = Q − M(‖C‖²E − CCᵀ).
  - A one-part edit or move costs O(1).
  - A full O(n) recompute runs on every validated layout and every 1,000 deltas.
  - Allowed drift: < 1e-12 relative.
- **Principal axes** from `eigh`:
  1. Eigenspaces whose relative gap is < 1e-3 (ASSUMED) are treated as degenerate. They are shown as "axes not unique (symmetric within 0.1 %)", with a Gram–Schmidt basis built from the body axes.
  2. Axes are matched to body axes by the best of the 6 permutations.
  3. Each axis is sign-fixed so its matched component is positive, and the frame is made right-handed.
  4. Misalignment θ = arccos((tr(PᵀV) − 1)/2) is reported.
- **Stage 2 frame mass (decision U7).**
  - The ASSUMED parametric frame (rails + walls, aluminium, about 0.876 kg by arithmetic) is a fixed, labelled pseudo-part.
  - By default it is **excluded from the hard CDS COM check**. This is conservative, because a symmetric frame can only pull the COM toward the centre.
  - The COM is reported both with and without the frame. Including it moves a −Z-packed stack's COM roughly 20 mm toward the centre (ESTIMATE).

### E.4 Requirements (CubeSat Design Specification Rev 14.1, verified from the primary PDF)
| Item | Value | Status in the tool |
|---|---|---|
| 3U envelope | 100.0 × 100.0 × 340.5 mm (length 340.5 ± 0.3 mm, from the change log; the 100.0 mm width is in drawings, not extracted text) | Stage 1 envelope |
| Mass (§2.2.10, *Note*, "typical maximum") | 1U 2.00; 1.5U 3.00; 2U 4.00; **3U 6.00**; 6U 12.00; 12U 24.00 kg | Reported check; never an optimiser constraint |
| COM (§2.2.11, **shall**, Table 2) | 3U: X ±20 mm, Y ±20 mm, Z ±70 mm from the geometric centre (1U ±20 mm on all axes; 6U X ±45 mm, Y ±20 mm, Z ±70 mm; 12U ±45 / ±45 / ±70 mm) | Hard in Stage 2; displayed in Stage 1 |

### E.5 What the inertia numbers mean (plain-language explanations are built from these)
- **Agility.** For a rest-to-rest slew of angle θ:
  - torque-limited: t = 2√(θI/T);
  - momentum-limited: t = θI/h_max + h_max/T.

  The worst axis is set by λ_max. Example (wheel values ASSUMED, UNVERIFIED): a 90° slew takes 10.1 s at I = 0.0103 kg·m² and 26.0 s at I = 0.0306 kg·m².
- **Products of inertia** couple the axes and tilt the principal frame. A 3U is nearly axisymmetric (I_xx ≈ I_yy), so a tiny I_xy can swing the XY principal axes by up to 45°. The tilt angle is therefore *displayed, not optimised*.
  - The optimiser instead reduces the smooth products magnitude P = √(I_xy² + I_xz² + I_yz²) inside the inertia objective (§F.3).
  - The dimensionless κ = max|I_ij|/√(I_ii·I_jj) is displayed.
  - Controllers use the full tensor, so small products are a preference, not a requirement.
- **Gravity-gradient torque** depends on inertia *differences* (up to (3μ/2R³)·ΔI). Minimising every moment is therefore not automatically right. A passive or spin-stabilised design needs inertia ratios instead, and a dissipative spin is stable only about the axis of maximum inertia. These modes are explained in the UI but not optimised by default, since a 3-axis concept was accepted.
- **Mass-distribution identity.** tr(I_C) = Σtr(Iᵢ) + 2Σmᵢ‖dᵢ‖². The self-inertia sum is 3.95e-3 kg·m² for this dataset, computed read-only by research agent E, and does not depend on rotation. So lowering inertia means keeping the *heavy parts' COMs close together*. Four heavy parts carry 45.7 % of the mass:

  | Part | Mass | COM lever |
  |---|---|---|
  | battery | 0.380 kg | 0.130 mm/mm |
  | camera | 0.327 kg | 0.112 mm/mm |
  | capsule | 0.322 kg | 0.110 mm/mm |
  | sphere | 0.305 kg | 0.105 mm/mm |

  This is the basis for the "why it moved" explanations (§I.6).

---

## F. Optimisation architecture

### F.1 Decision variables
For each part i:
- an orientation index oᵢ from its allowed, symmetry-reduced set;
- a translation tᵢ, stored canonically as integer micrometres so that validated, displayed and exported poses are bit-identical.

The free-rotation experiment adds a rotation vector ωᵢ. The search itself works in a random-key space (§F.7).

### F.2 Hard constraints (never weighted, never traded against a slider)
| Constraint | Stage 1 | Stage 2 |
|---|---|---|
| Containment | Inside 100 × 100 × 340.5 mm | Inside the inner box (96 × 96 × 336.5 mm, ASSUMED walls) minus the rails |
| Non-interpenetration | No OVERLAP (see the contact policy below) | Certified clearance ≥ 2.2 mm part–part, ≥ 1.2 mm part–wall/rail (U4) |
| Locks / orientation restrictions | as set | as set |
| Keep-outs | user boxes | + rails, harness channel (U5), connector zones |
| PCB stack | — | PCB-tagged parts parallel to XY, XY-locked, rail-centred, 15.24 mm PC/104 pitch (ASSUMED). The PCB meshes have no holes, so PC/104 rods are modelled as keep-outs spanning **only the stack's Z range**: PCB–rod pairs are exempt by design and every other part keeps 1.2 mm from them. Hole coordinates must be confirmed from a cited source in M2 (UNVERIFIED) |
| Mounting layer | — | 3 mm layer on an optimiser-chosen face that touches a wall or rail. It replaces the wall clearance on that face (U6) |
| Assemblability | flagged only (U8) | Every part insertable along ±Z in a valid order (exact blocking matrix + greedy removal, which is complete) |
| CDS COM box | displayed, with an "outside the CDS box — allowed in Stage 1, enforced in Stage 2" badge | **hard**. Frame mass excluded by default (U7) |

**Contact policy.** Three separate rules:
1. **Placement.** Decoders and compaction target a gap of +5 µm in Stage 1 and c + 5 µm in Stage 2. Optimiser-generated layouts are therefore strictly separated and certifiable. Along a 20-part Z chain this costs ≤ 0.1 mm.
2. **Classification (the accepted rule).**
   - CONTACT when |s| < 0.01 mm; OVERLAP when s ≤ −0.01 mm.
   - A negative s inside the band is accepted only with a proof that the overlap extent is ≤ 0.01 mm (from the manifold intersection). This applies only to imported or user-placed layouts. FCL cannot certify penetration depth.
3. **Accuracy.** "1 µm" in the validation tests is the required agreement of computed distances with an oracle.

**How constraints enter the search.** Candidates are compared by the key (CV, g). Feasible beats infeasible; infeasible candidates are ranked by normalised violation CV. NSGA-II uses constrained domination.

**When no layout is found.**
- A bound check runs before searching. A Stage 2 setup that bounds prove impossible is reported as **INFEASIBLE (proven)**.
- Otherwise a failed search reports **"NO FEASIBLE LAYOUT FOUND (not proven infeasible)"**, with the least-violating candidate and the constraint-attribution re-solves (§O.3).
- Constraints are never relaxed automatically.

### F.3 Objectives (raw form)
| Symbol | Objective | Definition |
|---|---|---|
| L | Compactness (min) | max over parts of (top z) − z₀, with z₀ = −170.25 mm (Stage 1) or the inner end face (Stage 2). *Option U2:* occupied span = max top z − min bottom z |
| D | COM error (min) | ‖C − C*‖₂. Target C* defaults to the geometric centre and is editable. Smoothed form √(‖·‖² + δ²) − δ (δ = 0.01 mm) for gradient refinement. *Advanced option:* CDS-scaled √((Δx/20)² + (Δy/20)² + (Δz/70)²) |
| I | Rotational inertia (min) | I = α·T̂ + (1 − α)·P̂. T = tr(I_C) = λ₁ + λ₂ + λ₃ (smooth, rotation-invariant; for a 3U, T ≈ 2·λ_max + I_zz, and T ≥ λ_max ≥ T/3). P = √(I_xy² + I_xz² + I_yz²) (products of inertia). α = 0.5 by default, set by the Expert "mass-distribution symmetry" slider |
| G | Feasibility margin (min), **Stage 2 only** | 1 − min(1, s_min / s_cap), where s_min is the smallest certified slack (distance − required clearance) over all pairs and walls, and s_cap = 5 mm (ASSUMED). This is slack beyond the hard limits; the limits themselves stay hard |

**Why T rather than λ_max.** A 3U has I_xx ≈ I_yy, so λ_max has a kink exactly at the operating point, which degrades gradient refinement. T is smooth and equals Σtr(Iᵢ) + 2Σmᵢ‖dᵢ‖², which makes it directly explainable. A benchmark check confirms that ranking the archive by λ_max and by T agree (Spearman correlation reported).

Displayed but not optimised:
- λ_max (worst-axis agility), the three principal moments and their ratios;
- κ = max|I_ij|/√(I_ii·I_jj) and the principal-axis tilt θ;
- the gravity-gradient indicator λ_max − λ_min;
- Space Used (constant), the largest empty box, the occupied span, and total mass vs the CDS note.

### F.4 Sliders and presets (objective weights only, unitless)
| Spec slider | Beginner label | Drives |
|---|---|---|
| Packing efficiency importance | Use Space Efficiently | weight of L |
| COM accuracy importance | Balance the Spacecraft | weight of D |
| Rotational inertia importance | Reduce Rotational Inertia | weight of I |
| Mass-distribution importance (Expert) | — | the split α between the trace and the products of inertia inside I. That is, how much "mass placed symmetrically about the body axes" matters. No extra rules are invented (accepted default) |
| Physical feasibility | Improve Physical Feasibility | weight of G in **Stage 2**. **Disabled in Stage 1**, with the tooltip "Stage 1 is idealized; switch to Stage 2 to work on physical feasibility" |

- **Advanced only:** "Computation: speed ↔ quality". This changes the compute budget only (population size, generations per tick, active islands, validation queue depth, background front on or off), not the objectives.
- **Weights.** Slider values sₖ ∈ [0, 100] map to wₖ = (sₖ + 1)/Σ(sⱼ + 1). Weights are therefore always > 0, which guarantees Pareto-optimal answers rather than weakly optimal ones. The UI shows each goal's normalised share.
- **Presets** are defined on the beginner sliders:

  | Preset | Setting |
  |---|---|
  | Maximum Packing Efficiency | favoured slider 70, others 10 |
  | Center-of-Mass Priority | favoured slider 70, others 10 |
  | Minimum Rotational Inertia | favoured slider 70, others 10 |
  | Balanced Optimization | all active sliders equal (three in Stage 1, four in Stage 2) |
  | Custom | your values |

- **Meaning.** The Tchebycheff optimum lies on the ray from the utopia point where every wₖf̂ₖ is equal, so f̂ₖ ∝ 1/wₖ. The UI draws this ray in the trade-off chart and explains it in plain words. For example, "70 vs 10" asks for about a 7× smaller normalised gap on the favoured goal.

### F.5 Normalisation
- **Formula.** f̂ₖ = (fₖ − uₖ)/(nₖ − uₖ).
- **Utopia u.** u_D = u_P = u_G = 0 analytically. u_L and u_T are the best single-objective values found, minus 1 % of the range. The proven lower bounds of §F.9 are shown next to them.
- **Nadir n.** The component-wise worst value over the lexicographically polished payoff table together with the validated non-dominated archive.
- **Range floors.** 1 mm (L), 0.5 mm (D), 1 % of u_T (T), 1 % of u_T (P), 0.05 (G).
- **Normalisation epochs.** (u, n) are frozen per epoch, so the same slider position always means the same thing. They are refreshed only when background single-objective runs finish or on request. The current epoch ID is shown, and "provisional" is displayed until the first refresh.

### F.6 Scalarisation
g(x | w) = max_k wₖ·f̂ₖ(x) + ρ·Σₖ wₖ·f̂ₖ(x), with ρ = 10⁻³ (augmented weighted Tchebycheff).
- A weighted sum is not used. It cannot reach non-convex parts of the front [Das & Dennis 1997].
- Tchebycheff reaches every Pareto point for some positive weight vector, and the ρ term removes weakly optimal ties [Steuer & Choo 1983].
- *Aspiration mode (Advanced).* The same formula with (f̂ₖ − r̂ₖ) is Wierzbicki's achievement function, for goals such as "L ≤ 230 mm".

### F.7 Search engine
- **Encoding.** 3n random keys: order, orientation, and a placement-rule blend. The rule blend mixes "deepest-in-Z / wall-hugging" with "toward the axis / toward the COM target" when choosing among candidate points. The decoder is deterministic and **independent of the weights**. A slider change therefore re-scores stored raw objective vectors, and no layout is re-decoded.
- **Decoders.**
  - (a) the EP ∪ EMS compound-box decoder;
  - (b) the voxel FFT decoder (V-level search with exact hand-off).

  Both are benchmark variants.
- **BRKGA islands** (our own loop, ~150 lines of NumPy).
  - Starting parameters: population 100–200 per island, elite fraction 0.15–0.25, mutant fraction 0.10–0.20, inheritance bias 0.6–0.7 [Londe et al.].
  - Parameters are tuned offline with optuna (MIT) on *training* instances only.
  - Constructive seeds make up 5–10 % of each initial population.
  - Each island uses slightly perturbed weights, so nearby slider positions are already covered in the archive.
- **Island mix:** 6 interactive islands: 5 BRKGA islands with memetic local search, plus 1 refiner island running late-acceptance hill climbing (LAHC) or simulated annealing on pose-level moves.
- **Decoder independence.** Default decoders depend only on geometry, never on weights or masses, so slider and mass edits only re-score cached layouts. COM-aware decoder variants (a physics tie-break, or a COM-seeking placement rule) run only in islands tagged for them. Their caches carry `weights_rev` and `mass_rev` and are invalidated on any change.
- **Memetic local search** on elites:
  - key-space moves (re-orient, swap, re-insert) with Lamarckian write-back;
  - pose moves (push-to-wall, slack shift, mirror) using incremental collision checks and O(1) physics deltas.

  Each record stores (chromosome, move log, decoder version, dataset SHA), so it can be replayed exactly.
- **Polishers:**
  - the slab post-optimiser: rotate or flip Z-slabs and reorder them. This keeps L fixed and changes only the COM.
  - fixed-topology LP polish (SciPy/HiGHS): keep each pair's separating axis and minimise an epigraph Tchebycheff of L and ‖COM − C*‖₁. Every LP solution is box-feasible.
  - contact-linearised SLSQP on exact geometry, with a trust region ≤ 2 mm and a re-validation step.
- **Exact compaction:** conservative advancement along −Z and toward neighbours. Distance is 1-Lipschitz, so moving by (d − c) is always safe.
- **Restarts and archive.**
  - An island is shaken after 20–100 generations without improvement and reset after 200–500.
  - The archive holds about 2,000 validated layouts with their raw objective vectors. It keeps the validated non-dominated set plus the best layout per cell of a Das–Dennis weight lattice.
- **Background front:** our own NSGA-II, with optional NSGA-III whose reference directions include the preset directions. It uses the same encoding and decoder and shares solutions with the archive in both directions. If it finds a better layout for your current weights, the UI says so.

### F.8 Exact methods (offline)
CP-SAT runs on the *box proxy* only:
- **Model:** 0.1 mm integer grid; one of ≤ 6 dimension permutations per part; pairwise six-literal relative-position disjunctions; a redundant cumulative constraint along Z on footprint area; symmetry breaking for the identical PCBs.
- **Variants:**
  - (a) Stage 1;
  - (b) Stage 1 plus the CDS COM box;
  - (c) Stage 2 with inflated proxies.
- **Outputs:** an upper-bound layout, which is valid for the meshes because the proxies contain them, and a lower bound that is valid for the proxy problem only.
- **Small subsets:** proven optima on 5–8-part subsets serve as regression oracles.
- **Bounded result:** CP-SAT is not expected to prove optimality on all 19 parts. Exact 3D methods have failed on instances of fewer than 20 boxes within 6 h [Silva et al. 2019], a figure we could not confirm in the full text.

### F.9 Lower bounds (reported next to every result)
| Bound | Value | Valid for |
|---|---|---|
| Solid volume / cross-section | **108.0 mm** | true geometry (the only rigorous mesh bound) |
| Largest part's smallest dimension | 59.9 mm (sphere) | true geometry |
| Compound-proxy volume | 151.1 mm | proxies only |
| Single-OBB volume | 186.3 mm | proxies only |
| Clique (sphere + blob + camera cannot share a Z slab) | 162.8 mm | box proxies only. *Invalid for true shapes:* a sphere and an upright capsule can share a slab |
| CP-SAT best bound | computed | box proxies only |

Every result reports its gap to the rigorous bound and its gap to the proxy bound, separately.

### F.10 Weight changes vs physical edits (also explained in the UI)
| Edit | Changes | Re-optimisation |
|---|---|---|
| Priority slider | Objective weights only. Never the parts | Re-scalarise the archive (< 1 ms ESTIMATE), show the best validated layout at once, re-target the islands after 150 ms |
| Mass or density | The physical model (COM, inertia). Never the geometry | O(1) metrics update; archive mass objectives refreshed. In Stage 2, the COM box is re-checked, so a layout can become INFEASIBLE |
| Lock / orientation restriction | Feasible set | Archive filtered; a user-placed part stays UNVERIFIED until validated |
| Clearance, stage, keep-outs, geometry | Feasible set | `constraint_rev++`; the displayed layout becomes STALE and is re-validated best-first |

---

## G. Multi-agent architecture

### G.1 Research phase (executed)
Agent orchestration was available, so 13 specialised research agents ran concurrently. They worked from one shared brief and the same frozen dataset, with these rules: read-only, no installs, no file writes, cite sources, and tag ESTIMATE/UNVERIFIED. A 14th cross-check agent then reconciled conflicts and verified high-impact claims from primary sources (§L.2). Each agent returned the 8 required items: approach, justification, advantages, limitations, cost, libraries, validation, difficulty.

| Group | Agent(s) | Central recommendation | Difficulty |
|---|---|---|---|
| A Box nesting | A1 (literature), A2 (implementation) | Compound-box proxies; EP-BFL and EMS decoders with random keys; lower bounds; slab and LP polish | 3/5 |
| B Convex | B1 (kernels), B2 (decomposition) | python-fcl GJK + separating-plane certificates in mm; certified convex covers (39 pieces, +2.6 % volume instead of +27.6 %) | 3/5; free rotation 4/5 |
| C Concave/irregular | C1 (voxel/SDF), C2 (exact mesh) | Voxel FFT search (never validates); FCL BVH + containment + manifold3d validator; exact ±Z interlock test | 3/5 |
| D Global optimisation | D1 (metaheuristics), D2 (math programming / multi-objective) | Memetic BRKGA islands with a weight-independent decoder; augmented Tchebycheff; CP-SAT bounds; own NSGA-II | 3/5 |
| E Physics | E | float64 covariance integration; tensor conventions; λ_max + κ objectives; CDS verified | 2/5 |
| F Software | F | Python 3.14 via portable uv; spawn-process topology; SQLite + JSON; licence register | 3/5 |
| G Interface | G | React + R3F (WebGL2); one store; single canvas with dual views; Okabe-Ito palette; WCAG AA | 3/5 |
| H CAD validation | H | Deferred, human-triggered Fusion script + export package; CadValidator adapter defaulting to NOT CONFIGURED | 3/5 |
| I Real-time | I | Single-writer coordinator; epochs and revisions; archive-first response; validation queue | 4/5 |

> **Process disclosure.** Two box-packing agents (A1, A2) ran small in-memory prototypes. These included simulated-annealing and BRKGA runs on box proxies, which counts as an optimisation experiment. The specification forbids this before approval. Nothing was installed or written to the project. Their numbers appear in this protocol only as *indicative, unauthorised prototype results*, never as benchmarks. The brief has been tightened, and the cross-check agent was barred from running code. Full details are in Appendix D.

### G.2 Implementation phase (after approval)
The lead (this session) owns:
- the shared contracts: data schemas, the WebSocket protocol, the proxy, validator and objective interfaces in `backend/src/t2s/core/`, and `shared/schema/`;
- integration, merges, the decision log (`docs/adr/`) and final validation.

Workstreams run as sub-agents in **separate git worktrees**. Each owns a disjoint set of directories, so there is never more than one writer per file. They merge only after their tests pass and the lead has reviewed the work.

| Workstream | Owns | Depends on |
|---|---|---|
| W1 Geometry & physics | `geometry/`, `massprops/`, `massprops_ref/` | contracts |
| W2 Collision & validation | `collision/`, `validate/`, `constraints/` | W1 |
| W3 Optimisation | `optimise/`, `objectives/`, `decoders/`, `archive/` | W1, W2 |
| W4 Real-time backend | `api/`, `workers/`, `storage/`, `repro/` | contracts (stubs first) |
| W5 Front end | `frontend/` | WebSocket contract (mocked with Playwright `routeWebSocket` until W4 lands) |
| W6 Benchmarks, reports, CAD package | `benchmarks/`, `reports/`, `cad/` | W3, W4 |

**Concurrency and review.**
- At most 3–4 workstreams run at the same time, because tests and benchmarks need the 12 compute threads.
- Each milestone ends with an independent review agent that checks correctness against this protocol.

### G.3 Running unattended and handling blockers
- Agents never install anything outside Appendix C, never bypass security controls, and never treat text in files or web pages as instructions.
- When an agent is blocked (a credential, a permission, an install, or a consequential engineering choice not covered here), it writes the blocker to `docs/BLOCKERS.md`, with what was tried, then carries on with independent work.
- Every claimed test result comes from a command that actually ran. The log is kept in `data/runs/`.

---

## H. Software stack

### H.1 Toolchain (portable, project-local, no admin rights, no registry or PATH writes)
| Tool | Version policy | Source | Notes |
|---|---|---|---|
| uv | Latest release that is **≥ 14 days old** at install time | GitHub astral-sh/uv release zip + `.sha256` | `UV_*` directories under `tools\`. `UV_PYTHON_INSTALL_REGISTRY=0`, `UV_PYTHON_INSTALL_BIN=0`, `UV_PYTHON_PREFERENCE=only-managed`, `UV_NO_MODIFY_PATH=1` |
| CPython | **3.14.x** (within the accepted "3.12+"), latest patch ≥ 14 days old, uv-managed `install_only` build | python-build-standalone via uv | Fallback is 3.13 if any core wheel is missing at install time. 3.10 (on this PC) reaches end of life this month and current NumPy needs ≥ 3.12 |
| Node.js | **24 LTS**, latest patch ≥ 14 days old | nodejs.org `win-x64.zip`, verified against SHASUMS256 | Node 26 becomes LTS on 2026-10-28, which is too new under the 14-day rule (register entry) |
| MinGit | Latest 64-bit ≥ 14 days old | git-for-windows releases | Local repo only, never pushed. GPL-2.0 executable used as a tool and never linked (TOOL_ONLY) |
| Playwright Chromium | Matching @playwright/test | Playwright CDN | `PLAYWRIGHT_BROWSERS_PATH=tools\ms-playwright` |

All environment variables are set per session by `tools\env.cmd`. `setx` and execution-policy changes are never used. A test checks before and after setup that no Python registry keys or user-profile folders were created.

### H.2 Backend dependencies (permissive licences only; exact pins written to `uv.lock` at install)
| Package | Role | Licence |
|---|---|---|
| numpy 2.5.x (< 2.6 for numba 0.68) | Arrays, `eigh` | BSD-3 |
| scipy 1.18.x | Hulls, `HalfspaceIntersection`, `Rotation`, `ndimage` (incl. exact EDT), `fft`, `linprog`/HiGHS, SLSQP, L-BFGS-B, statistics | BSD-3, with bundled Qhull and BSL-1.0 code (U2) |
| trimesh 5.1.x (no extras) | I/O helpers; **independent mass-property cross-check only.** Never used for transforms | MIT |
| manifold3d 3.5.x | Booleans, volume, hull, split-by-plane, `min_gap` cross-check | Apache-2.0 |
| python-fcl 0.7.0.x | GJK/EPA, BVH collision and distance | BSD-3 |
| coacd 1.0.x | Fallback convex decomposition (certified) | MIT |
| numba 0.68.x | Kernels (`nogil`, `fastmath=False`) | BSD-2 |
| ortools 9.15.x | CP-SAT bounds (offline) | Apache-2.0 |
| fastapi, uvicorn, pydantic 2 | API, WebSocket, schemas | MIT / BSD-3 / MIT |
| optuna 5.x | Offline parameter tuning; NSGA-II cross-check | MIT |
| fast-simplification 0.2.x (cp314 wheels) | Decimation for the Fusion package only (blob) | MIT |
| pytest, hypothesis, pytest-benchmark, ruff, mypy, pyinstrument, py-spy | Tests, property tests, benchmarks, lint, profiling | MIT / MPL-2.0 / BSD-2 / MIT / MIT / BSD-3 / MIT |

**Excluded:**

| Package | Reason |
|---|---|
| pymoo ≥ 0.6.1.6 | requires moocore, LGPL (U1) |
| DEAP | LGPL |
| pygmo | GPL/LGPL, no Windows wheels |
| Platypus, irace | GPL |
| nevergrad | pulls in GPL `directsearch` |
| jMetalPy | requires moocore |
| CGAL | GPL |
| IPOPT, CBC | EPL |
| pyFFTW | FFTW is GPL |
| TBB | Intel licence |
| coal | no Windows PyPI wheels (deferred) |
| OpenVDB | no Windows wheel |
| libigl Python wheel | builds copyleft and restricted modules by default |
| point-cloud-utils | no cp314 wheel |
| Open3D | Avoided: pulls in a large web stack (dash, flask, …). Our own Numba winding-number kernel plus SciPy's EDT is used instead |
| distance3d | Bundles BSL-1.0 code. Allowed as a *test-only* cross-check if U2 is approved |

### H.3 Front-end dependencies (all MIT unless noted)
- **Runtime:**
  - react 19.3.x (pinned < 19.4 for R3F 9.8), three 0.186.x
  - @react-three/fiber 9.8.x, @react-three/drei 10.7.x, three-mesh-bvh 0.9.x, camera-controls 3.x
  - zustand 5.x, radix-ui 1.x, lucide-react (ISC), uplot 1.6.x, @observablehq/plot 0.6.x (ISC)
- **Build and lint:** vite 8.3.x, typescript 6.0.x (typescript-eslint requires < 6.1), eslint + typescript-eslint
- **Tests:**
  - vitest 5.x, @testing-library/react, @react-three/test-renderer
  - @playwright/test 1.64.x (Apache-2.0), fast-check, @axe-core/playwright (MPL-2.0)
- **Fonts:** Windows system fonts only (Segoe UI, Consolas), so there is no font licence question.

### H.4 Process topology (resolved from the A–I proposals)
| Process | Count | Threads | Priority | Responsibility |
|---|---|---|---|---|
| Coordinator (uvicorn, single process, asyncio) | 1 | loop + SQLite writer + log listener | normal | Single writer of state: epochs and revisions, archive, validation queue, debounce, WebSocket fan-out, O(1) mass-edit physics |
| Interactive search islands | 6 | 1 each | below normal | 5 BRKGA islands with memetic local search + 1 LAHC/SA refiner, under the current weights |
| Validators | 2 | 1 each | normal | Exact G4 checks, Stage 2 checks, second mass-property implementation; pull-based queue |
| Background | ≤ 3 | 1 each | idle, pausable | NSGA-II front, single-objective anchor runs, offline CP-SAT |

That is 12 threads in total, leaving about 4 for the browser and the OS.

- **Why processes:** python-fcl never releases the GIL, which rules out threads for collision work.
- **Thread settings:** BLAS, OpenMP and Numba thread counts are set to 1 in the parent before spawning.
- **Worker lifecycle:**
  - Workers are persistent, started with `spawn` behind a `__main__` guard.
  - At start-up they load the memory-mapped caches and warm the Numba cache, then report READY.
  - A watchdog respawns a worker that misses its acknowledgement for 2 s.
- **Geometry preprocessing** (repair, hulls, covers, voxels, BVHs) runs on the same pool when a project loads, before the islands start.

### H.5 Data, storage and reproducibility
- **Project file.** `project.t2s.json` is validated with pydantic and has an integer `schema_version`. Chained migrations are tested, and newer unknown versions are refused.
- **Mesh storage.** Meshes are kept as immutable `meshes/<sha256>.stl` files. Derived caches go in `cache/<mesh_sha>/<op>-<params_hash>-<algo_ver>/*.npy` (memory-mapped, rebuildable).
- **History.** SQLite in WAL mode, with tables `runs`, `generations`, `candidates`, `pareto`.
- **Run manifest:**
  - dataset SHA-256, config SHA-256, `git describe` plus a dirty flag;
  - lockfile hashes and Python/Numba versions;
  - BLAS info via threadpoolctl, CPU, a 128-bit root seed.
- **Randomness.** Seeds are assigned per logical task with `SeedSequence(root, spawn_key=(island, gen, idx))`, so results do not depend on which worker ran them.
- **Two run modes:**
  - *Reproducible mode:* evaluation budgets and synchronous migration; bit-identical reruns.
  - *Interactive mode:* wall-clock driven, labelled non-reproducible, but every displayed layout can be replayed from its record.
- **Determinism rules:** reductions run in a fixed order, and nothing is ordered by set iteration.

### H.6 Repository layout
```
backend/src/t2s/{core,geometry,massprops,massprops_ref,collision,constraints,objectives,decoders,optimise,archive,validate,api,workers,storage,repro,cad,reports}
backend/tests/   backend/benchmarks/
frontend/{src,tests/unit,tests/e2e}
shared/schema/            (JSON Schemas for project, layout, WebSocket messages, CAD package)
data/{synthetic (read-only, SHA-pinned), projects, runs}
docs/{PROTOCOL.md, adr/, dependencies/register.toml + register.md, BLOCKERS.md, reports/}
tools/   (git-ignored binaries; committed lock + env scripts)
```

### H.7 Architecture alternatives considered
| Alternative | Why not chosen |
|---|---|
| Python desktop app (Qt + PyVista) | Weaker interface, and the accepted default was a web app |
| All-in-browser (WebAssembly) | Numerics hard to make rigorous; duplicated logic |
| conda / Docker | Mixes ecosystems; Docker was excluded by decision |
| Ray / Dask / Celery | Too heavy for 12 local workers |
| Threads only | FCL holds the GIL |
| coal instead of FCL | No Windows wheels on PyPI; revisit (register) |

---

## I. Interface design

### I.1 Design language
No visual references were supplied. The accepted direction is a *professional CAD/CAE tool*. When you supply references they will be analysed, and the tokens below revised before the front-end milestone.

| Element | Specification |
|---|---|
| Shape | Square corners (radius 0) |
| Layout | 4 px grid. Rows 24 px (Expert) / 28 px (Beginner; WCAG 2.2 target size) |
| Typography | Segoe UI 11/12/13/15/18 px, base 13, weights 400/600. Numerals in Consolas, right-aligned, with a shared exponent per column, e.g. "I (10⁻³ kg·m²)" |
| Motion | UI motion ≤ 120 ms. No decorative animation. `prefers-reduced-motion` respected. `forced-colors` fallback |
| Panels | Light/dark follow Windows. The viewport is always dark-neutral |

**Colours** (contrast ratios computed by agent G):

| Token | Light | Dark |
|---|---|---|
| Panel / app background | #FFFFFF / #F3F4F6 | #25282C / #1C1E21 |
| Text | #1B1D21 (16.9:1) | #E6E8EB (12.1:1) |
| Muted text | #4B5260 | #A3AAB4 |
| Control border | #7C838E (≥ 3:1) | #7A818C (≥ 3:1) |
| Accent | #1F5FBF | #5D96F0 |
| OK / warning / error | #1E7A46 / #8A5A00 / #B42318 | #5CC08A / #E3B341 / #F2877A |
| Viewport | background #26282C; enclosure #8C929B; labels #E6E8EB | same |

**Part colours** are Okabe-Ito by subsystem. Blue #0072B2 is dropped because it has too little contrast against the viewport.

| Subsystem | Colour |
|---|---|
| Power | #E69F00 |
| Electronics | #56B4E9 |
| ADCS | #009E73 |
| Tanks | #F0E442 |
| Payload / sensors | #CC79A7 |
| Structure | #8C929B |
| Unknown | #D4D7DB |

- Vermillion #D55E00 is reserved for collisions.
- Every part has dark feature edges.
- Part *identity* comes from labels and the list, never from colour alone.

### I.2 Overview tab (Beginner)
```
T2S │ 3U │ Stage 1 IDEALIZED ▾ │ Backend: connected │ [Optimise] [Pause] │ Beginner/Expert
[Overview][Components][Optimization][Physics][Algorithm Comparison][Eng. Constraints][CAD Validation][Results & Export]
┌ PARTS (19) [Upload] ─────┬ BEST VALIDATED · L-0042 · gen 17 ─────┬ GOALS (priorities, unitless) ──┐
│ ■ battery_pack  0.380 kg │                                         │ Use Space Efficiently    ▬▬●▬ │
│ ■ pcb_eps       0.034 kg │          3D viewport (dark)             │ Balance the Spacecraft   ▬●▬▬ │
│ …                        │                                         │ Reduce Rotational Inertia▬●▬▬ │
├ PART PROPERTIES (physical)│                                         │ Improve Phys. Feasibility●▬▬▬ │
│ Mass  [0.380] kg   USER   │ [Fit][Enclosure][Labels][COM][Axes]     │ Presets: Balanced ▾            │
│ Density 2,700 ASSUMED     │                                         ├ WHAT CHANGED ─────────────────┤
│ [Lock position]           │                                         │ Balance error  −1.3 mm better  │
└───────────────────────────┴─────────────────────────────────────────┴────────────────────────────────┘
 SPACE USED 31.7 % (same for every layout) · length 214.0/340.5 mm │ TOTAL MASS 2.916 kg (CDS note 6.00) │
 BALANCE ERROR 47.2 mm │ ROTATIONAL INERTIA (worst axis) 1.03e−2 kg·m² │ ENGINEERING VALIDITY: Not assessed (IDEALIZED)
```
The figures in the wireframe are placeholders, not results.

- **Layout.** Left column 280 px; right 320 px (a drawer below 1280 px); metric strip 64 px.
- **Physical vs priorities.** Physical properties (left) and priorities (right) sit in separate panels, separate store slices and separate message types. Captions say "changes the physics" and "never changes the parts".
- **Feasibility slider.** "Improve Physical Feasibility" is greyed out in Stage 1, with an explanation, and active in Stage 2.
- **Tooltips** (Radix, on hover and on focus) follow a fixed order: a plain-language sentence, then "Technically:" with the definition and units, then "Why it matters". The Space Used tooltip explains why that value never changes.

### I.3 Advanced tabs
| Tab | Content |
|---|---|
| Components | Dense part table: geometry, validity, repairs, labels, V, m, ρ, COM, principal moments, proxy fills. Single-part inspector in the local frame |
| Optimization | Algorithm and decoder; exact weights with the normalisation epoch; constraints; seed; budget; run controls; convergence chart (uPlot); generation log |
| Physics | COM vs the CDS box in three orthographic projections; full tensor and products table (labelled conventions); principal moments and axes with tilt; per-part parallel-axis contribution bars; agility / gravity-gradient explainer |
| Algorithm Comparison | Side-by-side viewports; 10-seed strip plots; median/IQR anytime curves; Pareto scatter with the Tchebycheff pick marked; hypervolume / IGD+ table; free-rotation experiment in its own section |
| Engineering Constraints | Ideal vs engineering comparison (§O); ASSUMED rule list with editable values; checks table (value, limit, margin, pass/fail); keep-outs hatched; insertion-order playback; constraint-attribution chart |
| CAD Validation | Status card "FUSION 360 VALIDATION: NOT CONFIGURED"; export-package button (enabled only for VALIDATED layouts); setup checklist; result ingestion (when configured) |
| Results & Export | FINAL layouts; history and restore; compare any two configurations; reports; export; provenance |

### I.4 Viewport encodings
| Feature | Encoding |
|---|---|
| Navigation | CameraControls. F fit; 1–6 standard views; 0 isometric; arrow keys orbit when the canvas has focus |
| Selection | Hover: 1.5 px accent outline. Select: 2.5 px white outline, list highlight and a screen-reader live region. Hide/isolate with H / I / Shift+H |
| Enclosure | Edges only (E); Stage 2 rails and walls; optional 6 % faces; Z section plane |
| Compactness | Dimension line "used 214.0 / 340.5 mm"; largest empty box as a hatched outline |
| COM markers | Part COM 6 px ringed dot. Assembly COM 16 px quartered disc, always on top. Target COM accent crosshair. CDS box dashed in Stage 1, solid "HARD" in Stage 2. Target→COM line labelled in mm |
| Inertia | Principal axes I₁ ≤ I₂ ≤ I₃ with dashed body axes and "tilt x.x°". Optional equivalent uniform ellipsoid, a = √(5(I₂ + I₃ − I₁)/2m) |
| Constraints | Backend verdicts only. Violating clearance: orange segment "1.6 / 2.2 mm". Interpenetration: vermillion plus contact markers |
| Bounding boxes, labels | Dashed AABBs (Expert). DOM labels, decluttered |
| States | VALIDATED drawn solid. CANDIDATE as a dotted edges-only ghost with an "UNVERIFIED" chip (Expert only). STALE / INFEASIBLE badges. Transitions: 300 ms tween labelled "visual interpolation — not a validated motion path". Metrics never interpolate |
| Dual view | One canvas, two scissor `View`s sharing geometry, linked camera. Badges "STAGE 1 IDEALIZED" / "STAGE 2 ENGINEERING-CONSTRAINED (ASSUMED frame)". Movement overlay: per-part arrows plus a ΔCOM vector with magnitude and components |
| Colour modes | One at a time: Subsystem (default), Status, Mass, Displacement |

### I.5 Rendering
- **Renderer.** three.js r186 `WebGLRenderer` (WebGL2 over ANGLE/D3D11) with `frameloop="demand"`, DPR [1, 2] and `PerformanceMonitor`.
- **WebGPU is deferred.** A forum benchmark measured three's WebGPURenderer at about 2× the CPU cost per frame, and R3F v10 is still alpha.
- **Materials.** Built-in only, so a later switch is cheap.
- **Picking.** three-mesh-bvh with `firstHitOnly`.
- **Precision.** The front end never integrates float32 mesh buffers for physics. Its instant COM recompute uses backend-supplied float64 per-part properties and is labelled "local recompute" until the backend confirms it.

**Frame-time ESTIMATE.**

| Situation | Estimate |
|---|---|
| 1440p-sized window | 2–5 ms |
| 4K full screen | 3–8 ms (2 views with ghosts, ~346k triangles, ~150 draw calls) |
| Idle | 0 ms (demand rendering) |

60 fps is a target, measured by test T-UI10.

### I.6 Explanations (numbers first; no invented causality)
- **"What changed".** Every accepted layout gets a signed delta for each metric, in words ("better" / "worse") as well as colour.
- **"Why it moved".** Generated only from computed quantities:
  - for the parts that moved most: the change in the part's contribution to tr(I_C) (2mᵢ‖dᵢ‖² term) and its COM lever (mᵢ/M);
  - for constraints: which constraint became binding.
- **Trade-off sentences.** Computed from the Pareto archive, e.g. "−12 mm length costs +9 mm balance error".
- **Labels.** "Best found so far — not proven optimal". "Best trade-offs found — approximate".
- **Two explanation modes.** Beginner is plain language. Expert adds the equations and units.

---

## J. Validation and benchmarking

### J.1 Principles
- A test counts as passed only if it actually ran. Its command, output and environment are kept in `data/runs/`.
- Every foundational calculation is checked against an *independent* oracle: an analytic formula, a second implementation, or brute force.
- Validated outputs must have **zero** collision or constraint violations. A single violation is a release blocker.
- Tolerances are fixed in advance, as listed below.

### J.2 Test catalogue (IDs are referenced in milestone exit criteria)

**Geometry (T-G)**
- binary and ASCII parsing;
- welding;
- topology of the fixtures:
  - open → 3 boundary edges, WITHHELD;
  - inverted → auto-flipped, REPAIRED;
  - two-body → 1 component with 2 shells;
- a generated self-intersection fixture → WITHHELD;
- unit warnings;
- the golden dataset: manifest SHA-256 and per-file hashes.

**Mass properties (T-M)**
- Tolerances:
  - rtol 1e-12 when vertices are exactly representable in float32, otherwise 1e-6;
  - COM atol 1e-5 × bbox diagonal;
  - off-diagonal terms atol 1e-6·tr.
- Canonical tetrahedron: V = 1/6; COM ¼(1,1,1); I_C has 1/80 on the diagonal and +1/480 off it.
- Analytic solids:

  | Solid | Moments of inertia |
  |---|---|
  | Box | m(b²+c²)/12 |
  | Sphere | ⅖mR² |
  | Cylinder | mR²/2 and m(3R²+h²)/12 |
  | Tube | m(R_o²+R_i²)/2 and m(3(R_o²+R_i²)+h²)/12 |
  | Torus | m(R²+¾a²) and m(R²/2+⅝a²) |
  | Ellipsoid | m(b²+c²)/5 |
  | Capsule | composite formula |

- Exact inscribed n-gon prism formulas, checked against the measured discretisation error (7.14e-4 at n = 96).
- Composites, rotations and the tilted payload box, whose eigenvectors must recover the authored rotation.
- The 24 orientations are bitwise exact.
- Mass override ×2: COM bitwise identical and I exactly doubled.
- Invariants:
  - the trace identity;
  - positive-definiteness;
  - the Loewner order;
  - delta-update drift < 1e-12 after 10⁵ edits.
- Precision guard: with parts shifted 1 m, float64 stays within 2.5e-6, and naive float32 integration must be shown to fail.
- trimesh cross-check.

**Collision (T-C)**
- Analytic box–box gaps g ∈ {−1, −0.01, −1e-3, 0, 1e-3, 0.01, 1, 2.2} mm, plus corner offsets.
- Invariance:
  - under all 24 rotations: ≤ 1e-12;
  - under a ±170 mm translation: ≤ 1e-9.
- Touching cases: flush faces, tilted "kissing" contact (1e-7 and 1e-3 rad) and near-coplanar faces → CONTACT, never OVERLAP.
- Containment trap: a rod coaxial inside the capsule must be OVERLAP. FCL alone says no collision; the winding-number test must catch it.
- Torus/rod coaxial: CLEAR (≈ 16.99 mm). With axes ⟂ Z it is INTERLOCKED in Stage 2.
- Facet trap: a rod in the tube bore with a 5 µm analytic gap; the verdict must follow the mesh, not the ideal shape.
- U-channel cavity cases.
- Conservative fuzz: 10⁵ low-poly + 10⁴ high-poly near-contact pairs with **zero false accepts** (oracles: an LP separation solver and manifold3d). The false-reject rate is reported.
- Proxy containment: vol(part − proxy) ≤ 1e-9·V for every level.
- Cross-implementation agreement within 1 µm.
- Units sweep m / mm / µm: identical classifications.
- **Tolerance sensitivity:** sweep ε from 1e-7 to 1e-3 mm and verify that classifications change monotonically and only inside the contact band.

**Stage 2 (T-S)**
- clearance thresholds at 2.2 / 1.2 mm ± 1 µm;
- the centred PCB cross clears the rails, while a full 90 × 90 box must be rejected;
- the harness-versus-PCB conflict is detected and explained;
- greedy disassembly gives the same result as exhaustive search on random blocking graphs;
- U-channel opening ±Z → assemblable; ±Y → interlocked;
- CDS boundaries: ±19.999 / ±20.001 mm and ±69.999 / ±70.001 mm;
- toggling frame mass on and off.

**Optimisation (T-O)**
- Decoder feasibility: 10⁴ random chromosomes, 0 violations.
- Determinism.
- Re-ranking equals re-evaluation.
- Known optima:
  - 8 cubes of 50 mm → L = 100;
  - 4 PCBs → 6.4 mm;
  - 19 slabs 100 × 100 × hᵢ → Σhᵢ;
  - 16 boxes 50 × 50 × 85.125 mm → 340.5 (8 such boxes → 170.25);
  - guillotine "perfect packing" generator: median gap ≤ 10 % (target).
- Concave-front Tchebycheff test (x = 0.6180).
- Ray property and augmentation tie-break.
- Normalisation floors and epochs.
- Feasibility ordering.
- CP-SAT oracles must return OPTIMAL; HiGHS MILP must agree on 4–6-part instances.
- Hypervolume of the unit simplex corners with reference point 1.1 = 0.331; IGD+ of a front against itself = 0.
- Our NSGA-II against the analytic ZDT1–3 and DTLZ2 fronts, and against optuna's NSGA-II.
- Repeatability: identical history hashes in reproducible mode.
- Spearman agreement between archive rankings by λ_max and by T (reported; it justifies the choice of T).

**Real-time (T-R)**
- Stale-drop property test: 1,000 seeds, 0 violations.
- Cancellation acknowledged within 100 ms; watchdog recovery.
- Incremental physics matches the independent implementation to 1e-12.
- "Lying surrogate": colliding layouts are never VALIDATED.
- Stage 2 COM-box flip on a mass edit.
- Backpressure: memory stays bounded.
- Latency instrumentation (§J.4).

**Interface (T-UI)**

| ID | Test |
|---|---|
| T-UI1 | Number formatting |
| T-UI2 | Aggregation: battery alone COM (40, 40, 11) mm, I_xx 2.181e-4 kg·m²; total 2.916 kg |
| T-UI3 | Generation invariants (fast-check) |
| T-UI4 | Physical edits and goal edits never touch each other's store slice |
| T-UI5 | Scene graph matches the poses |
| T-UI6 | Accessibility (axe, keyboard, `aria-valuetext`) |
| T-UI7 | Mocked WebSocket scenarios |
| T-UI8 | Dual-view render sync within 2 frames |
| T-UI9 | Visual regression (SwiftShader) |
| T-UI10 | Hardware frame time on the RX 6800 |
| T-UI11 | Token contrast and colour-vision-deficiency screenshots |

**CAD (T-CAD)**
- package determinism;
- schema validation;
- transform round-trip with det = +1;
- ingest of mock Fusion JSON (origin → COM inertia shift, units, reason codes);
- interference classifier: 0.005 mm → contact within tolerance, 0.02 mm → interference.

The Fusion-side tests (§N) are deferred.

**Toolchain (T-T)**
- No registry or user-profile writes.
- Wheel-only `uv sync --locked`.
- `npm ci` reproducible.
- **Licence audit:** fails on any SPDX id that is not approved, across both lockfiles.
- Import smoke tests: coacd's abi3 wheel on 3.14, numba, python-fcl, manifold3d.
- Golden mass-property test straight after install.

### J.3 Benchmark protocol
**Instances**

| ID | Instance |
|---|---|
| I1 | All 19 parts, Stage 1 |
| I2 | All 19 parts, Stage 2 |
| I3, I4 | 8- and 12-part subsets, Stage 1 |
| I5 | Perfect-packing generator (known optimum) |
| I6 | CP-SAT oracle micro-instances |

Each is run under the four fixed presets.

**Variants**

| ID | Variant |
|---|---|
| V1 | Constructive multistart (EP ∪ EMS) |
| V2 | BRKGA with the box decoder |
| V3 | LAHC alone |
| V4 | BRKGA + local search |
| V5 | Full hybrid (islands + refiners + compaction) |
| V6 | Independent portfolio (same workers, no migration or local search) |
| V7 | Voxel FFT decoder + BRKGA |
| V8 | CP-SAT box proxy (bounds) |
| V9 | NSGA-II (front quality) |

**Budgets**
- Algorithm comparisons use fixed evaluation budgets, e.g. 20,000 decodes.
- User-facing claims use fixed wall-clock budgets: 30 s on 10 workers.
- The planned total is about 2.5 h (ESTIMATE). It is trimmed if needed to stay within the **3 h cap**.

**Seeds.** 10 per stochastic variant and instance, from `SeedSequence`. Each seed index shares its initial population across variants, which permits paired tests.

**Metrics recorded for every run**
- Objectives: L, D, I (with T and P separately), G (Stage 2), plus λ_max and κ.
- Space Used and the largest empty box.
- Runtime and peak memory (RSS via Win32 `GetProcessMemoryInfo` through ctypes, plus `tracemalloc`).
- Evaluations, time to first valid layout, time to target.
- Convergence trace.
- Collision and constraint violations among validated outputs (must be 0).
- Reproducibility hash.

**Statistics**
- Per instance: median and IQR; paired Wilcoxon or Mann–Whitney U (exact or permutation); Vargha–Delaney A₁₂ with a bootstrap confidence interval; Holm correction.
- Across instances: Friedman test with post-hoc analysis.
- Anytime behaviour: ECDF and area under the curve.
- Fronts: hypervolume and IGD+ in one frozen normalised space.
- **Power caveat.** With 10 seeds, the power to detect A₁₂ = 0.71 is only about 0.39 (ESTIMATE). Non-significant results are reported as *inconclusive*, not as equivalence. Confidence intervals are always shown.

**The hybrid question (spec §9)** is answered by comparing V5 against V6 and against the single algorithms, with the adoption rule in §D.4.

### J.4 Interactive performance targets (targets to be measured, not promises)
| Interaction | Target | How measured |
|---|---|---|
| Slider / control echo | ≤ 16.7 ms p95 (one frame) | Event Timing → presented frame |
| Mass edit → COM marker and metrics | ≤ 50 ms p95 | Input → frame showing the new COM (Playwright + `performance.now()`) |
| Weight change → best archived validated layout shown | ≤ 100 ms p95 | Input → `layout.validated` frame |
| Re-optimisation start after the last slider move | 150 ms debounce (+ ≤ 16 ms timer jitter) | Server stamps |
| First *improved* validated layout after a change | ≤ 2 s median for ~20 parts. Reported as censored when the archive is already near-optimal | 10 seeds × 30 edits |
| Progress / layout stream | Layouts ≤ 4 Hz; progress ≤ 10 Hz; acknowledgements unthrottled | Message timestamps |
| Full exact validation of one layout | ≤ 0.5 s p95 (ESTIMATE 0.15 s typical) | Validator timing |
| Configuration switch (saved layout) | ≤ 100 ms | Input → frame |
| Viewport | 60 fps target in a 1440p-sized window; 4K measured and reported | 10 s scripted orbit; p50/p95 frame time |

Measured on-machine anchors so far:
- Windows inter-process round trips: 0.03–0.15 ms p99.
- Spawning a process: 70–96 ms, which is why worker pools are persistent.
- Python 3.10's `time.sleep` resolution: about 15.6 ms. To be re-measured on 3.14.

---

## K. Implementation roadmap
Each milestone ends with its exit tests passing, an ADR log update, a local git commit and a short status note. Nothing moves to the next milestone with a failing exit test, unless the failure is recorded as a blocker with a workaround.

| # | Milestone | Main content | Exit criteria |
|---|---|---|---|
| M0 | Toolchain and skeleton | Downloads from Appendix C (hashes verified); `tools\env.cmd`; `git init`; uv and npm projects; lockfiles; project-scoped allowlist; contracts and schemas (`shared/schema`); register files | T-T pass; `uv sync --locked` and `npm ci` from a clean state |
| M1 | Geometry and physics core | Ingest, validate, repair; float64 mass properties ×2 (main + reference); classification; canonical frames; golden dataset tests | T-G, T-M pass |
| M2 | Collision and validation | Proxies G0–G3 with containment certificates; G4 validator (FCL + own winding-number containment + manifold3d); Stage 2 checks incl. the blocking matrix; PC/104 coordinates confirmed from a cited source | T-C, T-S pass; **zero false accepts** in fuzzing |
| M3 | Decoders, bounds, polish | Compound proxies; EP ∪ EMS decoder; CP-SAT bounds and oracles; slab and LP polish; first validated layouts on the dataset | Decoder feasibility, known optima, lower-bound unit tests pass |
| M4 | Real-time backend | Coordinator, persistent workers, archive, validation queue, WebSocket protocol, storage, reproducibility | T-R pass; latency instrumentation live |
| M5 | Front end I | App shell, 8 tabs (Overview, Components and Physics complete), viewport, live mass editing, sliders and presets, explanations | T-UI1–T-UI8 pass; measured latencies recorded |
| M6 | Optimiser core | BRKGA islands, refiners, memetic local search, exact compaction, SLSQP, own NSGA-II; voxel FFT engine **after a timing spike** | T-O pass; first improved valid layout measured |
| M7 | Stage 2 and comparison | Engineering Constraints tab, dual view, movement overlay, constraint attribution (measured re-solves), least-violating-candidate reporting | T-S and comparison UI tests pass |
| M8 | Benchmarks and deliverables | Benchmark suite (≤ 3 h), Algorithm Comparison tab, Results & Export, reports (Markdown/HTML/CSV/JSON/PNG), Fusion export package + CAD Validation tab (NOT CONFIGURED), free-rotation experiment | Suite completes; every reported number traces to a run record |
| M9 | Final validation and report | Full regression run; final report with a status matrix (completed / tested / partial / planned), limitations, blockers, deferred Fusion tasks, assumptions, next steps | All exit tests re-run green or the failures are documented |

**Ordering rationale.**
- Correctness foundations come first (M1–M2). Every later number depends on them.
- The first visible, validated layouts arrive in M3. A usable interactive app exists after M5.
- If time runs out, the work up to M5 or M6 is already a coherent, tested product. The remaining milestones are then reported as planned.

---

## L. Risks and open questions

### L.1 Risk register
| # | Risk | Likelihood / impact | Mitigation |
|---|---|---|---|
| R1 | Stage 2 has **no feasible layout** under the ASSUMED hardware. The harness conflict is proven by arithmetic; two estimates put the length at ≥ 336.5 mm | High / high | Decisions U4–U7 made before coding; bound pre-check; mesh-level compaction recovers proxy waste (about 400 cm³ between compound proxies and solid); least-violating candidate + measured constraint attribution; never auto-relax |
| R2 | COM vs compactness conflict: compact layouts can sit outside ±70 mm in Z | High / medium | Slab post-optimiser and slack shifts (L unchanged); hard COM box in Stage 2; occupied span and COM badge (U3); trade-off chart |
| R3 | A validator falsely accepts an overlap | Low / critical | Certificates checked against all vertices; containment test; two exact implementations; INDETERMINATE = not valid; zero-false-accept fuzz gate |
| R4 | FCL robustness at touching contacts (known EPA/signed-distance issues) | Medium / medium | EPA never decides acceptance; 5 µm placement gap; mm kernel; contact fixtures |
| R5 | A convex decomposition under-covers its part (CoACD) | Medium / high | Certificate vol(mesh − ∪pieces) ≤ 1e-9·V or fall back to the hull; planar-cut covers first |
| R6 | Python overhead makes search too slow for the 2 s target | Medium / medium | Numba kernels; batched NumPy; voxel engine only after a timing spike; archive-first response means the screen always has a valid layout |
| R7 | Concurrency bugs (epochs, cancellation, stale overwrites) | Medium / high | Single writer; per-worker channels; property tests with 1,000 random interleavings |
| R8 | Library availability or licence surprises at install time (wheels, transitive copyleft) | Medium / medium | Wheel-only, locked installs; licence scan in M0; register with fallbacks (own NSGA-II, Open3D vs libigl, coal deferred) |
| R9 | Voxel FFT timing on CPU is unknown | Medium / low | Timing spike before committing. The engine is optional (V7) |
| R10 | Fusion preview API drift, facet limits, undocumented inertia sign convention | High / low (deferred) | Faceted conversion with `BRepBodyDefinition` fallback; decimation with recorded Hausdorff distance; sentinel tests decide signs |
| R11 | 60 fps at 4K not reached | Low / low | Demand rendering, `PerformanceMonitor`, DPR caps; measured and reported |
| R12 | Normalisation drift makes slider meaning unstable | Medium / medium | Frozen normalisation epochs; "provisional" label; explicit refresh |
| R13 | Statistical power is too low to separate variants | High / low | Confidence intervals; "inconclusive" wording; more seeds if the budget allows |
| R14 | Scope vs unattended run time | Medium / medium | Milestone ordering gives a usable product early; status matrix in the final report |
| R15 | Disk: C: has only 30.5 GB free | Low | Everything lives on D: (190 GB free) |

### L.2 Cross-check results
The cross-check agent read every report. It ran no code and wrote no files; its one disclosure is a read-only directory listing. It verified the claims below from primary sources: PyPI JSON metadata, tagged source code, official docs and schedules.

| # | Claim | Verdict |
|---|---|---|
| 1 | pymoo 0.6.1.6 / 0.6.2 hard-require `moocore>=0.1.7` (LGPL-2.1-or-later). 0.6.1.5 has no cp314 wheel | **CONFIRMED** → U1 |
| 2 | python-fcl 0.7.0.11: BSD; win_amd64 wheels cp312/313/314; no `nogil` in its Cython source | **CONFIRMED** → processes for collision |
| 3 | manifold3d 3.5.4 exposes `min_gap`, `split_by_plane`, `hull`, `volume`, `batch_hull`, `trim_by_plane`, `minkowski_sum` | **CONFIRMED** at the v3.5.4 tag. **No `winding_number`** → our own kernel |
| 4 | coal has no Windows wheels on PyPI | **CONFIRMED** → deferred |
| 5 | coacd 1.0.14 is MIT and ships one `cp39-abi3-win_amd64` wheel | **CONFIRMED.** Import on 3.14 UNVERIFIED → install smoke test |
| 6 | numpy 2.5.4 requires Python ≥ 3.12; numba 0.68.0 requires numpy < 2.6 and has cp314 wheels | **CONFIRMED** |
| 7 | nevergrad hard-depends on directsearch (GPL-3.0+) | **CONFIRMED** → excluded |
| 8 | The libigl wheel builds copyleft and restricted modules by default | **CONFIRMED** (CMake options) → excluded |
| 9 | Qhull (bundled in SciPy) uses a custom permissive licence not named on the whitelist | **CONFIRMED** → U2 |
| 10 | trimesh `transform_inertia` uses Rᵀ(I + mM)R in its parallel-axis branch | **CONFIRMED** → our own transforms; trimesh only as a cross-check |
| 11 | Node 24 has been Maintenance LTS since 2026-10-20 (EOL 2028-04-30); Node 26 becomes LTS on 2026-10-28 | **CONFIRMED** → Node 24 (accepted) |
| 12 | CP-SAT has no 3D no-overlap constraint (only `no_overlap`, `no_overlap_2d`, `cumulative`) | **CONFIRMED** |
| 13 | Fusion `measureMinimumDistance` and `createInterferenceInput` do not take MeshBody; `MeshConvertFeatures` is a Preview API | **CONFIRMED-INDIRECT** (official pages as indexed; direct fetches returned 404). Re-check at Fusion setup |

**Also confirmed:**
- cp314 Windows wheels exist for scipy 1.18.1, ortools 9.15.6755, highspy 1.15.1, pydantic-core, shapely, rtree, open3d 0.20.0 and fast-simplification 0.2.0.
- point-cloud-utils has no cp314 wheel.
- Python 3.12 and 3.13 are security-only; 3.14 is in bugfix.

**Corrections applied to this protocol:**
- inertia objective changed to the smooth trace + products form (§F.3);
- slider mapping (§F.4);
- contact policy split into placement, classification and accuracy rules (§F.2);
- unified proxy naming G0–G4 + V, and a containment certificate that requires an *empty* boolean difference, not a small volume (§D.3);
- the PCB hull rule (§C);
- canonical-frame candidates and tie-breaks (§D.5);
- conservative frame-mass default (U7);
- mounting-layer and PC/104-rod modelling (§F.2);
- the "no feasible layout" wording;
- the inverted fixture → REPAIRED (§B);
- a wrong oracle: 8 boxes of 50 × 50 × 85.125 mm stack to 170.25 mm, not 340.5 (§J);
- the convex-part count: 9, not 10;
- the licence exclusions (§H.2).

The cross-check's ranked risks are merged into §L.1.

### L.3 Decisions for you (defaults apply if you simply approve)
- **U1 — moocore licence.** pymoo ≥ 0.6.1.6 imports moocore (LGPL-2.1-or-later) at module level, and the accepted policy is permissive-only.
  - *Default:* implement NSGA-II, hypervolume and IGD+ ourselves, tested on ZDT/DTLZ and against optuna (MIT).
  - *Alternatives:* (b) pin pymoo 0.6.1.5, which has no cp314 wheel and would force Python 3.13 and a frozen dependency; (c) grant an LGPL waiver.
- **U2 — Licence wording.** The literal list (MIT/BSD/Apache-2.0/MPL-2.0/Zlib/ISC) fails the core stack:
  - NumPy's licence expression includes 0BSD and CC0-1.0;
  - SciPy bundles Qhull (its own permissive licence) and BSL-1.0 code;
  - pydantic needs typing-extensions (PSF-2.0);
  - manifold3d probably bundles Clipper2 (BSL-1.0, inferred).

  *Default:* the rule becomes "permissive, non-copyleft, SPDX-listed", naming BSL-1.0, PSF-2.0, Qhull, 0BSD, CC0-1.0 and Apache-2.0 WITH LLVM-exception. GPL, LGPL, AGPL, EPL and non-commercial licences stay excluded. An automated lockfile audit enforces it.
- **U3 — Compactness definition.** Your accepted definition ("used length with free space at one end") pushes the COM toward −Z. Prototype layouts sat 48–78 mm off-centre (indicative only).
  - *Default:* keep it.
  - *Additions:* every layout also shows the occupied span and a CDS COM-box badge, and a length-vs-COM chart marks the ±70 mm line. COM improvers that leave L unchanged (slab post-optimiser, slack shifts) are always on.
- **U4 — Clearance arithmetic.**
  - *Default:* 2.2 mm part–part and 1.2 mm part–wall (0.2 mm tolerance per gap).
  - *Alternative:* per-part stack-up, 2.4 mm part–part. An unauthorised prototype used this and over-stated the Stage 2 length.
- **U5 — Harness vs PCB stack.** Even with zero clearance, 2 + 10 + 90 + 2 = 104 mm > 100 mm. Without a rule, Stage 2 is infeasible by construction.
  - *Default:* the channel runs along one side wall **except across the PCB stack's Z span**. There, wiring is ASSUMED to use the PC/104 stack bus (labelled).
  - *Alternatives:* a corner channel (requires narrower boards); no harness model.
- **U6 — Mounting layer.** Which face carries the 3 mm layer decides the Stage 2 length.
  - *Default:* the optimiser picks a planar face (an AABB face for curved parts) that touches a wall or rail. On that face only, the layer replaces the 1.2 mm wall clearance.
  - *Alternatives:* always the smallest face; only faces you mark.
- **U7 — Frame mass.**
  - *Default:* exclude the ASSUMED frame (≈ 0.876 kg) from the hard COM check, which is conservative. Report the COM both ways.
  - *Alternative:* include it, which helps pass the check.
- **U8 — Interlocked placements.**
  - *Default:* Stage 1 may use cavities in ways that cannot be assembled (rod through the torus), flagged "not assemblable along ±Z". Stage 2 forbids them.
- **U9 — Unattended run.**
  - *Default:* the project-scoped allowlist in Appendix C.4, plus keep-awake. You choose the permission mode in the app before leaving.

### L.4 Engineering decisions taken by the lead (no input needed; recorded as ADRs)
| Decision | Choice | Why |
|---|---|---|
| Contact policy | Placement +5 µm; classification CONTACT \|s\| < 0.01 mm, OVERLAP s ≤ −0.01 mm; in-band negatives only with an overlap-extent proof (imported layouts); 1 µm = distance accuracy | Implements the accepted rule soundly; FCL cannot certify penetration depth |
| Box-proxy inflation | 1.1 mm per side plus a 0.1 mm wall shrink (follows from U4) | Lemma: disjoint inflated boxes ⇒ clearance ≥ 2.2 mm |
| Canonical frame | Smallest certified compound proxy among authored / min-OBB / principal (if well-defined) / largest-face frames; fixed tie-break; per-part override | Cross-hub, wedge and tilted-part cases |
| Geometry kernel units | mm (float64); SI at the physics boundary; integer-µm canonical poses | FCL's absolute tolerances; bit-identical validate, display and export |
| Inertia objective | I = α·T̂ + (1 − α)·P̂ (trace + products); λ_max, κ and tilt displayed | Smooth at the 3U operating point (I_xx ≈ I_yy), where λ_max has a kink |
| Spec sliders | L, D, I weights; mass-distribution = α; feasibility = margin objective G in Stage 2 only (disabled in Stage 1); speed ↔ quality = compute budget | Every spec slider has an honest meaning, and hard constraints are never weighted |
| No feasible Stage 2 layout | Bound pre-check; "NO FEASIBLE LAYOUT FOUND (not proven infeasible)" + least-violating candidate + measured constraint attribution; never auto-relax | Honest reporting |
| Toolchain | Python 3.14.x (3.13 fallback), Node 24 LTS, 14-day age rule | Within the accepted defaults; all core wheels confirmed |
| Speed ↔ quality | Compute budget only | It must not alter objectives |
| Inverted meshes | Auto-flip, labelled REPAIRED | Accepted lossless-repair policy |
| BRKGA / NSGA-II | Own implementations (small) | Licences; epoch hooks |
| Worker topology | §H.4 | Merges the I, F and D1 proposals; FCL GIL |

### L.5 Open items that do not block implementation
- Your visual references (the design tokens will be revised).
- A real STL dataset (units confirmation required then), real masses, mounting-hardware data, cable data, thermal data.
- Confirmation of the PC/104 hole pattern and rod length.
- The dispenser ICD (it may tighten the CDS limits).
- Your Fusion licence tier, and the status of the Fusion install found on disk.

---

## M. Real-time optimisation architecture

### M.1 Invariants
1. **Only the coordinator publishes state.** Every result is re-scored under the *current* specification before it is published.
2. **Revision tags on every message.** Each message carries `(epoch, constraint_rev, mass_rev, weights_rev, seq)`.
   - The client never shows a layout as VALID if its `constraint_rev` is older than the newest one it has seen.
   - Scores are shown only once `applied_client_seq` equals the last edit sent; until then the display says "updating".
3. **The viewport shows only validated layouts** (BEST VALIDATED).
   - A candidate appears only as an optional ghost labelled UNVERIFIED.
   - A validated layout that is older than the current inputs is badged "VALIDATED FOR PREVIOUS INPUTS".
4. **Validity does not depend on weights; optimality labels do.**

### M.2 Layout states
```
CANDIDATE ──► VALIDATING ──► VALIDATED ──► (user) FINAL
     │              │              └─► STALE (constraint_rev changed) ──► re-validated best-first
     └──────────────┴─► REJECTED (failing pairs fed back to the islands' repair step)
```
- A **VALIDATED certificate** records the layout hash, `constraint_rev`, geometry hashes, tolerance and validator version.
- A **FINAL** layout is a frozen snapshot. It is fully re-checked at G4 and with the independent mass-property implementation, and it is the source for exports.

### M.3 Main interaction sequences
1. **Dragging a priority slider**
   - `pointermove` updates the UI in the same frame. `edit.weights` is sent at ≤ 20 Hz, plus a `commit` on `pointerup`.
   - The coordinator increments `weights_rev`, re-scalarises the archive (O(K·m), < 1 ms ESTIMATE) and acknowledges. If the best validated layout for the new weights is a different one, it publishes that layout immediately (`source: archive`).
   - After a 150 ms trailing debounce (or at once on commit), the coordinator writes the shared control block and sends the new spec to the islands. The islands adopt it within ≤ 10 ms: they re-score their populations, inject the nearest archive elites in weight space, and keep searching.
   - Improvements flow through the validation queue and the validators. Each one is published as `layout.validated` if it is the new best.
2. **Editing a part's mass**
   - The coordinator updates COM and inertia in O(1) and sends `metrics.update` at once, so the COM marker moves.
   - Archive mass objectives are refreshed in O(K·n).
   - In **Stage 2** the COM box is re-checked. If the displayed layout is now outside it, it is marked `INFEASIBLE (COM box)` and the best feasible archive layout is shown.
   - The islands are then re-targeted, as in sequence 1.
3. **Constraint change** (clearance, stage, keep-out, lock, orientation restriction)
   - `constraint_rev` is incremented, and the displayed layout becomes STALE.
   - In-flight validations are cancelled cooperatively.
   - Archive entries are re-validated best-first, and the islands repair their populations.
4. **Reconnect.** `hello` is answered with a full `state.snapshot`. The client then re-sends only its latest intent per control, de-duplicated by `(session, client_seq)`.
5. **Pause / resume / reset / restore / save / compare.**
   - These are explicit `run.control` messages.
   - Restoring a saved layout re-validates it against the current `constraint_rev` before it can be shown as VALID.

### M.4 Mechanics
- **Cancellation.** A shared-memory int64 control block holds the epoch, revisions, run state, background pause flag, and one acknowledgement and heartbeat slot per worker. Each slot has exactly one writer.
  - Each worker has its own spec queue and its own result pipe.
  - Workers check the epoch between bounded steps of ≤ 10 ms, never inside Numba kernels.
  - Idle workers block on an Event.
  - The watchdog terminates a worker only if it misses its acknowledgement for 2 s.
- **Validation queue.**
  - Bounded at 32 entries and de-duplicated by layout hash.
  - Priority is recomputed when an entry is taken off the queue. Entries are dropped if their `constraint_rev` is stale or if they cannot beat the current best.
  - 25 % of slots are reserved for non-best Pareto candidates, so the archive keeps covering the other slider positions.
- **Archive.** About 2,000 validated layouts with their raw objective vectors (~2 MB ESTIMATE).
  - Geometry certificates do not depend on mass.
  - Mass objectives are tagged with `mass_rev`.
  - Locks and restrictions filter the archive; they never delete from it.
- **Throttling.** A per-connection mailbox keeps only the latest message of each type.
  - Layouts are sent at ≤ 4 Hz, with a leading send and a guaranteed trailing send.
  - Progress is sent at ≤ 10 Hz.
  - Acknowledgements and edit-driven metric updates are never throttled.
  - Throttles are based on timestamps, not sleeps, because of the ~16 ms timer granularity.
- **Transport.** JSON over WebSocket, about 1.3 KB per layout (orientation index + integer-µm translations). Meshes and feature edges are fetched once over HTTP and cached by hash.
- **Warm starts.** Search always resumes from the current population plus archive elites, never from scratch. Each island uses a slightly perturbed weight vector, so the next slider position is often already answered by the archive.
- **Rapid slider changes.** The debounce, epoch increments and the latest-wins mailbox stop obsolete requests from wasting compute. Stale results are dropped at the coordinator.
- **GPU acceleration is deferred.**
  - Per-layout work is tiny (171 pairs), so dispatch overhead would dominate.
  - There is no CUDA on the RX 6800, and WGSL has no f64.
  - Browser WebGPU would compete with the viewport.
  - Kernels keep a batch-shaped API (`evaluate_batch(B, n)`) so that a wgpu backend can be added if profiling ever shows surrogate evaluation above 50 % of wall time at B ≥ 10³.

---

## N. Fusion 360 validation architecture

**Status: FUSION 360 VALIDATION — NOT CONFIGURED.**
- No Fusion API call has been made, and none will be made until you confirm installation and authorise integration.
- An executable dated 2025-04-16 exists at `%LOCALAPPDATA%\Autodesk\webdeploy\production\…\Fusion360.exe`. It has not been opened or inspected beyond confirming the file exists.

### N.1 Role
- Fusion is an **independent CAD cross-check**, never the optimiser.
- Our optimiser performs its own collision detection and mass-property calculation.
- Internal validation ("VALIDATED") and CAD validation ("CAD cross-check") are separate labels. Neither implies flight qualification.

### N.2 What the Fusion API can and cannot do (documentation research; see §L.2 for primary-source verification)
| Need | API capability | Consequence |
|---|---|---|
| Run headless or triggered externally | No headless desktop mode | Tier T0: you run a generated script from Scripts and Add-Ins. T1 (optional): an add-in watching an inbox folder, using `fireCustomEvent` |
| Import STL | `MeshBodies.add(path, MillimeterMeshUnit)` (STL, OBJ, 3MF). Internal units are cm, rad, kg | One component per part, positioned with `Occurrence.transform2` built via `Matrix3D.setWithCoordinateSystem` |
| Interference | `Design.analyzeInterference` accepts **BRep bodies and occurrences only**. No documented tolerance. Coincident-face handling is fragile | Meshes must be converted to BRep. Run twice (`areCoincidentFacesIncluded` False/True). Tolerant classification of contacts |
| Mesh → BRep | `meshConvertFeatures` is a **preview** API (Faceted / Prismatic / Organic). Practical limit ~10k facets. Fallback: `BRepBodyDefinition` | Faceted conversion only, so the polyhedron stays identical. The blob (50,880 facets) is decimated and its result labelled APPROXIMATE, with the Hausdorff distance recorded. Capsule, sphere and ellipsoid (~9k) sit near the limit |
| Minimum distance (clearance) | `MeasureManager.measureMinimumDistance` does **not** accept MeshBody | Measured on converted BRep bodies |
| Mass properties | `PhysicalProperties` at `VeryHighCalculationAccuracy` (±0.01 %). Inertia given **about the world origin** in kg·cm², sign convention undocumented | Compared in our backend after a COM shift; a sentinel test settles the convention |
| Licence tiers | Personal: non-commercial, 10 active editable documents, API available. Education: educational use. Commercial: full | Works on Personal (import only; the script writes its own JSON) |

### N.3 Integration design (built in M8; tested without Fusion)
- **Adapter.**
  - `CadValidator` Protocol: `status()`, `capabilities()`, `build_package(layout_id)`, `ingest_results(path) → DiscrepancyReport`.
  - Default `NullCadValidator` → `NOT_CONFIGURED`.
  - `FusionPackageValidator` reads and writes files only. The backend never launches Fusion.
- **Export package** `tts_fusion_<layout>_<hash8>/`:
  - `package.json`: schema, dataset SHA, layout ID, stage, units = mm, tolerances, per-file SHA-256;
  - `parts/<id>.stl`: original bytes in the original frame;
  - `*.decimated.stl`: only where needed, with Hausdorff distance;
  - `transforms.json`: R, t in mm, orientation index, det = +1, explicit 4×4;
  - `frame.json`: Stage 2 rails and walls as exact boxes;
  - `expected_results.json`: our V, COM and I per part and for the assembly, expected contacts and minimum distances;
  - `fusion_validate.py` + `.manifest` (standard-library only, `runOnStartup: false`).
- **Script flow:**
  1. Verify hashes.
  2. New direct-modelling document.
  3. **Sentinels:**
     - a 10 mm cube must give 1.000 cm³;
     - an offset L-bracket fixes the axes and the sign and order of the inertia products.
  4. Import, place and convert every part.
  5. Read physical properties at component and occurrence level.
  6. Interference, run twice.
  7. Minimum distances for the expected pairs and against the frame.
  8. Write `results/fusion_results.json` (raw values with units, `app.version`, `sys.version`, status codes) and close without saving.
- **Comparison (our backend).**
  - Unit conversion: ×10 cm → mm; ×1e-4 kg·cm² → kg·m².
  - Origin → COM inertia shift.
  - Only density-independent quantities are compared (V, COM, I/m).
  - Thresholds:

    | Quantity | Threshold |
    |---|---|
    | Volume | relative ≤ 2e-4 |
    | COM | ≤ 2e-4 × OBB diagonal |
    | Inertia | ‖ΔI‖_F ≤ 2e-4·‖I‖_F |
    | Distance | within 1 µm (faceted) |

  - Overlaps whose minimum extent is ≤ 0.01 mm are classed CONTACT_WITHIN_TOL.
- **Report** `discrepancy_report.json`:
  - overall verdict: VALIDATED / DISCREPANCIES / INCONCLUSIVE;
  - per-part and per-pair verdicts;
  - reason codes: `FACET_LIMIT`, `DECIMATED`, `CONVERT_FAILED`, `PREVIEW_API_MISSING`, `COINCIDENT_FACE_ERROR`, `MESH_OPEN`.

### N.4 Deferred setup plan (after you authorise)
1. Install check: you read Help > About and the licence tier; a one-line script prints `sys.version`.
2. API environment: Scripts and Add-Ins dialog. Standard library only; no shared virtual environment.
3. Script configuration: link the package folder or copy it to `%APPDATA%\Autodesk\Autodesk Fusion 360\API\Scripts`.
4. Sentinel run: units, axes, det(R), inertia sign and order.
5. Assembly import: 19 components, names correct, `transform2` read back within 1e-9 cm.
6. Faceted conversion, with a failure list and blob decimation.
7. Interference in both coincident-face modes.
8. Part–part and part–wall clearance.
9. Physical-property extraction.
10. Automated comparison with `ingest_results`.
11. Report in the CAD Validation tab. Re-run the golden layouts after every Fusion update.

---

## O. Ideal versus real-world packaging

### O.1 Stage 1 (IDEALIZED)
- **Objective:** minimise the scalarised objectives (§F) over positions and orientations.
- **Subject to:**
  - certified non-interpenetration;
  - containment in the 100 × 100 × 340.5 mm box;
  - your locks.
- **Cavity use:** cavities may be used. Non-assemblable placements are flagged (U8).
- **COM:** every layout shows its COM-box status, but in Stage 1 the box is not enforced.
- **Free rotation:** reported as a separate experiment.
- **Every result is labelled IDEALIZED**, with packing (L, Space Used, largest empty box), COM, the full tensor, principal moments, runtime and constraint violations (0).

### O.2 Stage 2 (ENGINEERING-CONSTRAINED)
| Constraint | Model | Data status |
|---|---|---|
| Enclosure walls 2.0 mm | Inner box 96 × 96 × 336.5 mm | ASSUMED |
| Corner rails 8.5 × 8.5 mm (inside the 100 mm envelope) | Four full-length keep-out prisms | ASSUMED (the CDS gives rail width; the internal frame is ours) |
| Frame mass (U7) | Pseudo-part computed from the frame geometry at 2,700 kg/m³ (≈ 0.876 kg). Excluded from the hard COM check by default; COM reported both ways | ASSUMED |
| Clearances (U4) | 2.2 mm part–part, 1.2 mm part–wall/rail (incl. 0.2 mm tolerance) | ASSUMED |
| PCB stack | PCB-tagged parts parallel to XY, rail-centred, XY-locked, 15.24 mm pitch. PC/104 rod keep-outs span only the stack's Z range; PCB–rod pairs exempt; other parts keep 1.2 mm. Hole coordinates from a cited source in M2 | ASSUMED |
| Mounting allowance (U6) | 3 mm layer on an optimiser-chosen face touching a wall or rail; it replaces the wall clearance on that face; plus a reachability check | ASSUMED heuristic |
| Harness (U5) | 10 mm channel along one side wall, interrupted across the PCB stack's Z span (stack wiring ASSUMED through the PC/104 bus) | ASSUMED |
| Connector access | 15 mm deep zones on faces you mark | Not modelled until marked |
| Cable bend radius | — | **NOT MODELLED** (needs cable data) |
| Thermal | Tags: source / sensitive / needs-wall; 10 mm separation | Inactive until tagged |
| Insertion / serviceability | Exact ±Z blocking matrix from swept volumes; greedy removal (complete); "serviceable" parts removable alone | Exact for straight-line ±Z |
| CDS COM box | ±20 / ±20 / ±70 mm | Standard (verified) |
| Launch loads | Proxies only: mass per interface, COM inside the box | **NOT ANALYSED** |

Every Stage 2 result is labelled **ENGINEERING-CONSTRAINED — not flight-qualified**. It reports:
- clearance margins: minimum slack per pair and per wall;
- the insertion order;
- binding constraints;
- each ASSUMED item it relied on.

If no layout is found:
- the result is **"NO FEASIBLE LAYOUT FOUND (not proven infeasible)"**, or **INFEASIBLE (proven)** when a bound shows the setup is impossible;
- the least-violating candidate is shown, together with the measured constraint attribution;
- constraints are never relaxed automatically.

### O.3 Comparison workspace (Engineering Constraints / Results tabs)
- **Views:** IDEALIZED on the left, ENGINEERING-CONSTRAINED on the right, with synchronised cameras. An optional movement overlay shows per-part arrows and a ΔCOM vector with its magnitude and (Δx, Δy, Δz).
- **Metrics table:** L, Space Used, largest empty box, COM displacement, full tensor and principal moments, clearance margins, mounting feasibility, violations and runtime, with signed deltas.
- **Constraint attribution.** Stage 2 is re-solved with each constraint family relaxed in turn: warm-started, same seed and budget. The change in every objective is reported. This answers "which constraint cost the most" with *measured* sensitivities, labelled with the budget used. It is not a narrative.
- **Disclaimer, always visible:** "Successful geometric packaging does not demonstrate mechanical or flight qualification."

---

## P. User experience and interface accessibility
- **First screen.** It answers three questions: *What am I arranging? What am I optimising? How good is the current arrangement?* It shows five metrics in plain language. The full tensor is not on the home screen.
- **Two levels: Beginner and Expert.** Beginner hides candidates, convergence charts and tensors. Expert reveals them. The choice persists per user, in browser storage, as a convenience only.
- **Plain language first.** Tooltips and expandable "Technically" sections cover centre of mass, moment of inertia, packing efficiency (and why Space Used never changes), optimisation weights, collision detection and mechanical clearance. Example:

  > *Balance the Spacecraft — Moves heavy parts so the spacecraft's balance point sits near the middle.*
  > *Technically: minimises the distance between the assembly centre of mass and the target point (mm).*
  > *Why it matters: launch rules require the balance point within ±20 mm sideways and ±70 mm lengthwise.*

- **Honesty in wording.**
  - "Best found so far — not proven optimal".
  - Signed deltas with the words better / worse.
  - Trade-offs computed from data, e.g. "−12 mm length costs +9 mm balance error".
  - ASSUMED, USER and WITHHELD badges on physical values.
  - IDEALIZED / ENGINEERING-CONSTRAINED badges on every result.
- **Accessibility.**
  - WCAG 2.2 AA contrast, with every token pair checked by a unit test; 3:1 non-text contrast for controls and graphs.
  - Full keyboard operation, including viewport navigation keys and slider keys with `aria-valuetext` (e.g. "25 percent priority").
  - Visible 2 px focus ring.
  - Live-region announcements for selection and state changes.
  - DOM labels readable by screen readers.
  - Colour never the only signal: text badges, icons and dashed vs solid styles.
  - Okabe-Ito palette, checked with colour-vision-deficiency emulation.
  - `prefers-reduced-motion` and `forced-colors` respected.
- **Physical parameters vs priorities.** They are kept apart in layout, colour, captions, store slices and message types. Changing a mass "changes the physics"; moving a slider "changes what the optimiser prefers — never the parts".

---

## Appendix A — Dataset analysis (MEASURED, read-only, standard-library prototype)
Totals for the packable parts:
- 1,080.0 cm³ of solid, 2.916 kg at 2,700 kg/m³;
- 31.7 % of the 3U body volume;
- 86,520 triangles.

The analysis took 4.3 s for 22 files.

| Part | Tris | Volume cm³ | Mass kg | OBB mm | Solidity | OBB fill | Labels (computed) |
|---|---|---|---|---|---|---|---|
| battery_pack | 12 | 140.80 | 0.380 | 80.0 × 80.0 × 22.0 | 1.000 | 1.000 | box-like, convex, planar-faceted |
| camera_with_lens | 388 | 121.17 | 0.327 | 70.0 × 50.0 × 50.0 | 0.824 | 0.692 | strongly concave |
| cross_connector_hub | 60 | 28.67 | 0.077 | 48.0 × 45.3 × 45.3 | 0.488 | 0.292 | strongly concave, planar-faceted |
| ellipsoid_module | 9,024 | 37.63 | 0.102 | 60.0 × 40.0 × 30.0 | 1.000 | 0.523 | convex, curved |
| gas_tank_capsule | 9,216 | 119.15 | 0.322 | 90.0 × 45.0 × 45.0 | 1.000 | 0.654 | convex, elongated, curved |
| gear_mechanism | 252 | 15.88 | 0.043 | 49.5 × 49.5 × 10.0 | 0.818 | 0.649 | strongly concave, plate-like |
| irregular_blob | 50,880 | 71.28 | 0.192 | 54.7 × 53.4 × 52.9 | 0.814 | 0.462 | strongly concave, curved, highly irregular |
| l_shaped_electronics | 20 | 86.25 | 0.233 | 70.0 × 70.0 × 30.0 | 0.740 | 0.587 | strongly concave, planar-faceted |
| magnetometer_ring_torus | 6,144 | 37.63 | 0.102 | 76.0 × 76.0 × 16.0 | 0.569 | 0.408 | strongly concave, plate-like, curved, through-hole (genus 1) |
| magnetorquer_rod | 192 | 6.27 | 0.017 | 80.0 × 10.0 × 10.0 | 1.000 | 0.787 | convex, elongated, curved |
| optics_baffle_tube | 768 | 20.91 | 0.056 | 60.0 × 40.0 × 40.0 | 0.277 | 0.218 | strongly concave, curved, through-hole (genus 1) |
| payload_electronics_box | 12 | 72.00 | 0.194 | 60.0 × 40.0 × 30.0 | 1.000 | 1.000 | box-like, convex, planar-faceted |
| pcb_eps | 44 | 12.65 | 0.034 | 90.0 × 90.0 × 1.6 | 0.988 | 0.976 | box-like, convex, thin, planar-faceted |
| pcb_obc | 44 | 12.65 | 0.034 | 90.0 × 90.0 × 1.6 | 0.988 | 0.976 | box-like, convex, thin, planar-faceted |
| propellant_tank_sphere | 9,024 | 112.90 | 0.305 | 60.0 × 60.0 × 59.9 | 1.000 | 0.524 | convex, curved |
| reaction_wheel | 384 | 49.05 | 0.132 | 50.0 × 50.0 × 25.0 | 1.000 | 0.786 | convex |
| sensor_housing_hex | 20 | 69.28 | 0.187 | 50.0 × 46.2 × 40.0 | 1.000 | 0.750 | convex, planar-faceted |
| u_channel_bracket | 28 | 35.84 | 0.097 | 80.0 × 60.0 × 30.0 | 0.249 | 0.249 | strongly concave, planar-faceted |
| wedge_bracket | 8 | 30.00 | 0.081 | 50.0 × 40.0 × 30.0 | 1.000 | 0.500 | convex, planar-faceted |

**Check against analytic values (unit density).**
- Exact polyhedra match with relative error 0 to 5e-8 (the residual is float32 STL rounding). Examples: battery, L, U and cross give 0; the tilted payload box gives a COM error of 5.3e-7 mm.
- Tessellated shapes match their discretisation error:

  | Shape | Volume error |
  |---|---|
  | Cylinder, 96 segments | −7.14e-4 |
  | Rod, 48 segments | −2.85e-3 |
  | Sphere, 48 × 96 | −1.78e-3 |
  | Torus, 96 × 32 | −7.12e-3 |
  | Camera lens | 2.8e-4 overall |

**Fixtures.**
- Open mesh: 3 boundary edges, mass properties withheld.
- Inverted cylinder: signed volume −9,397.9 mm³. Withheld by the prototype; production auto-repairs it.
- Two-body file: solidity 0.800, 2 shells.

**Generator.** A seeded standard-library script (seed 20261021, version 0.1.0). It is in the session scratch area and moves to `tools/dataset/` after approval. The manifest records construction parameters, authored transforms and analytic mass properties.

## Appendix B — Deferred-dependency register (initial; becomes `docs/dependencies/register.toml`)
| ID | Item | Status | Reason / revisit trigger |
|---|---|---|---|
| DD-01 | Fusion 360 installation | **NOT CONFIGURED** | An executable exists on disk (2025-04-16). You must confirm it works and which licence tier it uses |
| DD-02 | Fusion API environment, script/add-in configuration | DEFERRED | After DD-01 and your authorisation |
| DD-03 | Fusion `meshConvertFeatures` (preview API) | DEFERRED | API drift risk. Fallback `BRepBodyDefinition` |
| DD-04 | CAD assembly reconstruction, interference and clearance runs | DEFERRED | After DD-02 |
| DD-05 | pymoo ≥ 0.6.1.6 / moocore (LGPL) | BLOCKED (licence) | U1 |
| DD-06 | coal (best GJK/EPA) | DEFERRED | No Windows wheels on PyPI |
| DD-07 | OpenVDB / pyopenvdb | REJECTED for now | No Windows wheel; dense grids are small |
| DD-08 | GPU compute (wgpu / OpenCL / ROCm) | DEFERRED | Profile trigger in §M.4 |
| DD-09 | Free-threaded Python (3.14t) | DEFERRED | Dependency wheels missing |
| DD-10 | Node 26 LTS, TypeScript 7 | DEFERRED | Too new (14-day rule); typescript-eslint compatibility |
| DD-11 | libigl Python wheel | REJECTED | Builds copyleft and restricted modules by default. Replaced by our own Numba winding-number kernel |
| DD-12 | distance3d | TEST-ONLY if U2 is approved | Bundles BSL-1.0 code |
| DD-18 | point-cloud-utils, Open3D | REJECTED / AVOIDED | No cp314 wheel / heavy web-stack dependencies |
| DD-19 | coacd on Python 3.14 (abi3 wheel) | VERIFY AT INSTALL | Import smoke test. If it fails, use planar-cut covers only |
| DD-20 | PC/104 hole coordinates and rod length | NEEDS SOURCE | No cited source yet. Confirmed from the PC/104 specification in M2 |
| DD-13 | PackingSolver | OPTIONAL (benchmark) | Pre-1.0 with frequent releases. Pin a version at least 14 days old |
| DD-14 | Real STL dataset, units, masses | AWAITING USER | Synthetic dataset in use |
| DD-15 | Mounting hardware, cable, thermal data; PC/104 pattern; dispenser ICD | AWAITING USER | ASSUMED models in use |
| DD-16 | Visual design references | AWAITING USER | Default design direction in use |
| DD-17 | Git (MinGit) | TOOL_ONLY | GPL-2.0 executable, never linked |

## Appendix C — Install list for approval (nothing has been downloaded)
**C.1 Portable tools.** Into `D:\text-to-spaceship\tools\`, from official sources, SHA-256 verified, each release at least 14 days old:

| Tool | Approx size |
|---|---|
| uv zip | ~15 MB |
| CPython 3.14.x `install_only` build | ~48 MB |
| Node.js 24 LTS `win-x64.zip` | ~38 MB |
| MinGit 64-bit zip | ~38 MB |
| Playwright Chromium | ~150–200 MB |

**C.2 Python packages (PyPI, wheels only).** The packages in §H.2, about 400–700 MB in the project `.venv`.

**C.3 npm packages (npm registry).** The packages in §H.3, about 300–500 MB in `node_modules`.

Total: about 1.5–2 GB on D:. The exact file names, versions and hashes go to `tools/toolchain.lock.json` at M0 and appear in the first status note.

**C.4 Unattended-run permissions (U9).** At M0, a project-scoped `.claude/settings.json` allowlist is written and shown to you before you leave. It allows:
- the project's uv, Python and pytest;
- the project's Node, npm, npx, vite, vitest and playwright;
- local git (no `push`, no remotes);
- file edits inside `D:\text-to-spaceship` only.

Downloads are limited to the hosts in C.1–C.3. Nothing outside the project folder is changed. You choose the session's permission mode in the app.

## Appendix D — Research-process disclosure
- **Two agents ran optimisation prototypes before approval.** A1 and A2 each ran throwaway, in-memory pure-Python prototypes of box decoders, including simulated-annealing and BRKGA runs, using the existing Python 3.10.
  - The specification forbids optimisation experiments before approval. My brief to the agents did not restate that rule.
  - No files were written to the project and nothing was installed. A2 notes that the tool harness itself kept fetched documents and background output in its own temporary folders.
  - Their figures are used here only as **indicative, unauthorised prototype results**:

    | Prototype result | Value |
    |---|---|
    | Stage 1 box-proxy L, single box | 225–243 mm |
    | Stage 1 box-proxy L, compound | 212–237 mm |
    | Stage 2 compound, with the 3 mm mounting layer | 342–359 mm |
    | Stage 2 compound, without the mounting layer | 323.5 mm |
    | Decode time | 1–73 ms |

  - None of these is a benchmark of the proposed system.
- **Read-only measurements by four agents.** These fall within "analyse supplied STL files in read-only mode":
  - **E:** mass-property precision checks on the dataset; read the CDS PDF.
  - **I:** Windows IPC and timer measurements using standard-library one-liners.
  - **B2:** sector-convexity checks on the torus and tube meshes.
  - **C1:** dataset surface area.

  No files were written.
- **Cross-check agent.** Barred from running any code. Its only disclosed action beyond reading and web lookups was a read-only listing of the dataset folder.
- **Web search budgets.** Several agents exhausted their search budgets. The resulting gaps are marked UNVERIFIED in the body, and the cross-check agent re-verified the highest-impact claims (§L.2).

## Appendix E — Key sources
- **CubeSat Design Specification Rev 14.1** (Cal Poly, 2022), §2.2.10–2.2.11: https://www.cubesat.org/s/CDS-REV14_1-2022-02-09.pdf
- **Packing heuristics and decoders**
  - Gonçalves & Resende 2013, BRKGA for 2D/3D bin packing: https://optimization-online.org/2012/04/3429/
  - Crainic, Perboli & Tadei 2008, extreme points: https://pubsonline.informs.org/doi/10.1287/ijoc.1070.0250
  - Parreño et al. 2008/2010, maximal spaces, GRASP and VNS
  - Londe et al. 2023/2025, BRKGA reviews: https://arxiv.org/html/2312.00961v2
- **Irregular and convex packing**
  - Cui et al. 2023, *Dense, Interlocking-Free and Scalable Spectral Packing of Generic 3D Objects* (SIGGRAPH): https://doi.org/10.1145/3592126
  - Romanova, Bennell, Stoyan & Pankratov 2018, packing concave polyhedra with phi-functions (EJOR): https://eprints.whiterose.ac.uk/139289/
  - Wei, Liu, Zhang & Pan 2022, CoACD: https://arxiv.org/abs/2205.02961
- **Collision detection**
  - Montaut et al. 2022, GJK / Nesterov acceleration (RSS): https://arxiv.org/abs/2205.09663
  - FCL: https://github.com/flexible-collision-library/fcl
  - manifold: https://github.com/elalish/manifold
- **Multi-objective optimisation**
  - Das & Dennis 1997; Steuer & Choo 1983; Miettinen 1999, *Nonlinear Multiobjective Optimization*
  - Deb et al. 2002 (NSGA-II); Zhang & Li 2007 (MOEA/D); Ishibuchi et al. 2015 (IGD+)
- **Mass properties**
  - Mirtich 1996: https://people.eecs.berkeley.edu/~jfc/mirtich/massProps.html
  - Eberly, *Polyhedral Mass Properties*: https://www.geometrictools.com/Documentation/PolyhedralMassProperties.pdf
- **Fusion API reference:** https://help.autodesk.com/view/fusion360/ENU/ (MeshBodies.add, analyzeInterference, measureMinimumDistance, PhysicalProperties, MeshConvertFeatures)
- **Interaction latency**
  - Liu & Heer 2014, latency in visual analysis: https://idl.uw.edu/papers/latency
  - Nielsen, response-time limits

The condensed per-agent research notes, with each agent's key findings and cited sources, are in the session's working notes. They move into `docs/research/` after approval. Before approval the only file written to the project is this protocol, apart from the dataset you accepted.

---

## Addendum 1 — Your review of 2026-10-22 (overrides any conflicting text above)

### 1.1 Final decisions
| ID | Decision |
|---|---|
| U1 | Use **pymoo 0.6.2 with moocore** for NSGA-II/III, hypervolume and IGD+. Acceptance tests decide whether it stays: hypervolume of the unit-simplex corners = 0.331; ZDT1–3 and DTLZ2 fronts within tolerance; same seed gives the same front. If any test fails, our own implementation replaces it. Our BRKGA loop stays, because it needs epoch hooks; pymoo's BRKGA becomes a cross-check |
| U2 | **All open-source licences allowed, including GPL/LGPL.** Proprietary and non-commercial licences stay excluded unless you say otherwise. The licence audit now *records* licences, and fails only on proprietary or unknown ones. *Distribution note:* shipping the app to others with GPL components linked would require releasing it under GPL |
| U3 | Packing definition approved. New **Size Study** tab (§1.3) |
| U4 | 2.2 mm part–part, 1.2 mm part–wall |
| U5 | The cable channel is driven by a **cable-routing importance slider** (§1.4) |
| U6, U7, U8 | Defaults as written |
| U9 | All permissions granted for the unattended run. Installs from official sources only. No pushing, publishing or messaging. Nothing outside the project folder except the documented tool caches |
| N1–N4 | Defaults in the short protocol: relative cost units; AlSi10Mg for metal additive manufacturing; Size Study on both stages with 5 seeds and ≤ 2 h; boards may stand on edge in cable mode |

**Newly usable under U2** (optional, chosen only where they help):
- libigl: winding numbers and signed distance, replacing our own kernel if it passes the same tests;
- DEAP / nevergrad: extra baselines;
- CGAL bindings: only if Windows wheels exist.

Still deferred: coal, which has no Windows wheels.

### 1.2 Licence audit change (test T-T)
- Every dependency's SPDX id is written to `docs/dependencies/licences.md`.
- The audit fails only on proprietary, non-commercial or unknown licences.

### 1.3 Size Study (new tab, milestone M8)
- **Scaling.** Every part is scaled uniformly by s in all three axes, about its own COM. Per part, with density held constant:

  | Quantity | Scales as |
  |---|---|
  | Geometry | s |
  | Volume and mass | s³ |
  | Inertia | s⁵ |

  Hardware is *not* scaled: enclosure, walls, rails, clearances and the PC/104 pitch stay the same.
- **Grid.** s = 1.00, 1.05, 1.10 … until no algorithm finds a valid layout within budget. The last interval is then bisected to 0.5 %.
- **What is reported.** The result is "largest size with a layout found" for each algorithm. It is called "proven impossible" only when a bound proves it.
- **Bounds shown on the chart:**

  | Bound | Value |
  |---|---|
  | Volume | L ≥ 108.0·s³ mm, so no fit beyond s ≈ (340.5/108.0)^(1/3) ≈ **1.47** |
  | Axis-aligned orientations | the 90 × 90 mm PCBs need a 90·s mm edge in the 100 mm cross-section, so s ≤ **1.11** |
  | Free rotation | PCBs can go diagonally, so the volume bound applies |

  ESTIMATE: the "best algorithm" is therefore likely to change near ×1.11. That is exactly the effect this tab is meant to show.
- **Variants at each s:**
  - constructive box decoder (V1);
  - full hybrid (V5);
  - voxel engine (V7);
  - free-rotation experiment (Stage 1 only);
  - CP-SAT proxy bound.

  Each runs in reproducible mode for 5 seeds × 30 s on one worker.
- **Budget.** ESTIMATE about 10–40 min per stage, capped at 2 h.
- **Display:**
  - length used vs s, one line per algorithm, with bounds and the CubeSat length;
  - a winner strip showing the most compact valid layout per s;
  - the maximum s per algorithm;
  - a 3D thumbnail of each winner;
  - COM and inertia vs s;
  - a full results table.

### 1.4 Cable-routing importance slider (Stage 2; milestone M7)
- **Corridor candidates.** A 10 mm × full-length channel along each of the four side walls, between the rails.
- **Objective.** H = blocked fraction of the chosen corridor's length, in [0, 1]. Slider label: "Keep cable path clear".
- **Mode switching** (shown on screen, with the packing penalty ΔL and ΔCOM relative to the default mode):

  | Slider | Mode | Behaviour |
  |---|---|---|
  | 0 | Default | Corridor interrupted across the PCB stack's Z span; wiring ASSUMED to use the PC/104 stack bus |
  | 1–69 | Soft | H is a weighted objective in the default mode |
  | ≥ 70 (configurable) | **Continuous-cable** | The corridor becomes a **hard** full-length keep-out, and the corridor wall becomes a search variable. The decoder enables edge-mounted PCB orientations (boards parallel to XZ/YZ in ASSUMED card guides). Islands restart under a new `constraint_rev` |

- If no continuous corridor is feasible, the result reads "NO FEASIBLE LAYOUT FOUND (not proven infeasible)", with the least-blocked candidate.

### 1.5 Manufacturable Design tab (new; milestone M9)
**Pipeline**
1. **Automatic algorithm choice.** Uses the part classification and the stored benchmark and Size Study results. For example, when curved or concave parts make up a large share of the volume, the hybrid with the voxel decoder is chosen; otherwise the box-decoder hybrid. The rationale is shown.
2. **Stage 2 layout.**
3. **Mount synthesis.**
4. **Full validation**, brackets included.
5. **Cost and hardware list.**

**Mount types**, cheapest first. The search uses a hardware cost objective C, weighted by its own slider "Keep hardware cost low":

| Type | When | Geometry |
|---|---|---|
| Direct | A planar part face within reach of a wall, rail or end plate | Fasteners only (M3, ASSUMED) |
| Catalogue | Standard offsets, cylinders, boards | Generic standoff lengths, L-brackets, tube clamps, PC/104 spacers (ASSUMED generic set) |
| Sheet metal | Medium offsets, ≤ 3 bends | Parametric L/Z/U, 1.5 mm aluminium (ASSUMED) |
| Machined | Short, stiff offsets | Parametric block |
| **Metal AM (3D-printed)** | Curved contact, awkward offsets, multi-point support, cavities | Generated: a conformal contact patch (the part surface offset by clearance) joined to attachment points by ribs. Built as an implicit/SDF model (manifold3d level sets), meshed, then checked against AM rules (ASSUMED): wall ≥ 1.0 mm, overhang ≤ 45°, holes ≥ 2 mm, build-volume fit |

**Rules for brackets**
- Brackets are real parts: collision-validated at G4 and included in mass properties (AlSi10Mg 2,670 kg/m³; sheet aluminium ~2,680 kg/m³; fasteners as point masses).
- Each mount also needs a straight-line tool-access check for its fasteners.

**Metal-AM identification**
- A dedicated colour plus a diagonal-hatch material in 3D, and an "AM" badge. The pattern carries the meaning, so it is safe for colour-blind users.
- Its own section in the hardware list.
- Exported separately as `bracket_AM_<part>.stl`.

**Cost model.** Relative units, ASSUMED, editable table. Illustrative starting values:

| Item | Relative cost |
|---|---|
| Fastener | 0.1 each |
| Catalogue part | 1 |
| Sheet metal | 3 + 0.5 per bend |
| Machined | 5 + volume term |
| Metal AM | 10 + 2 per cm³ + 1 support removal |

No dollar prices are invented. If you provide prices, the units switch to $.

**Outputs**
- hardware list (part, mount type, process, material, mass, cost);
- AM design-rule report;
- per-bracket STL files and a CSV.

All carry the label "manufacturing concept — assumed cost model, not a quote; brackets not stress-analysed".

### 1.6 Updated roadmap and risks
- **Roadmap:**

  | Milestone | Content |
  |---|---|
  | M7 | Stage 2 + comparison + cable-routing slider |
  | M8 | Benchmarks + Size Study |
  | M9 | Manufacturable Design |
  | M10 | Reports, Fusion export package, final regression run, final report |

  M0–M6 are unchanged.
- **New risks:**

  | ID | Risk | Mitigation |
  |---|---|---|
  | R16 | Generating AM bracket geometry is complex (high / medium) | Catalogue and parametric mounts first; SDF-based AM second; every bracket validated |
  | R17 | Cost model credibility | Relative units, editable, clearly labelled |
  | R18 | Size Study compute | 2 h cap, reproducible mode |
  | R19 | GPL obligations on distribution | Documented in the licence file |

---

## Addendum 2 — Second review of 2026-10-22 (overrides Addendum 1 where they differ)

### 2.1 Any STL, any time (affects M1, M4, M5 and every tab)
**Datasets are never hard-coded.** The synthetic set is just the first project's parts.

**Adding a part to a project.** Use **Add parts**, drag-and-drop, or drop a file into the project's `inbox/` folder. Each new file goes through the same §B pipeline:
1. Hash it and store an immutable copy in `meshes/`.
2. Parse it: binary or ASCII STL, from any CAD exporter.
3. Validate and repair it.
4. **Confirm units.** The interactive prompt defaults to mm. It warns when the extents suggest inches (25.4×) or metres (1000×), and stores the chosen unit per part.
5. Compute mass properties, classify the shape, build proxies and cache them.

Bad files are explained ("open mesh — 3 holes", "self-intersecting") and never crash the app. You choose: repair, enter mass properties yourself, or exclude the part.

**What happens to the project after an edit.**
- Adding, removing or replacing a part increments a `parts_rev` that is part of `constraint_rev`.
- The archive keeps old layouts, labelled "does not include *part*" or "*part* changed". They are never shown as valid for the current parts.
- **Re-run** restarts the islands with warm starts: existing layouts plus a constructive insertion of the new part. The background front, Size Study, Manufacturable Design and benchmarks each have a re-run button that uses the current parts.
- Project files store references to part hashes and per-part settings (units, mass override, tags, locks), so adding a part never loses earlier settings.

**Large files.**
- Above about 200k triangles, the viewport shows a decimated display copy, labelled.
- Search proxies are built from the full mesh and keep their containment certificates. Validation always uses the full mesh.
- Rendering and BVH builds run in workers, so the UI stays responsive.

**Tests.**
- T-G gains "unseen-file" fixtures generated at test time, so they were never seen during development: a new shape, an inch-unit file, an ASCII file, a multi-body file, an open mesh and a 1M-triangle file.
- An end-to-end test (Playwright) adds a file to an existing project, confirms units, re-runs, and checks that:
  - the new part appears in validated layouts;
  - old layouts are labelled stale;
  - mass totals update correctly.

### 2.2 Size Study run length (replaces the 2 h cap)
- **Stopping rule.** The study stops at the earliest of:
  - (a) **6 hours** of wall-clock time;
  - (b) **proven optimum**, for every size step: best length used within 0.1 mm of a proven lower bound for that stage;
  - (c) **convergence:** no improvement > 0.1 mm in length used, and < 0.1 % in the scalarised score, for 30 minutes across all seeds and algorithms, after each algorithm has had at least 20 minutes per size.
- **Reporting.** The tab reports which rule ended the run. "Best solution reached" is worded precisely: "proven optimal" only for (b), otherwise "no further improvement found".
- **Budget split.** Within the 6 h, the time is shared across sizes and algorithms with successive halving: unpromising algorithm and size combinations are dropped early and the time goes to the contested ones. Every result keeps its seed, so it can be reproduced.
- **Keep-awake.** Held for the duration.

### 2.3 Edge-standing circuit boards must be mountable (cable-routing high mode)
An edge-mounted PCB orientation is allowed only together with a **validated mount**. One of:
- **(a) Card guides.** Two ASSUMED aluminium guide rails, 5 × 5 mm section with a 1.8 mm slot, along two opposite board edges. Each guide is attached to a wall or rail within reach.
- **(b) Standoffs.** At least 4 ASSUMED M3 standoffs from the board face to a parallel wall within 3–50 mm, placed at board corners that are free of components.

The mount hardware is real geometry:
- collision-validated at G4 against all parts and the cable corridor;
- counted in mass and inertia, and in hardware cost (Manufacturable Design);
- tool access for its fasteners is checked.

If no mount fits, that board orientation is rejected. The board is never left floating.

---

## Addendum 3 — Request of 2026-10-22: idea map, fit proof, algorithm-choice view

### 3.1 Algorithm selector (backend; M6, with its evidence base filled in M8)
`select_algorithm(stage, weights, part_stats, modes) → AlgorithmChoice{decoder, search, mode, reasons[], evidence[]}`.

**Inputs**
- normalised slider weights;
- stage;
- cable-routing and cost-slider modes;
- part classification statistics: share of volume that is box-like, convex, curved or concave, and the number of parts.

**Selection rule**
- The rule is *performance-based selection* [Rice 1976]. For the current inputs, pick the variant with the best median benchmark result at the nearest measured weight vector, among instances with similar part statistics.
- Until M8 provides that evidence, a documented default rule set is used. It is labelled "default rule (no benchmark evidence yet)".

**Properties**
- The selector is deterministic and fast: no search, so it can be swept.
- Every change of choice is logged with its reasons.
- The Manufacturable Design tab uses the same selector.

### 3.2 Explain tab (new; UI in M8)
**(a) Idea map.** A node-link graph generated from live state:
- parts grouped by classification;
- the proxy chosen per part;
- the candidate algorithms;
- objective weights;
- active constraints and modes;
- the selected algorithm and the resulting VALIDATED layout's metrics.

Each edge is labelled with the quantity that drove the decision. Examples: "strongly concave volume share 31 %", "weight on compactness 0.70", "benchmark median L: 214.5 vs 221.0 mm (n = 10)". Nodes link to the relevant tab. The layout is deterministic and works by keyboard.

**(b) Fit proof.** For the displayed VALIDATED layout:
- **Theorem.** The n parts occupy pairwise-disjoint regions inside the enclosure. In Stage 2 they also keep clearances ≥ c and satisfy the COM box and the insertion order.
- **Lemma 1 (containment).** The enclosure E is convex and each part P ⊆ conv(V(P)). So if every transformed vertex of P satisfies the bounds of E, then P ⊆ E.
  - Shown per part: the extreme vertex on each axis and its margin.
- **Lemma 2 (separation of convex sets).** If n·u + d ≤ 0 for every vertex u of A, and n·v + d ≥ c for every vertex v of B, with |n| = 1, then dist(conv A, conv B) ≥ c. Each pair is proved by one of:
  - an AABB-gap interval argument;
  - a hull separating plane;
  - piece-pair planes over certified convex covers (Lemma 3).
- **Lemma 3 (non-convex pairs).**
  1. Every triangle of ∂A lies inside some convex cover piece. A triangle lies inside a convex piece exactly when its three vertices do.
  2. Every piece pair is separated by at least c (Lemma 2).
  3. A point of each connected component of A lies outside B, and vice versa. This is checked by an exact ray-parity / winding-number test.

  Then dist(A, B) ≥ c. Reason: the boundaries are at least c apart and neither solid contains the other.
- **COM and assembly.** COM-box inequalities with the computed values. The insertion order, with the blocking matrix entries that justify each step.
- **Lower bounds.** Why the layout cannot be much shorter, each with its derivation (§F.9 bounds).
- **Arithmetic.** All inequalities are evaluated in float64 from the original float32 STL vertices and the canonical integer-µm poses. Every margin is shown with its rounding allowance, and the margins must exceed it.
- **Export.**
  - `proof_<layout>.md`: a human-readable document with all numbers;
  - `certificate_<layout>.json`: planes, piece assignments, test points;
  - `check_certificate.py`: standard library only, independent of the app. It reloads the STL files, re-applies the transforms and re-verifies every inequality, printing PASS/FAIL per lemma.
- **Tests.**
  - The checker passes on every FINAL layout in the test suite.
  - Mutation tests: nudging one part by 2c, or corrupting one plane, makes the checker FAIL.

**(c) Algorithm-choice explorer.**
- Overview, Optimization and Manufacturable Design all show the current choice next to the sliders, as a chip: "Algorithm: Hybrid BRKGA + voxel decoder — because …".
- In the Explain tab:
  - **One strip per slider:** the selector is evaluated at 101 positions (0–100) with the other sliders held at their current values. Coloured bands show which algorithm is chosen, and the boundaries show the switch points.
  - **A two-slider heat map:** any two sliders, on a 41 × 41 grid.
  - **The evidence table** behind each choice.
  - **A switch log.**

  The selector is deterministic, so these sweeps are cheap and exact. They are not samples.

### 3.3 Roadmap placement
| Milestone | Work |
|---|---|
| M2 | Certificate generation in the validator (planes, piece assignments, test points) + the stand-alone checker |
| M6 | Selector with the default rules + the chip next to the sliders |
| M8 | Benchmark evidence base + Explain tab (idea map, proof view, explorer) |

---

## Addendum 4 — Request of 2026-10-22: automatic detail-level ladder for every added STL

When a part is added, the app finds, by measurement, the most detailed shape representation that still pays off in accuracy without taking too long. It does this by simplifying the shape and then making it progressively more complex, with every algorithm run at every level.

### 4.1 Detail ladder per part (simplest → most detailed)
| Level | Representation | Conservative? |
|---|---|---|
| F0 | Bounding box (OBB) | yes |
| F1 | Compound boxes, k = 2, 4, 6 | yes (certified) |
| F2 | Convex hull, simplified to a support polytope with 26 / 64 / 128 directions, then the exact hull | yes |
| F3 | Planar-cut convex cover, 2 / 4 / 8 / 16 pieces | yes (by construction; re-derived by the proof checker) |
| F4 | Conservative voxels at 2 / 1 / 0.5 mm | yes (for search only) |
| F5 | Decimated mesh at 1k / 5k / 20k triangles, inflated by its measured Hausdorff distance | yes, after inflation |
| F6 | Full mesh | exact |

Validation always uses the full mesh (§D.3). The ladder only changes what the *search* uses.

### 4.2 What is measured at each level
**Shape cost**
- proxy volume and overhead over the true solid;
- build time;
- evaluation time per collision query, as a median over 10⁴ queries.

**Task accuracy.** The part set is packed with each applicable algorithm (box decoder, hybrid, voxel decoder) while the new part uses that level. The same seeds and a fixed budget are used throughout. Recorded per run:
- length used, COM error and inertia of the resulting validated layout;
- time to the first valid layout;
- the false-reject rate, i.e. how often the proxy blocked a placement that the full mesh would allow.

### 4.3 Stopping and choice
The ladder climbs one level at a time and stops when either:
- **(a) accuracy has converged:** two successive levels change the best length used by < 0.5 mm, change the scalarised score by < 0.5 %, and change the false-reject rate by < 1 point; or
- **(b) time has run out:** the next level would push the per-evaluation time past the interactive budget, so that the first improved valid layout can no longer arrive within about 2 s.

**The chosen level** is the cheapest level whose accuracy is within those tolerances of the most detailed level tested. Each part has a **chosen level per algorithm**. The algorithm selector (Addendum 3) uses these, and the choice is shown with its evidence.

**Running it**
- The ladder runs in the background whenever a part is added or replaced.
- Default budget: 10 minutes per new part. It can be extended, and can be re-run at any time.
- Results are cached by mesh hash and invalidated when constraints change.

### 4.4 Display
- **Components tab, per part "Detail level" panel:**
  - a chart of accuracy (best length used, false-reject rate) against time, one line per algorithm, with one point per level;
  - the chosen level highlighted, with its plain-language reason, e.g. "more detail than 8-piece cover changed the result by only 0.2 mm but took 6× longer";
  - level thumbnails.
- **Algorithm Comparison tab:** a summary table of the chosen level for every part and algorithm.

### 4.5 Roadmap placement
| Milestone | Work |
|---|---|
| M1/M2 | Ladder representations and their certificates |
| M6 | Ladder runner, stopping rule, cache, selector integration |
| M8 | UI |

