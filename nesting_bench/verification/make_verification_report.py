"""
Plots for the two verification tests from results/verification_*_summary.csv: mean ratio to the known optimum with 99% CIs, per group and algorithm, plus solved rates.
Writes results/plots_verification/*.png and results/verification_report.pdf.
    python make_verification_report.py
"""

import os
import csv
import glob
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages

HERE = os.path.dirname(os.path.abspath(__file__))
results = os.path.join(HERE, "..", "results")
plots = os.path.join(results, "plots_verification")
os.makedirs(plots, exist_ok=True)
INK = "#0b0b0b"
INK2 = "#52514e"
INK3 = "#9a9a94"
LIGHT = "#e8e8e4"
FAMILY = {"random_rejection": "#9a9a94", "shelf_packing": "#2a78d6", "box_bottom_left": "#2a78d6", "box_extreme_points": "#2a78d6", "empty_maximal_spaces": "#2a78d6", "force_based": "#2a78d6", "force_based_v2": "#2a78d6", "voxel_bottom_left": "#1baf7a", "heightfield_drop": "#1baf7a", "best_of_fast": "#1baf7a", "simulated_annealing": "#eb6834", "genetic_algorithm": "#eb6834", "genetic_heightfield": "#eb6834"}
ORDER = list(FAMILY.keys())
SHORT = {"random_rejection": "random", "shelf_packing": "shelf", "box_bottom_left": "bottom\nleft", "box_extreme_points": "extreme\npoints", "empty_maximal_spaces": "EMS", "force_based": "force", "force_based_v2": "force\nv2", "voxel_bottom_left": "voxel", "heightfield_drop": "height\nfield", "best_of_fast": "best of\nfast", "simulated_annealing": "anneal", "genetic_algorithm": "genetic", "genetic_heightfield": "genetic\nhfield"}
plt.rcParams["font.family"] = "DejaVu Sans"
pdf = PdfPages(os.path.join(results, "verification_report.pdf"))


def read(path):
    rows = {}
    for row in csv.DictReader(open(path)):
        rows[(row["group"], row["algorithm"])] = {key: (float(value) if key not in ("group", "algorithm") else value) for key, value in row.items()}
    return rows


def panel_grid(title, subtitle, groups, rows, metric, y_label, file_name, y_limit=None, reference_line=None):
    columns = 3
    row_count = int(np.ceil(len(groups) / columns))
    figure = plt.figure(figsize=(13.333, 2.3 + 2.4 * row_count))
    figure.text(0.04, 1 - 0.35 / figure.get_figheight(), title, fontsize=18, weight="bold", color=INK, va="center")
    figure.text(0.04, 1 - 0.65 / figure.get_figheight(), subtitle, fontsize=10, color=INK2, va="center")
    panel_height = 1.9 / figure.get_figheight()
    gap = 0.5 / figure.get_figheight()
    for number, group in enumerate(groups):
        names = [name for name in ORDER if (group, name) in rows]
        if len(names) == 0:
            continue
        top = 1 - (1.0 / figure.get_figheight()) - (number // columns) * (panel_height + gap)
        axes = figure.add_axes([0.06 + (number % columns) * 0.315, top - panel_height, 0.26, panel_height])
        values = np.array([rows[(group, name)][metric] for name in names])
        if metric == "ratio_mean":
            lows = np.array([rows[(group, name)]["ratio_ci99_low"] for name in names])
            highs = np.array([rows[(group, name)]["ratio_ci99_high"] for name in names])
            errors = [np.clip(values - lows, 0, None), np.clip(highs - values, 0, None)]
        else:
            errors = None
        axes.bar(range(len(names)), values, color=[FAMILY[name] for name in names], width=0.72, yerr=errors, capsize=2, error_kw={"linewidth": 0.8, "color": INK})
        if reference_line is not None:
            axes.axhline(reference_line, color=INK3, linewidth=0.8, linestyle="--")
        axes.set_title(group.replace("_", " "), fontsize=10, loc="left", color=INK)
        axes.set_xticks(range(len(names)))
        axes.set_xticklabels([SHORT[name] for name in names], fontsize=6)
        axes.tick_params(axis="y", labelsize=7)
        axes.grid(axis="y", color=LIGHT, linewidth=0.6)
        axes.set_axisbelow(True)
        for spine in ("top", "right"):
            axes.spines[spine].set_visible(False)
        if y_limit is not None:
            axes.set_ylim(0, y_limit)
        if number % columns == 0:
            axes.set_ylabel(y_label, fontsize=8)
    figure.text(0.06, 0.012, "■ baseline", fontsize=8, color="#9a9a94")
    figure.text(0.14, 0.012, "■ box based", fontsize=8, color="#2a78d6")
    figure.text(0.23, 0.012, "■ shape based", fontsize=8, color="#1baf7a")
    figure.text(0.33, 0.012, "■ search", fontsize=8, color="#eb6834")
    figure.savefig(os.path.join(plots, file_name), dpi=150)
    pdf.savefig(figure)
    plt.close(figure)


for path in sorted(glob.glob(os.path.join(results, "verification_*_summary.csv"))):
    tag = os.path.basename(path).replace("verification_", "").replace("_summary.csv", "")
    rows = read(path)
    groups = sorted(set(key[0] for key in rows), key=lambda g: (g.split("_k")[0], int(g.split("_k")[1]) if "_k" in g and g.split("_k")[1].isdigit() else 0))
    if tag.startswith("scrabble"):
        groups = sorted(groups, key=lambda g: (g.split("_")[0], g.split("_")[1], int(g.split("_k")[1])))
    mode = "container" if "container" in tag else "open"
    pitch = "voxel pitch 1 mm" if "pitch1" in tag else "voxel pitch 2 mm"
    if mode == "open":
        panel_grid("Verification " + tag.replace("_", " ") + ": ratio to the known optimum", "open mode (minimize the box), t = 0, " + pitch + "; ratio = density / ceiling; 1.0 = the known optimum (dashed); bars = mean over instances and repeats, 99% CI", groups, rows, "ratio_mean", "density / ceiling", tag + "_ratio.png", None, 1.0)
    else:
        panel_grid("Verification " + tag.replace("_", " ") + ": share of parts that fit the proven box", "container mode (the instance's own box), t = 0, " + pitch + "; 1.0 = everything fits; bars = mean over instances and repeats, 99% CI", groups, rows, "ratio_mean", "fraction of parts placed", tag + "_fit.png", 1.05, 1.0)
    panel_grid("Verification " + tag.replace("_", " ") + ": solved rate", "solved = valid, all parts placed and within 2% of the optimum (" + mode + " mode, " + pitch + ")", groups, rows, "solved_rate", "solved rate", tag + "_solved.png", 1.05, None)
pdf.close()
print("wrote " + os.path.join(results, "verification_report.pdf") + " and " + plots)
