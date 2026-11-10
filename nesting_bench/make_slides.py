"""
Build slides.pdf: the problem, the test procedure, the datasets, one slide per algorithm (diagram + how / strength / weakness), then the results.
All diagrams are drawn here with matplotlib; all result plots are read from the CSVs in results/.

    python make_slides.py --six results/summary_20261027_142917.csv --four results/summary_<new>.csv --n1000 results/summary_<n1000>.csv --sweep results/summary_k5.csv results/summary_k20.csv results/summary_k30.csv
"""

import os
import csv
import argparse
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.patches import Rectangle, FancyArrowPatch, Circle, Polygon

parser = argparse.ArgumentParser()
parser.add_argument("--six", default="results/summary_20261027_142917.csv", help="summary CSV of the six original algorithms, n = 100, k = 10")
parser.add_argument("--four", default=None, help="summary CSV of the four new algorithms, n = 100, k = 10")
parser.add_argument("--n1000", default=None, help="summary CSV of the n = 1000 run")
parser.add_argument("--sweep", nargs="*", default=[], help="summary CSVs of the k sweep (k = 5, 20, 30); the k = 10 point comes from --six")
parser.add_argument("--container", nargs="*", default=[], help="summary CSVs of the container run (k = 30, 100 mm cube); later files override earlier rows")
parser.add_argument("--large_plots", default=None, help="folder of PNGs from make_report.py (large-pool runs); adds an appendix of result slides")
parser.add_argument("--output", default="slides.pdf")
arguments = parser.parse_args()

BLUE = "#2a78d6"
ORANGE = "#eb6834"
AQUA = "#1baf7a"
YELLOW = "#eda100"
MAGENTA = "#e87ba4"
GREEN = "#008300"
VIOLET = "#6250d6"
RED = "#e34948"
INK = "#0b0b0b"
INK2 = "#52514e"
INK3 = "#9a9a94"
LIGHT = "#e8e8e4"
FILL = "#cde2fb"
PAGE_WIDTH = 13.333
PAGE_HEIGHT = 7.5
DATASET_ORDER = ["cuboids", "simple_convex", "complex_convex", "simple_concave", "complex_concave", "real_shapes"]
ALGORITHM_ORDER = ["random_rejection", "shelf_packing", "box_bottom_left", "box_extreme_points", "force_based", "force_based_v2", "voxel_bottom_left", "heightfield_drop", "simulated_annealing", "genetic_algorithm"]
NEW_ALGORITHMS = ["heightfield_drop", "simulated_annealing", "genetic_algorithm", "force_based_v2"]
FAMILY = {"random_rejection": "baseline", "shelf_packing": "box", "box_bottom_left": "box", "box_extreme_points": "box", "force_based": "box", "force_based_v2": "box", "voxel_bottom_left": "shape", "heightfield_drop": "shape", "simulated_annealing": "search", "genetic_algorithm": "search"}
FAMILY_COLOR = {"baseline": INK3, "box": BLUE, "shape": AQUA, "search": ORANGE}
plt.rcParams["font.family"] = "DejaVu Sans"
plt.rcParams["axes.edgecolor"] = LIGHT
plt.rcParams["axes.labelcolor"] = INK2
plt.rcParams["xtick.color"] = INK2
plt.rcParams["ytick.color"] = INK2

slide_counter = [0]
pdf = PdfPages(arguments.output)


def pretty(name):
    return name.replace("_", " ")


SHORT = {"random_rejection": "random", "shelf_packing": "shelf", "box_bottom_left": "bottom\nleft", "box_extreme_points": "extreme\npoints", "force_based": "force", "force_based_v2": "force\nv2", "voxel_bottom_left": "voxel", "heightfield_drop": "height\nfield", "simulated_annealing": "anneal", "genetic_algorithm": "genetic"}


def read_summary(path):
    rows = {}
    if path is None or not os.path.exists(path):
        return rows
    with open(path) as summary_file:
        for row in csv.DictReader(summary_file):
            rows[(row["dataset"], row["algorithm"])] = {key: (float(value) if key not in ("dataset", "algorithm") else value) for key, value in row.items()}
    return rows


def new_slide(title, subtitle=None):
    slide_counter[0] = slide_counter[0] + 1
    figure = plt.figure(figsize=(PAGE_WIDTH, PAGE_HEIGHT))
    figure.patch.set_facecolor("white")
    figure.text(0.05, 0.925, title, fontsize=24, color=INK, weight="bold", va="center")
    if subtitle is not None:
        figure.text(0.05, 0.875, subtitle, fontsize=13, color=INK2, va="center")
    figure.text(0.05, 0.035, "Text to Spaceship  ·  3D nesting benchmark  ·  Dadmehr Ghasemfar  ·  Nov 2026", fontsize=9, color=INK3)
    figure.text(0.95, 0.035, str(slide_counter[0]), fontsize=9, color=INK3, ha="right")
    return figure


def finish(figure):
    pdf.savefig(figure)
    plt.close(figure)


def text_block(figure, x, y, lines, size=13, color=INK, spacing=0.055, weight="normal"):
    for number, line in enumerate(lines):
        figure.text(x, y - number * spacing, line, fontsize=size, color=color, va="top", weight=weight)


def sketch_axes(figure, rect):
    axes = figure.add_axes(rect)
    axes.set_aspect("equal")
    axes.axis("off")
    return axes


def box(axes, x, y, w, h, color, alpha=0.85, lw=1.2, ls="-", fill=True):
    axes.add_patch(Rectangle((x, y), w, h, facecolor=color if fill else "none", edgecolor=INK if fill else color, alpha=alpha, linewidth=lw, linestyle=ls))


def arrow(axes, start, end, color=INK, lw=1.8, style="-|>"):
    axes.add_patch(FancyArrowPatch(start, end, arrowstyle=style, mutation_scale=14, color=color, linewidth=lw))


def dot(axes, x, y, color, r=0.16):
    axes.add_patch(Circle((x, y), r, facecolor=color, edgecolor="white", linewidth=1.0, zorder=5))


# ---------------------------------------------------------------- 1. title
figure = plt.figure(figsize=(PAGE_WIDTH, PAGE_HEIGHT))
figure.text(0.08, 0.60, "3D nesting benchmark", fontsize=40, weight="bold", color=INK)
figure.text(0.08, 0.50, "Ten packing algorithms, six part categories, one Monte Carlo test bench", fontsize=18, color=INK2)
figure.text(0.08, 0.36, "Text to Spaceship  ·  UC Berkeley MEng capstone with NASA Goddard", fontsize=13, color=INK2)
figure.text(0.08, 0.31, "Dadmehr Daniel Ghasemfar  ·  November 5, 2026", fontsize=13, color=INK2)
figure.text(0.08, 0.20, "Code, datasets and results: nesting_bench/  (python viewer.py to explore, python benchmark.py to reproduce)", fontsize=10, color=INK3)
slide_counter[0] = 1
finish(figure)

