"""
One short MP4 per algorithm showing it at work in 3D: ordered packers show each part flying in from above to its spot, in placement order;
the two force-based packers show the boxes squeezing together and pushing apart. Writes videos/<algorithm>.mp4 (needs pyvista and ffmpeg).

    python make_videos.py --dataset simple_concave --k 8 --seed 3
"""

import os
import argparse
import subprocess
import numpy as np
import pyvista
import nesting_core
import algorithms

parser = argparse.ArgumentParser()
parser.add_argument("--dataset", default="simple_concave")
parser.add_argument("--k", type=int, default=8)
parser.add_argument("--seed", type=int, default=3)
parser.add_argument("--algorithms", nargs="+", default=["all"])
parser.add_argument("--fps", type=int, default=24)
arguments = parser.parse_args()

pyvista.OFF_SCREEN = True
PART_COLORS = ["#4e79a7", "#f28e2b", "#e15759", "#76b7b2", "#59a14f", "#edc948", "#b07aa1", "#ff9da7", "#9c755f", "#bab0ac", "#1f77b4", "#d62728"]
output_folder = "videos"
os.makedirs(output_folder, exist_ok=True)
settings = dict(algorithms.DEFAULT_SETTINGS)
check_pitch = settings["voxel_pitch"] / 2.0
all_parts = nesting_core.load_parts(arguments.dataset, check_pitch, 1.0)
selection_generator = np.random.default_rng(arguments.seed)
selected_indices = selection_generator.choice(len(all_parts), size=arguments.k, replace=arguments.k > len(all_parts))
selected_parts = [all_parts[index] for index in selected_indices]
algorithm_names = algorithms.BENCHMARK_ALGORITHMS if arguments.algorithms == ["all"] else arguments.algorithms


def polydata(part, placement, extra_offset):
    moved_mesh = nesting_core.world_mesh(part, placement)
    face_array = np.hstack([np.full((len(moved_mesh.faces), 1), 3), moved_mesh.faces]).ravel()
    return pyvista.PolyData(np.asarray(moved_mesh.vertices) + extra_offset, face_array)


def render_frames(name, frames, caption):
    """frames: list of (placements, extra_offsets list, subtitle). Writes the mp4."""
    all_points = np.vstack([nesting_core.world_vertices(selected_parts[placement["part_index"]], placement) for placement in frames[-1][0]])
    center = (all_points.min(axis=0) + all_points.max(axis=0)) / 2.0
    radius = float(np.linalg.norm(all_points.max(axis=0) - all_points.min(axis=0)))
    plotter = pyvista.Plotter(off_screen=True, window_size=[1280, 720])
    plotter.set_background("white")
    frame_folder = os.path.join(output_folder, "frames_" + name)
    os.makedirs(frame_folder, exist_ok=True)
    for frame_number, (placements, offsets, subtitle) in enumerate(frames):
        plotter.clear_actors()
        for placement, offset in zip(placements, offsets):
            part = selected_parts[placement["part_index"]]
            plotter.add_mesh(polydata(part, placement, offset), color=PART_COLORS[placement["part_index"] % len(PART_COLORS)], smooth_shading=True, split_sharp_edges=True, opacity=0.9)
        settled = [(placement, offset) for placement, offset in zip(placements, offsets) if np.all(offset == 0)]
        if len(settled) > 0:
            points = np.vstack([nesting_core.world_vertices(selected_parts[placement["part_index"]], placement) + offset for placement, offset in settled])
            low = points.min(axis=0)
            high = points.max(axis=0)
            plotter.add_mesh(pyvista.Box(bounds=(low[0], high[0], low[1], high[1], low[2], high[2])), style="wireframe", color="#333333", line_width=1.5)
        plotter.add_text(name.replace("_", " "), position="upper_left", font_size=16, color="#222222")
        plotter.add_text(subtitle, position="lower_left", font_size=11, color="#555555")
        plotter.add_text(caption, position="upper_right", font_size=10, color="#777777")
        plotter.camera_position = [center + np.array([1.0, -1.4, 0.8]) * radius, center, [0, 0, 1]]
        plotter.screenshot(os.path.join(frame_folder, "frame_" + str(frame_number).zfill(4) + ".png"))
    plotter.close()
    video_path = os.path.join(output_folder, name + ".mp4")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(arguments.fps), "-i", os.path.join(frame_folder, "frame_%04d.png"), "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-crf", "20", video_path], check=True)
    for file_name in os.listdir(frame_folder):
        os.remove(os.path.join(frame_folder, file_name))
    os.rmdir(frame_folder)
    print("wrote " + video_path + " (" + str(len(frames)) + " frames)")


for name in algorithm_names:
    rng = np.random.default_rng(arguments.seed)
    trace = []
    run_settings = dict(settings)
    if name in ("force_based", "force_based_v2"):
        run_settings["trace"] = trace
    for part in selected_parts:
        part["occupancy_cache"] = {}
    placements = algorithms.ALGORITHMS[name](selected_parts, None, rng, run_settings)
    result = nesting_core.evaluate_packing(selected_parts, placements, None, check_pitch, settings["clearance"])
    caption = arguments.dataset.replace("_", " ") + ", k = " + str(arguments.k) + "   density " + format(result["density"], ".3f")
    frames = []
    if name in ("force_based", "force_based_v2"):
        step = max(1, len(trace) // 240)
        repeat = 3 if len(trace) < 120 else 1
        for trace_number in range(0, len(trace), step):
            for repeat_number in range(repeat):
                frames.append((trace[trace_number], [np.zeros(3)] * len(trace[trace_number]), "squeeze toward the center, push overlapping boxes apart; state " + str(trace_number + 1) + " of " + str(len(trace))))
        for hold in range(arguments.fps):
            frames.append((placements, [np.zeros(3)] * len(placements), "final: overlapping boxes dropped, " + str(len(placements)) + " of " + str(arguments.k) + " placed"))
    else:
        drop_frames = 14
        drop_height = 1.2 * float(np.max([nesting_core.world_vertices(selected_parts[placement["part_index"]], placement).max(axis=0)[2] for placement in placements]) if len(placements) > 0 else 50.0)
        for step_number, placement in enumerate(placements):
            placed_so_far = placements[:step_number]
            for drop_frame in range(drop_frames):
                fraction = (drop_frame + 1) / drop_frames
                eased = 1.0 - (1.0 - fraction) ** 3
                offsets = [np.zeros(3)] * len(placed_so_far) + [np.array([0.0, 0.0, drop_height * (1.0 - eased)])]
                frames.append((placed_so_far + [placement], offsets, "placing part " + str(step_number + 1) + " of " + str(len(placements)) + ": " + selected_parts[placement["part_index"]]["name"]))
            for hold in range(4):
                frames.append((placements[:step_number + 1], [np.zeros(3)] * (step_number + 1), "placing part " + str(step_number + 1) + " of " + str(len(placements)) + ": " + selected_parts[placement["part_index"]]["name"]))
        for hold in range(arguments.fps):
            frames.append((placements, [np.zeros(3)] * len(placements), "done: " + str(len(placements)) + " parts, bounding box " + format(result["bbox_x"], ".0f") + " x " + format(result["bbox_y"], ".0f") + " x " + format(result["bbox_z"], ".0f") + " mm"))
    render_frames(name, frames, caption)
