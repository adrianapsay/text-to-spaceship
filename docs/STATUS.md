# Implementation status (running log)

Every number below comes from a run on this machine (Windows 10, CPython 3.14.8) on the synthetic dataset (19 packable
parts, SHA-256 8dd56927…0f7f) unless stated otherwise. "Probe" numbers come from development scripts in `backend/scripts/`
and are not the M8 benchmark (no repetitions, no statistics).

## Milestones

| Milestone | State | Tested by |
|---|---|---|
| M0 toolchain (portable uv/CPython/Node/MinGit, no registry writes) | done | `backend/tools_smoke.py` |
| M1 STL pipeline, mass properties, canonical frames, classification | done | `test_geometry_core`, `test_massprops`, `test_dataset_golden`, `test_unseen_files` |
| M2 certified proxies G0–G4, validator, fit-proof certificate + stand-alone checker | done | `test_validator` (250-pair fuzz, 0 false accepts), `test_proof` (round trip + mutations) |
| M3 box decoder, slab post-optimiser, lower bounds | done | `test_decoder` |
| M4 live backend (project store, islands, validators, coordinator, REST + WebSocket) | done | `test_api` (11 tests) |
| M5 front end on the live backend | done | Playwright live suite (4), mock suite (4), Vitest (62) |
| M6 search: memetic BRKGA, LAHC, pymoo NSGA-II, height-map decoder, compaction, selector, detail ladder | done with deviations (below) | `test_selector`, `test_pymoo_accuracy`, `test_api` |
| M7 Stage 2 model and search, cable-slider modes, mounting, insertion order, least-violating reporting, constraint attribution, comparison view | done with deviations (below) | `test_stage2` (8), `test_api` Stage 2 + attribution, Vitest INFEASIBLE rules |
| M8 benchmarks, CP-SAT seed, Size Study, Explain backend (selector sweep / map, idea map) | done with deviations (below) | full benchmark run (1,480 runs), `test_api` CP-SAT / Size Study / selector + idea map |
| M9 Manufacturable Design (mount rules, brackets incl. conformal metal AM, exact bracket checks, cost, exports) | done with deviations (below) | `test_api` Manufacturable Design, full-dataset smoke run |
| M10 reports (Markdown / HTML), placed-STL ZIP, Fusion 360 export package (prepared only), CAD Validation tab | done; Fusion 360 validation NOT CONFIGURED | `test_api` reports / exports / package, live E2E |
| Free-rotation experiment (Stage 1, research) | done with a recorded deviation (M8 notes) | `test_free_rotation` (3), `test_api` |

## M6 deviations from the protocol (recorded, not hidden)

- **Voxel FFT engine → 2.5-D height-map decoder.** Columns of h × h mm with conservative per-column z-ranges
  (triangle–column clipping). No FFT correlation and no placement under overhangs (space below a part's underside
  counts as filled). It does see open bores and curved tops. Every layout is validated on the true meshes.
- **SLSQP / LP polish: not implemented.** The slab post-optimiser (constant length) runs on every new best.
- **Exact compaction:** implemented as certified drop compaction (swept convex cover pieces + bisection; sound by
  construction, re-validated). Measured gain on the three constructive box layouts: 0.00 mm (−Z only and with lateral
  pushes); it is applied only to would-be new bests from the box decoder and kept only if it shortens the used length.
- **Detail ladder:** F2 support polytopes and F5 decimated meshes are not implemented; the false-reject rate is not
  measured for F4 (column) levels; the ladder runs for Stage 1. Default run budget 600 s per part; parts added
  after start-up run it automatically, dataset parts on request (`POST /api/fidelity/run`).
- **Selector:** documented default rules (thresholds ASSUMED: packing weight 0.40 / 0.20, box-proxy overhead 25 %)
  until M8 benchmark evidence exists; the evidence path (nearest measured weights, best median score) is implemented
  and unit-tested.
- **NSGA-II:** pymoo 0.6.2 (decision U1) after passing the accuracy tests (non-dominated sorting = brute force on
  tie-heavy sets, hypervolume exact in 2-D and 3-D, IGD < 0.01 on ZDT1, constrained ask/tell).

## M7 deviations and modelling choices (all ASSUMED rules are labelled in the app)

- **U6 mounting layer** modelled as a 1.8 mm pad reserved on each part's largest face (any orientation), so that
  side ends 3.0 mm from its wall / end plate / rail / PC/104 deck; reach ≤ 5 mm beyond the layer. All other sides
  keep the 1.2 mm clearance. The *face* is fixed (largest face); its direction is the search's choice.
