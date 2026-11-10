"""
Open a saved packing from a solutions_*.jsonl file (written by benchmark.py --save_solutions) in 3D and print its metrics.

    python replay.py results/solutions_large_fast_k10_n300.jsonl --dataset simple_concave --algorithm empty_maximal_spaces --trial 7
    python replay.py results/solutions_large_fast_k10_n300.jsonl --list                     (what is in the file)
    python replay.py ... --best                                                             (the densest trial of that dataset and algorithm)
"""

import json
import argparse
import numpy as np
import nesting_core

parser = argparse.ArgumentParser()
parser.add_argument("solutions_file")
parser.add_argument("--dataset", default=None)
parser.add_argument("--algorithm", default=None)
parser.add_argument("--trial", type=int, default=0)
parser.add_argument("--best", action="store_true", help="pick the densest trial instead of --trial")
parser.add_argument("--list", action="store_true", help="list datasets, algorithms and trial counts in the file")
parser.add_argument("--datasets_folder", default=None)
parser.add_argument("--save", default=None, help="write a PNG instead of opening a window")
arguments = parser.parse_args()

if arguments.datasets_folder is not None:
    nesting_core.DATASETS_FOLDER = arguments.datasets_folder

records = [json.loads(line) for line in open(arguments.solutions_file)]
if arguments.list:
    counts = {}
    for record in records:
        key = (record["dataset"], record["algorithm"], record["k"], record["mode"])
        counts[key] = counts.get(key, 0) + 1
    for key in sorted(counts):
        print(key[0].ljust(17) + key[1].ljust(22) + "k = " + str(key[2]).ljust(4) + key[3].ljust(10) + str(counts[key]) + " trials")
    raise SystemExit

matching = [record for record in records if (arguments.dataset is None or record["dataset"] == arguments.dataset) and (arguments.algorithm is None or record["algorithm"] == arguments.algorithm)]
if len(matching) == 0:
    raise SystemExit("no matching trials; use --list")
if arguments.best:
    record = max(matching, key=lambda record: record["density"] if record["valid"] else -1.0)
else:
    record = [record for record in matching if record["trial"] == arguments.trial][0]

all_parts = nesting_core.load_parts(record["dataset"], 1.0, 1.0)
parts_by_name = {part["name"]: part for part in all_parts}
selected_parts = [parts_by_name[name] for name in record["parts"]]
index_by_name = {name: index for index, name in enumerate(record["parts"])}
placements = [{"part_index": index_by_name[placement["part"]], "rotation": np.array(placement["rotation"]), "translation": np.array(placement["translation"])} for placement in record["placements"]]
container_size = None if record["container"] is None else np.array(record["container"])
result = nesting_core.evaluate_packing(selected_parts, placements, container_size, 1.0, 0.5)
print(record["dataset"] + "  " + record["algorithm"] + "  trial " + str(record["trial"]) + "  k = " + str(record["k"]))
print("density " + format(result["density"], ".3f") + "   box " + format(result["bbox_x"], ".0f") + " x " + format(result["bbox_y"], ".0f") + " x " + format(result["bbox_z"], ".0f") + " mm   aspect " + format(result["aspect_ratio"], ".2f") + "   COM offset " + format(100 * result["com_offset_normalized"], ".1f") + "%   min gap " + format(result["minimum_gap"], ".2f") + " mm   valid " + str(result["valid"]))
print("order: " + " > ".join(result["placement_order"]))

import pyvista
colors = ["#4e79a7", "#f28e2b", "#e15759", "#76b7b2", "#59a14f", "#edc948", "#b07aa1", "#ff9da7", "#9c755f", "#bab0ac", "#1f77b4", "#d62728"]
if arguments.save is not None:
    pyvista.OFF_SCREEN = True
plotter = pyvista.Plotter(window_size=[1200, 800])
plotter.set_background("white")
for placement in placements:
    part = selected_parts[placement["part_index"]]
    mesh = nesting_core.world_mesh(part, placement)
    face_array = np.hstack([np.full((len(mesh.faces), 1), 3), mesh.faces]).ravel()
    plotter.add_mesh(pyvista.PolyData(np.asarray(mesh.vertices), face_array), color=colors[placement["part_index"] % len(colors)], smooth_shading=True, split_sharp_edges=True, opacity=0.85)
all_vertices = np.vstack([nesting_core.world_vertices(selected_parts[placement["part_index"]], placement) for placement in placements])
low = all_vertices.min(axis=0)
high = all_vertices.max(axis=0)
plotter.add_mesh(pyvista.Box(bounds=(low[0], high[0], low[1], high[1], low[2], high[2])), style="wireframe", color="#333333", line_width=1.5)
plotter.add_mesh(pyvista.Sphere(radius=0.018 * float(np.linalg.norm(high - low)), center=result["center_of_mass"]), color="red")
plotter.add_mesh(pyvista.Sphere(radius=0.018 * float(np.linalg.norm(high - low)), center=result["bbox_center"]), color="black")
plotter.add_text(record["algorithm"].replace("_", " ") + "   density " + format(result["density"], ".3f"), position="upper_left", font_size=12, color="#222222")
plotter.view_isometric()
if arguments.save is not None:
    plotter.screenshot(arguments.save)
    print("saved " + arguments.save)
else:
    plotter.show()
