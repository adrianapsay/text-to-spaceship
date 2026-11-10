"""
Benchmark: for each algorithm and each dataset (object category), run n trials. Each trial picks k random parts, packs them (randomized algorithms get several tries and keep the best), and records every metric. Results are averaged per algorithm and category (Monte Carlo).
Every algorithm sees the exact same random part sets (same seed), so the comparison is fair.

Metrics per trial:
    bounding box x, y, z; % of volume utilized (density = parts volume / bounding box volume); aspect ratio (longest / shortest box side)
    center of mass (COM), center of volume (COV = bounding box center), distance COM to COV (mm and % of box diagonal)
    inertia about the COM along the box axes (Ixx, Iyy, Izz, Ixy, Ixz, Iyz) and principal moments (I1 <= I2 <= I3), g*mm^2
    placement order (empty for force_based, which moves all parts at once)
    minimum gap between parts (approximate) and whether it meets the clearance t
    valid (no overlap), parts placed, run time

Examples:
    python benchmark.py
    python benchmark.py --algorithms shelf_packing voxel_bottom_left --datasets real_shapes --k 10 --trials 500
    python benchmark.py --mode container --container 100 100 100 --k 30
    python benchmark.py --workers 8                      (8 processes; trials are independent, so this is about 8x faster on 8 cores)

Output: summary table on screen, results/trials_<time>.csv (one row per trial), results/summary_<time>.csv (one row per algorithm x category), results/summary_<time>.png (bar charts).
"""

import os
import csv
import json
import time
import argparse
import numpy as np
import nesting_core
import algorithms


parser = argparse.ArgumentParser(description="Compare packing algorithms on the datasets.")
parser.add_argument("--algorithms", nargs="+", default=["all"], help="algorithm names, or all (the ten benchmark algorithms)")
parser.add_argument("--datasets", nargs="+", default=["all"], help="dataset names, or all")
parser.add_argument("--k", type=int, default=10, help="parts per trial")
parser.add_argument("--trials", type=int, default=100, help="n, trials per algorithm per category")
parser.add_argument("--mode", default="open", choices=["open", "container"])
parser.add_argument("--container", type=float, nargs=3, default=[100.0, 100.0, 100.0])
parser.add_argument("--seed", type=int, default=0)
parser.add_argument("--clearance", type=float, default=algorithms.DEFAULT_SETTINGS["clearance"], help="minimum gap t between parts, mm")
parser.add_argument("--restarts", type=int, default=algorithms.DEFAULT_SETTINGS["restarts"], help="tries per trial for randomized algorithms (best kept)")
parser.add_argument("--voxel_pitch", type=float, default=algorithms.DEFAULT_SETTINGS["voxel_pitch"])
parser.add_argument("--voxel_orientations", default=algorithms.DEFAULT_SETTINGS["voxel_orientations"], choices=["faces", "all"])
parser.add_argument("--density", type=float, default=1.0, help="density of every part in g/cm^3 (override single parts with datasets/<dataset>/densities.csv)")
parser.add_argument("--no_plot", action="store_true", help="skip the bar chart")
parser.add_argument("--workers", type=int, default=1, help="parallel processes (trials are independent; use the number of CPU cores)")
parser.add_argument("--datasets_folder", default=None, help="folder holding the category folders (default: datasets/; use datasets_large/ for the 60-part categories)")
parser.add_argument("--save_solutions", action="store_true", help="also write every trial's packing (part, rotation, position) to solutions_<timestamp>.jsonl")
parser.add_argument("--name", default=None, help="name for the output files instead of the timestamp")
parser.add_argument("--resume", action="store_true", help="with --name: keep the (dataset, algorithm) pairs already complete in the existing trials file and only run the rest")

