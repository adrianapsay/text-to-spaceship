# WS1 — chassis-only mounting and the anchored PC/104 stack (notes)

Branch `ws1-chassis-mounting`. The user's rule: every component is fixed only to chassis structure (walls, end
plates, corner rails); the PC/104 board stack hangs on four rods that run to its end plate.

## What changed

* **No bracket on the stack.** The decoder gets no target but the corner rails (`extra_targets` all False for the
  harness breaks, rods and stack block; the decoder kernel is unchanged). `_bracket_mount` and the V1 Manufacturable
  tab offer walls, end plates and rails only. Each bracket states `target_kind` (`wall` / `end_plate` / `rail`) and
  `held_parts` (`[pid]` today; a list so that WS5's shared brackets keep the format); `target_parts` is gone. In
  `spec()` a bracket's held parts are exempt from it, and it may touch only the corner rail it is fixed to.
* **The stack is anchored at an end plate.** The stack key chooses the plate (`[0, 0.5)` → −Z, `[0.5, 1)` → +Z) and an
  offset beyond the 1.2 mm wall clearance of `STACK_OFFSET_MAX · u³` (u = the key's position within its half;
  `STACK_OFFSET_MAX` = 40 mm, ASSUMED; half the keys stay within 5 mm). `EXTRA_DEFAULT` puts it against −Z. The plate
  is decided at decode time and stored as `rod_end`, with `rod_model = "v2.5-end-plate"`.
* **One rod builder** (`stage2.pc104_rods`, `stage2_model.stack_rods`) for the decoder's obstacles, the validation
  statics, the insertion check, the V1 keep-outs and the display: rods from the true end plane (the inner box, not the
  relaxed decoder limit) through every board, as 5 mm square spacer-tube keep-outs (`ROD_KEEP`, as
  `mfg.brackets.spacer_set`).
* **COM shift.** Only the non-board parts move; the needed shift is scaled by total ÷ moving mass; the room is a
  sweep of the moving parts' proxy boxes against the stack block (part gap), the rods and the harness segments
  (keep-out gap).
* **Mass.** Each rod with its spacer tubes is a mass item (M3 steel rod 3.0 mm, 7850 kg/m³; aluminium tube 5 mm outside,
  3.2 mm bore, 2700 kg/m³ over the length the boards leave free; all ASSUMED) in the layout's physics and in
  `meta["stack_hardware"]`.
* **Board mount check.** A stack board is mounted only when all four rods end on the true end plane, span the board
  and stand inside its outline box.
* **Insertion check** (`service/worker.py`). Each part sweeps with its bracket's reserved box (edge boards with their
  standoffs), each convex piece on its own. The rods stay on their plate and block every non-board part; a board
  comes off only along its rods, away from that plate. ASSUMED: a part goes in already fixed to its bracket; the
  harness is routed after the parts (not a blocker, as before).
* **Legacy layouts.** A layout without `rod_model` in its meta keeps the old rules: rods over the stack span only
  (3.2 mm), deck brackets with their board exemptions. Archived proofs re-validate; issued certificates verify.
* `BRACKET_MODEL_VERSION` = v2.5; the rod model, `ROD_KEEP` and `STACK_OFFSET_MAX` are in the spec signature.

## Certificate (version 2) and checker

* `frame` block (from `Stage2Spec.frame`): `rules` (`v2.5` / `legacy`), `planes_mm` (true inner planes),
  `stack_ids`, `rod_end`, `harness_wall`, `harness_break_mm`, `relaxed`, and `items` (every static: name, kind,
  corners). Bracket entries add `target_kind`, `axis`, `neg`, `plane_mm`, `held_parts`; `exempt_parts` = `held_parts`.
* `tools/check_certificate.py` adds `frame_items_complete`, `exemptions_follow_rules` (any certificate with a frame
  block) and, for v2.5 rules, `brackets_fixed_to_chassis`, `every_part_held`, `stack_rods_to_end_plate` (module
  docstring, checks 8–9). A version-2 Stage 2 certificate without its frame block fails. Version-1 certificates and
  legacy-rule layouts skip the new checks with a NOTE.
* Proof text: Lemma 4 without the deck; Lemma 5 (every part fixed to the chassis).

## Verification

