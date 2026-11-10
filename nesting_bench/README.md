# Nesting benchmark (Text to Spaceship)

Offline Python test bench for 3D nesting / packing algorithms. For every algorithm and every object category it draws k random parts, packs them, records every metric, repeats n times, and averages (Monte Carlo).

## Setup (once)

Python 3.12 or newer. In a terminal opened in this folder (use the full path of your Python if "python" opens a different install):

    python -m pip install numpy scipy trimesh pyvista matplotlib

## Files

nesting_core.py: shared library (load STLs, rotate and voxelize parts, score a packing). Not run directly.
algorithms.py: the packing algorithms and the restart wrapper. Not run directly.
viewer.py: interactive window. Click a category and an algorithm, drag k and seed, see the packing and its metrics; "compare all" shows every algorithm on the same parts.
view.py: command-line version of the viewer (one packing per algorithm, metrics printed, optional --save picture.png).
benchmark.py: run this for the full test procedure; writes CSVs and a bar chart to results/.
check_exact.py: exact overlap check (manifold3d mesh booleans) on sample packings of every algorithm. Needs manifold3d.
replay.py: reopen any saved packing from a solutions_*.jsonl file (benchmark.py --save_solutions) in 3D, or --best for the densest trial.
make_report.py: result plots with 99% confidence intervals (results/plots/*.png, report PDF, leaderboard.csv) from any set of summary CSVs.
make_videos.py: one MP4 per algorithm showing it at work in 3D (videos/, needs pyvista and ffmpeg).
make_slides.py: builds slides.pdf (algorithm explainers and result plots) from the CSVs in results/. render_examples.py makes the part pictures it uses (needs pyvista).
generate_datasets.py: rebuilds datasets/. Not needed (datasets are included).

For one test: viewer.py first (sanity check by eye), then benchmark.py.

    python viewer.py
    python viewer.py --dataset simple_concave --algorithm "compare all" --k 10
    python benchmark.py                                  (defaults: all 10 algorithms, all 6 categories, k = 10, n = 100, t = 0.5 mm; about 2.5 h)
    python benchmark.py --algorithms shelf_packing box_extreme_points voxel_bottom_left heightfield_drop --trials 1000
    python benchmark.py --datasets cuboids --trials 500
    python check_exact.py --algorithms heightfield_drop simulated_annealing --datasets simple_concave --k 8 --trials 3

## Test procedure (benchmark.py)

For each algorithm, for each category, for n trials: pick k random parts (same sets for every algorithm), pack them (randomized algorithms get --restarts tries, best valid density kept), record the metrics. Then average per algorithm and category.

## Metrics (per trial, averaged in the summary)

1. Bounding box x, y, z; % volume utilized (density = parts volume / box volume); aspect ratio (longest / shortest side).
2. Center of mass (COM), center of volume (COV = box center), distance COM to COV in mm and as % of the box diagonal. Density of every part is --density (default 1 g/cm^3; override single parts with datasets/<category>/densities.csv, lines "part_name,density").
3. Moments of inertia about the COM along the box axes (Ixx, Iyy, Izz, plus Ixy, Ixz, Iyz) and principal moments (I1 <= I2 <= I3), g*mm^2.
4. Placement order (recorded only; force_based has none since all parts move at once).
5. Clearance: minimum gap between any two parts (nearest distance between dense surface samples, about 0.5 mm spacing, so it can read slightly high) and whether it meets t (--clearance, default 0.5 mm). The packers enforce t.

Also: valid (no overlap), parts placed, run time. Score = mean density with invalid trials counted as 0.

## Algorithms (algorithms.py)

random_rejection: random angle and position, rejected if its box comes within t of a placed box. The floor any real method must beat.
shelf_packing: lay parts flat, tallest first; fill a row, then the next row, then a new layer.
box_bottom_left: each part goes to the lowest, then frontmost, then leftmost free spot on a square floor.
box_extreme_points: only try spots at corners of placed boxes; keep the one that keeps the overall box smallest.
voxel_bottom_left: parts voxelized at their true shape (so concave parts can interlock); an FFT finds every collision-free spot; keep the one that keeps the overall box smallest.
force_based: start overlapping at random; repeatedly squeeze everything toward the middle and push overlapping pairs apart; keep the tightest overlap-free state.
force_based_v2: force_based with an anisotropic squeeze toward a target cube (no long rows), compaction (every box slides toward the origin), and orientation re-picking.
heightfield_drop: Huai-Yi's exact-shape drop. The stack is a 2D height map; a part lands where its bottom profile first meets the stack's top profile; tried at every (x, y) and orientation. Overlap-free by construction; nothing can slide under an overhang.
simulated_annealing: searches over placement order and orientation; each candidate is decoded by the voxel packer (orientations fixed) and scored by density; worse moves accepted with probability exp(gain / temperature). Fixed time budget (search_seconds, 5 s).
genetic_algorithm: same search space and decoder; population of 12, best half kept, children by order crossover plus one mutation. Same time budget.

Orientation: random_rejection uses any angle; the others turn each part so its tightest box is axis-aligned, then try its 6 face-down orientations (force_based picks one at random per try). Box-based methods (shelf, bottom-left, extreme points, force) treat each part as its box, so they cannot nest concave parts; voxel_bottom_left, heightfield_drop and the two search methods can. random_scatter (overlaps allowed) is available in view.py for pictures only.

Settings (algorithms.DEFAULT_SETTINGS): random_attempts 300, voxel_pitch 2.0 mm, voxel_orientations faces (6) or all (24), clearance 0.5 mm, restarts 3, force_iterations 40, search_seconds 5.0, search_decoder voxel or box, population_size 12.

empty_maximal_spaces: box packing over a list of maximal empty boxes (the standard EMS method); the best box method at every k.
genetic_heightfield: genetic_algorithm with the heightfield drop as decoder (about 10x more evaluations in the same 5 s); keeps the aspect ratio near 2.
best_of_fast: runs shelf, bottom-left, extreme points, EMS, voxel and heightfield and keeps the densest (the "let the tool choose" option).
genetic_box: genetic_algorithm with the exact extreme-points box decoder (no grid rounding, ~50x cheaper decodes); boxes only. Not in BENCHMARK_ALGORITHMS; used in the verification tests.

Adding an algorithm: write a function with the signature at the top of algorithms.py and add it to ALGORITHMS and BENCHMARK_ALGORITHMS (and RANDOMIZED_ALGORITHMS if it uses randomness, ORDERED_ALGORITHMS if its placement order means something).

## Run time

About 2.5 s per trial for the six original algorithms together (force_based and voxel_bottom_left are the slow ones), so n = 100 over 6 categories is roughly 25 to 30 minutes. The two search algorithms cost 5 s per packing each (their time budget), so all ten at n = 100 is about 2.5 hours. Expect 2 to 3 times longer on a light laptop. Pick --algorithms to run less.

## Measures added Nov 6
contacts: part pairs whose surfaces come within t + 0.5 mm (touching through the clearance padding); contacts_per_part; isolated_parts (parts touching nothing). Note: voxel and heightfield parts sit 1 to 2 mm apart because of the 2 mm grid, so they register few contacts within the 1 mm band.
99% confidence intervals (Student t) of every mean are in the summary CSVs (<metric>_ci99_low/high) and on the charts.
Solutions: with --save_solutions every trial's packing (part name, rotation matrix, position) goes to solutions_<name>.jsonl; replay.py opens them.
--resume continues an interrupted run (pairs already complete are kept). --workers N runs trials in parallel. --datasets_folder picks datasets/ (20 per category) or datasets_large/ (60 per category, seed 2027).

## Verification tests (verification/)
Two tests with known optima, run by verification/run_verification.py (see its docstring). Instances live in datasets_scrabble/ (600 cut solids, generate_scrabble.py) and datasets_literature/ (8 proven packings, generate_literature.py + known_packings.py).
Scrabble verification test: a 60 mm cube or sphere cut into k = 6, 9, 12, 15 pieces (guillotine, tilted, or merged/concave cuts), 25 instances each; ceiling = the solid's own box.
Known-literature verification test: 5/10/17 equal circles in a square as cylinders, 8/9/14 equal spheres in a cube, Soma cube, Slothouber-Graatsma; ceiling = the proven box.
Modes: open (ratio = density / ceiling) and container (the proven box; ratio = fraction of parts that fit). Clearance t = 0 (a perfect fit needs it), voxel pitch 2 mm (plus 1 mm for the literature grid methods), exact manifold3d overlap check on every run.
Outputs: results/verification_<test>_<mode>[_pitch1][_tag]_{trials,solutions.jsonl,summary,ranking}.csv, plots in results/plots_verification/, verification_report.pdf. genetic_box (GA with the exact box decoder) was run as a diagnostic (tag geneticbox).

## Results so far (results/)

Large-pool study (datasets_large, open mode, t = 0.5 mm): summary_large_fast_k{10,20,30}_n300.csv (10 fast algorithms), summary_large_search_k{10,20,30}_n100.csv (3 search algorithms), solutions_*.jsonl for every trial, report_large.pdf and plots/ (99% CI charts), leaderboard.csv (every dataset x k x algorithm ranked).


summary_20261027_142917.csv: six original algorithms, n = 100, k = 10, open mode.
summary_*_new4_n100.csv: the four new algorithms on the same part sets (same seeds).
summary_n1000_k10_all6.csv: the six original algorithms at n = 1000 (merged from summary_n1000_k10.csv and summary_n1000_k10_random_force.csv; the per-trial file of the random_force run was lost, only its summary is kept).
summary_*_k5 / k20 / k30.csv: the same four at k = 5, 20, 30, n = 100.
summary_*_container_k30.csv: container mode (100 mm cube), k = 30, n = 100, eight fast algorithms.
slides.pdf: one slide per algorithm and the result plots, built by make_slides.py.

## Limits

Overlap check is voxel based and gap measurement is sample based (both approximate); check_exact.py does the exact check on samples. The voxel grid only guarantees clearance along x, y, z (diagonal gaps can be slightly under t). No mounting, support, assemblability or thermal checks yet. Algorithms optimize volume only; COM, inertia and clearance are reported (clearance is also enforced).
