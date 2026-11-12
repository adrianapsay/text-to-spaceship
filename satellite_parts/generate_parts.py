"""
Builds the part library: for every record in parts_data/*.py writes <category>/<id>/part.step, part.stl (and _deployed variants), part.json,
then catalog.csv, downloads.csv and needs_verification.csv.

    python generate_parts.py                 (all)
    python generate_parts.py --only power    (one category module)
"""

import os
import re
import sys
import csv
import json
import glob
import time
import argparse
import importlib
import numpy as np
import build123d as b
import trimesh
import shapes
import shapes_detail
from parts_data._references import REFERENCES
from parts_data._detail_shapes import DETAIL_SHAPES

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
parser = argparse.ArgumentParser()
parser.add_argument("--only", nargs="*", default=None)
parser.add_argument("--tolerance", type=float, default=0.15, help="STL tessellation tolerance mm (bigger = fewer faces)")
parser.add_argument("--render", action="store_true", help="also write preview.png per part (needs pyvista; run under xvfb-run on a headless machine)")
parser.add_argument("--envelope-preview", action="store_true", help="render preview.png from the envelope instead of the detail geometry")
arguments = parser.parse_args()

modules = sorted(os.path.basename(path)[:-3] for path in glob.glob(os.path.join(HERE, "parts_data", "*.py")) if not os.path.basename(path).startswith("_"))
if arguments.only:
    modules = [name for name in modules if name in arguments.only]

def render_preview(folder, stems, body_lists):
    """preview.png: one subplot per geometry (stowed, deployed), bodies in their colors, isometric view."""
    import pyvista
    pyvista.OFF_SCREEN = True
    plotter = pyvista.Plotter(off_screen=True, window_size=[480, 360], shape=(1, len(stems)), lighting="three lights")
    for number, stem in enumerate(stems):
        plotter.subplot(0, number)
        plotter.set_background("white")
        extent = None
        for body_name, color, body_path in body_lists[stem]:
            mesh = trimesh.load(body_path)
            if len(mesh.faces) == 0:
                continue
            faces = np.hstack([np.full((len(mesh.faces), 1), 3), mesh.faces]).ravel()
            plotter.add_mesh(pyvista.PolyData(np.asarray(mesh.vertices), faces), color=color, smooth_shading=True, split_sharp_edges=True, feature_angle=35, show_edges=False, specular=0.3)
        whole = trimesh.load(os.path.join(folder, (stem if stem in ("part", "part_deployed") else "part") + ".stl"))
        extent = whole.bounds[1] - whole.bounds[0]
        plotter.add_text(("deployed  " if stem.endswith("deployed") else "") + " x ".join(format(v, ".1f") for v in extent) + " mm", position="lower_left", font_size=8, color="#444444")
        plotter.view_isometric()
        plotter.camera.elevation = 12
        plotter.camera.azimuth = -20
        plotter.show_axes()
    plotter.screenshot(os.path.join(folder, "preview.png"))
    plotter.close()


# Rendering style by category for plain boxes: electronics modules get a lid and connector (same envelope); stock and generic parts stay plain.
MODULE_CATEGORIES = ("adcs", "avionics", "comms", "power", "propulsion", "payload", "mechanisms")


