"""
Scores every part against the catalog standard and writes completeness.csv (one row per part) plus a summary on screen.
A part is complete when it has: (1) a photo, (2) CAD (part.step and part.stl), (3) a recorded photo-versus-CAD check that passed (image_cad_review.csv),
(4) at least one datasheet page, (5) a source that is not "unverified" and dimensions that are not assumed or estimated, and (6) the core tracked fields for its category.
    python audit_completeness.py
image_cad_review.csv is the hand-kept record of the visual check (verdicts: match, match_family = photo shows the product family or a representative item,
envelope_only = the CAD is the stated envelope but the photo shows a differently shaped assembly, placeholder = dimensions not from a source, no_photo).
"""
import os
import csv
import glob
import json
import collections

HERE = os.path.dirname(os.path.abspath(__file__))
PASSING_VERDICTS = ("match", "match_family")
# The block of category-specific numbers a part of that category must carry (any one of the listed blocks).
CATEGORY_BLOCKS = {"adcs": ("adcs", "electrical", "rf"), "avionics": ("electrical", "compute"), "comms": ("rf", "electrical"), "power": ("electrical",), "propulsion": ("propulsion",), "payload": ("electrical", "payload"), "mechanisms": ("mechanism", "electrical"), "thermal": ("thermal", "electrical"), "harness": ("electrical", "interfaces"), "structures": ("material", "mounting", "max_satellite_mass_kg"), "stock": ("material",), "fasteners": ("material", "thread_pitch_mm")}

review = {}
review_path = os.path.join(HERE, "image_cad_review.csv")
if os.path.exists(review_path):
    for row in csv.DictReader(open(review_path, encoding="utf-8")):
        review[row["part_id"]] = row

rows = list(csv.DictReader(open(os.path.join(HERE, "catalog.csv"), encoding="utf-8")))
output = []
missing_counts = collections.Counter()
for row in rows:
    folder = os.path.join(HERE, row["category"], row["id"])
    record = json.load(open(os.path.join(folder, "part.json"), encoding="utf-8"))
    has_photo = os.path.exists(os.path.join(folder, "reference_photo.jpg"))
    photo_kind = "none" if not has_photo else ("representative" if os.path.exists(os.path.join(folder, "photo_source.txt")) else "vendor")
    has_cad = os.path.exists(os.path.join(folder, "part.step")) and os.path.exists(os.path.join(folder, "part.stl"))
    datasheet_count = len(glob.glob(os.path.join(folder, "datasheet*_page1.png")))
    source_type = (record.get("source") or {}).get("type", "")
    verdict = review.get(row["id"], {}).get("verdict", "not_reviewed")
    if not has_photo:
        verdict = "no_photo"
    core_missing = [name for name in ("vendor", "model", "dimensions_mm", "mass_g", "status") if record.get(name) in (None, "", [], {})]
    if not (record.get("source") or {}).get("url"):
        core_missing.append("source.url")
    if record.get("status") == "unknown":
        core_missing.append("status")
    blocks = CATEGORY_BLOCKS.get(row["category"], ())
    if blocks and not any(record.get(block) not in (None, "", [], {}) for block in blocks):
        core_missing.append(" or ".join(blocks))
    missing = []
    if not has_photo:
        missing.append("photo")
    if not has_cad:
        missing.append("CAD")
    if verdict not in PASSING_VERDICTS and has_photo:
        missing.append("photo-CAD check (" + verdict + ")")
    if datasheet_count == 0:
        missing.append("datasheet")
    if source_type == "unverified":
        missing.append("verified source")
    dimensions_note = str(record.get("dimensions_note") or "").lower()
    if source_type != "unverified" and any(word in dimensions_note for word in ("assum", "placeholder", "estimate")):
        missing.append("sourced dimensions")
    if core_missing:
        missing.append("fields: " + ", ".join(core_missing))
    for item in missing:
        missing_counts[item.split(" (")[0].split(":")[0]] += 1
    output.append({"id": row["id"], "category": row["category"], "complete": "yes" if not missing else "no", "photo": photo_kind, "cad": "yes" if has_cad else "no", "datasheets": datasheet_count, "source_type": source_type, "image_cad_verdict": verdict, "image_cad_note": review.get(row["id"], {}).get("note", ""), "missing": "; ".join(missing)})

with open(os.path.join(HERE, "completeness.csv"), "w", newline="", encoding="utf-8") as handle:
    writer = csv.DictWriter(handle, fieldnames=list(output[0].keys()))
    writer.writeheader()
    writer.writerows(output)
complete = sum(1 for entry in output if entry["complete"] == "yes")
print(str(len(output)) + " parts, " + str(complete) + " complete, " + str(len(output) - complete) + " incomplete")
for name, count in missing_counts.most_common():
    print("  missing " + name + ": " + str(count))
by_category = collections.defaultdict(lambda: [0, 0])
for entry in output:
    by_category[entry["category"]][0 if entry["complete"] == "yes" else 1] += 1
for category in sorted(by_category):
    print("  " + category.ljust(12) + str(by_category[category][0]).rjust(4) + " complete, " + str(by_category[category][1]).rjust(3) + " incomplete")
