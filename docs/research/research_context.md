# TEXT-TO-SPACESHIP — shared research brief (read fully before starting)

You are one of 13 research agents (groups A–I) feeding an engineering protocol for a
CubeSat 3D packaging optimizer. A lead architect will merge your report with the others.
This is the RESEARCH phase. Nothing is implemented until the user approves the protocol.

## Hard rules
- Do NOT create, modify or delete any file anywhere. Do NOT install anything (no pip, npm, uv, winget).
- Do NOT launch, script or call Autodesk Fusion 360 (an install exists on disk; it is out of bounds).
- You MAY read (read-only) `D:\text-to-spaceship\data\synthetic\manifest.json` and the STL files beside it.
- You MAY use web search / web fetch for public papers, documentation, GitHub READMEs, PyPI/npm pages.
  Never upload or paste project data into any external service.
- No fabrication. Every non-obvious factual claim (capability, license, version, wheel availability,
  complexity bound, published benchmark figure) needs a source URL, or must be tagged UNVERIFIED.
  Estimates for our dataset must be tagged ESTIMATE with the reasoning shown. Never present an
  estimate as a measurement.
- Licenses: only permissive dependencies are acceptable (MIT, BSD, Apache-2.0, MPL-2.0, Zlib, ISC).
  Flag GPL/LGPL/AGPL/EPL/commercial-only options as excluded (you may mention them as references).

## Accepted decisions (user accepted all defaults)
- Form factor 3U per CubeSat Design Specification (CDS) Rev 14.1. Body envelope 100.0 x 100.0 x 340.5 mm.
  Recalled limits (to be verified by group E): mass <= 6.00 kg; COM within +-20 mm (X, Y) and +-70 mm (Z)
  of the geometric centre. Frame: origin at enclosure geometric centre, +Z along the rails, right-handed.
  SI internally; display mm / kg / kg*m^2.
- Two stages:
  - Stage 1 IDEALIZED: the full 100 x 100 x 340.5 mm box is usable; rigid parts; no interpenetration;
    zero clearance (contact allowed within 0.01 mm numerical tolerance); no mounting hardware.
  - Stage 2 ENGINEERING-CONSTRAINED (labelled, never "flight-qualified"): ASSUMED parametric frame with
    four 8.5 x 8.5 mm corner rails along the full length and 2.0 mm walls; clearances 2.0 mm part-to-part,
    1.0 mm part-to-wall, plus 0.2 mm manufacturing tolerance; PCB-tagged parts stacked parallel to XY
    with PC/104-style 4 x M3 rod keep-outs; 3 mm ASSUMED mounting layer on each other part's mounting face;
    one 10 mm harness channel along a side wall; connector zones only where the user marks faces;
    rule-based thermal tags (off until tagged); integration along +-Z with end caps off, straight-line
    insertion check in assembly order; CDS COM box becomes a HARD constraint. No FEA/vibration analysis.
- Orientations: Stage 1 = the 24 axis-aligned orientations, plus a separately reported free-rotation
  experiment; Stage 2 = axis-aligned only, restrictable per part.
- Objectives (all normalised to [0,1] via ideal/nadir points from single-objective runs):
  - Packing efficiency = COMPACTNESS: minimise the enclosure length used along Z (contiguous free space at
    one end). Also report the largest empty axis-aligned box. Plain volume fraction is shown as "Space Used"
    but cannot rank layouts (it is constant when every part is inside a fixed enclosure).
  - COM accuracy: distance of assembly COM to target (default: geometric centre). Soft in Stage 1;
    distance stays an objective in Stage 2 while the CDS box is hard.
  - Rotational inertia: 3-axis-controlled spacecraft (reaction wheels / magnetorquers): minimise principal
    moments (agility) and minimise products of inertia (principal axes close to body axes).
  - Mass distribution: no extra rules beyond what COM and inertia imply; explanations derived from numbers.
  - Interactive optimisation uses weighted Tchebycheff scalarisation; a background multi-objective run
    (NSGA-II family) builds the Pareto front for comparison. Hard constraints never enter the weighted sum.
    Single-objective presets put ~70% weight on their objective; Balanced is equal weights.