# ---------------------------------------------------------------- 2. the problem
figure = new_slide("The problem", "Given k parts, find positions and orientations so they take the least space without touching")
axes = sketch_axes(figure, [0.04, 0.15, 0.55, 0.65])
axes.set_xlim(0, 20)
axes.set_ylim(0, 10)
rng = np.random.default_rng(1)
shapes = [(2.2, 1.2), (1.0, 2.4), (1.6, 1.6), (0.8, 2.0), (2.6, 0.9), (1.3, 1.3)]
colors = [BLUE, ORANGE, AQUA, YELLOW, MAGENTA, VIOLET]
box(axes, 0.5, 0.5, 7.5, 8.5, "none", fill=False, lw=1.0, ls="--")
for number, ((w, h), color) in enumerate(zip(shapes, colors)):
    x = 1.0 + rng.uniform(0, 4.5)
    y = 1.0 + rng.uniform(0, 6.0)
    axes.add_patch(Rectangle((x, y), w, h, angle=rng.uniform(0, 90), facecolor=color, edgecolor=INK, alpha=0.85))
arrow(axes, (8.7, 5.0), (11.3, 5.0), lw=2.5)
axes.text(10.0, 5.6, "pack", ha="center", fontsize=12, color=INK2)
packed = [(12.0, 0.5, 2.2, 1.2, BLUE), (14.2, 0.5, 1.6, 1.6, AQUA), (15.8, 0.5, 0.8, 2.0, YELLOW), (12.0, 1.7, 2.6, 0.9, MAGENTA), (14.2, 2.1, 1.0, 2.4, ORANGE), (12.0, 2.6, 1.3, 1.3, VIOLET)]
for x, y, w, h, color in packed:
    box(axes, x, y, w, h, color)
box(axes, 12.0, 0.5, 4.6, 4.0, "none", fill=False, lw=1.6)
axes.text(14.3, 4.9, "bounding box", ha="center", fontsize=10, color=INK2)
dot(axes, 14.1, 2.3, RED, 0.22)
dot(axes, 14.3, 2.5, INK, 0.22)
axes.text(16.9, 2.2, "COM (red)\nbox center (black)", fontsize=9, color=INK2, va="center")
text_block(figure, 0.62, 0.78, ["Two modes", "   open: minimize the bounding box", "   container: fill a fixed box (e.g. 100 mm cube)", "", "What we measure per packing", "   density = parts volume / box volume", "   aspect ratio = longest / shortest side", "   COM to box center, % of diagonal", "   inertia tensor and principal moments", "   placement order (assemblability later)", "   minimum gap, must be ≥ t = 0.5 mm", "   valid = no overlap (voxel check, exact spot checks)"], size=12, spacing=0.05)
finish(figure)

# ---------------------------------------------------------------- 3. test procedure
figure = new_slide("The test procedure", "Monte Carlo: same random part sets for every algorithm, then average")
axes = sketch_axes(figure, [0.04, 0.12, 0.60, 0.70])
axes.set_xlim(0, 20)
axes.set_ylim(0, 10)
steps = [(0.5, "for each category (6)"), (3.0, "for each algorithm (10)"), (5.5, "for each trial, n = 100 or 1000"), (8.0, "pick k = 10 random parts (seed = trial)"), (10.5, "pack, measure, write one CSV row"), (13.0, "average per (category, algorithm)")]
for number, (x, text) in enumerate(steps):
    y = 8.5 - number * 1.5
    box(axes, x, y - 0.5, 6.2, 1.0, FILL if number < 3 else "#dff5ec", lw=0.8)
    axes.text(x + 0.2, y, text, fontsize=10.5, va="center", color=INK)
    if number < len(steps) - 1:
        arrow(axes, (x + 1.2, y - 0.5), (x + 2.5, y - 1.0), lw=1.2)
axes.text(0.5, 0.0, "score = mean density, with invalid (overlapping) packings counted as 0", fontsize=10.5, color=INK2)
text_block(figure, 0.67, 0.78, ["Fairness", "   trial t uses seed t for the part draw,", "   so every algorithm packs the same sets", "", "Randomized algorithms", "   3 restarts, best valid kept", "", "Cost", "   6 × 10 × 100 = 6,000 packings per run", "   n = 1000 for the six original methods:", "   36,000 packings"], size=12, spacing=0.05)
finish(figure)

# ---------------------------------------------------------------- 4. datasets
figure = new_slide("The parts: six categories, 123 watertight STLs", "Longest side 15 to 45 mm, centered; every part checked watertight, one body, positive volume")
descriptions = {"cuboids": "20 random boxes, 8 to 45 mm", "simple_convex": "20: prisms, pyramids, cylinders, cones, wedges", "complex_convex": "20: random hulls, ellipsoids, capsules, clipped boxes", "simple_concave": "20: L, T, U, I, cross, tube, step, plate with hole", "complex_concave": "20: unions of 3 to 7 primitives, 0 to 2 holes", "real_shapes": "23: bunny, dragon, teapot, armadillo ... (remeshed)"}
for number, dataset_name in enumerate(DATASET_ORDER):
    column = number % 3
    row = number // 3
    image_path = os.path.join("slide_images", "dataset_" + dataset_name + ".png")
    axes = figure.add_axes([0.05 + column * 0.31, 0.50 - row * 0.36, 0.28, 0.27])
    axes.axis("off")
    if os.path.exists(image_path):
        axes.imshow(plt.imread(image_path))
    axes.set_title(pretty(dataset_name), fontsize=13, color=INK, loc="left", pad=4)
    figure.text(0.05 + column * 0.31, 0.49 - row * 0.36, descriptions[dataset_name], fontsize=9.5, color=INK2)
finish(figure)

# ---------------------------------------------------------------- 5. shared rules
figure = new_slide("Rules every algorithm follows", "So the comparison tests the placement logic, not the bookkeeping")
axes = sketch_axes(figure, [0.04, 0.12, 0.45, 0.70])
axes.set_xlim(0, 14)
axes.set_ylim(0, 10)
axes.add_patch(Polygon([(1.0, 1.5), (4.5, 3.0), (3.5, 6.0), (0.5, 4.5)], closed=True, facecolor=AQUA, edgecolor=INK, alpha=0.8))
axes.add_patch(Polygon([(0.3, 1.2), (5.0, 2.8), (3.9, 6.5), (-0.1, 4.8)], closed=True, facecolor="none", edgecolor=INK2, linestyle="--"))
axes.text(2.3, 7.0, "tightest oriented box", ha="center", fontsize=10, color=INK2)
arrow(axes, (5.6, 4.0), (7.0, 4.0), lw=2.0)
box(axes, 7.8, 2.0, 4.0, 3.0, AQUA)
box(axes, 7.5, 1.7, 4.6, 3.6, "none", fill=False, lw=1.0, ls="--")
axes.text(9.8, 6.0, "aligned to x, y, z\n+ t/2 padding on each side", ha="center", fontsize=10, color=INK2)
axes.text(9.8, 0.9, "then try its 6 face-down orientations", ha="center", fontsize=10, color=INK2)
text_block(figure, 0.53, 0.78, ["Orientation", "   first align the part's minimum-volume", "   oriented box to the axes, then try the 6", "   ways to set that box down (24 optional)", "   random methods use any angle", "", "Clearance t = 0.5 mm", "   boxes are padded by t, voxels grown by t/2,", "   so no two parts come closer than t", "", "Order", "   largest box first, unless the algorithm", "   searches over the order itself"], size=12, spacing=0.05)
finish(figure)

