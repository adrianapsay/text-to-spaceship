"""
Writes <category>/<id>/drawing.png: a three-view dimension drawing (top, front, side) of part.stl with overall dimensions, in the style of a
datasheet outline drawing. Used as the reference image for generic parts (ISO fasteners, stock, generic frames) and as a second view for all parts.
    python make_drawings.py            (all)
    python make_drawings.py --only fasteners stock
"""
import os
import csv
import json
import argparse
import numpy as np
import trimesh
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.collections import PolyCollection

HERE = os.path.dirname(os.path.abspath(__file__))
parser = argparse.ArgumentParser()
parser.add_argument("--only", nargs="*", default=None)
arguments = parser.parse_args()

INK = "#1b2129"
FILL = "#dfe4ea"
FILL_DARK = "#b9c2cc"


def view(axes, mesh, axis_u, axis_v, axis_depth, label, bodies):
    """Orthographic silhouette: faces projected on (u, v), painted back to front, light shading by normal."""
    polygons = []
    depths = []
    shades = []
    for body_mesh, color in bodies:
        vertices = np.asarray(body_mesh.vertices)
        faces = np.asarray(body_mesh.faces)
        normals = np.asarray(body_mesh.face_normals)
        for face, normal in zip(faces, normals):
            if normal[axis_depth] <= 0:
                continue
            points = vertices[face][:, [axis_u, axis_v]]
            polygons.append(points)
            depths.append(float(vertices[face][:, axis_depth].mean()))
            shade = 0.55 + 0.45 * abs(normal[axis_depth])
            base = np.array(color)
            shades.append(tuple(np.clip(base * shade + (1 - shade) * 0.2, 0, 1)))
    order = np.argsort(depths)
    collection = PolyCollection([polygons[i] for i in order], facecolors=[shades[i] for i in order], edgecolors=[shades[i] for i in order], linewidths=0.4, antialiased=True)
    axes.add_collection(collection)
    # outline from the silhouette of the whole mesh in this view
    vertices = np.asarray(mesh.vertices)
    try:
        from shapely.geometry import Polygon as ShapelyPolygon
        from shapely.ops import unary_union
        faces = np.asarray(mesh.faces)
        triangles = [ShapelyPolygon(vertices[face][:, [axis_u, axis_v]]) for face in faces]
        silhouette = unary_union([t for t in triangles if t.is_valid and t.area > 1e-9])
        geoms = silhouette.geoms if hasattr(silhouette, "geoms") else [silhouette]
        for geometry in geoms:
            x, y = geometry.exterior.xy
            axes.plot(x, y, color=INK, linewidth=0.9)
            for interior in geometry.interiors:
                x, y = interior.xy
                axes.plot(x, y, color=INK, linewidth=0.7)
    except Exception:
        pass
    low = vertices.min(axis=0)
    high = vertices.max(axis=0)
    span_u = high[axis_u] - low[axis_u]
    span_v = high[axis_v] - low[axis_v]
    pad = 0.12 * max(span_u, span_v, 1.0)
    # dimension lines
    y_dim = low[axis_v] - pad * 0.55
    axes.annotate("", xy=(low[axis_u], y_dim), xytext=(high[axis_u], y_dim), arrowprops={"arrowstyle": "<->", "color": INK, "lw": 0.8})
    axes.text((low[axis_u] + high[axis_u]) / 2, y_dim - pad * 0.12, format(span_u, ".1f"), ha="center", va="top", fontsize=8, color=INK)
    x_dim = high[axis_u] + pad * 0.55
    axes.annotate("", xy=(x_dim, low[axis_v]), xytext=(x_dim, high[axis_v]), arrowprops={"arrowstyle": "<->", "color": INK, "lw": 0.8})
    axes.text(x_dim + pad * 0.12, (low[axis_v] + high[axis_v]) / 2, format(span_v, ".1f"), ha="left", va="center", fontsize=8, color=INK, rotation=90)
    axes.set_xlim(low[axis_u] - pad, high[axis_u] + pad * 1.4)
    axes.set_ylim(low[axis_v] - pad * 1.2, high[axis_v] + pad * 0.6)
    axes.set_aspect("equal")
    axes.axis("off")
    axes.set_title(label, fontsize=9, color=INK, loc="left")


rows = list(csv.DictReader(open(os.path.join(HERE, "catalog.csv"))))
count = 0
for row in rows:
    if arguments.only and row["category"] not in arguments.only:
        continue
    folder = os.path.join(HERE, row["category"], row["id"])
    mesh = trimesh.load(os.path.join(folder, "part.stl"))
    record = json.load(open(os.path.join(folder, "part.json")))
    bodies = []
    for body in (record.get("geometry") or {}).get("bodies", {}).get("part", []):
        path = os.path.join(folder, body["file"])
        if os.path.exists(path):
            bodies.append((trimesh.load(path), body["color"]))
    if not bodies:
        bodies = [(mesh, [0.75, 0.78, 0.82])]
    figure, axes = plt.subplots(1, 3, figsize=(7.5, 2.6))
    view(axes[0], mesh, 0, 1, 2, "top (x, y)", bodies)
    view(axes[1], mesh, 0, 2, 1, "front (x, z)", bodies)
    view(axes[2], mesh, 1, 2, 0, "side (y, z)", bodies)
    figure.suptitle(row["name"][:70] + "   mm", fontsize=9, color=INK, x=0.01, ha="left")
    figure.tight_layout()
    figure.savefig(os.path.join(folder, "drawing.png"), dpi=100, facecolor="white")
    plt.close(figure)
    count += 1
print(str(count) + " drawings")