- Uniform density 2,700 kg/m^3 placeholder (with uniform density, the optimal arrangement does not depend on
  the density value). Users may override mass (effective density = m/V, inertia scales linearly with mass)
  or density per part. No ballast. Mass limit is a dataset check, not an optimiser constraint.
- Mesh repair: lossless fixes automatic; small holes (< 0.1% of area) auto-filled and labelled REPAIRED;
  worse defects -> mass properties WITHHELD, part packed with a conservative labelled envelope.
- Architecture: local web app bound to localhost. Python backend (FastAPI, NumPy/SciPy, trimesh,
  manifold3d, an FCL-family collision library, pymoo) + React/TypeScript/three.js frontend, WebSocket
  streaming. Windows 10 only for now, OS-neutral code, no Docker. Python 3.12+ via portable uv (exact
  version chosen to match wheels); Node.js 24 LTS portable zip; MinGit portable; Playwright for UI tests.
- Machine: Intel i5-12600K (10 cores / 16 threads), 15.8 GB RAM, AMD Radeon RX 6800 (no CUDA),
  3840 x 2160 display. Optimiser may use up to 12 threads. Benchmark suite capped at ~3 h total.
- Latency targets (to be measured, not promised): control echo within one frame; mass edit -> COM marker
  and metrics < 50 ms; re-optimisation starts 150 ms after the last slider move, stale generations dropped;
  first improved VALID layout typically < 2 s for ~20 parts; refinements streamed every 250–500 ms;
  viewport 60 fps target in a 1440p-sized window.
- The viewport always shows the best VALIDATED layout; candidates may appear as a faint ghost marked
  UNVERIFIED; animated transitions are labelled "visual interpolation — not a validated motion path".
- Fusion 360 is a later, independent CAD validation layer (status NOT CONFIGURED), never the optimiser.
- Validation: unit tests vs analytic solutions, collision tests at 1 um tolerance, 10 seeds per stochastic
  algorithm, an independent second mass-property implementation.

