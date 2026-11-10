"""
Order study: how much does the placement order change each algorithm's result?

For every (category, k) it draws `--sets` part sets (same seeds and part sets as benchmark.py: seed + set number), and packs each set with every algorithm under:
    the algorithm's default order (largest box volume first),
    `--random_orders` random permutations (order seed = 1000 * set + order number),
    the heuristic orders: volume_desc, volume_asc, convexity_desc, combined (volume x convexity), flatness_desc.
Search algorithms (simulated annealing, genetic x3) take the order as their starting point and get `--random_orders_search` random orders instead.

Output: results/order_trials_<name>.csv (one row per run, with the order spec, the order itself, the result order and every metric),
        results/order_summary_<name>.csv (per category, k, algorithm, order spec: mean density, 99% CI, best, worst, spread),
        results/order_solutions_<name>.jsonl (every packing, for the explorer).
Resumable: rerun with the same --name and finished (category, k, algorithm, set, order) rows are kept.

    python order_study.py --name order_k10_k20 --k 10 20 --sets 10 --random_orders 20 --random_orders_search 8 --workers 2
"""

import os
import csv
import json
import time
import argparse
import numpy as np
import nesting_core
import algorithms
import benchmark

HERE = os.path.dirname(os.path.abspath(__file__))
parser = argparse.ArgumentParser()
parser.add_argument("--name", default="order")
parser.add_argument("--k", type=int, nargs="+", default=[10, 20])
parser.add_argument("--sets", type=int, default=10, help="part sets per (category, k)")
parser.add_argument("--random_orders", type=int, default=20)
parser.add_argument("--random_orders_search", type=int, default=8)
parser.add_argument("--algorithms", nargs="+", default=None)
parser.add_argument("--datasets", nargs="+", default=None)
parser.add_argument("--datasets_folder", default=os.path.join(HERE, "datasets_large"))
parser.add_argument("--seed", type=int, default=0)
parser.add_argument("--workers", type=int, default=2)
arguments = parser.parse_args()

HEURISTIC_ORDERS = ["default", "volume_desc", "volume_asc", "convexity_desc", "combined", "flatness_desc"]
SEARCH_ALGORITHMS = ["simulated_annealing", "genetic_algorithm", "genetic_heightfield", "genetic_box"]
ORDERED = [name for name in algorithms.ORDERED_ALGORITHMS if name in algorithms.ALGORITHMS]
nesting_core.DATASETS_FOLDER = os.path.abspath(arguments.datasets_folder)
os.environ["NESTING_DATASETS_FOLDER"] = nesting_core.DATASETS_FOLDER
algorithm_names = arguments.algorithms if arguments.algorithms else ORDERED
dataset_names = arguments.datasets if arguments.datasets else nesting_core.list_datasets()
metric_names = ["density", "bbox_x", "bbox_y", "bbox_z", "aspect_ratio", "com_offset", "com_offset_normalized", "I1", "I2", "I3", "minimum_gap", "contacts", "contacts_per_part", "isolated_parts", "placed_fraction", "seconds"]
trial_columns = ["dataset", "k", "algorithm", "set", "order_spec", "order_number", "order", "parts", "placement_order", "valid", "clearance_ok"] + metric_names

results_folder = os.path.join(HERE, "results")
trials_path = os.path.join(results_folder, "order_trials_" + arguments.name + ".csv")
summary_path = os.path.join(results_folder, "order_summary_" + arguments.name + ".csv")
solutions_path = os.path.join(results_folder, "order_solutions_" + arguments.name + ".jsonl")

settings = dict(algorithms.DEFAULT_SETTINGS)
check_pitch = settings["voxel_pitch"] / 2.0
loaded = {}


def run_job(job):
    dataset_name, k, algorithm_name, set_number, order_spec, order_number = job
    if dataset_name not in loaded:
        loaded[dataset_name] = nesting_core.load_parts(dataset_name, check_pitch, 1.0)
    all_parts = loaded[dataset_name]
    selection_generator = np.random.default_rng(arguments.seed + set_number)
    selected_indices = selection_generator.choice(len(all_parts), size=k, replace=k > len(all_parts))
    selected_parts = [all_parts[index] for index in selected_indices]
    run_settings = dict(settings)
    if order_spec == "random":
        order_generator = np.random.default_rng(1000 * set_number + order_number + 7)
        run_settings["order"] = [int(index) for index in order_generator.permutation(k)]
    else:
        run_settings["order"] = order_spec
    order_used = algorithms.initial_order(selected_parts, np.random.default_rng(0), run_settings)
    placements, result, run_seconds = algorithms.run_algorithm(algorithm_name, selected_parts, None, arguments.seed + set_number, run_settings, check_pitch)
    row = {"dataset": dataset_name, "k": k, "algorithm": algorithm_name, "set": set_number, "order_spec": order_spec, "order_number": order_number, "order": ">".join(selected_parts[index]["name"] for index in order_used), "parts": ";".join(part["name"] for part in selected_parts), "placement_order": ">".join(result["placement_order"]), "valid": result["valid"], "clearance_ok": result["clearance_ok"]}
    for name in metric_names:
        if name == "seconds":
            row[name] = run_seconds
        elif name in ("I1", "I2", "I3"):
            row[name] = result["principal_moments"][int(name[1]) - 1]
        else:
            row[name] = result[name]
    row["placements"] = [{"part": selected_parts[placement["part_index"]]["name"], "rotation": np.asarray(placement["rotation"]).round(6).tolist(), "translation": np.asarray(placement["translation"]).round(4).tolist()} for placement in placements]
    return row


