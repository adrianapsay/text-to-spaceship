"""
Result plots with 99% confidence intervals from one or more summary CSVs (any mix of k values and algorithm sets).
Writes PNGs to results/plots/ and a combined report.pdf; also a leaderboard CSV (one row per dataset, k, algorithm, sorted by score).

    python make_report.py results/summary_large_fast_k10_n300.csv results/summary_large_search_k10_n100.csv ... --output results/report_large.pdf
"""

import os
import csv
import argparse
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages

parser = argparse.ArgumentParser()
parser.add_argument("summaries", nargs="+")
parser.add_argument("--output", default="results/report.pdf")
parser.add_argument("--plots_folder", default="results/plots")
arguments = parser.parse_args()

INK = "#0b0b0b"
INK2 = "#52514e"
INK3 = "#9a9a94"
LIGHT = "#e8e8e4"
BLUE = "#2a78d6"
ORANGE = "#eb6834"
AQUA = "#1baf7a"
YELLOW = "#eda100"
MAGENTA = "#e87ba4"
VIOLET = "#6250d6"
DATASET_ORDER = ["cuboids", "simple_convex", "complex_convex", "simple_concave", "complex_concave", "real_shapes"]
ALGORITHM_ORDER = ["random_rejection", "shelf_packing", "box_bottom_left", "box_extreme_points", "empty_maximal_spaces", "skyline_3d", "wall_building", "force_based", "force_based_v2", "voxel_bottom_left", "heightfield_drop", "dblf_24", "best_of_fast", "simulated_annealing", "genetic_algorithm", "genetic_heightfield", "beam_search", "grasp_ems"]
FAMILY = {"random_rejection": "baseline", "shelf_packing": "box", "box_bottom_left": "box", "box_extreme_points": "box", "empty_maximal_spaces": "box", "force_based": "box", "force_based_v2": "box", "voxel_bottom_left": "shape", "heightfield_drop": "shape", "best_of_fast": "shape", "simulated_annealing": "search", "genetic_algorithm": "search", "genetic_heightfield": "search", "skyline_3d": "box", "wall_building": "box", "dblf_24": "shape", "beam_search": "search", "grasp_ems": "search"}
FAMILY_COLOR = {"baseline": INK3, "box": BLUE, "shape": AQUA, "search": ORANGE}
SHORT = {"random_rejection": "random", "shelf_packing": "shelf", "box_bottom_left": "bottom\nleft", "box_extreme_points": "extreme\npoints", "empty_maximal_spaces": "EMS", "force_based": "force", "force_based_v2": "force\nv2", "voxel_bottom_left": "voxel", "heightfield_drop": "height\nfield", "best_of_fast": "best of\nfast", "simulated_annealing": "anneal", "genetic_algorithm": "genetic", "genetic_heightfield": "genetic\nhfield", "skyline_3d": "skyline", "wall_building": "wall", "dblf_24": "DBLF\n24", "beam_search": "beam", "grasp_ems": "GRASP"}
plt.rcParams["font.family"] = "DejaVu Sans"
plt.rcParams["axes.edgecolor"] = LIGHT
plt.rcParams["axes.labelcolor"] = INK2
plt.rcParams["xtick.color"] = INK2
plt.rcParams["ytick.color"] = INK2

rows = {}
for path in arguments.summaries:
    with open(path) as summary_file:
        for row in csv.DictReader(summary_file):
            key = (row["dataset"], int(float(row["k"])), row["algorithm"])
            rows[key] = {name: (float(value) if name not in ("dataset", "algorithm", "mode") else value) for name, value in row.items()}
k_values = sorted(set(key[1] for key in rows))
os.makedirs(arguments.plots_folder, exist_ok=True)
pdf = PdfPages(arguments.output)


def present_algorithms(k):
    return [name for name in ALGORITHM_ORDER if all((dataset_name, k, name) in rows for dataset_name in DATASET_ORDER)]


