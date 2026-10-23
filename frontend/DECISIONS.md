# Front end (W5) — decisions, assumptions and contract gaps

Built against `docs/api-contract.md` v1 (including the detail-ladder endpoints of Addendum 4) and
`docs/PROTOCOL-FULL.md` §I, §M, §P and Addenda 1–4. Everything below was decided without the user (unattended run).

## How to run

All commands from `frontend/` after `. D:\text-to-spaceship\tools\env.ps1`.

| Command | What it does |
|---|---|
| `npm run fixtures` | (Re)builds `public/mock-fixtures/` from `data/synthetic` (git-ignored; the `pre*` scripts build it if missing) |
| `npm run dev` | Dev server on :5173, proxies `/api` and `/ws` to `127.0.0.1:8766`; uses the mock until `/api/health` answers |
| `npm run dev:mock` | Dev server forced into MOCK mode (`.env.mock` sets `VITE_MOCK=1`) |
| `npm test` | Vitest unit tests (jsdom) |
| `npm run build` | `tsc` (strict) + production build |
| `npm run e2e` | Playwright smoke test, headless Chromium + SwiftShader WebGL, mock mode on :5199 |

URL overrides for manual testing: `?mock=1` / `?mock=0`.

## Toolchain and packages

- Node 24.21.0 / npm 11.19 from `tools/`. `npm_config_before=2026-10-08` is honoured by `npm install`, but
  `npm view` ignores it, so exact versions published before the cutoff were picked by reading each package's
  `time` field and pinned exactly in `package.json`.