## The shared dataset (all agents use this; units mm)
Location: `D:\text-to-spaceship\data\synthetic\` (manifest.json has construction parameters, SHA-256,
analytic mass properties). Dataset SHA-256: 8dd5692792870f55a2e666a96555d7172e7e40adff351026d1eb17fa087e0f7f.
19 packable parts + 3 validation fixtures (fixtures/: two-body file, open mesh, inverted normals).
Totals (packable): 1,080.0 cm^3 solid, 2.916 kg at 2,700 kg/m^3, 31.7% of the 3U body volume.
Three parts are authored in tilted/offset frames (payload_electronics_box, ellipsoid_module, wedge_bracket).

Values below were computed by a read-only standard-library analysis (divergence-theorem mass properties,
quickhull, approximate minimum OBB). Solidity = volume / convex-hull volume.

| Part | Tris | Volume cm3 | Mass kg @2700 | OBB mm | Solidity | OBB fill | Labels (computed) |
|---|---|---|---|---|---|---|---|
| battery_pack | 12 | 140.80 | 0.380 | 80.0 x 80.0 x 22.0 | 1.000 | 1.000 | box-like, convex |
| camera_with_lens | 388 | 121.17 | 0.327 | 70.0 x 50.0 x 50.0 | 0.824 | 0.692 | strongly concave |
| cross_connector_hub | 60 | 28.67 | 0.077 | 48.0 x 45.3 x 45.3 | 0.488 | 0.292 | strongly concave |
| ellipsoid_module | 9024 | 37.63 | 0.102 | 60.0 x 40.0 x 30.0 | 1.000 | 0.523 | convex, curved |
| gas_tank_capsule | 9216 | 119.15 | 0.322 | 90.0 x 45.0 x 45.0 | 1.000 | 0.654 | convex, elongated, curved |
| gear_mechanism | 252 | 15.88 | 0.043 | 49.5 x 49.5 x 10.0 | 0.818 | 0.649 | strongly concave, plate-like |
| irregular_blob | 50880 | 71.28 | 0.192 | 54.7 x 53.4 x 52.9 | 0.814 | 0.462 | strongly concave, curved, highly irregular |
| l_shaped_electronics | 20 | 86.25 | 0.233 | 70.0 x 70.0 x 30.0 | 0.740 | 0.587 | strongly concave |
| magnetometer_ring_torus | 6144 | 37.63 | 0.102 | 76.0 x 76.0 x 16.0 | 0.569 | 0.408 | strongly concave, plate-like, through-hole |
| magnetorquer_rod | 192 | 6.27 | 0.017 | 80.0 x 10.0 x 10.0 | 1.000 | 0.787 | convex, elongated |
| optics_baffle_tube | 768 | 20.91 | 0.056 | 60.0 x 40.0 x 40.0 | 0.277 | 0.218 | strongly concave, through-hole |
| payload_electronics_box | 12 | 72.00 | 0.194 | 60.0 x 40.0 x 30.0 | 1.000 | 1.000 | box-like, convex |
| pcb_eps | 44 | 12.65 | 0.034 | 90.0 x 90.0 x 1.6 | 0.988 | 0.976 | box-like, thin (7 mm corner notches) |
| pcb_obc | 44 | 12.65 | 0.034 | 90.0 x 90.0 x 1.6 | 0.988 | 0.976 | box-like, thin (7 mm corner notches) |
| propellant_tank_sphere | 9024 | 112.90 | 0.305 | 60.0 x 60.0 x 59.9 | 1.000 | 0.524 | convex, curved |
| reaction_wheel | 384 | 49.05 | 0.132 | 50.0 x 50.0 x 25.0 | 1.000 | 0.786 | convex |
| sensor_housing_hex | 20 | 69.28 | 0.187 | 50.0 x 46.2 x 40.0 | 1.000 | 0.750 | convex |
| u_channel_bracket | 28 | 35.84 | 0.097 | 80.0 x 60.0 x 30.0 | 0.249 | 0.249 | strongly concave (open cavity) |
| wedge_bracket | 8 | 30.00 | 0.081 | 50.0 x 40.0 x 30.0 | 1.000 | 0.500 | convex |

Validation already observed (analysis vs analytic, unit density): exact polyhedra match to 0–5e-8 relative
(float32 STL rounding); tessellated shapes match their discretisation error (e.g. 96-segment cylinder
volume 7.14e-4 low; 32x96 torus 7.12e-3 low). Open and inverted fixtures are correctly WITHHELD.

Interesting packing features: the torus hole (inner diameter 44 mm) and tube bore (34 mm) can host other
parts (e.g. the 10 mm rod); the U-channel cavity (52 x 26 mm) can host parts; such interlocking may be
geometrically valid but not assemblable — relevant to Stage 2. Parts' OBB volumes sum to far more than
their solid volume (mean OBB fill ~0.6), so box proxies waste a lot of space for curved/concave parts.

## Report format (markdown, at most ~1,800 words, these headings in this order)
0. Summary (one paragraph)
1. Recommended approach
2. Technical justification
3. Advantages
4. Limitations
5. Expected computational cost (complexity, plus an ESTIMATE for this 19-part dataset on this CPU)
6. Relevant libraries (name, license, Python 3.12/3.13 Windows x64 wheels or JS availability, maintenance, URL)
7. Validation methodology (concrete, executable test cases)
8. Implementation difficulty (1–5 with reasons)
9. Alternatives considered and rejected (brief)
10. Sources (URLs)
11. Open questions and UNVERIFIED claims
