"""
Runs every algorithm on verification instances with a known optimum and scores it against the ceiling.

    python run_verification.py --test scrabble   --repeats 2 --workers 2
    python run_verification.py --test literature --repeats 5 --workers 2

Each instance folder holds the pieces (STL) and instance.json with ceiling_density (the proven / constructed optimum of parts volume / bounding box volume).
Two modes. open: minimize the bounding box, ratio = density / ceiling (ratio > 1 is possible where the ceiling is only a reference, e.g. pieces of a sphere,
or a row of cylinders beating the square arrangement). container: the box is the instance's own (proven minimal) box; ratio = fraction of parts that fit,
solved = everything fits with no overlap. The container test is the one the proofs actually support.
Per (instance, algorithm, repeat): the packing is run with the benchmark's settings except clearance t = 0 (a perfect fit is impossible with t > 0),
validity is checked EXACTLY with manifold3d mesh booleans (pairwise intersection volume < 0.1% of the smaller part), and
  ratio  = achieved density / ceiling density        (1.0 = the known optimum)
  solved = valid and ratio >= 0.98
Outputs in results/: verification_<test>_trials.csv, verification_<test>_solutions.jsonl (every packing), verification_<test>_summary.csv (mean ratio and solved rate per group and algorithm with 99% CIs), verification_<test>_ranking.csv.
"""

import os
import sys
import csv
import json
import time
import argparse
import multiprocessing
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import nesting_core
import algorithms

parser = argparse.ArgumentParser()
parser.add_argument("--test", choices=["scrabble", "literature"], required=True)
parser.add_argument("--algorithms", nargs="+", default=["all"])
parser.add_argument("--repeats", type=int, default=2, help="runs per (instance, algorithm); repeat r uses seed r")
parser.add_argument("--workers", type=int, default=1)
parser.add_argument("--clearance", type=float, default=0.0)
parser.add_argument("--voxel_pitch", type=float, default=2.0)
parser.add_argument("--search_seconds", type=float, default=5.0)
parser.add_argument("--instances", nargs="*", default=None, help="subset of instance folder names")
parser.add_argument("--resume", action="store_true")
parser.add_argument("--tag", default="", help="suffix for the output file names (separate runs)")
parser.add_argument("--mode", choices=["open", "container"], default="open", help="open: minimize the box, score = density / ceiling; container: the box is the instance's own box (the proven minimal one), score = does everything fit")
parser.add_argument("--container_tolerance", type=float, default=0.002, help="relative slack added to the container box (mesh facets)")
arguments = parser.parse_args()

datasets_folder = os.path.join(HERE, "..", "datasets_" + arguments.test)
results_folder = os.path.join(HERE, "..", "results")
os.makedirs(results_folder, exist_ok=True)
prefix = os.path.join(results_folder, "verification_" + arguments.test + "_" + arguments.mode + ("" if arguments.voxel_pitch == 2.0 else "_pitch" + format(arguments.voxel_pitch, "g")) + ("" if arguments.tag == "" else "_" + arguments.tag))
settings = dict(algorithms.DEFAULT_SETTINGS)
settings["clearance"] = arguments.clearance
settings["voxel_pitch"] = arguments.voxel_pitch
settings["search_seconds"] = arguments.search_seconds
check_pitch = arguments.voxel_pitch / 2.0
algorithm_names = algorithms.BENCHMARK_ALGORITHMS if arguments.algorithms == ["all"] else arguments.algorithms
instance_names = sorted(name for name in os.listdir(datasets_folder) if os.path.exists(os.path.join(datasets_folder, name, "instance.json")))
if arguments.instances is not None:
    instance_names = [name for name in instance_names if name in arguments.instances]

loaded = {}


def exact_overlap(selected_parts, placements):
    """Largest pairwise intersection volume as a fraction of the smaller part's volume (manifold3d booleans), only for pairs whose boxes intersect."""
    import manifold3d
    manifolds = []
    bounds = []
    for placement in placements:
        mesh = nesting_core.world_mesh(selected_parts[placement["part_index"]], placement)
        manifolds.append(manifold3d.Manifold(manifold3d.Mesh(vert_properties=np.asarray(mesh.vertices, dtype=np.float32), tri_verts=np.asarray(mesh.faces, dtype=np.uint32))))
        bounds.append((np.asarray(mesh.vertices).min(axis=0), np.asarray(mesh.vertices).max(axis=0)))
    worst = 0.0
    for first in range(len(manifolds)):
        for second in range(first + 1, len(manifolds)):
            if np.any(bounds[first][0] > bounds[second][1]) or np.any(bounds[second][0] > bounds[first][1]):
                continue
            volume = float((manifolds[first] ^ manifolds[second]).volume())
            smaller = min(selected_parts[placements[first]["part_index"]]["volume"], selected_parts[placements[second]["part_index"]]["volume"])
            worst = max(worst, volume / smaller)
    return worst


