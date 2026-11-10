"""
One explanation card per algorithm for the explorer's Algorithms tab: a sketch (PNG) plus short text (what it does, how it places, strengths, weaknesses, cost).
The ten original sketches are reused from make_slides.py (their draw_* functions are loaded from that file's source so the slides and the explorer stay identical);
nine more are drawn here (empty maximal spaces, best of fast, genetic heightfield, genetic box, skyline, wall building, DBLF 24, beam search, GRASP EMS).

    python algorithm_cards.py          writes results/algorithm_cards/<name>.png and results/algorithm_cards/cards.json
"""

import os
import json
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, FancyArrowPatch, Circle, Polygon

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "results", "algorithm_cards")
os.makedirs(OUT, exist_ok=True)

BLUE = "#2a78d6"
ORANGE = "#eb6834"
AQUA = "#1baf7a"
RED = "#e34948"
INK = "#0b0b0b"
INK2 = "#444444"
INK3 = "#8a8a8a"
LIGHT = "#e8e8e4"
FILL = "#cde2fb"
GREEN = "#008300"


def box(axes, x, y, w, h, color, alpha=0.85, lw=1.2, ls="-", fill=True):
    axes.add_patch(Rectangle((x, y), w, h, facecolor=color if fill else "none", edgecolor=INK if fill else color, alpha=alpha, linewidth=lw, linestyle=ls))


def arrow(axes, start, end, color=INK, lw=1.8, style="-|>"):
    axes.add_patch(FancyArrowPatch(start, end, arrowstyle=style, mutation_scale=14, color=color, linewidth=lw))


def dot(axes, x, y, color, r=0.16):
    axes.add_patch(Circle((x, y), r, facecolor=color, edgecolor="white", linewidth=1.0, zorder=5))


# Load the ten original sketches from make_slides.py without running the slide build.
slides_source = open(os.path.join(HERE, "make_slides.py")).read()
start = slides_source.index("def draw_random_rejection(axes):")
end = slides_source.index("\nalgorithm_slide(")
exec(slides_source[start:end], globals())


def draw_ems(axes):
    box(axes, 0.5, 0.5, 9.0, 8.0, INK3, fill=False, lw=1.2, ls="--")
    box(axes, 0.5, 0.5, 4.0, 3.0, BLUE)
    box(axes, 4.5, 0.5, 2.5, 2.0, BLUE)
    for (x, y, w, h) in [(0.5, 3.5, 9.0, 5.0), (4.5, 2.5, 5.0, 6.0), (7.0, 0.5, 2.5, 8.0)]:
        box(axes, x, y, w, h, AQUA, alpha=0.18, lw=1.0, ls="--")
    axes.text(0.5, 9.1, "free space = a list of maximal empty boxes (green, overlapping)", fontsize=10, color=INK)
    box(axes, 4.5, 2.5, 2.5, 1.6, ORANGE, alpha=0.7)
    axes.text(7.2, 3.3, "part placed at the min corner of the\nempty box that keeps the overall\nbox smallest; the empty boxes it cuts\nsplit into up to 6 pieces each", fontsize=9.5, color=INK2, va="center")
    axes.text(10.0, 7.5, "largest box first\n6 orientations\nboxes only", fontsize=10, color=INK)


def draw_best_of_fast(axes):
    names = ["shelf", "bottom-left", "extreme pts", "EMS", "voxel", "heightfield"]
    for i, name in enumerate(names):
        box(axes, 0.5, 8.3 - i * 1.3, 3.2, 1.0, FILL, lw=0.8)
        axes.text(2.1, 8.8 - i * 1.3, name, ha="center", va="center", fontsize=10)
        arrow(axes, (3.8, 8.8 - i * 1.3), (6.0, 5.6), color=INK3, lw=1.0)
    box(axes, 6.0, 4.8, 3.6, 1.6, ORANGE, alpha=0.7)
    axes.text(7.8, 5.6, "keep the densest\n(most parts first)", ha="center", va="center", fontsize=9.5)
    axes.text(6.0, 8.8, "runs all six constructive packers on\nthe same parts; cost = the sum of six;\n'let the tool pick the algorithm'", fontsize=10, color=INK, va="top")


def draw_genetic_heightfield(axes):
    draw_genetic(axes)
    axes.add_patch(Rectangle((0.3, 0.2), 13.4, 2.3, facecolor="white", edgecolor="none"))
    axes.text(0.5, 2.3, "same genetic search; the decoder is the heightfield drop (each decode about 10x cheaper\nthan voxel), so the 5 s budget evaluates about 10x more orders and orientations", fontsize=10, color=INK, va="top")


