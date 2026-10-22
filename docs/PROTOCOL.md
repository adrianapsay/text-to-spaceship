# TEXT-TO-SPACESHIP: Protocol (short version, rev 3)

**Status:** updated with both of your reviews from 2026-10-22. Waiting for your final go-ahead; nothing is built yet. Full detail is in [PROTOCOL-FULL.md](PROTOCOL-FULL.md); its **Addendum 1** overrides any older text there.

## What I'll build
A local app that runs in your browser.
- **Input:** **any STL files, added at any time** (see "New parts later" below). My 19-part test set is only the starting example. Nothing is built around it.
- **Output:** arrangements of those parts inside a 3U CubeSat (100 × 100 × 340.5 mm).
- **Each arrangement is scored on:**
  - **Compactness:** length used.
  - **Balance:** centre-of-mass error.
  - **Rotational inertia.**
  - In the engineering stage, also **cable routing** and **hardware cost**.
- **Kinds of result:**
  - **IDEALIZED:** an empty box.
  - **ENGINEERING-CONSTRAINED:** walls, rails, clearances, circuit-board stack, cable channel, assembly order.
  - **MANUFACTURABLE DESIGN:** adds real mounting hardware. Never a claim of flight qualification.

## How it works
1. **Analyse.** Check each part's mesh, then compute exact mass, centre of mass and inertia.
2. **Place.** A fast routine places simplified shapes. Every layout it produces is valid.
3. **Improve.** A genetic algorithm runs on parallel islands. The multi-objective search uses **pymoo** (U1).
4. **Tighten.** The real shapes are slid closer, using the gaps inside other parts.
5. **Validate.** A strict checker on the exact meshes is the only thing that can mark a layout VALID.

## What you'll see
- **Sliders:** moving one immediately shows the best already-validated layout for those priorities. Better ones stream in.
- **Mass edits:** the balance point moves at once. Shapes never change.
- **Unchecked layouts:** shown only as a faint ghost marked UNVERIFIED.
- **Screens:** a simple first screen, plus tabs for detail, plus the three new tabs below.

## New since your review
**1. Size Study tab (U3).**
- Every part is scaled up equally in all three axes, in steps (×1.00, ×1.05, ×1.10 …), until nothing fits. The final limit is found to within 0.5 %.
- At every size, each algorithm gets the same time budget. The tab shows:
  - length used vs. size, one line per algorithm;
  - which algorithm won at each size;
  - each algorithm's largest size that still fits;
  - a 3D thumbnail of the winning layout at each size.
- Expected insight (ESTIMATE): the 90 mm circuit boards stop fitting flat at about ×1.11 (100 ÷ 90). After that, algorithms that can tilt parts may win.
- **Run length.** Up to **6 hours**, stopping earlier once the best solution is reached:
  - a proven optimum (matches a proven lower bound), or
  - no improvement for 30 minutes across all seeds.

  The tab says which of the three ended the run.

**2. Cable routing slider (U5).**
- **At 0:** the default. The channel is interrupted beside the board stack, and wiring is assumed to pass through the boards' stack connector.
- **As you raise it:** blocked channel length counts against a layout.
- **At high importance:** the app switches to a different strategy. The full-length channel becomes a hard rule, and the optimiser may:
  - move the channel to another wall or corner;
  - stand circuit boards on edge, **but only where each board can still be mounted**: card guides along two opposite edges, or standoffs to a wall or rail. The mount is checked like any other: it must fit, it must not collide, and its weight and cost count;
  - rearrange everything.

  It accepts worse packing to do this. The screen says which strategy was chosen and what it cost. If no clear path exists, it says so.

**3. Manufacturable Design tab.**
- **Algorithm choice:** picks its own placement algorithm from the part shapes and benchmark results, and shows why.
- **Mounting hardware:** gives every part a way to be held, choosing the cheapest option that works:

  | Option | When it's used |
  |---|---|
  | Direct mount | A flat face screwed to a wall, rail or deck |
  | Catalogue part | Standoffs, L-brackets, PC/104 spacers, tube clamps (generic) |
  | Custom bracket | Sheet metal or machined (L, Z or saddle) |
  | **Metal 3D-printed bracket** | Generated to fit a part where nothing simple can reach, e.g. a curved part, an awkward offset, or several attachment points. Checked against basic printing rules (ASSUMED: minimum wall 1 mm, overhangs ≤ 45°) |

- **Metal 3D-printed brackets are always identifiable:**
  - their own colour and an "AM" badge in 3D;
  - a separate section in the parts list;
  - their own exported files (`bracket_AM_*.stl`).
- **Brackets are real geometry:** they are collision-checked and their weight counts in balance and inertia.
- **"Hardware cost" slider:** at high importance, parts are placed flat against walls and rails to avoid custom brackets, even if packing or balance gets worse.
- **Outputs:**
  - a hardware list: part, mount type, process, material, mass, cost;
  - export files.
