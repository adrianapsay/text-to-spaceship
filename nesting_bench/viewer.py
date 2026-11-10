"""
Interactive viewer: pick a category, k, an algorithm and a seed in the left panel; the packing and its metrics appear on the right.
Choosing "compare all" packs the same parts with every benchmark algorithm and shows them side by side, sorted by density.

    python viewer.py

Left panel: click a category or an algorithm (one of each is active), drag the k and seed sliders (the packing recomputes when you release),
tick "container 100 mm cube" to switch from open mode (smallest bounding box) to container mode (fit in a 100 x 100 x 100 mm box).
Right view: left drag rotates, scroll zooms, shift + drag pans. Red ball = center of mass, black ball = bounding box center, numbers = placement order. Press s to save a screenshot, q to quit.
"""

import time
import numpy as np
import pyvista
import nesting_core
import algorithms


PART_COLORS = ["#4e79a7", "#f28e2b", "#e15759", "#76b7b2", "#59a14f", "#edc948", "#b07aa1", "#ff9da7", "#9c755f", "#bab0ac", "#1f77b4", "#d62728"]
PANEL_WIDTH = 270
WINDOW_HEIGHT = 880
WINDOW_WIDTH = 1500
TEXT_COLOR = "#222222"
ACTIVE_COLOR = "#2f6db5"
INACTIVE_COLOR = "#d9d9d9"

import argparse
parser = argparse.ArgumentParser(description="Interactive nesting viewer.")
parser.add_argument("--dataset", default="real_shapes", choices=nesting_core.list_datasets())
parser.add_argument("--algorithm", default="voxel_bottom_left", choices=list(algorithms.BENCHMARK_ALGORITHMS) + ["compare all"])
parser.add_argument("--k", type=int, default=8)
parser.add_argument("--seed", type=int, default=0)
parser.add_argument("--container", action="store_true", help="start in container mode (100 mm cube)")
arguments = parser.parse_args()

state = {"dataset": arguments.dataset, "algorithm": arguments.algorithm, "k": arguments.k, "seed": arguments.seed, "container": arguments.container, "busy": False}
settings = dict(algorithms.DEFAULT_SETTINGS)
check_pitch = settings["voxel_pitch"] / 2.0
loaded_parts = {}
dataset_names = nesting_core.list_datasets()
algorithm_names = list(algorithms.BENCHMARK_ALGORITHMS) + ["compare all"]

pyvista.global_theme.font.family = "arial"
plotter = pyvista.Plotter(shape=(1, 2), col_weights=[PANEL_WIDTH, WINDOW_WIDTH - PANEL_WIDTH], window_size=[WINDOW_WIDTH, WINDOW_HEIGHT], title="Nesting viewer", border=False)
panel = plotter.renderers[0]
view = plotter.renderers[1]
panel.SetInteractive(False)
panel.set_background("#f3f3f3")
view.set_background("white")


def label(text, x, y, size=11, bold=False, color=TEXT_COLOR):
    actor = plotter.add_text(text, position=(x, y), font_size=size, color=color, viewport=False)
    actor.GetTextProperty().SetBold(bold)
    return actor


def get_parts(dataset_name):
    if dataset_name not in loaded_parts:
        loaded_parts[dataset_name] = nesting_core.load_parts(dataset_name, check_pitch, 1.0)
    return loaded_parts[dataset_name]


def draw_packing(selected_parts, placements, result, offset, show_order):
    """Draw one packing shifted by offset (so several can share the view). Returns the bounding box size."""
    for placement in placements:
        part = selected_parts[placement["part_index"]]
        moved_mesh = nesting_core.world_mesh(part, placement)
        face_array = np.hstack([np.full((len(moved_mesh.faces), 1), 3), moved_mesh.faces]).ravel()
        plotter.add_mesh(pyvista.PolyData(np.asarray(moved_mesh.vertices) + offset, face_array), color=PART_COLORS[placement["part_index"] % len(PART_COLORS)], smooth_shading=True, split_sharp_edges=True, opacity=0.75)
    if len(placements) == 0:
        return np.zeros(3)
    all_vertices = np.vstack([nesting_core.world_vertices(selected_parts[placement["part_index"]], placement) for placement in placements])
    bbox_minimum = all_vertices.min(axis=0) + offset
    bbox_maximum = all_vertices.max(axis=0) + offset
    plotter.add_mesh(pyvista.Box(bounds=(bbox_minimum[0], bbox_maximum[0], bbox_minimum[1], bbox_maximum[1], bbox_minimum[2], bbox_maximum[2])), style="wireframe", color="#333333", line_width=1.5)
    marker_radius = 0.018 * float(np.linalg.norm(bbox_maximum - bbox_minimum))
    plotter.add_mesh(pyvista.Sphere(radius=marker_radius, center=result["center_of_mass"] + offset), color="red")
    plotter.add_mesh(pyvista.Sphere(radius=marker_radius, center=result["bbox_center"] + offset), color="black")
    if show_order and len(result["placement_order"]) > 0:
        label_positions = []
        label_texts = []
        for placement_step, placement in enumerate(placements):
            part = selected_parts[placement["part_index"]]
            label_positions.append(placement["rotation"] @ part["center_of_mass_local"] + placement["translation"] + offset)
            label_texts.append(str(placement_step + 1))
        plotter.add_point_labels(np.array(label_positions), label_texts, font_size=13, point_size=1, shape_opacity=0.5, always_visible=True)
    if state["container"]:
        plotter.add_mesh(pyvista.Box(bounds=(offset[0], offset[0] + 100, offset[1], offset[1] + 100, offset[2], offset[2] + 100)), style="wireframe", color="red", line_width=1.5)
    return bbox_maximum - bbox_minimum


