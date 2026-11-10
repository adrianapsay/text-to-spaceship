"""
Scrabble verification test generator: cut a solid (cube or sphere, 60 mm) into k pieces, so the optimal packing is known (the solid itself).
Each instance is a folder of STLs: datasets_scrabble/<solid>_<style>_k<k>_s<seed>/piece_00.stl ... plus instance.json with the ceiling.

Cut styles
  guillotine : recursive axis-aligned splits at random fractions (every piece is a box for the cube)
  tilted     : random planes through the largest remaining piece's centroid (polyhedral pieces)
  merged     : tilted cut into k + m pieces, then m random touching pairs are joined (concave pieces)

Ceiling: density = sum of piece volumes / volume of the solid's own bounding box (1.0 for the cube, pi/6 for the sphere).
Pieces are written as cut, so the test must run with clearance t = 0 (with any t > 0 a perfect fit is impossible by definition).

    python generate_scrabble.py --k 6 9 12 15 --seeds 25
"""

import os
import json
import argparse
import numpy as np
import manifold3d
import trimesh

parser = argparse.ArgumentParser()
parser.add_argument("--k", type=int, nargs="+", default=[6, 9, 12, 15])
parser.add_argument("--seeds", type=int, default=25)
parser.add_argument("--side", type=float, default=60.0, help="cube side / sphere diameter, mm")
parser.add_argument("--output_folder", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "datasets_scrabble"))
arguments = parser.parse_args()
output_folder = os.path.abspath(arguments.output_folder)
os.makedirs(output_folder, exist_ok=True)


def to_trimesh(manifold):
    mesh = manifold.to_mesh()
    return trimesh.Trimesh(np.asarray(mesh.vert_properties)[:, :3], np.asarray(mesh.tri_verts), process=True)


def largest(pieces):
    return int(np.argmax([piece.volume() for piece in pieces]))


def cut_guillotine(solid, k, rng):
    pieces = [solid]
    while len(pieces) < k:
        index = largest(pieces)
        piece = pieces.pop(index)
        low, high = np.array(piece.bounding_box())[:3], np.array(piece.bounding_box())[3:]
        axis = int(np.argmax(high - low))
        fraction = rng.uniform(0.3, 0.7)
        normal = np.zeros(3)
        normal[axis] = 1.0
        offset = low[axis] + fraction * (high[axis] - low[axis])
        first, second = piece.split_by_plane(normal.tolist(), float(offset))
        pieces.append(first)
        pieces.append(second)
    return pieces


def cut_tilted(solid, k, rng):
    pieces = [solid]
    while len(pieces) < k:
        index = largest(pieces)
        piece = pieces.pop(index)
        for attempt in range(20):
            normal = rng.normal(size=3)
            normal = normal / np.linalg.norm(normal)
            low, high = np.array(piece.bounding_box())[:3], np.array(piece.bounding_box())[3:]
            center = (low + high) / 2.0 + rng.uniform(-0.15, 0.15, 3) * (high - low)
            offset = float(normal @ center)
            first, second = piece.split_by_plane(normal.tolist(), offset)
            smaller = min(first.volume(), second.volume())
            if smaller > 0.2 * piece.volume() and first.num_vert() > 0 and second.num_vert() > 0:
                pieces.append(first)
                pieces.append(second)
                break
        else:
            pieces.append(piece)
            break
    return pieces


def cut_merged(solid, k, rng):
    merges = max(2, k // 3)
    pieces = cut_tilted(solid, k + merges, rng)
    for merge in range(merges):
        if len(pieces) <= k:
            break
        boxes = np.array([piece.bounding_box() for piece in pieces])
        candidates = []
        for first in range(len(pieces)):
            for second in range(first + 1, len(pieces)):
                touching = np.all(boxes[first][:3] <= boxes[second][3:] + 1e-6) and np.all(boxes[second][:3] <= boxes[first][3:] + 1e-6)
                if touching:
                    union = pieces[first] + pieces[second]
                    if union.num_vert() > 0 and abs(union.volume() - pieces[first].volume() - pieces[second].volume()) < 1e-3 * union.volume() and len(union.decompose()) == 1:
                        union_mesh = to_trimesh(union)
                        if union_mesh.is_watertight and len(union_mesh.split(only_watertight=False)) == 1:
                            candidates.append((first, second, union))
        if len(candidates) == 0:
            break
        first, second, union = candidates[int(rng.integers(0, len(candidates)))]
        pieces = [piece for index, piece in enumerate(pieces) if index not in (first, second)] + [union]
    while len(pieces) > k:
        # merging failed somewhere: fall back to merging any clean touching pair, else give up on this instance
        return pieces
    return pieces


STYLES = {"guillotine": cut_guillotine, "tilted": cut_tilted, "merged": cut_merged}
count = 0
for solid_name in ("cube", "sphere"):
    for style_name, cut in STYLES.items():
        for k in arguments.k:
            valid = 0
            seed = -1
            while valid < arguments.seeds and seed < 10 * arguments.seeds:
                seed = seed + 1
                rng = np.random.default_rng(1000 * k + seed)
                if solid_name == "cube":
                    solid = manifold3d.Manifold.cube([arguments.side] * 3, True)
                else:
                    solid = manifold3d.Manifold.sphere(arguments.side / 2.0, 96)
                pieces = cut(solid, k, rng)
                if len(pieces) != k:
                    print("skipped " + solid_name + " " + style_name + " k=" + str(k) + " seed=" + str(seed) + " (" + str(len(pieces)) + " pieces)")
                    continue
                folder = os.path.join(output_folder, solid_name + "_" + style_name + "_k" + str(k) + "_s" + str(seed))
                os.makedirs(folder, exist_ok=True)
                piece_volumes = []
                ok = True
                for number, piece in enumerate(pieces):
                    mesh = to_trimesh(piece)
                    if not mesh.is_watertight or mesh.volume <= 0 or len(mesh.split(only_watertight=False)) != 1:
                        ok = False
                        break
                    mesh.export(os.path.join(folder, "piece_" + str(number).zfill(2) + ".stl"))
                    piece_volumes.append(float(mesh.volume))
                if not ok:
                    print("skipped " + folder + " (bad piece)")
                    for name in os.listdir(folder):
                        os.remove(os.path.join(folder, name))
                    os.rmdir(folder)
                    continue
                box = np.array(solid.bounding_box())
                box_volume = float(np.prod(box[3:] - box[:3]))
                ceiling_density = float(sum(piece_volumes) / box_volume)
                valid = valid + 1
                json.dump({"solid": solid_name, "style": style_name, "k": k, "seed": seed, "side": arguments.side, "solid_box": (box[3:] - box[:3]).tolist(), "ceiling_density": ceiling_density, "ceiling_bbox_volume": box_volume, "piece_volumes": piece_volumes}, open(os.path.join(folder, "instance.json"), "w"))
                count = count + 1
print("wrote " + str(count) + " instances to " + output_folder)