# ---------------------------------------------------------------- 6. families
figure = new_slide("Ten algorithms in three families", "Boxes are fast but blind to shape; shapes can interlock; search improves any of them")
axes = sketch_axes(figure, [0.04, 0.10, 0.92, 0.72])
axes.set_xlim(0, 30)
axes.set_ylim(0, 10)
families = [("baseline", "random rejection", 0.5, INK3, ["random_rejection"]), ("box based", "each part is its padded box", 6.0, BLUE, ["shelf_packing", "box_bottom_left", "box_extreme_points", "force_based", "force_based_v2"]), ("shape based", "the real shape on a grid", 15.5, AQUA, ["voxel_bottom_left", "heightfield_drop"]), ("search based", "optimize order + orientation", 22.5, ORANGE, ["simulated_annealing", "genetic_algorithm"])]
for title, caption, x, color, members in families:
    width = 4.5 if title == "baseline" else (8.5 if title == "box based" else 6.5)
    box(axes, x, 1.0, width, 8.0, "none", fill=False, lw=1.5)
    axes.add_patch(Rectangle((x, 8.2), width, 0.8, facecolor=color, edgecolor="none"))
    axes.text(x + 0.3, 8.6, title, fontsize=13, weight="bold", color="white", va="center")
    axes.text(x + 0.3, 7.6, caption, fontsize=10, color=INK2, va="center")
    for number, member in enumerate(members):
        axes.text(x + 0.5, 6.5 - number * 1.0, "•  " + pretty(member) + ("   (new)" if member in NEW_ALGORITHMS else ""), fontsize=11, color=INK, va="center")
finish(figure)


# ---------------------------------------------------------------- algorithm slides
def algorithm_slide(name, how, strength, weakness, draw, numbers):
    figure = new_slide(pretty(name), FAMILY[name] + " family" + ("   ·   new today" if name in NEW_ALGORITHMS else ""))
    axes = sketch_axes(figure, [0.04, 0.12, 0.50, 0.70])
    axes.set_xlim(0, 14)
    axes.set_ylim(0, 10)
    draw(axes)
    figure.text(0.57, 0.80, "How", fontsize=12, weight="bold", color=FAMILY_COLOR[FAMILY[name]], va="top")
    text_block(figure, 0.57, 0.765, how, size=11, spacing=0.042)
    y_after_how = 0.765 - len(how) * 0.042 - 0.03
    figure.text(0.57, y_after_how, "Strength", fontsize=12, weight="bold", color=GREEN, va="top")
    text_block(figure, 0.57, y_after_how - 0.035, strength, size=11, spacing=0.042)
    y_after_strength = y_after_how - 0.035 - len(strength) * 0.042 - 0.03
    figure.text(0.57, y_after_strength, "Weakness", fontsize=12, weight="bold", color=RED, va="top")
    text_block(figure, 0.57, y_after_strength - 0.035, weakness, size=11, spacing=0.042)
    if numbers is not None:
        figure.text(0.57, 0.115, numbers, fontsize=10, color=INK2, va="bottom")
    finish(figure)


six = read_summary(arguments.six)
four = read_summary(arguments.four)
n100 = dict(six)
n100.update(four)


def numbers_line(name):
    pieces = []
    for dataset_name in ["cuboids", "simple_concave", "real_shapes"]:
        row = n100.get((dataset_name, name))
        if row is not None:
            pieces.append(pretty(dataset_name) + " " + format(row["score"], ".2f"))
    if len(pieces) == 0:
        return None
    row = n100.get(("real_shapes", name))
    return "n = 100, k = 10 density:  " + "   ".join(pieces) + "   ·   " + format(row["seconds_mean"], ".2f") + " s per packing"


def draw_random_rejection(axes):
    box(axes, 0.5, 0.5, 9.0, 9.0, "none", fill=False, lw=1.2, ls="--")
    axes.text(5.0, 9.8, "region (grows 10% when stuck)", ha="center", fontsize=9.5, color=INK2)
    rng = np.random.default_rng(4)
    placed = [(1.0, 1.0, 2.5, 1.5, 20), (5.5, 1.2, 1.5, 2.6, -15), (1.5, 5.0, 2.0, 2.0, 40), (6.0, 6.0, 2.8, 1.2, 5)]
    for x, y, w, h, angle in placed:
        axes.add_patch(Rectangle((x, y), w, h, angle=angle, facecolor=BLUE, edgecolor=INK, alpha=0.8))
    axes.add_patch(Rectangle((4.0, 4.0), 2.4, 1.6, angle=30, facecolor=AQUA, edgecolor=INK, alpha=0.8))
    axes.text(6.9, 4.4, "accepted:\nclear of every\nplaced box by t", fontsize=9.5, color=INK2, va="center")
    axes.add_patch(Rectangle((2.2, 1.8), 2.0, 1.4, angle=-20, facecolor=RED, edgecolor=INK, alpha=0.45))
    axes.text(4.4, 1.5, "rejected (hits)", fontsize=9.5, color=RED, va="center")
    axes.text(10.0, 7.5, "random angle\nrandom position\n300 tries per part", fontsize=10, color=INK)


def draw_shelf(axes):
    row1 = [(0.5, 3.0, 2.4), (3.6, 2.2, 2.0), (5.9, 2.0, 1.6), (8.0, 1.5, 1.2)]
    for x, w, h in row1:
        box(axes, x, 0.5, w, h, BLUE)
    row2 = [(0.5, 2.6, 1.6), (3.2, 2.2, 1.3), (5.5, 1.8, 1.0)]
    for x, w, h in row2:
        box(axes, x, 3.2, w, h, BLUE, alpha=0.6)
    box(axes, 0.5, 5.3, 2.0, 1.0, BLUE, alpha=0.4)
    arrow(axes, (0.5, 2.95), (9.8, 2.95), lw=1.4)
    axes.text(10.0, 2.95, "row along x", fontsize=9.5, va="center", color=INK2)
    arrow(axes, (10.3, 0.5), (10.3, 4.8), lw=1.4)
    axes.text(10.6, 4.4, "next row along y\n(sketch: y drawn up)", fontsize=9.5, color=INK2)
    axes.text(0.5, 7.3, "tallest first, laid flat (shortest side up)\nrow height = tallest part in the row\nnew layer in z when the floor is full", fontsize=10, color=INK)
    axes.text(0.5, 6.4, "wasted", fontsize=9, color=RED)
    axes.add_patch(Rectangle((2.5, 5.3), 7.0, 1.0, facecolor=RED, alpha=0.12, edgecolor="none"))


