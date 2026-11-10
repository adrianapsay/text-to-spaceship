"""Writes catalog_images.html: one row per part with the STL preview, the supplier photo and the datasheet page when present, plus key fields. Open it in a browser."""
import os
import csv
import json
import html

HERE = os.path.dirname(os.path.abspath(__file__))
rows = list(csv.DictReader(open(os.path.join(HERE, "catalog.csv"))))
cells = []
for row in rows:
    folder = os.path.join(HERE, row["category"], row["id"])
    photo = next((name for name in ("reference_photo.jpg", "reference_photo.png", "reference_photo.webp", "reference_photo.jpeg") if os.path.exists(os.path.join(folder, name))), None)
    datasheet = "datasheet_page1.png" if os.path.exists(os.path.join(folder, "datasheet_page1.png")) else None
    record = json.load(open(os.path.join(folder, "part.json")))
    images = "<img src='" + row["category"] + "/" + row["id"] + "/preview.png' title='STL preview'>"
    images += "<img src='" + row["category"] + "/" + row["id"] + "/" + photo + "' title='supplier photo'>" if photo else "<span class='missing'>no photo</span>"
    images += "<img src='" + row["category"] + "/" + row["id"] + "/" + datasheet + "' title='datasheet page 1'>" if datasheet else "<span class='missing'>no datasheet</span>"
    facts = html.escape(row["vendor"] + " " + row["model"]) + "<br>" + row["x_mm"] + " x " + row["y_mm"] + " x " + row["z_mm"] + " mm, " + row["mass_g"] + " g<br>source: " + row["source_type"] + " <a href='" + html.escape(row["source_url"]) + "'>link</a>"
    cells.append("<div class='part'><h3>" + html.escape(row["id"]) + "</h3><div class='images'>" + images + "</div><div class='facts'>" + facts + "</div></div>")
page = "<!doctype html><meta charset='utf-8'><title>satellite_parts catalog</title><style>body{font-family:sans-serif;margin:16px}.part{border-bottom:1px solid #ddd;padding:8px 0;display:grid;grid-template-columns:220px 1fr 1fr;gap:8px;align-items:center}.images img{height:150px;margin-right:6px;border:1px solid #eee}.missing{display:inline-block;width:150px;height:150px;line-height:150px;text-align:center;color:#999;border:1px dashed #ccc;margin-right:6px}h3{margin:0;font-size:14px}.facts{font-size:13px}</style><h1>satellite_parts (" + str(len(rows)) + " parts)</h1>" + "".join(cells)
open(os.path.join(HERE, "catalog_images.html"), "w").write(page)
print("catalog_images.html written")
