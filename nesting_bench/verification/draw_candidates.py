"""
Contact sheet of candidate literature packings for the known-literature verification test. Reads known_solutions.json (made by the solver run).
    python draw_candidates.py candidates.png
"""

import sys
import json
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Circle, Rectangle

known = json.load(open("known_solutions.json"))
COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#6250d6", "#e34948", "#008300", "#8c564b", "#17becf", "#7f7f7f", "#bcbd22", "#4e79a7"]
figure = plt.figure(figsize=(16, 13))
figure.suptitle("Candidate literature packings for the known-literature verification test (pick 2 or 3)", fontsize=16, weight="bold", x=0.05, ha="left")
panels = []


def circles_panel(number, key, title, note):
    axes = figure.add_subplot(3, 3, number)
    points = np.array(known[key]["points"])
    separation = known[key]["separation"]
    radius = separation / 2.0
    scale = 1.0 / (1.0 + 2.0 * radius)
    for index, (x, y) in enumerate(points):
        axes.add_patch(Circle(((x + radius) * scale, (y + radius) * scale), radius * scale, facecolor=COLORS[index % len(COLORS)], edgecolor="black", linewidth=0.8))
    axes.add_patch(Rectangle((0, 0), 1, 1, fill=False, linewidth=1.5))
    axes.set_xlim(-0.02, 1.02)
    axes.set_ylim(-0.02, 1.02)
    axes.set_aspect("equal")
    axes.axis("off")
    axes.set_title(title, fontsize=11, loc="left")
    axes.text(0, -0.08, note, fontsize=8.5, color="#555555", transform=axes.transAxes, va="top")


def spheres_panel(number, key, title, note):
    axes = figure.add_subplot(3, 3, number, projection="3d")
    points = np.array(known[key]["points"])
    separation = known[key]["separation"]
    radius = separation / 2.0
    scale = 1.0 / (1.0 + 2.0 * radius)
    u = np.linspace(0, 2 * np.pi, 18)
    v = np.linspace(0, np.pi, 10)
    for index, center in enumerate(points):
        c = (center + radius) * scale
        r = radius * scale
        xs = c[0] + r * np.outer(np.cos(u), np.sin(v))
        ys = c[1] + r * np.outer(np.sin(u), np.sin(v))
        zs = c[2] + r * np.outer(np.ones_like(u), np.cos(v))
        axes.plot_surface(xs, ys, zs, color=COLORS[index % len(COLORS)], linewidth=0, antialiased=True, shade=True, alpha=0.95)
    for s, e in [((0, 0, 0), (1, 0, 0)), ((0, 0, 0), (0, 1, 0)), ((0, 0, 0), (0, 0, 1)), ((1, 1, 1), (0, 1, 1)), ((1, 1, 1), (1, 0, 1)), ((1, 1, 1), (1, 1, 0)), ((1, 0, 0), (1, 1, 0)), ((1, 0, 0), (1, 0, 1)), ((0, 1, 0), (1, 1, 0)), ((0, 1, 0), (0, 1, 1)), ((0, 0, 1), (1, 0, 1)), ((0, 0, 1), (0, 1, 1))]:
        axes.plot([s[0], e[0]], [s[1], e[1]], [s[2], e[2]], color="black", linewidth=0.8)
    axes.set_box_aspect((1, 1, 1))
    axes.set_axis_off()
    axes.set_title(title, fontsize=11, loc="left")
    axes.text2D(0, -0.02, note, fontsize=8.5, color="#555555", transform=axes.transAxes, va="top")


def voxels_panel(number, key, box, title, note):
    axes = figure.add_subplot(3, 3, number, projection="3d")
    grid = np.zeros(box, dtype=bool)
    colors = np.empty(box, dtype=object)
    for piece, cells in known[key]:
        for x, y, z in cells:
            grid[x, y, z] = True
            colors[x, y, z] = COLORS[piece % len(COLORS)]
    axes.voxels(grid, facecolors=colors, edgecolor="black", linewidth=0.5)
    axes.set_box_aspect((1, 1, 1))
    axes.set_axis_off()
    axes.set_title(title, fontsize=11, loc="left")
    axes.text2D(0, -0.02, note, fontsize=8.5, color="#555555", transform=axes.transAxes, va="top")


