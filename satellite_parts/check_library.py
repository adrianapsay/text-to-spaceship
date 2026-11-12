"""Consistency checks over every part.json: bbox vs declared dimensions, density plausibility, watertightness, missing fields. Prints problems; exit code 1 if any."""
import os
import json
import glob

HERE = os.path.dirname(os.path.abspath(__file__))
problems = []
for path in sorted([path for path in glob.glob(os.path.join(HERE, "*", "*", "part.json")) if not os.path.basename(os.path.dirname(os.path.dirname(path))).startswith("_")]):
    record = json.load(open(path))
    part_id = record["id"]
    dims = [record["dimensions_mm"]["x"], record["dimensions_mm"]["y"], record["dimensions_mm"]["z"]]
    measured = record["geometry"]["measured_bbox_mm"]
    for axis in range(3):
        if abs(measured[axis] - dims[axis]) > max(1.0, 0.1 * dims[axis]):
            problems.append(part_id + ": bbox axis " + "xyz"[axis] + " measured " + str(measured[axis]) + " vs declared " + str(dims[axis]))
    if not record["geometry"]["watertight"]:
        problems.append(part_id + ": STL not watertight")
    density = record["geometry"].get("effective_density_g_cm3")
    if density is not None and (density < 0.02 or density > 22):
        problems.append(part_id + ": effective density " + str(density) + " g/cm3 (mass " + str(record.get("mass_g")) + " g)")
    if not record.get("mass_g"):
        problems.append(part_id + ": no mass")
    if not record.get("source", {}).get("url"):
        problems.append(part_id + ": no source url")
    detail = record["geometry"].get("detail") or {}
    if detail and not detail.get("same_as_envelope") and not detail.get("inside_envelope", True):
        problems.append(part_id + ": detail geometry pokes out of the envelope by " + str(detail.get("overshoot_mm")) + " mm (packing would miss it)")
    if record["geometry"]["face_counts"]["part"] > 2000:
        problems.append(part_id + ": " + str(record["geometry"]["face_counts"]["part"]) + " faces")
for problem in problems:
    print(problem)
print(str(len(problems)) + " problems")
raise SystemExit(1 if problems else 0)
