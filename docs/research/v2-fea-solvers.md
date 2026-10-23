# V2 research: open-source FEA for bracket strength (2026-10-22)

Research only; versions and wheels checked on PyPI / conda-forge / official sites on 2026-10-22. Runtimes are
estimates (nothing was run). UNVERIFIED = not confirmed from a primary source.

## Chosen route

| Role | Tool | Why | Install (Windows, Python 3.14, no admin) |
|---|---|---|---|
| Solver A | **CalculiX ccx 2.23** (GPL-2), C3D10 quadratic tets, `*STATIC`, `*FREQUENCY` (ARPACK) | mature, independent code base, standard input deck | standalone `ccx.exe` from the conda-forge win-64 package (repodata gives SHA-256; build updated 2026-09-28) |
| Solver B | **NGSolve 6.2.2608** (LGPL-2.1), `VectorH1(order=2)`, CG + BDDC, PINVIT / scipy eigensolver | cp314 win_amd64 wheel, released 2026-10-01 | `uv add ngsolve==6.2.2608` (+ netgen-mesher, ngsolve-openblas 0.3.33) |
| Arbiter (optional) | scikit-fem 12.0.2 (BSD), `ElementTetP2` | pure Python, short readable assembly | pip wheel |
| Meshing | **gmsh 4.15.2** (GPL-2+) Python API, second order with `Mesh.SecondOrderLinear=1`; pytetwild 0.4.2 fallback for broken STLs | Windows wheel | pip wheel |

Rejected on this setup: FEniCSx (conda-only, needs MSVC, no SLEPc on Windows), SfePy (needs a compiler), PyMFEM (no
Windows wheel), GetFEM (old Windows binary only), Code_Aster (no native Windows build), PyAnsys (needs a licensed
Ansys install; Ansys Student is educational-only with a 128 K node limit), FeenoX (Linux only).

## Pitfalls to respect

- Linear tets under-predict stress badly (NAFEMS LE10: 1.5–4.4 MPa vs 5.38 target); quadratic tets are mandatory.
- Peak stress at fixed-face edges and re-entrant corners is a singularity: report a *filtered* maximum (exclude a band
  ~2 elements / ~1 mm around fixed and load edges); fix only washer/bolt footprints, not whole faces.
- Consistent nodal loads on quadratic faces (corner 0, mid-side 1/3) — compute the load vector once and share it.
- Units mm–N–MPa–t/mm³ (AlSi10Mg ≈ 2.67e-9 t/mm³). CalculiX threading: check 1 vs N threads give identical results.
- gmsh vs meshio tet10 node ordering differs (nodes 8 and 9 swapped).

## Verification protocol (each solver, before it is trusted)

1. Cantilever 200×10×6 mm, E = 70 GPa, ν = 0.33, tip load 100 N: tip deflection within 1 % of PL³/3EI + PL/κGA,
   mid-span bending stress within 2 %, first frequency within 2 % of the Euler–Bernoulli value, Σ reactions = load.
2. Lamé thick cylinder (ri 10, ro 20 mm, open ends): hoop stress at ri and radial displacement within 2 %.
3. Optional NAFEMS LE10 within ±10 % of 5.38 MPa; the solvers within 3 % of each other.
4. Free-free modal: six rigid-body modes near 0 Hz.

Per bracket: three meshes (h, h/1.5, h/2.25); accept when max |u| and f1 change < 1 %, reactions < 0.5 %, filtered
max von Mises < 5 % between the last two. Cross-solver on the same mesh: displacements within 0.1 %, f1 within 0.5 %,
centroid stress within 1 %; on independent meshes: max |u| and f1 within 2 %, filtered max stress within 5 %.

Key sources: CoFEA LE10 results <https://cofea.readthedocs.io/en/latest/benchmarks/001-thick-plate/results.html>,
NGSolve elasticity tutorial <https://docu.ngsolve.org/latest/i-tutorials/wta/elasticity3D.html>, CalculiX
<http://www.dhondt.de/>, conda-forge calculix <https://anaconda.org/conda-forge/calculix>, gmsh
<https://pypi.org/project/gmsh/>, scikit-fem <https://pypi.org/project/scikit-fem/>.
