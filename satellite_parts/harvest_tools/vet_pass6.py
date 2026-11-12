"""Vets pass6_candidates.csv: mass agreement between page and datasheet, a size word near the dimensions, component types only, and no duplicate of a catalog part.
    python3 vet_pass6.py <harvest folder> <our_models.json>
Writes pass6_vetted.csv with a verdict per row (accept / reject + reason). Accepted rows still get read by hand before import."""
import re
import sys
import csv
import json

ROOT = sys.argv[1]
ours = json.load(open(sys.argv[2]))
SKIP_TYPES = ("test solutions", "smallsat platform", "cubesat platform", "mediumsat platform", "largesat platform", "other platform", "special payload", "software", "ground", "service", "launch", "simulator")
SIZE_WORDS = re.compile(r"dimension|size|envelope|volume|footprint|outer|physical|packaged|mechanical", re.IGNORECASE)


def page_mass_grams(text):
    match = re.search(r"([\d.]+)\s*(kg|g)\b", text or "")
    if not match:
        return None
    return float(match.group(1)) * (1000.0 if match.group(2) == "kg" else 1.0)


def normalized(text):
    return re.sub(r"[^a-z0-9]", "", text.lower())


rows = list(csv.DictReader(open(ROOT + "/pass6_candidates.csv", encoding="utf-8")))
sheet_of = {row["slug"]: row["datasheet"].split("?")[0] for row in csv.DictReader(open(ROOT + "/pass6_index.csv", encoding="utf-8"))}
seen_dims_mass = {}
out = []
for row in rows:
    reasons = []
    if row["status"] != "candidate":
        reasons.append(row["status"])
    kind = row["type"].lower()
    if any(word in kind for word in SKIP_TYPES):
        reasons.append("not a component (" + row["type"] + ")")
    mass = float(row["mass_g"]) if row["mass_g"] else None
    page_mass = page_mass_grams(row["page_mass"])
    if mass and page_mass and abs(mass - page_mass) / page_mass > 0.12:
        reasons.append("mass differs from page (" + str(mass) + " vs " + str(page_mass) + ")")
    if row["dims_context"] and not SIZE_WORDS.search(row["dims_context"]):
        reasons.append("no size word near the dimensions")
    name_key = normalized(row["name"])
    duplicate = ""
    vendor_key = normalized(row["vendor"].split()[0]) if row["vendor"].split() else ""
    for part_id, model_key, name_key_ours in ours:
        same_vendor = len(vendor_key) >= 3 and (vendor_key[:5] in part_id.replace("_", "") or vendor_key[:5] in name_key_ours)
        if same_vendor and len(model_key) >= 4 and (model_key == name_key or (len(name_key) >= 5 and (name_key in model_key or model_key in name_key))):
            duplicate = part_id
            break
    if duplicate:
        reasons.append("already in catalog as " + duplicate)
    key = (sheet_of.get(row["slug"], row["slug"]), row["dims_mm"], row["mass_g"])
    if row["status"] == "candidate" and key in seen_dims_mass:
        reasons.append("same dims and mass as " + seen_dims_mass[key] + " (shared family sheet)")
    elif row["status"] == "candidate":
        seen_dims_mass[key] = row["slug"]
    row["verdict"] = "accept" if not reasons else "reject"
    row["reason"] = "; ".join(reasons)
    out.append(row)

with open(ROOT + "/pass6_vetted.csv", "w", newline="", encoding="utf-8") as handle:
    writer = csv.DictWriter(handle, fieldnames=list(out[0].keys()))
    writer.writeheader()
    writer.writerows(out)
print(sum(1 for row in out if row["verdict"] == "accept"), "accepted of", len(out))