def draw_bottom_left(axes):
    placed = [(0.5, 0.5, 4.0, 3.0), (4.5, 0.5, 2.5, 2.0), (0.5, 3.5, 2.5, 2.0)]
    for x, y, w, h in placed:
        box(axes, x, y, w, h, BLUE)
    x_values = [0.5, 3.0, 4.5, 7.0]
    y_values = [0.5, 2.5, 3.5, 5.5]
    for x in x_values:
        for y in y_values:
            dot(axes, x, y, INK3, 0.13)
    dot(axes, 3.0, 3.5, ORANGE, 0.2)
    box(axes, 3.0, 3.5, 3.0, 1.6, ORANGE, alpha=0.6)
    axes.text(6.3, 4.3, "lowest free spot\nthen frontmost\nthen leftmost", fontsize=9.5, color=INK2, va="center")
    axes.text(0.5, 7.6, "candidates = every combination of\nplaced box edges (grey dots)\nsquare floor ≈ cube root of total volume", fontsize=10, color=INK)
    box(axes, 0.5, 0.5, 8.0, 8.0, "none", fill=False, lw=1.0, ls="--")
    axes.text(8.7, 0.5, "floor", fontsize=9, color=INK2)


def draw_extreme_points(axes):
    placed = [(0.5, 0.5, 4.0, 3.0), (4.5, 0.5, 2.5, 2.0), (0.5, 3.5, 2.5, 2.0)]
    for x, y, w, h in placed:
        box(axes, x, y, w, h, BLUE)
    points = [(4.5, 3.5), (7.0, 0.5), (4.5, 2.5), (3.0, 3.5), (0.5, 5.5), (3.0, 0.5)]
    for x, y in points:
        dot(axes, x, y, INK3, 0.16)
    dot(axes, 3.0, 3.5, ORANGE, 0.22)
    box(axes, 3.0, 3.5, 3.0, 1.6, ORANGE, alpha=0.6)
    box(axes, 0.5, 0.5, 6.5, 4.6, "none", fill=False, lw=1.4)
    axes.text(0.5, 7.6, "candidates = only the 3 corners each\nplaced box exposes (+x, +y, +z)\npick spot + orientation that keeps the\noverall box (solid line) smallest", fontsize=10, color=INK)
    axes.text(7.3, 3.5, "fewer candidates\nthan bottom-left,\nbetter objective", fontsize=9.5, color=INK2, va="center")


def draw_voxel(axes):
    for i in range(10):
        for j in range(8):
            axes.add_patch(Rectangle((0.5 + i * 0.8, 0.5 + j * 0.8), 0.8, 0.8, facecolor="none", edgecolor=LIGHT, linewidth=0.6))
    l_cells = [(0, 0), (1, 0), (2, 0), (3, 0), (4, 0), (0, 1), (0, 2), (0, 3), (1, 1), (1, 2), (1, 3), (2, 1), (3, 1), (4, 1)]
    for i, j in l_cells:
        axes.add_patch(Rectangle((0.5 + i * 0.8, 0.5 + j * 0.8), 0.8, 0.8, facecolor=AQUA, edgecolor="white", linewidth=0.6))
    nested = [(2, 2), (3, 2), (4, 2), (2, 3), (3, 3), (4, 3), (2, 4), (3, 4), (4, 4)]
    for i, j in nested:
        axes.add_patch(Rectangle((0.5 + i * 0.8, 0.5 + j * 0.8), 0.8, 0.8, facecolor=ORANGE, edgecolor="white", linewidth=0.6))
    axes.text(0.5, 7.6, "parts voxelized at 2 mm in their real shape,\ngrown by t/2; the orange part sits inside\nthe L's notch (boxes could not do this)", fontsize=10, color=INK)
    axes.text(8.9, 3.0, "FFT convolution of\ngrid ⊗ part = overlap\ncount at every position;\nzero = free spot", fontsize=9.5, color=INK2, va="center")
    axes.text(8.9, 0.8, "keep the free spot that\nkeeps the box smallest", fontsize=9.5, color=INK2, va="center")


def draw_force(axes):
    boxes = [(2.0, 2.0, 3.0, 2.0), (3.8, 3.0, 2.5, 2.5), (5.5, 1.5, 2.0, 3.0), (1.0, 4.5, 2.5, 1.5)]
    for x, y, w, h in boxes:
        box(axes, x, y, w, h, BLUE, alpha=0.45)
    dot(axes, 4.2, 3.3, INK, 0.18)
    axes.text(4.4, 3.0, "centroid", fontsize=9, color=INK2)
    arrow(axes, (6.8, 5.5), (5.2, 4.2), color=INK2, lw=1.2)
    arrow(axes, (0.8, 1.0), (2.6, 2.4), color=INK2, lw=1.2)
    arrow(axes, (4.4, 4.6), (4.4, 6.2), color=RED, lw=2.0)
    arrow(axes, (4.0, 2.8), (4.0, 1.2), color=RED, lw=2.0)
    axes.text(0.5, 8.6, "repeat 40×:  squeeze all boxes 10% toward the centroid (grey)\nthen push each overlapping pair apart along its shallowest\noverlap (red), up to 60 passes; keep the tightest overlap-free state", fontsize=10, color=INK, va="top")
    axes.text(8.5, 2.5, "no placement order:\nall parts move at once", fontsize=9.5, color=INK2, va="center")


def draw_force_v2(axes):
    box(axes, 1.0, 0.3, 5.0, 5.0, "none", fill=False, lw=1.4, ls="--")
    axes.text(3.5, 5.6, "target cube", ha="center", fontsize=9.5, color=INK2)
    boxes = [(0.2, 0.8, 3.0, 1.6), (3.0, 1.3, 2.4, 2.2), (5.6, 0.5, 1.8, 2.6), (1.5, 3.2, 2.2, 1.4)]
    for x, y, w, h in boxes:
        box(axes, x, y, w, h, BLUE, alpha=0.5)
    arrow(axes, (8.2, 2.3), (6.5, 2.3), color=RED, lw=2.4)
    arrow(axes, (-0.6, 2.3), (0.9, 2.3), color=RED, lw=2.4)
    axes.text(0.0, 9.6, "1  anisotropic squeeze: an axis wider than the target is pulled\n    in harder (big red arrows), so rows cannot form\n2  compaction: every box slides toward the origin along z, y, x\n    as far as the others allow\n3  each box re-picks the orientation that overlaps least", fontsize=10, color=INK, va="top")
    arrow(axes, (9.5, 4.5), (9.5, 2.2), color=INK2, lw=1.2)
    arrow(axes, (11.5, 2.2), (10.0, 2.2), color=INK2, lw=1.2)
    box(axes, 9.5, 2.2, 1.5, 1.2, BLUE, alpha=0.5)
    axes.text(9.4, 1.4, "compaction", fontsize=9, color=INK2)


