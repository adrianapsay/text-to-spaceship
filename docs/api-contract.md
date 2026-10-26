# API contract (backend ⇄ front end), v1

Backend: FastAPI on `http://127.0.0.1:8768`, bound to localhost only. The front-end dev server proxies `/api` and `/ws` to it.

**Wire units:**

| Quantity | Wire format |
|---|---|
| Length | mm (float). **Poses use integer micrometres** |
| Mass | kg |
| Inertia | kg·m² (tensor convention I = ∫(‖r‖²E − rrᵀ)dm, so off-diagonal = −∫xy dm) |
| Angles | degrees |

Everything is JSON unless stated. Field names are snake_case.

## 1. Frames and poses
- **World frame.** Origin at the enclosure's geometric centre; +Z along the rails (the 340.5 mm axis); right-handed. The Stage 1 enclosure spans x, y ∈ [−50, 50] and z ∈ [−170.25, 170.25].
- **Part canonical frame.** Each part's mesh is served in its *canonical frame*. The origin is the centre of the part's canonical AABB, and the axes are the canonical axes chosen by the backend.
- **Pose** = `{part_id, orient, t_um: [x, y, z]}`.
  - `orient` ∈ 0..23 indexes `project.rotations` (24 integer 3×3 matrices, row-major, det = +1).
  - World point = R[orient] · p_canonical + t_um / 1000.
  - The rotation table is sent in the project snapshot. The front end must use it and never hard-code its own.

## 2. Objects

### Part
```json
{
  "id": "p03", "name": "battery_pack", "file": "battery_pack.stl", "sha256": "…",
  "units": "mm", "units_confirmed": true,
  "status": "VALID" | "REPAIRED" | "WITHHELD" | "NEEDS_UNITS" | "ANALYSING",
  "status_detail": "string (plain language, e.g. 'open mesh — 3 holes')",
  "repairs": ["flipped winding", "..."],
  "triangles": 12, "display_triangles": 12,
  "subsystem": "power|electronics|adcs|tanks|payload|structure|unknown",
  "labels": ["box-like", "convex"],
  "extents_mm": [80, 80, 22],
  "volume_mm3": 140800.0,
  "density_kg_m3": 2700.0, "mass_kg": 0.38016,
  "mass_source": "ASSUMED" | "USER_MASS" | "USER_DENSITY" | "WITHHELD",
  "com_canonical_mm": [0, 0, 0],
  "inertia_com_kgm2": [[...],[...],[...]],
  "principal_kgm2": [a, b, c],
  "solidity": 1.0, "obb_fill": 1.0,
  "allowed_orients": [0, 1, ...],
  "locked": false, "lock_pose": null,
  "tags": ["pcb" | "heat_source" | "temp_sensitive" | "needs_wall" | "serviceable" | ...]
}
```

