# WS2 (code part): search until Pause, bounded memory, running time

Branch `ws2-search-until-pause`. Plan: "WS2" and review items 3 and 5.

## Search until Pause

* **No automatic stop.** `Coordinator._tick` no longer sets CONVERGED (it did after 15 + 6 × speed/quality s without
  improvement, and after 6 h). Pause is the only stop; it still starts the automatic bracket design
  (`_set_status("PAUSED")` → `_maybe_auto_design`). The CONVERGED branches are gone from `_tick`, `_refresh_inputs`,
  `_select_best`, `_set_status`, `apply_settings`, `apply_part_patch` and `_on_bracket_design`.
* **Unchanged:** the search starts on launch; Resume / Optimise continue; Re-run restarts the islands with new seeds;
  a settings change while paused does not restart the search, while searching it goes on; the saved-STL settle logic
  (`_settle_at`, `_drop_saved_brackets`) is untouched.
* **Front end:** `RunStatus` has no CONVERGED. Engineering tab: with no feasible Stage 2 layout, "No feasible layout
  yet after N min of search (not proven infeasible; still searching)" while searching, "NO FEASIBLE LAYOUT FOUND after
  N min of search" when paused. The mock pauses (with a MOCK message) when its fixed attempt budget runs out.
* **Not mine:** `frontend/src/tabs/Hardware.tsx` line 332 still says "when the search pauses or converges".

## Speed / quality slider

* In the real backend `speed_quality` had exactly one effect: the stall time above. `select_algorithm` and the
  workers never read it (only the MOCK placeholder selector in `mock/content.ts` does).
* With the stall rule gone it changes nothing, so it is **no longer a search setting** (`NOT_SEARCH_SLIDERS`, left out
  of `_settings_view`): moving it neither removes the saved bracket STL files nor waits for a settle. It is hidden
  from the Goals panel (`copy.ts`: `notInGoals`); the setting key stays for compatibility. `Explain.tsx` still lists it
  in its selector sweeps (Expert): a flat sweep.

## Running time ("running M min")

* Time spent SEARCHING per search context (`ctx_id`); pauses do not count; a return to inputs searched before adds to
  their time; Re-run and Reset start it from zero. It counts this session only (not saved).
* Sent as `elapsed_s` in every `progress` message (it used to be the time since `search_t0`, pauses included), once on
  every status change and in `state.snapshot`, so a paused search still shows it.

## Recommended minimum (provisional)

* `backend/src/t2s/bench/convergence_table.py`, keyed by CubeSat size; 6U and 12U: none (`recommended_min_s: null`,
  the note says so). Status bar and Optimization tab: "recommended minimum N min · running M min", tooltip with the
  basis.
* **Measured** (read-only, streaming) from the user's archive: the 7.5 h run of 2026-10-24 (00:04:08–07:33:19 UTC),
  Stage 2, 3U, part size 54 %, one context (parts_sig `d9acc1360120c3ea`, spec_sig `2a65c8de635bde35`, 7,165 VALIDATED
  of 7,393 layouts). Longest gap between two layouts 105 s (no long pause); sliders unchanged for the first 367 min.
  Best used length L of VALIDATED layouts against the time since the run's first layout:

  | min | 3.3 | 7.4 | 13.9 | 20.8 | 29.8 | 35.1 | 98.8 | 121.2 | 179.7 | 265.0 | 291.0 | 318.0 |
  |---|---|---|---|---|---|---|---|---|---|---|---|---|
  | L (mm) | 171.6 | 160.3 | 149.0 | 148.9 | 147.6 | 145.1 | 144.0 | 143.6 | 143.3 | 143.1 | 142.87 | 142.868 |

  The reviewer's 147.6 at 30 min, 145.1 at 35 and 144.0 at 99 are confirmed; "142.9 at 318" is 142.873 mm, first
  reached at 291.0 min — the run's best, 142.868 mm, came at 318.0 min, with no improvement in the remaining 131 min.
* **Rule:** the time after which the best L stayed within 1 % of the run's best: 5,930 s = 98.8 min (within 2 %:
  35.1 min; 0.5 %: 179.7 min; 5 %: 13.9 min). Shown as "recommended minimum 99 min".
* Wall time on this PC: the run has no evaluation counts, so the plan's "evaluations converted with the live rate"
  waits for Milestone 3 (≥ 10 seeds + a reference run, idle machine). The search started at most 16 s before the
  run's first layout (after the previous context's last layout).
* Reproduce: `set PYTHONPATH=src && uv run python -m t2s.bench.convergence_table <archive.jsonl> d9acc1360120c3ea
  2a65c8de635bde35`.

## Bounded memory (`backend/src/t2s/service/archive.py`)