def draw_heightfield(axes):
    stack = [1.0, 1.0, 3.0, 3.0, 3.0, 2.0, 2.0, 4.0, 4.0, 1.5, 1.5, 1.5]
    for i, height in enumerate(stack):
        axes.add_patch(Rectangle((0.5 + i * 0.8, 0.5), 0.8, height, facecolor=BLUE, edgecolor="white", linewidth=0.6, alpha=0.8))
    bottom = [0.0, 0.0, 1.0, 1.0, 0.0]
    top = [2.0, 2.0, 2.0, 2.0, 2.0]
    landing = max(stack[2 + i] - bottom[i] for i in range(5)) + 0.5
    for i in range(5):
        axes.add_patch(Rectangle((0.5 + (2 + i) * 0.8, landing + bottom[i]), 0.8, top[i] - bottom[i], facecolor=ORANGE, edgecolor="white", linewidth=0.6, alpha=0.9))
        axes.add_patch(Rectangle((0.5 + (2 + i) * 0.8, landing + bottom[i] + 3.0), 0.8, top[i] - bottom[i], facecolor=ORANGE, edgecolor="white", linewidth=0.6, alpha=0.3))
    arrow(axes, (4.1, landing + 2.9), (4.1, landing + 2.2), color=INK, lw=1.6)
    axes.text(0.5, 9.9, "side view: the stack is a height map (blue tops); the part has a bottom\nprofile and a top profile per column (orange); it rests on its first two columns", fontsize=10, color=INK, va="top")
    axes.text(7.8, 7.2, "landing height =\nmax over its columns of\n(stack top − part bottom)", fontsize=10, color=INK, va="top")
    axes.text(10.4, 3.0, "tried at every (x, y)\nand every orientation;\nkeep the spot that\nkeeps the box smallest", fontsize=9.5, color=INK2, va="center")


def draw_annealing(axes):
    order = ["D", "A", "F", "B", "E", "C"]
    for i, name in enumerate(order):
        box(axes, 0.5 + i * 1.4, 7.0, 1.2, 1.2, FILL, lw=0.8)
        axes.text(1.1 + i * 1.4, 7.6, name, ha="center", va="center", fontsize=12, color=INK)
        axes.text(1.1 + i * 1.4, 6.6, "o" + str([2, 0, 5, 1, 3, 0][i]), ha="center", va="center", fontsize=8, color=INK2)
    arrow(axes, (2.5, 8.4), (6.7, 8.4), color=ORANGE, lw=2.0, style="<|-|>")
    axes.text(4.6, 8.9, "swap two parts, or change one orientation", ha="center", fontsize=9.5, color=ORANGE)
    arrow(axes, (4.6, 6.2), (4.6, 5.2), lw=1.4)
    axes.text(5.0, 5.7, "decode: voxel packer with the orientations fixed", fontsize=9.5, color=INK2, va="center")
    chart = axes.inset_axes([0.05, 0.05, 0.55, 0.42])
    steps = np.arange(0, 100)
    temperature = 0.05 * (0.001 / 0.05) ** (steps / 100)
    chart.plot(steps, temperature, color=ORANGE, linewidth=2)
    chart.set_yscale("log")
    chart.set_xlabel("time within the 5 s budget (%)", fontsize=8)
    chart.set_ylabel("temperature", fontsize=8)
    chart.tick_params(labelsize=7)
    chart.set_title("accept a worse packing with probability exp(Δdensity / T)", fontsize=8.5, loc="left")
    axes.text(9.0, 2.5, "about 100 decodes\nper packing at 5 s", fontsize=9.5, color=INK2, va="center")


def draw_genetic(axes):
    parent_a = ["A", "B", "C", "D", "E", "F"]
    parent_b = ["F", "D", "B", "A", "E", "C"]
    child = ["F", "D", "C", "D", "E", "A"]
    child = ["F", "B", "C", "D", "E", "A"]
    for i, name in enumerate(parent_a):
        box(axes, 0.5 + i * 1.1, 8.0, 1.0, 1.0, ORANGE if 2 <= i <= 4 else FILL, lw=0.8, alpha=0.7 if 2 <= i <= 4 else 1.0)
        axes.text(1.0 + i * 1.1, 8.5, name, ha="center", va="center", fontsize=11)
    axes.text(7.4, 8.5, "parent 1 (slice kept in place)", fontsize=9.5, color=INK2, va="center")
    for i, name in enumerate(parent_b):
        box(axes, 0.5 + i * 1.1, 6.3, 1.0, 1.0, FILL, lw=0.8)
        axes.text(1.0 + i * 1.1, 6.8, name, ha="center", va="center", fontsize=11)
    axes.text(7.4, 6.8, "parent 2 (fills the rest, in its order)", fontsize=9.5, color=INK2, va="center")
    arrow(axes, (3.8, 6.0), (3.8, 5.2), lw=1.4)
    for i, name in enumerate(child):
        box(axes, 0.5 + i * 1.1, 4.0, 1.0, 1.0, ORANGE if 2 <= i <= 4 else "#dff5ec", lw=0.8, alpha=0.7 if 2 <= i <= 4 else 1.0)
        axes.text(1.0 + i * 1.1, 4.5, name, ha="center", va="center", fontsize=11)
    axes.text(7.4, 4.5, "child, then one mutation", fontsize=9.5, color=INK2, va="center")
    axes.text(0.5, 2.8, "population 12; each generation keeps the best 6 and breeds 6 children\norientations come from either parent per part\ndecode and score every child (voxel packer); run for 5 s", fontsize=10, color=INK, va="top")


