## A. Project understanding

**What we are building.** A local engineering application that takes a set of STL parts, analyses each one, and searches for arrangements inside a CubeSat that are (1) geometrically valid, (2) compact, (3) balanced about a target centre of mass and (4) favourable in rotational inertia. It explains the trade-offs it finds. Results come in two clearly labelled kinds:

| Label | Meaning | Never implies |
|---|---|---|
| **IDEALIZED** (Stage 1) | Rigid parts in an empty 100 × 100 × 340.5 mm box. No overlap, contact allowed within 0.01 mm, no hardware. | That the layout can be built. |
| **ENGINEERING-CONSTRAINED** (Stage 2) | Stage 1 plus the ASSUMED frame, clearances, mounting allowances, harness channel, PCB stack, insertion order and the CDS COM box as hard constraints. | Flight qualification, structural adequacy or launch-load survival. |

The optimiser does its own geometry and collision work. Fusion 360 is an *independent, later* check whose status stays **NOT CONFIGURED** until the user authorises it.

**Five findings from the pre-protocol analysis that shape the design.**

1. **Volume fraction cannot rank layouts.** With every part inside a fixed enclosure, Σ part volume ÷ enclosure volume is the same for every valid layout: 31.7 % for this dataset in a 3U. So "packing efficiency" is defined as **compactness**: the enclosure length used along Z. The largest remaining empty box is reported alongside it. The plain fraction is still shown as "Space Used".
2. **Uniform density does not change the best arrangement.** If every part has density ρ, then COM = Σ Vᵢrᵢ / Σ Vᵢ for any ρ, and every inertia entry scales with ρ. After normalisation the objectives are identical. Density only matters for absolute kg and kg·m² and the mass-limit check. Arrangements change only when parts have *different* densities or masses.
3. **The mass limit is a parts-list check, not an optimisation constraint.** Rearranging parts cannot change total mass (2.916 kg here, against a 6.00 kg recalled 3U limit).
4. **STL precision is float32.** For parts whose coordinates are exactly representable, the analysis matches analytic values exactly. For rotated parts or coordinates like 1.6 mm, it matches to about 1e-8. A 1e-9 tolerance therefore applies only to in-memory float64 unit-test geometry; tests through STL files use about 1e-7. Tessellated curved parts differ from their ideal shape by their discretisation error (for example −7.1e-4 in volume for a 96-segment cylinder). That error belongs to the mesh, not the solver.
5. **Some geometrically valid layouts cannot be assembled.** The torus hole (Ø44 mm), the tube bore (Ø34 mm) and the U-channel cavity (52 × 26 mm) can hold other parts, for example the Ø10 mm rod. Stage 1 may use those spaces. Stage 2 adds a translational insertion check that rejects layouts which would need a part to pass through another.

## B. STL processing strategy

**Pipeline (each step logged, nothing silent).**

```
ingest ─► parse ─► weld ─► validate ─► (repair?) ─► units check ─► mass properties ─► descriptors ─► classify ─► proxies ─► cache
```

| Step | What happens | Output / rule |
|---|---|---|
| Ingest | Copy into `data/<dataset>/`, SHA-256 per file and for the dataset | Frozen dataset id; every run records it |
| Parse | Binary STL (`84 + 50n` bytes) or ASCII | Triangle soup, float32 values preserved |
| Weld | Exact float32 coordinate match. An optional tolerance weld (1e-6 × bbox diagonal) is a *repair*, logged | Indexed mesh |
| Validate | Degenerate triangles; boundary, non-manifold and mis-oriented edges; connected components (edge-connected); Euler characteristic and genus; signed volume sign; **self-intersection test** (exact triangle–triangle via the geometry library) | `VALID`, `REPAIRABLE`, `INVALID-FOR-MASS` |
| Repair | Lossless and automatic: merge duplicates, drop zero-area faces, make winding consistent, flip inverted shells. Small holes (patch < 0.1 % of area) are auto-filled and labelled REPAIRED, with volume shown before and after. Anything else is withheld | The original file is never modified; repaired copies are cached with a diff |
| Units | Declared unit (default mm). Warn if the largest extent is > 340.5 mm or < 1 mm, or if it looks like metres or inches | Internal SI conversion at one point only |
| Mass properties | Divergence theorem over signed tetrahedra about the bbox centre (origin shift for precision). Computed **only** for closed, consistently oriented, non-self-intersecting meshes | V, COM, full 3×3 tensor about COM, principal moments and axes |
| Descriptors | AABB, approximate minimum OBB, convex hull (volume, area), solidity, OBB fill, sphericity, planar-area fraction, elongation, thinness, genus, components, triangle count | See C |
| Proxies | OBB, convex hull, convex decomposition, voxel grid, simplified offset mesh (hierarchy defined in D) | Each with a documented guarantee: covers the part, or does not |

**Withholding rule.** A part whose mass properties are WITHHELD still appears in the app. It's packed using a conservative envelope (its convex hull, or its OBB if no hull exists), labelled `ENVELOPE — mass properties withheld`. It contributes **no** mass to assembly physics until the user picks a repair, enters mass properties, or accepts a labelled convex-hull approximation. The assembly metrics then show "incomplete: 1 part excluded".