- **Labelled:** "manufacturing concept — assumed cost model, not a quote; brackets not stress-analysed".

**4. New parts later (any STL, any time).**
- **Adding a file.** Click **Add parts** or drop STL files onto the window, whether binary or text, from any CAD program. The app then:
  1. checks and, if needed, repairs the mesh;
  2. asks you to confirm the units. It suggests mm, and warns if the file looks like inches or metres;
  3. calculates mass and inertia;
  4. classifies the shape, and adds the part to the parts list.
- **Re-running.** Click **Re-run** to re-optimise with the new part. The Size Study and Manufacturable Design tabs can be re-run too.
- **What carries over:** your saved layouts and settings. Old layouts are clearly marked as not including the new part.
- **Removing or replacing a part** works the same way.
- **Bad files** never break the program. They are explained ("open mesh — 3 holes"), and you choose: repair, enter the mass yourself, or leave the part out.
- **Very detailed files** (millions of triangles): the 3D view uses a lighter copy for display, while the checks still use the full-detail mesh.
- **Testing.** The automated tests include adding new, unseen files to an existing project: a different shape, an inch file, a text-format file and a broken file.

**5. Explain tab: idea map, proof that the parts fit, and algorithm choice.**
- **Idea map.** A clickable diagram built from the live run, not a static picture. It shows:

  parts (grouped by shape) → simplified shapes → candidate algorithms → your slider priorities → constraints → the chosen algorithm → the resulting layout and its numbers.

  Each link shows the number that drove the decision. Clicking a node opens the tab with the detail.
- **Proof that the parts fit.** For the layout on screen, the tab writes out a step-by-step mathematical proof with the actual numbers:
  - **Inside the box:** every corner point of every part lies within the enclosure limits, and the tightest point and its margin are shown per axis. The box is convex, so this proves the whole part is inside.
  - **No two parts touch** (or, in the engineering stage, they keep the required gap). Each pair of parts gets a *separating plane*: a flat surface with one part entirely on one side and the other part on the other side, at least the required distance apart. Parts with hollows or holes use the same argument on certified convex pieces, plus a check that neither part sits inside the other.
  - **Balance and assembly:** the centre-of-mass limits are written as inequalities with numbers, and the insertion order is listed with the reason each part can slide in.
  - **Why it can't be much shorter:** the lower-bound arguments, each with its derivation.
  - **Download:** the proof as a document, plus a small stand-alone checker script. The script re-verifies every inequality from the original STL files without using the app.
- **How sliders change the algorithm.**
  - Next to the sliders on every screen: the algorithm currently in use and a one-line reason.
  - In this tab, one strip per slider shows which algorithm would be chosen across its whole 0–100 range, with the others held where they are. A two-slider map is available too.
  - The choice is based on measured benchmark results for similar settings, and the evidence is shown. Every switch is logged.

## Build plan
| Step | Delivers |
|---|---|
| M0 | Tools inside the project folder |
| M1 | Part analysis + mass properties |
| M2 | Collision checker (zero real overlaps accepted) |
| M3 | First valid layouts + lower bounds |
| M4 | Live backend |
| M5 | Main screens + 3D view |
| M6 | Full optimiser (pymoo) |
| M7 | Engineering stage, comparison, cable-routing slider |
| M8 | Benchmarks, Size Study tab, Explain tab (idea map, fit proof, algorithm-choice explorer) |
| M9 | Manufacturable Design tab (brackets, metal 3D printing, cost) |
| M10 | Reports, Fusion export package, final test run, final report |

Each step ends with tests passing and a local git commit. Blockers go to `docs/BLOCKERS.md`, and I continue with other work.

## Your decisions (recorded)
| | Decision |
|---|---|
| U1 | Use pymoo (with moocore). If it fails our accuracy tests, write our own |
| U2 | All open-source licences allowed, including GPL/LGPL. Note: if you ever *distribute* the app, GPL parts would require releasing it under GPL. Fine for your own use |
| U3 | Packing definition approved, plus the Size Study tab |
| U4 | 2.2 mm between parts, 1.2 mm to walls |
| U5 | Cable channel driven by its own slider (above) |
| U6–U8 | Defaults |
| U9 | All permissions. I'll install what's needed and work unattended. I won't push code anywhere or publish anything |

## Defaults for the new tabs (approving accepts these)
| | Question | Default |
|---|---|---|
| N1 | Cost units | **Relative cost units** (e.g. catalogue bracket = 1), editable. I won't invent dollar prices; give me prices any time and it switches to $ |
| N2 | Metal 3D-print material | **AlSi10Mg aluminium** (common, light). Ti-6Al-4V selectable |
| N3 | Size Study scope | Both stages, 5 seeds per size. Runs up to 6 h, or stops early when the best solution is reached (proven bound, or no improvement for 30 min). Runs in the background |
| N4 | Cable-routing high mode | Boards may stand on edge **only if mountable**: guides or standoffs that fit, don't collide, and are counted in mass and cost |