* **Backend:** the full suite, 224 tests: 224 passed, 0 failed, 0 skipped (JUnit XML; 422 s). New tests:
  `test_chassis_mounting.py` (no deck target in the decoder, the V2 bracket check or the V1 tab; certificate round
  trip with every new check PASS; eleven checker mutations — a bracket on the deck, a bracket plane inside the
  enclosure, a part without a bracket, exempt parts beyond the held part, a bracket touching a rod, a part exempt
  from a rod, rods ending short, a moved rail, inconsistent corners, a solid off its plane, a dropped frame block;
  a legacy deck layout validates and verifies, and fails under the v2.5 rules; a version-1 certificate verifies);
  `test_stage2.py` (the stack at both end plates with rods to the plate, the key mapping, the COM shift leaving the
  stack and its rods in place and moving the COM by s · moving ÷ total mass, bracket boxes and board directions in the
  insertion check, fixed rods blocking parts). `test_decoder_mount.py`'s 6U statistic passes unchanged.
* **Frontend:** `tsc` clean; vitest 12 files, 75 tests passed.
* **Lint:** no ruff finding added in any changed Python file (per file, against main).
* **The user's archived layout L-9607** (3U 54 %; the gas tank's metal-AM bracket on the stack underside), re-proved
  with this code as `build_proof` does: valid under its own (legacy) rules; its new certificate passes the new
  checker with the legacy NOTE; under the v2.5 rules it fails exactly on the deck contact (board p02 – bracket:p08
  0.000 mm, bracket:p08 – stack_reserve 0.000 mm).
* **An issued version-1 certificate** (L-0003, Stage 2, 8 brackets, 2026-10-23) passes the new checker, as it passes
  the old one.

## Feasibility

