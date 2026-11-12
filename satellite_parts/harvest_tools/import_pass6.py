"""Turns vetted pass 6 harvest rows into catalog parts.
    python3 import_pass6.py <harvest folder> <reject list file>
Writes parts_data/harvest_2026_11_11.json (records read by parts_data/harvest_2026_11_11.py) and copies each part's datasheet page,
datasheet text and photo into staging (_harvest_files/<id>/), which copy_harvest_files() puts into the part folders after generation."""
import os
import re
import sys
import csv
import json
import shutil

ROOT = sys.argv[1]
REJECT = set(line.split("#")[0].strip() for line in open(sys.argv[2], encoding="utf-8") if line.split("#")[0].strip())
CATALOG = "/home/claude/nb/satellite_parts"
STAGING = os.path.join(CATALOG, "_harvest_files")

TYPE_MAP = {
    "star tracker": ("adcs", "star_tracker"), "sun sensor": ("adcs", "sun_sensor"), "earth/horizon sensor": ("adcs", "earth_sensor"), "magnetometer": ("adcs", "magnetometer"),
    "magnetorquer": ("adcs", "magnetorquer"), "reaction wheel": ("adcs", "reaction_wheel"), "cmg": ("adcs", "cmg"), "imu/iru": ("adcs", "imu"), "gnss/gps receiver": ("adcs", "gnss_receiver"),
    "acs/acds system": ("adcs", "integrated_adcs"), "on-board computer": ("avionics", "obc"), "cdh other": ("avionics", "payload_processor"), "atomic clock": ("avionics", "clock"),
    "processor": ("avionics", "processor"), "memory": ("avionics", "memory"), "transceiver": ("comms", "transceiver"), "transmitter": ("comms", "transmitter"), "receiver": ("comms", "receiver"),
    "transponder": ("comms", "transponder"), "sdr": ("comms", "sdr"), "microstrip antenna": ("comms", "antenna"), "wire antenna": ("comms", "antenna"), "aperture antenna": ("comms", "antenna"),
    "eps/pcdu": ("power", "eps"), "primary battery": ("power", "battery"), "secondary battery": ("power", "battery"), "solar panel": ("power", "solar_panel"), "solar cell": ("power", "solar_cell"),
    "camera/imager": ("payload", "imager"), "electric propulsion thruster": ("propulsion", "electric_thruster"), "electric propulsion system": ("propulsion", "electric_thruster"),
    "monopropellant thruster": ("propulsion", "thruster"), "cold gas thruster": ("propulsion", "thruster"), "tank": ("propulsion", "tank"), "valve": ("propulsion", "valve"),
    "mechanism": ("mechanisms", "mechanism"), "other": ("thermal", "thermal_control_unit"),
    "optical comm": ("comms", "optical_terminal"), "cold gas system": ("propulsion", "cold_gas_module"), "avionics package": ("avionics", "avionics_package"),
}
CATEGORY_BLOCK = {"adcs": "adcs", "avionics": "electrical", "comms": "rf", "power": "electrical", "payload": "payload", "propulsion": "propulsion", "mechanisms": "mechanism", "thermal": "thermal"}


def shape_for(category, subcategory, x, y, z):
    footprint = sorted((x, y))
    if subcategory == "reaction_wheel":
        return {"kind": "reaction_wheel", "x": x, "y": y, "z": z}
    if subcategory == "sun_sensor" and max(x, y, z) < 70:
        return {"kind": "sun_sensor", "x": x, "y": y, "z": z}
    if subcategory == "antenna" and z < 0.25 * min(x, y):
        return {"kind": "patch_antenna", "x": x, "y": y, "z": z}
    if 85 <= footprint[0] <= 97 and 88 <= footprint[1] <= 100 and z <= 40:
        return {"kind": "pc104_board", "x": x, "y": y, "z": 1.6, "components_height": round(z - 1.6, 2)}
    return {"kind": "module_box", "x": x, "y": y, "z": z}


def model_from(row):
    text = open(os.path.join(ROOT, "pass6", row["slug"], "datasheet.txt"), encoding="utf-8", errors="ignore").read()[:600]
    name = row["name"].strip()
    head = re.sub(r"\s+", " ", text).strip()
    return name, head


PAGE_MASS_ACCEPT = set(line.strip() for line in open(sys.argv[3], encoding="utf-8") if line.strip()) if len(sys.argv) > 3 else set()
rows = [row for row in csv.DictReader(open(os.path.join(ROOT, "pass6_vetted.csv"), encoding="utf-8")) if (row["verdict"] == "accept" or row["slug"] in PAGE_MASS_ACCEPT) and row["slug"] not in REJECT]
for row in rows:
    if row["slug"] in PAGE_MASS_ACCEPT:
        match = re.search(r"([\d.]+)\s*(kg|g)\b", row["page_mass"])
        row["mass_g"] = str(float(match.group(1)) * (1000.0 if match.group(2) == "kg" else 1.0))
        row["mass_context"] = "mass from the catalog page (" + row["page_mass"] + "); the data sheet text gave no parsable mass"
