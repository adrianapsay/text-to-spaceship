"""
Builds catalog_explorer.html: a self-contained page with every part (facts, STL thumbnail, 3D mesh, photo and datasheet links, similar parts).
    python make_catalog_explorer.py
"""
import os
import io
import csv
import json
import base64
import numpy as np
import trimesh
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
rows = list(csv.DictReader(open(os.path.join(HERE, "catalog.csv"))))
parts = []
meshes = {}
for row in rows:
    folder = os.path.join(HERE, row["category"], row["id"])
    record = json.load(open(os.path.join(folder, "part.json")))
    def mesh_entry(path, color=None):
        mesh = trimesh.load(path)
        if len(mesh.faces) > 1200:
            try:
                mesh = mesh.simplify_quadric_decimation(face_count=1200)
            except Exception:
                pass
        entry = {"v": np.asarray(mesh.vertices, dtype=float).round(2).ravel().tolist(), "f": np.asarray(mesh.faces, dtype=int).ravel().tolist()}
        if color is not None:
            entry["c"] = color
        return entry
    bodies = (record.get("geometry") or {}).get("bodies") or {}
    for stem, key in (("part", row["id"]), ("part_deployed", row["id"] + "__deployed")):
        stem_path = os.path.join(folder, stem + ".stl")
        if not os.path.exists(stem_path):
            continue
        body_entries = []
        for body in bodies.get(stem, []):
            body_path = os.path.join(folder, body["file"])
            if os.path.exists(body_path):
                body_entries.append(mesh_entry(body_path, body["color"]))
        if body_entries:
            meshes[key] = {"bodies": body_entries}
        else:
            meshes[key] = mesh_entry(stem_path)
    deployed_path = os.path.join(folder, "part_deployed.stl")
    thumbnail = ""
    preview_path = os.path.join(folder, "preview.png")
    if os.path.exists(preview_path):
        image = Image.open(preview_path).convert("RGB")
        image.thumbnail((260, 200))
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=70)
        thumbnail = "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode()
    record["thumbnail"] = thumbnail
    def embed(path, size, quality):
        if not os.path.exists(path):
            return ""
        image = Image.open(path).convert("RGB")
        image.thumbnail(size)
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=quality)
        return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode()
    record["photo"] = embed(os.path.join(folder, "reference_photo.jpg"), (280, 280), 62)
    record["datasheet_image"] = ""
    record["datasheet_images"] = []
    for sheet in (record.get("reference_images") or {}).get("datasheets", []):
        image = embed(os.path.join(folder, sheet["file"]), (200, 270), 45)
        if image:
            record["datasheet_images"].append({"image": image, "url": sheet.get("url"), "title": sheet.get("title"), "kind": sheet.get("kind")})
    record["drawing"] = embed(os.path.join(folder, "drawing.png"), (330, 115), 60) if not record["photo"] else ""
    record["photo_note"] = open(os.path.join(folder, "photo_source.txt")).read() if os.path.exists(os.path.join(folder, "photo_source.txt")) else ""
    record["has_deployed"] = os.path.exists(deployed_path)
    parts.append(record)

payload = json.dumps({"parts": parts, "meshes": meshes}, separators=(",", ":"))
template = open(os.path.join(HERE, "catalog_explorer_template.html")).read()
page = template.replace("/*__DATA__*/", payload)
open(os.path.join(HERE, "catalog_explorer.html"), "w").write(page)
print(str(len(parts)) + " parts, " + format(len(page) / 1e6, ".1f") + " MB")