def styled_spec(record, spec):
    spec = dict(spec)
    if spec.get("kind") == "box" and record["category"] in MODULE_CATEGORIES and record.get("vendor", "generic") != "generic" and min(spec["x"], spec["y"], spec["z"]) >= 6:
        spec["kind"] = "module_box"
    if spec.get("kind") == "box" and record.get("subcategory") == "heater":
        spec["kind"] = "heater_foil"
    if spec.get("kind") == "box" and record.get("subcategory") == "thermal_strap":
        spec["kind"] = "thermal_strap"
    if spec.get("kind") == "box" and record.get("subcategory") == "connector":
        spec["kind"] = "connector_block"
    if spec.get("kind") == "box" and record.get("subcategory") == "sun_sensor":
        spec["kind"] = "sun_sensor"
    if spec.get("kind") == "box" and record.get("subcategory") == "solar_cell":
        spec["kind"] = "solar_cell"
    if spec.get("kind") in ("box", "module_box") and record.get("subcategory") in ("battery", "battery_pack") and spec["x"] >= 70 and spec["y"] >= 40 and spec["z"] >= 20:
        spec["kind"] = "battery_pack"
        spec["cells"] = (1, max(1, min(8, int((spec["y"] - 4) // 20))))
    if spec.get("kind") in ("box", "module_box") and record.get("subcategory") == "antenna" and "shape_deployed" in record:
        spec["kind"] = "tape_antenna_stowed"
        spec["base_x"], spec["base_y"], spec["base_z"] = spec["x"], spec["y"], spec["z"]
    return spec


catalog_rows = []
verification_rows = []
download_rows = []
reference_rows = []
started = time.perf_counter()
seen_ids = set()
for module_name in modules:
    module = importlib.import_module("parts_data." + module_name)
    for record in module.PARTS:
        part_id = record["id"]
        if part_id in seen_ids:
            raise SystemExit("duplicate part id: " + part_id + " in " + module_name)
        seen_ids.add(part_id)
        category = record["category"]
        folder = os.path.join(HERE, category, part_id)
        os.makedirs(folder, exist_ok=True)
        geometries = {"part": record["shape"]}
        if "shape_deployed" in record:
            geometries["part_deployed"] = record["shape_deployed"]
        face_counts = {}
        body_lists = {}
        bodies_folder = os.path.join(folder, "bodies")
        os.makedirs(bodies_folder, exist_ok=True)
        for file_stem, shape_spec in geometries.items():
            spec = styled_spec(record, shape_spec)
            spec_kind = spec["kind"]
            tolerance = spec.get("tolerance", arguments.tolerance)
            fused, body_list = shapes.build(spec)
            compound_children = []
            for body_name, color, body in body_list:
                body.label = body_name
                body.color = b.Color(*color)
                compound_children.append(body)
            assembly = b.Compound(children=compound_children, label=part_id)
            b.export_step(assembly, os.path.join(folder, file_stem + ".step"))
            b.export_stl(fused, os.path.join(folder, file_stem + ".stl"), tolerance=tolerance, angular_tolerance=0.3)
            body_lists[file_stem] = []
            for body_name, color, body in body_list:
                body_path = os.path.join(bodies_folder, file_stem + "__" + body_name + ".stl")
                b.export_stl(body, body_path, tolerance=tolerance, angular_tolerance=0.3)
                body_lists[file_stem].append((body_name, color, body_path))
            mesh = trimesh.load(os.path.join(folder, file_stem + ".stl"))
            if not mesh.is_watertight:
                mesh.merge_vertices()
                trimesh.repair.fill_holes(mesh)
                mesh.export(os.path.join(folder, file_stem + ".stl"))
                mesh = trimesh.load(os.path.join(folder, file_stem + ".stl"))
            if not mesh.is_watertight and spec_kind == "sphere":
                mesh = trimesh.creation.icosphere(subdivisions=3, radius=spec["diameter"] / 2.0)
                mesh.export(os.path.join(folder, file_stem + ".stl"))
                mesh = trimesh.load(os.path.join(folder, file_stem + ".stl"))
            face_counts[file_stem] = int(len(mesh.faces))
            if file_stem == "part":
                bounds = mesh.bounds
                measured = (bounds[1] - bounds[0]).round(2).tolist()
                record.setdefault("geometry", {})["measured_bbox_mm"] = measured
                record["geometry"]["mesh_volume_mm3"] = round(float(mesh.volume), 1)
                record["geometry"]["watertight"] = bool(mesh.is_watertight)
                record["geometry"]["render_kind"] = spec_kind
                if record.get("mass_g") and mesh.volume > 0:
                    record["geometry"]["effective_density_g_cm3"] = round(record["mass_g"] / (mesh.volume / 1000.0), 3)
            else:
                record["geometry"]["deployed_measured_bbox_mm"] = (mesh.bounds[1] - mesh.bounds[0]).round(2).tolist()
        record["geometry"]["bodies"] = {stem: [{"name": body_name, "color": [round(c, 3) for c in color], "file": "bodies/" + os.path.basename(body_path)} for body_name, color, body_path in body_lists[stem]] for stem in body_lists}
        record["geometry"]["face_counts"] = face_counts
        # Detail level (shapes_detail.py): visible features, all inside the envelope. Packing uses part.stl (the envelope); detail.stl is for looks and fine checks.
        if part_id in DETAIL_SHAPES:
            record["detail_shape"] = DETAIL_SHAPES[part_id]
        detail_list = shapes_detail.detail_bodies(record, styled_spec(record, record["shape"]))
        detail_folder = os.path.join(folder, "bodies_detail")
        os.makedirs(detail_folder, exist_ok=True)
        for old_file in glob.glob(os.path.join(detail_folder, "*.stl")):
            os.remove(old_file)
        if detail_list is None:
            detail_paths = [(body_name, color, body_path) for body_name, color, body_path in body_lists["part"]]
            record["geometry"]["detail"] = {"same_as_envelope": True, "bodies": record["geometry"]["bodies"]["part"]}
        else:
            detail_fused = None
            for body_name, color, body in detail_list:
                detail_fused = body if detail_fused is None else detail_fused + body
            envelope_bbox = trimesh.load(os.path.join(folder, "part.stl")).bounds
            detail_box = detail_fused.bounding_box()
            detail_size = np.array([detail_box.max.X - detail_box.min.X, detail_box.max.Y - detail_box.min.Y, detail_box.max.Z - detail_box.min.Z])
            shift = b.Pos(-(detail_box.min.X + detail_box.max.X) / 2 + (envelope_bbox[0][0] + envelope_bbox[1][0]) / 2, -(detail_box.min.Y + detail_box.max.Y) / 2 + (envelope_bbox[0][1] + envelope_bbox[1][1]) / 2, -(detail_box.min.Z + detail_box.max.Z) / 2 + (envelope_bbox[0][2] + envelope_bbox[1][2]) / 2)
            detail_paths = []
            children = []
            for body_name, color, body in detail_list:
                body = shift * body
                body_path = os.path.join(detail_folder, body_name + ".stl")
                b.export_stl(body, body_path, tolerance=min(arguments.tolerance, 0.1), angular_tolerance=0.15)
                detail_paths.append((body_name, color, body_path))
                body.label = body_name
                body.color = b.Color(*color)
                children.append(body)
            b.export_step(b.Compound(children=children, label=part_id + "_detail"), os.path.join(folder, "detail.step"))
            envelope_size = envelope_bbox[1] - envelope_bbox[0]
            overshoot = (detail_size - envelope_size).round(2)
            record["geometry"]["detail"] = {"same_as_envelope": False, "measured_bbox_mm": detail_size.round(2).tolist(), "inside_envelope": bool((overshoot <= 0.5).all()), "overshoot_mm": [max(0.0, float(value)) for value in overshoot],
                                            "bodies": [{"name": body_name, "color": [round(c, 3) for c in color], "file": "bodies_detail/" + os.path.basename(body_path)} for body_name, color, body_path in detail_paths], "step": "detail.step"}
        if arguments.render:
            if arguments.envelope_preview or "part_deployed" in geometries:
                render_preview(folder, list(geometries.keys()), body_lists)
            else:
                render_preview(folder, ["detail"], {"detail": detail_paths})
            record["image"] = "preview.png"
        # Interfaces: structured block for compatibility checks (buses, connectors, mechanical). Data buses are parsed from electrical.interfaces when not given explicitly.
        buses = set()
        for text in (record.get("electrical") or {}).get("interfaces", []) or []:
            for bus in ("I2C", "CAN", "SPI", "UART", "RS-422", "RS-485", "USB", "Ethernet", "PPS", "GPIO", "PWM", "ADC", "JTAG", "CSP"):
                if bus.lower() in str(text).lower():
                    buses.add(bus)
        interfaces = dict(record.get("interfaces") or {})
        interfaces.setdefault("data_buses", sorted(buses))
        interfaces.setdefault("mechanical", (record.get("mounting") or {}).get("pattern") or ("PC/104 stack" if "PC/104" in " ".join(str(t) for t in (record.get("electrical") or {}).get("interfaces", []) or []) or (record.get("shape") or {}).get("kind") == "pc104_board" else None))
        interfaces.setdefault("electrical_connectors", record.get("connectors") or [])
        interfaces.setdefault("rf_connectors", record.get("rf_connectors") or [])
        interfaces.setdefault("power_bus_V", ((record.get("electrical") or {}).get("voltage_V") or {}).get("nominal"))
        record["interfaces"] = interfaces
        # Reference images: supplier/marketplace photo (by id or longest id prefix) plus the datasheet PDF when the source url is a PDF.
        reference_key = max((key for key in REFERENCES if part_id == key or part_id.startswith(key)), key=len, default=None)
        reference = dict(REFERENCES[reference_key]) if reference_key else {}
        source_url = (record.get("source") or {}).get("url", "") or ""
        datasheet_url = reference.get("datasheet") or (source_url if source_url.lower().split("?")[0].endswith(".pdf") else None)
        photo_present = os.path.exists(os.path.join(folder, "reference_photo.jpg"))
        datasheet_present = os.path.exists(os.path.join(folder, "datasheet_page1.png"))
        photo_note_path = os.path.join(folder, "photo_source.txt")
        datasheets = []
        if datasheet_present:
            datasheets.append({"file": "datasheet_page1.png", "pdf": "datasheet.pdf" if os.path.exists(os.path.join(folder, "datasheet.pdf")) else None, "url": datasheet_url, "kind": "vendor_link", "title": (record.get("source") or {}).get("document", {}).get("title")})
        for name in sorted(os.listdir(folder)):
            match = re.match(r"datasheet_(\d+)_page1\.png$", name)
            if not match:
                continue
            source_path = os.path.join(folder, "datasheet_" + match.group(1) + "_source.txt")
            info = {"file": name, "pdf": "datasheet_" + match.group(1) + ".pdf", "kind": "web_search", "url": None, "title": None}
            if os.path.exists(source_path):
                for line in open(source_path, encoding="utf-8"):
                    if line.startswith("url: "):
                        info["url"] = line[5:].strip()
                    if line.startswith("title: "):
                        info["title"] = line[7:].strip()
            datasheets.append(info)
        record["reference_images"] = {"datasheets": datasheets, "stl_preview": "preview.png" if os.path.exists(os.path.join(folder, "preview.png")) else None, "drawing": "drawing.png" if os.path.exists(os.path.join(folder, "drawing.png")) else None, "photo_url": reference.get("photo"), "photo_source": reference.get("photo_source"), "photo_page": reference.get("page"), "photo_file": "reference_photo.jpg" if photo_present else None, "photo_kind": ("web_search_representative" if os.path.exists(photo_note_path) else "vendor_or_marketplace") if photo_present else None, "datasheet_url": datasheet_url, "datasheet_page_file": "datasheet_page1.png" if datasheet_present else None, "note": "reference_photo.jpg and datasheet_page1.png are downloaded by fetch_reference_images.py on a machine with web access; drawing.png by make_drawings.py"}
        reference_rows.append([part_id, category, reference.get("photo") or "", reference.get("photo_source") or "", reference.get("page") or "", datasheet_url or ""])
        output = {key: value for key, value in record.items() if key not in ("shape", "shape_deployed", "detail_shape", "connectors", "rf_connectors")}
        output["files"] = {stem: [stem + ".step", stem + ".stl"] for stem in geometries}
        json.dump(output, open(os.path.join(folder, "part.json"), "w"), indent=1)
        dims = record.get("dimensions_mm", {})
        source = record.get("source", {})
        catalog_rows.append([part_id + "/preview.png" if arguments.render else "", part_id, category, record.get("subcategory", ""), record.get("name", ""), record.get("vendor", ""), record.get("model", ""), record.get("status", ""), dims.get("x", ""), dims.get("y", ""), dims.get("z", ""), record.get("mass_g", ""), record.get("material", ""), source.get("type", ""), source.get("url", ""), record.get("first_available_year", ""), (record.get("cost") or {}).get("value", ""), face_counts.get("part", "")])
        flags = []
        if source.get("type") in ("unverified", "derived"):
            flags.append("source " + source.get("type"))
        for field in ("mass_note", "dimensions_note", "cost_note"):
            if record.get(field) and any(word in str(record[field]).lower() for word in ("derived", "estimate", "unverified", "assumed", "approximate", "memory")):
                flags.append(field.replace("_note", "") + " " + str(record[field]))
        if flags:
            verification_rows.append([part_id, "; ".join(flags), source.get("notes", "")])
        for link in record.get("cad_downloads", []):
            download_rows.append([part_id, record.get("vendor", ""), link.get("format", ""), link.get("url", ""), link.get("notes", "")])
        print(module_name.ljust(12) + part_id.ljust(40) + str(face_counts), flush=True)

previous_ids = set()
if os.path.exists(os.path.join(HERE, "catalog.csv")) and not arguments.only:
    previous_ids = set(row["id"] for row in csv.DictReader(open(os.path.join(HERE, "catalog.csv"))))
removed_ids = sorted(previous_ids - set(row[1] for row in catalog_rows))
if removed_ids:
    print("WARNING removed since last full build: " + ", ".join(removed_ids))
with open(os.path.join(HERE, "catalog.csv"), "w", newline="") as catalog_file:
    writer = csv.writer(catalog_file)
    writer.writerow(["image", "id", "category", "subcategory", "name", "vendor", "model", "status", "x_mm", "y_mm", "z_mm", "mass_g", "material", "source_type", "source_url", "first_available_year", "cost", "faces"])
    writer.writerows(catalog_rows)
with open(os.path.join(HERE, "needs_verification.csv"), "w", newline="") as verification_file:
    writer = csv.writer(verification_file)
    writer.writerow(["id", "flags", "source_notes"])
    writer.writerows(verification_rows)
with open(os.path.join(HERE, "downloads.csv"), "w", newline="") as download_file:
    writer = csv.writer(download_file)
    writer.writerow(["part_id", "vendor", "format", "url", "notes"])
    writer.writerows(download_rows)
with open(os.path.join(HERE, "references.csv"), "w", newline="") as reference_file:
    writer = csv.writer(reference_file)
    writer.writerow(["part_id", "category", "photo_url", "photo_source", "photo_page", "datasheet_url"])
    writer.writerows(reference_rows)
print(str(sum(1 for row in reference_rows if row[2])) + " photo links, " + str(sum(1 for row in reference_rows if row[5])) + " datasheet links")
print(str(len(catalog_rows)) + " parts in " + format(time.perf_counter() - started, ".0f") + " s; " + str(len(verification_rows)) + " need verification; " + str(len(download_rows)) + " CAD links")
