"""Reads the pass 6 harvest (page texts + datasheet texts + photos) and writes pass6_candidates.csv:
one row per harvested product that has a photo and a datasheet, with the dimension and mass statements found in the datasheet text.
    python3 extract_pass6_candidates.py <folder that holds pass6/ and pass6_index.csv>
Every row is a candidate only; a person (Claude) reads the snippets and accepts or rejects it before a part record is written."""
import os
import re
import sys
import csv
import glob

ROOT = sys.argv[1]
PAGES = os.path.join(ROOT, "pass6")
UNIT_TO_MM = {"mm": 1.0, "cm": 10.0, "m": 1000.0, "in": 25.4, "inch": 25.4, "inches": 25.4, '"': 25.4}
NUMBER = r"(\d{1,4}(?:[.,]\d{1,3})?)"
TRIPLET = re.compile(NUMBER + r"\s*(?:mm|cm)?\s*[x×X\*]\s*" + NUMBER + r"\s*(?:mm|cm)?\s*[x×X\*]\s*" + NUMBER + r"\s*(mm|cm|m|in|inch|inches|\")?(?![a-z0-9])")
MASS = re.compile(r"(?:mass|weight)[^\n0-9<>]{0,40}([<>≤~]?)\s*" + NUMBER + r"\s*(kg|g|grams|gram|lbm|lbs|lb)\b", re.IGNORECASE)
DIMENSION_WORDS = re.compile(r"dimension|size|envelope|footprint|l\s*x\s*w\s*x\s*h|outline", re.IGNORECASE)


def number(text):
    return float(text.replace(",", "."))


def page_fields(slug):
    path = os.path.join(PAGES, "_page__" + slug + ".txt")
    if not os.path.exists(path):
        return {}
    lines = [line.strip() for line in open(path, encoding="utf-8", errors="ignore")]
    fields = {"url": lines[0] if lines else ""}
    title = lines[1] if len(lines) > 1 else ""
    fields["title"] = title.split(" | ")[0]
    if "satcatalog" in slug:
        for index, line in enumerate(lines[:-1]):
            if line in ("Component Type", "Vendor", "Dry Mass", "Form Factor", "Status", "Subsystem"):
                fields.setdefault(line, lines[index + 1])
        fields["name"] = fields["title"].split(" - ")[0]
        fields["type"] = fields.get("Component Type", "")
        fields["vendor"] = fields.get("Vendor", "")
        fields["page_mass"] = fields.get("Dry Mass", "")
    else:
        for index, line in enumerate(lines):
            if line.startswith("Last updated:") and index + 2 < len(lines):
                fields["vendor"] = lines[index + 1]
                fields["name"] = lines[index + 2]
            if line == "&gt;" and index > 0 and "type" not in fields:
                fields["type"] = lines[index - 1]
            if line.lower().startswith("mass:") and "page_mass" not in fields:
                fields["page_mass"] = line.split(":", 1)[1].strip()
        fields.setdefault("name", fields["title"])
    return fields


rows = []
for folder in sorted(glob.glob(os.path.join(PAGES, "*", ""))):
    slug = os.path.basename(os.path.dirname(folder))
    text_path = os.path.join(folder, "datasheet.txt")
    photo_path = os.path.join(folder, "photo.jpg")
    if not os.path.exists(text_path):
        continue
    text = open(text_path, encoding="utf-8", errors="ignore").read()
    flat = re.sub(r"[ \t]+", " ", text)
    fields = page_fields(slug)
    triplets = []
    for match in TRIPLET.finditer(flat):
        unit = match.group(4) or ""
        context = flat[max(0, match.start() - 80):match.end() + 10].replace("\n", " ")
        if not unit:
            header = re.search(r"\((mm|cm|in)\)|\[(mm|cm|in)\]", context)
            unit = (header.group(1) or header.group(2)) if header else ""
        if not unit and "mm" in flat[max(0, match.start() - 40):match.start()]:
            unit = "mm"
        if not unit:
            continue
        values = [round(number(match.group(i)) * UNIT_TO_MM[unit], 2) for i in (1, 2, 3)]
        if min(values) <= 0 or max(values) > 6000:
            continue
        triplets.append((1 if DIMENSION_WORDS.search(context) else 0, values, context.strip()[-140:]))
    masses = []
    for match in MASS.finditer(flat):
        unit = match.group(3).lower()
        value = number(match.group(2))
        grams = value * (1000.0 if unit == "kg" else 453.592 if unit.startswith("lb") else 1.0)
        masses.append((round(grams, 1), match.group(1), flat[max(0, match.start() - 20):match.end() + 5].replace("\n", " ").strip()))
    triplets.sort(key=lambda item: -item[0])
    if not triplets or not masses:
        status = "no_dims" if not triplets else "no_mass"
    else:
        status = "candidate"
    rows.append({"slug": slug, "status": status, "has_photo": os.path.exists(photo_path), "name": fields.get("name", ""), "vendor": fields.get("vendor", ""), "type": fields.get("type", ""), "page_mass": fields.get("page_mass", ""),
                 "url": fields.get("url", ""), "dims_mm": " x ".join(str(value) for value in triplets[0][1]) if triplets else "", "dims_context": triplets[0][2] if triplets else "",
                 "other_dims": " | ".join(" x ".join(str(v) for v in item[1]) for item in triplets[1:4]), "mass_g": masses[0][0] if masses else "", "mass_bound": masses[0][1] if masses else "",
                 "mass_context": masses[0][2][:120] if masses else "", "other_masses": " | ".join(str(item[0]) for item in masses[1:4])})

with open(os.path.join(ROOT, "pass6_candidates.csv"), "w", newline="", encoding="utf-8") as handle:
    writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()) if rows else ["slug"])
    writer.writeheader()
    writer.writerows(rows)
print(len(rows), "harvested with photo + datasheet;", sum(1 for row in rows if row["status"] == "candidate"), "candidates with dims and mass")