Measured with `backend/scripts/feasibility_check.py`: the protocol of the documented runs (BRKGA + local search,
population 30, two constructive seeds; 25 generations = 1,230 evaluations, "4×" = 100 generations = 4,830
evaluations), synthetic parts, default mode, bracket budget step 1, seeds 1–4 (the documented runs' seeds are not on
record; 1–4 chosen here). Each cell: validator-certified best layouts → also insertable (the app's ±Z check) / runs.
Variants: **before** = main (fc63c67); **deck only** = main with the deck no longer a target; **rods only** = commit
1 of this branch (anchored stack, new insertion check, deck still a target); **after** = this branch. Runs are
deterministic (22 repeated runs gave identical layouts).

| Setting | Effort | before | deck only | rods only | after | after, old ±Z rule | before, new ±Z rule |
|---|---|---|---|---|---|---|---|
| 3U 54 % | 1× | 4 → 4/4 | 4 → 4/4 | 4 → 2/4 | 4 → 4/4 | 4/4 | 1/4 |
| 3U 54 % | 4× | 4 → 4/4 | 4 → 4/4 | 4 → 2/4 | 4 → 4/4 | 4/4 | 0/2 |
| 3U 75 % | 1× | 4 → 4/4 | 4 → 2/4 | 4 → 0/4 | 4 → 2/4 | 3/4 | 0/4 |
| 3U 75 % | 4× | 4 → 4/4 | 4 → 3/4 | 4 → 0/4 | 4 → 1/4 | 2/4 | — |
| 6U 50 % | 1× | 4 → 4/4 | 4 → 3/4 | 4 → 4/4 | 4 → 4/4 | 4/4 | 3/4 |
| 6U 50 % | 4× | 4 → 4/4 | 4 → 4/4 | 4 → 3/4 | 4 → 4/4 | 4/4 | — |
| 6U 100 % | 1× | 4 → 3/4 | 4 → 4/4 | 4 → 1/4 | 4 → 4/4 | 4/4 | 1/4 |
| 6U 100 % | 4× | 4 → 4/4 | 4 → 3/4 | 4 → 1/4 | 4 → 3/4 | 4/4 | — |
| 12U 50 % | 1× | 4 → 4/4 | 4 → 4/4 | 4 → 4/4 | 4 → 4/4 | 4/4 | 4/4 |
| 12U 50 % | 4× | 4 → 4/4 | 4 → 4/4 | 4 → 4/4 | 4 → 4/4 | 4/4 | — |

* **No certified layout is lost:** every run of every variant ends with a validator-certified best layout (every part
  placed and mounted, inside the length, COM inside the CDS box).
* **Every loss is the insertion check** of that single best layout (the search does not optimise insertion; the app
  checks it for each layout it validates). With insertion: before 39/40, deck only 35/40, rods only 21/40, after
  34/40; the after layouts under the old parts-only rule: 37/40.
* **Attribution** (after 34/40 vs before 39/40). Deck removal alone, old rule: 35/40 — five runs lost (3U 75 % 1× ×2
  and 4×, 6U 50 % 1×, 6U 100 % 4×), one gained (6U 100 % 1×); these are single-seed changes of the search's path. The
  stricter v2.5 insertion rule (brackets move with their parts, rods fixed, boards leave away from their plate) costs
  3 of the after layouts (37 → 34: 3U 75 % 1× and 4×, 6U 100 % 4×). Anchoring the stack while the deck stays a target
  is the worst combination (21/40): parts hung on the stack trap the boards. The new rule also rejects 13 of the 22
  before layouts re-checked (their deck-mounted parts).
* **The stack in the after layouts:** all 40 at the −Z end plate; gap to the plate 1.2 mm (median) to 38.0 mm; rods
  17.2–54.8 mm long; rods and spacer tubes 5.8–18.6 g; the other parts shifted 0–98.7 mm; all 680 brackets on side
  walls.

**Decode time per layout** (100 random chromosomes per run after 3 warm-up decodes, one process at a time, before
and after alternating; median of 3 runs):

| Setting | before (ms) | after (ms) | after / before | every part placed and mounted, 300 random decodes |
|---|---|---|---|---|
| 3U 54 % | 26.3 | 27.6 | 1.05 | before 251, after 292 |
| 3U 75 % | 27.6 | 30.3 | 1.10 | before 118, after 122 |
| 6U 50 % | 21.8 | 22.6 | 1.04 | before 281, after 300 |
| 6U 100 % | 30.4 | 30.8 | 1.01 | before 120, after 227 |
| 12U 50 % | 20.0 | 21.6 | 1.08 | before 300, after 300 |

Random decodes mount more parts after the change. The deck-only variant shows the same rise (100 decodes, seed 7:
3U 54 % 82 → 98, 6U 50 % 92 → 100, 6U 100 % 34 → 75 against before), so it comes with the removal of the deck
target; the mechanism was not investigated.

## Not done here / for the lead

* **Physics in the coordinator** (`service/coordinator.py` `_compute_physics`, not WS1's file): it rebuilds a layout's
  hardware from standoffs and brackets only, while the search's evaluator also counts the rods and spacer tubes. Add
  `meta["stack_hardware"]` items (`mass_kg`, `com_mm`, `inertia_kgm2`) to `hardware` there, or the archived COM and cv
  differ slightly from the search's (a few grams at the stack's end plate).
* **Texts outside WS1's files that still describe the deck or the floating stack:** `docs/V2.md` lines 20–21, 29, 40
  and 145 (deck targets; "PC/104 deck" in the design-job note), `docs/STATUS.md` 45, `docs/FINAL-REPORT.md` 88,
  `docs/PROTOCOL.md` 63, `docs/research/draft_A_B_C_O.md` 88; `gd/domain.py` lines 7, 70 and 133 (comments: "rail or
  deck", "under a wedge-shaped part on the PC/104 deck"); `service/coordinator.py` `_stage2_view` assumed list
  ("whole layout shifted along Z" — now every part but the boards; "rods at (±35, ±35) mm" — now from the stack's end
  plate) and `project_json` note ("PCB stack macro and rods arrive with M7"); `frontend/src/tabs/Engineering.tsx` 111
  (PCB stack row: anchored at an end plate on rods); `docs/api-contract.md` 80 (`stage2` could list `rod_end`).
* **V1 Manufacturable tab** (`mfg/design.py`, not WS1's file): `synthesize` adds spacer sets between the boards only;
  with the stack anchored, the rods and the spacers from the end plate to the first board are missing from its
  hardware list.
* **The stack's frequency on its rods** (plan, review item 1) is not computed here; `STACK_OFFSET_MAX` (40 mm,
  ASSUMED) bounds the free rod length. WS3 owns the vibration analysis.
* **Insertion is not part of the search objective** (as before): the search optimises without it and the app checks
  it after validation. The stricter v2.5 rule rejects more best layouts (see Feasibility).
