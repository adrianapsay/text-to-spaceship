"""
Builds explorer.html: a self-contained page with the result summaries (leaderboards and charts with 99% CIs) and a 3D viewer for a curated set of saved packings.
    python make_explorer.py
"""

import os
import csv
import json
import glob
import hashlib
import numpy as np
import trimesh
import nesting_core

HERE = os.path.dirname(os.path.abspath(__file__))
RESULTS = os.path.join(HERE, "results")
ALGORITHM_ORDER = ["random_rejection", "shelf_packing", "box_bottom_left", "box_extreme_points", "empty_maximal_spaces", "skyline_3d", "wall_building", "force_based", "force_based_v2", "voxel_bottom_left", "heightfield_drop", "dblf_24", "best_of_fast", "simulated_annealing", "genetic_algorithm", "genetic_heightfield", "genetic_box", "beam_search", "grasp_ems"]
FAMILY = {"random_rejection": "baseline", "shelf_packing": "box", "box_bottom_left": "box", "box_extreme_points": "box", "empty_maximal_spaces": "box", "force_based": "box", "force_based_v2": "box", "voxel_bottom_left": "shape", "heightfield_drop": "shape", "best_of_fast": "shape", "simulated_annealing": "search", "genetic_algorithm": "search", "genetic_heightfield": "search", "genetic_box": "search", "skyline_3d": "box", "wall_building": "box", "dblf_24": "shape", "beam_search": "search", "grasp_ems": "search"}
DATASET_ORDER = ["cuboids", "simple_convex", "complex_convex", "simple_concave", "complex_concave", "real_shapes"]


def read_csv(path):
    return list(csv.DictReader(open(path)))


# ---------------- summaries
benchmark_rows = []
for path in sorted(glob.glob(os.path.join(RESULTS, "summary_large_*_k*_n*.csv"))):
    for row in read_csv(path):
        benchmark_rows.append({"dataset": row["dataset"], "k": int(float(row["k"])), "algorithm": row["algorithm"], "n": int(float(row["trials"])), "score": float(row["score"]), "lo": float(row["score_ci99_low"]), "hi": float(row["score_ci99_high"]), "aspect": float(row["aspect_ratio_mean"]), "aspect_lo": float(row["aspect_ratio_ci99_low"]), "aspect_hi": float(row["aspect_ratio_ci99_high"]), "com": 100 * float(row["com_offset_normalized_mean"]), "com_lo": 100 * float(row["com_offset_normalized_ci99_low"]), "com_hi": 100 * float(row["com_offset_normalized_ci99_high"]), "gap": float(row["minimum_gap_mean"]), "contacts": float(row.get("contacts_per_part_mean", "nan") or "nan"), "isolated": float(row.get("isolated_parts_mean", "nan") or "nan"), "seconds": float(row["seconds_mean"]), "valid": float(row["valid_rate"])})

verification_rows = []
for path in sorted(glob.glob(os.path.join(RESULTS, "verification_*_summary.csv"))):
    tag = os.path.basename(path).replace("verification_", "").replace("_summary.csv", "")
    test = tag.split("_")[0]
    mode = "container" if "container" in tag else "open"
    pitch = 1 if "pitch1" in tag else 2
    for row in read_csv(path):
        verification_rows.append({"run": tag, "test": test, "mode": mode, "pitch": pitch, "group": row["group"], "algorithm": row["algorithm"], "n": int(float(row["runs"])), "ratio": float(row["ratio_mean"]), "lo": float(row["ratio_ci99_low"]), "hi": float(row["ratio_ci99_high"]), "best": float(row["ratio_best"]), "solved": float(row["solved_rate"]), "valid": float(row["valid_rate"]), "aspect": float(row["aspect_ratio_mean"]), "seconds": float(row["seconds_mean"])})

# ---------------- curated packings for the 3D viewer
meshes = {}


def mesh_key(mesh):
    return hashlib.md5(np.asarray(mesh.vertices).round(3).tobytes() + np.asarray(mesh.faces).tobytes()).hexdigest()[:10]


def register_mesh(mesh, max_faces=700):
    if len(mesh.faces) > max_faces:
        try:
            mesh = mesh.simplify_quadric_decimation(face_count=max_faces)
        except Exception:
            pass
    key = mesh_key(mesh)
    if key not in meshes:
        meshes[key] = {"v": np.asarray(mesh.vertices, dtype=float).round(2).ravel().tolist(), "f": np.asarray(mesh.faces, dtype=int).ravel().tolist()}
    return key