- **Edge-standing boards** (continuous-cable mode): option (b) only — four M3 standoffs (5 × 5 mm envelope,
  3–50 mm, lengthened to the facing wall when the path is clear). Card guides (option a) are not implemented.
- **Volume between stacked PCBs is reserved** for board components (ASSUMED); nothing else is placed there.
- **Thermal tags, connector-access zones and cable bend radius:** not modelled (as in the protocol, "inactive until
  tagged" / "NOT MODELLED").
- **Overflow model:** the Stage 2 decoder may stack parts beyond the end plate; overflow is a violation the search
  minimises. A candidate that breaks any engineering rule is certified under relaxed rules and reported as
  INFEASIBLE ("NO FEASIBLE LAYOUT FOUND (not proven infeasible)"), never as VALIDATED.
- **Constraint attribution** rows are search results under relaxed rules (box-feasible by construction, not
  certified), equal effort per row (fixed generations), baseline repeated with a second seed to show noise.
- **Stage 2 search uses the box decoder only** (the height-map decoder has no keep-out model).
- **COM-centring shift (added after the Size Study showed small layouts failing the COM box):** after each Stage 2
  decode the whole layout moves along Z (stack, rods, harness breaks and reserve included): at least far enough to
  put the parts' COM inside the CDS box (|z| ≤ 69.5 mm, 0.5 mm margin), further toward the envelope centre as a
  third extra key asks (the chromosome is now 3n + 3; the constructive baseline uses the minimal shift). It is
  limited by the end plates (padded proxy boxes keep the wall clearance; no overflow), never taken if it would
  mount fewer parts (up to three candidate shifts are compared), and off with locked parts, unplaced parts, an
  overflowing layout, a withheld mass, or the COM-box rule relaxed (attribution study). For the same keys it can
  only lower the constraint violation. The used length is still measured from the −Z end plate, so a shift
  lengthens it by the shift distance.
- **"INFEASIBLE (proven)"** is never claimed: no Stage 2 bound proof is implemented.

## M8 notes

- **Benchmark protocol:** fixed budget of 5,000 box-decode equivalents per run, 10 seeds, 4 weight presets, instances
  I1 (19 parts, Stage 1), I2 (19 parts, Stage 2), I3 / I4 (8- and 12-part subsets), I5 (perfect packing, optimum ≤
  200 mm); Wilcoxon + Vargha–Delaney A12 + Holm, Friedman over instance × preset blocks. Results:
  `docs/benchmarks/full-b5000-benchmarks.json`.
- **The hybrid did not meet the pre-registered adoption rule** (A12 ≥ 0.64 with Holm p < 0.05 on at least half the
  instances, worse on none): it wins on none and is worse on I3 and I5. The selector therefore uses the measured
  evidence (nearest instance, nearest weights, best median score) instead of preferring the hybrid.
- **I2 (Stage 2) was run only for V1, V4, V5, V6 with the balanced preset** and produced no feasible layout in any
  of its 40 runs.
- **CP-SAT** solves the single-box proxy problem only (0.1 mm grid); its bound is valid for that proxy problem, not
  for the true shapes. Its layout is validated like any other.
- **Size Study** is implemented (scan → bisection → successive halving, 6 h cap, stops on convergence or a proven
  optimum), tested with tiny budgets (`test_api`) and run once for 1 hour as a demonstration (below); no 6-hour run
  yet. The time cap used to be checked only between batches (the demonstration overran by 26 min); queued runs are
  now cancelled as soon as the cap is reached.
- **Free-rotation experiment** (Stage 1, research, reported separately): implemented as a greedy rotate-and-drop
  local search from the shortest validated axis-aligned layout, every kept pose checked exactly on the meshes (FCL +
  containment trap, envelope on hull vertices) and the final layout re-checked from scratch. Deviation: the
  protocol's quasi-phi penalty with L-BFGS-B and CMA-ES restarts is not implemented. The rotated layout is not shown
  in the 3D viewports (they draw the 24 axis-aligned orientations only).
- **PNG export** of the views is not implemented (the HTML report carries SVG views).

## M9 deviations and modelling choices (labelled "manufacturing concept — assumed cost model, not a quote; brackets not stress-analysed")

- **Mount rules (ASSUMED):** bracket reach 40 mm; flat side (≥ 60 % planar) → direct fasteners ≤ 3.5 mm, machined
  block ≤ 15 mm, sheet Z-bracket beyond; symmetric elongated / curved bodies → tube clamp; otherwise a conformal
  metal-AM bracket (AlSi10Mg, decision N2). Relative cost units (N1): fastener 0.1, catalogue 1, sheet 3 + 0.5 per
  bend, machined 5 + 0.5 / cm³, metal AM 10 + 2 / cm³ + 1 support.
- **Conformal AM brackets** are a signed-distance level set (2 mm shell at a 0.3 mm gap, 2 mm plate, 2.5 mm ribs)
  built clear of the other parts' certified boxes plus 1.2 mm + margin, then checked exactly (FCL distance +
  containment probes both ways). A bracket that still fails is rebuilt with a larger margin, then replaced by a
  labelled machined block. Bracket-to-bracket pairs are checked exactly too.