**Prototype already run (read-only, standard library).** A divergence-theorem mass-property routine, edge topology, quickhull and an approximate minimum OBB were run on the 22-file dataset in 4.3 s. All 19 packable parts are watertight and consistently oriented. The open fixture (3 boundary edges) and the inverted fixture (signed volume −9,397.9 mm³) are correctly withheld. The two-body fixture is reported as one rigid component with 2 shells. Two prototype defects were found and fixed:
- The first blob was effectively convex (solidity 0.997). It was regenerated at 0.814.
- The OBB search was stuck on a local minimum for the L-part. Starting candidates from hull faces fixed it.

The production pipeline adds what the prototype lacks: the self-intersection test, the repair operators and tolerance welding.

## C. Geometric classification

**Approach: multi-label descriptors, not one category.** Each part gets every label whose test it passes. Algorithm choice uses the descriptor values themselves, not a single class.

| Descriptor | Definition | Provisional threshold (to be tuned on more datasets) |
|---|---|---|
| Solidity | V / V_hull | ≥ 0.98 convex · 0.90–0.98 mildly concave · < 0.90 strongly concave |
| OBB fill | V / V_OBB(min) | ≥ 0.90 box-like |
| Thinness | e_min / e_mid (OBB extents sorted) | < 0.10 thin · < 0.25 plate-like |
| Elongation | e_max / e_mid | > 1.8 elongated |
| Planar-area fraction | Share of area in facet-normal bins holding ≥ 3 % of total area | > 0.95 planar-faceted · < 0.25 curved |
| Inertial symmetry | Two principal moments within 2 % | Symmetric |
| Highly irregular | Strongly concave ∧ curved ∧ not symmetric | Flag |
| Genus, components | From topology | Through-hole, multi-body |

**Result on the dataset.** The labels match the intended category for all 19 parts. The PCBs (solidity 0.988, because their notches are shallow) are "convex, box-like, thin" rather than "mildly concave". That's a correct reading of the geometry, so the intended labels in the manifest should say "near-convex".

**How classification drives algorithm selection** (details in D):

| If a part is… | Its cheapest *safe* proxy is… | Because |
|---|---|---|
| box-like (OBB fill ≥ 0.9) | OBB | < 10 % wasted |
| convex, not box-like | convex hull (exact for convex parts) | OBB would waste 21–50 % (sphere, ellipsoid, wedge) |
| mildly concave | convex hull | Waste ≤ 10 % |
| strongly concave / through-hole | convex decomposition or voxels; exact mesh for validation | Hull waste is 18–75 % (U-channel 0.249, tube 0.277, cross 0.488) |
| thin / plate-like | OBB, or a 2D outline + thickness | Stacking constraints apply in Stage 2 |
| highly irregular | voxels + exact mesh | No good analytic proxy |

## O. Ideal versus real-world packaging

**Stage 1 (IDEALIZED) solves:** minimise the normalised objectives over positions and the 24 orientations, subject to: no interpenetration (signed clearance ≥ −0.01 mm counts as contact, < −0.01 mm is overlap), every part inside the 100 × 100 × 340.5 mm box, and user locks. A separately reported free-rotation experiment uses continuous SO(3) orientations.

**Stage 2 (ENGINEERING-CONSTRAINED) adds constraints by type:**

| Constraint | How it is modelled | Data status |
|---|---|---|
| Enclosure walls 2.0 mm | Smaller inner box (96 × 96 × 336.5 mm) | ASSUMED |
| Corner rails 8.5 × 8.5 mm | Four full-length keep-out prisms | ASSUMED (CDS gives rail width; the internal frame shape is ours) |
| Clearances 2.0 / 1.0 mm + 0.2 mm tolerance | Inflated distance thresholds (2.2 mm part-part, 1.2 mm part-wall) | ASSUMED |
| PCB stack | PCB-tagged parts parallel to XY, centred, 4 × M3 rod keep-outs on the PC/104 hole pattern | ASSUMED pattern; hole positions to be confirmed in implementation from the PC/104 standard |
| Mounting allowance | 3 mm layer on the face that mounts to a wall, rail or deck, plus a reachability check | ASSUMED heuristic |
| Harness channel | 10 mm keep-out strip along one side wall | ASSUMED |
| Connector access | 15 mm deep zones on user-marked faces | Not modelled until faces are marked |
| Cable bend radius | — | NOT MODELLED (needs cable data) |
| Thermal | Rule tags (source, sensitive, needs wall), 10 mm source-to-sensitive separation | Inactive until tagged |
| Insertion / serviceability | Straight-line ±Z insertion in assembly order; "serviceable" parts removable alone | Heuristic |
| COM box | ±20 mm X/Y, ±70 mm Z about the geometric centre (to be verified from CDS Rev 14.1) | Standard |
| Launch loads | Proxies only (mass per interface, COM in box) | NOT ANALYSED |

**Comparison workspace (left IDEALIZED, right ENGINEERING-CONSTRAINED).** It has synchronised cameras, a movement overlay (per-part displacement arrows) and COM markers joined by a displacement vector with magnitude and direction. A metrics table shows the Δ of each objective. A **constraint attribution** analysis answers "which constraint cost the most". It re-solves Stage 2 with each constraint family relaxed in turn (warm-started from the Stage 2 result, same seed and budget) and reports the change in each objective. That's a measured sensitivity, not a narrative, and it's labelled with the budget it used.