def save(figure, file_name):
    figure.savefig(os.path.join(arguments.plots_folder, file_name), dpi=150)
    pdf.savefig(figure)
    plt.close(figure)


def bars_by_category(k, metric, scale, y_label, title, y_limit=None, higher_is_better=True):
    names = present_algorithms(k)
    figure = plt.figure(figsize=(13.333, 7.5))
    figure.text(0.05, 0.94, title, fontsize=20, weight="bold", color=INK, va="center")
    figure.text(0.05, 0.895, "k = " + str(k) + ", open mode, 60-part categories (23 real shapes); error bars = 99% confidence interval of the mean; n per bar in the leaderboard CSV", fontsize=11, color=INK2, va="center")
    for number, dataset_name in enumerate(DATASET_ORDER):
        axes = figure.add_axes([0.06 + (number % 3) * 0.315, 0.52 - (number // 3) * 0.40, 0.26, 0.27])
        values = np.array([rows[(dataset_name, k, name)][metric + "_mean" if metric != "score" else "score"] * scale for name in names])
        lows = np.array([rows[(dataset_name, k, name)][(metric if metric != "score" else "score") + "_ci99_low"] * scale for name in names])
        highs = np.array([rows[(dataset_name, k, name)][(metric if metric != "score" else "score") + "_ci99_high"] * scale for name in names])
        colors = [FAMILY_COLOR[FAMILY[name]] for name in names]
        axes.bar(range(len(names)), values, color=colors, width=0.72, yerr=[values - lows, highs - values], capsize=2, error_kw={"linewidth": 0.8, "color": INK})
        axes.set_title(dataset_name.replace("_", " "), fontsize=11, loc="left", color=INK)
        axes.set_xticks(range(len(names)))
        axes.set_xticklabels([SHORT[name].replace("\n", " ") for name in names], fontsize=6.5, rotation=60, ha="right", rotation_mode="anchor")
        axes.tick_params(axis="y", labelsize=8)
        axes.grid(axis="y", color=LIGHT, linewidth=0.6)
        axes.set_axisbelow(True)
        for spine in ("top", "right"):
            axes.spines[spine].set_visible(False)
        if y_limit is not None:
            axes.set_ylim(0, y_limit)
        if number % 3 == 0:
            axes.set_ylabel(y_label, fontsize=9)
        best = int(np.argmax(values)) if higher_is_better else int(np.argmin(values))
        axes.text(best, highs[best], format(values[best], ".2f"), ha="center", va="bottom", fontsize=7.5, color=INK)
    figure.text(0.62, 0.845, "■ baseline", fontsize=9, color=INK3)
    figure.text(0.70, 0.845, "■ box based", fontsize=9, color=BLUE)
    figure.text(0.79, 0.845, "■ shape based", fontsize=9, color=AQUA)
    figure.text(0.89, 0.845, "■ search", fontsize=9, color=ORANGE)
    figure.text(0.05, 0.012, "nesting_bench  ·  make_report.py", fontsize=8, color=INK3)
    save(figure, metric + "_k" + str(k) + ".png")


for k in k_values:
    if len(present_algorithms(k)) == 0:
        continue
    bars_by_category(k, "score", 1.0, "density (parts volume / box volume)", "Density by category, k = " + str(k), 1.0)
    bars_by_category(k, "aspect_ratio", 1.0, "longest / shortest box side", "Aspect ratio (lower = more compact), k = " + str(k), None, False)
    bars_by_category(k, "com_offset_normalized", 100.0, "COM offset, % of diagonal", "Center of mass offset (lower = better balanced), k = " + str(k), None, False)
    bars_by_category(k, "seconds", 1.0, "seconds per packing", "Cost per packing, k = " + str(k), None, False)
    if all("contacts_per_part_mean" in rows[(dataset_name, k, name)] for dataset_name in DATASET_ORDER for name in present_algorithms(k)):
        bars_by_category(k, "contacts_per_part", 1.0, "contacts per part (pairs within t + 0.5 mm)", "Contacts per part (higher = more parts touch through the clearance), k = " + str(k))
        bars_by_category(k, "isolated_parts", 1.0, "parts touching nothing", "Isolated parts (parts with no contact, i.e. nothing to support them), k = " + str(k), None, False)

# density versus k, one panel per category, one line per algorithm present at every k, with 99% CI bands
if len(k_values) >= 2:
    names = [name for name in ALGORITHM_ORDER if all(all((dataset_name, k, name) in rows for dataset_name in DATASET_ORDER) for k in k_values)]
    palette = [INK3, BLUE, AQUA, YELLOW, MAGENTA, VIOLET, ORANGE, "#008300", "#8c564b", "#e34948", "#17becf", "#7f7f7f", "#bcbd22", "#1f3b73", "#b0469a", "#5a8f29", "#c98a00", "#333333"]
    figure = plt.figure(figsize=(13.333, 7.5))
    figure.text(0.05, 0.94, "Density versus part count k", fontsize=20, weight="bold", color=INK, va="center")
    figure.text(0.05, 0.895, "shaded band = 99% confidence interval of the mean", fontsize=11, color=INK2, va="center")
    for number, dataset_name in enumerate(DATASET_ORDER):
        axes = figure.add_axes([0.06 + (number % 3) * 0.315, 0.53 - (number // 3) * 0.35, 0.26, 0.27])
        for color, name in zip(palette, names):
            means = [rows[(dataset_name, k, name)]["score"] for k in k_values]
            lows = [rows[(dataset_name, k, name)]["score_ci99_low"] for k in k_values]
            highs = [rows[(dataset_name, k, name)]["score_ci99_high"] for k in k_values]
            axes.plot(k_values, means, color=color, linewidth=1.8, marker="o", markersize=3.5, label=name.replace("_", " "))
            axes.fill_between(k_values, lows, highs, color=color, alpha=0.15, linewidth=0)
        axes.set_title(dataset_name.replace("_", " "), fontsize=11, loc="left", color=INK)
        axes.set_xticks(k_values)
        axes.tick_params(labelsize=8)
        axes.set_ylim(0, 1.0)
        axes.grid(color=LIGHT, linewidth=0.6)
        for spine in ("top", "right"):
            axes.spines[spine].set_visible(False)
        if number % 3 == 0:
            axes.set_ylabel("density", fontsize=9)
        if number >= 3:
            axes.set_xlabel("k parts", fontsize=9)
    handles, labels = axes.get_legend_handles_labels()
    figure.legend(handles, labels, loc="lower center", ncol=7, fontsize=8, frameon=False, bbox_to_anchor=(0.5, 0.04))
    save(figure, "density_vs_k.png")

# leaderboard CSV
leaderboard_path = os.path.join(os.path.dirname(arguments.output), "leaderboard.csv")
with open(leaderboard_path, "w", newline="") as leaderboard_file:
    writer = csv.writer(leaderboard_file)
    writer.writerow(["dataset", "k", "rank", "algorithm", "n", "score", "ci99_low", "ci99_high", "aspect_ratio", "com_offset_pct", "min_gap_mm", "seconds"])
    for dataset_name in DATASET_ORDER:
        for k in k_values:
            ranked = sorted([(key[2], row) for key, row in rows.items() if key[0] == dataset_name and key[1] == k], key=lambda item: -item[1]["score"])
            for rank, (name, row) in enumerate(ranked):
                writer.writerow([dataset_name, k, rank + 1, name, int(row["trials"]), format(row["score"], ".4f"), format(row["score_ci99_low"], ".4f"), format(row["score_ci99_high"], ".4f"), format(row["aspect_ratio_mean"], ".3f"), format(100 * row["com_offset_normalized_mean"], ".2f"), format(row["minimum_gap_mean"], ".3f"), format(row["seconds_mean"], ".3f")])
pdf.close()
print("wrote " + arguments.output + ", plots in " + arguments.plots_folder + ", leaderboard " + leaderboard_path)
