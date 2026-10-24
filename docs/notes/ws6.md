# WS6: Bill of Materials and Drawings tabs

Added at the user's request: "a bill of materials and an engineering drawings tab that connect to the 3D render,
these should update as the design updates … the engineering drawings should use the same drawings template as
found in most 3D modelling software."

Both tabs show the layout the Overview shows: the best validated layout, or the least-violating Stage 2 candidate
when there is none (`renderPlan`). They fetch it in full (`GET /api/layouts/{id}`) and fetch it again when its
brackets are designed (the design run finishes, or `layout.updated` replaces it in the store), so a new best layout,
designed brackets and part edits all show up without a reload.

## Bill of Materials

**Single source:** `backend/src/t2s/report/bom.py`, served at `GET /api/layouts/{id}/bom` (`?format=csv` downloads it).

**Rows** (item numbers 1…n in this order; the drawings' balloons use the same numbers):

| Group | Rows | Mass and its source |
|---|---|---|
| Parts | one per placed part, in the project's part order | the part record at the layout's part size: `ASSUMED` density (2,700 kg/m³ unless entered), `USER_MASS`, `USER_DENSITY`, or `WITHHELD` (no mass, not in the totals) |
| Brackets | one per V2 bracket except direct mounts, in the order of the parts they hold | the solid alone: `designed` (gd.design, FEA-checked), `exact` (machined block, sheet bracket built from boxes), `catalogue` (tube clamp, ASSUMED), `ESTIMATE` (cradle / metal AM until designed) |
| Fasteners & hardware | one aggregated `M3 × 8 screw with washer` row (count from every bracket's `fasteners`, `mfg.rules.FASTENER_MASS_KG` each, ASSUMED); spacer-washer stacks of the direct mounts aggregated by envelope (to 0.01 mm); standoffs aggregated by envelope; PC/104 rods from the frame keep-outs (no mass model: listed, not in the totals); any other extra item kind (a later model's rods or spacers) aggregated by kind, label, material and mass | as the layout gives them |
| Structure | the ASSUMED frame (walls and 4 corner rails), `metrics.frame_mass_kg` | listed, **not** in the total (as in the metrics) |

**Totals.** A V2 bracket's mass in the layout includes its fasteners (`mfg.brackets.v2_bracket`,
`gd.design.design_bracket`). The BOM lists each bracket's solid and the fasteners as one row, so nothing is counted
twice: **parts + hardware = the layout's `metrics.mass_kg`** (the parts with mass properties, standoffs and brackets,
designed masses where designed). `totals.matches_metrics` checks this to 1 mg and the tab shows it ("= layout mass").
The frame and rows without a mass model are listed but not included; "total with the frame" adds the frame.

**Manufacturable Design layouts** (`meta.mfg_items`) list their items as they are; their masses already include
their fasteners and the item records carry no fastener count, so no fastener row is split out.

**Tab** (`frontend/src/tabs/Bom.tsx`): grouped table (item, qty, name and description, material, process, unit and
total mass in grams, mass-source badge), totals, notes, CSV download, and the 3D view of the same layout (the app's
`MainViewport` with `itemsFor`). A row selects its part in the 3D view (a bracket selects the part it holds; Enter /
Space too, double-click or I isolates it); a part picked in the 3D view highlights its rows (its part and bracket rows
selected, the shared hardware used on it marked as related) and scrolls the first into view. Hovering a row
highlights the part in 3D. The BOM is fetched again when the layout's items change or when `mass_rev` / `parts_rev`
change (mass edits).

In MOCK mode the in-browser backend serves a BOM built by `lib/bom.ts` `buildBomClient` (the backend's rules,
simplified) and tags it `mock: true`; the tab shows the MOCK tag.

## Drawings

**Template** (`components/drawing/sheet.ts`):
* ISO A3 landscape (ISO 5457), the default: 420 × 297 mm, 20 mm filing margin on the left, 10 mm elsewhere, 0.7 mm
  frame, centring marks from the trimmed edge to 5 mm inside the frame, grid reference fields of 50 mm counted from
  the centring marks (1–8 across, A–F down), first-angle projection.
* ANSI B (17 × 11 in), the alternative: third-angle projection, margins of 0.62 in at the sides and 0.38 in at top
  and bottom, 4 × 2 zones (numbers right to left, letters bottom to top) as in common CAD templates (**ASSUMED**,
  not checked against ASME Y14.1).
