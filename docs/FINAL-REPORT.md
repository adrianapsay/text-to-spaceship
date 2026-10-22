# TEXT-TO-SPACESHIP — final report (2026-10-22)

A local web app (Python backend, React / three.js front end) that packs any set of STL parts into a 3U CubeSat:
it analyses and classifies the parts, searches layouts with several algorithms, certifies every reported layout on
the exact meshes, computes mass properties, and explains its choices. Start it with `start.cmd` (opens
http://127.0.0.1:8765). Every number below comes from a run on this machine; the running log with all measured
values is [STATUS.md](STATUS.md), the endpoints are in [api-contract.md](api-contract.md).

**FUSION 360 VALIDATION: NOT CONFIGURED.** No Fusion 360 API call has been made. SolidWorks was not used as a
substitute.

## 1. Status matrix

| Area | State | Evidence |
|---|---|---|
| M0 portable toolchain (uv, CPython 3.14.8, Node 24.21, MinGit; no registry or profile writes) | completed, tested | `backend/tools_smoke.py` |
| M1 STL pipeline: units, repair, mass properties, canonical frames, classification; files added later (upload, inbox, `--add`) | completed, tested | `test_geometry_core`, `test_massprops`, `test_dataset_golden`, `test_unseen_files`, live E2E "file added later (in inches)" |
| M2 certified proxies, exact-mesh validator, fit-proof certificate + stand-alone checker | completed, tested | `test_validator` (250-pair fuzz, 0 false accepts), `test_proof` |
| M3 box decoder, slab post-optimiser, lower bounds | completed, tested | `test_decoder` |
| M4 live backend: islands, validators, coordinator, REST + WebSocket | completed, tested | `test_api` |
| M5 front end (11 tabs, 3D viewport, live editing) | completed, tested | Vitest 64, mock E2E 4, live E2E 7 |
| Robust progress files (atomic write with retry on Windows) | completed, tested | full backend run |
| M6 search: memetic BRKGA, LAHC, NSGA-II (pymoo), height-map decoder, compaction, selector, detail ladder F0–F4 | completed with deviations | `test_selector`, `test_pymoo_accuracy`, `test_api` |
| M7 Stage 2 engineering model, cable-slider modes, mounting, insertion order, INFEASIBLE reporting, constraint attribution | completed with deviations | `test_stage2`, `test_api` |
| M8 benchmarks (1,480 runs), CP-SAT seed, evidence-based selector, idea map, slider → algorithm sweep / map | completed, tested | full benchmark run, `test_api`, live E2E "slider switches the algorithm where the sweep says" |
| M8 Size Study (scan, bisection, successive halving; 6 h cap, stops on convergence), both stages | completed; tested with tiny budgets, one 1-hour demonstration run on project `default` (section 3), no 6-hour run yet | `test_api`, demonstration run |
| M9 Manufacturable Design: own algorithm choice, mount rules, conformal metal-AM brackets (identifiable: own colour, hatch, "AM" badge, `bracket_AM_*.stl`), cost slider, exact bracket checks | completed with deviations | `test_api`, live E2E, full-dataset smoke run |
| M10 reports (Markdown / HTML), placed-STL ZIP, Fusion 360 export package, CAD Validation tab | completed; Fusion package prepared only | `test_api`, live E2E |
| Detail ladder F2 (support polytopes), F5 (decimated meshes); false-reject rate for F4 levels; ladder for Stage 2 | partial — not implemented | STATUS.md M6 |
| Voxel FFT engine | not implemented — replaced by the 2.5-D height-map decoder | STATUS.md M6 |
| SLSQP / LP polish | not implemented | STATUS.md M6 |
| Free-rotation experiment (Stage 1, research, Algorithm Comparison tab) | completed with a deviation: greedy rotate-and-drop search with exact checks instead of the protocol's quasi-phi / L-BFGS-B / CMA-ES; rotated layouts are not drawn in the 3D views | `test_free_rotation` (3), `test_api`, full-dataset run (section 3) |
| PNG export of the views | planned — not implemented (the HTML report has SVG views) | — |
| Card guides for edge boards; thermal tags; connector-access zones; cable bend radius | not modelled | STATUS.md M7 |
| Restoring an archived layout from the history | planned — no endpoint | Results tab note |
| Fusion 360 validation and result ingestion | deferred until you confirm the installation | section 5 |

## 2. Regression run (2026-10-22, after the last code change)

| Suite | Result |
|---|---|
| Backend (pytest, all modules) | 121 passed, 0 failed |
| Front end unit tests (Vitest) | 64 passed |
| Front end E2E, mock backend (Playwright) | 4 passed |
| Front end E2E, live backend (Playwright) | 7 passed |
| Type check (`tsc`) | clean |

Failures found and fixed on the way (recorded, not hidden):
- The first live E2E run failed one test that still expected the pre-M8 "default rule — no benchmark evidence yet"
  text. The selector now follows the shipped benchmark evidence. The slider test was rewritten to check the
  algorithm name against the backend's own selector sweep; before that, it passed only because the expected names
  also appeared inside the explanation text.
- One full backend run failed two tests (constraint attribution and Size Study) with "Access is denied". That run
  overlapped a separate experiment, which made the timing collision more likely. The cause is real: on Windows a
  background job cannot replace its progress file while the coordinator is reading it. All progress and result
  writers now use one atomic-write helper that retries for up to about 2 s. The re-run passed 121 of 121.

## 3. Key results

- **Stage 1 (IDEALIZED):** all 19 parts fit. Shortest validated used length in a live run: 225.9 mm (NSGA-II + box
  decoder, 6 islands, 60 s). CP-SAT on single-box proxies reached 225.3 mm in 60 s (its bound is valid for the proxy
  problem only).
- **Stage 2 (ENGINEERING-CONSTRAINED, ASSUMED rules):** no feasible layout found for the full dataset — reported as
  "NO FEASIBLE LAYOUT FOUND (not proven infeasible)", never as VALIDATED. Constraint attribution: the U6 mounting rule
  has the largest effect (330.8 mm used length and violation 1.00 when relaxed, against 393.8 mm / 9.85 baseline).
- **Manufacturable Design (full dataset, 120 s search):** still infeasible (18.5 mm over the usable length, 1 part
  unmounted, 1 unplaced), with 16 hardware items including 6 conformal metal-AM brackets; all parts validated, all
  16 bracket clearance checks and all 120 bracket pairs pass; relative hardware cost 264.5, hardware mass 0.360 kg.
- **Benchmarks:** the hybrid did not meet the pre-registered adoption rule (wins on no instance, worse on I3 and
  I5); NSGA-II + box decoder has the best mean rank (3.19, Friedman p = 0.015). On the perfect-packing instance
  (optimum ≤ 200 mm) the shortest result was 231.0 mm, so the search leaves a measurable gap.
- **Size Study (1-hour demonstration, both stages, 5 seeds, 360 runs):** in Stage 1 the parts still fit when scaled
  by 1.109 in all three axes, right at the axis-aligned fit bound (1.111: the largest second-longest part dimension
  against the 100 mm envelope width). The best algorithm changes with size: height-map hybrid at 1.00, box hybrid at 1.05–1.10 and 1.109,
  constructive multistart at 1.106. In Stage 2 a valid layout was found only by the box hybrid, at scales 0.70, 0.80
  and 0.85 — none at full size. At small scales the decoder packs everything against the −Z end, which pushes the
  centre of mass outside the CDS box. The study ran 26 min past its cap because the cap was checked only between
  batches; that is fixed. A full 6-hour run has not been made.
- **Free rotation (19 parts, 120 s):** from the shortest validated axis-aligned layout (233.17 mm), 231.58 mm
  (−1.59 mm); the final layout re-checks valid on the meshes. Of the two parts left off-axis, one is the sphere
  (geometrically neutral), so the run does not show how much of the gain the rotations themselves made.

## 4. Limitations

- All Stage 2 rules (frame, rails, 2.2 / 1.2 mm clearances, PC/104 stack, 3 mm mounting layer, 10 mm harness) are
  ASSUMED stand-ins. There is no loads, vibration or thermal analysis, so nothing here is flight-qualified.
- Masses use the ASSUMED density of 2,700 kg/m³ unless you enter a mass or density.
- Brackets are manufacturing concepts: no stress analysis and no fastener holes in the meshes. The cost model is
  ASSUMED and uses relative units, so it is not a quote. AlSi10Mg is ASSUMED for metal AM.
- Orientations are limited to the 24 axis-aligned ones.
- The search works on proxies. The exact-mesh check certifies the layouts but does not prove that a layout is
  optimal. The only bounds are the volume bound and the CP-SAT proxy bound.
- In the HTML report, the views are convex-hull silhouettes, so concave parts look fuller than they are.

## 5. Blockers and decisions that are yours

- **Fusion 360:** not installed or configured, so cross-validation cannot start until you confirm it is.
- **Stage 2 is infeasible for this dataset under the ASSUMED rules.** Choosing which rule to change is an
  engineering decision that I have left to you. The attribution study shows the mounting rule matters most.

### Deferred Fusion 360 tasks

1. Install and configure Autodesk Fusion 360; this needs your confirmation.
2. Review the DRAFT script `fusion_import_t2s.py` from the export package, then run it in Fusion 360. It has never
   been run.
3. Convert the meshes to solids and run Fusion's interference analysis. Compare the result with the app's exact
   validation: the pairs checked and the minimum clearance.
4. Compare Fusion's physical properties (mass, COM, inertia) with `assembly.json`, using the same densities.
5. Build result ingestion in the CAD Validation tab. It does not exist yet.