def job_key(job):
    return tuple(str(value) for value in job)


if __name__ == "__main__":
    os.makedirs(results_folder, exist_ok=True)
    jobs = []
    for dataset_name in dataset_names:
        for k in arguments.k:
            for algorithm_name in algorithm_names:
                random_count = arguments.random_orders_search if algorithm_name in SEARCH_ALGORITHMS else arguments.random_orders
                for set_number in range(arguments.sets):
                    for order_spec in HEURISTIC_ORDERS:
                        jobs.append((dataset_name, k, algorithm_name, set_number, order_spec, 0))
                    for order_number in range(random_count):
                        jobs.append((dataset_name, k, algorithm_name, set_number, "random", order_number))
    done = set()
    if os.path.exists(trials_path):
        for old in csv.DictReader(open(trials_path)):
            done.add((old["dataset"], old["k"], old["algorithm"], old["set"], old["order_spec"], old["order_number"]))
    pending = [job for job in jobs if job_key(job) not in done]
    print(str(len(jobs)) + " runs, " + str(len(done)) + " done, " + str(len(pending)) + " pending", flush=True)
    write_header = not os.path.exists(trials_path)
    trials_file = open(trials_path, "a", newline="")
    writer = csv.writer(trials_file)
    if write_header:
        writer.writerow(trial_columns)
    solutions_file = open(solutions_path, "a")
    # Group pending jobs by dataset so each worker keeps one dataset loaded at a time.
    pending.sort(key=lambda job: (job[0], job[1], job[2]))
    started = time.perf_counter()
    import multiprocessing
    pool = multiprocessing.Pool(arguments.workers, maxtasksperchild=200)
    for number, row in enumerate(pool.imap(run_job, pending, chunksize=1)):
        writer.writerow([row[column] for column in trial_columns])
        trials_file.flush()
        solutions_file.write(json.dumps({"dataset": row["dataset"], "k": row["k"], "algorithm": row["algorithm"], "set": row["set"], "order_spec": row["order_spec"], "order_number": row["order_number"], "parts": row["parts"].split(";"), "order": row["order"].split(">"), "placements": row["placements"], "density": row["density"], "valid": row["valid"]}) + "\n")
        solutions_file.flush()
        if (number + 1) % 50 == 0:
            elapsed = time.perf_counter() - started
            print(str(number + 1) + "/" + str(len(pending)) + "  " + format(elapsed / (number + 1) * (len(pending) - number - 1) / 3600.0, ".1f") + " h left", flush=True)
    pool.close()
    pool.join()
    trials_file.close()
    solutions_file.close()
    # Summary
    rows = list(csv.DictReader(open(trials_path)))
    groups = {}
    for row in rows:
        groups.setdefault((row["dataset"], row["k"], row["algorithm"], row["order_spec"]), []).append(row)
    with open(summary_path, "w", newline="") as summary_file:
        summary_writer = csv.writer(summary_file)
        summary_writer.writerow(["dataset", "k", "algorithm", "order_spec", "runs", "score", "score_ci99_low", "score_ci99_high", "score_std", "score_best", "score_worst", "valid_rate", "aspect_ratio_mean", "contacts_per_part_mean", "seconds_mean", "within_set_spread"])
        for (dataset_name, k, algorithm_name, order_spec), group in sorted(groups.items()):
            scores = np.array([float(row["density"]) if row["valid"] == "True" else 0.0 for row in group])
            low, high = benchmark.confidence_interval_99(scores)
            per_set = {}
            for row, score in zip(group, scores):
                per_set.setdefault(row["set"], []).append(score)
            spread = float(np.mean([max(values) - min(values) for values in per_set.values() if len(values) > 1])) if any(len(values) > 1 for values in per_set.values()) else 0.0
            summary_writer.writerow([dataset_name, k, algorithm_name, order_spec, len(group), scores.mean(), low, high, scores.std(ddof=1) if len(scores) > 1 else 0.0, scores.max(), scores.min(), np.mean([row["valid"] == "True" for row in group]), np.mean([float(row["aspect_ratio"]) for row in group]), np.mean([float(row["contacts_per_part"]) for row in group]), np.mean([float(row["seconds"]) for row in group]), spread])
    print("summary " + summary_path)
