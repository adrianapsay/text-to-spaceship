"""Builds pass7.csv (same columns as pass5.csv, so fetch_pass5.py can read it): photos and datasheets for the parts added by web search on 2026-11-11."""
import os
import csv
import sys
import glob
import importlib

CATALOG = "/home/claude/nb/satellite_parts"
sys.path.insert(0, CATALOG)
NEW_MODULES = ["smallsat_2026_11_11", "cots_2026_11_11", "web_2026_11_11", "web2_2026_11_11", "fasteners"]
NEW_FASTENER_PREFIXES = ("bhcs_", "set_screw_", "pan_screw_")

FASTENER_FAMILIES = {
    "bhcs_": {"datasheets": ["https://westfieldfasteners.co.uk/Standards/ScrewBolt-SHBtn-M.pdf", "https://www.westfieldfasteners.co.uk/Standards/ScrewBolt-SHBtn-M.html"],
              "photo_page": "https://www.westfieldfasteners.co.uk/A2-ScrewBolt-SHBtn-{SIZE}.html", "terms": "7380|button"},
    "set_screw_": {"datasheets": ["https://westfieldfasteners.co.uk/Standards/ScrewBolt-GrubFlat-M.pdf"],
                   "photo_page": "https://www.westfieldfasteners.co.uk/A2-ScrewBolt-GrubFlat-{SIZE}.html", "terms": "4026|913|grub"},
    "pan_screw_": {"datasheets": ["https://westfieldfasteners.co.uk/Standards/ScrewBolt-PoziPan-M.pdf", "https://westfieldfasteners.co.uk/Standards/ScrewBolt-PoziPan-M.html", "https://westfieldfasteners.co.uk/Standards/ScrewBolt-PhilRaPan-M.pdf"],
                   "photo_page": "https://westfieldfasteners.co.uk/A2-ScrewBolt-PoziPan-{SIZE}.html", "terms": "7045|7985|pan"},
}
SKIP_WORDS = ("the", "and", "mah", "cubesat", "battery", "panel", "solar", "fixed", "double", "single", "dual", "patch", "antenna", "imager", "frame", "structure", "series",
              "deployable", "star", "tracker", "sun", "sensor", "camera", "system", "micro", "mini", "fine", "module", "board", "data", "sheet", "with", "standard", "mid", "full", "extension", "network", "array", "stowed", "bare", "cell", "material", "assembly",
              "deg", "head", "unit", "optical", "electrical", "wheel", "reaction", "radio", "package", "gnss", "pec", "...", "thruster", "propulsion", "baseline", "rotor", "heavy", "medium", "active")

rows = []
for module_name in NEW_MODULES:
    try:
        module = importlib.import_module("parts_data." + module_name)
    except ModuleNotFoundError:
        continue
    for record in module.PARTS:
        part_id = record["id"]
        if module_name == "fasteners" and not part_id.startswith(NEW_FASTENER_PREFIXES):
            continue
        folder = os.path.join(CATALOG, record["category"], part_id)
        has_photo = bool(glob.glob(folder + "/reference_photo*.jpg"))
        has_datasheet = bool(glob.glob(folder + "/datasheet*.pdf"))
        if has_photo and has_datasheet:
            continue
        source_url = (record.get("source") or {}).get("url") or ""
        family = None
        for prefix, info in FASTENER_FAMILIES.items():
            if part_id.startswith(prefix):
                family = info
        if family:
            size = part_id[len("set_screw_" if part_id.startswith("set_screw_") else part_id.split("_")[0] + "_"):].split("x")[0].upper().replace("P", ".")
            photo_urls = [family["photo_page"].replace("{SIZE}", size)]
            datasheet_urls = list(family["datasheets"])
            terms = family["terms"]
        else:
            photo_urls = []
            if source_url and not source_url.lower().split("?")[0].endswith(".pdf"):
                photo_urls.append(source_url)
            photo_urls.append("datasheet")
            datasheet_urls = [source_url] if source_url else []
            model = str(record.get("model") or "")
            words = []
            for word in model.replace("(", " ").replace(")", " ").replace(",", " ").replace("/", " ").split():
                if len(word) >= 3 and word.lower() not in SKIP_WORDS:
                    words.append(word.lower())
            words.append(model.lower())
            terms = "|".join(dict.fromkeys(word for word in words if word))
            if not terms:
                terms = str(record.get("vendor") or "").split()[0].lower()
        rows.append({"part_id": part_id, "category": record["category"], "need_photo": "no" if has_photo else "yes", "photo_urls": " | ".join(photo_urls),
                     "need_datasheet": "no" if has_datasheet else "yes", "datasheet_urls": " | ".join(datasheet_urls), "must_terms": terms})

writer = csv.DictWriter(open("pass7.csv", "w", newline="", encoding="utf-8"), fieldnames=list(rows[0].keys()))
writer.writeheader()
writer.writerows(rows)
print(len(rows), "rows;", sum(1 for row in rows if row["need_photo"] == "yes"), "photos;", sum(1 for row in rows if row["need_datasheet"] == "yes"), "datasheets")