def run_job(job):
    instance_name, algorithm_name, repeat = job
    nesting_core.DATASETS_FOLDER = os.path.abspath(datasets_folder)
    if len(loaded) > 8:
        loaded.clear()
    if instance_name not in loaded:
        loaded[instance_name] = nesting_core.load_parts(instance_name, check_pitch, 1.0)
    selected_parts = loaded[instance_name]
    for part in selected_parts:
        part["occupancy_cache"] = {}
    instance = json.load(open(os.path.join(datasets_folder, instance_name, "instance.json")))
    container_size = None if arguments.mode == "open" else np.array(instance["solid_box"]) * (1.0 + arguments.container_tolerance)
    placements, result, run_seconds = algorithms.run_algorithm(algorithm_name, selected_parts, container_size, repeat, settings, check_pitch)
    overlap = exact_overlap(selected_parts, placements) if len(placements) > 1 else 0.0
    all_placed = len(placements) == len(selected_parts)
    inside = True
    if container_size is not None and len(placements) > 0:
        all_vertices = np.vstack([nesting_core.world_vertices(selected_parts[placement["part_index"]], placement) for placement in placements])
        inside = bool(np.all(all_vertices >= -1e-6) and np.all(all_vertices <= container_size + 1e-6))
    valid = bool(overlap < 1e-3 and inside)
    if arguments.mode == "open":
        ratio = float(result["density"] / instance["ceiling_density"]) if (valid and all_placed) else 0.0
    else:
        ratio = float(len(placements) / len(selected_parts)) if valid else 0.0
    row = {"instance": instance_name, "algorithm": algorithm_name, "repeat": repeat, "k": len(selected_parts), "placed": len(placements), "valid": valid, "exact_overlap_fraction": overlap, "density": result["density"], "ceiling_density": instance["ceiling_density"], "ratio": ratio, "solved": bool(valid and all_placed and ratio >= 0.98), "mode": arguments.mode, "bbox_volume": result["bbox_volume"], "ceiling_bbox_volume": instance["ceiling_bbox_volume"], "bbox_x": result["bbox_x"], "bbox_y": result["bbox_y"], "bbox_z": result["bbox_z"], "aspect_ratio": result["aspect_ratio"], "com_offset_normalized": result["com_offset_normalized"], "minimum_gap": result["minimum_gap"], "contacts": result["contacts"], "isolated_parts": result["isolated_parts"], "seconds": run_seconds, "placement_order": ">".join(result["placement_order"])}
    for key in ("solid", "style", "seed", "name"):
        row[key] = instance.get(key, "")
    solution = {"test": arguments.test, "mode": arguments.mode, "container": None if container_size is None else container_size.tolist(), "instance": instance_name, "algorithm": algorithm_name, "repeat": repeat, "ratio": ratio, "valid": valid, "parts": [part["name"] for part in selected_parts], "placements": [{"part": selected_parts[placement["part_index"]]["name"], "rotation": np.asarray(placement["rotation"]).round(6).tolist(), "translation": np.asarray(placement["translation"]).round(4).tolist()} for placement in placements]}
    return row, solution


def confidence_interval_99(values):
    values = np.asarray(values, dtype=float)
    if len(values) < 2:
        return float(values.mean()), float(values.mean())
    from scipy import stats
    half = stats.t.ppf(0.995, len(values) - 1) * values.std(ddof=1) / np.sqrt(len(values))
    return float(values.mean() - half), float(values.mean() + half)


def group_of(row):
    if arguments.test == "scrabble":
        return row["solid"] + "_" + row["style"] + "_k" + str(row["k"])
    return row["instance"]


