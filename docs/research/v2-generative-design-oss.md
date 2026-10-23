# V2 research: open-source generative design for metal 3D-printed brackets (2026-10-22)

Research only (nothing installed or run when this was written). EST = the researcher's estimate; UNVERIFIED = not
confirmed from a primary source.

## Contest entrants chosen

| Entrant | Method | Licence | Install on Windows, Python 3.14, no admin | Notes |
|---|---|---|---|---|
| **Baseline (V1)** | conformal shell 2 mm + ribs + plate, signed-distance level set (manifold3d) | own | already installed | geometric rule, no FE in the loop |
| **pyMOTO 2.0.1** | SIMP, OC / MMA / GCMMA, structured voxel grid, passive solid/void via fixed densities | MIT | pure-Python wheel (Python 3.14 untested upstream) | best fit: masks map directly onto the bracket's reserved box; stress-constraint example exists |
| **BESO for CalculiX** | bi-directional evolutionary, stiffness or von Mises failure index | LGPL-3 | plain Python scripts + external `ccx.exe` | genuinely different algorithm; needs an `.inp` (gmsh tets, element sets, supports, loads) |
| **pytopo3d 0.3.0** | SIMP, OC, compliance only | MIT | pure-Python wheel | quick off-the-shelf control entry; obstacles from JSON/STL |
| torch-fem 0.14.0 (stretch) | SIMP on tetrahedral meshes | MIT | `pyamg` has no cp314 Windows wheel (blocker) | measured 214 k tets, 10.7 s/iteration on an M1 Pro CPU (upstream example) |

Not usable here: FEniCSx-based tools (FEniTop, dolfiny, FormOpt — need PETSc, unavailable on Windows), TopOpt_in_PETSc,
ToPy (Python 2), ToOptix (2019, no licence), OpenLSTO (C++, no Python API), JAX-FEM (2D TO example only, PETSc
reference environment), DL4TO (stale; packaging fixes needed; slow CPU solver — stretch only), OpenPisco (only
plausible level-set code; Windows features unclear).

ML / AI 3D generators (Shap-E, TRELLIS.2, CAD-Recode, Optimize-Any-Topology (2D), TopoDiff (2D), NTopo): none takes
loads, supports or keep-outs; they are shape generators or 2D research code, not contest entrants.

## Contest hygiene

- Every entrant, the baseline included, is scored by the same referee FE on its exported mesh (independent of each
  tool's own objective): mass, peak (filtered) von Mises against the AlSi10Mg allowable with the safety factors,
  displacement, first natural frequency.
- Same design domain, same voxel size (~0.5–1.5 mm) and the same minimum feature size (filter radius ≥ 1.5 voxels,
  ~2–3 mm members, comparable to the 2 mm baseline shell) for every entrant.

Key sources: pyMOTO <https://github.com/aatmdelissen/pyMOTO>, BESO <https://github.com/calculix/beso>, pytopo3d
<https://github.com/jihoonkim888/PyTopo3D>, torch-fem <https://github.com/meyer-nils/torch-fem>, DL4TO
<https://github.com/dl4to/dl4to>, dolfinx Windows status <https://github.com/FEniCS/dolfinx>.
