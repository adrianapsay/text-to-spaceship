"""
Pick k random parts from a dataset, pack them with one algorithm (or all of them side by side), print the metrics, and open a 3D window.

Examples:
    python view.py --dataset real_shapes --k 6 --algorithm random_scatter
    python view.py --dataset complex_concave --k 8 --algorithm voxel_bottom_left
    python view.py --dataset simple_concave --k 8 --algorithm all
    python view.py --dataset cuboids --k 10 --algorithm all --mode container --container 100 100 100
    python view.py --dataset real_shapes --k 6 --algorithm all --save picture.png     (saves an image instead of opening a window)

Mouse: left drag rotates, scroll zooms, shift + drag pans. Press q to close.
In the window: red ball = center of mass of the packing, black ball = center of the bounding box, numbers = placement order.
"""

import argparse
import time
import numpy as np
import pyvista
import nesting_core
import algorithms


PART_COLORS = ["#4e79a7", "#f28e2b", "#e15759", "#76b7b2", "#59a14f", "#edc948", "#b07aa1", "#ff9da7", "#9c755f", "#bab0ac"]

parser = argparse.ArgumentParser(description="Visualize one packing.")
parser.add_argument("--dataset", default="real_shapes", choices=nesting_core.list_datasets())
parser.add_argument("--k", type=int, default=10, help="number of random parts to pick")
parser.add_argument("--algorithm", default="all", choices=list(algorithms.ALGORITHMS.keys()) + ["all"], help="one algorithm, or all (the ten benchmark algorithms)")
parser.add_argument("--mode", default="open", choices=["open", "container"], help="open = minimize bounding box, container = fit as many as possible in --container")
parser.add_argument("--container", type=float, nargs=3, default=[100.0, 100.0, 100.0], help="container size in mm (container mode only)")
parser.add_argument("--seed", type=int, default=0)
parser.add_argument("--voxel_pitch", type=float, default=algorithms.DEFAULT_SETTINGS["voxel_pitch"])
parser.add_argument("--voxel_orientations", default=algorithms.DEFAULT_SETTINGS["voxel_orientations"], choices=["faces", "all"])
parser.add_argument("--clearance", type=float, default=algorithms.DEFAULT_SETTINGS["clearance"], help="minimum gap t between parts, mm")
parser.add_argument("--restarts", type=int, default=algorithms.DEFAULT_SETTINGS["restarts"], help="tries for randomized algorithms (best kept)")
parser.add_argument("--density", type=float, default=1.0, help="density of every part in g/cm^3 (override single parts with datasets/<dataset>/densities.csv)")
parser.add_argument("--save", default=None, help="save a PNG to this path instead of opening a window")
arguments = parser.parse_args()

settings = dict(algorithms.DEFAULT_SETTINGS)
settings["voxel_pitch"] = arguments.voxel_pitch
settings["voxel_orientations"] = arguments.voxel_orientations
settings["clearance"] = arguments.clearance
settings["restarts"] = arguments.restarts
check_pitch = arguments.voxel_pitch / 2.0
container_size = None if arguments.mode == "open" else np.array(arguments.container)

print("Loading " + arguments.dataset + " ...")
all_parts = nesting_core.load_parts(arguments.dataset, check_pitch, arguments.density)
selection_generator = np.random.default_rng(arguments.seed)
selected_indices = selection_generator.choice(len(all_parts), size=arguments.k, replace=arguments.k > len(all_parts))
selected_parts = [all_parts[index] for index in selected_indices]
print("Parts: " + ", ".join(part["name"] for part in selected_parts))

if arguments.algorithm == "all":
    algorithm_names = algorithms.BENCHMARK_ALGORITHMS
else:
    algorithm_names = [arguments.algorithm]

