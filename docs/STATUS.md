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
| M7 Stage 2 search, cable modes, comparison | planned | — |
| M8 benchmarks, Size Study, Explain backend | planned | — |
| M9 Manufacturable Design | planned | — |
| M10 exports, CAD package, final report | planned | — |

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
