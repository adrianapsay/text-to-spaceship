"""
Order study summary: results/order_summary_k10_k20.csv (from order_study.py), plots in results/plots_order/, and results/order_findings.md
with the numbers an engineer needs: how much each algorithm depends on the placement order, which fixed order is best for it, and whether
any fixed order beats the default (largest box first) with 99% confidence.
    python make_order_report.py
"""
import os
import csv
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import benchmark

HERE = os.path.dirname(os.path.abspath(__file__))
RESULTS = os.path.join(HERE, "results")
PLOTS = os.path.join(RESULTS, "plots_order")
os.makedirs(PLOTS, exist_ok=True)
ALGORITHM_ORDER = ["random_rejection", "shelf_packing", "box_bottom_left", "box_extreme_points", "empty_maximal_spaces", "skyline_3d", "wall_building", "voxel_bottom_left", "heightfield_drop", "dblf_24", "best_of_fast", "simulated_annealing", "genetic_algorithm", "genetic_heightfield", "genetic_box", "beam_search", "grasp_ems"]
ORDERS = ["default", "volume_desc", "volume_asc", "convexity_desc", "combined", "flatness_desc", "random"]
LABEL = {"default": "default (largest first)", "volume_desc": "volume desc", "volume_asc": "volume asc", "convexity_desc": "convex first", "combined": "big+convex first", "flatness_desc": "compact first", "random": "random"}

rows = list(csv.DictReader(open(os.path.join(RESULTS, "order_trials_k10_k20.csv"))))
groups = {}
for row in rows:
    groups.setdefault((row["dataset"], int(row["k"]), row["algorithm"], row["order_spec"]), []).append(row)
summary = {}
for key, group in groups.items():
    scores = np.array([float(row["density"]) if row["valid"] == "True" else 0.0 for row in group])
    per_set = {}
    for row, score in zip(group, scores):
        per_set.setdefault(row["set"], []).append(score)
    low, high = benchmark.confidence_interval_99(scores)
    spread = float(np.mean([max(values) - min(values) for values in per_set.values()])) if key[3] == "random" else None
    summary[key] = {"n": len(group), "mean": float(scores.mean()), "lo": low, "hi": high, "best": float(scores.max()), "worst": float(scores.min()), "spread": spread, "per_set": per_set}

datasets = sorted({key[0] for key in summary})
ks = sorted({key[1] for key in summary})
algorithms = [name for name in ALGORITHM_ORDER if any(key[2] == name for key in summary)]

# Paired comparison per algorithm: fixed order minus default on the same part set, pooled over datasets and k; 99% CI of the paired difference.
lines = ["# Order study findings", "", "Same part sets as the benchmark; every algorithm packed each set under its default order (largest box volume first), five fixed heuristic orders and random permutations. Numbers are density (parts volume / bounding box volume). Paired differences are per part set, pooled over categories and k, with 99% confidence intervals (Student t).", ""]
lines.append("| algorithm | sets | random spread (best-worst, same set) | default | best other fixed order | gain vs default (99% CI) | random mean vs default | best of the random orders vs default (99% CI) |")
lines.append("|---|---|---|---|---|---|---|---|")
sensitivity = []
for name in algorithms:
    spreads = []
    default_scores = []
    diffs = {order: [] for order in ORDERS if order != "default"}
    random_diffs = []
    best_random_diffs = []
    for dataset in datasets:
        for k in ks:
            base = summary.get((dataset, k, name, "default"))
            if base is None:
                continue
            for set_number, values in base["per_set"].items():
                base_value = values[0]
                default_scores.append(base_value)
                for order in diffs:
                    other = summary.get((dataset, k, name, order))
                    if other and set_number in other["per_set"]:
                        if order == "random":
                            random_diffs.append(np.mean(other["per_set"][set_number]) - base_value)
                            spreads.append(max(other["per_set"][set_number]) - min(other["per_set"][set_number]))
                            best_random_diffs.append(max(other["per_set"][set_number]) - base_value)
                        else:
                            diffs[order].append(other["per_set"][set_number][0] - base_value)
    if not default_scores:
        continue
    best_order = None
    best_gain = None
    best_ci = None
    for order, values in diffs.items():
        if order in ("random", "volume_desc") or not values:
            continue
        gain = float(np.mean(values))
        if best_gain is None or gain > best_gain:
            best_gain = gain
            best_order = order
            best_ci = benchmark.confidence_interval_99(values)
    random_gain = float(np.mean(random_diffs)) if random_diffs else float("nan")
    if len(default_scores) >= 120:
        sensitivity.append((name, float(np.mean(spreads)) if spreads else 0.0))
    significant = best_ci is not None and best_ci[0] > 0
    best_random_ci = benchmark.confidence_interval_99(best_random_diffs) if best_random_diffs else (float("nan"), float("nan"))
    lines.append("| " + name + (" (partial, still running)" if len(default_scores) < 120 else "") + " | " + str(len(default_scores)) + " | " + format(np.mean(spreads) if spreads else 0.0, ".3f") + " | " + format(np.mean(default_scores), ".3f") + " | " + (LABEL[best_order] if best_order else "-") + " | " + (format(best_gain, "+.3f") + " (" + format(best_ci[0], "+.3f") + " to " + format(best_ci[1], "+.3f") + ")" + (" significant" if significant else "") if best_gain is not None else "-") + " | " + format(random_gain, "+.3f") + " | " + (format(np.mean(best_random_diffs), "+.3f") + " (" + format(best_random_ci[0], "+.3f") + " to " + format(best_random_ci[1], "+.3f") + ")" if best_random_diffs else "-") + " |")