plot_columns = min(len(algorithm_names), 3)
plot_rows = (len(algorithm_names) + plot_columns - 1) // plot_columns
plotter = pyvista.Plotter(shape=(plot_rows, plot_columns), off_screen=arguments.save is not None, window_size=[520 * plot_columns, 520 * plot_rows])
for column, algorithm_name in enumerate(algorithm_names):
    placements, result, run_seconds = algorithms.run_algorithm(algorithm_name, selected_parts, container_size, arguments.seed, settings, check_pitch)

    print("")
    print(algorithm_name + "  (" + format(run_seconds, ".2f") + " s)")
    print("  placed            " + str(result["parts_placed"]) + " / " + str(result["parts_requested"]))
    print("  bounding box mm   " + format(result["bbox_x"], ".1f") + " x " + format(result["bbox_y"], ".1f") + " x " + format(result["bbox_z"], ".1f"))
    print("  bbox volume mm3   " + format(result["bbox_volume"], ".0f"))
    print("  parts volume mm3  " + format(result["placed_volume"], ".0f"))
    print("  density           " + format(result["density"], ".3f") + "   (% volume utilized = parts volume / bounding box volume)")
    print("  aspect ratio      " + format(result["aspect_ratio"], ".2f") + "   (longest / shortest box side)")
    print("  minimum gap mm    " + format(result["minimum_gap"], ".2f") + "   (clearance t = " + str(arguments.clearance) + " mm met: " + str(result["clearance_ok"]) + ")")
    if container_size is not None:
        print("  container fill    " + format(result["container_fill"], ".3f") + "   (parts volume / container volume)")
    print("  overlap mm3       " + format(result["overlap_volume"], ".0f") + "   (" + format(100 * result["overlap_fraction"], ".1f") + "% of parts volume)")
    print("  valid             " + str(result["valid"]))
    print("  total mass g      " + format(result["total_mass"], ".1f") + "   (density " + str(arguments.density) + " g/cm3 unless overridden)")
    print("  center of mass    " + np.array2string(result["center_of_mass"], precision=1) + "   bbox center " + np.array2string(result["bbox_center"], precision=1))
    print("  COM offset mm     " + format(result["com_offset"], ".2f") + "   (" + format(100 * result["com_offset_normalized"], ".1f") + "% of bbox diagonal)")
    if container_size is not None:
        print("  COM to container center mm  " + format(result["com_offset_from_container_center"], ".2f"))
    inertia_tensor = result["inertia_tensor"]
    print("  inertia g*mm2     Ixx " + format(inertia_tensor[0, 0], ".0f") + "  Iyy " + format(inertia_tensor[1, 1], ".0f") + "  Izz " + format(inertia_tensor[2, 2], ".0f"))
    print("  principal g*mm2   I1 " + format(result["principal_moments"][0], ".0f") + "  I2 " + format(result["principal_moments"][1], ".0f") + "  I3 " + format(result["principal_moments"][2], ".0f"))
    print("  products g*mm2    Ixy " + format(inertia_tensor[0, 1], ".0f") + "  Ixz " + format(inertia_tensor[0, 2], ".0f") + "  Iyz " + format(inertia_tensor[1, 2], ".0f") + "   (about the packing COM, along box x, y, z)")
    if len(result["placement_order"]) > 0:
        print("  placement order   " + " > ".join(result["placement_order"]))
    else:
        print("  placement order   none (all parts move at once)")

    plotter.subplot(column // plot_columns, column % plot_columns)
    for placement in placements:
        part = selected_parts[placement["part_index"]]
        moved_mesh = nesting_core.world_mesh(part, placement)
        face_array = np.hstack([np.full((len(moved_mesh.faces), 1), 3), moved_mesh.faces]).ravel()
        plotter.add_mesh(pyvista.PolyData(np.asarray(moved_mesh.vertices), face_array), color=PART_COLORS[placement["part_index"] % len(PART_COLORS)], smooth_shading=True, split_sharp_edges=True, opacity=0.6)
    if len(placements) > 0:
        all_vertices = np.vstack([nesting_core.world_vertices(selected_parts[placement["part_index"]], placement) for placement in placements])
        bbox_minimum = all_vertices.min(axis=0)
        bbox_maximum = all_vertices.max(axis=0)
        plotter.add_mesh(pyvista.Box(bounds=(bbox_minimum[0], bbox_maximum[0], bbox_minimum[1], bbox_maximum[1], bbox_minimum[2], bbox_maximum[2])), style="wireframe", color="black", line_width=2)
        # Red ball = center of mass of the packing, black ball = center of the bounding box. Numbers = placement order.
        marker_radius = 0.02 * float(np.linalg.norm(bbox_maximum - bbox_minimum))
        plotter.add_mesh(pyvista.Sphere(radius=marker_radius, center=result["center_of_mass"]), color="red")
        plotter.add_mesh(pyvista.Sphere(radius=marker_radius, center=result["bbox_center"]), color="black")
        label_positions = []
        label_texts = []
        for placement_step, placement in enumerate(placements):
            part = selected_parts[placement["part_index"]]
            label_positions.append(placement["rotation"] @ part["center_of_mass_local"] + placement["translation"])
            label_texts.append(str(placement_step + 1))
        if len(result["placement_order"]) > 0:
            plotter.add_point_labels(np.array(label_positions), label_texts, font_size=14, point_size=1, shape_opacity=0.6, always_visible=True)
    if container_size is not None:
        plotter.add_mesh(pyvista.Box(bounds=(0, container_size[0], 0, container_size[1], 0, container_size[2])), style="wireframe", color="red", line_width=2)
    title = algorithm_name + "\ndensity " + format(result["density"], ".3f") + "  placed " + str(result["parts_placed"]) + "/" + str(result["parts_requested"]) + "\nCOM offset " + format(result["com_offset"], ".1f") + " mm"
    if not result["valid"]:
        title = title + "  INVALID (overlap)"
    plotter.add_text(title, font_size=10)
    plotter.show_axes()

if arguments.save is not None:
    plotter.screenshot(arguments.save)
    print("")
    print("Saved " + arguments.save)
else:
    plotter.show()
