# Context for Claude sessions (nesting_bench)

Project: "Text to Spaceship" (UC Berkeley MEng capstone #156, Co-Design Lab, advisor Kosa Goucher-Lambert, coordinator Douglas McGowan, NASA Goddard collaborator Ryan McClelland). Goal: a text-to-satellite workflow where AI agents build and verify multi-part assemblies, applied to NASA's Habitable Worlds Observatory. Team: Adrian Apsay (agents, repo owner), Huai-Yi Wang (agent integration, SolidWorks pipeline, exact-shape heightfield packer), Sebastian Shunda (ME, manufacturability, CubeSat builder on branch v3), Dadmehr Ghasemfar (physical feasibility and verification, this benchmark).

This folder is Dadmehr's offline 3D nesting benchmark: 10 packing algorithms, 6 part categories (123 watertight STLs), Monte Carlo test procedure, metrics (density, bounding box, aspect ratio, COM offset, inertia, placement order, minimum gap, validity). Read README.md first. Results CSVs and slides.pdf are in results/.

Fall milestone (due 12/11/2026): nesting writeup and a standalone STL/STEP validity checker. Open questions for the team: volume utilization vs compact envelope, COM as a limit or an objective, clearance value, assembly sequencing, which HWO subassembly.

Code style (keep it): simple Python, one statement per line, never split a statement across lines, long descriptive variable names, minimal helper functions, numpy/scipy/trimesh only (pyvista for the viewer, manifold3d only for exact checks and dataset generation). Every algorithm has the signature in algorithms.py and is registered in ALGORITHMS and BENCHMARK_ALGORITHMS. Anything checkable by code must be checked by code (check_exact.py), never judged by eye.

Working with Dadmehr: terse, direct answers; challenge his assumptions; no em dashes; show word counts on prose; approve changes one at a time; documents in plain word-processor style. He runs Python 3.14 on Windows at C:\Users\danie\AppData\Local\Python\pythoncore-3.14-64\python.exe.