def draw_genetic_box(axes):
    draw_genetic(axes)
    axes.add_patch(Rectangle((0.3, 0.2), 13.4, 2.3, facecolor="white", edgecolor="none"))
    axes.text(0.5, 2.3, "same genetic search with the extreme-points box decoder: exact box geometry (no grid\nrounding), about 50x cheaper decodes; boxes only. A diagnostic for how much the grid costs", fontsize=10, color=INK, va="top")


def draw_skyline(axes):
    heights = [2.0, 2.0, 3.5, 3.5, 3.5, 1.0, 1.0, 2.5, 2.5, 4.0, 4.0]
    for i, h in enumerate(heights):
        axes.add_patch(Rectangle((0.5 + i * 0.8, 0.5), 0.8, h, facecolor=BLUE, edgecolor="white", linewidth=0.6, alpha=0.75))
    xs = [0.5 + i * 0.8 for i in range(len(heights))] + [0.5 + len(heights) * 0.8]
    for i, h in enumerate(heights):
        axes.plot([xs[i], xs[i + 1]], [0.5 + h, 0.5 + h], color=INK, linewidth=2.0)
        if i + 1 < len(heights):
            axes.plot([xs[i + 1], xs[i + 1]], [0.5 + h, 0.5 + heights[i + 1]], color=INK, linewidth=2.0)
    box(axes, 4.5, 1.5, 2.4, 1.6, ORANGE, alpha=0.75)
    axes.add_patch(Rectangle((4.5, 1.5), 2.4, 0.0, facecolor="none"))
    axes.add_patch(Rectangle((4.5 + 0.8, 0.5 + 1.0), 1.6, 0.5, facecolor=RED, alpha=0.25, edgecolor="none"))
    axes.text(7.1, 2.3, "rests on the highest\ncolumn under it; the\nred gap is wasted", fontsize=9.5, color=INK2, va="center")
    axes.text(0.5, 9.6, "the stack seen from the side is a skyline of box tops (black line) on a 1 mm height map\ncandidates: the 2D corners of placed boxes; pick the lowest resulting top, then least waste", fontsize=10, color=INK, va="top")
    axes.text(0.5, 7.2, "floor sizes 1.0, 1.25, 1.5, 2.0 x footprint tried; densest kept", fontsize=9.5, color=INK2)


def draw_wall_building(axes):
    walls = [(0.5, 2.6), (3.3, 2.0), (5.5, 3.2)]
    for x, depth in walls:
        box(axes, x, 0.5, depth, 7.0, INK3, fill=False, lw=1.2, ls="--")
    boxes = [(0.5, 0.5, 2.6, 3.0), (0.5, 3.7, 2.2, 2.0), (3.3, 0.5, 2.0, 4.0), (3.3, 4.7, 1.6, 1.6), (5.5, 0.5, 3.2, 2.4), (5.5, 3.1, 2.4, 3.2)]
    for i, (x, y, w, h) in enumerate(boxes):
        box(axes, x, y, w, h, BLUE if i < 4 else ORANGE, alpha=0.8)
    arrow(axes, (0.5, 8.0), (9.2, 8.0), lw=1.4)
    axes.text(9.4, 8.0, "walls along x", fontsize=9.5, va="center", color=INK2)
    axes.text(0.5, 9.6, "the first part of a wall sets its depth; the wall's y-z face is filled with 2D maximal\nempty rectangles by any remaining part whose box depth fits; a new wall when nothing fits", fontsize=10, color=INK, va="top")
    axes.text(9.4, 3.5, "George and Robinson\n(1980) container loading\nheuristic, boxes only", fontsize=9.5, color=INK2, va="center")


def draw_dblf(axes):
    draw_voxel(axes)
    axes.add_patch(Rectangle((0.3, 7.2), 13.4, 2.6, facecolor="white", edgecolor="none"))
    axes.text(0.5, 9.6, "deep-bottom-left-fill on the voxel grid: all 24 axis-aligned orientations per part (not only\nthe 6 distinct box shapes); position = deepest z, then y, then x inside a fixed floor", fontsize=10, color=INK, va="top")