- **Not modelled:** loads, stiffness, fastener holes in the meshes, thermal paths; AM rules are reported (wall by
  construction, overhang share per best build axis, build-volume fit), supports only counted in the cost.
- **Algorithm choice:** the selector's Stage 2 rule for the manufacturable weights (box decoder: mount synthesis needs
  its frame, rail and keep-out model); the height-map decoder is not available in this tab.

## M10 notes

- Reports are built from the archived layout, the part records and a fresh full proof; nothing is re-estimated. The
  HTML report draws convex-hull silhouettes (concave parts look fuller than they are) and hatches metal-AM brackets.
- **FUSION 360 VALIDATION: NOT CONFIGURED.** The export package is prepared only; it contains a DRAFT import script
  that has never been run and a list of the deferred Fusion 360 tasks. No Fusion 360 API call is made anywhere.

## Measured so far

| What | Result |
|---|---|
| Box decoder, one random-key decode (19 parts) | 12.63 ms → 2.98 ms after compiling the whole decode (200 decodes) |
| One BRKGA island (box decoder) | 306 evaluations/s |
| Constructive box decoder, used length (orders: volume / box volume / max dim / min dim) | 266.6 / 250.0 / 293.3 / 258.5 mm, all validated |
| Constructive height-map decoder h = 2 mm | 295.0 / 304.9 / 281.5 / 245.2 mm, all validated; 6.1 ms per random decode |
| Constructive height-map decoder h = 1 mm | 272.3 / 310.8 / 280.7 / 243.4 mm, all validated; 84.9 ms per random decode |
| 20 s, one island, "maximum packing" weights | box decoder L ≈ 261–263 mm; height-map decoder L ≈ 250–252 mm (3 seeds) |
| Live, 6 islands, 60 s, mixed run | shortest validated L 225.9 mm (NSGA-II, box decoder); best by score 233.7 mm, D 40.3 mm |
| Settings edit → `edit.ack` | 7.1 ms; mass edit → `metrics.update` 63 ms (≈ 250 archived layouts re-computed) |
| Proof for a live layout | 0.30 s; stand-alone checker OVERALL: PASS |
| Detail ladder, torus, 10 levels (before the convergence fix) | 515 s; F3-16 cover build alone 118 s |
| Stage 2 used length in a 700 mm test box, box decoder, 20 s GA, no mounting / COM | default 416.7 mm, soft 347.6 mm, continuous 367.4 mm (usable ≈ 334 mm) |
| Stage 2, one island, 90 s, all rules | default: 13.1 mm over, 2 parts unmounted; soft: 56.7 mm over, all mounted; continuous: 4.2 mm over, 3 unmounted |
| Live Stage 2 (4 islands, ~60 s, default mode) | NO FEASIBLE LAYOUT FOUND; least-violating L-0463: 78.2 mm over, 3 parts unmounted |
| Full benchmark (5,000 decodes per run, 10 seeds, 8 workers) | 1,480 runs in 2,146 s; 1,461 outputs validated, 0 invalid; Friedman p = 0.015, mean ranks V9 NSGA-II 3.19, V5 hybrid 3.94, V4 BRKGA+LS 4.13 … V1 constructive 6.50 |
| Benchmark, I5 perfect packing (optimum ≤ 200 mm) | shortest found 231.0 mm (V4, min-inertia preset); best median under max-packing weights 250.6 mm (V1): no variant got within 31 mm of the optimum |
| Benchmark, shortest used length found per instance | I1 250.0 mm (V6), I3 119.6 mm (V4), I4 162.5 mm (V1), I5 231.0 mm (V4) |
| Benchmark, I1 balanced preset | best median score V9 (median L 285.5 mm, best 278.4 mm) |
| CP-SAT single-box proxy, I1, 60 s | 225.3 mm |
| Size Study demonstration, project `default`, both stages, 5 seeds, max-packing preset, 9 workers, 1 h cap | 360 runs in 5,185 s (stop: time limit). Stage 1 largest feasible scale 1.109 (V1 and V5; V7 1.100) against the axis-aligned fit bound 1.111; winners by scale: V7 at 1.00 (268.6 mm), V5 at 1.05 (274.1 mm) and 1.10 (298.9 mm), V1 at 1.106 (295.0 mm), V5 at 1.109 (291.8 mm). Stage 2: no valid layout at 1.00 → scanned down; validated only by V5 at 0.70 (209.6 mm), 0.80 (271.0 mm), 0.85 (302.8 mm); none at 0.50–0.65, 0.75, 0.90–1.00 |
| Size Study, Stage 2 at small scales | the box decoder packs from the −Z end, so the centre of mass of small layouts falls outside the CDS box: COM distance from the target at scale 0.50: V1 132.8 mm, V5 122.1 mm; at 0.75 / 0.80: V5 49.5 / 49.8 mm (best rows of the scan, read during the run) |
| COM-centring shift, before → after: 300 random Stage 2 decodes per case, placed layouts with the COM inside the CDS box | scale 0.7 (all 300 placed): default 109 → 218, soft 32 → 151, continuous 51 → 194; scale 1.0: default 27 / 189 → 35 / 206, soft 142 / 300 → 151 / 300, continuous 17 / 54 → 14 / 57 (full-size layouts overflow the end plate, so they are never shifted, and the new key changes the random draws). No decode was fully rule-feasible in any case, before or after |
| COM-centring shift, before → after: GA, 10 seeds, 8 + 30 generations × 40, default sliders | scale 0.7 default: feasible 0 → 0, COM in box 8 → 10, mean violation 2.05 → 1.80, mean \|COM z\| 61.5 → 52.1 mm, used length 216.5 → 222.7 mm; 0.7 soft: 0 → 0, 5 → 8, 2.10 → 1.64, 66.4 → 60.8 mm, 206.6 → 200.4 mm; 0.8 default: 0 → 0, 10 → 10, 2.10 → 1.70, 28.1 → 15.0 mm, 303.1 → 296.7 mm; 0.8 soft: **2 → 0**, 10 → 10, 1.40 → 1.60, 39.7 → 37.2 mm, 273.9 → 275.2 mm. Overall 2 / 40 → 0 / 40 feasible (not a significant difference at this sample size); the remaining violations are unmounted parts |
| COM-centring shift, before → after: Size Study, Stage 2 only, 5 seeds, 9 workers, 30 min cap, identical settings | before: 154 runs in 1,951 s, no valid layout at any scale 0.50–1.00; after: 154 runs in 1,928 s, no valid layout at any scale. COM distance of the best rows at scales 0.50–0.70: 66–133 mm before → 69.6–70.8 mm after (V5 at every scale, V1 at 0.50, 0.55, 0.70; V1 stayed at 107.3 mm at 0.60 and 90.1 mm at 0.65), i.e. the COM now sits at the box edge; the parts that cannot be mounted remain |
| COM-centring shift in the live app (test project, 4 parts, Stage 2) | VALIDATED layout L-0011: shift 53.1 mm, COM z −122.6 → −69.5 mm, all parts mounted; a later best L-0053: shift 75.6 mm, COM \|z\| 30.5 mm (PASS); the Engineering tab shows the shift |
| Free-rotation experiment, 19 parts, 120 s, from L-0456 (233.17 mm, hybrid height-map) | 231.58 mm (−1.59 mm), 17 moves kept, 76,229 exact pair checks, final re-check valid, min distance 0.0036 mm; parts left off-axis: propellant_tank_sphere 36.4° (geometrically neutral), irregular_blob 20.1° |
| Manufacturable Design, full dataset, default harness mode, 120 s search | 172 s total; NO FEASIBLE LAYOUT FOUND: 18.5 mm over, 1 part unmounted, 1 unplaced; 16 hardware items incl. 6 conformal metal-AM brackets (27.7–74.3 g), relative cost 264.5, hardware 0.360 kg; parts validated (153 pairs), 16 / 16 bracket checks and 120 bracket pairs pass |
| Conformal AM bracket construction (1 mm grid, compiled SDF) | sphere 9.5 s, blob 18.4 s (pure-Python SDF: 84 s) |
| Constraint attribution, default mode, 25 generations × 40 per row | baseline 393.8 mm / violation 9.85; clearances → Stage 1: 339.0 mm; no walls/rails: 346.0 mm; free boards: 363.6 mm; no harness: 397.4 mm; **no mounting rule: 330.8 mm, violation 1.00**; COM box off: 413.4 mm (noise) |
