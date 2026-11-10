"""
Known-literature verification test instances (each a folder of STLs + instance.json with the proven ceiling), in datasets_literature/.
  cylinders_5, cylinders_10, cylinders_17 : n equal circles in a square (proven optimal) extruded to cylinders of height = diameter; box side 60 mm
  spheres_8, spheres_9, spheres_14        : n equal spheres in a cube (proven optimal, Schaer 1966 / Joós 2009); cube side 60 mm
  soma, slothouber_graatsma               : exact-fit polycube puzzles (density 1), unit cube 15 mm -> 45 mm cube
Ceiling for the cylinders is the proven 2D optimum with every cylinder standing; a packing that beats it would be a finding, not an error.
    python generate_literature.py
"""

import os
import json
import numpy as np
import manifold3d
import trimesh
import known_packings

output_folder = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "datasets_literature"))
os.makedirs(output_folder, exist_ok=True)
solutions = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "known_solutions.json")))
SIDE = 60.0
UNIT = 15.0


def write_instance(name, manifolds, ceiling_density, box, note, reference_placements):
    folder = os.path.join(output_folder, name)
    os.makedirs(folder, exist_ok=True)
    volumes = []
    for number, manifold in enumerate(manifolds):
        mesh = manifold.to_mesh()
        part = trimesh.Trimesh(np.asarray(mesh.vert_properties)[:, :3], np.asarray(mesh.tri_verts), process=True)
        assert part.is_watertight
        part.export(os.path.join(folder, "piece_" + str(number).zfill(2) + ".stl"))
        volumes.append(float(part.volume))
    json.dump({"name": name, "k": len(manifolds), "ceiling_density": ceiling_density, "ceiling_bbox_volume": float(np.prod(box)), "solid_box": list(map(float, box)), "piece_volumes": volumes, "note": note, "reference_placements": reference_placements}, open(os.path.join(folder, "instance.json"), "w"))
    print(name.ljust(22) + " k = " + str(len(manifolds)).rjust(3) + "   ceiling density " + format(ceiling_density, ".4f"))


for count in (5, 10, 17):
    separation = known_packings.CIRCLES_IN_SQUARE_SEPARATION[count]
    points = np.array(solutions["circles_" + str(count)]["points"])
    radius_unit = separation / 2.0
    scale = SIDE / (1.0 + 2.0 * radius_unit)
    radius = radius_unit * scale
    height = 2.0 * radius
    cylinders = [manifold3d.Manifold.cylinder(height, radius, radius, 64) for index in range(count)]
    total_volume = count * np.pi * radius ** 2 * height
    box = [SIDE, SIDE, height]
    reference = [{"center": [float((x + radius_unit) * scale), float((y + radius_unit) * scale), float(height / 2.0)]} for x, y in points]
    write_instance("cylinders_" + str(count), cylinders, float(total_volume / np.prod(box)), box, "proven optimal circle packing in a square, cylinders standing, height = diameter", reference)

for count in (8, 9, 14):
    separation = known_packings.SPHERES_IN_CUBE_SEPARATION[count]
    points = np.array(solutions["spheres_" + str(count)]["points"])
    radius_unit = separation / 2.0
    scale = SIDE / (1.0 + 2.0 * radius_unit)
    radius = radius_unit * scale
    spheres = [manifold3d.Manifold.sphere(radius, 48) for index in range(count)]
    sphere_volume = float(manifold3d.Manifold.sphere(radius, 48).volume())
    box = [SIDE, SIDE, SIDE]
    reference = [{"center": [float(v) for v in (p + radius_unit) * scale]} for p in points]
    write_instance("spheres_" + str(count), spheres, float(count * sphere_volume / SIDE ** 3), box, "proven optimal sphere packing in a cube (Schaer 1966 for 8 and 9, Joós 2009 for 14); density uses the faceted sphere volume", reference)

for name, pieces, key in (("soma", known_packings.SOMA_PIECES, "soma"), ("slothouber_graatsma", known_packings.SLOTHOUBER_GRAATSMA_PIECES, "slothouber")):
    manifolds = []
    for cells in pieces:
        manifold = None
        for x, y, z in cells:
            cube = manifold3d.Manifold.cube([UNIT, UNIT, UNIT], False).translate([x * UNIT, y * UNIT, z * UNIT])
            manifold = cube if manifold is None else manifold + cube
        manifolds.append(manifold)
    box = [3 * UNIT] * 3
    reference = [{"piece": piece, "cells": cells} for piece, cells in solutions[key]]
    write_instance(name, manifolds, 1.0, box, "exact-fit polycube puzzle, 3 x 3 x 3", reference)