- Runtime: react / react-dom 19.3.0, three 0.186.1, @react-three/fiber 9.8.1, @react-three/drei 10.7.9,
  three-mesh-bvh 0.9.15, zustand 5.0.15, radix-ui 1.7.0, uplot 1.6.32, @observablehq/plot 0.6.17 (ISC).
  Dev: vite 8.3.3, @vitejs/plugin-react 6.1.2, typescript 6.0.3 (protocol H.3 says 6.0.x; 7.x exists but was not
  used), vitest 5.0.3, jsdom 30.1.2, @testing-library/* , fast-check 4.10.2, @playwright/test 1.64.0 (Apache-2.0).
  All MIT unless noted. No other packages.
- Playwright Chromium was installed with `npx playwright install chromium` into `tools/ms-playwright`.
- Not installed (gaps): `@axe-core/playwright` (T-UI6 automated axe scan), `@react-three/test-renderer`
  (scene-graph test T-UI5), eslint.

## Architecture

- `src/api/types.ts` — wire types (snake_case as on the wire).
- `src/api/transport.ts` — one `Transport` interface (fetch + socket factory) for the live backend and the mock,
  so the REST and WebSocket clients are the same code in both modes.
- `src/api/rest.ts` — typed REST client; 404/405/501 are mapped to "not available yet" → empty states.
- `src/api/ws.ts` — WebSocket client (envelope, `hello` on open, exponential backoff 250 ms → 5 s, ping 15 s)
  and the leading+trailing `Throttle` (≤ 20 Hz).
- `src/api/protocol.ts` — pure reducer for server envelopes + the display-rule selectors
  (`renderPlan`, `displayKind`, `scoresVisible`, `isCurrent`). Property-tested.
- `src/api/session.ts` — owns side effects: throttled `edit.settings` / `edit.part`, re-send of the latest
  intent per control after reconnect, project re-fetch, run control, add / units / remove parts.
- `src/store/store.ts` — one vanilla zustand store with slices `dataset`, `physical`, `goals`, `solver`, `view`,
  `conn`. Physical edits (mass, lock) and goal edits (sliders, presets, stage) never touch each other's slice
  and use different message types (`edit.part` vs `edit.settings`).
- `src/mock/` — in-browser backend (REST router + `MockSocket`), STL reader, placeholder packer, MOCK content.
- `src/components/viewport/` — R3F viewport (WebGL2, `frameloop="demand"`), dual view (one canvas, two drei
  `View`s), thumbnails (one canvas, many `View`s), part inspector.

## Display rules (api-contract §4) as implemented

1. **VALIDATED only for current inputs.** `conn.newest` is the component-wise maximum of every accepted
   envelope's revisions (and of `project.revs`). A layout whose `constraint_rev` or `parts_rev` is older is not
   hidden but drawn desaturated with the badge **VALIDATED FOR PREVIOUS INPUTS** (protocol §M.1.3), plus
   "does not include *part*" when current packable parts are missing from its poses. `layout.stale` marks the
   best as STALE with its reason. An incoming `layout.validated` that is older than the one on screen is ignored.
2. **Scores only when caught up.** `applied_client_seq` (every envelope) and `edit.ack` raise
   `appliedClientSeq`; scores (g, normalised gaps) show "updating…" while it is below the last `client_seq` sent.
3. **Candidates** are only drawn as dotted, edges-only ghosts with an "UNVERIFIED" chip, and only in Expert mode
   with "Ghost" on (protocol §I.4 "Expert only"). The reducer never puts a candidate into the solid slot.
4. **Metrics never interpolate.** Pose changes tween for 300 ms (disabled under `prefers-reduced-motion`) with
   the chip "visual interpolation — not a validated motion path"; the metric strip switches at once.

Latest-wins: envelopes with `seq` ≤ the last accepted seq on the connection, or an `epoch` older than the
current one, are dropped. A snapshot with a different epoch resets `newest` (server restart / reset).

## Contract gaps and the assumptions taken (please confirm with W4)

| Topic | Assumption |
|---|---|
| How the client "asks for candidates" | `hello` payload carries an extra key `want_candidates: bool` (true in Expert mode). |
| `client_seq` scope | Per connection: restarts at 1 after every (re)connect; after the snapshot the latest unacknowledged settings intent and per-part patches are re-sent with new seqs. |
| Stage switch | Sent as `edit.settings` with `commit: true` (stage is a Settings field). |
| `principal_axes` | Rows are the unit principal axes, row k ↔ `principal_kgm2[k]`. |
| `project.limits` keys | `com_box_mm`, `cds_mass_note_kg`, `clearance_part_mm`, `clearance_wall_mm`, `length_mm`, optional `cable_mode_threshold` (default 70). |
| `project.enclosure` | `size_mm: [100, 100, 340.5]` (fallback to those values). |
| `stage2_frame` shape | `{wall_mm, inner_box_mm, rail_mm, boxes: [{kind, min, max}], walls: {inner_min, inner_max}}`; rails/walls are drawn from `boxes`/`walls` if present. |
| Parts changes over WS | No message exists; the client re-fetches `GET /api/project` after its own REST part mutations, after an acknowledged `edit.part`, and whenever an envelope raises `parts_rev` or `mass_rev`. |
| `GET /api/layouts` / `POST /api/parts` | Accept either a bare array or `{layouts}` / `{parts}`. A summary may carry `part_ids` so history rows can say "does not include …". |
| `GET /api/selector/map` | `{x, y, n, grid[row=y][col=x], legend?}` or a bare 2-D array. |
| `GET /api/selector` `algorithm` | Either `{id, label}` or a bare id string. |
| Collision / clearance indicators | Optional `layout.violations: [{a, b, kind: 'clearance'|'overlap', distance_mm, required_mm, points: [p, q]}]`; nothing is ever computed client-side. |
| `study.update` for fidelity | `{study: "fidelity", progress, partial: {part_id, status, progress?, level?}}` (object or array). |
| Size Study / benchmarks / mfg payloads | Not specified in the contract. The UI renders the fields listed in `types.ts` (`SizeStudy`, `Benchmarks`, `MfgResult`) when present and shows an empty state otherwise. |
| Seed, constraint attribution, ASSUMED-rule editing, layout restore | No fields/endpoints → shown as "—" or an explicit empty state; ASSUMED rules are read-only. |
| Detail-ladder "level thumbnails" | No per-level geometry endpoint → a table of levels (volume, overhead, build, eval time) instead. |
| `/api/parts/{id}/proxy` | Not used yet. |

## MOCK mode

- Selection: `VITE_MOCK=1` forces the mock, `VITE_MOCK=0` forces live; unset in dev → probe `/api/health` at start
  (JSON `{ok: true}` within 1.5 s) and use the mock otherwise; while mocked, re-probe every 10 s and offer a reload
  when a backend answers. Production builds default to live.
- Every screen shows the "MOCK DATA" banner; MOCK badges sit next to mock-derived numbers.
- Fixtures (`scripts/build-mock-fixtures.mjs`, from `data/synthetic`): 19 packable parts in the contract's binary
  mesh format, canonical frame = AABB centre at the origin, orient 0 = identity, 24-rotation table (identity first);
  float64 mass properties at an ASSUMED 2,700 kg/m³ (total 1,080.0 cm³, 2.916 kg — matches the protocol);
  subsystem and labels from the manifest's *intended* labels; `solidity`/`obb_fill` are `null` ("—").
- Placeholder layout: parts in AABB layers along Z, footprints side by side (a plain single stack is 618 mm and does
  not fit). It is checked by an AABB-disjointness + containment test (valid for these layouts, recorded as
  `validator_version: "mock-aabb-1"`), and labelled "MOCK placeholder" everywhere.
- "Optimise" in mock mode runs a seeded randomised version of the same layer packer and streams candidates /
  validated layouts / progress / Pareto points. It is not an optimiser and says so in the status text.
  Metrics come from the same aggregation code the UI uses; scores use the protocol's normalisation and augmented
  Tchebycheff over the mock archive.
- Selector rule, sweeps, map, idea map: deterministic **illustrative** rule, labelled "MOCK default rule".
- Detail ladder (Addendum 4): mock results are **ILLUSTRATIVE** (only the F0 AABB volume and F6 mesh volume are real)
  and carry `mock_note`; a new part's study streams `study.update` (PENDING → RUNNING → DONE).
- Fit proof: a genuine AABB-interval argument with the actual numbers, labelled as not the backend validator;
  `.md` and `.json` downloads work, the checker script returns 501.
- Not implemented in the mock (empty states): Stage 2 search, benchmarks, Size Study, Manufacturable Design,
  extra-item meshes, CAD package, report/STL exports (JSON and CSV exports work).
- Added STL files are parsed in the browser (binary/ASCII), always come back `NEEDS_UNITS`; on confirmation they
  are scaled, checked (open edges → WITHHELD "open mesh — N holes"; inverted winding → REPAIRED) and integrated.

## UI decisions

- Square corners, Segoe UI / Consolas, tokens and Okabe-Ito palette from §I.1 in `src/styles/tokens.css`;
  light/dark follow the OS; viewport always #26282C. Contrast pairs are unit-tested.
- Metal-AM brackets: colour #B48CFF (not used by any subsystem), screen-space diagonal-hatch shader, "AM" label in 3D,
  hatched swatch and their own "METAL 3D-PRINTED" section in the Overview hardware list and the Manufacturable
  Design hardware table.
- Sliders are native `<input type="range">` (keyboard + `aria-valuetext="25 percent priority"`); Radix is used for
  Tabs, Tooltip (hover and focus; plain → Technically → Why it matters) and Dialog.
- drei `<Html>` is not used: under React 19 it logged "synchronously unmount a root" errors on tab switches. A small
  DOM label layer (`labels.tsx`) projects labels each rendered frame and declutters them by priority.
- The camera fits the enclosure's bounding sphere (keeps the viewing direction); F fit, 1–6 views, 0 isometric,
  arrows orbit, H / I / Shift+H hide / isolate / show all, E enclosure.
- Mass edits show a labelled "local recompute" of COM / inertia from backend per-part float64 properties until the
  backend's `metrics.update` arrives; geometry-only metrics are never recomputed.
- Beginner hides candidate ghosts, the convergence chart and the tensor tables (protocol §P); Expert shows them.
  The Beginner/Expert choice and colour mode are kept in `localStorage` (try/catch; convenience only).
- Each tab and each viewport sits in an error boundary so one failure never blanks the app.

## Known gaps

- No automated axe scan, visual-regression (T-UI9), dual-view sync timing (T-UI8) or frame-time (T-UI10) tests.
- Not yet exercised against the real backend (it did not exist during this work).
- The main bundle is ~1.3 MB (three + drei); tabs are code-split.
