# API contract (backend ⇄ front end), v1

Backend: FastAPI on `http://127.0.0.1:8765`, bound to localhost only. The front-end dev server proxies `/api` and `/ws` to it.

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
[{kind, id, min, max}], insertion_order, assumed}`; mounting hardware (standoffs) appears in `extra_items`.

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
| GET | `/api/layouts?status=&limit=` | Archive list (metrics only) |
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
| GET / POST | `/api/mfg`, `/api/mfg/run` | Manufacturable Design result / start |
| GET | `/api/items/{id}/mesh` | Binary mesh of an extra item (bracket), in **world frame** |
| GET | `/api/parts/{id}/fidelity` | Detail-ladder result: `{status: "PENDING"\|"RUNNING"\|"DONE", levels:[{level:"F3-8", family:"F3", label, params, proxy_volume_mm3, overhead, build_s, eval_us_median, results:{<algorithm_id>: {length_used_mm, com_error_mm, score_g, first_valid_s, false_reject_rate}}}], chosen:{<algorithm_id>: level}, reasons:{<algorithm_id>: "plain text"}, stop_reason:"converged"\|"time_budget"\|"max_level"}` |
| POST | `/api/fidelity/run` `{part_ids?: [...], budget_s?}` | Start or restart the detail-ladder study (it also starts automatically when a part is added) |
| GET | `/api/fidelity/summary` | `{parts:[{part_id, name, chosen:{algorithm_id: level}}]}` |
| GET | `/api/stage2/attribution` | Constraint attribution (§O.3): `{status, mode, seed, generations, population, rows:[{relaxed, label, cv, feasible, length_used_mm, overflow_mm, unmounted, unplaced, com_error_mm, evaluations, seconds, delta_*}], largest_effect, note}`; 404 until run |
| POST | `/api/stage2/attribution/run` | Start it (background; progress as `study.update` with `study: "attribution"`) |
| GET | `/api/debug/state` | Coordinator diagnostics (queues, workers, last errors) |
| GET | `/api/cad/status` | `{status: "NOT_CONFIGURED", detail}` |
| POST | `/api/cad/package/{layout_id}` | Builds the Fusion export package; returns a download path |
| GET | `/api/export/{layout_id}?kind=report_md\|report_html\|csv\|json\|stl_zip` | Exports |

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
| `state.snapshot` | `{project, best_validated: Layout\|null, candidate: Layout\|null, run_status, selector, least_violating: Layout\|null}` |
| `edit.ack` | `{client_seq}` |
| `metrics.update` | `{layout_id, metrics}`, sent immediately after a mass edit |
| `layout.validated` | `{layout: Layout, source: "archive"\|"search"}` |
| `layout.candidate` | `{layout}` (only if the client asked for candidates) |
| `layout.stale` | `{layout_id, reason}` |
| `layout.infeasible` | `{layout, verdict}` — Stage 2 with no feasible layout: the least-violating candidate, status `INFEASIBLE` (geometry certified under its rules; `violations_engineering` lists what it breaks). Never drawn as VALIDATED |
| `project.changed` | `{reason}` — parts or part data changed; revisions in the envelope tell the client to re-fetch the project |
| `progress` | `{status, evaluations, best_g, elapsed_s, islands:[...]}`, ≤ 10 Hz |
| `selector.changed` | `{algorithm, reasons}` |
| `pareto.update` | `{points}` |
| `study.update` | `{study: "size"\|"benchmark"\|"mfg", progress, partial}` |
| `status` | `{run_status: IDLE\|SEARCHING\|CONVERGED\|PAUSED\|REVALIDATING\|ERROR, detail}` |
| `error` | `{message}` |
| `pong` | — |

**Client display rules (mandatory)**
1. Never draw a layout as VALIDATED if its `constraint_rev` or `parts_rev` is older than the newest one the client has received.
2. Show scores only when `applied_client_seq` ≥ the last `client_seq` sent; otherwise show "updating…".
3. Candidates are drawn only as a dotted ghost with an "UNVERIFIED" chip.
4. Metrics never interpolate. Pose tweens are labelled "visual interpolation — not a validated motion path".