def stats_text(name, result, run_seconds):
    lines = []
    lines.append(name + "   " + format(run_seconds, ".2f") + " s")
    lines.append("placed         " + str(result["parts_placed"]) + " / " + str(result["parts_requested"]))
    lines.append("bounding box   " + format(result["bbox_x"], ".0f") + " x " + format(result["bbox_y"], ".0f") + " x " + format(result["bbox_z"], ".0f") + " mm")
    lines.append("density        " + format(result["density"], ".3f") + "   (parts volume / box volume)")
    lines.append("aspect ratio   " + format(result["aspect_ratio"], ".2f"))
    lines.append("COM offset     " + format(result["com_offset"], ".1f") + " mm   (" + format(100 * result["com_offset_normalized"], ".1f") + "% of diagonal)")
    lines.append("min gap        " + format(result["minimum_gap"], ".2f") + " mm   (t = " + str(settings["clearance"]) + " mm " + ("met" if result["clearance_ok"] else "NOT met") + ")")
    lines.append("contacts       " + str(result["contacts"]) + " pairs within " + format(result["contact_band"], ".1f") + " mm   (" + format(result["contacts_per_part"], ".1f") + " per part, " + str(result["isolated_parts"]) + " isolated)")
    inertia_tensor = result["inertia_tensor"]
    lines.append("inertia        Ixx " + format(inertia_tensor[0, 0], ".3g") + "   Iyy " + format(inertia_tensor[1, 1], ".3g") + "   Izz " + format(inertia_tensor[2, 2], ".3g") + "  g mm2")
    if state["container"]:
        lines.append("container fill " + format(result["container_fill"], ".3f"))
    lines.append("valid          " + ("yes" if result["valid"] else "NO (overlap " + format(100 * result["overlap_fraction"], ".1f") + "%)"))
    if len(result["placement_order"]) > 0:
        lines.append("order          " + " > ".join(result["placement_order"]))
    return "\n".join(lines)