algorithm_slide("random_rejection", ["each part: random angle, random position inside a cube", "reject if its box comes within t of any placed box", "300 tries, then grow the cube 10% and try again", "3 restarts, best kept"], ["the floor every real method must beat", "any orientation, no assumptions"], ["no packing logic at all", "density 0.09 to 0.19; gaps 2 to 3 mm"], draw_random_rejection, numbers_line("random_rejection"))
algorithm_slide("shelf_packing", ["lay every part flat: shortest side up, longest along x", "tallest first; fill a row along x, then the next row in y,", "then a new layer in z when the square floor is full"], ["fastest method (0.03 s per packing)", "predictable layers; good for flat parts"], ["a tall part sets the whole layer height", "space above shorter parts is wasted"], draw_shelf, numbers_line("shelf_packing"))
algorithm_slide("box_bottom_left", ["largest box first", "candidate corners: every combination of placed box", "edges (x, y, z maxima and 0) on a square floor", "take the lowest, then frontmost, then leftmost free", "corner over the 6 orientations"], ["near-cubic packings (aspect 1.1 to 1.3)", "simple, deterministic, 0.05 s"], ["fixed floor size limits the layout", "boxes only: cannot use a concave part's notch"], draw_bottom_left, numbers_line("box_bottom_left"))
algorithm_slide("box_extreme_points", ["largest box first", "candidates: only the 3 corners each placed box exposes", "choose the corner and orientation that keep the overall", "bounding box smallest (container mode: lowest corner)"], ["densest box method on cuboids (0.78)", "few candidates, so fast (0.04 s)"], ["greedy volume objective builds slabs", "(aspect 4 to 6); boxes only"], draw_extreme_points, numbers_line("box_extreme_points"))
algorithm_slide("force_based", ["every box starts at a random spot, overlapping", "repeat 40×: squeeze 10% toward the centroid, then push", "overlapping pairs apart along the shallowest overlap", "keep the tightest overlap-free state (3 restarts)"], ["no placement order; all parts move at once", "constraints can be added as extra forces"], ["isotropic squeeze forms long rows (Izz/Ixx ≈ 10)", "barely above random on concave parts"], draw_force, numbers_line("force_based"))
algorithm_slide("force_based_v2", ["as force_based, plus:", "anisotropic squeeze toward a target cube", "compaction: slide each box to the origin along z, y, x", "re-pick each box's orientation to the one that", "overlaps least where it sits"], ["density 10 to 25% above v1, rows gone (Izz/Ixx 3 to 6 vs 8 to 12)", "keeps the order-free, force-based structure"], ["still boxes, still below the greedy methods", "still elongated (aspect 2.5 to 4); 0.4 s per packing"], draw_force_v2, numbers_line("force_based_v2"))
algorithm_slide("voxel_bottom_left", ["each part voxelized at 2 mm in its real shape, grown by t/2", "for each orientation, an FFT convolution of the grid with", "the part gives the overlap count at every position at once", "keep the free position that keeps the box smallest"], ["concave parts can interlock", "best on real shapes and simple convex"], ["2 mm grid + 0.5 mm clearance eat most of the", "interlock gain; 5 to 10× slower than box methods"], draw_voxel, numbers_line("voxel_bottom_left"))
algorithm_slide("heightfield_drop", ["Huai-Yi's method, rebuilt on the benchmark's grid", "the stack is a 2D height map; each part has a bottom", "and a top profile per column", "drop at every (x, y) and orientation: landing height =", "max over its columns of (stack top − part bottom)", "keep the landing that keeps the box smallest"], ["overlap-free by construction (exact check: 0 mm³)", "no 3D search: 0.04 to 0.08 s per packing, 5× faster than voxel", "within 0.02 of voxel on every category"], ["a column is solid from bottom to top, so nothing", "slides under an overhang (a sideways tube is a block)", "greedy smallest-box choice builds towers (aspect 4 to 6)"], draw_heightfield, numbers_line("heightfield_drop"))
algorithm_slide("simulated_annealing", ["the decision = placement order + one orientation per part", "the voxel packer (orientations fixed) decodes it to a packing", "each step: swap two parts or re-orient one; accept if density", "rises, else with probability exp(Δ / T), T: 0.05 → 0.001", "runs for a fixed 5 s budget (~100 decodes)"], ["+0.01 to +0.03 density over voxel bottom-left on every category", "most compact boxes (aspect 2 to 4) and lowest COM offset", "(3% of the diagonal) of any method"], ["5 s per packing; the result depends on the budget", "and on the CPU, so runs are not bit-reproducible", "100 decodes is a small search for 10! orders"], draw_annealing, numbers_line("simulated_annealing"))
algorithm_slide("genetic_algorithm", ["same decision and decoder as annealing", "population of 12; keep the best 6 each generation", "children: order crossover (a slice of parent 1 stays in", "place, parent 2 fills the rest in its order), orientations", "from either parent, then one mutation; 5 s budget"], ["best density on 5 of 6 categories (tied with extreme", "points on cuboids); parallel-friendly (children are", "independent)"], ["same 5 s cost; only +0.01 over annealing", "same non-reproducibility (time budget)"], draw_genetic, numbers_line("genetic_algorithm"))

# ---------------------------------------------------------------- results
present = [name for name in ALGORITHM_ORDER if all((dataset_name, name) in n100 for dataset_name in DATASET_ORDER)]


