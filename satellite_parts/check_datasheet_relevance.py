"""
Checks that every downloaded datasheet actually belongs to its part: the extracted text of the PDF (pdftotext, first pages) must name the vendor or the model.
Web-search downloads sometimes attach a neighbouring product's sheet or a general report. Writes datasheet_relevance.csv; rows with verdict "mismatch" should be moved out.
    python check_datasheet_relevance.py <folder of extracted .txt files named part_id__datasheet[_N].txt>
"""
import os
import re
import sys
import csv

HERE = os.path.dirname(os.path.abspath(__file__))
text_folder = sys.argv[1]
rows = {row["id"]: row for row in csv.DictReader(open(os.path.join(HERE, "catalog.csv"), encoding="utf-8"))}
GENERIC = {"generic", "space", "systems", "technology", "technologies", "aerospace", "the", "and", "satellite", "gmbh", "inc", "ltd", "corp", "corporation", "solar", "power", "advanced", "products", "industries"}
# Words that appear in many product sheets, so naming them does not tie a sheet to one model (2026-11-11: stricter check).
WEAK_MODEL_WORDS = {"structure", "cubesat", "panel", "antenna", "battery", "imager", "fixed", "double", "single", "compact", "patch", "thruster", "transmitter", "receiver", "transceiver", "layer", "configuration", "module", "deployable", "sensor", "wheel", "reaction", "camera", "computer", "onboard", "onboardcomputer", "control", "passive", "switch", "separation", "deployment", "mounted", "chassis", "skeletonized", "cryocooler", "board", "frame", "array", "radio", "magnetometer", "torquer", "tracker", "star", "unit", "system", "series", "standard", "micro", "mini", "nano"}
SIZE_PATTERN = re.compile(r"(?<![0-9a-z])(1p5u|1\.5u|[0-9]{1,2}u)(?![a-z0-9])")


def tokens(text):
    return [token for token in re.split(r"[^a-z0-9]+", text.lower()) if len(token) >= 3 and token not in GENERIC]


output = []
for name in sorted(os.listdir(text_folder)):
    if "__" not in name or not name.endswith(".txt"):
        continue
    part_id, file_stem = name[:-4].split("__")
    if part_id not in rows:
        continue
    row = rows[part_id]
    if not os.path.exists(os.path.join(HERE, row["category"], part_id, file_stem + "_page1.png")):
        continue
    text = open(os.path.join(text_folder, name), encoding="utf-8", errors="ignore").read().lower()
    compact = re.sub(r"[^a-z0-9]+", "", text)
    if len(text.strip()) < 200:
        verdict, why = "no_text", "image-only or empty PDF; cannot be checked"
    else:
        vendor_hit = [token for token in tokens(row["vendor"].split("(")[0]) if token in text]
        model_tokens = [token for token in tokens(row["model"]) if any(character.isdigit() for character in token) or len(token) >= 5]
        model_compact = re.sub(r"[^a-z0-9]+", "", row["model"].lower())
        model_hit = [token for token in model_tokens if token in compact] + ([model_compact] if len(model_compact) >= 4 and model_compact in compact else [])
        strong_hit = [token for token in model_hit if token not in WEAK_MODEL_WORDS]
        sizes = SIZE_PATTERN.findall((part_id + " " + row["model"]).lower().replace("_", " "))
        size_ok = True
        for size in sizes:
            number = size.replace("p5", ".5").replace("u", "")
            size_words = [number + "u", number + " u", number + "-unit", number + " unit", number + "-u"]
            if not any(word in text for word in size_words):
                size_ok = False
        if strong_hit and size_ok:
            verdict, why = "match", "names the model (" + ", ".join(sorted(set(strong_hit))[:3]) + ")"
        elif model_hit and not size_ok:
            verdict, why = "wrong_size", "names the model family but not the size " + ", ".join(sizes)
        elif model_hit:
            verdict, why = "weak", "names only generic words of the model (" + ", ".join(sorted(set(model_hit))[:3]) + ")"
        elif vendor_hit and row["vendor"].lower().startswith("generic") is False:
            verdict, why = "vendor_only", "names the vendor (" + ", ".join(vendor_hit[:2]) + ") but not this model"
        elif row["vendor"].lower().startswith("generic"):
            verdict, why = "generic", "generic or standard part; any supplier sheet for the standard is acceptable"
        else:
            verdict, why = "mismatch", "names neither the vendor nor the model"
    first_line = next((line.strip() for line in text.splitlines() if line.strip()), "")[:70]
    output.append({"part_id": part_id, "file": file_stem, "verdict": verdict, "why": why, "first_line": first_line})
with open(os.path.join(HERE, "datasheet_relevance.csv"), "w", newline="", encoding="utf-8") as handle:
    writer = csv.DictWriter(handle, fieldnames=list(output[0].keys()))
    writer.writeheader()
    writer.writerows(output)
counts = {}
for entry in output:
    counts[entry["verdict"]] = counts.get(entry["verdict"], 0) + 1
print(counts)