def load_instance_parts(folder, instance_name):
    nesting_core.DATASETS_FOLDER = folder
    parts = nesting_core.load_parts(instance_name, 2.0, 1.0)
    keys = {}
    for part in parts:
        keys[part["name"]] = register_mesh(part["mesh"])
    return parts, keys


def pack_record(record, keys, extra):
    placements = [{"m": keys[placement["part"]], "r": [round(value, 5) for row in placement["rotation"] for value in row], "t": [round(value, 3) for value in placement["translation"]]} for placement in record["placements"]]
    entry = {"algorithm": record["algorithm"], "placements": placements}
    entry.update(extra)
    return entry


packings = []
# literature: container mode, best repeat per algorithm, plus the proven reference
for path in [os.path.join(RESULTS, "verification_literature_container_solutions.jsonl"), os.path.join(RESULTS, "verification_literature_container_geneticbox_solutions.jsonl")]:
    best = {}
    for line in open(path):
        record = json.loads(line)
        key = (record["instance"], record["algorithm"])
        if key not in best or record["ratio"] > best[key]["ratio"]:
            best[key] = record
    for (instance_name, algorithm_name), record in sorted(best.items()):
        parts, keys = load_instance_parts(os.path.join(HERE, "datasets_literature"), instance_name)
        instance = json.load(open(os.path.join(HERE, "datasets_literature", instance_name, "instance.json")))
        packings.append(pack_record(record, keys, {"collection": "literature", "instance": instance_name, "mode": "container", "container": record["container"], "ratio": record["ratio"], "valid": record["valid"], "placed": len(record["placements"]), "k": len(record["parts"]), "note": "fraction of parts that fit the proven box"}))
for instance_name in sorted(os.listdir(os.path.join(HERE, "datasets_literature"))):
    instance = json.load(open(os.path.join(HERE, "datasets_literature", instance_name, "instance.json")))
    parts, keys = load_instance_parts(os.path.join(HERE, "datasets_literature"), instance_name)
    placements = []
    if "center" in instance["reference_placements"][0]:
        for part, reference in zip(parts, instance["reference_placements"]):
            placements.append({"m": keys[part["name"]], "r": [1, 0, 0, 0, 1, 0, 0, 0, 1], "t": [round(value, 3) for value in reference["center"]]})
    else:
        unit = 15.0
        for reference in instance["reference_placements"]:
            cubes = None
            for x, y, z in reference["cells"]:
                cube = trimesh.creation.box(extents=[unit, unit, unit])
                cube.apply_translation([(x + 0.5) * unit, (y + 0.5) * unit, (z + 0.5) * unit])
                cubes = cube if cubes is None else trimesh.util.concatenate([cubes, cube])
            placements.append({"m": register_mesh(cubes), "r": [1, 0, 0, 0, 1, 0, 0, 0, 1], "t": [0, 0, 0]})
    packings.append({"collection": "literature", "instance": instance_name, "algorithm": "proven solution", "mode": "container", "container": instance["solid_box"], "ratio": 1.0, "valid": True, "placed": len(placements), "k": len(placements), "placements": placements, "note": instance["note"]})

# scrabble: six instances (k = 9, seed 0 of each solid x style), open mode, best repeat per algorithm, plus the original solid as reference
scrabble_instances = [name for name in sorted(os.listdir(os.path.join(HERE, "datasets_scrabble"))) if name.endswith("_k9_s0")]
best = {}
for line in open(os.path.join(RESULTS, "verification_scrabble_open_solutions.jsonl")):
    record = json.loads(line)
    if record["instance"] not in scrabble_instances:
        continue
    key = (record["instance"], record["algorithm"])
    if key not in best or record["ratio"] > best[key]["ratio"]:
        best[key] = record
for (instance_name, algorithm_name), record in sorted(best.items()):
    parts, keys = load_instance_parts(os.path.join(HERE, "datasets_scrabble"), instance_name)
    packings.append(pack_record(record, keys, {"collection": "scrabble", "instance": instance_name, "mode": "open", "container": None, "ratio": record["ratio"], "valid": record["valid"], "placed": len(record["placements"]), "k": len(record["parts"]), "note": "density / ceiling (the solid's own box)"}))