def pieces_panel(number, pieces, title, note):
    axes = figure.add_subplot(3, 3, number, projection="3d")
    cursor = 0
    for index, cells in enumerate(pieces):
        cells = np.array(cells)
        extent = cells.max(axis=0) + 1
        grid = np.zeros((cells.max(axis=0)[0] + 1 + cursor, 4, 2), dtype=bool)
        for x, y, z in cells:
            axes.bar3d(x + cursor, y, z, 1, 1, 1, color=COLORS[index % len(COLORS)], edgecolor="black", linewidth=0.4, shade=True)
        cursor = cursor + extent[0] + 1
    axes.set_box_aspect((cursor, 4, 2))
    axes.set_axis_off()
    axes.set_title(title, fontsize=11, loc="left")
    axes.text2D(0, -0.02, note, fontsize=8.5, color="#555555", transform=axes.transAxes, va="top")


circles_panel(1, "circles_17", "A  17 equal circles in a square → 17 cylinders in a box", "Proven optimal (computer-assisted proofs cover n ≤ 30). The famous irregular one.\nTest: 17 identical cylinders, open mode; ceiling = the proven square side.")
circles_panel(2, "circles_10", "B  10 equal circles in a square → 10 cylinders in a box", "Proven optimal; asymmetric pattern, min separation 0.4213 in the unit square.\nSame test as A with fewer parts (k = 10 matches the benchmark).")
circles_panel(3, "circles_5", "C  5 equal circles in a square → 5 cylinders in a box", "Proven optimal: four corners and the center. The easy control case.")
spheres_panel(4, "spheres_8", "D  8 equal spheres in a cube", "Proven optimal (Schaer 1966): one sphere per corner.\nTests whether clearance-aware packers find the corners.")
spheres_panel(5, "spheres_14", "E  14 equal spheres in a cube", "Proven optimal (Joós 2009): 8 corners + 6 face centers (one FCC cell), separation √2/2.\nThe hardest proven sphere case.")
spheres_panel(6, "spheres_9", "F  9 equal spheres in a cube", "Proven optimal (Schaer): 8 corners + center, separation √3/2.")
voxels_panel(7, "soma", (3, 3, 3), "G  Soma cube: 7 polycubes → 3 × 3 × 3", "Exact fit, density 1, 240 solutions. Pieces are concave; only shape-aware packers can solve it.\nDirect 3D Scrabble from the literature.")
voxels_panel(8, "slothouber", (3, 3, 3), "H  Slothouber–Graatsma: 6 blocks 1×2×2 + 3 unit cubes → 3 × 3 × 3", "Exact fit, density 1, unique solution up to symmetry.\nBox pieces only, so box packers can in principle solve it.")
import known_packings as kp
pieces_panel(9, [kp.CONWAY_PIECES[0], kp.CONWAY_PIECES[3], kp.CONWAY_PIECES[4], kp.CONWAY_PIECES[5]], "I  Conway's puzzle: 18 box pieces → 5 × 5 × 5", "3 rods 1×1×3, one 1×2×2, one 2×2×2, 13 slabs 1×2×4 (one of each kind shown).\nExact fit, density 1. Harder box jigsaw at k = 18.")
figure.text(0.05, 0.015, "Not included: 17 squares in a square (famous but NOT proven optimal); circles in a circle (needs a cylindrical container); regular tetrahedra (best known only).", fontsize=9, color="#555555")
plt.subplots_adjust(left=0.03, right=0.98, top=0.93, bottom=0.06, hspace=0.35, wspace=0.15)
figure.savefig(sys.argv[1], dpi=110)
print("saved " + sys.argv[1])