* ISO 7200-style title block, 180 × 56 mm at the bottom right: drawn by "TEXT-TO-SPACESHIP (generated)", checked /
  approved "not reviewed", technical reference (layout id, stage), document type, scale, size, units mm, the
  projection symbol (ISO 5456-2: the cone's end view right of it in first angle, left in third angle), mass, general
  tolerances "ISO 2768-m (ASSUMED)", material, process, document status "ENGINEERING-CONSTRAINED — not
  flight-qualified; not for manufacture without review" (Stage 1: IDEALIZED), title, drawing number
  `T2S-<layout>-<item>` (000 for the assembly), revision, date of issue, language, sheet n/m.
* Revision block at the top right: A = generated from the layout (its date), B = the brackets designed (date of the
  design run when this session saw it).
* Parts list directly above the title block (ISO 7573: headings next to the title block, items numbered upward),
  the BOM's rows; long lists are squeezed to 3 mm rows, then summarised in one line.

**Sheets:** 1 = the assembly; then one detail sheet per designed bracket (BOM rows with `designed`).

**Views** (`projection.ts`, `layout.ts`, `render.ts`): front (from −Y, Z up, as the 3D view's key 1), top (from +Z),
the side view right of the front view (seen from the left in first angle, from the right in third angle), and a
true isometric view from the right-front-top corner. The three orthographic views keep their projection
relationship (first angle: plan below, side view right; third angle: plan above) at the largest ISO 5455 scale that
fits left of the title-block column (3U: 1:2 on both templates); they are not labelled (views in the projection
arrangement need no label; the projection symbol says which is which, and each view image carries its name for
screen readers). The isometric view goes where the largest scale fits and is labelled, with its own scale when it
differs.

Each view is rendered off screen with three.js from the **same meshes as the 3D view** (`loadPartGeometry`, the
extra items' `mesh_url`, rods as boxes), placed like the 3D view (`R[orient] · part_scale · p + t`): white faces,
black feature edges (creases above 30° and boundaries always; smooth edges where the surface turns away from this
view direction, so curved parts get their silhouette), fat lines of 0.35 mm, optional hidden edges dashed at 0.18 mm.
A second pass renders each item in a flat id colour; its pixels give each item's visible area and a point well
inside it (two-pass chamfer distance). The images are placed in the SVG sheet at the view rectangles of the same
projection that places every vector: the envelope as phantom lines (or the bracket's reserved box), centre lines,
overall dimensions (envelope height and the used length as a reference dimension in the front view, widths in the
plan and side view; a bracket's solid extents on its detail sheet), and balloons.

**Balloons:** every BOM item that can be seen is ballooned once, in the view where most of it shows; balloons stand
in lanes left and right of the view, ordered by the heights of the points they refer to so that leaders do not
cross, the front view sending most of them right (its dimensions are on its left); a leader ends in a dot on the
item. Items hidden in every view are named under the drawing. Fasteners have no solid and no balloon.

**Updating:** the drawing model is rebuilt whenever the layout, its BOM or the parts change; the current sheet is
rebuilt 250 ms after the last change; rendered views are cached per geometry, template and hidden-line setting, so a
mass edit only redraws the parts list and title block; meshes are cached like the 3D view's.

**Interaction and output:** sheet selector, template (remembered in the browser), hidden lines, wheel / +/− zoom
about the pointer, drag / arrow-key pan, Fit; balloons and parts-list rows select their part in the 3D views (and
show the selection, on screen only). Export SVG (true size in mm, views embedded as PNG), Print / Save as PDF of the
sheet or of all sheets through the browser's dialog (print CSS shows only the sheets, one per page, `@page` set to
the template's size; print at 100 % for true scale).

## Tests
* backend `tests/test_bom.py`: aggregation (one fastener row = Σ fasteners, washer stacks, bracket solids), totals =
  `_compute_physics`'s `metrics.mass_kg` on a real Stage 2 decode (also at 80 % part size with a user mass, and with
  a designed / failed design), each 3D id in one row, the endpoint (JSON, CSV, 404, 400), rods / spacers of a later
  model, Manufacturable Design items, Stage 1.
* frontend `tests/unit/bom.test.ts`, `drawingSheet.test.ts`, `drawingProjection.test.ts`,
  `drawingBalloons.test.ts`; e2e smoke: 14 tabs, and a BOM / drawing check in MOCK mode.

## Limitations
* The drawings are generated documentation of a concept, not manufacturing drawings: no tolerances beyond the
  general note, no surface finish, no hole callouts (fastener holes are not modelled in the concept meshes; the
  detail sheet draws bolt positions only if a design record carries them — today's records do not).
* Views are raster images (about 200 dpi) inside a vector sheet; edges come from the display meshes (decimated).
* PC/104 rods are drawn and listed but have no mass until the layout carries one (WS1).
* 6U / 12U assemblies fit A3 / ANSI B only at 1:5.
* ANSI B zones and margins: ASSUMED from common CAD templates.