lines.append("")
lines.append("volume desc is the default order itself (same sort key), so it is left out of 'best other fixed order'.")
lines.append("")
lines.append("The last column is what a cheap order search buys: run the packer under the 20 (8 for search methods) random orders of the same parts and keep the best. For constructive packers that is 20 runs of 0.1 s.")
lines.append("")
lines.append("Reading: spread is how much the same parts can change density by order alone (large = order matters). A gain whose 99% interval excludes 0 means that fixed order beats largest-first on average. Random mean vs default below 0 means largest-first is better than a typical random order.")
open(os.path.join(RESULTS, "order_findings.md"), "w").write("\n".join(lines) + "\n")

# Plot 1: sensitivity (spread) by algorithm
figure, axes = plt.subplots(figsize=(11, 4))
axes.bar([name.replace("_", "\n") for name, _ in sensitivity], [value for _, value in sensitivity], color="#2a78d6")
axes.set_ylabel("best minus worst density\n(random orders, same parts)")
axes.set_title("How much placement order matters, by algorithm (pooled over categories, k = 10 and 20; complete runs only)")
axes.tick_params(axis="x", labelsize=7)
figure.tight_layout()
figure.savefig(os.path.join(PLOTS, "order_sensitivity.png"), dpi=130)
plt.close(figure)

# Plot 2: per dataset and k, density by order for each algorithm (grid)
for k in ks:
    figure, axes_grid = plt.subplots(2, 3, figsize=(15, 8), sharey=False)
    for number, dataset in enumerate(datasets[:6]):
        axes = axes_grid[number // 3][number % 3]
        width = 0.8 / len(ORDERS)
        for order_number, order in enumerate(ORDERS):
            values = [summary.get((dataset, k, name, order), {}).get("mean", np.nan) for name in algorithms]
            errors = [summary.get((dataset, k, name, order), {}).get("hi", np.nan) - summary.get((dataset, k, name, order), {}).get("mean", np.nan) for name in algorithms]
            axes.bar(np.arange(len(algorithms)) + (order_number - len(ORDERS) / 2 + 0.5) * width, values, width, yerr=errors, label=LABEL[order], capsize=1, error_kw={"linewidth": 0.5})
        axes.set_title(dataset.replace("_", " ") + ", k = " + str(k), fontsize=10)
        axes.set_xticks(np.arange(len(algorithms)))
        axes.set_xticklabels([name.replace("_", "\n") for name in algorithms], fontsize=6)
        axes.grid(axis="y", alpha=0.3)
        if number == 0:
            axes.legend(fontsize=7)
    figure.suptitle("Density by placement order (error bars = 99% CI)", fontsize=12)
    figure.tight_layout()
    figure.savefig(os.path.join(PLOTS, "order_by_algorithm_k" + str(k) + ".png"), dpi=120)
    plt.close(figure)
# Summary CSV
with open(os.path.join(RESULTS, "order_summary_k10_k20.csv"), "w", newline="") as handle:
    writer = csv.writer(handle)
    writer.writerow(["dataset", "k", "algorithm", "order_spec", "runs", "score", "score_ci99_low", "score_ci99_high", "score_best", "score_worst", "within_set_spread"])
    for key, value in sorted(summary.items()):
        writer.writerow(list(key) + [value["n"], value["mean"], value["lo"], value["hi"], value["best"], value["worst"], value["spread"] if value["spread"] is not None else ""])
print("\n".join(lines))