index = {row["slug"]: row for row in csv.DictReader(open(os.path.join(ROOT, "pass6_index.csv"), encoding="utf-8"))}
records = []
os.makedirs(STAGING, exist_ok=True)
for row in rows:
    kind = row["type"].strip().lower()
    KEYWORDS = (("antenna", "microstrip antenna"), ("magnetorquer", "magnetorquer"), ("power condition", "eps/pcdu"), ("data acquisition", "on-board computer"), ("on-board comput", "on-board computer"),
                ("gnss", "gnss/gps receiver"), ("camera", "camera/imager"), ("laser rangefin", "mechanism"), ("transmitter", "transmitter"), ("integrated adc", "acs/acds system"),
                ("integrated com", "transceiver"), ("reaction wheel", "reaction wheel"), ("star tracker", "star tracker"), ("integrated sat", "on-board computer"), ("telecom other", "transceiver"),
                ("satellite and", "secondary battery"), ("battery", "secondary battery"), ("magnetometer", "magnetometer"), ("thrust contro", "eps/pcdu"), ("power conditi", "eps/pcdu"), ("power convers", "eps/pcdu"), ("electrical po", "eps/pcdu"),
                ("electrical an", "on-board computer"), ("transition mo", "on-board computer"), ("deployable sy", "mechanism"), ("satellite dep", "mechanism"), ("transmitters", "transmitter"), ("transceivers", "transceiver"),
                ("gyroscope", "imu/iru"), ("low noise", "transceiver"), ("transponders", "transponder"), ("frequency syn", "transceiver"), ("automatic ide", "receiver"), ("automatic dep", "receiver"),
                ("satellite cam", "camera/imager"), ("earth sensor", "earth/horizon sensor"), ("waveguide swi", "on-board computer"), ("sun sensor", "sun sensor"), ("on-board comp", "on-board computer"))
    if kind not in TYPE_MAP:
        for word, mapped in KEYWORDS:
            if word in kind:
                kind = mapped
                break
    if kind not in TYPE_MAP:
        print("skip (type not mapped):", row["slug"], row["type"])
        continue
    category, subcategory = TYPE_MAP[kind]
    x, y, z = [float(value) for value in row["dims_mm"].split(" x ")]
    mass = float(row["mass_g"])
    vendor = row["vendor"].strip()
    name = row["name"].strip()
    part_id = re.sub(r"[^a-z0-9]+", "_", (vendor.split()[0] + "_" + name).lower()).strip("_")[:60]
    page_url = index[row["slug"]]["url"]
    sheet_url = index[row["slug"]]["datasheet"].split("?")[0]
    notes = "Read from the vendor data sheet (" + sheet_url.rsplit("/", 1)[-1] + "): dimensions \"" + re.sub(r"\s+", " ", row["dims_context"]).strip()[-110:] + "\"; mass \"" + re.sub(r"\s+", " ", row["mass_context"]).strip()[:90] + "\". Catalog page lists " + (row["page_mass"] or "no mass") + "."
    record = {"id": part_id, "name": vendor + " " + name, "category": category, "subcategory": subcategory, "vendor": vendor, "model": name,
              "dimensions_mm": {"x": x, "y": y, "z": z}, "mass_g": mass, "shape": shape_for(category, subcategory, x, y, z),
              "source": {"type": "datasheet", "url": sheet_url, "document": {"title": vendor + " " + name + " data sheet", "revision": None, "date": None}, "accessed": "2026-11-11",
                         "fields_from_source": ["dimensions_mm", "mass_g"], "notes": notes, "found_via": page_url},
              "status": "in_production", "fidelity": "envelope", "distributors": ["direct"], "cost": {"value": None, "currency": "USD", "basis": "quote", "source": None},
              "harvest_slug": row["slug"]}
    if row["mass_bound"] in ("<", "≤"):
        record["mass_note"] = "upper bound stated by the data sheet"
    page_lines = [line.strip() for line in open(os.path.join(ROOT, "pass6", "_page__" + row["slug"] + ".txt"), encoding="utf-8", errors="ignore")]
    for line_number, line in enumerate(page_lines[:-1]):
        if line == "Average Power":
            power = re.match(r"([\d.]+)\s*W", page_lines[line_number + 1])
            if power:
                record["electrical"] = {"power_W": {"nominal": float(power.group(1))}, "note": "average power from the catalog page"}
        if line == "Heritage" and page_lines[line_number + 1] in ("Yes", "No"):
            record["flight_heritage"] = page_lines[line_number + 1] == "Yes"
    records.append(record)
    folder = os.path.join(STAGING, part_id)
    os.makedirs(folder, exist_ok=True)
    source_folder = os.path.join(ROOT, "pass6", row["slug"])
    for name_in, name_out in (("datasheet_page1.png", "datasheet_h_1_page1.png"), ("datasheet.txt", "datasheet_h_1.txt"), ("photo.jpg", "reference_photo.jpg")):
        if os.path.exists(os.path.join(source_folder, name_in)):
            shutil.copy(os.path.join(source_folder, name_in), os.path.join(folder, name_out))
    open(os.path.join(folder, "datasheet_h_1_source.txt"), "w", encoding="utf-8").write("url: " + sheet_url + "\nfound from: " + page_url + "\ndownloaded on the lab laptop by harvest_catalogs.py (pass 6) on 2026-11-11\n")
    if os.path.exists(os.path.join(source_folder, "photo.jpg")):
        how = open(os.path.join(source_folder, "photo_source.txt"), encoding="utf-8").read().strip() if os.path.exists(os.path.join(source_folder, "photo_source.txt")) else "product image on " + page_url
        open(os.path.join(folder, "photo_origin.txt"), "w", encoding="utf-8").write("url: " + (index[row["slug"]].get("image") or sheet_url) + "\nmethod: " + how + "\n")

ids = [record["id"] for record in records]
assert len(ids) == len(set(ids)), "duplicate ids"
json_path = os.path.join(CATALOG, "parts_data", "harvest_2026_11_11.json")
if os.path.exists(json_path):
    kept = json.load(open(json_path, encoding="utf-8"))
    kept_ids = set(record["id"] for record in kept)
    records = kept + [record for record in records if record["id"] not in kept_ids]
json.dump(records, open(json_path, "w", encoding="utf-8"), indent=1)
print(len(records), "records written;", sum(1 for record in records if os.path.exists(os.path.join(STAGING, record["id"], "reference_photo.jpg"))), "with photo")