def recompute():
    if state["busy"]:
        return
    state["busy"] = True
    plotter.subplot(0, 1)
    view.clear_actors()
    plotter.add_text("computing ...", position="upper_left", font_size=12, color=TEXT_COLOR, name="stats")
    plotter.render()
    all_parts = get_parts(state["dataset"])
    selection_generator = np.random.default_rng(state["seed"])
    selected_indices = selection_generator.choice(len(all_parts), size=state["k"], replace=state["k"] > len(all_parts))
    selected_parts = [all_parts[index] for index in selected_indices]
    container_size = np.array([100.0, 100.0, 100.0]) if state["container"] else None
    view.clear_actors()
    if state["algorithm"] == "compare all":
        outcomes = []
        for name in algorithms.BENCHMARK_ALGORITHMS:
            placements, result, run_seconds = algorithms.run_algorithm(name, selected_parts, container_size, state["seed"], settings, check_pitch)
            outcomes.append((name, placements, result, run_seconds))
        outcomes.sort(key=lambda outcome: -outcome[2]["density"])
        spacing = max(max(outcome[2]["bbox_x"], outcome[2]["bbox_y"]) for outcome in outcomes) * 1.4
        columns = 5
        table = ["algorithm             density    AR   COM%   gap    s"]
        for number, (name, placements, result, run_seconds) in enumerate(outcomes):
            offset = np.array([(number % columns) * spacing, -(number // columns) * spacing, 0.0])
            draw_packing(selected_parts, placements, result, offset, False)
            caption = name + "\n" + format(result["density"], ".3f")
            plotter.add_point_labels([offset + np.array([0.0, -0.22 * spacing, 0.0])], [caption], font_size=11, point_size=1, shape=None, always_visible=True, text_color=TEXT_COLOR)
            table.append(name.ljust(22) + format(result["density"], ".3f").rjust(7) + format(result["aspect_ratio"], ".2f").rjust(6) + format(100 * result["com_offset_normalized"], ".1f").rjust(7) + format(result["minimum_gap"], ".2f").rjust(6) + format(run_seconds, ".2f").rjust(6) + ("" if result["valid"] else "   INVALID"))
        plotter.add_text("\n".join(table), position="upper_left", font_size=10, color=TEXT_COLOR, font="courier", name="stats")
    else:
        placements, result, run_seconds = algorithms.run_algorithm(state["algorithm"], selected_parts, container_size, state["seed"], settings, check_pitch)
        draw_packing(selected_parts, placements, result, np.zeros(3), True)
        plotter.add_text(stats_text(state["algorithm"], result, run_seconds), position="upper_left", font_size=10, color=TEXT_COLOR, font="courier", name="stats")
    plotter.add_text("parts: " + ", ".join(part["name"] for part in selected_parts), position="lower_left", font_size=8, color="#666666", name="parts")
    plotter.view_isometric()
    plotter.reset_camera()
    plotter.render()
    state["busy"] = False


# ---------- left panel ----------
plotter.subplot(0, 0)
label("Nesting viewer", 16, WINDOW_HEIGHT - 40, size=15, bold=True)
row_height = 24
dataset_buttons = {}
algorithm_buttons = {}


def make_radio(names, buttons, key, top_y):
    for number, name in enumerate(names):
        y = top_y - number * row_height
        def callback(value, name=name):
            if state["busy"]:
                return
            state[key] = name
            for other_name, other_button in buttons.items():
                other_button.GetRepresentation().SetState(1 if other_name == name else 0)
            recompute()
        button = plotter.add_checkbox_button_widget(callback, value=(name == state[key]), position=(18, y), size=16, color_on=ACTIVE_COLOR, color_off=INACTIVE_COLOR, border_size=1)
        buttons[name] = button
        label(name.replace("_", " "), 42, y + 1, size=10)


y_cursor = WINDOW_HEIGHT - 80
label("CATEGORY", 16, y_cursor, size=9, bold=True, color="#777777")
y_cursor = y_cursor - row_height
make_radio(dataset_names, dataset_buttons, "dataset", y_cursor)
y_cursor = y_cursor - row_height * len(dataset_names) - 16
label("ALGORITHM", 16, y_cursor, size=9, bold=True, color="#777777")
y_cursor = y_cursor - row_height
make_radio(algorithm_names, algorithm_buttons, "algorithm", y_cursor)
y_cursor = y_cursor - row_height * len(algorithm_names) - 10


def set_k(value):
    new_k = int(round(value))
    if new_k != state["k"]:
        state["k"] = new_k
        recompute()


def set_seed(value):
    new_seed = int(round(value))
    if new_seed != state["seed"]:
        state["seed"] = new_seed
        recompute()


def set_container(value):
    state["container"] = bool(value)
    recompute()


slider_style = {"color": ACTIVE_COLOR, "slider_width": 0.03, "tube_width": 0.006, "title_height": 0.02, "fmt": "%.0f", "style": "modern", "interaction_event": "end"}
plotter.add_slider_widget(set_k, [1, 30], value=state["k"], title="k  parts", pointa=(0.1, 0.19), pointb=(0.9, 0.19), **slider_style)
plotter.add_slider_widget(set_seed, [0, 99], value=state["seed"], title="seed", pointa=(0.1, 0.10), pointb=(0.9, 0.10), **slider_style)
plotter.add_checkbox_button_widget(set_container, value=state["container"], position=(18, 22), size=16, color_on=ACTIVE_COLOR, color_off=INACTIVE_COLOR, border_size=1)
label("container 100 mm", 42, 23, size=10)
label("s: screenshot   q: quit", 16, 2, size=8, color="#999999")


def save_screenshot():
    file_name = "viewer_" + time.strftime("%Y%m%d_%H%M%S") + ".png"
    plotter.screenshot(file_name)
    print("Saved " + file_name)


plotter.add_key_event("s", save_screenshot)
plotter.subplot(0, 1)
plotter.show_axes()
recompute()
plotter.show()