def draw_beam(axes):
    levels = [[(1.0, 8.5)], [(0.5, 6.5), (2.0, 6.5), (3.5, 6.5)], [(0.5, 4.5), (2.0, 4.5), (3.5, 4.5), (5.0, 4.5)], [(1.2, 2.5), (2.7, 2.5), (4.2, 2.5)]]
    kept = {(1, 0), (1, 2), (2, 1), (2, 3), (3, 1)}
    for level, nodes in enumerate(levels):
        for number, (x, y) in enumerate(nodes):
            color = ORANGE if (level, number) in kept or level == 0 else LIGHT
            box(axes, x, y, 1.0, 0.8, color, alpha=0.9, lw=0.8)
            if level > 0:
                parent = levels[level - 1][min(number // 2, len(levels[level - 1]) - 1)]
                axes.plot([parent[0] + 0.5, x + 0.5], [parent[1], y + 0.8], color=INK3, linewidth=0.8)
    axes.text(6.5, 7.5, "each level = one more part placed\n(every remaining part x every orientation)\nkeep the best B = 8 partial packings\n(orange), drop the rest", fontsize=10, color=INK, va="top")
    axes.text(6.5, 3.8, "score = density if the remaining parts\nfit perfectly into the current box;\nextreme-points decoder; deterministic;\n5 s cap, then greedy to the end", fontsize=9.5, color=INK2, va="top")


def draw_grasp(axes):
    draw_ems(axes)
    axes.add_patch(Rectangle((0.3, 8.6), 13.4, 1.3, facecolor="white", edgecolor="none"))
    axes.add_patch(Rectangle((9.6, 0.3), 4.1, 8.2, facecolor="white", edgecolor="none"))
    axes.text(0.5, 9.6, "GRASP: repeat EMS constructions for 5 s; each one perturbs the order (neighbour swaps)\nand picks each part's spot at random among the 3 best; keep the densest", fontsize=10, color=INK, va="top")
    axes.text(9.8, 6.0, "randomized greedy\nescapes the ties\nand traps of pure\ngreedy EMS", fontsize=9.5, color=INK2, va="center")


CARDS = {
    "random_rejection": {"family": "baseline", "what": "The floor every real method must beat: random angle, random position, keep the try that does not hit anything.", "how": "Each part gets up to 300 random poses inside a cube; a pose is rejected if its box comes within the clearance of a placed box. When stuck the cube grows 10%. Three restarts, best kept.", "strengths": ["No assumptions, any orientation.", "Shows what 'no packing logic' gives."], "weaknesses": ["Density 0.09 to 0.19.", "Gaps of 2 to 3 mm everywhere."], "cost": "about 0.3 s per packing", "draw": draw_random_rejection},
    "shelf_packing": {"family": "box", "what": "Rows and layers, like filling a bookshelf.", "how": "Lay every part flat (shortest side up), tallest first. Fill a row along x, then the next row in y, then a new layer in z when the square floor is full.", "strengths": ["Fastest method (0.03 s).", "Predictable layers; good for flat parts."], "weaknesses": ["A tall part sets the whole layer height.", "Space above shorter parts is wasted."], "cost": "0.03 s", "draw": draw_shelf},
    "box_bottom_left": {"family": "box", "what": "Classic bottom-left-fill on bounding boxes.", "how": "Largest box first. Candidate corners are every combination of placed-box edges on a square floor; take the lowest, then frontmost, then leftmost free corner over the 6 orientations.", "strengths": ["Near-cubic packings (aspect 1.1 to 1.3).", "Simple, deterministic, 0.05 s."], "weaknesses": ["Fixed floor size limits the layout.", "Boxes only: cannot use a concave part's notch."], "cost": "0.05 s", "draw": draw_bottom_left},
    "box_extreme_points": {"family": "box", "what": "Bottom-left with far fewer candidates and a better objective.", "how": "Only the three corners each placed box exposes (+x, +y, +z) are candidates. Choose the corner and orientation that keep the overall bounding box smallest.", "strengths": ["Densest plain box method on cuboids.", "Few candidates, so fast (0.04 s)."], "weaknesses": ["The greedy volume objective builds slabs (aspect 4 to 6).", "Boxes only."], "cost": "0.04 s", "draw": draw_extreme_points},
    "empty_maximal_spaces": {"family": "box", "what": "Keeps an explicit list of the empty space as maximal boxes.", "how": "Start with one big empty box. Each part goes at the min corner of the empty box (and orientation) that keeps the overall box smallest; every empty box it cuts is split into up to six boxes around it, and boxes inside others are dropped.", "strengths": ["Best constructive box method on most categories.", "Fast (0.1 s); container mode is natural."], "weaknesses": ["Boxes only.", "Greedy: one bad early choice is never revisited."], "cost": "0.1 s", "draw": draw_ems},
    "force_based": {"family": "box", "what": "Physics-style: throw the boxes in, squeeze, push overlaps apart.", "how": "Every box starts at a random spot, overlapping. Repeat 40 times: squeeze all boxes 10% toward the centroid, then push overlapping pairs apart along their shallowest overlap. Keep the tightest overlap-free state. Three restarts.", "strengths": ["No placement order; all parts move at once.", "Constraints can be added as extra forces."], "weaknesses": ["Isotropic squeeze forms long rows.", "Barely above random on concave parts."], "cost": "0.3 s", "draw": draw_force},
    "force_based_v2": {"family": "box", "what": "force_based with an anisotropic squeeze, compaction and re-orientation.", "how": "Axes wider than a target cube are pulled in harder; after each pass every box slides toward the origin along z, y, x as far as the others allow and re-picks the orientation that overlaps least.", "strengths": ["10 to 25% denser than v1, rows gone.", "Keeps the order-free structure."], "weaknesses": ["Still boxes, still below the greedy methods.", "Elongated (aspect 2.5 to 4)."], "cost": "0.4 s", "draw": draw_force_v2},
    "voxel_bottom_left": {"family": "shape", "what": "Bottom-left on the real shape, voxelized.", "how": "Each part is voxelized at 2 mm, grown by half the clearance. For each orientation an FFT convolution of the grid with the part gives the overlap count at every position at once; keep the free position that keeps the box smallest.", "strengths": ["Concave parts can interlock.", "Best constructive method on real shapes."], "weaknesses": ["The 2 mm grid and the clearance eat most of the interlock gain.", "5 to 10x slower than box methods."], "cost": "0.5 to 2 s", "draw": draw_voxel},
    "heightfield_drop": {"family": "shape", "what": "Huai-Yi's method rebuilt on the benchmark grid: drop parts onto a height map.", "how": "The stack is a 2D height map; each part has a bottom and a top profile per column. Drop at every (x, y) and orientation: landing height = max over its columns of (stack top minus part bottom). Keep the landing that keeps the box smallest.", "strengths": ["Overlap-free by construction.", "No 3D search: 5x faster than voxel, within 0.02 of it."], "weaknesses": ["A column is solid from bottom to top, so nothing slides under an overhang.", "Greedy smallest-box choice builds towers."], "cost": "0.05 to 0.1 s", "draw": draw_heightfield},
    "best_of_fast": {"family": "shape", "what": "Run the six constructive packers and keep the densest.", "how": "Shelf, bottom-left, extreme points, EMS, voxel and heightfield on the same parts; keep the result with the most parts placed, then the highest density.", "strengths": ["Never worse than its best member.", "The 'let the tool choose' baseline."], "weaknesses": ["Cost is the sum of six.", "No new placements, only selection."], "cost": "about 1 s", "draw": draw_best_of_fast},
    "simulated_annealing": {"family": "search", "what": "Search over the placement order and orientations, decoded by the voxel packer.", "how": "Start from largest-first. Each step swaps two parts or re-orients one, decodes with the voxel packer (orientations fixed), accepts if density rises or with probability exp(gain / T); T falls from 0.05 to 0.001 over a 5 s budget.", "strengths": ["+0.01 to +0.03 over voxel bottom-left.", "Most compact boxes and lowest COM offset of any method."], "weaknesses": ["5 s per packing; result depends on budget and CPU.", "About 100 decodes is a small search for 10! orders."], "cost": "5 s (time budget)", "draw": draw_annealing},
    "genetic_algorithm": {"family": "search", "what": "A population of (order, orientations) genomes bred for density, decoded by the voxel packer.", "how": "Population 12; each generation keeps the best 6 and breeds 6 children by order crossover (a slice of parent 1 stays, parent 2 fills the rest in its order), orientations from either parent, one mutation. 5 s budget.", "strengths": ["Best density on most categories at k = 10.", "Children are independent: parallel-friendly."], "weaknesses": ["5 s per packing.", "Only +0.01 over annealing."], "cost": "5 s (time budget)", "draw": draw_genetic},
    "genetic_heightfield": {"family": "search", "what": "The genetic search with the heightfield drop as decoder.", "how": "Same genome and operators; each decode is about 10x cheaper than voxel, so the same 5 s evaluates about 10x more orders and orientations.", "strengths": ["Usually the best search method at k = 20 and 30.", "Exact overlap-free decodes."], "weaknesses": ["Inherits the heightfield's overhang blindness.", "5 s per packing."], "cost": "5 s (time budget)", "draw": draw_genetic_heightfield},
    "genetic_box": {"family": "search", "what": "The genetic search with the exact extreme-points box decoder.", "how": "Same genome and operators; decodes are about 50x cheaper and have no grid rounding. Boxes only.", "strengths": ["Shows how much the voxel grid costs on box-like parts.", "Very many decodes per budget."], "weaknesses": ["Boxes only: no interlocking.", "Diagnostic more than a contender on concave parts."], "cost": "5 s (time budget)", "draw": draw_genetic_box},
    "skyline_3d": {"family": "box", "what": "Skyline packing: the stack is a height map of box tops.", "how": "A square floor carries a 1 mm height map. Each part's box, in each orientation, is tried at the 2D corners of placed boxes and rests on the highest point under it; keep the lowest resulting top, then the least wasted volume. Four floor sizes tried, densest kept.", "strengths": ["Simple, fast, compact footprints.", "Standard 2D strip-packing idea lifted to 3D."], "weaknesses": ["Weak on this benchmark: waste under boxes adds up.", "Boxes only; no overhangs."], "cost": "about 0.1 s", "draw": draw_skyline},
    "wall_building": {"family": "box", "what": "Container-loading classic: fill vertical walls one after another.", "how": "The first part of a wall sets its depth. The wall's face is filled with 2D maximal empty rectangles by any remaining part whose box depth fits in some orientation; when nothing fits, a new wall starts behind it.", "strengths": ["Natural for container mode and layered assemblies.", "Fast (0.1 s)."], "weaknesses": ["Wall depth is set by one part, so depth is wasted.", "Boxes only."], "cost": "about 0.1 s", "draw": draw_wall_building},
    "dblf_24": {"family": "shape", "what": "Deep-bottom-left-fill on voxels with all 24 orientations.", "how": "Like voxel bottom-left, but every axis-aligned orientation is tried (not only the 6 distinct box shapes) and the position is the deepest, then lowest, then leftmost free cell inside a fixed floor.", "strengths": ["More orientations than any other grid method.", "Near-cubic results."], "weaknesses": ["About 4x the cost of voxel bottom-left.", "The fixed floor can force a tall stack."], "cost": "2 to 5 s", "draw": draw_dblf},
    "beam_search": {"family": "search", "what": "Deterministic tree search over placement sequences with a beam.", "how": "Each level places one more part: every partial packing in the beam is extended by every remaining part in every orientation (extreme-points decoder), scored by the density reachable if the rest fit perfectly, and the best 8 are kept. 5 s cap, then greedy.", "strengths": ["Deterministic and reproducible.", "Cheaper than the genetic methods on small k."], "weaknesses": ["The optimistic score favours slabs.", "Boxes only."], "cost": "0.3 to 5 s", "draw": draw_beam},
    "grasp_ems": {"family": "search", "what": "GRASP: many randomized EMS constructions, keep the best.", "how": "For 5 s: perturb the largest-first order with neighbour swaps, run EMS picking each part's spot at random among the 3 best choices, keep the densest valid construction.", "strengths": ["Best box-based density in the smoke tests (0.82 on cuboids).", "Simple and parallel-friendly."], "weaknesses": ["5 s per packing.", "Boxes only."], "cost": "5 s (time budget)", "draw": draw_grasp},
}


def main():
    cards = {}
    for name, card in CARDS.items():
        figure = plt.figure(figsize=(7.0, 5.0))
        axes = figure.add_axes([0.02, 0.02, 0.96, 0.96])
        axes.set_aspect("equal")
        axes.set_xlim(0, 14)
        axes.set_ylim(0, 10)
        axes.axis("off")
        card["draw"](axes)
        path = os.path.join(OUT, name + ".png")
        figure.savefig(path, dpi=100, facecolor="white")
        plt.close(figure)
        cards[name] = {key: value for key, value in card.items() if key != "draw"}
        cards[name]["image"] = name + ".png"
        print(name)
    json.dump(cards, open(os.path.join(OUT, "cards.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