### Layout
```json
{
  "id": "L-0042", "hash": "…", "stage": 1 | 2, "mode": "default" | "continuous_cable" | "manufacturable",
  "status": "CANDIDATE" | "VALIDATING" | "VALIDATED" | "REJECTED" | "STALE" | "FINAL",
  "parts_rev": 3, "constraint_rev": 7, "mass_rev": 2, "weights_rev": 11,
  "poses": [Pose, ...],
  "extra_items": [{"id":"b01", "kind":"bracket", "process":"metal_am|sheet|machined|catalogue|direct|card_guide|standoff",
                   "for_part":"p07", "mesh_url":"/api/items/b01/mesh", "mass_kg":0.012, "cost_rel":14.2}],
  "metrics": {
    "length_used_mm": 214.0, "span_mm": 208.5, "space_used": 0.317, "largest_empty_box_mm": [96, 96, 120],
    "mass_kg": 2.916, "com_mm": [0.4, -0.2, -55.1], "com_error_mm": 55.1, "com_box_ok": true,
    "com_box_margin_mm": [19.6, 19.8, 14.9],
    "inertia_kgm2": [[...],[...],[...]], "principal_kgm2": [..], "principal_axes": [[..],[..],[..]],
    "lambda_max_kgm2": 0.0103, "trace_kgm2": 0.022, "products_norm_kgm2": 1.2e-5, "kappa": 0.004, "tilt_deg": 1.2,
    "min_clearance_mm": 0.005, "margin_objective": 0.4, "cable_blocked_fraction": 0.0, "hardware_cost_rel": 0.0,
    "insertion_order": ["p01", "p05", ...] | null, "interlocked": [["p11","p10"]] | []
  },
  "scores": {"normalised": {"L":0.2, "D":0.5, "I":0.3, "G":null, "H":null, "C":null}, "g": 0.41, "norm_epoch": 2},
  "algorithm": {"id": "hybrid_box", "label": "Hybrid BRKGA + box decoder", "reason": "…"},
  "validation": {"certified": true, "validator_version": "1.0", "tolerance_mm": 0.001, "pairs": 171,
                  "checked_at": "ISO time"},
  "origin": "archive" | "search" | "user" | "import",
  "created": "ISO time"
}
```
Status `INFEASIBLE` (Stage 2 only): certified collision-free under the layout's own rules, but breaking an engineering
rule (outside the enclosure, a part not mountable, COM outside the CDS box, no ±Z insertion order). Stage 2 layouts
also carry `label` ("ENGINEERING-CONSTRAINED — not flight-qualified"), `violations_engineering: [text]`,
`verdict` (INFEASIBLE only) and `stage2: {mode, corridor, stack_span_mm, overflow_mm, unmounted, mounts, frame:
[{kind, id, min, max}], insertion_order, com_shift_mm, com_z_unshifted_mm, rod_end, brackets, hardware_cost_rel,
bracket_designs, bracket_overrides, assumed, com_first}`; mounting hardware (standoffs, V2 brackets, the PC/104 rods
with their spacer tubes) appears in `extra_items`. `com_shift_mm` is how far every part except the PC/104 boards was
moved along +Z by the COM-centring shift (0 when there was no room, no need, or a shift would have cost a mount; the
boards stay on their rods at their end plate, `rod_end` `-z` or `+z`, V2 rules v2.5); `com_z_unshifted_mm` is the
parts' COM height before it. `bracket_designs` holds each designed bracket's record (mass, margins per load case,
governing check, flags, its settings and the automatic run's ladder), `bracket_overrides` the user's per-bracket
settings. `com_first` is true for a layout found in centre-of-mass-first mode (Stage 2 with `balance` and
`bracket_budget` both at 100; V2.md §2.2): full centring along Z and brackets of any length (beyond 40 mm metal
3D-printed only). Reaching or leaving that point restarts the search.
M4 adds `bracket_layout` (the bracket layout the views use: `per_part`, `combined` or `one_piece`),
`bracket_layout_chosen` and `bracket_layout_designs` (`{extra item id: record}` of the combined brackets / the one
piece shown). Their `extra_items` have `kind: "bracket"`, `bracket_kind: "combined" | "one_piece"`, `for_parts`
(every part held), `layout_mode`, `layout_key`, `solid_mass_kg`, `fastener_mass_kg`, `fasteners`, `passed`,
`size_mm`; ids `<layout>-cb<k>` and `<layout>-op`; they replace the per-part brackets of the parts they hold.

### Settings
```json
{
  "stage": 1 | 2,
  "sliders": {"space": 25, "balance": 25, "inertia": 25, "feasibility": 25, "mass_symmetry": 50,
              "cable": 0, "cost": 0, "speed_quality": 50},
  "target_com_mm": [0, 0, 0],
  "compactness_definition": "one_end" | "span",
  "show_frame_mass_in_com": false
}
```
- Slider values are 0..100.
- `feasibility` is ignored in Stage 1; the UI greys it out.
- `cable` and `cost` matter only in Stage 2 and the Manufacturable Design tab.
- `speed_quality` is kept for compatibility but changes nothing since the search runs until Pause (it only set how
  long the search waited without improvement before stopping itself): the UI no longer shows it, and moving it does
  not count as a settings change for the saved bracket STL files.
- V2 adds `part_scale_pct` (50–100), `form_factor` (`3U` / `6U` / `12U`), the sliders `bracket_budget` and
  `optional_parts`, `auto_design_brackets` (default true), `launch_environment` (a `/api/design-options`
  environment id, default `gevs`) and `bracket_material` (an AM material id, default `AlSi10Mg`). An unknown
  environment or material is refused: 400 over REST, an `error` message over WebSocket; nothing changes.

## 3. REST endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | `{ok, version}` |
| GET | `/api/project` | Project snapshot: `{name, enclosure, rotations, parts[], settings, stage2_frame, limits, revs}` |
| POST | `/api/parts` (multipart `files[]`, optional `units`) | Add STL files; returns the new Part records (may be NEEDS_UNITS) |
| POST | `/api/parts/{id}/units` `{units}` | Confirm units (`mm`, `cm`, `m`, `in`) |
| PATCH | `/api/parts/{id}` | `{mass_kg?, density_kg_m3?, locked?, allowed_orients?, tags?, subsystem?}` |
| DELETE | `/api/parts/{id}` | Remove a part |
| GET | `/api/parts/{id}/mesh?lod=display\|full` | Binary: `uint32 nv, uint32 nt, float32[3nv] positions (canonical frame, mm), uint32[3nt] indices` (little-endian) |
| GET | `/api/parts/{id}/proxy?level=G1\|G2\|G3` | JSON `{boxes: [[minx..maxz]...]}` or `{hulls: [{positions, indices}]}` |
| PUT | `/api/settings` | Settings object (also possible over WebSocket) |
| POST | `/api/run` `{action: "start"\|"pause"\|"resume"\|"reset"\|"rerun"}` | Optimiser control |
| GET | `/api/layouts?status=&limit=` | Archive list (metrics only), newest first by layout number; layouts kept on disk only (bounded memory) are read back for the answer |
| GET | `/api/layouts/{id}` | Full layout |
| POST | `/api/layouts/{id}/final` | Freeze as FINAL (full re-validation) |
| GET | `/api/layouts/{id}/proof` | `{markdown, certificate}` |
| GET | `/api/layouts/{id}/proof/download?kind=md\|json\|checker` | Files |
| GET | `/api/selector` | Current choice `{algorithm, reasons[], evidence[]}` |
| GET | `/api/selector/sweep?slider=space` | `{slider, values:[0..100], choices:[algorithm_id...], legend:{id:label}}` |
| GET | `/api/selector/map?x=space&y=balance&n=41` | 2-D grid of algorithm ids |
| GET | `/api/ideamap` | `{nodes:[{id,label,kind,tab,detail}], edges:[{from,to,label}]}` |
| GET | `/api/pareto` | `{points:[{layout_id, L, D, I, ...}], hv, norm_epoch}` |
| GET / POST | `/api/benchmarks`, `/api/benchmarks/run` | Results table, run trigger |
| GET / POST | `/api/studies/size`, `/api/studies/size/run` | Size Study results / start |
| GET | `/api/experiments/free-rotation` | Free-rotation experiment (Stage 1, research, reported separately): `{status, label, method, start_layout_id, start_length_mm, length_used_mm, improvement_mm, valid, min_distance_mm, gap_mm, seconds, rounds, accepted_moves, exact_checks, rotated:[{part_id, name, angle_deg}], history:[{t_s, length_mm}], poses:[{part_id, R, t_mm}]}`; 404 until run |
| POST | `/api/experiments/free-rotation/run` `{budget_s?, seed?}` | Start it from the shortest validated Stage 1 layout of the current parts (background, default 120 s; progress as `study.update` with `study: "free_rotation"`) |
| GET | `/api/mfg` | Manufacturable Design result for the current parts: `{status: "RUNNING"\|"DONE"\|"ERROR", label, mode, seconds, evaluations, weights, bracket_reach_mm, algorithm:{id,label,reason}, layout_id, feasible, layout_status, verdict, violations[], com_mm, validation:{parts_valid, pairs, statics, violations, brackets:[{item_id, ok, min_clearance_mm}], bracket_pairs_checked, bracket_conflicts[], relaxed_rules}, items:[{id, item_id, for_part, part_name, mount_type, process, material, mass_kg, cost_rel, fasteners, label}], am_rules:[{item_id, rule, value, limit, pass}], total_cost_rel, hardware_mass_kg, exports:[{kind, url, label, metal_am?}]}`; 404 until run |
| POST | `/api/mfg/run` `{budget_s?}` | Start it (background, default 90 s search); 409 while one runs. The layout is archived as Stage 2, mode `manufacturable`, with the hardware as `extra_items` |
| GET | `/api/gd/contest` | V2 generative-design contest results (`data/gd_contest/results.json`) |
| POST | `/api/layouts/{id}/design-brackets` `{pids?, overrides?}` | V2: design the layout's metal-AM, cradle and clamp brackets (background; progress as `study.update` with `study: "bracket_design"`). `pids`: only these brackets (the others keep their designs); `overrides`: `{part id: {material?, vol_frac?, min_member_mm?}}`, each a value or `"auto"` (material `null`: the project default), kept with the layout. 400: a bracket not in the layout or a value out of range; 404: unknown layout; 409: nothing to design, or a run in progress |
| GET | `/api/items/{id}/fea` | V2: a designed bracket's FEA colour maps — a per-part bracket (`<layout>-br<k>`), a combined bracket (`<layout>-cb<k>`) or the one piece (`<layout>-op`): `{available, why?, fields: [{id, label, unit, kind, case, axis, max, max_all}], environment, environment_name, material, yield_mpa, ultimate_mpa, solvers, n_vertices, voxel_mm (mm; per axis for a combined bracket and the one piece), note, part_id (null for a combined bracket and the one piece), parts, kind, passed, governing, ms_yield, ms_ult, ms_bolt, f1_hz, checks, bolt_checks}`; `max_all` is the field's largest value over every voxel / FE node (what the margins use). `why` when there are none: designed before they were saved, or its two-solver check did not run (memory). 404 when the item is not a designed bracket |
| GET | `/api/items/{id}/fea/{field}` | V2: one field, float32 little-endian, one value per vertex of `GET /api/items/{id}/mesh` |
| GET | `/api/design-options` | V2: `{environments: [preset summary], materials: [{id, name, process, E_mpa, yield_mpa, ultimate_mpa, density_g_cm3, source}], allowables, machined, vol_frac: {range, ladder}, min_member_mm: {range, am_min_wall_mm, generator_sets_member_size}, generator, launch_environment, bracket_material}` |
| GET | `/api/layouts/{id}/bracket-layouts` | M4: the layout's three bracket layouts side by side: `{layout_id, chosen, active, modes: {per_part \| combined \| one_piece: {mode, name, status: "designed"\|"not designed"\|"not run", summary: {bracket_mass_kg, estimates, worst: {case, axis, check, ms, bracket, parts} \| null, f1: {f_hz, bracket} \| null, prints, largest_print_mm, largest_fits, build_volume_mm, pieces, failed?, passed?, unchanged?}, result?: {status, created, environment, material, settings, designs: {key: record}, groups, seconds, peak_rss_mb, estimate}, brace_frame, frame_check: {environment, static_g, f1_hz, f1_guidance_hz, modes: [{f_hz, eff_mass_frac}], n_modes, highest_mode_hz, eff_mass_captured, residual_mass_frac, max_deflection_mm, max_deflection_at_mm, max_deflection_axis, part_deflection_mm, groups: {frame \| brackets: {ms_yield, ms_ult, governing, checks, mass_kg, elements}}, total_mass_kg, frame_mass_kg, solids, notes, model, assumed, estimated, passed, created, brace_frame} \| {error, created, brace_frame} \| null}}, combined_plan: [{name, pids, target, bridges: [{ends, gap_mm, box}]}], build_volume_mm, build_volume_note, running: {mode, layout_id} \| null, budget_range_s, exploratory: {one_piece: true}}`. `chosen` is the user's choice (`per_part` by default), `active` what the views use (`per_part` when the chosen one has no solid). `brace_frame`: the one piece was designed to brace the frame. `frame_check`: the whole satellite with this layout's brackets, held at its rail ends (`gd.frame_eval`; masses in kg, deflections in mm, groups `frame` = walls, end plates and rails, `brackets` = the brackets or the piece; `estimated` lists the brackets modelled by their reserved box). 404 unknown layout; 409 not a Stage 2 layout |
| POST | `/api/layouts/{id}/bracket-layouts/one_piece/estimate` `{settings?}` | M4: before a one-piece run (the run's settings, `brace_frame` included), `{grid, h_mm, free_voxels, held_parts, kept_brackets, dofs_fine, dofs_coarse, fe_dofs_estimate, seconds_estimate, simp_seconds_estimate, fe_seconds_estimate, memory_mb_estimate, available_mb, budget_s, notes, model}` (builds the domain: seconds) |
| POST | `/api/layouts/{id}/bracket-layouts/{mode}/run` `{settings?, overrides?}` | M4: design the combined brackets (`mode` `combined`) or the one piece (`one_piece`, exploratory) in the background, one design run at a time (the per-part job included); progress as `study.update` `bracket_design` with `partial.mode` and one row per combined bracket (`label`, `parts`) or the one piece's row (`phase`); `settings`: `{material?, vol_frac?, min_member_mm?, budget_s? (one piece, 60–7200 s), brace_frame? (one piece: the piece braces the whole frame; needs the Bracket budget at 100)}`, `overrides` (combined): `{group key (member part ids joined by "+"): settings}`. The result is kept in the layout (`meta.bracket_layouts`); the per-part designs stay. Each run ends with the whole-satellite check of its result (`meta.frame_checks[mode]`). 400 bad mode or setting (also `brace_frame` below budget 100 or for `combined`); 404 unknown layout; 409 a run in progress, no brackets, or nothing to combine |
| POST | `/api/layouts/{id}/bracket-layouts/{mode}/frame-check` | The whole-satellite check of one bracket layout (`per_part`, `combined`, `one_piece`) in the background, in the design runs' slot (one at a time): the frame held at its rail ends with these brackets, under the memory guard; progress as `study.update` `bracket_design` with `partial.mode` `frame_check`; the result replaces `frame_check` of that column. `{status: "RUNNING", layout_id, mode}`. 400 unknown mode; 404 unknown layout; 409 a run in progress, no brackets, or that layout not designed |
| POST | `/api/layouts/{id}/bracket-layouts/use` `{mode}` | M4: "Use for saved STL files": the layout is shown and saved with this bracket layout (`per_part`, `combined`, `one_piece`); the 3D views (`extra_items`), physics, BOM, drawings, proof (Lemma 4 with combined brackets' boxes, the one piece's clearance check) and the saved STL files (manifest `bracket_layout`) follow it; `{layout_id, chosen, status: "SAVING"}`. 409 when that layout has no designed solid |
| GET / POST | `/api/saved-stl`, `/api/saved-stl` `{layout_id}`, `/api/saved-stl/download` | V2: the saved STL files of the designed best layout (manifest, folder, a save under way); save a layout now; the set as a zip |
| GET | `/api/layouts/{id}/bom?format=json\|csv` | V2: the layout's bill of materials (`report/bom.py`) |
| GET | `/api/mfg/download/{file}` | Hardware list (CSV) and bracket STL files; metal 3D-printed brackets are `bracket_AM_<part>.stl` |
| GET | `/api/items/{id}/mesh` | Binary mesh of an extra item (bracket, spacer set, standoff), in **world frame** |
| GET | `/api/parts/{id}/fidelity` | Detail-ladder result: `{status: "PENDING"\|"RUNNING"\|"DONE", levels:[{level:"F3-8", family:"F3", label, params, proxy_volume_mm3, overhead, build_s, eval_us_median, results:{<algorithm_id>: {length_used_mm, com_error_mm, score_g, first_valid_s, false_reject_rate}}}], chosen:{<algorithm_id>: level}, reasons:{<algorithm_id>: "plain text"}, stop_reason:"converged"\|"time_budget"\|"max_level"}` |
| POST | `/api/fidelity/run` `{part_ids?: [...], budget_s?}` | Start or restart the detail-ladder study (it also starts automatically when a part is added) |
| GET | `/api/fidelity/summary` | `{parts:[{part_id, name, chosen:{algorithm_id: level}}]}` |
| GET | `/api/stage2/attribution` | Constraint attribution (§O.3): `{status, mode, seed, generations, population, rows:[{relaxed, label, cv, feasible, length_used_mm, overflow_mm, unmounted, unplaced, com_error_mm, evaluations, seconds, delta_*}], largest_effect, note}`; 404 until run |
| POST | `/api/stage2/attribution/run` | Start it (background; progress as `study.update` with `study: "attribution"`) |
| GET | `/api/debug/state` | Coordinator diagnostics (queues, workers, last errors) |
| GET | `/api/cad/status` | `{status: "NOT_CONFIGURED", detail}` |
| POST | `/api/cad/package/{layout_id}` | Prepares the Fusion 360 export package for a VALIDATED or FINAL layout of the current inputs (409 otherwise): `{status: "PACKAGED", fusion360: "NOT_CONFIGURED", detail, path, bytes, download}`. No Fusion 360 call is made |
| GET | `/api/cad/package/{layout_id}/download` | The package ZIP: `parts_world/`, `parts_canonical/`, `hardware/`, `assembly.json` (transforms, densities, the app's mass properties and validation for comparison), report, proof certificate + checker, DRAFT import script (never run), README with the deferred tasks |
| GET | `/api/export/{layout_id}?kind=report_md\|report_html\|csv\|json\|stl_zip` | Exports. The reports re-run the full proof; the HTML report adds top / front / side views; the ZIP holds every placed part and hardware item as world-frame STL (mm) |

## 4. WebSocket `/ws`
**Envelope (both directions)**
```json
{"v":1, "type":"…", "seq":123, "epoch":5, "parts_rev":3, "constraint_rev":7, "mass_rev":2, "weights_rev":11,
 "applied_client_seq":40, "ts":"ISO", "payload":{…}}
```

**Client → server**
| Message | Payload |
|---|---|
| `hello` | `{last_epoch}` |
| `edit.settings` | `{client_seq, settings, commit: bool}` |
| `edit.part` | `{client_seq, part_id, patch}` |
| `run.control` | `{action}` |
| `ping` | — |

**Server → client**
| Message | Payload / behaviour |
|---|---|
| `state.snapshot` | `{project, best_validated: Layout\|null, candidate: Layout\|null, run_status, selector, least_violating: Layout\|null, progress}` — `progress` as in the `progress` message, so the running time shows while paused too |
| `edit.ack` | `{client_seq}` |
| `metrics.update` | `{layout_id, metrics}`, sent immediately after a mass edit |
| `layout.validated` | `{layout: Layout, source: "archive"\|"search"}` |
| `layout.candidate` | `{layout}` (only if the client asked for candidates) |
| `layout.stale` | `{layout_id, reason}` |
| `layout.infeasible` | `{layout, verdict}` — Stage 2 with no feasible layout: the least-violating candidate, status `INFEASIBLE` (geometry certified under its rules; `violations_engineering` lists what it breaks). Never drawn as VALIDATED |
| `project.changed` | `{reason}` — parts or part data changed; revisions in the envelope tell the client to re-fetch the project |
| `progress` | `{status, evaluations, best_g, best_length_mm, elapsed_s, recommended_min_s, recommended_note, validation_queue, validating, archive, islands:[...]}`, ≤ 10 Hz while searching, and once on every status change. `elapsed_s` is the running time: seconds spent SEARCHING for the current inputs (search context); pauses do not count, a return to inputs searched before adds to their time, Re-run and Reset start it again. `recommended_min_s`: recommended minimum search time for the current CubeSat size — search-based and provisional (`backend/src/t2s/bench/convergence_table.py`), `null` where none has been measured (6U, 12U); `recommended_note` says what it is based on, or that none exists. `archive`: archived layouts of the current inputs |
| `selector.changed` | `{algorithm, reasons}` |
| `pareto.update` | `{points}` |
| `study.update` | `{study: "size"\|"benchmark"\|"mfg"\|"bracket_design"\|…, progress, partial}`; `bracket_design` (V2, M4): `partial` = `{status, layout_id, mode: "per_part"\|"combined"\|"one_piece", brackets: [{k, pid, kind, label?, parts?, phase?, status, started_s?, seconds?, passed?, mass_g?, solid?, reason?}], n_total, n_done, workers, seconds, eta_s, estimate?, peak_rss_mb?}` |
| `status` | `{run_status: IDLE\|SEARCHING\|PAUSED\|REVALIDATING\|ERROR, detail}` — the search runs until Pause (`run.control` `pause`); it never stops on its own (V2: no CONVERGED status). Pause also starts the automatic bracket design of the best Stage 2 layout |
| `error` | `{message}` |
| `pong` | — |

**Client display rules (mandatory)**
1. Never draw a layout as VALIDATED if its `constraint_rev` or `parts_rev` is older than the newest one the client has received.
2. Show scores only when `applied_client_seq` ≥ the last `client_seq` sent; otherwise show "updating…".
3. Candidates are drawn only as a dotted ghost with an "UNVERIFIED" chip.
4. Metrics never interpolate. Pose tweens are labelled "visual interpolation — not a validated motion path".