* **Cold store.** `archive.jsonl` stays append-only; the last line of an id wins. `LayoutArchive` indexes the byte
  offset of each id's last line (a regex reads id, hash, stage, status, parts_sig and spec_sig from the line head;
  other lines are parsed in full). It is dict-like: `[]`, `.get`, `in`, `len` and iteration cover every layout;
  `.values()` / `.items()` only those in memory. A layout read back is brought up to date for the current inputs
  (`_hydrate`: physics, revisions, score), as the layouts in memory are.
* **What stays in memory** (`_enforce_memory`, every 5 s, once more than 800 are in memory): best, least-violating,
  FINAL, the layout of a bracket design run or an STL save under way, the last 32 read on request, the 500
  best-scoring layouts of the current inputs and the 200 newest. Everything else is on disk only.
* **Why rows, not the non-dominated layouts in memory:** in the user's 7.5 h run, 1,669 of the 7,165 VALIDATED
  layouts are non-dominated in the six objectives of g (L, D, T, P, G, C; 700 in L, D, T), and the set keeps growing
  (207 of the first 500, 361 of 1,000, 611 of 2,000, 1,000 of 4,000): kept as full layouts (0.12 MB each) it would
  not stay bounded. As rows it costs a few floats per layout, and every choice stays exact.
* **Objective table.** One row per layout of the current inputs (class, cv, finite raw objectives: a few floats). The
  best (`_select_best`: (cv, g, L, id)), the least-violating ((cv, g, id)), the candidate filter in `_on_island`
  (dominated in L, D, T) and the normaliser's ranges (`_maybe_new_epoch`) use it, so a layout on disk still counts. g
  is vectorised; the near-ties are re-scored with `_score_raw` itself, so the choice is the one the full scan made.
  The table is rebuilt (reading the context's layouts one at a time) when the inputs, the mass revision or the COM
  target change; the tables of the last 4 contexts are cached for a return to them.
* **Pareto plot.** An incremental non-dominated filter (`ParetoFront`) replaces the two N × N × 3 arrays: a new layout
  costs O(front); the front is recomputed from the table (O(N · front)) only when the normaliser epoch, the
  mass-symmetry slider (α) or a layout's values change. One difference: two layouts with exactly equal (L̂, D̂, Î) are
  both shown only if both are non-dominated in all raw objectives.
* **Compaction** at start (`_load_archive`) when at least 200 lines, and a fifth of all lines, are superseded by later
  lines of the same id (designed brackets, FINAL; the user's archive: 99 of 9,720, so not now). FINAL no longer
  rewrites the whole archive (it appends; Reset still rewrites it, keeping FINAL layouts).
* **Also bounded:** proofs cached (last 32), candidate pools of the last 4 contexts, `_qual` of the current context,
  `best_g_hist` (last 1,000).
* **Also fixed:** `/api/layouts` sorted ids as strings, so "L-10000" would come before "L-9999" (the user's archive
  reaches L-9622): now by number.
* `_compute_physics` is faster (same results: identical output on 1,196 of the user's Stage 2 layouts): the bracket
  mounts are no longer walked again by `jsonable`, the frame mass is computed once per CubeSat size, and the table
  build computes the part mass properties once.

### Measured (this PC, copy of the user's project; machine shared with other agents)

| | before (HEAD) | now |
|---|---|---|
| start: read the archive (9,621 layouts, 362 MB) | 1.6 ms and ~0.21 MB RSS per layout (1,196-layout sample): ≈ 15 s, ≈ 2 GB | index: 0.16–0.38 s, +4 MB RSS |
| one archived Stage 2 layout in memory | 0.119 MB (tracemalloc) | only if kept (≤ 800 + pinned) |
| physics of a 7,393-layout context | 0.89 ms per layout in memory (6.6 s) | table rebuild 7.4 s (1.0 ms per layout, read + parse + physics), +3 MB RSS, 3.4 MB peak |
| synthetic stream, 5,000 layouts (13.8 kB JSON each) | — | ≤ 800 in memory; +660 B per layout (index, row, hash) |
| best layout / candidate filter / Pareto plot (7,393 rows) | O(N) scans; N × N × 3 arrays (~170 MB each at 7.5k) | 0.4–0.6 ms / 23–28 µs / ~10 ms |
| newest 200 for the layout lists | in memory | 107 ms (read back) |

## Risks, not done

* **Disk:** every layout stays in `archive.jsonl` (~40 kB per Stage 2 layout): 18–68 MB per hour at the user's 450–1,700
  layouts per hour, indefinitely. Nothing deletes layouts.
* **Pauses of the event loop:** a table rebuild takes ~1 ms per layout of the context (7–8 s at 7,400) after a mass
  edit, a COM-target change, or a return to inputs not among the last 4 — about what the in-memory physics pass took
  before, without its memory.
* The recommendation is one run of one setting on a shared PC; Milestone 3 replaces it.