if __name__ == "__main__":
    trials_path = prefix + "_trials.csv"
    solutions_path = prefix + "_solutions.jsonl"
    done = set()
    rows = []
    if arguments.resume and os.path.exists(trials_path):
        for old in csv.DictReader(open(trials_path)):
            done.add((old["instance"], old["algorithm"], int(old["repeat"])))
            rows.append(old)
        print("resuming: " + str(len(done)) + " jobs already done", flush=True)
    jobs = [(instance_name, algorithm_name, repeat) for instance_name in instance_names for algorithm_name in algorithm_names for repeat in range(arguments.repeats) if (instance_name, algorithm_name, repeat) not in done]
    print(str(len(instance_names)) + " instances, " + str(len(algorithm_names)) + " algorithms, " + str(arguments.repeats) + " repeats: " + str(len(jobs)) + " jobs to run", flush=True)
    columns = ["instance", "solid", "style", "seed", "name", "algorithm", "repeat", "mode", "k", "placed", "valid", "exact_overlap_fraction", "density", "ceiling_density", "ratio", "solved", "bbox_volume", "ceiling_bbox_volume", "bbox_x", "bbox_y", "bbox_z", "aspect_ratio", "com_offset_normalized", "minimum_gap", "contacts", "isolated_parts", "seconds", "placement_order"]
    write_header = not (arguments.resume and os.path.exists(trials_path))
    trials_file = open(trials_path, "a" if not write_header else "w", newline="")
    writer = csv.DictWriter(trials_file, fieldnames=columns)
    if write_header:
        writer.writeheader()
    solutions_file = open(solutions_path, "a" if not write_header else "w")
    start = time.perf_counter()
    pool = multiprocessing.Pool(arguments.workers, maxtasksperchild=40) if arguments.workers > 1 else None
    iterator = pool.imap_unordered(run_job, jobs) if pool is not None else map(run_job, jobs)
    for number, (row, solution) in enumerate(iterator):
        writer.writerow(row)
        trials_file.flush()
        solutions_file.write(json.dumps(solution) + "\n")
        solutions_file.flush()
        rows.append({key: str(value) for key, value in row.items()})
        if (number + 1) % 50 == 0:
            elapsed = time.perf_counter() - start
            print(str(number + 1) + "/" + str(len(jobs)) + "   about " + format(elapsed / (number + 1) * (len(jobs) - number - 1) / 60.0, ".1f") + " min left", flush=True)
    if pool is not None:
        pool.close()
        pool.join()
    trials_file.close()
    solutions_file.close()

    # summary per group and algorithm, and overall ranking
    groups = {}
    for row in rows:
        groups.setdefault((group_of(row), row["algorithm"]), []).append(row)
    with open(prefix + "_summary.csv", "w", newline="") as summary_file:
        summary_writer = csv.writer(summary_file)
        summary_writer.writerow(["group", "algorithm", "runs", "ratio_mean", "ratio_ci99_low", "ratio_ci99_high", "ratio_best", "solved_rate", "valid_rate", "aspect_ratio_mean", "seconds_mean"])
        for (group, algorithm_name), members in sorted(groups.items()):
            ratios = [float(member["ratio"]) for member in members]
            low, high = confidence_interval_99(ratios)
            summary_writer.writerow([group, algorithm_name, len(members), format(np.mean(ratios), ".4f"), format(low, ".4f"), format(high, ".4f"), format(max(ratios), ".4f"), format(np.mean([member["solved"] == "True" for member in members]), ".3f"), format(np.mean([member["valid"] == "True" for member in members]), ".3f"), format(np.mean([float(member["aspect_ratio"]) for member in members]), ".3f"), format(np.mean([float(member["seconds"]) for member in members]), ".3f")])
    overall = {}
    for row in rows:
        overall.setdefault(row["algorithm"], []).append(row)
    ranking = []
    for algorithm_name, members in overall.items():
        ratios = [float(member["ratio"]) for member in members]
        low, high = confidence_interval_99(ratios)
        ranking.append((np.mean(ratios), algorithm_name, low, high, np.mean([member["solved"] == "True" for member in members]), np.mean([member["valid"] == "True" for member in members]), len(members)))
    ranking.sort(reverse=True)
    with open(prefix + "_ranking.csv", "w", newline="") as ranking_file:
        ranking_writer = csv.writer(ranking_file)
        ranking_writer.writerow(["rank", "algorithm", "runs", "ratio_mean", "ratio_ci99_low", "ratio_ci99_high", "solved_rate", "valid_rate"])
        print("\nRanking (" + arguments.test + "): mean ratio to the known optimum, 99% CI, solved rate (ratio >= 0.98)")
        for rank, (mean_ratio, algorithm_name, low, high, solved_rate, valid_rate, count) in enumerate(ranking):
            ranking_writer.writerow([rank + 1, algorithm_name, count, format(mean_ratio, ".4f"), format(low, ".4f"), format(high, ".4f"), format(solved_rate, ".3f"), format(valid_rate, ".3f")])
            print(str(rank + 1).rjust(3) + "  " + algorithm_name.ljust(22) + format(mean_ratio, ".3f") + "  [" + format(low, ".3f") + ", " + format(high, ".3f") + "]   solved " + format(solved_rate, ".2f") + "   valid " + format(valid_rate, ".2f"))
    print("Total time " + format((time.perf_counter() - start) / 60.0, ".1f") + " min")