for instance_name in scrabble_instances:
    parts, keys = load_instance_parts(os.path.join(HERE, "datasets_scrabble"), instance_name)
    placements = []
    for part in parts:
        original = trimesh.load(os.path.join(HERE, "datasets_scrabble", instance_name, part["name"] + ".stl"))
        center = (original.bounds[0] + original.bounds[1]) / 2.0
        placements.append({"m": keys[part["name"]], "r": [1, 0, 0, 0, 1, 0, 0, 0, 1], "t": [round(float(value), 3) for value in center]})
    packings.append({"collection": "scrabble", "instance": instance_name, "algorithm": "original solid (ceiling)", "mode": "open", "container": None, "ratio": 1.0, "valid": True, "placed": len(placements), "k": len(placements), "placements": placements, "note": "the pieces as cut"})

# benchmark: one trial (trial 0) per category at k = 10, every algorithm
best = {}
for path in sorted(glob.glob(os.path.join(RESULTS, "solutions_large_*_k10_n*.jsonl"))):
    for line in open(path):
        record = json.loads(line)
        if record["trial"] == 0:
            best[(record["dataset"], record["algorithm"])] = record
for (dataset_name, algorithm_name), record in sorted(best.items()):
    parts, keys = load_instance_parts(os.path.join(HERE, "datasets_large"), dataset_name)
    used = {name: keys[name] for name in record["parts"]}
    packings.append(pack_record(record, used, {"collection": "benchmark", "instance": dataset_name, "mode": "open", "container": None, "ratio": record["density"], "valid": record["valid"], "placed": len(record["placements"]), "k": len(record["parts"]), "note": "density (parts volume / box volume), trial 0 of the k = 10 run"}))


# ---------------- order study (aggregated from the trials file so a partial run can be shown)
order_rows = []
order_trials_path = os.path.join(RESULTS, "order_trials_k10_k20.csv")
if os.path.exists(order_trials_path):
    import benchmark
    groups = {}
    for row in read_csv(order_trials_path):
        groups.setdefault((row["dataset"], int(row["k"]), row["algorithm"], row["order_spec"]), []).append(row)
    for (dataset_name, k, algorithm_name, order_spec), group in sorted(groups.items()):
        scores = np.array([float(row["density"]) if row["valid"] == "True" else 0.0 for row in group])
        low, high = benchmark.confidence_interval_99(scores)
        per_set = {}
        for row, score in zip(group, scores):
            per_set.setdefault(row["set"], []).append(score)
        spread = float(np.mean([max(values) - min(values) for values in per_set.values()])) if order_spec == "random" and len(group) > 1 else None
        order_rows.append({"dataset": dataset_name, "k": k, "algorithm": algorithm_name, "order": order_spec, "n": len(group), "sets": len(per_set), "score": float(scores.mean()), "lo": float(low), "hi": float(high), "best": float(scores.max()), "worst": float(scores.min()), "spread": spread, "aspect": float(np.mean([float(row["aspect_ratio"]) for row in group])), "seconds": float(np.mean([float(row["seconds"]) for row in group]))})
print("order rows " + str(len(order_rows)))

# ---------------- algorithm cards (text + sketch)
import base64
cards = {}
cards_folder = os.path.join(RESULTS, "algorithm_cards")
if os.path.exists(os.path.join(cards_folder, "cards.json")):
    cards = json.load(open(os.path.join(cards_folder, "cards.json")))
    for name, card in cards.items():
        image_path = os.path.join(cards_folder, card["image"])
        card["image"] = "data:image/png;base64," + base64.b64encode(open(image_path, "rb").read()).decode() if os.path.exists(image_path) else None

data = {"order": order_rows, "cards": cards, "benchmark": benchmark_rows, "verification": verification_rows, "packings": packings, "meshes": meshes, "algorithms": ALGORITHM_ORDER, "family": FAMILY, "datasets": DATASET_ORDER}
payload = json.dumps(data, separators=(",", ":"))
template = open(os.path.join(HERE, "explorer_template.html")).read()
page = template.replace("/*__DATA__*/", payload)
open(os.path.join(HERE, "explorer.html"), "w").write(page)
print("meshes " + str(len(meshes)) + ", packings " + str(len(packings)) + ", page " + format(len(page) / 1e6, ".1f") + " MB")