def results_bars(title, subtitle, metric, scale, y_label, y_limit=None):
    figure = new_slide(title, subtitle)
    for number, dataset_name in enumerate(DATASET_ORDER):
        axes = figure.add_axes([0.06 + (number % 3) * 0.315, 0.50 - (number // 3) * 0.36, 0.26, 0.27])
        values = [n100[(dataset_name, name)][metric] * scale for name in present]
        colors = [ORANGE if name in NEW_ALGORITHMS else BLUE for name in present]
        axes.bar(range(len(present)), values, color=colors, width=0.7)
        axes.set_title(pretty(dataset_name), fontsize=11, loc="left", color=INK)
        axes.set_xticks(range(len(present)))
        axes.set_xticklabels([SHORT[name] for name in present], fontsize=7)
        axes.tick_params(axis="y", labelsize=8)
        axes.grid(axis="y", color=LIGHT, linewidth=0.6)
        axes.set_axisbelow(True)
        for spine in ("top", "right"):
            axes.spines[spine].set_visible(False)
        if y_limit is not None:
            axes.set_ylim(0, y_limit)
        if number % 3 == 0:
            axes.set_ylabel(y_label, fontsize=9)
        best = int(np.argmax(values)) if metric == "score" else int(np.argmin(values))
        axes.text(best, values[best], format(values[best], ".2f"), ha="center", va="bottom", fontsize=8, color=INK)
    figure.text(0.72, 0.825, "■ existing", fontsize=10, color=BLUE)
    figure.text(0.82, 0.825, "■ new today", fontsize=10, color=ORANGE)
    finish(figure)


results_bars("Results: density by category", "n = 100 trials, k = 10 parts, open mode, t = 0.5 mm; invalid packings count as 0", "score", 1.0, "density (parts volume / box volume)", 1.0)
results_bars("Results: aspect ratio (lower = more compact)", "the densest packers make slabs; bottom-left and force v2 stay near-cubic", "aspect_ratio_mean", 1.0, "longest / shortest box side")
results_bars("Results: center of mass offset (lower = better balanced)", "distance from COM to box center as % of the box diagonal; no algorithm optimizes this yet", "com_offset_normalized_mean", 100.0, "COM offset, % of diagonal")

# density vs aspect ratio scatter
figure = new_slide("The trade-off: density costs shape", "each point is one algorithm on one category (n = 100); up-left is the goal")
axes = figure.add_axes([0.08, 0.14, 0.60, 0.68])
for name in present:
    xs = [n100[(dataset_name, name)]["aspect_ratio_mean"] for dataset_name in DATASET_ORDER]
    ys = [n100[(dataset_name, name)]["score"] for dataset_name in DATASET_ORDER]
    axes.scatter(xs, ys, s=70, color=FAMILY_COLOR[FAMILY[name]], edgecolor="white", linewidth=0.8, label=pretty(name), zorder=3, marker="o" if name not in NEW_ALGORITHMS else "D")
    axes.annotate(pretty(name), (np.mean(xs), np.mean(ys)), fontsize=7.5, color=INK2, xytext=(4, 4), textcoords="offset points")
axes.set_xlabel("aspect ratio (longest / shortest box side)")
axes.set_ylabel("density")
axes.grid(color=LIGHT, linewidth=0.6)
axes.set_axisbelow(True)
for spine in ("top", "right"):
    axes.spines[spine].set_visible(False)
text_block(figure, 0.72, 0.78, ["color = family", "   grey baseline", "   blue box based", "   aqua shape based", "   orange search based", "diamond = new today", "", "Greedy 'smallest box' choices", "stack parts into towers and", "slabs. A satellite wants a", "compact envelope, so the", "objective needs an aspect", "or target-box term."], size=11, spacing=0.045)
finish(figure)

# speed
figure = new_slide("Results: cost per packing", "seconds per packing on the benchmark machine (2 cores), log scale; search methods are fixed at a 5 s budget")
axes = figure.add_axes([0.08, 0.16, 0.85, 0.65])
seconds = [np.mean([n100[(dataset_name, name)]["seconds_mean"] for dataset_name in DATASET_ORDER]) for name in present]
colors = [ORANGE if name in NEW_ALGORITHMS else BLUE for name in present]
axes.bar(range(len(present)), seconds, color=colors, width=0.7)
axes.set_yscale("log")
axes.set_xticks(range(len(present)))
axes.set_xticklabels([SHORT[name].replace("\n", " ") for name in present], fontsize=10)
axes.set_ylabel("seconds per packing (mean over categories)")
axes.grid(axis="y", color=LIGHT, linewidth=0.6)
axes.set_axisbelow(True)
for spine in ("top", "right"):
    axes.spines[spine].set_visible(False)
for number, value in enumerate(seconds):
    axes.text(number, value, format(value, ".2f") + " s", ha="center", va="bottom", fontsize=8.5, color=INK)
finish(figure)

# n = 1000 confirmation
n1000 = read_summary(arguments.n1000)
if len(n1000) > 0:
    figure = new_slide("Confirmation at n = 1000", "the six original methods, 36,000 packings; error bars = standard error of the mean density; same ranking as at n = 100")
    names_1000 = [name for name in ["random_rejection", "shelf_packing", "box_bottom_left", "box_extreme_points", "voxel_bottom_left", "force_based"] if all((dataset_name, name) in n1000 for dataset_name in DATASET_ORDER)]
    axes = figure.add_axes([0.08, 0.16, 0.85, 0.64])
    width = 0.8 / len(names_1000)
    colors_1000 = [INK3, BLUE, AQUA, YELLOW, ORANGE, MAGENTA]
    for number, name in enumerate(names_1000):
        means = [n1000[(dataset_name, name)]["score"] for dataset_name in DATASET_ORDER]
        errors = [n1000[(dataset_name, name)]["density_std"] / np.sqrt(n1000[(dataset_name, name)]["trials"]) for dataset_name in DATASET_ORDER]
        positions = np.arange(len(DATASET_ORDER)) + (number - (len(names_1000) - 1) / 2.0) * width
        axes.bar(positions, means, width * 0.92, color=colors_1000[number], label=pretty(name), yerr=errors, capsize=2, error_kw={"linewidth": 0.8, "color": INK2})
    axes.set_xticks(range(len(DATASET_ORDER)))
    axes.set_xticklabels([pretty(name) for name in DATASET_ORDER], fontsize=10)
    axes.set_ylabel("density")
    axes.legend(frameon=False, fontsize=9)
    axes.grid(axis="y", color=LIGHT, linewidth=0.6)
    axes.set_axisbelow(True)
    for spine in ("top", "right"):
        axes.spines[spine].set_visible(False)
    finish(figure)

# k sweep
sweep = {}
for path in arguments.sweep:
    rows = read_summary(path)
    if len(rows) == 0:
        continue
    with open(path) as sweep_file:
        header = sweep_file.readline()
    k_value = None
    trials_path = path.replace("summary_", "trials_")
    if os.path.exists(trials_path):
        with open(trials_path) as trials_file:
            reader = csv.DictReader(trials_file)
            first = next(reader)
            k_value = len(first["parts"].split(";"))
    if k_value is None:
        continue
    sweep[k_value] = rows
if len(six) > 0:
    sweep[10] = six
k_values = sorted(k for k in sweep if k != 10 or True)
if len(sweep) >= 3:
    figure = new_slide("Results: density versus part count k", "n = 100 per point, the same four methods: density barely depends on k from 5 to 30, so the greedy rules do not improve with more parts")
    names_sweep = ["shelf_packing", "box_bottom_left", "box_extreme_points", "voxel_bottom_left"]
    colors_sweep = [BLUE, AQUA, YELLOW, ORANGE]
    for number, dataset_name in enumerate(DATASET_ORDER):
        axes = figure.add_axes([0.06 + (number % 3) * 0.315, 0.50 - (number // 3) * 0.36, 0.26, 0.27])
        for color, name in zip(colors_sweep, names_sweep):
            ks = [k for k in k_values if (dataset_name, name) in sweep[k]]
            values = [sweep[k][(dataset_name, name)]["score"] for k in ks]
            axes.plot(ks, values, color=color, linewidth=2, marker="o", markersize=4, label=pretty(name))
        axes.set_title(pretty(dataset_name), fontsize=11, loc="left", color=INK)
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
        if number == 2:
            axes.legend(frameon=False, fontsize=7.5, loc="lower right")
    finish(figure)

# container mode
container = {}
for path in arguments.container:
    container.update(read_summary(path))
if len(container) > 0:
    names_container = [name for name in ALGORITHM_ORDER if all((dataset_name, name) in container for dataset_name in DATASET_ORDER)]
    figure = new_slide("Results: container mode, 100 mm cube, k = 30", "share of the 30 parts that fit, n = 100; search methods not run here (5 s each); the force methods drop parts that still collide")
    for number, dataset_name in enumerate(DATASET_ORDER):
        axes = figure.add_axes([0.06 + (number % 3) * 0.315, 0.50 - (number // 3) * 0.36, 0.26, 0.27])
        values = [container[(dataset_name, name)]["placed_fraction_mean"] for name in names_container]
        colors = [ORANGE if name in NEW_ALGORITHMS else BLUE for name in names_container]
        axes.bar(range(len(names_container)), values, color=colors, width=0.7)
        axes.set_title(pretty(dataset_name), fontsize=11, loc="left", color=INK)
        axes.set_xticks(range(len(names_container)))
        axes.set_xticklabels([SHORT[name] for name in names_container], fontsize=7)
        axes.tick_params(axis="y", labelsize=8)
        axes.set_ylim(0, 1.05)
        axes.grid(axis="y", color=LIGHT, linewidth=0.6)
        axes.set_axisbelow(True)
        for spine in ("top", "right"):
            axes.spines[spine].set_visible(False)
        if number % 3 == 0:
            axes.set_ylabel("fraction of parts placed", fontsize=9)
        best = int(np.argmax(values))
        axes.text(best, values[best], format(values[best], ".2f"), ha="center", va="bottom", fontsize=8, color=INK)
    figure.text(0.72, 0.825, "■ existing", fontsize=10, color=BLUE)
    figure.text(0.82, 0.825, "■ new today", fontsize=10, color=ORANGE)
    finish(figure)

# verification
figure = new_slide("Verification", "anything checkable by code is checked by code, never judged by eye")
text_block(figure, 0.06, 0.78, ["Overlap: exact mesh booleans (manifold3d) on sample packings of every algorithm: 0 mm³ intersection", "   the fast voxel check flags 7 of 1,000 shape-based packings at 0.5 to 0.7% (threshold 0.5%); all 7 re-checked exactly: 0 mm³", "", "Clearance: the minimum gap is measured from dense surface samples (0.5 mm spacing) and checked against a", "   brute-force KD-tree on 54 packings: identical. Every packer keeps ≥ t = 0.5 mm in every trial", "", "Inertia: the tensor code reproduces the closed-form tensor of a solid box exactly", "", "Reproducibility: trial t draws its parts with seed t, so every algorithm sees the same sets; the search methods", "   are time-budgeted, so their numbers move by about ±0.01 between machines; a clean venv with only requirements.txt runs everything", "", "Known limits: the voxel grid only guarantees clearance along x, y, z (diagonal gaps can be slightly under t);", "   box methods cannot use concave space; no assemblability (insertion path) check yet; COM and inertia are", "   reported but not optimized"], size=11.5, spacing=0.046)
finish(figure)

# takeaways
figure = new_slide("Takeaways and next steps")
text_block(figure, 0.06, 0.78, ["1   Search beats greedy: the genetic algorithm is the densest method on 5 of 6 categories (annealing is 0.01 behind),", "     +0.02 to +0.05 over voxel bottom-left, and with the most compact boxes and the lowest COM offset of any method", "2   Shape beats boxes on concave and real parts; the 2 mm grid and the 0.5 mm clearance cap the gain", "3   Heightfield drop is the cheap shape-aware option: 0.05 s, overlap-free by construction, within 0.02 of voxel", "4   Density costs shape in the greedy methods: 'smallest box' choices make slabs and towers (aspect 4 to 6);", "     force v2 fixes the rows of v1 (+10 to 25% density) but is still 20 to 30% below the greedy methods", "5   In a 100 mm cube with 30 parts, voxel, heightfield and bottom-left place the most parts; nothing controls COM yet", "", "Next", "     multi-objective score: density, aspect ratio (or target box), COM offset; decide which are limits, which are optimized", "     assembly feasibility: straight-line insertion along ±x, ±y, ±z given the placement order", "     longer search budgets and a parallel decoder for the GA; 1 mm grid and 24 orientations for the shape-based methods", "     connect the viewer to the team GUI so 'pack these parts' shows the algorithms side by side"], size=11.5, spacing=0.046)
finish(figure)

# appendix: large-pool runs (60-part categories, k = 10 / 20 / 30, 13 algorithms, 99% CIs)
if arguments.large_plots is not None and os.path.isdir(arguments.large_plots):
    figure = new_slide("Appendix: 60-part categories, k = 10, 20, 30, 13 algorithms", "n = 300 per bar for the fast methods, n = 100 for the search methods; error bars and bands are 99% confidence intervals of the mean")
    text_block(figure, 0.06, 0.78, ["What changed from the main study", "   part pool: 60 random parts per synthetic category instead of 20 (real shapes unchanged, 23)", "   three more algorithms: empty maximal spaces (box), genetic heightfield (search with the heightfield decoder), best of fast (runs the", "   six fast packers, keeps the densest)", "   two more measures: contacts (part pairs whose surfaces come within t + 0.5 mm) and isolated parts (parts touching nothing)", "   every trial's packing is saved (results/solutions_*.jsonl) and can be reopened with replay.py", "", "Findings", "   1  k = 10: the genetic algorithm leads on 5 of 6 categories but by only +0.01 over best of fast; on cuboids it loses (0.748 vs 0.767)", "   2  k = 20 and 30: the 5 s search budget no longer covers the order space; best of fast, EMS and voxel lead on density everywhere", "   3  the greedy methods' towers get worse with k: aspect ratio 4 to 5 at k = 10, 7 to 9 at k = 20, 10 to 12 at k = 30;", "       genetic heightfield holds aspect ratio about 2 at every k at a 3 to 6% density cost", "   4  empty maximal spaces is the best box method at every k (ties or beats extreme points, same cost)", "   5  contacts: box methods touch 2 to 3 neighbours per part on blocky parts; voxel and heightfield parts sit 1 to 2 mm apart", "       (the 2 mm grid), so they register few contacts within the 1 mm band; the band should scale with the grid pitch", "   6  random rejection and force-based v2 fall apart as k grows (v2: 0.47 at k = 10, 0.29 at k = 20 on cuboids)"], size=11, spacing=0.044)
    finish(figure)
    for file_name, title in [("density_k10.png", "Density, k = 10"), ("density_k20.png", "Density, k = 20"), ("density_k30.png", "Density, k = 30"), ("density_vs_k.png", "Density versus k"), ("aspect_ratio_k20.png", "Aspect ratio, k = 20"), ("com_offset_normalized_k20.png", "Center of mass offset, k = 20"), ("contacts_per_part_k10.png", "Contacts per part, k = 10"), ("isolated_parts_k10.png", "Isolated parts, k = 10"), ("seconds_k30.png", "Cost per packing, k = 30")]:
        path = os.path.join(arguments.large_plots, file_name)
        if not os.path.exists(path):
            continue
        slide_counter[0] = slide_counter[0] + 1
        figure = plt.figure(figsize=(PAGE_WIDTH, PAGE_HEIGHT))
        axes = figure.add_axes([0, 0, 1, 1])
        axes.axis("off")
        axes.imshow(plt.imread(path))
        figure.text(0.95, 0.035, str(slide_counter[0]), fontsize=9, color=INK3, ha="right")
        finish(figure)

pdf.close()
print("wrote " + arguments.output + " with " + str(slide_counter[0]) + " slides")