def main_body():
    global arguments
    algorithm_names = algorithms.BENCHMARK_ALGORITHMS if arguments.algorithms == ["all"] else arguments.algorithms
    dataset_names = nesting_core.list_datasets() if arguments.datasets == ["all"] else arguments.datasets
    settings = dict(algorithms.DEFAULT_SETTINGS)
    settings["voxel_pitch"] = arguments.voxel_pitch
    settings["voxel_orientations"] = arguments.voxel_orientations
    settings["clearance"] = arguments.clearance
    settings["restarts"] = arguments.restarts
    check_pitch = arguments.voxel_pitch / 2.0
    container_size = None if arguments.mode == "open" else np.array(arguments.container)

    results_folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
    os.makedirs(results_folder, exist_ok=True)
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    if arguments.name is not None:
        timestamp = arguments.name
    trials_path = os.path.join(results_folder, "trials_" + timestamp + ".csv")
    summary_path = os.path.join(results_folder, "summary_" + timestamp + ".csv")
    plot_path = os.path.join(results_folder, "summary_" + timestamp + ".png")
    solutions_path = os.path.join(results_folder, "solutions_" + timestamp + ".jsonl")
    if arguments.datasets_folder is not None:
        nesting_core.DATASETS_FOLDER = os.path.abspath(arguments.datasets_folder)
        os.environ["NESTING_DATASETS_FOLDER"] = nesting_core.DATASETS_FOLDER

    # Numeric metrics averaged in the summary, in this order.
    metric_names = ["density", "bbox_x", "bbox_y", "bbox_z", "aspect_ratio", "com_offset", "com_offset_normalized", "Ixx", "Iyy", "Izz", "I1", "I2", "I3", "minimum_gap", "contacts", "contacts_per_part", "isolated_parts", "placed_fraction", "container_fill", "total_mass", "seconds"]
    trial_columns = ["dataset", "algorithm", "trial", "parts", "placement_order", "valid", "clearance_ok"] + metric_names + ["com_x", "com_y", "com_z", "cov_x", "cov_y", "cov_z", "Ixy", "Ixz", "Iyz"]
    summary_columns = ["dataset", "algorithm", "k", "mode", "trials", "score", "score_ci99_low", "score_ci99_high", "valid_rate", "clearance_ok_rate"] + [name + "_mean" for name in metric_names] + [name + "_std" for name in metric_names] + [name + "_ci99_low" for name in metric_names] + [name + "_ci99_high" for name in metric_names]
    summary_rows = []
    total_runs = len(dataset_names) * len(algorithm_names) * arguments.trials
    finished_runs = 0
    benchmark_start = time.perf_counter()

    # Resume: rows of pairs that already have all their trials are kept and reused; partial pairs are rerun.
    kept_rows = {}
    if arguments.resume and os.path.exists(trials_path):
        with open(trials_path) as old_file:
            for old_row in csv.DictReader(old_file):
                kept_rows.setdefault((old_row["dataset"], old_row["algorithm"]), []).append(old_row)
        kept_rows = {key: value for key, value in kept_rows.items() if len(value) == arguments.trials}
        kept_solutions = {}
        if arguments.save_solutions and os.path.exists(solutions_path):
            for line in open(solutions_path):
                record = json.loads(line)
                if (record["dataset"], record["algorithm"]) in kept_rows:
                    kept_solutions.setdefault((record["dataset"], record["algorithm"]), []).append(line)
        print("Resuming: " + str(len(kept_rows)) + " (dataset, algorithm) pairs already complete", flush=True)
    else:
        kept_solutions = {}
    solutions_file = open(solutions_path, "w") if arguments.save_solutions else None
    with open(trials_path, "w", newline="") as trials_file:
        trials_writer = csv.writer(trials_file)
        trials_writer.writerow(trial_columns)
        import multiprocessing
        pool = multiprocessing.Pool(arguments.workers) if arguments.workers > 1 else None
        for dataset_name in dataset_names:
            print("Loading " + dataset_name + " ...", flush=True)
            for algorithm_name in algorithm_names:
                metric_values = {name: [] for name in metric_names}
                valid_flags = []
                clearance_flags = []
                if (dataset_name, algorithm_name) in kept_rows:
                    for old_row in kept_rows[(dataset_name, algorithm_name)]:
                        for name in metric_names:
                            metric_values[name].append(float(old_row[name]) if old_row[name] != "" else 0.0)
                        valid_flags.append(old_row["valid"] == "True")
                        clearance_flags.append(old_row["clearance_ok"] == "True")
                        trials_writer.writerow([old_row[column] for column in trial_columns])
                    for line in kept_solutions.get((dataset_name, algorithm_name), []):
                        solutions_file.write(line)
                    trials_file.flush()
                    finished_runs = finished_runs + arguments.trials
                    print("  " + algorithm_name.ljust(20) + " kept from the previous run", flush=True)
                    jobs = []
                else:
                    jobs = [(dataset_name, algorithm_name, trial, arguments.k, arguments.seed, settings, check_pitch, container_size, arguments.density) for trial in range(arguments.trials)]
                if pool is None:
                    row_iterator = map(run_one_trial, jobs)
                else:
                    row_iterator = pool.imap(run_one_trial, jobs)
                for trial, row_values in enumerate(row_iterator):
                    for name in metric_names:
                        metric_values[name].append(row_values[name])
                    valid_flags.append(row_values["valid"])
                    clearance_flags.append(row_values["clearance_ok"])
                    center_of_mass = row_values["center_of_mass"]
                    bbox_center = row_values["bbox_center"]
                    trials_writer.writerow([dataset_name, algorithm_name, trial, row_values["part_names"], row_values["placement_order"], row_values["valid"], row_values["clearance_ok"]] + [row_values[name] for name in metric_names] + [center_of_mass[0], center_of_mass[1], center_of_mass[2], bbox_center[0], bbox_center[1], bbox_center[2]] + row_values["products"])
                    trials_file.flush()
                    if arguments.save_solutions:
                        solutions_file.write(json.dumps({"dataset": dataset_name, "algorithm": algorithm_name, "trial": trial, "k": arguments.k, "mode": arguments.mode, "container": None if container_size is None else list(container_size), "parts": row_values["part_names"].split(";"), "placements": row_values["placements"], "density": row_values["density"], "valid": row_values["valid"]}) + "\n")
                        solutions_file.flush()
                    finished_runs = finished_runs + 1
                    if (trial + 1) % max(arguments.trials // 5, 1) == 0:
                        elapsed_seconds = time.perf_counter() - benchmark_start
                        remaining_seconds = elapsed_seconds / finished_runs * (total_runs - finished_runs)
                        print("  " + algorithm_name.ljust(20) + str(trial + 1).rjust(5) + "/" + str(arguments.trials) + "   about " + format(remaining_seconds / 60.0, ".1f") + " min left overall", flush=True)
                valid_flags = np.array(valid_flags)
                densities = np.array(metric_values["density"])
                summary_row = {}
                summary_row["dataset"] = dataset_name
                summary_row["algorithm"] = algorithm_name
                summary_row["k"] = arguments.k
                summary_row["mode"] = arguments.mode
                summary_row["trials"] = arguments.trials
                scores = np.where(valid_flags, densities, 0.0)
                summary_row["score"] = float(np.mean(scores))
                summary_row["score_ci99_low"], summary_row["score_ci99_high"] = confidence_interval_99(scores)
                summary_row["valid_rate"] = float(np.mean(valid_flags))
                summary_row["clearance_ok_rate"] = float(np.mean(clearance_flags))
                for name in metric_names:
                    values = np.array(metric_values[name], dtype=float)
                    summary_row[name + "_mean"] = float(np.mean(values))
                    summary_row[name + "_std"] = float(np.std(values, ddof=1)) if len(values) > 1 else 0.0
                    summary_row[name + "_ci99_low"], summary_row[name + "_ci99_high"] = confidence_interval_99(values)
                summary_rows.append(summary_row)

    if pool is not None:
        pool.close()
        pool.join()
    if solutions_file is not None:
        solutions_file.close()
        print("Solutions:         " + solutions_path)

    with open(summary_path, "w", newline="") as summary_file:
        summary_writer = csv.DictWriter(summary_file, fieldnames=summary_columns)
        summary_writer.writeheader()
        summary_writer.writerows(summary_rows)

    print("")
    print("mode=" + arguments.mode + "  k=" + str(arguments.k) + "  n=" + str(arguments.trials) + "  clearance t=" + str(arguments.clearance) + " mm  restarts=" + str(arguments.restarts) + "  voxel_pitch=" + str(arguments.voxel_pitch))
    print("dens = % volume utilized (mean), AR = aspect ratio, COM% = COM to COV distance as % of box diagonal, gap = min gap mm, cont = part pairs in contact (within t + 0.5 mm), clr = share of trials meeting t")
    header = "dataset".ljust(17) + "algorithm".ljust(20) + "score".rjust(7) + "dens".rjust(7) + "valid".rjust(7) + "box x*y*z mm".rjust(20) + "AR".rjust(6) + "COM%".rjust(6) + "Izz/Ixx".rjust(9) + "gap".rjust(6) + "cont".rjust(6) + "clr".rjust(6) + "s/trial".rjust(9)
    print(header)
    for summary_row in summary_rows:
        box_text = format(summary_row["bbox_x_mean"], ".0f") + "x" + format(summary_row["bbox_y_mean"], ".0f") + "x" + format(summary_row["bbox_z_mean"], ".0f")
        inertia_ratio = summary_row["Izz_mean"] / summary_row["Ixx_mean"] if summary_row["Ixx_mean"] > 0 else 0.0
        line = summary_row["dataset"].ljust(17) + summary_row["algorithm"].ljust(20)
        line = line + format(summary_row["score"], ".3f").rjust(7)
        line = line + format(summary_row["density_mean"], ".3f").rjust(7)
        line = line + format(summary_row["valid_rate"], ".2f").rjust(7)
        line = line + box_text.rjust(20)
        line = line + format(summary_row["aspect_ratio_mean"], ".2f").rjust(6)
        line = line + format(100 * summary_row["com_offset_normalized_mean"], ".1f").rjust(6)
        line = line + format(inertia_ratio, ".2f").rjust(9)
        line = line + format(summary_row["minimum_gap_mean"], ".2f").rjust(6)
        line = line + format(summary_row["contacts_mean"], ".1f").rjust(6)
        line = line + format(summary_row["clearance_ok_rate"], ".2f").rjust(6)
        line = line + format(summary_row["seconds_mean"], ".3f").rjust(9)
        print(line)
    print("")
    print("Total time: " + format((time.perf_counter() - benchmark_start) / 60.0, ".1f") + " min")
    print("Per-trial results: " + trials_path)
    print("Summary:           " + summary_path)

    if not arguments.no_plot:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        chart_metrics = [("score", "% volume utilized (score, invalid = 0)", 1.0), ("aspect_ratio_mean", "aspect ratio (longest / shortest)", 1.0), ("com_offset_normalized_mean", "COM to COV distance, % of box diagonal", 100.0), ("minimum_gap_mean", "minimum gap between parts, mm", 1.0), ("valid_rate", "share of valid trials", 1.0), ("seconds_mean", "seconds per trial", 1.0)]
        figure, axes = plt.subplots(2, 3, figsize=(18, 9))
        bar_width = 0.8 / len(algorithm_names)
        category_positions = np.arange(len(dataset_names))
        for axis, (metric_key, metric_title, scale) in zip(axes.ravel(), chart_metrics):
            for algorithm_number, algorithm_name in enumerate(algorithm_names):
                values = []
                error_low = []
                error_high = []
                for dataset_name in dataset_names:
                    matching_rows = [row for row in summary_rows if row["dataset"] == dataset_name and row["algorithm"] == algorithm_name]
                    row = matching_rows[0] if len(matching_rows) > 0 else None
                    values.append(row[metric_key] * scale if row is not None else 0.0)
                    low_key = metric_key.replace("_mean", "") + "_ci99_low"
                    high_key = metric_key.replace("_mean", "") + "_ci99_high"
                    if row is not None and low_key in row:
                        error_low.append(values[-1] - row[low_key] * scale)
                        error_high.append(row[high_key] * scale - values[-1])
                    else:
                        error_low.append(0.0)
                        error_high.append(0.0)
                axis.bar(category_positions + (algorithm_number - (len(algorithm_names) - 1) / 2.0) * bar_width, values, bar_width, label=algorithm_name, yerr=[error_low, error_high], capsize=1.5, error_kw={"linewidth": 0.7, "color": "#333333"})
            axis.set_title(metric_title, fontsize=11)
            axis.set_xticks(category_positions)
            axis.set_xticklabels(dataset_names, rotation=20, fontsize=9)
            axis.grid(axis="y", alpha=0.3)
            if metric_key == "seconds_mean":
                axis.set_yscale("log")
        axes[0, 0].legend(fontsize=8)
        figure.suptitle("Nesting benchmark  (mode " + arguments.mode + ", k = " + str(arguments.k) + ", n = " + str(arguments.trials) + ", clearance " + str(arguments.clearance) + " mm; error bars = 99% confidence interval of the mean)", fontsize=13)
        figure.tight_layout()
        figure.savefig(plot_path, dpi=130)
        print("Chart:             " + plot_path)


def confidence_interval_99(values):
    """99% confidence interval of the mean (Student t), as (low, high)."""
    values = np.asarray(values, dtype=float)
    count = len(values)
    if count < 2:
        return float(values.mean()), float(values.mean())
    from scipy import stats
    half_width = stats.t.ppf(0.995, count - 1) * values.std(ddof=1) / np.sqrt(count)
    return float(values.mean() - half_width), float(values.mean() + half_width)


loaded_parts_in_this_process = {}


def run_one_trial(job):
    """One trial, runnable in a worker process: (dataset_name, algorithm_name, trial, k, seed, settings, check_pitch, container_size, density). Returns the CSV row values."""
    dataset_name, algorithm_name, trial, k, seed, settings, check_pitch, container_size, density = job
    if dataset_name not in loaded_parts_in_this_process:
        loaded_parts_in_this_process[dataset_name] = nesting_core.load_parts(dataset_name, check_pitch, density)
    all_parts = loaded_parts_in_this_process[dataset_name]
    selection_generator = np.random.default_rng(seed + trial)
    selected_indices = selection_generator.choice(len(all_parts), size=k, replace=k > len(all_parts))
    selected_parts = [all_parts[index] for index in selected_indices]
    placements, result, run_seconds = algorithms.run_algorithm(algorithm_name, selected_parts, container_size, seed + trial, settings, check_pitch)
    inertia_tensor = result["inertia_tensor"]
    principal_moments = result["principal_moments"]
    row_values = {}
    row_values["density"] = result["density"]
    row_values["bbox_x"] = result["bbox_x"]
    row_values["bbox_y"] = result["bbox_y"]
    row_values["bbox_z"] = result["bbox_z"]
    row_values["aspect_ratio"] = result["aspect_ratio"]
    row_values["com_offset"] = result["com_offset"]
    row_values["com_offset_normalized"] = result["com_offset_normalized"]
    row_values["Ixx"] = inertia_tensor[0, 0]
    row_values["Iyy"] = inertia_tensor[1, 1]
    row_values["Izz"] = inertia_tensor[2, 2]
    row_values["I1"] = principal_moments[0]
    row_values["I2"] = principal_moments[1]
    row_values["I3"] = principal_moments[2]
    row_values["minimum_gap"] = result["minimum_gap"]
    row_values["contacts"] = result["contacts"]
    row_values["contacts_per_part"] = result["contacts_per_part"]
    row_values["isolated_parts"] = result["isolated_parts"]
    row_values["placed_fraction"] = result["placed_fraction"]
    row_values["container_fill"] = result["container_fill"]
    row_values["total_mass"] = result["total_mass"]
    row_values["seconds"] = run_seconds
    row_values["valid"] = result["valid"]
    row_values["clearance_ok"] = result["clearance_ok"]
    row_values["part_names"] = ";".join(part["name"] for part in selected_parts)
    row_values["placement_order"] = ">".join(result["placement_order"])
    row_values["center_of_mass"] = result["center_of_mass"]
    row_values["bbox_center"] = result["bbox_center"]
    row_values["products"] = [inertia_tensor[0, 1], inertia_tensor[0, 2], inertia_tensor[1, 2]]
    row_values["placements"] = [{"part": selected_parts[placement["part_index"]]["name"], "rotation": np.asarray(placement["rotation"]).round(6).tolist(), "translation": np.asarray(placement["translation"]).round(4).tolist()} for placement in placements]
    return row_values


if __name__ == "__main__":
    arguments = parser.parse_args()
    main_body()
